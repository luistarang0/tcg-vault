"""
Defensa 3: puntaje de riesgo por comportamiento (+ honeypot).

El cliente (hook useBehaviorTracker de React) SOLO informa métricas; el servidor
decide. Puntos por señal (tabla del paso 7 de la guía):

  Honeypot lleno                                   +60
  Algún evento con isTrusted = false               +40
  navigator.webdriver = true                       +30
  User-Agent headless                              +30
  User-Agent vacío o de librería (requests, curl)  +30  (mismo peso que headless)
  Tiempo total de llenado < 1.5 s                  +25
  ≥10 pulsaciones con desviación < 5 ms            +20
  Sin mousemove ni teclas                          +15  (peso bajo: móvil y accesibilidad)
  Falta Accept-Language                            +10
  Sin objeto behavior (el cliente no lo envió)     +60  (script que llama a la API directo:
                                                         nuestro formulario SIEMPRE lo envía)

Máximo 100. Respuesta escalonada:
  0-29   permitir
  30-59  permitir y registrar
  60-79  frenar  (HTTP 429 + Retry-After)
  80-100 exigir desafío (Turnstile)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.security.audit import SCRIPT_UAS

# Umbrales: punto de partida, se ajustan revisando logs/access.jsonl
UMBRAL_REGISTRAR = 30
UMBRAL_FRENAR = 60
UMBRAL_DESAFIO = 80


@dataclass
class Riesgo:
    score: int
    flags: list[str] = field(default_factory=list)

    @property
    def accion(self) -> str:
        if self.score >= UMBRAL_DESAFIO:
            return "challenge"
        if self.score >= UMBRAL_FRENAR:
            return "throttle"
        if self.score >= UMBRAL_REGISTRAR:
            return "log"
        return "allow"


def _num(valor, defecto=0.0) -> float:
    """Convierte a número sin confiar en el cliente (puede mandar cualquier cosa)."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return defecto


def score_request(headers, behavior: dict | None, honeypot: str = "") -> Riesgo:
    """Calcula el puntaje de riesgo a partir de encabezados, métricas y honeypot."""
    score, flags = 0, []
    b = behavior if isinstance(behavior, dict) else None

    if honeypot and honeypot.strip():
        score += 60
        flags.append("honeypot")

    if b is None:
        score += 60
        flags.append("no_behavior")
        b = {}

    total_events = int(_num(b.get("totalEvents")))
    trusted_events = int(_num(b.get("trustedEvents")))
    if total_events > trusted_events:
        score += 40
        flags.append("untrusted_events")

    if b.get("webdriver") is True:
        score += 30
        flags.append("webdriver")

    if "headlesschrome" in (headers.get("user-agent", "") or "").lower():
        score += 30
        flags.append("headless_ua")

    ua_l = (headers.get("user-agent", "") or "").lower()
    if not ua_l or any(s in ua_l for s in SCRIPT_UAS):
        score += 30
        flags.append("script_ua")

    fill_ms = _num(b.get("fillTimeMs"), defecto=-1)
    if 0 <= fill_ms < 1500:
        score += 25
        flags.append("fast_fill")

    keys = int(_num(b.get("keyCount")))
    std = _num(b.get("keyIntervalStdMs"), defecto=999)
    if keys >= 10 and std < 5:
        score += 20
        flags.append("robotic_typing")

    if int(_num(b.get("mouseMoves"))) == 0 and keys == 0 and "no_behavior" not in flags:
        score += 15
        flags.append("no_interaction")

    if not headers.get("accept-language"):
        score += 10
        flags.append("no_accept_language")

    return Riesgo(min(score, 100), flags)
