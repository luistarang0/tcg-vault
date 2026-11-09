"""
Actividad 1: auditoría comparativa de los 5 sitios.

Para cada sitio mide evidencias verificables con muy pocas peticiones:
  * Certificado TLS del dominio que indica la actividad.
  * robots.txt: reglas, Crawl-delay y si las rutas de datos están permitidas.
  * Respuesta HTTP: servidor, CDN/WAF, tamaño, filtros, paginación y descargas.
  * API oficial: solo se consulta si existe, no pide token y robots.txt la permite.
  * Navegador: si carga, qué tanto contenido agrega JavaScript y si hay bloqueo.
Con esas señales aplica la regla de config.py y clasifica en básico/intermedio/avanzado.

Salidas: resultados/auditoria.json, matriz_comparativa.csv, matriz_comparativa.md
         y resultados/capturas/<sitio>.png

Uso:  python actividad_datos_abiertos/01_auditoria.py [--headless] [--solo data_gov]
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import time
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException, WebDriverException

import config
from comun import (AccesoNoPermitido, Bitacora, Bloqueado, Cliente, TextoEstable, CuentaEstable, abrir_navegador,
                   args_headless, esperar, guardar_csv, guardar_json, tabla_md)

EXTENSIONES = r"\.(csv|xlsx?|json|xml|zip|pdf|kml|geojson)(\?|$)"
ENCABEZADOS_CDN = {"cf-ray": "Cloudflare", "x-akamai-transformed": "Akamai", "x-amz-cf-id": "CloudFront",
                   "x-fastly-request-id": "Fastly", "x-cdn": "CDN"}


def revisar_tls(url: str) -> dict:
    """Solo hace el saludo TLS, sin petición HTTP. Nunca se desactiva la verificación."""
    host = urlparse(url).netloc
    try:
        with socket.create_connection((host, 443), timeout=20) as s, \
                ssl.create_default_context().wrap_socket(s, server_hostname=host):
            return {"host": host, "valido": True, "detalle": "certificado válido para el dominio"}
    except ssl.SSLCertVerificationError as e:
        return {"host": host, "valido": False, "detalle": e.verify_message}
    except OSError as e:
        return {"host": host, "valido": False, "detalle": f"{e.__class__.__name__}: {e}"}


def revisar_robots(c: Cliente, sitio: dict) -> dict:
    rp = c.robots_de(sitio["pagina"])
    return {"host": urlparse(sitio["pagina"]).netloc,
            "reglas_para_todos": len(rp.reglas),
            "crawl_delay": rp.crawl,
            "pagina_permitida": rp.permite(sitio["pagina"]),
            "rutas_datos_prohibidas": [u for u in sitio["rutas_datos"] if not rp.permite(u)]}


def medir_http(c: Cliente, sitio: dict) -> dict:
    c.comprobar(sitio["pagina"])
    inicio = time.perf_counter()
    r = c.s.get(sitio["pagina"], timeout=config.TIMEOUT_HTTP_S)
    segundos = round(time.perf_counter() - inicio, 2)
    html = BeautifulSoup(r.text, "html.parser")
    enlaces = [a["href"] for a in html.find_all("a", href=True)]
    cdn = sorted({n for h, n in ENCABEZADOS_CDN.items() if h in {k.lower() for k in r.headers}})
    if "cloudflare" in r.headers.get("server", "").lower():
        cdn = sorted(set(cdn) | {"Cloudflare"})
    filas = len(html.select(sitio["selector_datos"])) if sitio["selector_datos"] else None
    for basura in html(["script", "style", "noscript", "template"]):
        basura.decompose()
    return {"estado": r.status_code, "servidor": r.headers.get("server"), "cdn_waf": cdn,
            "bytes": len(r.content), "segundos": segundos,
            "texto_visible": len(" ".join(html.get_text().split())),
            "formularios": len(html.find_all("form")), "tablas": len(html.find_all("table")),
            "filtros": len(html.select("select, input[type=checkbox], input[type=radio]")),
            "buscador": bool(html.select("input[type=search], input[name=q], input[type=text]")),
            "paginacion": bool(re.search(r"[?&](amp;)?(page|after)=", r.text))    # también cursores y hx-get
                          or any(re.search(r"pagina", e, re.I) for e in enlaces),
            "descargas_directas": sorted({m.group(1).lower() for e in enlaces if (m := re.search(EXTENSIONES, e, re.I))}),
            "filas_de_datos": filas}


def revisar_api(c: Cliente, sitio: dict, b: Bitacora) -> dict:
    api = sitio["api"]
    if not api:
        return {"nombre": None, "estado": "sin API pública encontrada"}
    salida = {"nombre": api["nombre"], "requiere_token": api["requiere_token"]}
    if api["requiere_token"]:
        return {**salida, "estado": "no consultada: exige token personal (ver documentación)"}
    if not c.permitido(api["url_prueba"]):
        b.evento("medida", f"{sitio['clave']}: API no consultada porque robots.txt la prohíbe")
        return {**salida, "estado": "no consultada: robots.txt prohíbe la ruta"}
    r = c.get(api["url_prueba"])
    return {**salida, "estado": f"HTTP {r.status_code}", "tipo": r.headers.get("content-type")}


def revisar_documentos(c: Cliente, sitio: dict, b: Bitacora) -> dict:
    salida = {}
    for nombre, url in sitio["documentos"].items():
        try:
            r = c.get(url)
            salida[nombre] = {"url": url, "estado": r.status_code,
                              "menciona_api": bool(re.search(r"\bAPI\b", r.text))}
        except (requests.RequestException, AccesoNoPermitido) as e:
            salida[nombre] = {"url": url, "estado": f"no verificado: {e.__class__.__name__}"}
            b.evento("error", f"{sitio['clave']}: documento {nombre} no verificado ({e.__class__.__name__})")
    return salida


def medir_navegador(c: Cliente, driver, sitio: dict, b: Bitacora) -> dict:
    captura = config.CAPTURAS / f"{sitio['clave']}.png"
    captura.parent.mkdir(parents=True, exist_ok=True)
    for intento in (1, 2):                            # un reintento solo si el sitio tardó de más
        try:
            c.navegar(driver, sitio["pagina"])
            condicion = CuentaEstable(sitio["selector_datos"]) if sitio["selector_datos"] else TextoEstable()
            esperar(driver, condicion)
            break
        except Bloqueado as e:
            driver.save_screenshot(str(captura))
            b.evento("bloqueo", f"{sitio['clave']}: {e}. Se detiene el navegador para este sitio.")
            return {"bloqueado": True, "detalle": str(e), "titulo": driver.title}
        except TimeoutException:
            b.evento("error", f"{sitio['clave']}: el navegador agotó el tiempo (intento {intento} de 2)")
            if intento == 2:
                return {"bloqueado": False, "error": "TimeoutException"}
        except WebDriverException as e:
            b.evento("error", f"{sitio['clave']}: navegador {e.__class__.__name__}")
            return {"bloqueado": False, "error": e.__class__.__name__}
    driver.save_screenshot(str(captura))
    medir = driver.execute_script("""
        return {texto: document.body.innerText.replace(/\\s+/g,' ').trim().length,
                nodos: document.querySelectorAll('*').length,
                tablas: document.querySelectorAll('table').length,
                filtros: document.querySelectorAll('select,input[type=checkbox],input[type=radio]').length,
                webdriver: navigator.webdriver === true}""")
    filas = len(driver.find_elements("css selector", sitio["selector_datos"])) if sitio["selector_datos"] else None
    return {"bloqueado": False, "titulo": driver.title, "filas_de_datos": filas, **medir}


def clasificar(reg: dict, sitio: dict) -> tuple[str, int, list[str]]:
    """Aplica la regla fijada en config.py y devuelve las razones como evidencia."""
    puntos, razones = 0, []
    http, nav, robots = reg["http"], reg["navegador"], reg["robots"]
    if nav.get("bloqueado"):
        puntos += 2
        razones.append(f"+2 bloquea al navegador automatizado ({nav.get('titulo')})")
    if http.get("cdn_waf") and not nav.get("bloqueado"):
        puntos += 1
        razones.append(f"+1 CDN/WAF visible: {', '.join(http['cdn_waf'])}")
    dinamico = False
    if not nav.get("bloqueado") and nav.get("texto"):
        filas_http, filas_nav = http.get("filas_de_datos"), nav.get("filas_de_datos")
        if filas_nav and filas_http == 0:
            dinamico = True
            razones.append(f"+1 datos solo con JavaScript: {filas_http} filas por HTTP, {filas_nav} en navegador")
        elif filas_nav is None and nav["texto"] >= 1.5 * max(http.get("texto_visible", 1), 1):
            dinamico = True
            razones.append(f"+1 JavaScript agrega contenido: {http.get('texto_visible')} caracteres por HTTP, "
                           f"{nav['texto']} en navegador")
    puntos += int(dinamico)
    reg["dinamico"] = dinamico
    if robots.get("crawl_delay"):
        puntos += 1
        razones.append(f"+1 robots.txt pide Crawl-delay de {robots['crawl_delay']:g} s")
    if robots.get("rutas_datos_prohibidas"):
        puntos += 1
        razones.append("+1 robots.txt prohíbe rutas de datos: " + ", ".join(
            urlparse(u).path for u in robots["rutas_datos_prohibidas"]))
    if sitio["api"] and sitio["api"]["requiere_token"]:
        puntos += 1
        razones.append("+1 la API oficial exige token")
    nivel = ("avanzado" if puntos >= config.UMBRAL_AVANZADO
             else "intermedio" if puntos >= config.UMBRAL_INTERMEDIO else "básico")
    return nivel, puntos, razones or ["0 sin señales: HTML directo, sin bloqueo ni restricciones"]


def fila_matriz(reg: dict, sitio: dict) -> dict:
    http, nav, robots, api = reg["http"], reg["navegador"], reg["robots"], reg["api"]
    return {
        "Sitio": sitio["nombre"],
        "Navegación": sitio["navegacion"],
        "TLS": "OK" if reg["tls"]["valido"] else f"Falla en {reg['tls']['host']}",
        "Filtros (HTTP / navegador)": f"{http.get('filtros', '?')} / {nav.get('filtros', 'no medible')}",
        "Paginación": "Sí" if http.get("paginacion") else "No visible",
        "Dinámico": "Sí" if reg.get("dinamico") else ("No medible" if nav.get("bloqueado") or nav.get("error") else "No"),
        "Formatos": sitio["formatos"],
        "Crawl-delay": robots.get("crawl_delay") or "No",
        "API": f"{api.get('nombre') or 'No'}: {api['estado']}",
        "Documentos": "; ".join(f"{k} ({v['estado']})" for k, v in reg["documentos"].items()),
        "Condiciones de uso": sitio["condiciones"],
        "Clasificación": f"{reg['nivel']} ({reg['puntos']} pts)",
        "Justificación": "; ".join(reg["razones"]),
        "Método propuesto": sitio["metodo"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--headless", action="store_true", help="sin ventana del navegador")
    ap.add_argument("--solo", choices=[s["clave"] for s in config.SITIOS],
                    help="vuelve a medir solo este sitio y conserva lo ya medido de los demás")
    a = ap.parse_args()

    b = Bitacora("01_auditoria")
    c = Cliente(b)
    driver = abrir_navegador(args_headless())
    b.evento("herramienta", f"Selenium con {driver.nombre_navegador}; requests; BeautifulSoup")
    archivo = config.RESULTADOS / "auditoria.json"
    previos = {r["clave"]: r for r in json.loads(archivo.read_text(encoding="utf-8"))} if a.solo and archivo.exists() else {}
    registros = []
    try:
        for sitio in config.SITIOS:
            if a.solo and sitio["clave"] != a.solo:
                if sitio["clave"] in previos:
                    registros.append(previos[sitio["clave"]])
                continue
            print(f"\n=== {sitio['nombre']}")
            reg = {"clave": sitio["clave"], "nombre": sitio["nombre"], "fecha": datetime.now().isoformat(timespec="seconds"),
                   "tls": revisar_tls(sitio["url_actividad"])}
            if not reg["tls"]["valido"]:
                b.evento("error", f"{sitio['clave']}: TLS de {reg['tls']['host']}: {reg['tls']['detalle']}. "
                                  f"Se usa {urlparse(sitio['pagina']).netloc}; no se desactiva la verificación.")
            reg["robots"] = revisar_robots(c, sitio)
            reg["http"] = medir_http(c, sitio)
            reg["api"] = revisar_api(c, sitio, b)
            reg["documentos"] = revisar_documentos(c, sitio, b)
            reg["navegador"] = medir_navegador(c, driver, sitio, b)
            reg["nivel"], reg["puntos"], reg["razones"] = clasificar(reg, sitio)
            print(f"  => {reg['nivel']} ({reg['puntos']} pts): " + "; ".join(reg["razones"]))
            registros.append(reg)
    finally:
        driver.quit()

    guardar_json(archivo, registros)
    por_clave = {s["clave"]: s for s in config.SITIOS}
    matriz = pd.DataFrame([fila_matriz(r, por_clave[r["clave"]]) for r in registros])
    guardar_csv(config.RESULTADOS / "matriz_comparativa.csv", matriz)
    (config.RESULTADOS / "matriz_comparativa.md").write_text(
        f"# Matriz comparativa de los 5 sitios\n\nGenerada el {datetime.now():%Y-%m-%d %H:%M}.\n\n{tabla_md(matriz)}\n",
        encoding="utf-8")
    print(f"\nListo: {config.RESULTADOS / 'matriz_comparativa.md'}")


if __name__ == "__main__":
    main()
