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
- **Mercado de subastas**: cuentas reales, puntos, colección de cartas y subastas con
  pujas (ver sección "Mercado de subastas").

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

### Base de datos del mercado (Postgres en Neon)

El catálogo vive en SQLite (`server/data/cards.db`, solo lectura). Usuarios, cartas
en posesión, subastas y pujas viven en Postgres, porque en Vercel el disco es de
solo lectura. Se usa Neon:

1. En Vercel: **Storage → Create Database → Neon**, conectada al proyecto. Esto crea
   `DATABASE_URL` (rama `main`) para producción.
2. En la consola de Neon: **Branches → Create branch** `dev` (padre `main`).
3. **Connect** → rama `dev`, con pooling → copiar la cadena en `server/.env`:
   `DATABASE_URL=postgresql://...-pooler...neon.tech/neondb?sslmode=require`

Las tablas se crean solas la primera vez que el backend se conecta.

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
| `RATE_LIMIT_LOGIN` | `10/minute` | Login por IP + sesión |
| `RATE_LIMIT_BIDS` | `20/minute` | Pujas y acciones del mercado por IP + sesión |
| `RATE_LIMIT_POLL` | `40/minute` | Lecturas del mercado (polling cada ~5 s) |
| `LOGIN_MAX_FAILS` / `LOGIN_WINDOW_MIN` | `5` / `15` | Fallos de login que bloquean una CUENTA y ventana en minutos |
| `DATABASE_URL` | — | Postgres de Neon (rama `dev` en local) |
| `SESSION_DAYS` | `7` | Vigencia de la sesión de usuario |
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

## Bitácora de seguridad en Postgres

En Vercel el archivo `access.jsonl` vive en `/tmp` y se pierde con cada instancia,
así que los eventos de las defensas (puntajes, desafíos, CSRF inválido, logins,
pujas) y cada respuesta **429** se guardan también en la tabla `security_events`
de Neon. Las peticiones normales no se guardan. Está activo por defecto en Vercel;
en local se enciende con `SECURITY_EVENTS_DB=1`.

```powershell
# desde server/: usa la DATABASE_URL de .env (rama dev); --url para la rama main
python scripts/ver_eventos.py --horas 24
python scripts/ver_eventos.py --evento rate_limited
python scripts/ver_eventos.py --resumen
```

En la consola de Neon (SQL Editor, rama `main`) se ve lo que pasó en producción:

```sql
SELECT ts, event, status, ip, score, action, flags, data
FROM security_events ORDER BY ts DESC LIMIT 50;
```

## Panel de seguridad del administrador (`/admin`)

Un **único** administrador (lo garantiza un índice único en `users.is_admin`) entra
por el login normal y ve en `/admin` la bitácora `security_events`:

- Filtros por periodo (1 h, 24 h, 7 días, 30 días o rango personalizado), tipo de
  evento, acción, código HTTP (exacto o 4xx/5xx), IP y texto libre. Viven en la URL.
- Indicadores (429, desafíos, frenados, CSRF inválido, logins fallidos, IPs),
  gráfica de eventos por hora/día/semana con vista en tabla, IPs y señales más
  frecuentes, bitácora paginada con detalle y exportación a CSV.
- Las rutas `/api/admin/*` responden 401 sin sesión y 403 a cualquier otra cuenta.

Crear el administrador (la contraseña se pide sin mostrarse; mínimo 12 caracteres):

```powershell
# desde server/, con el .venv activado. Local = rama dev de server/.env
python scripts/crear_admin.py --usuario admin --correo admin@tcgvault.mx
# producción: la cadena de la rama main (Vercel → Storage → Neon)
python scripts/crear_admin.py --usuario admin --correo admin@tcgvault.mx --url "postgresql://…"
python scripts/crear_admin.py --ver                  # quién es el administrador
python scripts/crear_admin.py --promover luis_demo   # convertir una cuenta existente
```

En local el panel solo muestra eventos si el backend guarda en la base:
`$env:SECURITY_EVENTS_DB="1"` antes de `uvicorn`. En Vercel se guardan siempre.

## Token CSRF (double-submit)

`server/app/security/csrf.py`: el backend entrega la cookie `csrf_token` y exige
que toda operación que modifica datos (POST/PUT/PATCH/DELETE a `/api/*`) traiga el
mismo valor en el encabezado `X-CSRF-Token`; si falta o no coincide responde **403**
(en `enforce`; en `observe` solo registra `csrf_invalid`). `client/src/api.js`
copia la cookie al encabezado. Un sitio ajeno no puede leer la cookie, así que no
puede falsificar el encabezado.

## Reto de las n solicitudes (TAD 2.4, actividad 3)

```powershell
# backend con límite de login de 5 por minuto (desde server/)
$env:SECURITY_MODE="enforce"; $env:RATE_LIMIT_LOGIN="5/minute"; uvicorn app.main:app --port 8000
# en otra terminal, desde la raíz
python scraper_tests/05_reto_n_solicitudes.py
```

Muestra 5 solicitudes válidas → 429 en la 6.ª (IP + sesión), que una sesión nueva
sí pasa, el reinicio tras `Retry-After` y el bloqueo por cuenta tras 5 fallos.

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
| POST | `/api/register` | Crea la cuenta (1000 pts + sobre de 5 cartas) y abre sesión |
| POST | `/api/login` · `/api/logout` | Iniciar / cerrar sesión |
| GET | `/api/me` | Usuario actual, saldo, puntos congelados (`{"user": null}` sin sesión) |
| GET | `/api/me/cards` | Mi colección (copias individuales) |
| POST | `/api/me/cards/{id}/sell` | Vender una copia a la casa |
| GET | `/api/me/auctions` | Mis subastas y las subastas en que he pujado |
| GET | `/api/auctions` | Subastas activas: `page`, `source` (`all`/`house`/`users`), `sort` |
| GET | `/api/auctions/{id}` | Detalle + historial de pujas |
| POST | `/api/auctions` | Subastar una carta propia: `owned_card_id`, `duration`, `start_price`, `buyout_price?` |
| POST | `/api/auctions/{id}/bid` · `/buyout` · `/cancel` | Pujar, compra inmediata, cancelar |
| GET | `/api/users/{username}` | Perfil público |

## Mercado de subastas

| Regla | Valor (en `server/app/economy.py`) |
|---|---|
| Saldo inicial / bono diario | 1000 pts / +100 pts (una vez por día UTC, desde el día siguiente al registro) |
| Sobre inicial | 5 cartas al azar, ponderadas por rareza |
| Puja mínima | la actual + 5 % o + 10 pts, lo que sea mayor |
| Anti-sniping | una puja en los últimos 2 min deja la subasta con 2 min por delante |
| Puntos congelados | se descuentan al pujar y se devuelven al instante si alguien te supera |
| Duraciones | 5 min, 1 h, 6 h, 24 h, 3 días; sin pujas, la carta sigue siendo del dueño |
| Cancelar | solo el vendedor y solo si no hay pujas |
| Casa | mantiene 8 subastas activas; sale al doble del precio de recompra y ofrece compra inmediata |
| Venta a la casa | precio fijo por rareza (Común 10 … Rara Secreta 500) |

**Sin procesos en segundo plano** (Vercel no los tiene): las subastas vencidas se
liquidan cuando alguien consulta el mercado, una subasta o un perfil, y las de la
casa se reponen al listar el mercado. Toda operación con puntos ocurre en una
transacción con `SELECT ... FOR UPDATE`, y cada cambio de saldo queda en la tabla
`ledger` (no se muestra, sirve para auditar que los saldos cuadran).

**Defensas en el mercado:** el registro y el login usan el puntaje escalonado y
Turnstile (`security/gate.py`); el login además bloquea la cuenta tras 5 fallos
(guardado en Postgres, no en memoria); pujas y acciones tienen su propio límite y
cada puja deja un evento `bid` con las huellas del cliente en `access.jsonl`.

Atributos estables de las subastas: `data-auction-id`, `data-card-id`, `data-seller`
(`casa` o el usuario), `data-current-bid`, `data-min-next-bid`, `data-buyout`,
`data-bids`, `data-status` y `data-ends-at` (hora exacta de cierre en ISO).

## Atributos estables para el scraper

Cada carta del listado es un `<article>` con:
`data-card-id`, `data-card-name`, `data-type`, `data-collection`,
`data-generation`, `data-rarity`, `data-category`. Estos no cambiarán con el DOM
dinámico del paso 9 (el contenedor ya no tiene `id="card-list"` fijo).
