"""
Defensa 5 (paso 9): DOM dinámico. Compara dos scrapers sobre el catálogo local.

  frágil    Usa localizadores fijos copiados del inspector un día cualquiera:
            By.ID("card-list") y la clase señuelo "dyn-xxxxxx" de esa carga.
            Esperado: NoSuchElementException, porque el sitio genera IDs y clases
            nuevas en cada carga (hook useDynamicDom del frontend).
  robusto   Usa el contrato estable: article[data-card-id] y sus atributos data-*.
            Esperado: extrae las cartas sin problema en todas las cargas.

También recarga la página varias veces y muestra cómo cambia el id del contenedor,
mientras los data-card-id siguen iguales.

Funciona igual en los tres SECURITY_MODE (el DOM dinámico vive en el frontend).
Guarda evidencia en scraper_tests/evidencia/03_dom_dinamico.json y .png

Uso:
    python scraper_tests/03_dom_dinamico.py
    python scraper_tests/03_dom_dinamico.py --recargas 5 --headless
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from selenium_comun import EVIDENCIA, crear_driver, solo_localhost

CARTA = (By.CSS_SELECTOR, "article[data-card-id]")


def esperar_cartas(driver) -> None:
    """La SPA carga el listado con fetch: hay que esperar, no basta con get()."""
    WebDriverWait(driver, 15).until(EC.presence_of_element_located(CARTA))


def estado_dom(driver) -> dict:
    """Lee el id y la clase señuelo del contenedor de cartas en esta carga."""
    contenedor = driver.find_element(*CARTA).find_element(By.XPATH, "..")
    clases = (contenedor.get_attribute("class") or "").split()
    return {
        "id_contenedor": contenedor.get_attribute("id"),
        "clase_senuelo": next((c for c in clases if c.startswith("dyn-")), None),
        "data_card_ids": [el.get_attribute("data-card-id") for el in driver.find_elements(*CARTA)],
    }


def scraper_fragil(driver, id_fijo: str, clase_fija: str | None) -> dict:
    """Intenta los localizadores 'copiados del inspector' en una carga anterior."""
    resultado = {}
    for nombre, loc in [("By.ID", (By.ID, id_fijo)),
                        ("By.CLASS_NAME", (By.CLASS_NAME, clase_fija or "dyn-inexistente"))]:
        try:
            driver.find_element(*loc)
            resultado[nombre] = f"encontrado ({loc[1]})"
        except NoSuchElementException:
            resultado[nombre] = f"NoSuchElementException ({loc[1]})"
    return resultado


def scraper_robusto(driver) -> list[dict]:
    """Extrae con los atributos data-*: el contrato que el DOM dinámico no toca."""
    campos = ["data-card-id", "data-card-name", "data-type", "data-collection",
              "data-generation", "data-rarity", "data-category"]
    return [{c.removeprefix("data-"): el.get_attribute(c) for c in campos}
            for el in driver.find_elements(*CARTA)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:5173/cartas?page=1")
    ap.add_argument("--recargas", type=int, default=3, help="cargas de la página a comparar")
    ap.add_argument("--id-fijo", default="card-list",
                    help="id que usaría un scraper ingenuo (antes de la defensa era 'card-list')")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--chrome-bin")
    ap.add_argument("--driver")
    ap.add_argument("--navegador", choices=["auto", "chrome", "edge"], default="auto")
    a = ap.parse_args()
    solo_localhost(a.url)

    driver = crear_driver(a.headless, a.chrome_bin, a.driver, a.navegador)
    EVIDENCIA.mkdir(exist_ok=True)
    cargas = []
    try:
        driver.get(a.url)
        esperar_cartas(driver)
        primera = estado_dom(driver)
        # Lo que un scraper frágil "copiaría" del inspector en la primera visita
        clase_copiada = primera["clase_senuelo"]

        for i in range(1, a.recargas + 1):
            if i > 1:
                driver.refresh()
                esperar_cartas(driver)
            estado = estado_dom(driver)
            fragil = scraper_fragil(driver, a.id_fijo, clase_copiada)
            robusto = scraper_robusto(driver)
            cargas.append({"carga": i, "id_contenedor": estado["id_contenedor"],
                           "clase_senuelo": estado["clase_senuelo"],
                           "scraper_fragil": fragil, "cartas_extraidas_data": len(robusto),
                           "data_card_ids_iguales_a_carga_1":
                               estado["data_card_ids"] == primera["data_card_ids"],
                           "muestra": robusto[:2]})
        driver.save_screenshot(str(EVIDENCIA / "03_dom_dinamico.png"))
    finally:
        driver.quit()

    print(f"\nDOM dinámico: {a.recargas} cargas de {a.url}\n")
    print(f"{'carga':<6}{'id del contenedor':<26}{'By.ID fijo':<26}{'clase de la carga 1':<26}{'data-*':>8}")
    for c in cargas:
        corto = lambda s: s.split(" ")[0]  # noqa: E731
        print(f"{c['carga']:<6}{c['id_contenedor']:<26}{corto(c['scraper_fragil']['By.ID']):<26}"
              f"{corto(c['scraper_fragil']['By.CLASS_NAME']):<26}{c['cartas_extraidas_data']:>8}")
    print("\nConclusión: los localizadores por ID/clase dejan de funcionar entre cargas;"
          " los data-* extraen las mismas cartas siempre.")

    salida = EVIDENCIA / "03_dom_dinamico.json"
    salida.write_text(json.dumps({"fecha": datetime.now().isoformat(timespec="seconds"),
                                  "url": a.url, "id_fijo": a.id_fijo, "cargas": cargas},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evidencia en {salida} y 03_dom_dinamico.png")


if __name__ == "__main__":
    main()
