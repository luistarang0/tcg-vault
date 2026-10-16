"""
Punto de entrada del backend en Vercel.

Vercel ejecuta este archivo como función serverless de Python y busca la variable
`app` (ASGI). vercel.json reescribe /api/* hacia aquí conservando la ruta original,
así FastAPI recibe /api/cards, /api/health, etc. igual que en local.

Localmente se sigue usando: cd server && uvicorn app.main:app --reload --port 8000
"""
import sys
from pathlib import Path

# El paquete `app` vive en server/; se agrega al path para importarlo sin moverlo
SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER_DIR))

from app.main import app  # noqa: E402
