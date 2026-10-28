"""
Extractor con Selenium de los catálogos públicos auditados (TAD 2.4).

Recorre los sitios que la auditoría clasificó como de extracción viable y guarda
los datos CRUDOS (texto tal como aparece en la página) para que limpieza.py los
estructure después:

  porke         menú por categoría (portada) + ficha de cada producto
                (calorías, porción, ingredientes, descripción larga)
  cafe          menú y promociones; el sitio cambia el NOMBRE de sus atributos
                data-* en cada despliegue, así que se localizan por su VALOR
                con XPath: //*[@*='menu-item']
  ticketshield  listado de eventos paginado ("Siguiente") + fichas con tipos de
                boleto, fecha completa y lugar
  tcgvault      sitio propio: catálogo paginado y subastas activas, leídos con el
                contrato estable data-* (la Defensa 5 cambia ids y clases, no esto)

Técnicas de Selenium que se usan: esperas explícitas (WebDriverWait +
expected_conditions), localizadores CSS y XPath (incluido following-sibling y
ancestros), clic en la paginación con espera de "staleness" del contenido
anterior, reintentos por página, capturas de pantalla como evidencia y cierre
garantizado del navegador en finally.

Uso (desde la raíz del proyecto, con el .venv activado):
    python extraccion_sitios/extractor.py                  # los 4 sitios, con ventana
    python extraccion_sitios/extractor.py --headless
    python extraccion_sitios/extractor.py --sitios cafe porke
    python extraccion_sitios/extractor.py --rapido         # prueba corta (2 páginas, 3 fichas)
Salida: extraccion_sitios/datos/crudos_<fecha>.json y capturas/<fecha>/*.png
Después: python extraccion_sitios/limpieza.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.robotparser
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from selenium.common.exceptions import (NoSuchElementException, StaleElementReferenceException,
                                        TimeoutException, WebDriverException)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper_tests"))
from config import ALLOWED_HOSTS, CAPTURAS, DATOS, ESPERA_S, PAUSA_S, REINTENTOS, SITIOS  # noqa: E402
from selenium_comun import crear_driver  # noqa: E402  (Chrome o, si no hay, Edge)


class SitioNoPermitido(Exception):
    pass


class Extractor:
    def __init__(self, headless: bool):
        self.ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.carpeta_capturas = CAPTURAS / self.ts
        self.carpeta_capturas.mkdir(parents=True, exist_ok=True)
        self.errores: list[dict] = []
        self.robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.d = crear_driver(headless=headless)
        self.w = WebDriverWait(self.d, ESPERA_S)
        print(f"Navegador: {getattr(self.d, 'origen_driver', '?')}")

    # ------------------------------------------------------------ utilidades
    def _robots(self, base: str) -> urllib.robotparser.RobotFileParser:
        """Lee robots.txt una vez por sitio. 404 = sin restricciones; 5xx se reintenta."""
        if base in self.robots:
            return self.robots[base]
        rp = urllib.robotparser.RobotFileParser()
        for intento in range(1, 4):
            try:
                r = requests.get(urljoin(base, "/robots.txt"), timeout=60,
                                 headers={"User-Agent": "TCGVaultExtractor/1.0 (proyecto escolar)"})
            except requests.RequestException as e:
                print(f"  robots.txt: {e.__class__.__name__}, reintento {intento}/3")
                time.sleep(10)
                continue
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
                break
            if 400 <= r.status_code < 500:
                rp.allow_all = True
                break
            print(f"  robots.txt respondió {r.status_code} (¿servidor despertando?), reintento {intento}/3")
            time.sleep(10)
        else:
            raise SitioNoPermitido(f"No se pudo leer {base}/robots.txt")
        self.robots[base] = rp
        return rp

    def abrir(self, url: str) -> None:
        """Navega solo si el host está permitido y robots.txt lo autoriza."""
        host = urlparse(url).netloc
        if host not in ALLOWED_HOSTS:
            raise SitioNoPermitido(f"{host} no está en la lista de sitios permitidos")
        base = f"{urlparse(url).scheme}://{host}"
        if not self._robots(base).can_fetch("*", url):
            raise SitioNoPermitido(f"robots.txt no permite {url}")
        self.d.get(url)

    def captura(self, nombre: str) -> None:
        self.d.save_screenshot(str(self.carpeta_capturas / f"{nombre}.png"))

    def reintentar(self, sitio: str, descripcion: str, funcion):
        """Ejecuta funcion() hasta REINTENTOS veces; si falla siempre, registra el error y sigue."""
        for intento in range(1, REINTENTOS + 1):
            try:
                return funcion()
            except (TimeoutException, StaleElementReferenceException, WebDriverException) as e:
                causa = (getattr(e, "msg", None) or str(e)).strip().splitlines()[0][:120] if str(e) else ""
                print(f"    ! {descripcion}: {e.__class__.__name__} {causa} (intento {intento}/{REINTENTOS})")
                time.sleep(2)
        self.errores.append({"sitio": sitio, "paso": descripcion, "url": self.d.current_url})
        return None

    @staticmethod
    def texto(raiz, by, selector, defecto: str = "") -> str:
        try:
            return raiz.find_element(by, selector).text.strip()
        except NoSuchElementException:
            return defecto

    @staticmethod
    def attr(raiz, by, selector, nombre, defecto: str = "") -> str:
        try:
            return raiz.find_element(by, selector).get_attribute(nombre) or defecto
        except NoSuchElementException:
            return defecto

    def siguiente_del_label(self, etiqueta: str) -> str:
        """Valor que sigue a una etiqueta de texto: <p>Calorías</p><p>480 cal</p>."""
        return self.texto(self.d, By.XPATH,
                          f"(//*[normalize-space()='{etiqueta}'])[last()]/following-sibling::*[1]")

    # ------------------------------------------------------------ Porké
    def porke(self) -> list[dict]:
        cfg = SITIOS["porke"]
        print(f"\n[Porké] {cfg['base']}")
        self.abrir(cfg["base"] + "/")
        self.w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/products/']")))
        self.captura("porke_menu")

        productos = []
        # Cada sección es un <h2> (categoría) seguido de la cuadrícula de tarjetas
        for h2 in self.d.find_elements(By.XPATH, "//main//h2"):
            categoria = h2.text.strip()
            for a in h2.find_elements(By.XPATH, "./following-sibling::div[1]//a[starts-with(@href,'/products/')]"):
                productos.append({
                    "id_externo": a.get_attribute("href").rstrip("/").split("/")[-1],
                    "categoria": categoria,
                    "nombre": self.texto(a, By.CSS_SELECTOR, "h3"),
                    "descripcion": self.texto(a, By.CSS_SELECTOR, "h3 + p"),
                    "precio_texto": self.texto(a, By.XPATH, ".//span[contains(.,'$')]"),
                    "imagen": self.attr(a, By.CSS_SELECTOR, "img", "src"),
                    "url": a.get_attribute("href"),
                })
        print(f"  {len(productos)} productos en {len({p['categoria'] for p in productos})} categorías")

        # Fichas de detalle: datos que no aparecen en la tarjeta
        for i, p in enumerate(productos[:cfg["max_fichas"]], 1):
            def ficha():
                self.abrir(p["url"])
                self.w.until(EC.presence_of_element_located(
                    (By.XPATH, "//*[normalize-space()='Calorías' or normalize-space()='Ingredientes']")))
                return {"detalle": self.siguiente_del_label("Detalles del Producto"),
                        "calorias_texto": self.siguiente_del_label("Calorías"),
                        "porcion": self.siguiente_del_label("Porción"),
                        "ingredientes": self.siguiente_del_label("Ingredientes")}
            datos = self.reintentar("porke", f"ficha {p['nombre']}", ficha)
            if datos:
                p.update(datos)
            if i == 1:
                self.captura("porke_ficha")
            print(f"  ficha {i}/{min(len(productos), cfg['max_fichas'])}: {p['nombre']}", end="\r")
            time.sleep(PAUSA_S)
        print()
        return productos

    # ------------------------------------------------------------ Café & Charla
    def cafe(self) -> tuple[list[dict], list[dict]]:
        cfg = SITIOS["cafe"]
        print(f"\n[Café & Charla] {cfg['base']}")
        # El nombre del atributo cambia (data-x3f8c45ea…); el valor no. @* = cualquier atributo.
        self.abrir(cfg["base"] + "/menu")
        self.w.until(EC.presence_of_element_located((By.XPATH, "//*[@*='menu-item']")))
        self.captura("cafe_menu")
        menu = [{
            "nombre": self.texto(li, By.XPATH, ".//*[@*='menu-name']"),
            "precio_texto": self.texto(li, By.XPATH, ".//*[@*='menu-price']"),
            "descripcion": self.texto(li, By.XPATH, ".//p[not(@*='menu-meta')]"),
            "meta": self.texto(li, By.XPATH, ".//*[@*='menu-meta']"),
            "imagen": self.attr(li, By.CSS_SELECTOR, "img", "src"),
            "url": cfg["base"] + "/menu",
        } for li in self.d.find_elements(By.XPATH, "//*[@*='menu-item']")]
        print(f"  {len(menu)} productos en el menú")
        time.sleep(PAUSA_S)

        self.abrir(cfg["base"] + "/promociones")
        self.w.until(EC.presence_of_element_located((By.XPATH, "//*[@*='promo-item']")))
        self.captura("cafe_promociones")
        promos = []
        for li in self.d.find_elements(By.XPATH, "//*[@*='promo-item']"):
            parrafos = [p.text.strip() for p in li.find_elements(By.XPATH, ".//p[not(@*='promo-discount')]")]
            promos.append({
                "titulo": self.texto(li, By.XPATH, ".//*[@*='promo-title']"),
                "descuento_texto": self.texto(li, By.XPATH, ".//*[@*='promo-discount']"),
                "descripcion": next((t for t in parrafos if not t.startswith("Válida")), ""),
                "vigencia_texto": next((t for t in parrafos if t.startswith("Válida")), ""),
            })
        print(f"  {len(promos)} promociones")
        return menu, promos

    # ------------------------------------------------------------ TicketShield
    def ticketshield(self) -> list[dict]:
        cfg = SITIOS["ticketshield"]
        print(f"\n[TicketShield] {cfg['base']}  (Render puede tardar ~1 min en despertar)")
        self.abrir(cfg["base"] + "/events")
        WebDriverWait(self.d, 150).until(            # espera larga solo para el arranque en frío
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/event/']")))
        self.captura("ticketshield_eventos")

        eventos, vistos = [], set()
        for pagina in range(1, cfg["max_paginas"] + 1):
            def leer_pagina():
                filas = []
                for a in self.d.find_elements(By.CSS_SELECTOR, "a[href*='/event/']"):
                    url = a.get_attribute("href")
                    if url in vistos:
                        continue
                    # lugar, duración y fecha: los <div> que siguen a cada ícono SVG
                    campos = [d.text.strip() for d in a.find_elements(By.XPATH, ".//*[local-name()='svg']/following-sibling::div")]
                    campos += [""] * (3 - len(campos))
                    filas.append({"slug": url.rstrip("/").split("/")[-1], "url": url,
                                  "categoria": self.texto(a, By.CSS_SELECTOR, "span"),
                                  "titulo": self.texto(a, By.CSS_SELECTOR, "h5"),
                                  "lugar": campos[0], "duracion_texto": campos[1],
                                  "fecha_tarjeta": campos[2], "pagina": pagina})
                return filas
            filas = self.reintentar("ticketshield", f"página {pagina}", leer_pagina) or []
            for f in filas:
                vistos.add(f["url"])
            eventos += filas
            print(f"  página {pagina}: {len(filas)} eventos (total {len(eventos)})")

            siguientes = self.d.find_elements(By.XPATH, "//a[normalize-space()='Siguiente' and @href]")
            if not siguientes:
                break                                 # última página: "Siguiente" ya no es enlace
            primera = self.d.find_element(By.CSS_SELECTOR, "a[href*='/event/']")
            siguientes[0].click()
            self.reintentar("ticketshield", f"cambio a página {pagina + 1}",
                            lambda: self.w.until(EC.staleness_of(primera)))
            self.w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/event/']")))
            time.sleep(PAUSA_S)

        # Fichas: tipos de boleto con precio, fecha completa (con año) y dirección
        for i, e in enumerate(eventos[:cfg["max_fichas"]], 1):
            def ficha():
                self.abrir(e["url"])
                self.w.until(EC.presence_of_element_located((By.XPATH, "//h5[normalize-space()='Tipos de Boletos']")))
                bloque = lambda t: [x.strip() for x in self.texto(  # noqa: E731
                    self.d, By.XPATH, f"//h5[normalize-space()='{t}']/../../..").splitlines() if x.strip()]
                fechas = bloque("Fechas y horas")
                boletos = bloque("Tipos de Boletos")[1:]            # sin el encabezado
                direccion = self.texto(self.d, By.XPATH, "//dt[normalize-space()='Direccion']/following-sibling::dd[1]")
                return {"fecha_ficha": fechas[1] if len(fechas) > 1 else "",
                        "boletos": [{"tipo": boletos[k], "precio_texto": boletos[k + 1]}
                                    for k in range(0, len(boletos) - 1, 2)],
                        "direccion": direccion.replace("Ver mapa", "").strip()}
            datos = self.reintentar("ticketshield", f"ficha {e['slug']}", ficha)
            if datos:
                e.update(datos)
            if i == 1:
                self.captura("ticketshield_ficha")
            print(f"  ficha {i}/{min(len(eventos), cfg['max_fichas'])}", end="\r")
            time.sleep(PAUSA_S)
        print()
        return eventos

    # ------------------------------------------------------------ TCG Vault (propio)
    def tcgvault(self) -> tuple[list[dict], list[dict]]:
        cfg = SITIOS["tcgvault"]
        print(f"\n[TCG Vault] {cfg['base']}")
        self.abrir(cfg["base"] + "/cartas")
        self.w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "article[data-card-id]")))
        self.captura("tcgvault_catalogo")

        cartas = []
        for pagina in range(1, cfg["max_paginas"] + 1):
            def leer_pagina():
                filas = []
                for art in self.d.find_elements(By.CSS_SELECTOR, "article[data-card-id]"):
                    g = art.get_attribute
                    filas.append({"id": g("data-card-id"), "nombre": g("data-card-name"),
                                  "tipos": g("data-type"), "coleccion": g("data-collection"),
                                  "generacion": g("data-generation"), "rareza": g("data-rarity"),
                                  "categoria": g("data-category"),
                                  "hp_texto": self.texto(art, By.XPATH, ".//span[starts-with(normalize-space(),'PS ')]"),
                                  "meta": self.texto(art, By.CSS_SELECTOR, "p"), "pagina": pagina})
                return filas
            filas = self.reintentar("tcgvault", f"página {pagina}", leer_pagina) or []
            cartas += filas
            print(f"  página {pagina}: {len(filas)} cartas (total {len(cartas)})", end="\r")
            siguiente = self.d.find_elements(By.CSS_SELECTOR, "a[rel='next']")   # enlace real de la paginación
            if not siguiente:
                break
            primera = self.d.find_element(By.CSS_SELECTOR, "article[data-card-id]")
            siguiente[0].click()
            self.reintentar("tcgvault", f"cambio a página {pagina + 1}",
                            lambda: self.w.until(EC.staleness_of(primera)))
            self.w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "article[data-card-id]")))
            time.sleep(PAUSA_S)
        print()

        time.sleep(PAUSA_S)
        self.abrir(cfg["base"] + "/subastas")
        self.w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-auction-id]")))
        self.captura("tcgvault_subastas")
        subastas = []
        for s in self.d.find_elements(By.CSS_SELECTOR, "article[data-auction-id]"):
            g = s.get_attribute
            subastas.append({"id": g("data-auction-id"), "carta_id": g("data-card-id"),
                             "carta": self.texto(s, By.CSS_SELECTOR, "h3"), "vendedor": g("data-seller"),
                             "puja_actual": g("data-current-bid"), "puja_minima": g("data-min-next-bid"),
                             "compra_inmediata": g("data-buyout"), "num_pujas": g("data-bids"),
                             "estado": g("data-status"),
                             "termina_en": self.attr(s, By.CSS_SELECTOR, "[data-ends-at]", "data-ends-at")})
        print(f"  {len(cartas)} cartas, {len(subastas)} subastas activas")
        return cartas, subastas

    def cerrar(self):
        self.d.quit()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sitios", nargs="+", choices=list(SITIOS), default=list(SITIOS))
    ap.add_argument("--headless", action="store_true", help="sin ventana del navegador")
    ap.add_argument("--rapido", action="store_true", help="prueba corta: 2 páginas y 3 fichas por sitio")
    a = ap.parse_args()
    if a.rapido:
        for cfg in SITIOS.values():
            for k in ("max_paginas", "max_fichas"):
                if k in cfg:
                    cfg[k] = 2 if k == "max_paginas" else 3

    inicio = datetime.now()
    salida = {"meta": {"inicio": inicio.isoformat(timespec="seconds"), "sitios": {}}}
    ex = Extractor(a.headless)
    try:
        for clave in a.sitios:
            t0 = time.perf_counter()
            try:
                if clave == "porke":
                    salida["porke_productos"] = ex.porke()
                elif clave == "cafe":
                    salida["cafe_menu"], salida["cafe_promociones"] = ex.cafe()
                elif clave == "ticketshield":
                    salida["ticketshield_eventos"] = ex.ticketshield()
                elif clave == "tcgvault":
                    salida["tcgvault_cartas"], salida["tcgvault_subastas"] = ex.tcgvault()
                estado = "ok"
            except (SitioNoPermitido, TimeoutException, WebDriverException) as e:
                estado = f"error: {e.__class__.__name__}: {str(e).splitlines()[0][:150] if str(e) else ''}"
                ex.errores.append({"sitio": clave, "paso": "sitio completo", "detalle": estado})
                print(f"  x {clave}: {estado}")
            salida["meta"]["sitios"][clave] = {**{k: v for k, v in SITIOS[clave].items() if not k.startswith("max_")},
                                               "estado": estado, "segundos": round(time.perf_counter() - t0, 1)}
    finally:
        ex.cerrar()                                   # el navegador se cierra aunque algo falle

    salida["meta"]["fin"] = datetime.now().isoformat(timespec="seconds")
    salida["meta"]["errores"] = ex.errores
    DATOS.mkdir(parents=True, exist_ok=True)
    archivo = DATOS / f"crudos_{ex.ts}.json"
    archivo.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nResumen")
    for k, v in salida.items():
        if k != "meta":
            print(f"  {k:<24} {len(v):>4} registros")
    print(f"  errores                  {len(ex.errores):>4}")
    print(f"\nCrudos en {archivo}\nCapturas en {ex.carpeta_capturas}")
    print("Siguiente paso: python extraccion_sitios/limpieza.py")


if __name__ == "__main__":
    main()
