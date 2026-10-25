"""
Actividad 3 (TAD 2.4): el reto de las n solicitudes.

Demuestra que el límite de solicitudes vive en el BACKEND (no en un botón
deshabilitado) y documenta a qué se aplica: IP + sesión, solo IP y cuenta.
Llama a la API directamente con `requests`, sin pasar por la interfaz: si el
límite fuera solo del frontend, este script nunca vería un 429.

Usa POST /api/login con dos límites distintos:
  * RATE_LIMIT_LOGIN (por IP + cookie `sid`), que para esta prueba se configura
    en 5/minute al arrancar el backend.
  * Bloqueo por CUENTA: LOGIN_MAX_FAILS=5 fallos en LOGIN_WINDOW_MIN=15 minutos,
    guardado en Postgres (no se evita cambiando de sesión ni de IP).

Fases:
  A  5 inicios de sesión válidos + extras en la MISMA sesión  -> 200 x5, luego 429
  B  la misma prueba con una sesión NUEVA (otra cookie sid)    -> 200 (la clave incluye la sesión)
  C  esperar Retry-After y repetir en la sesión original       -> 200 de nuevo
  D  contraseña incorrecta, sesión NUEVA en cada intento       -> 401 x5, luego 429 (por cuenta)
     y después ni la contraseña correcta entra                 -> 429

SOLO contra localhost. Arranque del backend para esta prueba (PowerShell, desde server/):
    $env:SECURITY_MODE="enforce"; $env:RATE_LIMIT_LOGIN="5/minute"; uvicorn app.main:app --port 8000
Uso:
    python scraper_tests/05_reto_n_solicitudes.py
    python scraper_tests/05_reto_n_solicitudes.py --extra 3 --sin-espera
Evidencia: scraper_tests/evidencia/05_reto_n_solicitudes.json
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
EVIDENCIA = Path(__file__).resolve().parent / "evidencia"
LOG_SERVIDOR = Path(__file__).resolve().parent.parent / "server" / "logs" / "access.jsonl"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0 Safari/537.36 TCGVaultReto/1.0",
           "Accept-Language": "es-MX,es;q=0.9"}
# Métricas plausibles para que el puntaje de riesgo no intervenga: aquí se prueba el límite, no el puntaje
BEHAVIOR = {"fillTimeMs": 4200, "keyCount": 18, "keyIntervalMeanMs": 140, "keyIntervalStdMs": 45,
            "mouseMoves": 25, "totalEvents": 40, "trustedEvents": 40, "webdriver": False}
filas: list[dict] = []


def nueva_sesion(base: str) -> requests.Session:
    """Sesión nueva = cookie `sid` nueva. /api/health entrega también la cookie csrf_token."""
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f"{base}/api/health", timeout=10)
    return s


def post(s: requests.Session, base: str, path: str, data: dict) -> requests.Response:
    # El token CSRF se copia de la cookie al encabezado, como hace el frontend
    return s.post(f"{base}{path}", json=data, timeout=20,
                  headers={"X-CSRF-Token": s.cookies.get("csrf_token", "")})


def login(s, base, usuario, password, fase, n):
    t = time.perf_counter()
    r = post(s, base, "/api/login", {"username": usuario, "password": password, "behavior": BEHAVIOR})
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = {}
    fila = {"fase": fase, "n": n, "sid": s.cookies.get("sid", "")[:6], "status": r.status_code,
            "retry_after": r.headers.get("Retry-After"), "mensaje": cuerpo.get("error") or cuerpo.get("detail") or "ok",
            "ms": round((time.perf_counter() - t) * 1000)}
    filas.append(fila)
    print(f"  {fase:<2} #{n:<2} sid={fila['sid']:<7} {fila['status']}  "
          f"{'Retry-After=' + fila['retry_after'] if fila['retry_after'] else '':<16} {fila['mensaje'][:60]}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--limite", type=int, default=5, help="límite configurado en RATE_LIMIT_LOGIN (por minuto)")
    ap.add_argument("--extra", type=int, default=2, help="solicitudes extra después del límite")
    ap.add_argument("--sin-espera", action="store_true", help="omite la fase C (esperar el reinicio)")
    a = ap.parse_args()
    if urlparse(a.base).hostname not in ALLOWED_HOSTS:
        raise SystemExit("Este script solo puede apuntar a localhost (tu propio servidor).")

    salud = requests.get(f"{a.base}/api/health", timeout=10).json()
    print(f"Servidor: {salud}")
    if salud.get("security_mode") != "enforce":
        print("AVISO: el servidor no está en enforce; no aparecerán 429.")
    inicio_log = LOG_SERVIDOR.stat().st_size if LOG_SERVIDOR.exists() else 0
    inicio = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Cuenta de prueba nueva (nombre único por ejecución)
    usuario, password = f"reto_{time.strftime('%H%M%S')}", "ContrasenaReto-2026"
    s = nueva_sesion(a.base)
    r = post(s, a.base, "/api/register", {"collector_name": usuario, "email": f"{usuario}@prueba.test",
                                          "password": password, "behavior": BEHAVIOR})
    print(f"Cuenta de prueba {usuario}: HTTP {r.status_code}\n")
    if r.status_code != 201:
        raise SystemExit(f"No se pudo crear la cuenta: {r.text[:200]}")

    print(f"[A] {a.limite} solicitudes válidas + {a.extra} extra en la MISMA sesión")
    s = nueva_sesion(a.base)
    for n in range(1, a.limite + a.extra + 1):
        r = login(s, a.base, usuario, password, "A", n)
    retry = int(r.headers.get("Retry-After") or 60)

    print("\n[B] Sesión NUEVA (otra cookie sid), misma IP")
    login(nueva_sesion(a.base), a.base, usuario, password, "B", 1)

    if not a.sin_espera:
        print(f"\n[C] Esperando {retry + 2} s a que se reinicie la ventana…")
        time.sleep(retry + 2)
        for n in range(1, a.limite + 2):
            login(s, a.base, usuario, password, "C", n)

    print("\n[D] Contraseña incorrecta, con una sesión NUEVA en cada intento (límite por cuenta)")
    for n in range(1, 7):
        login(nueva_sesion(a.base), a.base, usuario, "incorrecta-" + str(n), "D", n)
    print("    …y ahora con la contraseña CORRECTA:")
    login(nueva_sesion(a.base), a.base, usuario, password, "D", 7)

    # Lo que el servidor registró durante la prueba
    eventos = []
    if LOG_SERVIDOR.exists():
        with LOG_SERVIDOR.open(encoding="utf-8") as f:
            f.seek(inicio_log)
            for linea in f:
                try:
                    e = json.loads(linea)
                except ValueError:
                    continue
                if e.get("path") == "/api/login" and (e.get("type") == "event" or e.get("status") == 429):
                    eventos.append(e)
        print(f"\nRegistro del servidor (server/logs/access.jsonl): {len(eventos)} líneas de /api/login")
        for e in eventos[-12:]:
            if e["type"] == "request":
                print(f"  {e['ts'][11:23]}  request  status={e['status']}  sid={str(e.get('sid'))[:6]}")
            else:
                extra = e.get("result") or e.get("action") or ""
                print(f"  {e['ts'][11:23]}  {e['event']:<14} {extra}")
    else:
        print("\n(No se encontró server/logs/access.jsonl en esta máquina)")

    EVIDENCIA.mkdir(exist_ok=True)
    salida = EVIDENCIA / "05_reto_n_solicitudes.json"
    salida.write_text(json.dumps({"inicio": inicio, "servidor": salud, "usuario": usuario, "limite": a.limite,
                                  "solicitudes": filas, "eventos_log": eventos}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\nEvidencia guardada en {salida}")


if __name__ == "__main__":
    main()
