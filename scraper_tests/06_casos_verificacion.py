"""
Actividad 1 (TAD 2.4): casos de prueba de los mecanismos de verificación.

Envía POST /api/register DIRECTO al servidor (sin pasar por el formulario) con
respuestas incorrectas, campos vacíos, datos correctos y valores manipulados, y
muestra qué responde el servidor. Así se comprueba que las validaciones viven en
el backend: el formulario puede saltarse, el servidor no.

Mecanismos que se ejercitan:
  * Validación de campos (Pydantic)            -> 422
  * Honeypot + puntaje de comportamiento       -> 429 (60-79) / 403 desafío (>=80)
  * Turnstile validado en servidor             -> 403 con token vacío o inventado
  * Token CSRF (double-submit)                 -> 403 sin token o manipulado
  * Duplicados                                 -> 409

SOLO contra localhost. Arranque recomendado del backend (PowerShell, desde server/):
    $env:SECURITY_MODE="enforce"; $env:TURNSTILE_SECRET="2x0000000000000000000000000000000AA"; uvicorn app.main:app --port 8000
(la secreta 2x... de Cloudflare rechaza siempre: demuestra que un token inventado no pasa)
Para el caso "token válido" se usa la secreta 1x... (siempre acepta): --base http://localhost:8001

Uso:
    python scraper_tests/06_casos_verificacion.py
    python scraper_tests/06_casos_verificacion.py --solo-token-valido --base http://localhost:8001
Evidencia: scraper_tests/evidencia/06_casos_verificacion.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
EVIDENCIA = Path(__file__).resolve().parent / "evidencia"
NAVEGADOR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0 Safari/537.36",
             "Accept-Language": "es-MX,es;q=0.9"}
SCRIPT = {"User-Agent": "python-requests/2.34.2"}          # sin Accept-Language, como un script real
HUMANO = {"fillTimeMs": 9000, "keyCount": 30, "keyIntervalMeanMs": 150, "keyIntervalStdMs": 60,
          "mouseMoves": 80, "totalEvents": 120, "trustedEvents": 120, "webdriver": False}
TAG = time.strftime("%H%M%S")
resultados: list[dict] = []


def datos(n: int, sin_behavior: bool = False, **cambios) -> dict:
    d = {"collector_name": f"caso{TAG}_{n}", "email": f"caso{TAG}_{n}@prueba.test",
         "password": "Prueba-2026!", "behavior": HUMANO}
    d.update(cambios)
    if sin_behavior:
        d.pop("behavior")
    return d


def enviar(base: str, caso: str, cuerpo: dict, headers=NAVEGADOR, csrf: str | None = "cookie") -> None:
    s = requests.Session()
    s.headers.update(headers)
    s.get(f"{base}/api/health", timeout=10)          # entrega las cookies sid y csrf_token
    h = {}
    if csrf == "cookie":
        h["X-CSRF-Token"] = s.cookies.get("csrf_token", "")
    elif csrf:
        h["X-CSRF-Token"] = csrf                     # valor manipulado
    r = s.post(f"{base}/api/register", json=cuerpo, headers=h, timeout=20)
    try:
        j = r.json()
    except ValueError:
        j = {}
    detalle = j.get("detail")
    if isinstance(detalle, list) and detalle:
        detalle = f"{detalle[0].get('loc', ['', ''])[-1]}: {detalle[0].get('msg')}"
    msg = j.get("error") or j.get("message") or detalle or ""
    resultados.append({"caso": caso, "status": r.status_code, "respuesta": msg})
    print(f"{caso:<55} {r.status_code}  {str(msg)[:80]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--solo-token-valido", action="store_true",
                    help="solo el caso de puntaje alto + token (usar con la secreta 1x...)")
    a = ap.parse_args()
    if urlparse(a.base).hostname not in ALLOWED_HOSTS:
        raise SystemExit("Este script solo puede apuntar a localhost (tu propio servidor).")
    print(f"Servidor {a.base}: {requests.get(a.base + '/api/health', timeout=10).json()}\n")
    print(f"{'Caso':<55} HTTP  Respuesta del servidor")
    b = a.base

    if a.solo_token_valido:
        enviar(b, "16 Puntaje >=80 con token Turnstile aceptado",
               datos(16, sin_behavior=True, turnstile_token="XXXX.DUMMY.TOKEN.XXXX"), headers=SCRIPT)
    else:
        enviar(b, "01 Campos vacíos", {"collector_name": "", "email": "", "password": "", "behavior": HUMANO})
        enviar(b, "02 Correo inválido", datos(2, email="no-es-correo"))
        enviar(b, "03 Contraseña de 5 caracteres", datos(3, password="12345"))
        enviar(b, "04 Nombre con espacios y símbolos", datos(4, collector_name="Ash <script>"))
        enviar(b, "05 Datos correctos, interacción humana", datos(5))
        enviar(b, "06 Mismo nombre y correo otra vez", datos(5))
        enviar(b, "07 Honeypot lleno (campo website)", datos(7, website="https://spam.example"))
        enviar(b, "08 Sin métricas behavior (API directa)", datos(8, sin_behavior=True))
        enviar(b, "09 Métricas manipuladas (isTrusted, webdriver)",
               datos(9, behavior={**HUMANO, "trustedEvents": 3, "webdriver": True}))
        enviar(b, "10 Llenado en 0.4 s con tecleo robótico",
               datos(10, behavior={**HUMANO, "fillTimeMs": 400, "keyIntervalStdMs": 1}))
        enviar(b, "11 python-requests sin métricas (puntaje >=80)", datos(11, sin_behavior=True), headers=SCRIPT)
        enviar(b, "12 Puntaje >=80 con token vacío", datos(12, sin_behavior=True, turnstile_token=""),
               headers=SCRIPT)
        enviar(b, "13 Puntaje >=80 con token inventado",
               datos(13, sin_behavior=True, turnstile_token="token-inventado-por-el-bot"), headers=SCRIPT)
        enviar(b, "14 Datos correctos SIN token CSRF", datos(14), csrf=None)
        enviar(b, "15 Token CSRF manipulado", datos(15), csrf="valor-manipulado")

    EVIDENCIA.mkdir(exist_ok=True)
    salida = EVIDENCIA / ("06_token_valido.json" if a.solo_token_valido else "06_casos_verificacion.json")
    salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nEvidencia en {salida}")
    print("El puntaje y las señales de cada caso quedan en server/logs/access.jsonl (evento register_attempt).")


if __name__ == "__main__":
    main()
