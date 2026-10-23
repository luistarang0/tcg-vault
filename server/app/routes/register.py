"""
POST /api/register: crea la cuenta de coleccionista.

Al registrarse el usuario recibe STARTING_POINTS puntos y un sobre inicial de
STARTER_PACK_SIZE cartas, y queda con la sesión iniciada. Como ahora una cuenta
tiene valor (puntos y cartas), las defensas evitan granjas de cuentas:

  1. Rate limiting (slowapi): RATE_LIMIT_FORMS por IP+sesión y RATE_LIMIT_IP por IP.
  2. Logging de huellas: cada intento queda en logs/access.jsonl (audit.py).
  3. Puntaje de comportamiento: métricas del cliente + honeypot + encabezados (risk.py).
  4. Turnstile: si el puntaje es ≥80 se exige un token validado en el servidor.

La respuesta escalonada vive en security/gate.py (la comparte el login).
La contraseña se guarda solo como hash scrypt y nunca se registra.
"""
import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from pydantic import BaseModel, Field, field_validator
from slowapi.util import get_remote_address
from starlette.concurrency import run_in_threadpool

from app import config, economy as eco
from app.auth import create_session, hash_password
from app.market import add_points, give_starter_pack
from app.pg import get_pg
from app.security.audit import log_event
from app.security.gate import risk_gate
from app.security.ratelimit import limiter

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
# El nombre forma parte de la URL del perfil público (/u/nombre): sin espacios ni símbolos raros
USERNAME_RE = re.compile(r"^[\w.-]{3,24}$")


class RegisterIn(BaseModel):
    """Cuerpo esperado. Pydantic responde 422 automáticamente si algo no cumple."""
    collector_name: str = Field(min_length=3, max_length=40)
    email: str = Field(max_length=120)
    password: str = Field(min_length=8, max_length=128)
    website: str = Field(default="", max_length=200)   # honeypot: debe llegar vacío
    behavior: dict | None = None                       # métricas de useBehaviorTracker
    turnstile_token: str | None = Field(default=None, max_length=4096)

    @field_validator("email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        if not EMAIL_RE.match(v):
            raise ValueError("correo inválido")
        return v.lower()

    @field_validator("collector_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if not USERNAME_RE.match(v):
            raise ValueError("de 3 a 24 letras, números, punto, guion o guion bajo")
        return v


def _crear_cuenta(payload: RegisterIn, response: Response) -> list[str] | None:
    """Inserta usuario, saldo inicial y sobre. None si el nombre o correo ya existen."""
    password_hash = hash_password(payload.password)   # scrypt tarda ~50 ms a propósito
    with get_pg() as conn:
        try:
            with conn.transaction():
                user = conn.execute(
                    # last_bonus = hoy: el bono diario empieza a contar desde mañana
                    "INSERT INTO users (username, email, password_hash, last_bonus) "
                    "VALUES (%s, %s, %s, (now() AT TIME ZONE 'UTC')::date) RETURNING id",
                    (payload.collector_name, payload.email, password_hash),
                ).fetchone()
                add_points(conn, user["id"], eco.STARTING_POINTS, "saldo_inicial")
                cartas = give_starter_pack(conn, user["id"])
                create_session(conn, user["id"], response)
        except pg_errors.UniqueViolation:
            return None
    return cartas


# Los decoradores de slowapi exigen que la función reciba `request: Request`.
@router.post("/register", status_code=201)
@limiter.limit(config.RATE_LIMIT_FORMS)                                # IP + sesión
@limiter.limit(config.RATE_LIMIT_IP, key_func=get_remote_address)      # solo IP
async def register(request: Request, payload: RegisterIn, response: Response):
    bloqueo, riesgo = await risk_gate(request, payload, "register_attempt")
    if bloqueo:
        return bloqueo

    # `response` es la respuesta que FastAPI devolverá: create_session le pone la cookie
    cartas = await run_in_threadpool(_crear_cuenta, payload, response)
    if cartas is None:
        log_event(request, "register_duplicate")
        return JSONResponse(status_code=409, content={
            "ok": False, "error": "Ese nombre de coleccionista o correo ya está registrado."})

    log_event(request, "register_ok", score=riesgo.score)
    return {
        "ok": True,
        "message": f"¡Bienvenido, {payload.collector_name}! Recibiste {eco.STARTING_POINTS} puntos "
                   f"y un sobre con {len(cartas)} cartas.",
        "username": payload.collector_name,
    }
