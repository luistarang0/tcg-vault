"""
Punto de entrada del backend TCG Vault.

Arranque (desde server/):
    uvicorn app.main:app --reload --port 8000

Orden de middleware (Starlette ejecuta primero el ÚLTIMO agregado):
    petición -> AuditMiddleware -> SessionCookieMiddleware -> SlowAPIMiddleware -> ruta
Así el log registra todas las respuestas (incluidas las 429), el limitador evalúa
cada petición y la cookie `sid` se agrega a la respuesta.

Nota de compatibilidad: con FastAPI reciente, SlowAPIMiddleware solo alcanza las
rutas definidas directamente en `app`. Por eso las rutas de los routers declaran
sus límites con @limiter.limit(...) (ver routes/cards.py y routes/register.py).
"""
from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app import config
from app.routes import cards, register
from app.security.audit import AuditMiddleware
from app.security.ratelimit import limiter, rate_limit_handler
from app.security.session import SessionCookieMiddleware

app = FastAPI(
    title="TCG Vault API",
    description="Catálogo de cartas Pokémon para practicar scraping y defensas web.",
    version="0.1.0",
)

# --- Defensa 1: rate limiting -------------------------------------------------
app.state.limiter = limiter                                   # slowapi lo busca aquí
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)                         # aplica default_limits

# --- Cookie de sesión (se agrega después = se ejecuta antes) -------------------
app.add_middleware(SessionCookieMiddleware)

# --- Defensa 2: log de cada petición con huellas de automatización -------------
# Es la capa más externa: registra también las respuestas 429 del limitador.
app.add_middleware(AuditMiddleware)

# --- Rutas --------------------------------------------------------------------
app.include_router(cards.router, prefix="/api", tags=["catálogo"])
app.include_router(register.router, prefix="/api", tags=["formulario"])


@app.get("/api/health", tags=["sistema"])
@limiter.exempt                       # el health-check nunca se limita
def health():
    """Checkpoint del paso 1. Informa también el modo de seguridad activo."""
    return {"status": "ok", "security_mode": config.SECURITY_MODE}
