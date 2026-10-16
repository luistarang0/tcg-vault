"""
Demostración de la Defensa 1 (rate limiting) para la Revisión 1.

Envía peticiones consecutivas SIN pausa a la API local y muestra en qué
momento el servidor empieza a responder 429 con Retry-After.

SOLO contra localhost. El script se niega a correr contra otro host.

Uso (con el backend corriendo en SECURITY_MODE=enforce):
    python scraper_tests/00_rate_limit_demo.py                  # 80 peticiones, misma sesión
    python scraper_tests/00_rate_limit_demo.py --no-cookies     # descarta la cookie sid
    python scraper_tests/00_rate_limit_demo.py --rotate-sid     # cookie distinta en cada petición
"""
import argparse
import time
from collections import Counter
from urllib.parse import urlparse

import requests

ALLOWED_HOSTS = {"localhost", "127.0.0.1"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/api/cards")
    ap.add_argument("-n", type=int, default=80, help="número de peticiones")
    ap.add_argument("--no-cookies", action="store_true", help="no reenviar la cookie sid")
    ap.add_argument("--rotate-sid", action="store_true", help="inventar un sid nuevo cada vez")
    args = ap.parse_args()

    # Salvaguarda: este proyecto solo se prueba contra su propio servidor
    if urlparse(args.url).hostname not in ALLOWED_HOSTS:
        raise SystemExit("Este script solo puede apuntar a localhost.")

    session = requests.Session()          # guarda y reenvía la cookie sid automáticamente
    codes, first_429 = [], None
    start = time.perf_counter()

    for i in range(1, args.n + 1):
        if args.no_cookies:
            session.cookies.clear()
        cookies = {"sid": f"rotada-{i}"} if args.rotate_sid else None
        r = session.get(args.url, params={"page": (i % 45) + 1}, cookies=cookies, timeout=5)
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


if __name__ == "__main__":
    main()
