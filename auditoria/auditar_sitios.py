"""
Auditoría de mecanismos anti-bot en sitios web reales (Fase 2).

Para cada sitio hace MUY pocas peticiones (robots.txt + 2 GET a la portada y,
opcionalmente, una visita con Selenium) y clasifica las barreras que encuentra:

  Estáticas   : se ven en la respuesta HTTP sin ejecutar JavaScript
                (robots.txt, filtrado por User-Agent, encabezados de rate limit,
                 honeypots o tokens CSRF en el HTML).
  Dinámicas   : requieren ejecutar JavaScript o interactuar
                (contenido que se pinta con JS, CAPTCHA, scripts de huella digital).
  CDN / WAF   : el sitio está detrás de Cloudflare, Akamai, Imperva, AWS, etc.
                (se detecta por encabezados y cookies característicos).

Uso responsable: no hace ráfagas, no intenta evadir nada y se identifica.
Uso:
    python auditoria/auditar_sitios.py https://sitio1.gob.mx https://sitio2.com
    python auditoria/auditar_sitios.py --archivo auditoria/sitios.txt --selenium
Salida: auditoria/resultados/auditoria_<fecha>.csv y .md (tabla comparativa)
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

CARPETA = Path(__file__).resolve().parent / "resultados"
UA_NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 TCGVaultAuditoria/0.1 (proyecto escolar)")
HEADERS_NAVEGADOR = {"User-Agent": UA_NAVEGADOR, "Accept-Language": "es-MX,es;q=0.9",
                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

# Firmas de CDN/WAF: (nombre, encabezados, cookies, valores de "server"/"via")
FIRMAS_WAF = [
    ("Cloudflare", ["cf-ray", "cf-cache-status", "cf-mitigated"], ["__cf_bm", "cf_clearance", "__cflb"], ["cloudflare"]),
    ("Akamai", ["akamai-grn", "x-akamai-transformed", "akamai-cache-status"], ["_abck", "bm_sz", "ak_bmsc", "bm_sv"], ["akamaighost", "akamai"]),
    ("Imperva / Incapsula", ["x-iinfo", "x-cdn"], ["incap_ses", "visid_incap", "nlbi_"], ["incapsula", "imperva"]),
    ("AWS CloudFront / WAF", ["x-amz-cf-id", "x-amz-cf-pop"], ["aws-waf-token", "awsalb"], ["cloudfront", "awselb"]),
    ("Sucuri", ["x-sucuri-id", "x-sucuri-cache"], [], ["sucuri"]),
    ("F5 BIG-IP", [], ["bigipserver", "ts01", "f5_cspm"], ["big-ip", "bigip"]),
    ("Fastly", ["x-fastly-request-id", "fastly-debug-digest"], [], ["fastly"]),
    ("Azure Front Door", ["x-azure-ref"], [], ["azure"]),
]

SENALES_CAPTCHA = {
    "reCAPTCHA": ["google.com/recaptcha", "g-recaptcha", "grecaptcha"],
    "hCaptcha": ["hcaptcha.com", "h-captcha"],
    "Turnstile": ["challenges.cloudflare.com/turnstile", "cf-turnstile"],
    "Desafío Cloudflare": ["challenge-platform", "cf-chl", "just a moment", "cf_chl_opt"],
    "Akamai Bot Manager": ["/akam/", "bmak."],
    "PerimeterX / HUMAN": ["px-captcha", "perimeterx", "_pxappid"],
    "DataDome": ["datadome", "dd.js"],
}


def detectar_waf(resp: requests.Response) -> list[str]:
    h = {k.lower(): v.lower() for k, v in resp.headers.items()}
    cookies = " ".join(c.name.lower() for c in resp.cookies) + " " + h.get("set-cookie", "")
    servidor = h.get("server", "") + " " + h.get("via", "") + " " + h.get("x-cdn", "")
    hallados = []
    for nombre, encabezados, nombres_cookie, servidores in FIRMAS_WAF:
        if (any(e in h for e in encabezados) or any(c in cookies for c in nombres_cookie)
                or any(s in servidor for s in servidores)):
            hallados.append(nombre)
    return hallados


def revisar_robots(base: str) -> dict:
    url = urljoin(base, "/robots.txt")
    try:
        r = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=15)
    except requests.RequestException as e:
        return {"robots": f"error ({e.__class__.__name__})", "disallow": 0, "crawl_delay": ""}
    if r.status_code != 200 or "<html" in r.text[:200].lower():
        return {"robots": f"no publicado ({r.status_code})", "disallow": 0, "crawl_delay": ""}
    lineas = [l.strip().lower() for l in r.text.splitlines()]
    disallow = sum(1 for l in lineas if l.startswith("disallow:") and l.split(":", 1)[1].strip())
    delay = next((l.split(":", 1)[1].strip() for l in lineas if l.startswith("crawl-delay")), "")
    bloquea_todo = any(l == "disallow: /" for l in lineas)
    return {"robots": "sí" + (" (bloquea /)" if bloquea_todo else ""), "disallow": disallow, "crawl_delay": delay}


def senales_html(html: str) -> dict:
    bajo = html.lower()
    texto = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", bajo, flags=re.S)
    texto = re.sub(r"\s+", " ", texto).strip()
    scripts = len(re.findall(r"<script\b", bajo))
    raiz_vacia = bool(re.search(r'<div id="(root|app|__next|__nuxt)"[^>]*>\s*</div>', bajo))
    requiere_js = raiz_vacia or (len(texto) < 400 and scripts >= 3) or "enable javascript" in bajo \
        or "habilita javascript" in bajo or "__next_data__" in bajo or "ng-version" in bajo
    captchas = [n for n, firmas in SENALES_CAPTCHA.items() if any(f in bajo for f in firmas)]
    honeypot = bool(re.search(r'<input[^>]+(display:\s*none|visibility:\s*hidden|class="[^"]*(honeypot|hp-field))', bajo))
    csrf = bool(re.search(r'name="(csrf|_csrf|csrfmiddlewaretoken|__requestverificationtoken|authenticity_token)"', bajo))
    huella = any(s in bajo for s in ["fingerprintjs", "fpjs", "canvas.todataurl", "navigator.webdriver"])
    return {"texto_chars": len(texto), "scripts": scripts, "requiere_js": requiere_js, "captchas": captchas,
            "honeypot": honeypot, "csrf": csrf, "huella": huella}


def revisar_selenium(url: str) -> dict:
    """Abre el sitio con Selenium (una visita) y observa si aparece un desafío."""
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    try:
        opts = webdriver.ChromeOptions()
        opts.add_argument("--window-size=1280,900")
        d = webdriver.Chrome(options=opts)
    except Exception:  # noqa: BLE001 - sin Chrome: se usa Microsoft Edge
        opts = webdriver.EdgeOptions()
        opts.add_argument("--window-size=1280,900")
        d = webdriver.Edge(options=opts)
    try:
        d.get(url)
        time.sleep(6)                             # deja correr scripts de protección
        titulo = d.title
        html = d.page_source.lower()
        reto = [n for n, firmas in SENALES_CAPTCHA.items() if any(f in html for f in firmas)]
        visible = len(d.find_element(By.TAG_NAME, "body").text)
        CARPETA.mkdir(exist_ok=True)
        d.save_screenshot(str(CARPETA / f"selenium_{urlparse(url).netloc}.png"))
        return {"sel_titulo": titulo[:60], "sel_desafio": ", ".join(reto) or "no", "sel_texto_visible": visible}
    finally:
        d.quit()


def clasificar(fila: dict) -> str:
    tipos = []
    if fila["cdn_waf"] != "ninguno detectado":
        tipos.append("CDN/WAF")
    if fila["requiere_js"] == "sí" or fila["captcha"] != "no" or fila["huella_js"] == "sí":
        tipos.append("Dinámica")
    if (fila["ua_python"].startswith(("bloqueado", "distinto")) or "bloquea" in fila["robots"]
            or fila.get("crawl_delay")
            or fila["rate_limit_headers"] != "no" or fila["honeypot"] == "sí" or fila["csrf"] == "sí"):
        tipos.append("Estática")
    return " + ".join(tipos) or "Sin barreras visibles"


def auditar(url: str, con_selenium: bool) -> dict:
    print(f"\n== {url}")
    fila: dict = {"sitio": urlparse(url).netloc, "url": url}
    fila.update(revisar_robots(url))
    time.sleep(2)

    t0 = time.perf_counter()
    try:
        r = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=20, allow_redirects=True)
    except requests.RequestException as e:
        fila.update({"http": f"error ({e.__class__.__name__})", "clasificacion": "No accesible"})
        print(f"  no accesible: {e}")
        return fila
    fila["http"] = r.status_code
    fila["ms"] = int((time.perf_counter() - t0) * 1000)
    fila["servidor"] = r.headers.get("server", "—")
    fila["cdn_waf"] = ", ".join(detectar_waf(r)) or "ninguno detectado"
    rl = [k for k in r.headers if k.lower().startswith(("x-ratelimit", "ratelimit", "retry-after"))]
    fila["rate_limit_headers"] = ", ".join(rl) or "no"
    s = senales_html(r.text)
    fila["requiere_js"] = "sí" if s["requiere_js"] else "no"
    fila["captcha"] = ", ".join(s["captchas"]) or "no"
    fila["honeypot"] = "sí" if s["honeypot"] else "no"
    fila["csrf"] = "sí" if s["csrf"] else "no"
    fila["huella_js"] = "sí" if s["huella"] else "no"
    fila["texto_chars"] = s["texto_chars"]
    time.sleep(2)

    # ¿Trata distinto a un script que se presenta como tal?
    try:
        r2 = requests.get(url, timeout=20)   # User-Agent por defecto: python-requests/x.y
        if r2.status_code in (401, 403, 406, 429, 503):
            fila["ua_python"] = f"bloqueado ({r2.status_code})"
        elif abs(len(r2.text) - len(r.text)) > max(2000, 0.3 * len(r.text)):
            fila["ua_python"] = f"distinto contenido ({r2.status_code})"
        else:
            fila["ua_python"] = f"igual ({r2.status_code})"
    except requests.RequestException as e:
        fila["ua_python"] = f"error ({e.__class__.__name__})"

    if con_selenium:
        try:
            fila.update(revisar_selenium(url))
        except Exception as e:  # noqa: BLE001
            fila["sel_desafio"] = f"error ({e.__class__.__name__})"

    fila["clasificacion"] = clasificar(fila)
    for k in ["http", "cdn_waf", "robots", "requiere_js", "captcha", "ua_python", "clasificacion"]:
        print(f"  {k:<15} {fila.get(k)}")
    return fila


COLUMNAS = [("sitio", "Sitio"), ("http", "HTTP"), ("servidor", "Servidor"), ("cdn_waf", "CDN / WAF"),
            ("robots", "robots.txt"), ("disallow", "Reglas Disallow"), ("crawl_delay", "Crawl-delay"),
            ("ua_python", "UA python-requests"), ("rate_limit_headers", "Encabezados rate limit"),
            ("requiere_js", "Requiere JS"), ("captcha", "CAPTCHA / desafío"), ("honeypot", "Honeypot"),
            ("csrf", "Token CSRF"), ("huella_js", "Huella JS"), ("sel_desafio", "Desafío con Selenium"),
            ("clasificacion", "Clasificación")]


def guardar(filas: list[dict]) -> None:
    CARPETA.mkdir(exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d_%H%M")
    ruta_csv = CARPETA / f"auditoria_{sello}.csv"
    with ruta_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([t for _, t in COLUMNAS])
        for fila in filas:
            w.writerow([fila.get(k, "") for k, _ in COLUMNAS])
    ruta_md = CARPETA / f"auditoria_{sello}.md"
    lineas = ["| " + " | ".join(t for _, t in COLUMNAS) + " |",
              "|" + "---|" * len(COLUMNAS)]
    lineas += ["| " + " | ".join(str(f.get(k, "")) for k, _ in COLUMNAS) + " |" for f in filas]
    ruta_md.write_text(f"# Auditoría {sello}\n\n" + "\n".join(lineas) + "\n", encoding="utf-8")
    print(f"\nTabla guardada en:\n  {ruta_csv}\n  {ruta_md}")


def main():
    ap = argparse.ArgumentParser(description="Auditoría de barreras anti-bot (pocas peticiones)")
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--archivo", type=Path, help="archivo con una URL por línea")
    ap.add_argument("--selenium", action="store_true", help="además abre cada sitio con Selenium")
    a = ap.parse_args()
    urls = list(a.urls)
    if a.archivo:
        urls += [l.strip() for l in a.archivo.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
    if not urls:
        sys.exit("Indica al menos una URL o --archivo auditoria/sitios.txt")
    guardar([auditar(u, a.selenium) for u in urls])


if __name__ == "__main__":
    main()
