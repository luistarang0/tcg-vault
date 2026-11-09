"""
Lectura de la tabla "All Countries and Economies" del World Bank por tres vías.

La misma tabla sirve al duelo (03) y al flujo a base de datos (04):
  * por_selenium(): abre la página y espera a que JavaScript dibuje las filas.
  * por_http(): descarga el HTML y busca las mismas filas con BeautifulSoup.
  * por_api(): consulta la API oficial v2.

La página muestra el valor redondeado y a veces escalado, con la unidad en el
encabezado (por ejemplo "Most Recent Value (Thousands)"). La API da el valor exacto.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

import config
from comun import Cliente, CuentaEstable, esperar

SELECTOR_FILA = ".infinite .item"
SELECTOR_ENLACE = ".infinite .item a.country-name"


def _pais_id(href: str) -> str | None:
    valor = parse_qs(urlparse(href or "").query).get("locations", [None])[0]
    return valor.upper() if valor else None


def por_selenium(c: Cliente, driver, indicador: str) -> dict:
    """Localiza las filas con Selenium, esperando la condición en vez de dormir un tiempo fijo."""
    url = config.URL_INDICADOR.format(id=indicador)
    c.navegar(driver, url)
    esperar(driver, CuentaEstable(SELECTOR_ENLACE, minimo=10))
    # La lista es de carga progresiva: se baja al final y se espera a que deje de crecer
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
    esperar(driver, CuentaEstable(SELECTOR_ENLACE, minimo=10))

    filas = []
    for fila in driver.find_elements(By.CSS_SELECTOR, SELECTOR_FILA):
        celdas = fila.find_elements(By.XPATH, "./div")
        enlace = fila.find_elements(By.CSS_SELECTOR, "a.country-name")
        if not enlace or len(celdas) < 3:
            continue
        filas.append({"pais": enlace[0].text, "pais_id": _pais_id(enlace[0].get_attribute("href")),
                      "anio_texto": celdas[1].text, "valor_texto": celdas[2].text})
    encabezado = re.search(r"Most Recent Value\s*\(([^)]+)\)", driver.execute_script("return document.body.innerText"))
    return {"indicador": indicador, "url": url, "unidad_texto": encabezado.group(1) if encabezado else None,
            "filas": filas}


def por_http(c: Cliente, indicador: str) -> list[dict]:
    """Primer intento del duelo: el HTML que entrega el servidor, sin ejecutar JavaScript."""
    r = c.get(config.URL_INDICADOR.format(id=indicador))
    html = BeautifulSoup(r.text, "html.parser")
    filas = []
    for fila in html.select(SELECTOR_FILA):
        celdas = fila.find_all("div", recursive=False)
        enlace = fila.select_one("a.country-name")
        if enlace and len(celdas) >= 3:
            filas.append({"pais": enlace.get_text(strip=True), "pais_id": _pais_id(enlace.get("href")),
                          "anio_texto": celdas[1].get_text(strip=True), "valor_texto": celdas[2].get_text(strip=True)})
    return filas


def paises_api(c: Cliente) -> dict[str, str]:
    """Países reales según la API (quita agregados como 'World' o 'Euro area')."""
    r = c.get("https://api.worldbank.org/v2/country?format=json&per_page=400")
    r.raise_for_status()
    return {p["iso2Code"]: p["name"] for p in r.json()[1] if p["region"]["id"] != "NA"}


def por_api(c: Cliente, indicador: str, paises: dict[str, str]) -> list[dict]:
    """Dato más reciente no vacío de cada país (mrnev=1). La API pagina; se piden todas."""
    filas, pagina, total = [], 1, 1
    while pagina <= total:
        r = c.get(f"https://api.worldbank.org/v2/country/all/indicator/{indicador}"
                  f"?format=json&mrnev=1&per_page=400&page={pagina}")
        r.raise_for_status()
        meta, datos = r.json()
        total = meta["pages"]
        for d in datos or []:
            if d["country"]["id"] in paises:
                filas.append({"pais": d["country"]["value"], "pais_id": d["country"]["id"],
                              "anio_texto": d["date"], "valor": d["value"]})
        pagina += 1
    return filas
