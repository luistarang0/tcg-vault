"""
Configuración del bot de extracción (Fase 3).

Todo lo que cambia entre ejecuciones vive aquí, y casi todo se puede
sobrescribir desde la línea de comandos (ver `python bot_portal.py --help`).

El bot está pensado para portales CKAN (datos.gob.mx/busca, y la mayoría de
portales de datos abiertos de gobierno usan CKAN). Para usar otro portal CKAN
basta con cambiar BASE_URL.
"""
from pathlib import Path

# --- Sitio objetivo -----------------------------------------------------------
# Raíz del CKAN. Portales revisados (15/10/2026):
#   https://datos.gob.mx/busca   -> Akamai responde "Access Denied" al navegador
#                                   automatizado (bloqueo del WAF): no se puede usar.
#   https://datos.cdmx.gob.mx    -> CKAN 2.11, pero su robots.txt no permite las búsquedas.
#   https://datos.gob.ar         -> CKAN 2.11 (Portal Andino). robots.txt permite /dataset,
#                                   búsquedas y paginación; pide Crawl-Delay de 10 s.
BASE_URL = "https://datos.gob.ar"
RUTA_INICIO = "/"                    # portada: tiene el buscador y suele cargar rápido (caché)
RUTA_BUSQUEDA = "/dataset"           # página de resultados de búsqueda

# --- Qué buscar ---------------------------------------------------------------
TERMINO_BUSQUEDA = "salud"
# Filtro (faceta) que se aplica haciendo clic en la barra lateral.
# Parámetros típicos de CKAN: res_format (formato), organization, groups, tags, license_id.
# En datos.gob.ar las facetas son organization, groups y tags ("salud" = Ministerio de Salud).
FILTRO_PARAMETRO = "organization"
FILTRO_VALOR = "salud"

# --- Límites (uso responsable) --------------------------------------------------
MAX_PAGINAS = 3                      # páginas de resultados a recorrer (20 por página)
MAX_DETALLES = 10                    # fichas de detalle a visitar (0 = ninguna)
PAUSA_MIN = 2.0                      # segundos mínimos entre cargas de página
PAUSA_MAX = 5.0                      # segundos máximos (pausa aleatoria = más "humana")
TIMEOUT_ESPERA = 20                  # segundos máximos de WebDriverWait

# --- Identificación del bot ---------------------------------------------------
# Se agrega al User-Agent real del navegador para que el sitio sepa quién es.
BOT_ID = "TCGVaultEduBot/0.1 (proyecto escolar; scraping educativo, bajo volumen)"

# --- Salidas ------------------------------------------------------------------
CARPETA_DATOS = Path(__file__).resolve().parent / "datos"
CARPETA_CAPTURAS = Path(__file__).resolve().parent / "capturas"
