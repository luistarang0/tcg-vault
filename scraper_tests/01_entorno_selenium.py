"""
Primer script de Selenium: verifica que el entorno de automatización funciona.

Comprueba:
  1. Versiones de Python, Selenium y webdriver-manager.
  2. Que Chrome se abre automatizado (webdriver-manager descarga el driver).
  3. Que se puede cargar el catálogo local y esperar el contenido dinámico
     con WebDriverWait (la lista llega por fetch, no está en el HTML inicial).
  4. Que se leen las cartas con selectores robustos (atributos data-*).
  5. Qué huellas deja el navegador automatizado (navigator.webdriver, UA).

Requisitos: backend (8000) y frontend (5173) corriendo.
Uso:
    python scraper_tests/01_entorno_selenium.py
    python scraper_tests/01_entorno_selenium.py --headless
"""
import argparse
import platform
import time
from importlib.metadata import PackageNotFoundError, version

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from selenium_comun import EVIDENCIA, crear_driver, solo_localhost


def ver(paquete: str) -> str:
    try:
        return version(paquete)
    except PackageNotFoundError:
        return "no instalado"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:5173/cartas?page=1")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--chrome-bin")
    ap.add_argument("--driver")
    ap.add_argument("--navegador", choices=["auto", "chrome", "edge"], default="auto")
    a = ap.parse_args()
    solo_localhost(a.url)
    EVIDENCIA.mkdir(exist_ok=True)

    print("== 1. Entorno ==")
    print(f"Python            {platform.python_version()}")
    print(f"selenium          {ver('selenium')}")
    print(f"webdriver-manager {ver('webdriver-manager')}")

    print("\n== 2. Abrir el navegador automatizado ==")
    t0 = time.perf_counter()
    driver = crear_driver(a.headless, a.chrome_bin, a.driver, a.navegador)
    print(f"{driver.capabilities.get('browserName')} {driver.capabilities.get('browserVersion')} "
          f"abierto en {time.perf_counter() - t0:.1f}s ({driver.origen_driver})")

    try:
        print("\n== 3. Cargar el catálogo y esperar el contenido dinámico ==")
        driver.get(a.url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article[data-card-id]")))
        cartas = driver.find_elements(By.CSS_SELECTOR, "article[data-card-id]")
        print(f"{len(cartas)} cartas visibles en {driver.current_url}")

        print("\n== 4. Lectura con atributos data-* ==")
        for el in cartas[:5]:
            print(f"  {el.get_attribute('data-card-id'):<12} {el.get_attribute('data-card-name'):<22} "
                  f"tipo={el.get_attribute('data-type') or '—':<10} gen={el.get_attribute('data-generation') or '—'}")

        print("\n== 5. Huellas del navegador automatizado ==")
        huellas = driver.execute_script("""return {
            webdriver: navigator.webdriver,
            userAgent: navigator.userAgent,
            plugins: navigator.plugins.length,
            languages: navigator.languages.join(',')
        }""")
        for k, v in huellas.items():
            print(f"  {k:<10} {v}")

        ruta = EVIDENCIA / "01_entorno_selenium.png"
        driver.save_screenshot(str(ruta))
        print(f"\nCaptura: {ruta}")
        print("Entorno listo.")
    finally:
        if not a.headless:
            time.sleep(2)            # deja ver la ventana un momento antes de cerrarla
        driver.quit()


if __name__ == "__main__":
    main()
