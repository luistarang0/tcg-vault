"""
Bot de extracción con Selenium para portales de datos abiertos CKAN (Fase 3).

Qué hace, en orden:
  1. Revisa robots.txt del portal y se niega a visitar rutas no permitidas.
  2. Abre la página de búsqueda, escribe el término en el buscador y lo envía.
  3. Aplica un filtro haciendo clic en la faceta de la barra lateral (ej. formato CSV).
  4. Recorre N páginas de resultados con el enlace "siguiente" (»).
  5. Visita la ficha de detalle de los primeros M conjuntos de datos.
  6. Guarda los datos CRUDOS en datos/crudos_<fecha>.json y .csv
     (la limpieza con Pandas la hace limpieza.py).

Uso responsable integrado:
  * Esperas explícitas (WebDriverWait) en lugar de time.sleep fijos para esperar al DOM.
  * Pausas aleatorias entre páginas (PAUSA_MIN-PAUSA_MAX) y Crawl-delay de robots.txt.
  * Localizadores robustos: CSS/XPath por clases semánticas y atributos (href, data-*),
    nunca rutas XPath absolutas (/html/body/div[3]/...).
  * User-Agent identificable (se agrega BOT_ID al del navegador).
  * Si aparece un desafío (CAPTCHA, Cloudflare, "verifica que eres humano") el bot
    NO intenta resolverlo ni evadirlo: se detiene y pide intervención humana.
  * No se ocultan las huellas de automatización (navigator.webdriver sigue en true).

Ejemplos:
    python bot_portal.py                                  # usa config.py
    python bot_portal.py --termino "educacion" --paginas 2 --detalles 10
    python bot_portal.py --filtro-param organization --filtro-valor imss
    python bot_portal.py --base-url http://localhost:5050/busca   # simulador local
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import quote_plus, urljoin, urlparse
from pathlib import Path
from urllib.robotparser import RobotFileParser

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config

# ---------------------------------------------------------------------------
# Localizadores. Cada elemento tiene una lista de alternativas que se prueban en
# orden: si el portal personalizó la plantilla de CKAN, la siguiente suele servir.
# Se basan en clases y atributos SEMÁNTICOS de CKAN 2.9/2.10/2.11.
# ---------------------------------------------------------------------------
LOC = {
    # Buscador principal
    "buscador": [
        (By.CSS_SELECTOR, "#field-giant-search"),
        (By.CSS_SELECTOR, "form.search-form input[name='q']"),
        (By.CSS_SELECTOR, "input[name='q']"),
    ],
    # Texto "N conjuntos de datos encontrados"
    "total": [
        (By.CSS_SELECTOR, "form.search-form h1"),
        (By.CSS_SELECTOR, "form.search-form h2"),
        (By.XPATH, "//*[self::h1 or self::h2 or self::p or self::div][not(*)]"
                   "[contains(., 'encontrad') or contains(., 'found') or contains(., 'resultados')]"),
    ],
    # Cada resultado de la lista
    "resultado": [
        (By.CSS_SELECTOR, "ul.dataset-list > li.dataset-item"),
        (By.CSS_SELECTOR, "li.dataset-item"),
        (By.CSS_SELECTOR, ".dataset-item"),                 # temas como Portal Andino (div/a)
        (By.CSS_SELECTOR, "[class*='dataset-item']"),
    ],
    # Dentro de un resultado (búsquedas relativas al <li>)
    "res_titulo": [
        (By.CSS_SELECTOR, ".dataset-heading a"),
        (By.XPATH, ".//h2/a | .//h3/a"),
        (By.CSS_SELECTOR, ".dataset-title, .dataset-heading"),
        (By.XPATH, ".//h2 | .//h3"),
    ],
    "res_descripcion": [
        (By.CSS_SELECTOR, ".dataset-notes"),
        (By.CSS_SELECTOR, ".dataset-content > div:not(.dataset-author)"),
        (By.CSS_SELECTOR, ".dataset-content > p:not(.empty)"),
        (By.XPATH, ".//p[not(contains(@class,'empty'))]"),
    ],
    "res_organizacion": [
        (By.CSS_SELECTOR, ".dataset-author"),
        (By.CSS_SELECTOR, ".dataset-organization"),
    ],
    "res_formatos": [
        (By.CSS_SELECTOR, "ul.dataset-resources a[data-format]"),
        (By.CSS_SELECTOR, "ul.dataset-resources li a"),
        (By.CSS_SELECTOR, "[data-format]"),
        (By.CSS_SELECTOR, ".dataset-resources .label, .dataset-resources span"),
    ],
    # Enlace a la página siguiente (CKAN usa "»"; algunos temas usan texto)
    "siguiente": [
        (By.XPATH, "//*[contains(@class,'pagination')]//a[normalize-space(.)='»']"),
        (By.XPATH, "//*[contains(@class,'pagination')]//a[@rel='next' or normalize-space(.)='>' "
                   "or contains(normalize-space(.),'Siguiente') or contains(normalize-space(.),'Next')]"),
    ],
    # Ficha de detalle
    "det_titulo": [
        (By.CSS_SELECTOR, "article.module h1"),
        (By.CSS_SELECTOR, ".module-content h1"),
        (By.TAG_NAME, "h1"),
    ],
    "det_organizacion": [
        (By.CSS_SELECTOR, "ol.breadcrumb a[href*='/organization/']"),
        (By.CSS_SELECTOR, ".breadcrumb a[href*='/organization/']"),
        (By.CSS_SELECTOR, "section.module-narrow .heading, aside .organization h1"),
    ],
    "det_filas_info": [
        (By.CSS_SELECTOR, "section.additional-info table tbody tr"),
        (By.XPATH, "//section[contains(@class,'additional-info')]//tr[th and td]"),
        (By.XPATH, "//table//tr[th and td]"),
    ],
    "det_recursos": [
        (By.CSS_SELECTOR, "ul.resource-list > li.resource-item"),
        (By.CSS_SELECTOR, "li.resource-item"),
    ],
    "det_etiquetas": [
        (By.CSS_SELECTOR, "ul.tag-list a"),
        (By.CSS_SELECTOR, ".tags a"),
    ],
}

# Etiquetas de la "Información adicional" en temas que no usan tabla (Portal Andino)
ETIQUETAS_INFO = ["Fecha de publicación", "Última actualización", "Fecha de actualización",
                  "Última modificación", "Frecuencia de actualización", "Licencia", "Mantenedor",
                  "Autor", "Fuente", "Etiquetas", "Creado", "Last Updated", "Created"]

# Para cada etiqueta: busca un elemento cuyo texto propio sea exactamente esa etiqueta y
# devuelve el texto de su siguiente hermano (la celda/columna del valor).
JS_PARES_ETIQUETA_VALOR = """
const etiquetas = arguments[0], out = {};
for (const el of document.querySelectorAll('body *')) {
  if (el.children.length > 2) continue;
  const t = (el.innerText || '').trim().replace(/\\s+/g, ' ');
  if (etiquetas.includes(t) && !(t in out)) {
    let v = el.nextElementSibling;
    if (!v && el.parentElement) v = el.parentElement.nextElementSibling;
    if (v && v.innerText.trim()) out[t] = v.innerText.trim();
  }
}
return out;
"""

# Bloqueo definitivo del WAF/CDN (no hay desafío que resolver): el bot se detiene
SENALES_BLOQUEO = ["access denied", "acceso denegado", "403 forbidden", "request blocked",
                   "you don't have permission to access", "errors.edgesuite.net"]

# Señales de que la página es un desafío anti-bot y no contenido real
# (frases completas para no confundir un conjunto de datos que mencione "captcha")
SENALES_TITULO = ["just a moment", "attention required", "access denied", "acceso denegado",
                  "too many requests", "demasiadas solicitudes", "verificación de seguridad"]
SENALES_IFRAME = ["challenges.cloudflare.com", "recaptcha", "hcaptcha", "turnstile"]
SENALES_TEXTO = ["verify you are human", "verifica que eres humano", "no soy un robot",
                 "i'm not a robot", "complete the security check", "too many requests"]


ARCHIVO_LOG: Path | None = None   # se define al iniciar: capturas/<fecha>/registro.txt


def log(msg: str) -> None:
    """Mensaje con hora en la terminal y en el registro de la ejecución."""
    linea = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(linea, flush=True)
    if ARCHIVO_LOG:
        with ARCHIVO_LOG.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")


class ServidorNoDisponible(Exception):
    """El portal responde errores 5xx de forma persistente."""


class DesafioNoResuelto(Exception):
    """El sitio presentó un desafío y nadie lo resolvió: se detiene la extracción."""


class BotPortal:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.base = args.base_url.rstrip("/")
        self.pausa_min = config.PAUSA_MIN
        self.pausa_max = config.PAUSA_MAX
        self.robots: RobotFileParser | None = None
        self.robots_estado = "no revisado"
        self.url_busqueda = ""
        self.filtro_estado = "sin filtro"
        self.paso_captura = 0
        config.CARPETA_DATOS.mkdir(exist_ok=True)
        self.sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.carpeta_capturas = config.CARPETA_CAPTURAS / self.sello      # una carpeta por ejecución
        self.carpeta_capturas.mkdir(parents=True, exist_ok=True)
        global ARCHIVO_LOG
        ARCHIVO_LOG = self.carpeta_capturas / "registro.txt"
        log(f"Inicio: portal={self.base} término='{args.termino}' filtro={args.filtro_param}="
            f"{args.filtro_valor} páginas={args.paginas} fichas={args.detalles}")
        log("Aviso: entre cada página el bot hace pausas (más largas si el sitio pide Crawl-delay). "
            "Si la ventana se ve en blanco unos segundos, es normal: NO la cierres.")
        self.driver = self._crear_driver()
        self.wait = WebDriverWait(self.driver, config.TIMEOUT_ESPERA)

    # ------------------------------------------------------------------ setup
    def _crear_driver(self):
        """Abre el navegador. Prueba en orden: Chrome (Selenium Manager), Chrome
        (webdriver-manager) y Microsoft Edge, e informa por qué falló cada opción."""
        def opciones(clase):
            o = clase()
            if self.args.headless:
                o.add_argument("--headless=new")
            o.add_argument("--window-size=1366,900")
            o.add_argument("--lang=es-MX")
            # "eager": driver.get() regresa cuando el HTML está listo (DOMContentLoaded),
            # sin esperar imágenes, fuentes ni scripts de analítica de terceros, que en
            # algunos portales tardan más de un minuto. Las esperas explícitas hacen el resto.
            o.page_load_strategy = "eager"
            if sys.platform.startswith("linux"):
                o.add_argument("--no-sandbox")
            return o

        def chrome(service):
            o = opciones(webdriver.ChromeOptions)
            if self.args.chrome_bin:
                o.binary_location = self.args.chrome_bin
            return webdriver.Chrome(service=service, options=o)

        def chrome_wdm():
            from webdriver_manager.chrome import ChromeDriverManager
            return chrome(Service(ChromeDriverManager().install()))

        def edge():
            from selenium.webdriver.edge.service import Service as EdgeService
            return webdriver.Edge(service=EdgeService(), options=opciones(webdriver.EdgeOptions))

        nav = self.args.navegador
        intentos = []
        if self.args.driver:
            intentos.append(("Chrome con el driver indicado", lambda: chrome(Service(self.args.driver))))
        if nav in ("auto", "chrome"):
            intentos += [("Chrome con Selenium Manager", lambda: chrome(Service())),
                         ("Chrome con webdriver-manager", chrome_wdm)]
        if nav in ("auto", "edge"):
            intentos.append(("Microsoft Edge con Selenium Manager", edge))

        driver = None
        for nombre, abrir in intentos:
            try:
                driver = abrir()
                break
            except Exception as e:  # noqa: BLE001 - se informa y se prueba la siguiente opción
                causa = (getattr(e, "msg", None) or str(e)).strip().splitlines()[0][:160]
                log(f"  x {nombre}: {e.__class__.__name__}: {causa}")
        if driver is None:
            raise SystemExit("No se pudo abrir ningún navegador (instala Google Chrome o actualiza Edge).")

        driver.set_page_load_timeout(90)        # tiempo máximo para que llegue el HTML

        # User-Agent honesto: el del navegador + identificación del proyecto
        ua = driver.execute_script("return navigator.userAgent")
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": f"{ua} {config.BOT_ID}"})
        self.driver_nombre = f"{driver.capabilities.get('browserName')} {driver.capabilities.get('browserVersion')}"
        log(f"Navegador listo: {driver.capabilities.get('browserName')} "
            f"{driver.capabilities.get('browserVersion')} ({nombre}). "
            f"navigator.webdriver = {driver.execute_script('return navigator.webdriver')}")
        return driver

    # --------------------------------------------------------------- ética
    def _descargar_robots(self, url: str) -> tuple[int, str]:
        """Descarga robots.txt con el MISMO User-Agent del navegador (incluye BOT_ID).
        Devuelve (código HTTP, texto). Código 0 = error de red."""
        ua = self.driver.execute_script("return navigator.userAgent")
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "text/plain,*/*",
                                                   "Accept-Language": "es-MX,es;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception as e:  # noqa: BLE001 - sin red, DNS, TLS
            log(f"  no se pudo descargar robots.txt directamente ({e.__class__.__name__})")
            return 0, ""

    def _robots_con_navegador(self, url: str) -> str | None:
        """Plan B: abre robots.txt en el navegador (algunos WAF rechazan clientes que no
        ejecutan JavaScript, pero sí entregan el archivo al navegador)."""
        try:
            self.driver.get(url)
            texto = self.driver.find_element(By.TAG_NAME, "body").text
        except Exception:  # noqa: BLE001
            return None
        return texto if re.search(r"(?im)^\s*user-agent\s*:", texto) else None

    def cargar_robots(self) -> None:
        """Lee robots.txt y aplica sus reglas y Crawl-delay, según el estándar RFC 9309:
          * 200        -> se respetan las reglas publicadas.
          * 4xx        -> "no disponible": el estándar permite rastrear sin restricciones;
                          aun así el bot mantiene volumen bajo y pausas más largas.
          * 5xx / red  -> "inaccesible": se asume que NO se permite y el bot se detiene.
        """
        parsed = urlparse(self.base)
        url_robots = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        codigo, texto = self._descargar_robots(url_robots)

        if codigo in (401, 403, 0):
            log(f"robots.txt respondió {codigo or 'error'} a la descarga directa; se intenta con el navegador.")
            via_nav = self._robots_con_navegador(url_robots)
            if via_nav:
                codigo, texto = 200, via_nav
                self.manejar_desafio()

        if codigo == 200:
            rp.parse(texto.splitlines())
            reglas = sum(1 for l in texto.splitlines() if l.strip().lower().startswith("disallow:"))
            log(f"robots.txt leído ({reglas} reglas Disallow): {url_robots}")
            self.robots_estado = f"200, {reglas} reglas Disallow"
        elif 400 <= codigo < 500:
            rp.allow_all = True
            self.pausa_min, self.pausa_max = max(self.pausa_min, 4.0), max(self.pausa_max, 7.0)
            log(f"robots.txt no disponible ({codigo}). RFC 9309: sin reglas publicadas no hay "
                f"restricciones; se usan pausas conservadoras de {self.pausa_min}-{self.pausa_max}s.")
            self.robots_estado = f"{codigo} (no disponible, RFC 9309)"
        else:
            raise SystemExit(f"robots.txt inaccesible ({codigo or 'sin conexión'}). "
                             "RFC 9309 indica asumir que no se permite rastrear: el bot se detiene.")

        delay = rp.crawl_delay(config.BOT_ID) or rp.crawl_delay("*")
        if delay and float(delay) > self.pausa_min:
            self.pausa_min = float(delay)
            self.pausa_max = max(self.pausa_max, self.pausa_min + 2)
            log(f"Crawl-delay de {delay}s: pausas ajustadas a {self.pausa_min}-{self.pausa_max}s.")
        self.robots = rp

    def permitido(self, url: str) -> bool:
        return self.robots is None or self.robots.can_fetch(config.BOT_ID, url)

    def pausa(self, motivo: str = "") -> None:
        """Pausa aleatoria entre cargas: reduce carga al servidor y se parece a una persona."""
        s = random.uniform(self.pausa_min, self.pausa_max)
        log(f"  pausa {s:.1f}s {motivo}".rstrip())
        time.sleep(s)

    # ---------------------------------------------------------- utilidades
    def encontrar(self, clave: str, raiz=None, todos: bool = False):
        """Prueba los localizadores alternativos de LOC[clave] hasta que uno funcione."""
        raiz = raiz or self.driver
        for by, sel in LOC[clave]:
            try:
                if todos:
                    els = raiz.find_elements(by, sel)
                    if els:
                        return els
                else:
                    return raiz.find_element(by, sel)
            except NoSuchElementException:
                continue
        return [] if todos else None

    def esperar(self, clave: str, timeout: int | None = None):
        """Espera explícita hasta que aparezca cualquiera de los localizadores de `clave`."""
        condiciones = [EC.presence_of_element_located(loc) for loc in LOC[clave]]
        w = WebDriverWait(self.driver, timeout or config.TIMEOUT_ESPERA)
        return w.until(EC.any_of(*condiciones))

    def clic_seguro(self, el) -> None:
        """Desplaza el elemento a la vista y hace clic; si algo lo tapa, usa clic por JS."""
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        try:
            self.wait.until(EC.element_to_be_clickable(el)).click()
        except (ElementClickInterceptedException, TimeoutException):
            self.driver.execute_script("arguments[0].click();", el)

    def captura(self, nombre: str) -> None:
        """Guarda una captura de pantalla numerada como evidencia."""
        self.paso_captura += 1
        ruta = self.carpeta_capturas / f"{self.paso_captura:02d}_{nombre}.png"
        self.driver.save_screenshot(str(ruta))

    # ------------------------------------------------- desafíos / intervención
    def detectar_desafio(self) -> str | None:
        """Devuelve el motivo si la página actual parece un desafío anti-bot."""
        titulo = (self.driver.title or "").lower()
        for s in SENALES_TITULO:
            if s in titulo:
                return f"título de la página: '{self.driver.title}'"
        for f in self.driver.find_elements(By.TAG_NAME, "iframe"):
            src = (f.get_attribute("src") or "").lower()
            if any(s in src for s in SENALES_IFRAME):
                return f"iframe de desafío ({src[:60]})"
        try:
            texto = self.driver.find_element(By.TAG_NAME, "body").text.lower()[:3000]
        except NoSuchElementException:
            texto = ""
        for s in SENALES_TEXTO:
            if s in texto:
                return f"texto en la página: '{s}'"
        return None

    def es_bloqueo(self) -> bool:
        """True si la página es un rechazo definitivo (p. ej. 'Access Denied' de Akamai)."""
        try:
            texto = (self.driver.title + " " + self.driver.find_element(By.TAG_NAME, "body").text).lower()
        except NoSuchElementException:
            texto = (self.driver.title or "").lower()
        return any(s in texto for s in SENALES_BLOQUEO)

    def manejar_desafio(self) -> None:
        """Si hay desafío: espera en un 429, o pide a una persona que lo resuelva."""
        for intento in range(1, 4):
            motivo = self.detectar_desafio()
            if not motivo:
                return
            self.captura("desafio_detectado")

            if self.es_bloqueo():
                log(f"BLOQUEO DEL SITIO: {motivo}. Es un rechazo del WAF/CDN, no un desafío: "
                    "no hay nada que resolver y el bot no intenta evadirlo.")
                raise DesafioNoResuelto(f"bloqueo del WAF ({motivo})")

            if "too many" in motivo.lower() or "demasiadas" in motivo.lower():
                espera = 60 * intento
                log(f"El servidor pide bajar el ritmo ({motivo}). Esperando {espera}s y reintentando.")
                time.sleep(espera)
                self.driver.refresh()
                continue

            log(f"DESAFÍO DETECTADO: {motivo}")
            if self.args.headless or not sys.stdin.isatty():
                raise DesafioNoResuelto(f"{motivo} (sin ventana visible para intervención humana)")
            print("\n" + "=" * 70)
            print(" INTERVENCIÓN HUMANA REQUERIDA")
            print(" El sitio mostró un desafío. El bot NO lo resolverá automáticamente.")
            print(" 1) Resuélvelo tú en la ventana de Chrome.")
            print(" 2) Regresa aquí y presiona Enter para continuar (o escribe 'q' para salir).")
            print("=" * 70)
            if input("> ").strip().lower() == "q":
                raise DesafioNoResuelto("la persona decidió detener la extracción")
        if self.detectar_desafio():
            raise DesafioNoResuelto("el desafío sigue presente tras 3 intentos")


    def _cargar(self, url: str) -> None:
        t0 = time.perf_counter()
        try:
            self.driver.get(url)
        except TimeoutException:
            # El HTML tardó demasiado: se detiene la carga y se trabaja con lo que haya llegado.
            log(f"  la página tardó más de 90 s; se detiene la carga y se continúa ({url})")
            self.driver.execute_script("window.stop();")
        log(f"  cargada en {time.perf_counter() - t0:.1f}s: {self.driver.current_url} "
            f"(título: '{self.driver.title[:50]}')")

    def error_servidor(self) -> str | None:
        """Detecta páginas de error 5xx del servidor (p. ej. '504: Gateway time-out')."""
        t = (self.driver.title or "").lower()
        m = re.search(r"\b(50[0-4])\b", t)
        if m or "gateway" in t or "service unavailable" in t or "bad gateway" in t:
            return m.group(1) if m else "5xx"
        return None

    def ir(self, url: str, motivo: str = "") -> None:
        """Navega respetando robots.txt, con pausa previa, reintentos ante errores del
        servidor (5xx) con espera creciente, y revisión de desafíos."""
        if not self.permitido(url):
            raise PermissionError(f"robots.txt no permite visitar {url}")
        self.pausa(motivo)
        self._cargar(url)
        for intento, espera in enumerate((30, 60, 90), start=1):
            codigo = self.error_servidor()
            if not codigo:
                break
            log(f"  el servidor respondió {codigo} (sobrecargado). Reintento {intento}/3 en {espera}s; "
                "esperar más entre intentos evita sobrecargarlo aún más.")
            time.sleep(espera)
            self._cargar(url)
        else:
            if self.error_servidor():
                raise ServidorNoDisponible(f"{url} sigue respondiendo error {self.error_servidor()} tras 3 reintentos")
        self.manejar_desafio()

    # ------------------------------------------------------------- navegación
    def buscar(self, termino: str) -> None:
        """Abre la búsqueda y escribe el término en el buscador como lo haría una persona.
        Si la página no tiene buscador propio (algunos temas de CKAN lo ponen solo en la
        portada), se navega directo a la URL de búsqueda ?q=..."""
        self.ir(self.base + config.RUTA_INICIO, "(abrir portada con buscador)")
        try:
            self.esperar("buscador", timeout=10)    # espera explícita al buscador
            caja = self.encontrar("buscador")
            caja.clear()
            for letra in termino:                   # tecleo con ritmo humano
                caja.send_keys(letra)
                time.sleep(random.uniform(0.05, 0.18))
            anterior = self.driver.current_url
            caja.send_keys(Keys.ENTER)
            self.wait.until(lambda d: d.current_url != anterior and "q=" in d.current_url)
        except TimeoutException:
            url = f"{self.base}{config.RUTA_BUSQUEDA}?q={quote_plus(termino)}"
            log("No hay buscador en esta página; se usa la URL de búsqueda directamente.")
            self.ir(url, "(búsqueda por URL)")
        if not self.permitido(self.driver.current_url):
            raise PermissionError(f"robots.txt no permite las búsquedas ({self.driver.current_url})")
        self.manejar_desafio()
        self.esperar_resultados()
        self.url_busqueda = self.driver.current_url
        log(f"Búsqueda '{termino}': {self.leer_total()}")
        self.captura("busqueda")

    def aplicar_filtro(self, parametro: str, valor: str) -> bool:
        """Hace clic en la faceta cuyo enlace agrega `parametro=valor` a la URL."""
        sel_css = f"a[href*='{parametro}={quote_plus(valor)}']"
        candidatos = (self.driver.find_elements(By.CSS_SELECTOR, f".nav-facet {sel_css}")
                      or self.driver.find_elements(By.CSS_SELECTOR, f"section.module {sel_css}")
                      or [a for a in self.driver.find_elements(By.CSS_SELECTOR, sel_css)
                          if "page=" not in (a.get_attribute("href") or "")])
        if not candidatos:
            log(f"No se encontró el filtro {parametro}={valor} en la barra lateral; se omite.")
            return False
        enlace = candidatos[0]
        lbl = enlace.find_elements(By.CSS_SELECTOR, ".item-label, span")
        etiqueta = (lbl[0].text if lbl else enlace.text).strip() or valor
        destino = enlace.get_attribute("href")
        primero = self.encontrar("resultado")
        self.pausa("(antes de aplicar filtro)")
        self.clic_seguro(enlace)
        self._despues_de_clic(primero, destino)
        self.wait.until(EC.url_contains(f"{parametro}="))
        self.esperar_resultados()
        self.filtro_estado = f"{parametro}={valor} ({etiqueta})"
        log(f"Filtro aplicado ({etiqueta}): {self.leer_total()}")
        self.captura("filtro")
        return True

    def _despues_de_clic(self, primero, destino: str | None) -> None:
        """Tras un clic que navega: espera a que la lista vieja desaparezca y, si el
        servidor respondió un error 5xx, reintenta esa misma URL con espera creciente."""
        if primero is not None:
            try:
                self.wait.until(EC.staleness_of(primero))     # la lista vieja desaparece
            except TimeoutException:
                pass                                          # la página sigue cargando
        try:
            WebDriverWait(self.driver, 90).until(
                lambda d: d.execute_script("return document.readyState") != "loading")
        except TimeoutException:
            self.driver.execute_script("window.stop();")
        if self.error_servidor() and destino:
            log(f"  el servidor respondió {self.error_servidor()} tras el clic; se reintenta la misma página.")
            self.ir(destino, "(reintento)")
        else:
            self.manejar_desafio()

    def esperar_resultados(self) -> None:
        """Espera a que aparezca la lista de resultados o el texto con el total."""
        condiciones = [EC.presence_of_element_located(loc) for loc in LOC["resultado"] + LOC["total"]]
        self.wait.until(EC.any_of(*condiciones))

    def leer_total(self) -> str:
        el = self.encontrar("total")
        if el is None:
            visibles = len(self.encontrar("resultado", todos=True))
            return f"{visibles} resultados visibles (el portal no muestra el total)"
        numeros = [int(re.sub(r"[,\.]", "", n)) for n in re.findall(r"\d[\d,\.]*", el.text)]
        return f"{max(numeros) if numeros else 0} resultados"

    def extraer_pagina(self, num_pagina: int) -> list[dict]:
        """Lee todos los resultados visibles de la página actual."""
        try:
            self.esperar("resultado", timeout=10)
        except TimeoutException:
            return []
        filas = []
        for pos, li in enumerate(self.encontrar("resultado", todos=True), start=1):
            try:
                a = self.encontrar("res_titulo", raiz=li)
                desc = self.encontrar("res_descripcion", raiz=li)
                org = self.encontrar("res_organizacion", raiz=li)
                formatos = [(f.get_attribute("data-format") or f.text).strip()
                            for f in self.encontrar("res_formatos", raiz=li, todos=True)]
                url = a.get_attribute("href") if a is not None else None
                if not url:
                    if li.tag_name == "a":
                        url = li.get_attribute("href")
                    else:
                        enlaces = li.find_elements(By.CSS_SELECTOR, "a[href*='/dataset/']")
                        url = enlaces[0].get_attribute("href") if enlaces else None
                filas.append({
                    "pagina": num_pagina,
                    "posicion": pos,
                    "titulo": a.text if a is not None else None,
                    "url": url,
                    "descripcion": desc.text if desc else None,
                    "organizacion_lista": org.text if org else None,
                    "formatos": formatos,
                    "extraido_en": datetime.now().isoformat(timespec="seconds"),
                })
            except StaleElementReferenceException:
                continue                                   # el DOM cambió: se salta ese elemento
        return filas

    def siguiente_pagina(self) -> bool:
        """Hace clic en '»'. Devuelve False si ya no hay más páginas."""
        enlace = self.encontrar("siguiente")
        if enlace is None:
            return False
        destino = enlace.get_attribute("href")
        if destino and not self.permitido(destino):
            log("robots.txt no permite la siguiente página; se detiene la paginación.")
            return False
        primero = self.encontrar("resultado")
        self.pausa("(siguiente página)")
        self.clic_seguro(enlace)
        self._despues_de_clic(primero, destino)
        self.esperar_resultados()
        return True

    def extraer_detalle(self, url: str) -> dict:
        """Visita la ficha de un conjunto de datos y lee su tabla de información adicional."""
        self.ir(url, "(ficha de detalle)")
        self.esperar("det_titulo")
        det: dict = {"url": url, "detalle_ok": True}
        t = self.encontrar("det_titulo")
        det["titulo_detalle"] = t.text if t else None
        org = self.encontrar("det_organizacion")
        det["organizacion"] = org.text if org else None
        det["num_recursos"] = len(self.encontrar("det_recursos", todos=True))
        det["etiquetas"] = [e.text.strip() for e in self.encontrar("det_etiquetas", todos=True) if e.text.strip()]

        # Tabla "Información adicional": campo -> valor. Las fechas traen el atributo
        # data-datetime en ISO 8601, más confiable que el texto visible.
        for tr in self.encontrar("det_filas_info", todos=True):
            try:
                campo = tr.find_element(By.TAG_NAME, "th").text.strip()
                td = tr.find_element(By.TAG_NAME, "td")
            except NoSuchElementException:
                continue
            fecha = td.find_elements(By.CSS_SELECTOR, "[data-datetime]")
            valor = (fecha[0].get_attribute("data-datetime") or td.text) if fecha else td.text
            det[f"info::{campo}"] = valor.strip()

        # Temas que no usan <table> (p. ej. Portal Andino): se busca cada etiqueta conocida
        # ("Fecha de publicación", "Licencia"...) y se toma el texto del elemento hermano.
        for campo, valor in self.driver.execute_script(JS_PARES_ETIQUETA_VALOR, ETIQUETAS_INFO).items():
            det.setdefault(f"info::{campo}", valor)
        if not det["etiquetas"] and det.get("info::Etiquetas"):
            det["etiquetas"] = [e.strip() for e in det["info::Etiquetas"].split("\n") if e.strip()]
        if not det["num_recursos"]:
            det["num_recursos"] = len(self.driver.find_elements(
                By.XPATH, "//a[translate(normalize-space(.),'descarg','DESCARG')='DESCARGAR']"))
        return det

    # ------------------------------------------------------------- flujo
    def ejecutar(self) -> None:
        a = self.args
        inicio = time.perf_counter()
        resultados: list[dict] = []
        detalles: list[dict] = []
        try:
            self.cargar_robots()
            self.buscar(a.termino)
            if a.filtro_param and a.filtro_valor:
                try:
                    self.aplicar_filtro(a.filtro_param, a.filtro_valor)
                except (ServidorNoDisponible, TimeoutException) as e:
                    log(f"El filtro no cargó ({e.__class__.__name__}); se continúa con los "
                        "resultados de la búsqueda sin filtro.")
                    self.ir(self.url_busqueda, "(volver a la búsqueda)")
                    self.esperar_resultados()

            for n in range(1, a.paginas + 1):
                filas = self.extraer_pagina(n)
                resultados.extend(filas)
                log(f"Página {n}: {len(filas)} resultados (acumulado {len(resultados)})")
                if n == 1:
                    self.captura("pagina_1")
                if n == a.paginas:
                    break
                try:
                    if not self.siguiente_pagina():
                        break
                except (ServidorNoDisponible, TimeoutException) as e:
                    log(f"La página {n + 1} no cargó ({e.__class__.__name__}); se conservan las "
                        f"{len(resultados)} filas obtenidas y se pasa a las fichas.")
                    break

            # Fichas de detalle (las primeras `detalles` URL únicas)
            urls = list(dict.fromkeys(r["url"] for r in resultados if r.get("url")))[: a.detalles]
            for i, url in enumerate(urls, 1):
                try:
                    detalles.append(self.extraer_detalle(url))
                    if i == 1:
                        self.captura("detalle")
                    log(f"Detalle {i}/{len(urls)}: {detalles[-1].get('titulo_detalle')}")
                except (TimeoutException, PermissionError, ServidorNoDisponible) as e:
                    log(f"Detalle {i} omitido: {e.__class__.__name__}")
                    detalles.append({"url": url, "detalle_ok": False})
        except DesafioNoResuelto as e:
            log(f"Extracción detenida: {e}. Se guarda lo obtenido hasta ahora.")
        except PermissionError as e:
            log(f"Extracción detenida por robots.txt: {e}")
        except ServidorNoDisponible as e:
            log(f"Extracción detenida: el portal no está disponible ahora ({e}). "
                "Intenta más tarde; no es un error del bot.")
        except (TimeoutException, NoSuchElementException) as e:
            # La página no tiene la estructura esperada (¿el portal cambió su diseño?).
            # Se guardan captura y HTML para ajustar los localizadores.
            self.captura("error_estructura")
            ruta = self.carpeta_capturas / "pagina_error.html"
            ruta.write_text(self.driver.page_source, encoding="utf-8")
            log(f"La página no tiene la estructura esperada ({e.__class__.__name__}) en "
                f"{self.driver.current_url}. HTML guardado en {ruta}")
        except KeyboardInterrupt:
            log("Interrumpido con Ctrl+C. Se guarda lo obtenido hasta ahora.")
        except WebDriverException as e:
            causa = (getattr(e, "msg", None) or str(e)).strip().splitlines()[0][:120]
            log(f"El navegador dejó de responder o se cerró ({causa}). Se guarda lo obtenido.")
        finally:
            try:
                self.driver.quit()
            except Exception:  # noqa: BLE001 - la ventana ya estaba cerrada
                pass

        self.guardar(resultados, detalles, time.perf_counter() - inicio)

    def guardar(self, resultados: list[dict], detalles: list[dict], segundos: float) -> None:
        """Une lista + detalle por URL y guarda los datos crudos (sin limpiar)."""
        if not resultados:
            log("No se obtuvieron resultados; no se generó archivo.")
            return
        df = pd.DataFrame(resultados)
        if detalles:
            df = df.merge(pd.DataFrame(detalles), on="url", how="left")
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta_json = config.CARPETA_DATOS / f"crudos_{sello}.json"
        ruta_csv = config.CARPETA_DATOS / f"crudos_{sello}.csv"
        meta = {
            "portal": self.base, "termino": self.args.termino,
            "filtro": self.filtro_estado,
            "generado": sello, "segundos": round(segundos, 1), "filas": len(df),
            "robots": self.robots_estado, "navegador": self.driver_nombre,
        }
        ruta_json.write_text(json.dumps({"meta": meta, "datos": df.to_dict(orient="records")},
                                        ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        df.to_csv(ruta_csv, index=False, encoding="utf-8-sig")
        log(f"Listo en {segundos:.0f}s: {len(df)} filas crudas")
        log(f"  {ruta_json}")
        log(f"  {ruta_csv}")
        log("Siguiente paso: python limpieza.py")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bot Selenium para portales CKAN (uso educativo)")
    p.add_argument("--base-url", default=config.BASE_URL)
    p.add_argument("--termino", default=config.TERMINO_BUSQUEDA)
    p.add_argument("--filtro-param", default=config.FILTRO_PARAMETRO)
    p.add_argument("--filtro-valor", default=config.FILTRO_VALOR)
    p.add_argument("--paginas", type=int, default=config.MAX_PAGINAS)
    p.add_argument("--detalles", type=int, default=config.MAX_DETALLES)
    p.add_argument("--headless", action="store_true", help="sin ventana (no permite intervención humana)")
    p.add_argument("--chrome-bin", help="ruta a Chrome si no está en la ubicación estándar")
    p.add_argument("--driver", help="ruta a chromedriver (normalmente no hace falta)")
    p.add_argument("--navegador", choices=["auto", "chrome", "edge"], default="auto",
                   help="auto prueba Chrome y, si falla, Microsoft Edge")
    return p.parse_args()


if __name__ == "__main__":
    BotPortal(parse_args()).ejecutar()
