"""
Protección CSRF con el patrón "double-submit cookie".

CSRF (Cross-Site Request Forgery): un sitio malicioso hace que el navegador de
la víctima envíe una petición a TCG Vault; el navegador adjunta solo las cookies
de sesión y la operación se ejecuta como si la hubiera pedido el usuario.

Cómo se evita:
  1. El servidor entrega una cookie `csrf_token` aleatoria (NO httponly: el
     JavaScript de nuestra propia página debe poder leerla).
  2. En cada operación que modifica datos (POST/PUT/PATCH/DELETE a /api/*), el
     frontend copia ese valor en el encabezado `X-CSRF-Token`.
  3. El servidor compara cookie y encabezado. Un sitio ajeno puede provocar que
     el navegador envíe la cookie, pero NO puede leerla para ponerla en el
     encabezado (política de mismo origen). Sin coincidencia -> 403.

La validación vive aquí, en el backend: que el token aparezca en el navegador no
protege nada por sí solo. Complementa a la cookie SameSite=Lax de la sesión.

Obedece a SECURITY_MODE como las demás defensas:
  off      no se valida
  observe  se registra `csrf_invalid` en el log, pero se deja pasar
  enforce  se responde 403
"""
import hmac
import secrets

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app import config
from app.security.audit import log_event

COOKIE_NAME = "csrf_token"
HEADER_NAME = "x-csrf-token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _token_ok(request: Request) -> tuple[bool, str]:
    cookie = request.cookies.get(COOKIE_NAME)
    header = request.headers.get(HEADER_NAME)
    if not cookie:
        return False, "sin_cookie"
    if not header:
        return False, "sin_encabezado"
    if not hmac.compare_digest(cookie, header):   # comparación en tiempo constante
        return False, "no_coincide"
    return True, ""


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = None
        if (request.method in UNSAFE_METHODS and request.url.path.startswith("/api/")
                and config.SECURITY_MODE != "off"):
            ok, motivo = _token_ok(request)
            if not ok:
                log_event(request, "csrf_invalid", reason=motivo, mode=config.SECURITY_MODE)
                if config.should_enforce():
                    response = JSONResponse(status_code=403, content={
                        "ok": False, "csrf_failed": True,
                        "error": "Token CSRF ausente o inválido. Recarga la página e inténtalo de nuevo."})

        if response is None:
            response = await call_next(request)
        # Incluso en el 403 se entrega la cookie: el siguiente intento legítimo ya la tendrá
        if COOKIE_NAME not in request.cookies:
            response.set_cookie(
                key=COOKIE_NAME, value=secrets.token_urlsafe(32),
                max_age=60 * 60 * 24 * 7,
                httponly=False,              # a propósito: el frontend la copia al encabezado
                samesite="strict",           # nunca viaja en peticiones iniciadas por otro sitio
                secure=config.COOKIE_SECURE,
                path="/",
            )
        return response
