"""
Utilidades compartidas por los scripts de Selenium de scraper_tests/.

* crear_driver(): abre un navegador automatizado probando varias opciones en orden
  hasta que una funcione, e imprime por qué falló cada una:
    1. Chrome con Selenium Manager (incluido en Selenium 4.6+; si Chrome no está
       instalado, descarga "Chrome for Testing" automáticamente).
    2. Chrome con webdriver-manager (descarga el chromedriver para tu Chrome).
    3. Microsoft Edge con Selenium Manager (Edge viene instalado en Windows).
  Con --navegador chrome|edge se fuerza uno.
* solo_localhost(): salvaguarda. Estos scripts SOLO pueden apuntar a tu propio
  servidor (localhost / 127.0.0.1).
* solo_sitio_propio(): como la anterior, pero acepta además el despliegue propio
  en Vercel (PRODUCCION). Lo usan los scripts que tienen la opción --produccion.
  Ningún otro dominio se acepta.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService

EVIDENCIA = Path(__file__).resolve().parent / "evidencia"
LOG_SERVIDOR = Path(__file__).resolve().parent.parent / "server" / "logs" / "access.jsonl"


# Despliegue propio de TCG Vault: el único dominio público al que pueden apuntar los scripts
PRODUCCION = "https://tcg-vault-eight.vercel.app"
HOSTS_LOCALES = {"localhost", "127.0.0.1"}


def solo_localhost(url: str) -> None:
    if urlparse(url).hostname not in HOSTS_LOCALES:
        raise SystemExit("Estos scripts solo pueden apuntar a localhost (tu propio servidor).")


def solo_sitio_propio(url: str) -> bool:
    """Acepta localhost o el despliegue propio. Devuelve True si es producción."""
    host = urlparse(url).hostname
    if host in HOSTS_LOCALES:
        return False
    if host == urlparse(PRODUCCION).hostname:
        return True
    raise SystemExit(f"Este script solo puede apuntar a localhost o a {PRODUCCION} (sitios propios).")


def chrome_instalado() -> bool:
    """Busca Chrome en las rutas estándar de Windows (en otros sistemas asume que sí)."""
    if not sys.platform.startswith("win"):
        return True
    rutas = [Path(os.environ.get(v, "")) / "Google/Chrome/Application/chrome.exe"
             for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    return any(r.exists() for r in rutas)


def _opciones(clase, headless: bool, binario: str | None):
    opts = clase()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--lang=es-MX")
    if binario:
        opts.binary_location = binario
    if sys.platform.startswith("linux"):
        opts.add_argument("--no-sandbox")
    return opts


def crear_driver(headless: bool = False, chrome_bin: str | None = None,
                 driver_path: str | None = None, navegador: str = "auto"):
    """Abre el navegador automatizado. No oculta que es automatizado (navigator.webdriver = true)."""
    def chrome(service):
        return webdriver.Chrome(service=service, options=_opciones(webdriver.ChromeOptions, headless, chrome_bin))

    def edge():
        return webdriver.Edge(service=EdgeService(), options=_opciones(webdriver.EdgeOptions, headless, None))

    def chrome_wdm():
        from webdriver_manager.chrome import ChromeDriverManager
        return chrome(ChromeService(ChromeDriverManager().install()))

    intentos = []
    if driver_path:
        intentos.append(("Chrome con el driver indicado", lambda: chrome(ChromeService(driver_path))))
    if navegador in ("auto", "chrome"):
        intentos.append(("Chrome con Selenium Manager", lambda: chrome(ChromeService())))
        intentos.append(("Chrome con webdriver-manager", chrome_wdm))
    if navegador in ("auto", "edge"):
        edge_intento = ("Microsoft Edge con Selenium Manager", edge)
        # Sin Chrome instalado, Edge va primero (evita descargar Chrome for Testing)
        if navegador == "auto" and not chrome_instalado() and not chrome_bin:
            print("(No se encontró Google Chrome instalado: se usará Microsoft Edge)")
            intentos.insert(0, edge_intento)
        else:
            intentos.append(edge_intento)

    for nombre, abrir in intentos:
        try:
            driver = abrir()
            driver.origen_driver = nombre
            return driver
        except Exception as e:  # noqa: BLE001 - se informa y se prueba la siguiente opción
            causa = (getattr(e, "msg", None) or str(e)).strip().splitlines()[0][:160]
            print(f"  x {nombre}: {e.__class__.__name__}: {causa}")
    raise SystemExit("No se pudo abrir ningún navegador. Instala Google Chrome o actualiza Edge "
                     "y vuelve a intentar (copia los mensajes de arriba si sigue fallando).")
