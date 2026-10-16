"""
POST /api/register: formulario principal de práctica.

NO guarda ningún dato: valida los campos y responde 201. Sobre él actúan
cuatro defensas en capas:

  1. Rate limiting (slowapi): RATE_LIMIT_FORMS por IP+sesión y RATE_LIMIT_IP por IP.
  2. Logging de huellas: cada intento queda en logs/access.jsonl (audit.py).
  3. Puntaje de comportamiento: métricas del cliente + honeypot + encabezados (risk.py).
  4. Turnstile: si el puntaje es ≥80 se exige un token validado en el servidor.

Respuesta escalonada (solo en SECURITY_MODE=enforce):
  0-29   201 permitido
  30-59  201 permitido, queda registrado
  60-79  429 Too Many Requests + Retry-After (frenar)
  80-100 403 con challenge_required; se acepta solo con token Turnstile válido
En observe se calcula y registra todo, pero siempre se responde 201.
"""
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from slowapi.util import get_remote_address

from app import config
from app.security.audit import client_ip, log_event
from app.security.ratelimit import limiter
from app.security.risk import score_request
from app.security.turnstile import verify_turnstile

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


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
        return v.strip()


def _behavior_resumen(b: dict | None) -> dict:
    """Solo las métricas numéricas que se guardan en el log (nada de datos personales)."""
    if not isinstance(b, dict):
        return {}
    claves = ["fillTimeMs", "keyCount", "keyIntervalMeanMs", "keyIntervalStdMs", "mouseMoves",
              "totalEvents", "trustedEvents", "webdriver", "pluginsLength", "languagesLength"]
    return {k: b.get(k) for k in claves if k in b}


# Los decoradores de slowapi exigen que la función reciba `request: Request`.
@router.post("/register", status_code=201)
@limiter.limit(config.RATE_LIMIT_FORMS)                                # IP + sesión
@limiter.limit(config.RATE_LIMIT_IP, key_func=get_remote_address)      # solo IP
async def register(request: Request, payload: RegisterIn):
    # La contraseña se valida y se descarta. Nunca se registra.
    riesgo = score_request(request.headers, payload.behavior, payload.website)
    accion = riesgo.accion
    log_event(request, "register_attempt", score=riesgo.score, flags=riesgo.flags,
              action=accion, mode=config.SECURITY_MODE,
              behavior=_behavior_resumen(payload.behavior),
              has_token=bool(payload.turnstile_token))

    ok = {"ok": True,
          "message": f"Registro de práctica recibido para {payload.collector_name}. No se guardó ningún dato."}

    if not config.should_enforce():
        # off / observe: no se bloquea nada (en observe ya quedó registrado)
        return ok

    if accion == "throttle":
        return JSONResponse(
            status_code=429,
            content={"ok": False, "error": "Demasiados intentos sospechosos. Intenta más tarde.",
                     "retry_after": config.RETRY_AFTER_SECONDS},
            headers={"Retry-After": str(config.RETRY_AFTER_SECONDS)},
        )

    if accion == "challenge":
        if not payload.turnstile_token:
            # Se pide el desafío. No se revela qué señales lo provocaron.
            return JSONResponse(status_code=403, content={
                "ok": False, "challenge_required": True,
                "sitekey": config.TURNSTILE_SITEKEY,
                "error": "Confirma que eres humano para continuar.",
            })
        valido, errores = await verify_turnstile(payload.turnstile_token, client_ip(request))
        log_event(request, "turnstile_verify", success=valido, errors=errores)
        if not valido:
            return JSONResponse(status_code=403, content={
                "ok": False, "challenge_required": True,
                "sitekey": config.TURNSTILE_SITEKEY,
                "error": "La verificación no fue válida. Inténtalo de nuevo.",
            })
        ok["message"] += " (verificación humana superada)"

    return ok
