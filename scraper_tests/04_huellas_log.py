"""
Defensa 2 (paso 6): logging y huellas de automatización.

Visita el catálogo local con varios "visitantes" y después lee las líneas que el
servidor escribió en server/logs/access.jsonl para comparar sus huellas:

  navegador   requests con los encabezados que manda un Chrome real
              (User-Agent de Chrome, Accept-Language, Sec-CH-UA coherente).
              Esperado: flags=[]  automation_suspected=false
  script      requests con sus encabezados por defecto ("python-requests/x.y",
              sin Accept-Language).
              Esperado: flags=[script_ua, no_accept_language]
  selenium    Navegador automatizado en modo headless abriendo /cartas.
              Esperado: flags con headless_ua (UA "HeadlessChrome"/"HeadlessEdg")
              y navigator.webdriver = true en la página.
  humano      (opcional, --con-humano) Tú abres el sitio en tu navegador normal;
              el script espera a que presiones Enter.

El servidor solo ETIQUETA: no bloquea por estas huellas (eso lo hacen las
defensas 1, 3 y 4). Requiere SECURITY_MODE=observe o enforce (en off no se escribe log).

Uso (backend en :8000 y, para selenium/humano, frontend en :5173):
    python scraper_tests/04_huellas_log.py
    python scraper_tests/04_huellas_log.py --con-humano
    python scraper_tests/04_huellas_log.py --sin-selenium
Evidencia: scraper_tests/evidencia/04_huellas_log.json
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime

import requests

from selenium_comun import EVIDENCIA, LOG_SERVIDOR, solo_localhost

# Encabezados que envía un Chrome de escritorio real al pedir /api/cards
ENCABEZADOS_CHROME = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Sec-CH-UA": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
    "Accept": "application/json",
}


def visitar_con_requests(api: str, sid: str, encabezados: dict | None, n: int = 3) -> None:
    """Hace n peticiones al catálogo con una cookie sid fija para reconocerlas en el log."""
    s = requests.Session()
    if encabezados:
        s.headers.update(encabezados)
    for pagina in range(1, n + 1):
        s.get(f"{api}/api/cards", params={"page": pagina}, cookies={"sid": sid}, timeout=5)


def visitar_con_selenium(front: str, navegador: str) -> tuple[str | None, bool | None, str]:
    """Abre /cartas en headless. Devuelve (sid, navigator.webdriver, user agent)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    from selenium_comun import crear_driver

    d = crear_driver(headless=True, navegador=navegador)
    try:
        d.get(f"{front}/cartas?page=1")
        WebDriverWait(d, 15).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "article[data-card-id]")))
        webdriver = d.execute_script("return navigator.webdriver")
        ua = d.execute_script("return navigator.userAgent")
        cookie = d.get_cookie("sid")            # WebDriver sí puede leer cookies httponly
        return (cookie or {}).get("value"), webdriver, ua
    finally:
        d.quit()


def leer_log_desde(posicion: int) -> list[dict]:
    with LOG_SERVIDOR.open(encoding="utf-8") as f:
        f.seek(posicion)
        return [json.loads(l) for l in f if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--front", default="http://localhost:5173")
    ap.add_argument("--sin-selenium", action="store_true")
    ap.add_argument("--con-humano", action="store_true",
                    help="pausa para que abras el sitio en tu navegador normal")
    ap.add_argument("--navegador", choices=["auto", "chrome", "edge"], default="auto")
    a = ap.parse_args()
    solo_localhost(a.api)
    solo_localhost(a.front)

    salud = requests.get(f"{a.api}/api/health", timeout=5).json()
    print(f"Servidor en SECURITY_MODE={salud.get('security_mode')}")
    if salud.get("security_mode") == "off":
        raise SystemExit("En modo off el servidor no escribe log. Usa observe o enforce.")

    inicio = LOG_SERVIDOR.stat().st_size if LOG_SERVIDOR.exists() else 0
    visitantes = {"navegador": "demo-navegador-chrome", "script": "demo-script-requests"}

    print("Visitante 'navegador' (requests con encabezados de Chrome)...")
    visitar_con_requests(a.api, visitantes["navegador"], ENCABEZADOS_CHROME)
    print("Visitante 'script' (requests con encabezados por defecto)...")
    visitar_con_requests(a.api, visitantes["script"], None)

    extra = {}
    if not a.sin_selenium:
        print("Visitante 'selenium' (navegador automatizado headless)...")
        sid, webdriver, ua = visitar_con_selenium(a.front, a.navegador)
        if sid:
            visitantes["selenium"] = sid
        extra["selenium"] = {"navigator.webdriver": webdriver, "userAgent": ua}

    if a.con_humano:
        print(f"\n>> Abre {a.front}/cartas en tu navegador normal, navega un poco"
              " (cambia de página) y presiona Enter aquí.")
        input("> ")

    time.sleep(0.5)                              # deja que el servidor termine de escribir
    if not LOG_SERVIDOR.exists():
        raise SystemExit(f"No existe {LOG_SERVIDOR}. ¿El backend corre desde este repo?")
    lineas = [l for l in leer_log_desde(inicio) if l.get("type") == "request"]

    por_sid = {sid: nombre for nombre, sid in visitantes.items()}
    resultado: dict[str, dict] = {}
    for l in lineas:
        nombre = por_sid.get(l.get("sid"))
        if nombre is None:
            # Peticiones sin sid conocido: la primera de Selenium (antes de recibir la
            # cookie) o las del humano.
            ua = (l.get("user_agent") or "").lower()
            nombre = "selenium" if "headless" in ua else ("humano" if a.con_humano else None)
        if nombre and nombre not in resultado:
            resultado[nombre] = {k: l.get(k) for k in
                                 ("user_agent", "accept_language", "sec_ch_ua", "flags",
                                  "automation_suspected", "status", "path")}

    print(f"\n{'visitante':<11}{'sospechoso':<12}flags")
    for nombre in ("humano", "navegador", "script", "selenium"):
        if nombre in resultado:
            r = resultado[nombre]
            print(f"{nombre:<11}{str(r['automation_suspected']):<12}{', '.join(r['flags']) or '—'}")
            print(f"{'':<11}UA: {(r['user_agent'] or '(vacío)')[:90]}")
    if "selenium" in extra:
        print(f"\nnavigator.webdriver en la página de Selenium = {extra['selenium']['navigator.webdriver']}")

    EVIDENCIA.mkdir(exist_ok=True)
    salida = EVIDENCIA / "04_huellas_log.json"
    salida.write_text(json.dumps({"fecha": datetime.now().isoformat(timespec="seconds"),
                                  "security_mode": salud.get("security_mode"),
                                  "visitantes": resultado, "cliente": extra},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nEvidencia en {salida}")


if __name__ == "__main__":
    main()
