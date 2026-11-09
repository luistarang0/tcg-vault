"""
Utilidades compartidas: acceso responsable por HTTP y por navegador, y bitácora.

El Cliente es la única puerta de salida a internet de estos scripts. Antes de cada
petición comprueba que el host esté autorizado, lee robots.txt y espera el turno.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait

import config

for flujo in (sys.stdout, sys.stderr):
    flujo.reconfigure(encoding="utf-8")

# Textos que indican un bloqueo o un reto. Si aparecen, el script se detiene.
SENALES_BLOQUEO = ("access denied", "acceso denegado", "request blocked", "verify you are human",
                   "attention required", "just a moment", "no soy un robot", "captcha")


class AccesoNoPermitido(Exception):
    """El host no está autorizado o robots.txt prohíbe la ruta."""


class Bloqueado(Exception):
    """El sitio bloqueó al navegador automatizado o mostró un reto. No se insiste."""


class Bitacora:
    """Registra herramientas, errores y medidas tomadas en resultados/bitacora.jsonl."""

    def __init__(self, script: str):
        self.script = script
        config.RESULTADOS.mkdir(parents=True, exist_ok=True)
        self.archivo = config.RESULTADOS / "bitacora.jsonl"

    def evento(self, tipo: str, detalle: str, **extra) -> None:
        fila = {"fecha": datetime.now().isoformat(timespec="seconds"), "script": self.script,
                "tipo": tipo, "detalle": detalle, **extra}
        with self.archivo.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
        print(f"  [{tipo}] {detalle}")


class Robots:
    """
    Interpreta robots.txt para el agente '*' según RFC 9309.

    No se usa urllib.robotparser porque codifica el '?' de las reglas como %3F: una
    regla como 'Disallow: /nota_detalle.php?' nunca coincide y la ruta prohibida se da
    por permitida. Tampoco entiende comodines '*'. Aquí gana la regla más larga y, en
    empate, Allow.
    """

    def __init__(self, texto: str = ""):
        self.texto = texto
        self.reglas: list[tuple[bool, str, re.Pattern]] = []
        self.crawl: float | None = None
        agentes: list[str] = []
        en_reglas = False
        for linea in texto.splitlines():
            linea = linea.split("#", 1)[0].strip()
            if ":" not in linea:
                continue
            campo, valor = (p.strip() for p in linea.split(":", 1))
            campo = campo.lower()
            if campo == "user-agent":
                if en_reglas:                 # empieza otro grupo
                    agentes, en_reglas = [], False
                agentes.append(valor.lower())
            elif campo in ("allow", "disallow", "crawl-delay"):
                en_reglas = True
                if "*" not in agentes:
                    continue
                if campo == "crawl-delay":
                    try:
                        self.crawl = float(valor)
                    except ValueError:
                        pass
                elif valor:                   # 'Disallow:' vacío no prohíbe nada
                    self.reglas.append((campo == "allow", valor, self._patron(valor)))

    @staticmethod
    def _patron(ruta: str) -> re.Pattern:
        final = ruta.endswith("$")
        cuerpo = re.escape(ruta[:-1] if final else ruta).replace(r"\*", ".*")
        return re.compile(cuerpo + ("$" if final else ""))

    def permite(self, url: str) -> bool:
        partes = urlparse(url)
        objetivo = (partes.path or "/") + (f"?{partes.query}" if partes.query else "")
        coincidencias = [(len(ruta), permitir) for permitir, ruta, p in self.reglas if p.match(objetivo)]
        return max(coincidencias)[1] if coincidencias else True


class Cliente:
    """HTTP con host autorizado, robots.txt y pausas. Selenium usa las mismas reglas."""

    def __init__(self, bitacora: Bitacora):
        self.b = bitacora
        self.s = requests.Session()
        self.s.headers["User-Agent"] = config.USER_AGENT
        self.robots: dict[str, Robots] = {}
        self.ultimo: dict[str, float] = {}
        self.pausado = 0.0                 # segundos de cortesía, para no contarlos como tiempo del método

    @staticmethod
    def _autorizar_host(url: str) -> str:
        host = urlparse(url).netloc
        if host not in config.HOSTS_AUTORIZADOS:
            raise AccesoNoPermitido(f"{host} no está en HOSTS_AUTORIZADOS")
        return host

    def robots_de(self, url: str) -> Robots:
        """Lee robots.txt una vez por host. 4xx = sin reglas; un fallo de red impide continuar."""
        host = self._autorizar_host(url)
        if host in self.robots:
            return self.robots[host]
        r = self.s.get(f"https://{host}/robots.txt", timeout=config.TIMEOUT_HTTP_S)
        if r.status_code >= 500:
            raise AccesoNoPermitido(f"robots.txt de {host} respondió {r.status_code}")
        self.robots[host] = Robots(r.text if r.status_code == 200 else "")
        self.ultimo[host] = time.monotonic()
        return self.robots[host]

    def permitido(self, url: str) -> bool:
        return self.robots_de(url).permite(url)

    def crawl_delay(self, url: str) -> float | None:
        return self.robots_de(url).crawl

    def turno(self, url: str) -> None:
        """Espera lo que pide robots.txt (Crawl-delay) o la pausa mínima de cortesía."""
        host = urlparse(url).netloc
        pausa = max(config.PAUSA_MINIMA_S, self.crawl_delay(url) or 0)
        falta = self.ultimo.get(host, 0) + pausa - time.monotonic()
        if falta > 0:
            time.sleep(falta)
            self.pausado += falta
        self.ultimo[host] = time.monotonic()

    def comprobar(self, url: str) -> None:
        if not self.permitido(url):
            raise AccesoNoPermitido(f"robots.txt no permite {url}")
        self.turno(url)

    def get(self, url: str) -> requests.Response:
        """GET con hasta 3 intentos solo ante fallos transitorios. 403 y 429 nunca se reintentan."""
        for intento in range(1, config.INTENTOS_HTTP + 1):
            self.comprobar(url)
            try:
                r = self.s.get(url, timeout=config.TIMEOUT_HTTP_S)
                if r.status_code < 500 or intento == config.INTENTOS_HTTP:
                    return r
                motivo = f"HTTP {r.status_code}"
            except (requests.Timeout, requests.ConnectionError) as e:
                if intento == config.INTENTOS_HTTP:
                    raise
                motivo = e.__class__.__name__
            self.b.evento("error", f"{urlparse(url).netloc}: {motivo}; intento {intento} de {config.INTENTOS_HTTP}")
            time.sleep(5 * intento)
            self.pausado += 5 * intento
        raise AssertionError("inalcanzable")

    def navegar(self, driver, url: str) -> None:
        """Abre la URL en el navegador con las mismas reglas y se detiene ante un bloqueo."""
        self.comprobar(url)
        driver.get(url)
        motivo = detectar_bloqueo(driver)
        if motivo:
            raise Bloqueado(f"{url}: {motivo}")


def detectar_bloqueo(driver) -> str | None:
    titulo = (driver.title or "").lower()
    texto = (driver.execute_script("return document.body ? document.body.innerText : ''") or "")[:600].lower()
    for senal in SENALES_BLOQUEO:
        if senal in titulo or senal in texto:
            return f"señal de bloqueo: '{senal}' (título: {driver.title!r})"
    return None


def abrir_navegador(headless: bool = False):
    """Abre Edge o, si no está, Chrome. No oculta la automatización (navigator.webdriver = true)."""
    def opciones(clase):
        o = clase()
        if headless:
            o.add_argument("--headless=new")
        o.add_argument("--window-size=1366,900")
        return o

    intentos = [("Microsoft Edge", lambda: webdriver.Edge(options=opciones(webdriver.EdgeOptions))),
                ("Google Chrome", lambda: webdriver.Chrome(options=opciones(webdriver.ChromeOptions)))]
    fallos = []
    for nombre, abrir in intentos:
        try:
            driver = abrir()
            driver.nombre_navegador = nombre
            return driver
        except Exception as e:  # noqa: BLE001 - se prueba el siguiente navegador
            fallos.append(f"{nombre}: {e.__class__.__name__}")
    raise SystemExit(f"No se pudo abrir ningún navegador ({'; '.join(fallos)})")


class CuentaEstable:
    """Condición de WebDriverWait: hay al menos `minimo` elementos y la cuenta dejó de crecer."""

    def __init__(self, selector: str, minimo: int = 1):
        self.selector, self.minimo, self.previa = selector, minimo, -1

    def __call__(self, driver):
        cuenta = driver.execute_script("return document.querySelectorAll(arguments[0]).length", self.selector)
        estable = cuenta >= self.minimo and cuenta == self.previa
        self.previa = cuenta
        return cuenta if estable else False


class TextoEstable:
    """Condición de WebDriverWait para páginas sin filas: el texto visible dejó de crecer."""

    def __init__(self):
        self.previo = -1

    def __call__(self, driver):
        largo = driver.execute_script("return document.body ? document.body.innerText.length : 0")
        estable = largo > 0 and largo == self.previo
        self.previo = largo
        return largo if estable else False


def esperar(driver, condicion, maximo: int | None = None):
    """Espera explícita: sondea cada segundo, en lugar de dormir un tiempo fijo."""
    return WebDriverWait(driver, maximo or config.ESPERA_MAX_S, poll_frequency=1.0).until(condicion)


def tabla_md(df: pd.DataFrame) -> str:
    """Convierte un DataFrame en tabla Markdown sin dependencias extra."""
    celdas = df.astype(object).where(df.notna(), "").astype(str)
    filas = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    filas += ["| " + " | ".join(v.replace("|", "/") for v in fila) + " |" for fila in celdas.values.tolist()]
    return "\n".join(filas)


def guardar_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def guardar_csv(ruta: Path, df: pd.DataFrame) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")       # con BOM para que Excel respete acentos


def args_headless() -> bool:
    return "--headless" in sys.argv or os.environ.get("HEADLESS") == "1"
