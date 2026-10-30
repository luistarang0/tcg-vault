"""
Sesión de usuario:
    POST /api/login    inicia sesión (nombre o correo + contraseña)
    POST /api/logout   cierra la sesión (borra el token de la base)
    GET  /api/me       usuario actual, saldo y bono diario; {"user": null} sin sesión

Defensas del login (contra fuerza bruta y relleno de credenciales):
  1. Rate limiting por IP+sesión (RATE_LIMIT_LOGIN) y por IP (RATE_LIMIT_IP).
  2. Límite por CUENTA en Postgres: LOGIN_MAX_FAILS fallos en LOGIN_WINDOW_MIN
     minutos bloquean esa cuenta aunque el atacante cambie de IP.
  3. Puntaje de comportamiento + honeypot y Turnstile escalonado (security/gate.py),
     igual que el registro.
  4. Mensaje de error único ("usuario o contraseña incorrectos") y mismo tiempo de
     respuesta exista o no la cuenta: no se puede averiguar qué nombres existen.
"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import config, economy as eco
from app.auth import DUMMY_HASH, create_session, destroy_session, user_from_request, verify_password
from app.market import frozen_points, grant_daily_bonus, settle_expired
from app.pg import get_pg
from app.security.audit import client_ip, log_event
from app.security.gate import risk_gate
from app.security.ratelimit import key_ip, limiter

router = APIRouter()


class LoginIn(BaseModel):
    username: str = Field(min_length=3, max_length=120)   # nombre de coleccionista o correo
    password: str = Field(min_length=1, max_length=128)
    website: str = Field(default="", max_length=200)      # honeypot
    behavior: dict | None = None
    turnstile_token: str | None = Field(default=None, max_length=4096)


def _login(payload: LoginIn, ip: str, response: Response) -> str:
    """Devuelve 'ok', 'bad' (credenciales) o 'locked' (demasiados fallos en la cuenta)."""
    ident = payload.username.strip()
    with get_pg() as conn:
        fallos = conn.execute(
            "SELECT count(*) AS n FROM login_attempts WHERE lower(username) = lower(%s) AND NOT ok "
            "AND created_at > now() - make_interval(mins => %s)",
            (ident, config.LOGIN_WINDOW_MIN),
        ).fetchone()["n"]
        if fallos >= config.LOGIN_MAX_FAILS and config.should_enforce():
            return "locked"

        user = conn.execute(
            "SELECT id, password_hash, is_admin FROM users WHERE lower(username) = lower(%s) OR lower(email) = lower(%s)",
            (ident, ident),
        ).fetchone()
        # Si no existe se verifica igual contra un hash de relleno (mismo tiempo de respuesta)
        ok = verify_password(payload.password, user["password_hash"] if user else DUMMY_HASH) and user is not None
        conn.execute("INSERT INTO login_attempts (username, ip, ok) VALUES (%s, %s, %s)", (ident, ip, ok))
        if not ok:
            return "bad"
        create_session(conn, user["id"], response)
        if not user["is_admin"]:
            grant_daily_bonus(conn, user["id"])
    return "ok"


@router.post("/login")
@limiter.limit(config.RATE_LIMIT_LOGIN)                                # IP + sesión
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)      # solo IP
async def login(request: Request, payload: LoginIn, response: Response):
    bloqueo, _ = await risk_gate(request, payload, "login_attempt")
    if bloqueo:
        return bloqueo

    resultado = await run_in_threadpool(_login, payload, client_ip(request), response)
    log_event(request, "login_result", result=resultado)
    if resultado == "locked":
        retry = config.LOGIN_WINDOW_MIN * 60
        return JSONResponse(status_code=429, headers={"Retry-After": str(retry)}, content={
            "ok": False, "retry_after": retry,
            "error": "Demasiados intentos fallidos para esta cuenta. Intenta más tarde."})
    if resultado == "bad":
        return JSONResponse(status_code=401, content={
            "ok": False, "error": "Usuario o contraseña incorrectos."})
    return {"ok": True}


@router.post("/logout")
@limiter.limit(config.RATE_LIMIT_LOGIN)
def logout(request: Request, response: Response):
    destroy_session(request, response)
    return {"ok": True}


@router.get("/me")
@limiter.limit(config.RATE_LIMIT_POLL)                                 # se llama en cada carga
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def me(request: Request):
    with get_pg() as conn:
        user = user_from_request(conn, request)
        if user is None:
            return {"user": None, "rules": eco.public_rules()}
        if user["is_admin"]:
            # El administrador solo usa el panel de seguridad: sin puntos, cartas ni bono
            return {"user": {"username": user["username"], "is_admin": True, "points": None,
                             "frozen": None, "bonus_granted": 0}, "rules": eco.public_rules()}
        settle_expired(conn)                      # así el saldo refleja ventas ya vencidas
        bono = grant_daily_bonus(conn, user["id"])
        points = conn.execute("SELECT points FROM users WHERE id = %s", (user["id"],)).fetchone()["points"]
        return {
            "user": {
                "username": user["username"],
                "is_admin": False,
                "points": points,
                "frozen": frozen_points(conn, user["id"]),
                "bonus_granted": bono,
            },
            "rules": eco.public_rules(),
        }
