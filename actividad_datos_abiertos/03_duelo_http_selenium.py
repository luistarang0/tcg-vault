"""
Actividad 2: duelo entre HTTP y Selenium (y la API oficial cuando existe).

Se comparan cantidad de registros, campos faltantes y tiempo en dos fuentes:
  A. World Bank, tabla por país: contenido dinámico; hay API oficial.
  B. catalog.data.gov, una página de resultados: el HTML ya trae los datos.

El tiempo de Selenium se da con y sin el arranque del navegador. No incluye las pausas
de cortesía, que son iguales para todos y no dependen del método.

Salidas: resultados/duelo.json, duelo_comparativa.csv y duelo_comparativa.md

Uso:  python actividad_datos_abiertos/03_duelo_http_selenium.py [--headless]
"""
from __future__ import annotations

import re
import time
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

import config
import worldbank as wb
from comun import (Bitacora, Bloqueado, Cliente, CuentaEstable, abrir_navegador, args_headless, esperar,
                   guardar_csv, guardar_json, tabla_md)
from limpieza import MULTIPLICADORES, numero

INDICADOR = "SP.POP.TOTL"
URL_CATALOGO = "https://catalog.data.gov/?q=water"
API_CATALOGO = "https://catalog.data.gov/search?q=water&per_page=20"
ITEM_CATALOGO = ".organization-datasets__item"


def metricas(fuente: str, metodo: str, filas: list[dict], campos: list[str], segundos: float, nota: str = "") -> dict:
    df = pd.DataFrame(filas, columns=campos).replace("", pd.NA)
    return {"Fuente": fuente, "Método": metodo, "Registros": len(df),
            "Campos faltantes": int(df.isna().sum().sum()) if len(df) else "n/a",
            "Tiempo (s)": round(segundos, 2), "Observación": nota}


def cronometrar(funcion, c: Cliente | None = None):
    """Mide el método sin contar las pausas de cortesía ni las esperas entre reintentos."""
    pausa_previa = c.pausado if c else 0
    inicio = time.perf_counter()
    resultado = funcion()
    return resultado, time.perf_counter() - inicio - ((c.pausado - pausa_previa) if c else 0)


def duelo_worldbank(c: Cliente, driver, arranque: float, b: Bitacora) -> tuple[list[dict], dict]:
    campos = ["pais", "pais_id", "anio_texto", "valor_texto"]
    http, t_http = cronometrar(lambda: wb.por_http(c, INDICADOR), c)
    b.evento("resultado", f"World Bank por HTTP: {len(http)} filas en el HTML inicial")

    sel, t_sel = cronometrar(lambda: wb.por_selenium(c, driver, INDICADOR), c)
    b.evento("resultado", f"World Bank por Selenium: {len(sel['filas'])} filas (unidad: {sel['unidad_texto']})")

    paises, t_paises = cronometrar(lambda: wb.paises_api(c), c)
    api, t_api = cronometrar(lambda: wb.por_api(c, INDICADOR, paises), c)
    b.evento("resultado", f"World Bank por API: {len(api)} países con dato")

    # Consistencia: ¿Selenium y la API dicen lo mismo?
    factor = MULTIPLICADORES.get((sel["unidad_texto"] or "").lower(), 1)
    tabla = pd.DataFrame(sel["filas"]).assign(valor_sel=lambda d: d["valor_texto"].map(numero) * factor)
    union = tabla.merge(pd.DataFrame(api), on="pais_id", suffixes=("_sel", "_api"))
    iguales = int(((union["valor_sel"] - union["valor"]).abs() <= union["valor"].abs() * 0.005).sum())
    solo_sel = sorted(set(tabla["pais_id"].dropna()) - set(union["pais_id"]))
    solo_api = sorted({f["pais_id"] for f in api} - set(tabla["pais_id"].dropna()))
    agregados = [p for p in solo_sel if p not in paises]
    consistencia = {"coinciden_margen_0.5pct": iguales, "comparados": len(union),
                    "agregados_regionales_solo_en_selenium": len(agregados),
                    "paises_solo_en_selenium": [p for p in solo_sel if p in paises], "paises_solo_en_api": solo_api}

    filas = [
        metricas("World Bank", "HTTP + BeautifulSoup", http, campos, t_http,
                 "El HTML inicial no trae la tabla: la dibuja JavaScript"),
        metricas("World Bank", "Selenium + WebDriverWait", sel["filas"], campos, t_sel,
                 f"Con arranque del navegador: {t_sel + arranque:.2f} s. Valores redondeados "
                 f"(unidad: {sel['unidad_texto']}). Incluye {len(agregados)} agregados regionales"),
        metricas("World Bank", "API oficial v2", api, ["pais", "pais_id", "anio_texto", "valor"], t_api + t_paises,
                 "Valores exactos; incluye la consulta de países para quitar agregados"),
    ]
    return filas, consistencia


def catalogo_http(c: Cliente) -> list[dict]:
    r = c.get(URL_CATALOGO)
    filas = []
    for item in BeautifulSoup(r.text, "html.parser").select(ITEM_CATALOGO):
        meta = {}
        for li in item.select(".usa-collection__meta-item"):
            clave, _, valor = " ".join(li.get_text().split()).partition(":")
            meta[clave] = valor.strip()
        titulo = item.select_one(".usa-collection__heading a")
        descripcion = item.select_one(".usa-collection__description")
        filas.append({"titulo": " ".join(titulo.get_text().split()) if titulo else None,
                      "organizacion": meta.get("Organization"), "actualizado": meta.get("Dataset Last Updated"),
                      "descripcion": " ".join(descripcion.get_text().split()) if descripcion else None,
                      "formatos": ", ".join(a.get_text(strip=True) for a in item.select(".dataset-resources a")) or None})
    return filas


def catalogo_selenium(c: Cliente, driver) -> list[dict]:
    c.navegar(driver, URL_CATALOGO)
    esperar(driver, CuentaEstable(ITEM_CATALOGO))
    filas = []
    for item in driver.find_elements(By.CSS_SELECTOR, ITEM_CATALOGO):
        meta = {}
        for li in item.find_elements(By.CSS_SELECTOR, ".usa-collection__meta-item"):
            clave, _, valor = re.sub(r"\s+", " ", li.text).partition(":")
            meta[clave] = valor.strip()
        titulo = item.find_elements(By.CSS_SELECTOR, ".usa-collection__heading a")
        descripcion = item.find_elements(By.CSS_SELECTOR, ".usa-collection__description")
        filas.append({"titulo": titulo[0].text.strip() if titulo else None,
                      "organizacion": meta.get("Organization"), "actualizado": meta.get("Dataset Last Updated"),
                      "descripcion": descripcion[0].text.strip() if descripcion else None,
                      "formatos": ", ".join(a.text.strip() for a in item.find_elements(By.CSS_SELECTOR, ".dataset-resources a")) or None})
    return filas


def catalogo_api(c: Cliente) -> list[dict]:
    """Toma solo campos del conjunto: la respuesta incluye contactos que no se guardan."""
    r = c.get(API_CATALOGO)
    r.raise_for_status()
    filas = []
    for resultado in r.json()["results"]:
        d = resultado.get("dcat") or {}
        formatos = sorted({x.get("format") or x.get("mediaType") for x in d.get("distribution") or []
                           if x.get("format") or x.get("mediaType")})
        filas.append({"titulo": d.get("title"), "organizacion": (d.get("publisher") or {}).get("name"),
                      "actualizado": d.get("modified"), "descripcion": d.get("description"),
                      "formatos": ", ".join(formatos) or None})
    return filas


def duelo_catalogo(c: Cliente, driver, arranque: float, b: Bitacora) -> list[dict]:
    campos = ["titulo", "organizacion", "actualizado", "descripcion", "formatos"]
    http, t_http = cronometrar(lambda: catalogo_http(c), c)
    sel, t_sel = cronometrar(lambda: catalogo_selenium(c, driver), c)
    api, t_api = cronometrar(lambda: catalogo_api(c), c)
    b.evento("resultado", f"catalog.data.gov: HTTP {len(http)}, Selenium {len(sel)}, API {len(api)} filas")
    titulos_http = {f["titulo"] for f in http}
    comunes_sel = len(titulos_http & {f["titulo"] for f in sel})
    comunes_api = len(titulos_http & {f["titulo"] for f in api})
    return [metricas("catalog.data.gov", "HTTP + BeautifulSoup", http, campos, t_http, "El HTML ya contiene los resultados"),
            metricas("catalog.data.gov", "Selenium + WebDriverWait", sel, campos, t_sel,
                     f"Con arranque del navegador: {t_sel + arranque:.2f} s. "
                     f"{comunes_sel} títulos iguales a los del HTML"),
            metricas("catalog.data.gov", "API oficial (GET /search)", api, campos, t_api,
                     f"JSON documentado. {comunes_api} títulos iguales a los del HTML; "
                     "se omiten los contactos personales")]


def main() -> None:
    b = Bitacora("03_duelo")
    c = Cliente(b)
    driver, arranque = cronometrar(lambda: abrir_navegador(args_headless()))
    b.evento("herramienta", f"requests, BeautifulSoup y Selenium con {driver.nombre_navegador}")
    consistencia, filas = {}, []
    try:
        fila, consistencia = duelo_worldbank(c, driver, arranque, b)
        filas += fila
        filas += duelo_catalogo(c, driver, arranque, b)
    except Bloqueado as e:
        b.evento("bloqueo", f"{e}. El duelo se detiene y no se reintenta.")
    finally:
        driver.quit()

    df = pd.DataFrame(filas)
    guardar_json(config.RESULTADOS / "duelo.json", {
        "fecha": datetime.now().isoformat(timespec="seconds"), "arranque_navegador_s": round(arranque, 2),
        "consistencia_selenium_vs_api": consistencia, "metricas": filas})
    guardar_csv(config.RESULTADOS / "duelo_comparativa.csv", df)
    (config.RESULTADOS / "duelo_comparativa.md").write_text(
        f"# Duelo HTTP vs Selenium vs API\n\n{tabla_md(df)}\n\n"
        f"Consistencia de Selenium contra la API: {consistencia}\n", encoding="utf-8")
    print("\n" + df.to_string(index=False))
    print(f"\nConsistencia: {consistencia}")


if __name__ == "__main__":
    main()
