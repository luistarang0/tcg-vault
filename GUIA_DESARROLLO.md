# TCG Vault: guía de desarrollo paso a paso

Repositorio de cartas Pokémon (SPA en React + API en Python) pensado para **practicar scraping con Selenium y defensas web reales sobre un sitio propio**.

## Cómo usar esta guía

1. Sigan los pasos **en orden**. Cada paso depende del anterior.
2. Cada paso tiene tres partes: **Objetivo**, **Qué hacer** y **Checkpoint** (cómo saber que quedó bien). Si el checkpoint no pasa, no avancen.
3. Cuando terminen un paso, márquenlo en la tabla de la sección 3.
4. Todo se prueba **solo contra su propio servidor local** (`localhost`). Nunca apunten los scripts de prueba a sitios ajenos.

---

## 1. Decisiones acordadas

| Tema | Decisión |
|---|---|
| Frontend | React con Vite (SPA) |
| Backend | Python: **FastAPI** (guía escrita con FastAPI; equivalencias con Flask abajo) |
| Datos | API de TCGdex en español, importada **una sola vez** a un catálogo local |
| Almacenamiento | SQLite (módulo `sqlite3` de Python, sin instalar nada extra) |
| Volumen | ~900 cartas, 20 por página (~45 páginas), configurable |
| CAPTCHA | Cloudflare Turnstile (token invisible) |
| Pruebas de ataque | Selenium (Python), solo contra `localhost` |

### Equivalencias si el equipo prefiere Flask

| FastAPI | Flask |
|---|---|
| `uvicorn app.main:app --reload` | `flask --app app run --debug` |
| `APIRouter` | `Blueprint` |
| `slowapi` | `Flask-Limiter` |
| Validación con `Query(...)` | `request.args` con validación manual |
| `@app.middleware("http")` | `@app.before_request` / `@app.after_request` |

El frontend y todos los conceptos de seguridad son idénticos en ambos.

### Las 5 defensas

| # | Defensa | Dónde vive | Paso |
|---|---|---|---|
| 1 | Rate limiting (HTTP 429 + `Retry-After`) | Backend | 5 |
| 2 | Logging y detección de huellas de automatización | Backend + Frontend | 6 |
| 3 | Puntaje de comportamiento + honeypot | Frontend + Backend | 7 |
| 4 | CAPTCHA (Turnstile) validado en servidor | Frontend + Backend | 8 |
| 5 | DOM dinámico (IDs/clases cambiantes) | Frontend | 9 |

**Principio de diseño:** el sitio sigue siendo scrapeable. Las defensas **gradúan** la respuesta (permitir, registrar, frenar, desafiar) en lugar de bloquear de golpe.

---

## 2. Estructura del repositorio

```
tcg-vault/
├─ README.md
├─ GUIA_DESARROLLO.md
├─ .gitignore
├─ client/                      # React + Vite
│  ├─ src/
│  │  ├─ pages/                 # CardsPage, CardDetailPage, RegisterPage
│  │  ├─ components/            # CardItem, FilterBar, Pagination
│  │  ├─ hooks/                 # useBehaviorTracker.js
│  │  ├─ api.js                 # funciones fetch al backend
│  │  └─ main.jsx
│  ├─ .env.example
│  └─ vite.config.js
├─ server/
│  ├─ app/
│  │  ├─ __init__.py
│  │  ├─ main.py                # crea la app y registra rutas/middleware
│  │  ├─ config.py              # lee variables de entorno
│  │  ├─ db.py                  # conexión a SQLite
│  │  ├─ routes/
│  │  │  ├─ __init__.py
│  │  │  ├─ cards.py            # /api/cards, /api/cards/{id}, /api/filters
│  │  │  └─ register.py         # /api/register (formulario)
│  │  └─ security/
│  │     ├─ __init__.py
│  │     ├─ ratelimit.py
│  │     ├─ audit.py            # logging + huellas
│  │     ├─ risk.py             # puntaje de riesgo
│  │     └─ turnstile.py
│  ├─ scripts/import_tcgdex.py
│  ├─ data/cards.db             # catálogo generado
│  ├─ logs/                     # access.jsonl (no se sube a git)
│  ├─ requirements.txt
│  └─ .env.example
└─ scraper_tests/               # scripts Selenium (solo contra localhost)
```

---

## 3. Seguimiento del equipo

| Paso | Descripción | Responsable | Estado |
|---|---|---|---|
| 0 | Preparación del repo y herramientas | | ☐ |
| 1 | Backend base funcionando | | ☐ |
| 2 | Importar catálogo de TCGdex | | ☐ |
| 3 | API del catálogo (paginación y filtros) | | ☐ |
| 4 | Frontend: catálogo, detalle y filtros | | ☐ |
| 5 | Formulario + Defensa 1 (rate limiting) | | ☐ |
| 6 | Defensa 2 (logging y huellas) | | ☐ |
| 7 | Defensa 3 (puntaje de comportamiento) | | ☐ |
| 8 | Defensa 4 (Turnstile) | | ☐ |
| 9 | Defensa 5 (DOM dinámico) | | ☐ |
| 10 | Modos `SECURITY_MODE` | | ☐ |
| 11 | Pruebas con Selenium y evidencia | | ☐ |
| 12 | Cierre y entrega | | ☐ |

> **Hito Revisión 1:** pasos **0 al 5** completos (servidor local funcional, formulario principal y al menos un seguro activo) **más** elegir el portal oficial de la Fase 3.

---

## Paso 0. Preparación

**Objetivo:** que todos tengan el mismo entorno.

**Qué hacer**

1. Instalar: **Python 3.11+**, **Node.js 20+** y **Git**. Verificar:
   ```bash
   python --version
   node --version
   git --version
   ```
2. Crear el repositorio y la estructura de la sección 2.
3. Crear `.gitignore` con al menos:
   ```
   .venv/
   node_modules/
   __pycache__/
   .env
   server/logs/
   dist/
   ```
4. Convenciones del equipo:
   - Ramas: `main` (estable), `dev` (integración), `feature/<nombre>` por tarea.
   - Commits cortos y claros: `feat: filtros de catálogo`, `fix: paginación`.
   - **Nunca** subir `.env` ni claves. Solo `.env.example` con valores de ejemplo.

**Checkpoint:** todos clonan el repo, y los tres comandos de versión responden.

---

## Paso 1. Backend base

**Objetivo:** un servidor local que responde peticiones HTTP.

**Qué hacer**

1. Entorno virtual e instalación:
   ```bash
   cd server
   python -m venv .venv
   # Windows:  .venv\Scripts\activate
   # Mac/Linux: source .venv/bin/activate
   pip install fastapi "uvicorn[standard]" slowapi httpx python-dotenv requests
   pip freeze > requirements.txt
   ```
2. `server/app/config.py`:
   ```python
   import os
   from dotenv import load_dotenv

   load_dotenv()

   SECURITY_MODE = os.getenv("SECURITY_MODE", "observe")   # off | observe | enforce
   RATE_LIMIT_CATALOG = os.getenv("RATE_LIMIT_CATALOG", "60/minute")
   RATE_LIMIT_FORMS = os.getenv("RATE_LIMIT_FORMS", "10/minute")
   TURNSTILE_SECRET = os.getenv("TURNSTILE_SECRET", "")
   ```
3. `server/app/main.py` mínimo:
   ```python
   from fastapi import FastAPI

   app = FastAPI(title="TCG Vault API")

   @app.get("/api/health")
   def health():
       return {"status": "ok"}
   ```
4. Crear los archivos `__init__.py` vacíos en `app/`, `app/routes/` y `app/security/`.
5. Crear `server/.env.example`:
   ```
   SECURITY_MODE=observe
   RATE_LIMIT_CATALOG=60/minute
   RATE_LIMIT_FORMS=10/minute
   TURNSTILE_SECRET=
   ```
6. Arrancar (desde `server/`):
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

**Checkpoint:** `http://localhost:8000/api/health` devuelve `{"status":"ok"}`. FastAPI además publica documentación interactiva en `http://localhost:8000/docs`.

---

## Paso 2. Importar el catálogo de TCGdex

**Objetivo:** tener ~900 cartas en SQLite, con tipo, colección, generación y ataques.

**Reglas**

- Se importa **una sola vez**. El sitio no consulta TCGdex en cada petición.
- El script hace **pausas** entre peticiones (0.3 s) y se identifica con un `User-Agent` propio. Revisen los términos de uso de TCGdex.
- Una persona ejecuta el script y **sube `server/data/cards.db`** al repo, para que todos tengan el mismo catálogo.

**Qué hacer**

1. Obtener los ids de las colecciones disponibles: `https://api.tcgdex.net/v2/es/sets`.
2. Elegir **8 a 12 colecciones de distintas eras**. Criterios:
   - Cada generación incluida debe tener al menos ~30 cartas.
   - Cada tipo y rareza debe dar **más de una página** de resultados al filtrar (mínimo ~40 cartas por tipo).
   - Incluir cartas de Pokémon, Entrenador y Energía (las Energías no tienen ataques, y el scraper debe manejar campos ausentes).
3. Esquema de la tabla (`cards`):
   ```sql
   CREATE TABLE IF NOT EXISTS cards (
     id TEXT PRIMARY KEY,
     name TEXT NOT NULL,
     category TEXT,          -- Pokémon / Entrenador / Energía
     hp INTEGER,
     types TEXT,             -- guardado como "|Fuego|Agua|" para filtrar con LIKE
     rarity TEXT,
     set_id TEXT,
     set_name TEXT,
     local_id TEXT,
     dex_id INTEGER,
     generation INTEGER,
     illustrator TEXT,
     image TEXT,
     attacks_json TEXT       -- lista de ataques en JSON
   );
   ```
4. Generación a partir del número de Pokédex (`dexId`):

   | Generación | Rango |
   |---|---|
   | 1 | 1–151 |
   | 2 | 152–251 |
   | 3 | 252–386 |
   | 4 | 387–493 |
   | 5 | 494–649 |
   | 6 | 650–721 |
   | 7 | 722–809 |
   | 8 | 810–905 |
   | 9 | 906–1025 |

5. Esqueleto de `server/scripts/import_tcgdex.py`:
   ```python
   import json, sqlite3, time
   from pathlib import Path
   import requests

   BASE = "https://api.tcgdex.net/v2/es"
   HEADERS = {"User-Agent": "tcg-vault-school-project/0.1"}
   SET_IDS = ["base1", "swsh3", "sv06"]   # completar con las colecciones elegidas
   MAX_PER_SET = 120
   DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cards.db"

   RANGES = [(1,151,1),(152,251,2),(252,386,3),(387,493,4),(494,649,5),
             (650,721,6),(722,809,7),(810,905,8),(906,1025,9)]

   def generation(dex):
       for lo, hi, g in RANGES:
           if lo <= dex <= hi:
               return g
       return None

   def get(path):
       r = requests.get(f"{BASE}{path}", headers=HEADERS, timeout=15)
       r.raise_for_status()
       time.sleep(0.3)                     # pausa cortés
       return r.json()

   def main():
       DB_PATH.parent.mkdir(exist_ok=True)
       conn = sqlite3.connect(DB_PATH)
       # 1) crear tabla (SQL del punto 3)
       for set_id in SET_IDS:
           s = get(f"/sets/{set_id}")
           for brief in s["cards"][:MAX_PER_SET]:
               c = get(f"/cards/{brief['id']}")
               dex = (c.get("dexId") or [None])[0]
               # 2) insertar con INSERT OR REPLACE, usando c.get(...) para campos opcionales
       conn.commit(); conn.close()

   if __name__ == "__main__":
       main()
   ```
   > Los nombres exactos de los campos (`types`, `rarity`, `attacks`, `dexId`…) verifíquenlos con una respuesta real de `/cards/{id}` antes de insertar.

6. Ejecutar (desde `server/`): `python scripts/import_tcgdex.py`

**Checkpoint:** en SQLite, `SELECT COUNT(*) FROM cards;` da ~900, y `SELECT generation, COUNT(*) FROM cards GROUP BY generation;` muestra varias generaciones con volumen suficiente.

---

## Paso 3. API del catálogo

**Objetivo:** endpoints con paginación y filtros que el frontend (y después Selenium) consumirá.

**Endpoints**

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/cards` | Lista paginada. Parámetros: `page`, `limit` (máx. 50), `type`, `set_id`, `generation`, `rarity`, `q` |
| GET | `/api/cards/{id}` | Detalle de una carta |
| GET | `/api/filters` | Valores válidos para los filtros |

**Qué hacer**

1. `server/app/db.py`:
   ```python
   import sqlite3
   from pathlib import Path

   DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cards.db"

   def get_conn():
       conn = sqlite3.connect(DB_PATH)
       conn.row_factory = sqlite3.Row
       return conn
   ```
2. `server/app/routes/cards.py` (esqueleto):
   ```python
   from fastapi import APIRouter, HTTPException, Query
   from app.db import get_conn

   router = APIRouter()

   @router.get("/cards")
   def list_cards(
       page: int = Query(1, ge=1),
       limit: int = Query(20, ge=1, le=50),
       card_type: str | None = Query(None, alias="type"),
       set_id: str | None = None,
       generation: int | None = None,
       rarity: str | None = None,
       q: str | None = None,
   ):
       where, params = [], []
       if card_type:  where.append("types LIKE ?");  params.append(f"%|{card_type}|%")
       if set_id:     where.append("set_id = ?");    params.append(set_id)
       if generation: where.append("generation = ?"); params.append(generation)
       if rarity:     where.append("rarity = ?");    params.append(rarity)
       if q:          where.append("name LIKE ?");   params.append(f"%{q}%")
       sql_where = ("WHERE " + " AND ".join(where)) if where else ""

       conn = get_conn()
       total = conn.execute(f"SELECT COUNT(*) FROM cards {sql_where}", params).fetchone()[0]
       rows = conn.execute(
           f"SELECT * FROM cards {sql_where} ORDER BY set_id, CAST(local_id AS INTEGER) LIMIT ? OFFSET ?",
           params + [limit, (page - 1) * limit],
       ).fetchall()
       conn.close()
       return {"items": [dict(r) for r in rows], "page": page, "limit": limit,
               "total": total, "pages": -(-total // limit)}
   ```
   **Importante:** los valores del usuario siempre van como parámetros (`?`), nunca pegados al texto del SQL (evita inyección SQL).
3. Registrar el router en `main.py`: `app.include_router(cards.router, prefix="/api")`.
4. Completar `/api/cards/{id}` (404 si no existe) y `/api/filters` (valores distintos de tipo, colección, generación y rareza).

**Checkpoint:** `GET /api/cards?page=3&limit=20`, `GET /api/cards?type=Fuego&generation=1` y `GET /api/cards/<id>` responden bien, y `pages` es coherente con `total`.

---

## Paso 4. Frontend: catálogo, detalle y filtros

**Objetivo:** que se vea y navegue el catálogo, con una estructura **scrapeable por diseño**.

**Qué hacer**

1. Crear el proyecto (desde la raíz del repo):
   ```bash
   npm create vite@latest client -- --template react
   cd client
   npm install
   npm install react-router-dom
   ```
2. Proxy al backend en `client/vite.config.js` (evita problemas de CORS en desarrollo):
   ```js
   import { defineConfig } from 'vite'
   import react from '@vitejs/plugin-react'

   export default defineConfig({
     plugins: [react()],
     server: { proxy: { '/api': 'http://localhost:8000' } },
   })
   ```
3. Rutas con `react-router-dom`: `/cartas`, `/cartas/:id`, `/registro`.
4. **Filtros y página en la URL** (con `useSearchParams`): `/cartas?page=3&type=Fuego&generation=1`. Así las páginas se pueden visitar y scrapear directamente.
5. **Atributos de datos estables** en cada carta (esto es lo que el scraper usará y **no cambiará** con el DOM dinámico):
   ```jsx
   <article
     data-card-id={card.id}
     data-card-name={card.name}
     data-type={card.types}
     data-collection={card.set_name}
     data-generation={card.generation}
   >
     ...
   </article>
   ```
6. Paginación visible, con enlaces anterior/siguiente y número de página.
7. Estilos con **CSS Modules** (archivos `*.module.css`), que Vite soporta sin configuración.
8. Mezcla de renderizado: el listado carga por `fetch` (obliga a usar Selenium con esperas explícitas); el detalle puede incluir además un bloque JSON-LD con los datos de la carta.

**Checkpoint:** con backend y frontend corriendo (`npm run dev`), se puede paginar por todo el catálogo, filtrar por tipo, colección, generación y rareza, y abrir el detalle de cualquier carta. Al inspeccionar el HTML se ven los `data-*`.

---

## Paso 5. Formulario + Defensa 1: Rate limiting

**Objetivo:** el formulario principal funciona y hay un seguro activo. **Este paso completa el hito de la Revisión 1.**

**Parte A. Formulario**

1. Crear la página `/registro` con campos: nombre de coleccionista, correo y un campo de contraseña.
2. Endpoint `POST /api/register` en `routes/register.py`. **No se guarda ninguna contraseña real**: el endpoint solo valida los campos y responde `201`. Es un formulario de práctica para las métricas y el CAPTCHA de los pasos 7 y 8. *(Actualización: con el mercado de subastas este endpoint ya crea la cuenta real, con la contraseña guardada como hash scrypt; ver README.)*
3. Agregar al formulario un campo **honeypot** oculto con CSS (se usará en el paso 7).

**Parte B. Rate limiting con `slowapi`**

1. `server/app/security/ratelimit.py`:
   ```python
   from fastapi import Request
   from fastapi.responses import JSONResponse
   from slowapi import Limiter
   from slowapi.errors import RateLimitExceeded
   from slowapi.util import get_remote_address
   from app import config

   def key_ip_session(request: Request) -> str:
       sid = request.cookies.get("sid", "nosession")
       return f"{get_remote_address(request)}:{sid}"

   limiter = Limiter(
       key_func=key_ip_session,
       default_limits=[config.RATE_LIMIT_CATALOG],
       enabled=(config.SECURITY_MODE == "enforce"),
   )

   async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
       return JSONResponse(
           status_code=429,
           content={"error": "Too Many Requests", "detail": str(exc.detail)},
           headers={"Retry-After": "60"},
       )
   ```
2. Registrarlo en `main.py`:
   ```python
   from slowapi.errors import RateLimitExceeded
   from slowapi.middleware import SlowAPIMiddleware
   from app.security.ratelimit import limiter, rate_limit_handler

   app.state.limiter = limiter
   app.add_middleware(SlowAPIMiddleware)
   app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
   ```
3. Cookie de sesión `sid` (un middleware la crea si no existe, con `httponly=True` y `samesite="lax"`). Sin ella, la clave "IP + sesión" no distingue sesiones.
4. Límite más estricto en el formulario (la función necesita el parámetro `request: Request`):
   ```python
   @router.post("/register")
   @limiter.limit(config.RATE_LIMIT_FORMS)
   async def register(request: Request, ...):
       ...
   ```
5. Un atacante puede descartar la cookie para evadir el límite por sesión. Por eso conviene añadir un segundo límite **solo por IP**, más alto, usando `key_func=get_remote_address` en otro `@limiter.limit(...)`.

**Checkpoint**

- Con `SECURITY_MODE=enforce`, un bucle de más de 60 peticiones por minuto a `/api/cards` recibe **HTTP 429** con el encabezado `Retry-After`.
- Una navegación humana normal nunca lo activa.
- Guarden una captura de la respuesta 429 (sirve de evidencia para la pregunta 2).

> ### ✅ Hito Revisión 1
> Tienen: servidor local funcional (pasos 1 a 4), formulario principal con una defensa activa (paso 5). Falta solo **confirmar el portal oficial** de la Fase 3 (nombre y URL; revisar su `robots.txt` y términos de uso, y si ofrece una API o descarga directa).

---

## Paso 6. Defensa 2: Logging y huellas de automatización

**Objetivo:** cada petición queda registrada con las señales que delatan un navegador automatizado.

**Qué hacer**

1. Middleware en `security/audit.py` que escriba **una línea JSON por petición** en `server/logs/access.jsonl`:
   ```python
   record = {
       "ts": datetime.utcnow().isoformat(),
       "ip": request.client.host,
       "sid": request.cookies.get("sid"),
       "method": request.method,
       "path": request.url.path,
       "query": str(request.url.query),
       "status": response.status_code,
       "user_agent": request.headers.get("user-agent"),
       "accept_language": request.headers.get("accept-language"),
       "sec_ch_ua": request.headers.get("sec-ch-ua"),
       "automation_suspected": flags != [],
       "flags": flags,
   }
   ```
2. Reglas de etiquetado en el servidor (se **etiqueta**, no se bloquea):
   - `User-Agent` contiene `HeadlessChrome` (o está vacío).
   - Falta `Accept-Language`.
   - `Sec-CH-UA` incoherente con el `User-Agent`.
3. Señales del lado del cliente (se envían junto con el formulario, paso 7): `navigator.webdriver`, `navigator.plugins.length`, `navigator.languages.length`.
4. **No registrar contraseñas ni datos sensibles** en los logs.

**Checkpoint:** tras navegar con un navegador normal y con un script de Selenium, `access.jsonl` muestra líneas distintas (el UA, los `flags` y `automation_suspected`). Guarden un ejemplo de cada una (evidencia para la pregunta 5).

---

## Paso 7. Defensa 3: Puntaje de comportamiento y honeypot

**Objetivo:** estimar si el que llena el formulario es una persona, sumando puntos de riesgo.

**Cliente (React).** Hook `useBehaviorTracker` que recopila, mientras el usuario llena el formulario:
- Tiempo total de llenado y por campo.
- Intervalos entre pulsaciones de teclas (media y desviación).
- Cantidad de eventos `mousemove`.
- Proporción de eventos con `event.isTrusted === true`.
- Valor del honeypot.
- `navigator.webdriver`.

Todo se envía en el cuerpo del `POST /api/register` dentro de un objeto `behavior`.

**Servidor.** `security/risk.py` calcula el puntaje (el **servidor decide**, el cliente solo informa):

| Señal | Puntos |
|---|---|
| Honeypot lleno | +60 |
| Algún evento con `isTrusted = false` | +40 |
| `navigator.webdriver = true` | +30 |
| `User-Agent` headless | +30 |
| Tiempo total de llenado < 1.5 s | +25 |
| ≥10 pulsaciones con desviación < 5 ms | +20 |
| Sin `mousemove` ni teclas | +15 (peso bajo: móvil y accesibilidad) |
| Falta `Accept-Language` | +10 |

Puntaje máximo: 100.

```python
def score_request(headers: dict, behavior: dict) -> tuple[int, list[str]]:
    score, flags = 0, []
    if behavior.get("honeypot"):
        score += 60; flags.append("honeypot")
    # ... seguir con el resto de la tabla
    return min(score, 100), flags
```

**Respuesta escalonada**

| Puntaje | Acción |
|---|---|
| 0–29 | Permitir |
| 30–59 | Permitir y registrar en el log |
| 60–79 | Frenar (HTTP 429 con `Retry-After`) |
| 80–100 | Exigir desafío (Turnstile, paso 8) |

> Cuiden la accesibilidad: no penalicen fuerte la ausencia de mouse. Los umbrales anteriores son un punto de partida y se ajustan con los logs.

**Checkpoint:** un formulario llenado a mano da un puntaje bajo; uno enviado con un script que llena todo al instante o rellena el honeypot da un puntaje alto, y ambos quedan en el log.

---

## Paso 8. Defensa 4: CAPTCHA con Cloudflare Turnstile

**Objetivo:** un desafío que se activa cuando el puntaje es alto, **validado en el servidor**.

**Qué hacer**

1. Crear un sitio en el panel de Cloudflare Turnstile y obtener `sitekey` (pública) y `secret` (privada). Para desarrollar, Cloudflare publica **claves de prueba** que siempre pasan o siempre fallan (consulten la sección *Testing* de su documentación).
2. Frontend:
   ```bash
   npm install @marsidev/react-turnstile
   ```
   ```jsx
   import { Turnstile } from '@marsidev/react-turnstile'

   <Turnstile siteKey={import.meta.env.VITE_TURNSTILE_SITEKEY} onSuccess={setToken} />
   ```
   Guardar la sitekey en `client/.env` como `VITE_TURNSTILE_SITEKEY=...` (y dejar `.env.example`).
3. Backend, `security/turnstile.py`:
   ```python
   import httpx
   from app import config

   VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

   async def verify_turnstile(token: str, ip: str) -> bool:
       if not token:
           return False
       async with httpx.AsyncClient(timeout=5) as client:
           r = await client.post(VERIFY_URL, data={
               "secret": config.TURNSTILE_SECRET,
               "response": token,
               "remoteip": ip,
           })
       return r.json().get("success", False)
   ```
4. En `POST /api/register`: si el puntaje exige desafío y el token no es válido, responder **403**. El token es de un solo uso.
5. La **clave secreta nunca va en el frontend**.

**Checkpoint:** con una clave de prueba que falla, el servidor rechaza la petición aunque el cliente "diga" que pasó; con una que pasa, el formulario se procesa. Esto demuestra por qué la validación debe ser del lado del servidor (pregunta 3).

---

## Paso 9. Defensa 5: DOM dinámico

**Objetivo:** romper los localizadores estáticos de Selenium **sin romper los datos**.

**Qué cambia y qué no**

| Cambia (decorativo) | Se mantiene estable (contenido) |
|---|---|
| IDs y clases de botones y contenedores | `data-card-id`, `data-card-name`, `data-type`, `data-collection`, `data-generation` |
| Nombres de clases generados por CSS Modules | URLs `/cartas?page=N&...` |

**Qué hacer**

1. **Nivel A (ya incluido):** los CSS Modules de Vite generan nombres de clase con hash. Cambian en cada compilación.
2. **Nivel B:** IDs y clases decorativas aleatorias en cada carga de página:
   ```jsx
   import { useRef } from 'react'

   const salt = useRef(Math.random().toString(36).slice(2, 8)).current
   <button id={`btn-${salt}`} className={`${styles.btn} dyn-${salt}`}>Buscar</button>
   ```
   El estilo sigue viniendo de `styles.btn`, así que el aspecto no cambia, pero un `By.ID("btn-buscar")` deja de funcionar.
3. **No** cambiar los `data-*` de contenido, para que el catálogo siga siendo scrapeable con selectores robustos.

**Costos a documentar (pregunta 4):** mayor dificultad para escribir pruebas E2E propias (necesitan atributos estables), depuración más compleja, riesgo para la accesibilidad si se alteran etiquetas ARIA y menor eficacia del caché.

**Checkpoint:** un script de Selenium con `By.ID` fijo falla con `NoSuchElementException`; uno que usa los atributos `data-*` extrae los datos sin problema.

---

## Paso 10. Modos de seguridad

**Objetivo:** poder comparar el comportamiento con las defensas apagadas, observando o actuando.

| `SECURITY_MODE` | Efecto |
|---|---|
| `off` | Sitio totalmente abierto (línea base para el scraping) |
| `observe` | Todo se registra en el log, nada se bloquea |
| `enforce` | Las defensas actúan (429, desafíos, rechazos) |

**Qué hacer**

1. `config.SECURITY_MODE` ya existe (paso 1). Crear helpers:
   ```python
   def should_log():     return config.SECURITY_MODE in ("observe", "enforce")
   def should_enforce(): return config.SECURITY_MODE == "enforce"
   ```
2. Cada defensa los consulta antes de actuar. El rate limiting ya lo usa mediante `enabled=`.
3. Cambiar de modo = editar `.env` y reiniciar el servidor.

**Checkpoint:** el mismo script de scraping se comporta distinto en los tres modos (completa, completa con logs, recibe bloqueos).

---

## Paso 11. Pruebas con Selenium y evidencia

**Objetivo:** generar los datos reales que respaldan las respuestas a las preguntas de la actividad.

> Solo contra `http://localhost`. Nunca contra sitios ajenos.

**Qué hacer**

1. En `scraper_tests/`:
   ```bash
   pip install selenium webdriver-manager
   ```
2. Tres scripts mínimos:

   | Script | Qué hace | Evidencia que produce |
   |---|---|---|
   | `01_baseline.py` | Recorre las ~45 páginas con pausas, `SECURITY_MODE=off` | Tiempo total y cartas extraídas |
   | `02_aggressive.py` | Peticiones sin pausa y en paralelo (varias pestañas) | Respuestas 429, líneas del log |
   | `03_polite.py` | Respeta `Retry-After` y espera con `WebDriverWait` | Cómo un scraper educado evita el bloqueo |

3. Esqueleto base:
   ```python
   from selenium import webdriver
   from selenium.webdriver.common.by import By
   from selenium.webdriver.support.ui import WebDriverWait
   from selenium.webdriver.support import expected_conditions as EC

   driver = webdriver.Chrome()
   driver.get("http://localhost:5173/cartas?page=1")
   WebDriverWait(driver, 10).until(
       EC.presence_of_element_located((By.CSS_SELECTOR, "article[data-card-id]"))
   )
   for el in driver.find_elements(By.CSS_SELECTOR, "article[data-card-id]"):
       print(el.get_attribute("data-card-name"), el.get_attribute("data-type"))
   driver.quit()
   ```
4. Ejecutar cada script en los tres modos (`off`, `observe`, `enforce`) y **guardar evidencia**:
   - Captura de la respuesta 429 con `Retry-After`.
   - Líneas de `access.jsonl` de un navegador normal vs. Selenium.
   - Valor de `navigator.webdriver` detectado.
   - Resultado del formulario con y sin Turnstile válido.
   - Falla de un localizador por ID y éxito con `data-*`.

**Checkpoint:** tabla completa (script × modo → resultado) con sus capturas.

### Evidencia por pregunta de la actividad

| Pregunta | Qué evidencia viene de qué paso |
|---|---|
| 1. Métricas del cliente | Paso 7: puntaje de un humano vs. un script |
| 2. Rate limiting y 429 | Pasos 5 y 11: captura del 429 y el efecto de pestañas en paralelo |
| 3. CAPTCHA en servidor | Paso 8: rechazo con token inválido |
| 4. DOM dinámico | Paso 9: falla de `By.ID`, éxito con `data-*` |
| 5. Cabeceras y `navigator.webdriver` | Paso 6: líneas del log |

---

## Paso 12. Cierre y entrega

1. Revisar que ningún secreto esté en el repo (`git log` y `git grep -i secret`).
2. `README.md` con: cómo instalar, cómo arrancar backend y frontend, variables de entorno y cómo cambiar `SECURITY_MODE`.
3. Actualizar las respuestas de la actividad pasando de **diseño a resultados observados**, con las capturas del paso 11.
4. Subir la entrega (se permiten varios envíos: conviene enviar una versión inicial y mejorarla).

---

## Anexo: problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `ModuleNotFoundError: app` | Se ejecutó `uvicorn` fuera de `server/` o falta `__init__.py` | Ejecutar desde `server/` y crear los `__init__.py` |
| Frontend recibe 404 en `/api/...` | Falta el proxy de Vite | Revisar `vite.config.js` y reiniciar `npm run dev` |
| El rate limit no se activa | `SECURITY_MODE` no está en `enforce` | Revisar `.env` y reiniciar el servidor |
| El 429 se activa con uso normal | Límite demasiado bajo o `sid` ausente | Subir el límite o revisar el middleware de cookie |
| Selenium no encuentra elementos | La SPA carga por JS | Usar `WebDriverWait` en lugar de `sleep` |
| Turnstile siempre falla | Clave secreta incorrecta o sitekey de otro entorno | Usar claves de prueba y verificar el `.env` |
| Importador devuelve 404 en algún id | Colección o carta no disponible en español | Revisar el id en `/v2/es/sets` y omitir la colección |
