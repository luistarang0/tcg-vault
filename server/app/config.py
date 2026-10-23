"""
Configuración central del backend.

Lee las variables de entorno (archivo .env en server/) una sola vez al importar
el módulo. El resto de la app importa `from app import config` y usa estas
constantes, así hay un único lugar donde cambiar el comportamiento.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Carga server/.env si existe (en producción las variables pueden venir del sistema)
load_dotenv()

# Modo de seguridad global:
#   off     -> sitio abierto (línea base para scraping)
#   observe -> se registra todo, no se bloquea nada
#   enforce -> las defensas actúan (429, desafíos, rechazos)
SECURITY_MODE = os.getenv("SECURITY_MODE", "observe").strip().lower()
if SECURITY_MODE not in ("off", "observe", "enforce"):
    SECURITY_MODE = "observe"  # valor inválido -> modo seguro por defecto

# Límites en formato de la librería `limits` usada por slowapi: "N/periodo"
RATE_LIMIT_CATALOG = os.getenv("RATE_LIMIT_CATALOG", "60/minute")   # por IP + sesión
RATE_LIMIT_FORMS = os.getenv("RATE_LIMIT_FORMS", "10/minute")       # formulario, por IP + sesión
RATE_LIMIT_IP = os.getenv("RATE_LIMIT_IP", "120/minute")            # respaldo solo por IP

RATE_LIMIT_LOGIN = os.getenv("RATE_LIMIT_LOGIN", "10/minute")       # login, por IP + sesión
RATE_LIMIT_BIDS = os.getenv("RATE_LIMIT_BIDS", "20/minute")         # pujas y acciones del mercado
RATE_LIMIT_POLL = os.getenv("RATE_LIMIT_POLL", "40/minute")         # polling de subastas (~cada 5 s)

# Límite por CUENTA del login (guardado en Postgres, no en memoria):
# tras LOGIN_MAX_FAILS fallos en LOGIN_WINDOW_MIN minutos, esa cuenta responde 429.
LOGIN_MAX_FAILS = int(os.getenv("LOGIN_MAX_FAILS", "5"))
LOGIN_WINDOW_MIN = int(os.getenv("LOGIN_WINDOW_MIN", "15"))

# Postgres (Neon). En local: rama dev en server/.env. En Vercel: la crea la integración.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Sesión de usuario: días de vigencia de la cookie y si exige HTTPS.
# En Vercel (VERCEL=1) siempre hay HTTPS; en localhost no, por eso Secure solo allí.
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "7"))
COOKIE_SECURE = bool(os.getenv("VERCEL"))

# Segundos que se anuncian en el encabezado Retry-After de las respuestas 429
RETRY_AFTER_SECONDS = int(os.getenv("RETRY_AFTER_SECONDS", "60"))

# Cloudflare Turnstile (paso 8).
# La SITEKEY es pública: el backend la entrega al frontend cuando exige el desafío.
# La SECRET es privada: solo el servidor la usa para validar el token. Nunca va al frontend.
# Si no se definen (o quedan vacías en .env) se usan las claves de PRUEBA oficiales
# de Cloudflare: la sitekey 3x... muestra una casilla interactiva y la secret 1x... siempre valida.
TURNSTILE_SITEKEY = os.getenv("TURNSTILE_SITEKEY") or "3x00000000000000000000FF"
TURNSTILE_SECRET = os.getenv("TURNSTILE_SECRET") or "1x0000000000000000000000000000000AA"
TURNSTILE_VERIFY_URL = os.getenv(
    "TURNSTILE_VERIFY_URL", "https://challenges.cloudflare.com/turnstile/v0/siteverify")

# Carpeta del log de acceso (access.jsonl).
# En Vercel (que define VERCEL=1) solo /tmp admite escritura y se borra entre ejecuciones;
# en local se usa server/logs. LOG_DIR en el entorno tiene prioridad sobre ambos.
_DEFAULT_LOG_DIR = (Path("/tmp/tcg-vault-logs") if os.getenv("VERCEL")
                    else Path(__file__).resolve().parent.parent / "logs")
LOG_DIR = Path(os.getenv("LOG_DIR") or _DEFAULT_LOG_DIR)


def should_log() -> bool:
    """True si las defensas deben registrar eventos (modos observe y enforce)."""
    return SECURITY_MODE in ("observe", "enforce")


def should_enforce() -> bool:
    """True si las defensas deben actuar (solo en modo enforce)."""
    return SECURITY_MODE == "enforce"
