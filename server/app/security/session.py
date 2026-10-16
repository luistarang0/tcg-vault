"""
Middleware de cookie de sesión `sid`.

Si la petición no trae cookie `sid`, se genera un identificador aleatorio y se
envía en la respuesta. El navegador la devuelve en las siguientes peticiones y
el rate limiter puede distinguir sesiones que comparten IP.

* httponly=True  -> JavaScript no puede leerla (mitiga robo por XSS).
* samesite="lax" -> no viaja en peticiones cruzadas de otros sitios (mitiga CSRF).
* No guarda datos personales: es solo un identificador opaco.
"""
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

COOKIE_NAME = "sid"
COOKIE_MAX_AGE = 60 * 60 * 24   # 1 día


class SessionCookieMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if COOKIE_NAME not in request.cookies:
            response.set_cookie(
                key=COOKIE_NAME,
                value=secrets.token_urlsafe(16),   # 128 bits aleatorios
                max_age=COOKIE_MAX_AGE,
                httponly=True,
                samesite="lax",
                path="/",
            )
        return response
