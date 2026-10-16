"""
Defensa 1: Rate limiting con slowapi.

* Clave principal: IP + cookie de sesión `sid`. Dos personas detrás de la misma IP
  (por ejemplo, la red de la escuela) no se bloquean entre sí.
* Clave de respaldo: solo IP, con un límite más alto. Si un scraper descarta la
  cookie para "renovar" su sesión, sigue topando con este límite.
* Solo actúa en SECURITY_MODE=enforce (enabled=...). En off/observe no bloquea.
* Al exceder el límite responde HTTP 429 con encabezado Retry-After.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app import config


def key_ip_session(request: Request) -> str:
    """Clave del contador: 'IP:sid'. Sin cookie se agrupa en 'IP:nosession'."""
    sid = request.cookies.get("sid", "nosession")
    return f"{get_remote_address(request)}:{sid}"


# storage_uri="memory://" -> contadores en memoria del proceso (suficiente para
# un servidor local). En producción con varios procesos se usaría Redis.
limiter = Limiter(
    key_func=key_ip_session,
    default_limits=[config.RATE_LIMIT_CATALOG],   # aplica a todas las rutas sin decorador
    enabled=config.should_enforce(),
    storage_uri="memory://",
)


async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Respuesta uniforme para cualquier límite superado."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "Too Many Requests",
            "detail": f"Límite superado: {exc.detail}",
            "retry_after": config.RETRY_AFTER_SECONDS,
        },
        headers={"Retry-After": str(config.RETRY_AFTER_SECONDS)},
    )
