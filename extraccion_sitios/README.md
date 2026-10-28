# Extracción de sitios auditados (TAD 2.4)

Script de Selenium que extrae los **catálogos públicos** de los sitios que la auditoría
clasificó como de extracción viable, y un proceso de limpieza con pandas que deja los
datos en **SQLite, CSV y Excel**.

| Sitio | Qué se extrae | Cómo se navega |
|---|---|---|
| Porké (cochinita-pibil-pwa.vercel.app) | Menú por categoría + ficha de cada producto (calorías, porción, ingredientes) | Secciones `h2` → tarjetas → ficha `/products/<id>` |
| Café & Charla (cafe-charla-app.vercel.app) | Menú y promociones | Atributos con **nombre** aleatorio y valor estable: XPath `//*[@*='menu-item']` |
| TicketShield (ticketshield-ihy6.onrender.com) | Eventos (categoría, lugar, duración, fecha) + tipos de boleto con precio | Paginación con clic en "Siguiente" + fichas `/event/<slug>` |
| TCG Vault (sitio propio) | Catálogo de cartas y subastas activas | Contrato estable `data-*` + enlace `rel="next"` |

Fuera del alcance, a propósito: **SurgePath** (datos de salud) y **Clara** (finanzas
personales). Ambos están detrás del login y sus datos son sensibles según la LFPDPPP.

## Archivos

| Archivo | Responsabilidad |
|---|---|
| `config.py` | Sitios permitidos, pausas, límites de páginas y fichas |
| `extractor.py` | Selenium: navegación, esperas explícitas, paginación, fichas, reintentos y capturas |
| `limpieza.py` | pandas: tipos, precios, fechas, duplicados y atípicos → SQLite/CSV/Excel |
| `datos/crudos_<fecha>.json` | Texto tal como aparece en cada página |
| `datos/extraccion_sitios.sqlite` | Base final con llaves primarias, foráneas y vistas |
| `datos/limpios/*.csv`, `datos/dataset_limpio.xlsx` | Las mismas tablas en CSV y Excel |
| `capturas/<fecha>/*.png` | Evidencia de cada sitio |

## Uso

Desde la raíz del proyecto, con el `.venv` activado (Chrome o Edge instalados):

```powershell
python extraccion_sitios/extractor.py              # los 4 sitios (~10 min por las pausas)
python extraccion_sitios/extractor.py --headless   # sin ventana
python extraccion_sitios/extractor.py --rapido     # prueba corta: 2 páginas y 3 fichas por sitio
python extraccion_sitios/extractor.py --sitios cafe porke
python extraccion_sitios/limpieza.py               # procesa el crudo más reciente
```

## Base de datos

| Tabla | Llave | Contenido |
|---|---|---|
| `sitios` | `clave` | Sitio, tecnología, clasificación de la auditoría, estado y duración de la extracción |
| `productos` | `sitio, id_externo` | Productos de Porké y Café & Charla: precio, moneda, calorías, porción, ingredientes, disponibilidad, `precio_atipico` |
| `promociones` | `sitio, titulo` | Descuento en %, vigencia (inicio, fin, días) |
| `eventos` | `slug` | Categoría, lugar, dirección, duración en minutos, fecha ISO, `anio_inferido`, precio mínimo y máximo |
| `boletos` | `evento_slug, tipo, precio` | Tipos de boleto por evento (relación 1 a N con `eventos`) |
| `cartas` | `id` | Cartas de TCG Vault: tipos, tipo principal, rareza, colección, número, generación, PS |
| `subastas` | `id` | Subastas activas: vendedor, pujas, compra inmediata, hora de cierre (UTC) |

Vistas para el análisis: `v_resumen_sitios`, `v_precios_productos`,
`v_eventos_por_categoria` y `v_cartas_por_rareza`.

```sql
SELECT * FROM v_eventos_por_categoria;
SELECT sitio, nombre, precio FROM productos WHERE precio_atipico = 1;
```

## Decisiones de limpieza

- **Moneda:** solo Café & Charla declara pesos mexicanos. En Porké y TicketShield queda `no_indicada`, porque no se inventa una moneda.
- **Formato de precios:** `$ 26.000,00` usa punto de miles y coma decimal; se convierte a `26000.0`. `Gratis` → `0`.
- **Año de los eventos:** las tarjetas del listado no traen año. Si se visitó la ficha, se usa su fecha completa. Si no, se infiere el año más cercano a la fecha de extracción y se marca `anio_inferido = 1`.
- **Precios atípicos:** se marcan (no se borran) los que superan tres veces la mediana de su sitio o quedan por debajo de un tercio. Por ejemplo, un producto de prueba de Porké a $50 entre platillos de $2 a $10.
- **Fichas de TicketShield:** se visitan las primeras 100 de unos 260 eventos, por cortesía con un servidor del plan gratuito de Render. El resto conserva los datos del listado y deja nulos el precio y los boletos.
- **Datos personales:** no se guardan teléfonos, nombres de personas ni contenido del foro o de las reseñas.

## Uso responsable

- Solo se navega a los hosts de `config.ALLOWED_HOSTS`.
- Se consulta `robots.txt` antes de cada sitio y se respetan sus reglas.
- Hay una pausa de 1.5 s entre páginas y un número máximo de páginas y fichas.
- No se inicia sesión, no se envían formularios y no se evade ninguna defensa: el navegador se identifica como automatizado (`navigator.webdriver = true`).
