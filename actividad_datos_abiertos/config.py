"""
Configuración de la actividad de datos abiertos.

Aquí vive todo lo que cambia entre ejecuciones: los 5 sitios asignados, los hosts
autorizados, las pausas y los indicadores que se extraen.

Reglas que el código respeta (ver comun.py):
  * Solo se contactan los hosts de HOSTS_AUTORIZADOS.
  * Se lee robots.txt antes de cada petición y se respeta Disallow y Crawl-delay.
    robots.txt comunica reglas a los rastreadores; NO es una autorización ni una
    garantía de seguridad. Por eso además se revisan los términos de uso.
  * Si un sitio bloquea al navegador automatizado o muestra un CAPTCHA, el script se
    detiene y lo registra. No se reintenta por otra vía ni se oculta la automatización.
  * Volumen mínimo: unas cuantas páginas, sin pruebas de carga ni datos personales.
"""
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
RESULTADOS = CARPETA / "resultados"
CAPTURAS = RESULTADOS / "capturas"
DATOS = CARPETA / "datos"

USER_AGENT = "TAD-EduAudit/1.0 (practica escolar; bajo volumen)"
PAUSA_MINIMA_S = 3         # pausa entre peticiones al mismo host si robots.txt no pide otra
ESPERA_MAX_S = 45          # tiempo máximo de WebDriverWait
TIMEOUT_HTTP_S = 45
INTENTOS_HTTP = 3          # solo ante timeouts, fallos de conexión y errores 5xx

HOSTS_AUTORIZADOS = {
    "www.inegi.org.mx",
    "www.datos.gob.mx", "www.gob.mx",
    "data.worldbank.org", "api.worldbank.org", "datahelpdesk.worldbank.org",
    "data.gov", "catalog.data.gov",
    "www.dof.gob.mx", "dof.gob.mx",
}

# Regla de clasificación fijada antes de medir (01_auditoria.py suma los puntos):
#   +2  el sitio bloquea al navegador automatizado o muestra CAPTCHA
#   +1  hay CDN/WAF visible en los encabezados, sin bloqueo
#   +1  los datos aparecen solo después de ejecutar JavaScript
#   +1  robots.txt pide Crawl-delay
#   +1  robots.txt prohíbe alguna ruta de datos (API o fichas)
#   +1  la API oficial exige token
#   0-1 = básico · 2-3 = intermedio · 4 o más = avanzado
UMBRAL_INTERMEDIO = 2
UMBRAL_AVANZADO = 4

SITIOS = [
    {
        "clave": "inegi",
        "nombre": "INEGI - Datos abiertos",
        "url_actividad": "https://www.inegi.org.mx/datosabiertos/",
        "pagina": "https://www.inegi.org.mx/datosabiertos/",
        "selector_datos": None,                       # el árbol de programas no tiene filas fijas
        "rutas_datos": [],
        "api": {"nombre": "API de Indicadores (BIE/BISE)", "requiere_token": True, "url_prueba": None},
        "documentos": {
            "API": "https://www.inegi.org.mx/servicios/api_indicadores.html",
            "Terminos": "https://www.inegi.org.mx/inegi/terminos.html",
        },
        "navegacion": "Árbol temas > programas > archivos, armado con JavaScript al cargar. "
                      "El HTML inicial solo trae plantillas vacías.",
        "formatos": "CSV y metadatos en descarga masiva por programa; JSON/XML por la API",
        "condiciones": "Términos de uso publicados en inegi.org.mx/inegi/terminos.html",
        "metodo": "API de Indicadores con token gratuito para series, o descarga directa de los "
                  "archivos de Datos Abiertos. Selenium no aporta: el dato ya se publica como archivo.",
    },
    {
        "clave": "datos_gob_mx",
        "nombre": "datos.gob.mx",
        "url_actividad": "https://www.datos.gob.mx/",
        "pagina": "https://www.datos.gob.mx/dataset",
        "selector_datos": None,
        "rutas_datos": ["https://www.datos.gob.mx/api/3/action/package_search"],
        "api": {"nombre": "API CKAN (/api/3/action)", "requiere_token": False,
                "url_prueba": "https://www.datos.gob.mx/api/3/action/package_search?rows=1"},
        "documentos": {"Terminos": "https://www.gob.mx/terminos"},
        "navegacion": "Portal CKAN: buscador, listado /dataset y fichas con recursos descargables.",
        "formatos": "Los recursos que publica cada dependencia (CSV, entre otros)",
        "condiciones": "Términos generales en gob.mx/terminos; licencia indicada por conjunto de datos",
        "metodo": "Descarga manual de los recursos desde la ficha, o solicitar autorización a la "
                  "administración del portal. robots.txt prohíbe /api/ y el navegador automatizado "
                  "recibe Access Denied: no se automatiza.",
    },
    {
        "clave": "worldbank",
        "nombre": "World Bank Open Data",
        "url_actividad": "https://data.worldbank.org/",
        "pagina": "https://data.worldbank.org/indicator/SP.POP.TOTL",
        "selector_datos": ".infinite .item a.country-name",
        "rutas_datos": [],
        "api": {"nombre": "Indicators API v2", "requiere_token": False,
                "url_prueba": "https://api.worldbank.org/v2/country/MX/indicator/SP.POP.TOTL?format=json&per_page=3"},
        "documentos": {
            "API": "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392",
            "Terminos": "https://data.worldbank.org/summary-terms-of-use",
        },
        "navegacion": "Indicadores por tema y por país; cada indicador tiene gráfica, mapa y una "
                      "tabla por país que se llena con JavaScript.",
        "formatos": "CSV, XML y Excel en cada indicador; JSON/XML por la API",
        "condiciones": "CC BY 4.0, con atribución (data.worldbank.org/summary-terms-of-use)",
        "metodo": "API oficial v2: sin clave, valores exactos y paginación documentada. Licencia CC BY 4.0.",
    },
    {
        "clave": "data_gov",
        "nombre": "Data.gov",
        "url_actividad": "https://data.gov/",
        "pagina": "https://catalog.data.gov/?q=water",
        "selector_datos": ".organization-datasets__item",
        "rutas_datos": [],
        "api": {"nombre": "Catalog API (GET /search)", "requiere_token": False,
                "url_prueba": "https://catalog.data.gov/search?q=water&per_page=1"},
        "documentos": {
            "Guia de usuario": "https://data.gov/user-guide/",
            "Politicas": "https://data.gov/privacy-policy/",
        },
        "navegacion": "Portada informativa y catálogo aparte (catalog.data.gov) con búsqueda, "
                      "filtros por organización y paginación por cursor (botón 'Show more results' con after=).",
        "formatos": "Enlaces a CSV, JSON, XML, KML, GeoJSON según el conjunto",
        "condiciones": "Políticas en data.gov/privacy-policy; licencia indicada por conjunto de datos",
        "metodo": "Catalog API JSON (GET /search), sin autenticación, respetando Crawl-delay de 10 s. "
                  "El HTML también trae los resultados: no hace falta navegador. Se omiten los contactos "
                  "que incluye la respuesta para no guardar datos personales.",
    },
    {
        "clave": "dof",
        "nombre": "Diario Oficial de la Federación",
        "url_actividad": "https://www.dof.gob.mx/",
        "pagina": "https://dof.gob.mx/index.php?year=2026&month=11&day=06",
        "selector_datos": "a[href*='nota_detalle.php']",
        "rutas_datos": ["https://dof.gob.mx/nota_detalle.php?codigo=5803257&fecha=06/11/2026"],
        "api": None,
        "documentos": {"Mapa del sitio": "https://dof.gob.mx/mapa.php",
                       "Busqueda avanzada": "https://dof.gob.mx/busqueda_avanzada.php"},
        "navegacion": "Índice por fecha (?year&month&day), secciones por dependencia y búsqueda avanzada.",
        "formatos": "HTML; imágenes y documentos por nota",
        "condiciones": "No se localizaron: el enlace AVISO LEGAL de la portada está vacío y la Ayuda da 404",
        "metodo": "Petición HTTP al índice de una fecha, solo títulos. robots.txt prohíbe las fichas "
                  "nota_detalle.php, así que no se visitan. Usar dof.gob.mx: el certificado no cubre www.",
    },
]

# Extracción con Selenium: indicadores públicos del World Bank
URL_INDICADOR = "https://data.worldbank.org/indicator/{id}"
INDICADORES = {
    "SP.POP.TOTL": "Poblacion total",
    "SP.DYN.LE00.IN": "Esperanza de vida al nacer (anios)",
    "NY.GDP.PCAP.CD": "PIB per capita (US$ corrientes)",
    "IT.NET.USER.ZS": "Personas que usan Internet (% poblacion)",
}
