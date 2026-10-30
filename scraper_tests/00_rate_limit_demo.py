"""
Demostración de la Defensa 1 (rate limiting) para la Revisión 1.

Envía peticiones consecutivas SIN pausa a la API y muestra en qué momento el
servidor empieza a responder 429 con Retry-After.

Solo contra sitios propios: localhost o el despliegue en Vercel (--produccion).
Cualquier otro dominio se rechaza.

Uso (con el backend en SECURITY_MODE=enforce):
    python scraper_tests/00_rate_limit_demo.py                  # 80 peticiones, misma sesión
    python scraper_tests/00_rate_limit_demo.py --no-cookies     # descarta la cookie sid
    python scraper_tests/00_rate_limit_demo.py --rotate-sid     # cookie distinta en cada petición
    python scraper_tests/00_rate_limit_demo.py --produccion     # contra tcg-vault-eight.vercel.app

Nota sobre Vercel: los contadores viven en la memoria de cada instancia de la
función. Si Vercel reparte la ráfaga entre varias instancias, el primer 429 puede
llegar más tarde que en local (o no llegar con pocas peticiones): súbelas con -n.
"""
import argparse
import time
from collections import Counter

import requests

from selenium_comun import PRODUCCION, solo_sitio_propio


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="por defecto http://localhost:8000/api/cards")
    ap.add_argument("--produccion", action="store_true", help=f"usa {PRODUCCION}/api/cards")
    ap.add_argument("-n", type=int, default=80, help="número de peticiones")
    ap.add_argument("--no-cookies", action="store_true", help="no reenviar la cookie sid")
    ap.add_argument("--rotate-sid", action="store_true", help="inventar un sid nuevo cada vez")
    args = ap.parse_args()
    url = args.url or (f"{PRODUCCION}/api/cards" if args.produccion else "http://localhost:8000/api/cards")

    # Salvaguarda: este proyecto solo se prueba contra sus propios servidores
    produccion = solo_sitio_propio(url)
    salud = requests.get(url.split("/api/")[0] + "/api/health", timeout=30).json()
    print(f"Destino: {url}  ({'producción' if produccion else 'local'}) · servidor: {salud}")

    session = requests.Session()          # guarda y reenvía la cookie sid automáticamente
    codes, first_429 = [], None
    start = time.perf_counter()

    for i in range(1, args.n + 1):
        if args.no_cookies:
            session.cookies.clear()
        cookies = {"sid": f"rotada-{i}"} if args.rotate_sid else None
        r = session.get(url, params={"page": (i % 40) + 1}, cookies=cookies, timeout=30 if produccion else 5)
        codes.append(r.status_code)
        if r.status_code == 429 and first_429 is None:
            first_429 = i
            print(f"\nPrimer 429 en la petición #{i}")
            print(f"  Retry-After: {r.headers.get('Retry-After')}")
            print(f"  Cuerpo:      {r.text}\n")
        print(r.status_code, end=" ", flush=True)

    elapsed = time.perf_counter() - start
    print(f"\n\nResumen en {elapsed:.2f} s: {dict(Counter(codes))}")
    if first_429 is None:
        print("No hubo 429. ¿El backend está en SECURITY_MODE=enforce?")
        if produccion:
            print("En Vercel también puede deberse a que la ráfaga se repartió entre varias instancias "
                  "(cada una cuenta por separado): prueba con -n 200.")
    if produccion:
        print("Los 429 de producción quedan en el panel /admin (evento rate_limited).")


if __name__ == "__main__":
    main()
