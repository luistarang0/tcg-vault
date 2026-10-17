# TCG Vault

Catálogo de cartas Pokémon (SPA en React + API en FastAPI) para practicar scraping
con Selenium y defensas web **sobre un sitio propio**. Todas las pruebas se hacen
solo contra `localhost`.

Estado:
- **Revisión 1** (pasos 0-5): servidor local, catálogo, formulario y rate limiting.
- **Revisión 2** (pasos 6-8): log de huellas, puntaje de comportamiento + honeypot,
  CAPTCHA Turnstile validado en servidor, scripts de Selenium y auditoría de sitios.
- **Revisión 3** (Fase 3): bot de extracción en portal oficial + limpieza con Pandas
  (carpeta `fase3_extraccion/`, ver su README).
- **Defensa 5** (paso 9): DOM dinámico, IDs y clases decorativas que cambian en cada carga.

## Requisitos

- Python 3.11+
- Node.js 20+
- Git

## 1. Backend (FastAPI)

```bash
cd server
python -m venv .venv
# Windows:   .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # en Windows: copy .env.example .env
```

### Catálogo

Opción real (una sola vez, requiere internet):

```bash
python scripts/import_tcgdex.py --list-sets   # ver colecciones disponibles en español
python scripts/import_tcgdex.py               # importa las colecciones de SET_IDS
```

Opción sin red (solo para pruebas, 900 cartas ficticias `demo-*`):

```bash
python scripts/seed_demo.py --force
```

### Arrancar

```bash
uvicorn app.main:app --reload --port 8000
```

- `http://localhost:8000/api/health` → `{"status":"ok","security_mode":"..."}`
- `http://localhost:8000/docs` → documentación interactiva

## 2. Frontend (React + Vite)

```bash
cd client
npm install
npm run dev
```

Abrir `http://localhost:5173/cartas`. Vite reenvía `/api` al backend (puerto 8000).

## Variables de entorno (`server/.env`)

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `SECURITY_MODE` | `observe` | `off` (abierto), `observe` (registra), `enforce` (bloquea) |
| `RATE_LIMIT_CATALOG` | `60/minute` | Límite del catálogo por IP + sesión |
| `RATE_LIMIT_FORMS` | `10/minute` | Límite del formulario por IP + sesión |
| `RATE_LIMIT_IP` | `120/minute` | Límite de respaldo solo por IP |
| `RETRY_AFTER_SECONDS` | `60` | Valor del encabezado `Retry-After` |
| `TURNSTILE_SITEKEY` | clave de prueba | Clave pública de Turnstile (el servidor la envía al frontend) |
| `TURNSTILE_SECRET` | clave de prueba | Clave secreta de Turnstile, solo en el servidor |

Para cambiar de modo: editar `SECURITY_MODE` en `.env` y reiniciar uvicorn.

## Demostración del bloqueo (Revisión 1)

Con el backend en `SECURITY_MODE=enforce`:

```bash
pip install requests
python scraper_tests/00_rate_limit_demo.py                # misma sesión: 429 tras 60
python scraper_tests/00_rate_limit_demo.py --rotate-sid -n 140   # rota cookies: 429 tras 120 (límite por IP)
```

## Revisión 2: defensas del formulario y scripts de Selenium

Con `SECURITY_MODE=enforce`, `POST /api/register` responde de forma escalonada
según un puntaje de riesgo (0-100) que el servidor calcula con las métricas del
formulario (`useBehaviorTracker`), el honeypot y los encabezados:

| Puntaje | Respuesta |
|---|---|
| 0-29 | 201 permitido |
| 30-59 | 201 permitido, queda en el log |
| 60-79 | 429 + Retry-After |
| 80-100 | 403 + desafío Turnstile; solo pasa con token válido |

Todo queda en `server/logs/access.jsonl` (una línea JSON por petición o evento).

```bash
pip install -r scraper_tests/requirements.txt
python scraper_tests/01_entorno_selenium.py              # verifica Selenium + webdriver-manager
python scraper_tests/02_bot_formulario.py --modo ingenuo  # el servidor bloquea al bot
python scraper_tests/02_bot_formulario.py --modo cuidadoso
python auditoria/auditar_sitios.py --archivo auditoria/sitios.txt --selenium
```

## Defensa 5: DOM dinámico

El hook `client/src/hooks/useDynamicDom.js` genera una sal aleatoria por carga de
página y la usa en los IDs y en una clase señuelo (`dyn-<sal>`) del listado, los
filtros, la paginación, el detalle y el formulario. El estilo sigue viniendo de
CSS Modules, así que el aspecto no cambia. No se tocan los `data-*`, los `name`
de los inputs, los `href` ni las etiquetas ARIA.

```bash
python scraper_tests/03_dom_dinamico.py            # By.ID fijo falla, data-* extrae todo
```

Costos (pregunta 4): las pruebas E2E propias necesitan atributos estables,
la depuración es más difícil (los IDs cambian en cada recarga) y hay que cuidar
no alterar etiquetas ARIA ni asociaciones `label`/`input`.

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado del servidor (sin límite) |
| GET | `/api/cards` | Lista paginada: `page`, `limit` (≤50), `type`, `set_id`, `generation`, `rarity`, `category`, `q` |
| GET | `/api/cards/{id}` | Detalle (404 si no existe) |
| GET | `/api/filters` | Valores válidos de los filtros |
| POST | `/api/register` | Formulario de práctica (no guarda datos) |

## Atributos estables para el scraper

Cada carta del listado es un `<article>` con:
`data-card-id`, `data-card-name`, `data-type`, `data-collection`,
`data-generation`, `data-rarity`, `data-category`. Estos no cambiarán con el DOM
dinámico del paso 9 (el contenedor ya no tiene `id="card-list"` fijo).
