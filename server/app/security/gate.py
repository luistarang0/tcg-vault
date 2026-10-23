"""
Respuesta escalonada de las defensas 3 y 4, compartida por registro y login.

Calcula el puntaje (risk.py), lo registra y, solo en SECURITY_MODE=enforce, decide:
  0-59   continuar
  60-79  429 Too Many Requests + Retry-After (frenar)
  80-100 403 challenge_required; se continúa solo con token Turnstile válido
En off/observe siempre se continúa (en observe ya quedó registrado).

Uso en una ruta:
    bloqueo, riesgo = await risk_gate(request, payload, "login_attempt")
    if bloqueo:
        return bloqueo
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app import config
from app.security.audit import client_ip, log_event
from app.security.risk import Riesgo, score_request
from app.security.turnstile import verify_turnstile

BEHAVIOR_KEYS = ["fillTimeMs", "keyCount", "keyIntervalMeanMs", "keyIntervalStdMs", "mouseMoves",
                 "totalEvents", "trustedEvents", "webdriver", "pluginsLength", "languagesLength"]


def behavior_resumen(b: dict | None) -> dict:
    """Solo las métricas numéricas que se guardan en el log (nada de datos personales)."""
    if not isinstance(b, dict):
        return {}
    return {k: b.get(k) for k in BEHAVIOR_KEYS if k in b}


async def risk_gate(request: Request, payload, event: str) -> tuple[JSONResponse | None, Riesgo]:
    """
    `payload` debe tener los campos behavior, website (honeypot) y turnstile_token.
    Devuelve (respuesta_de_bloqueo_o_None, riesgo).
    """
    riesgo = score_request(request.headers, payload.behavior, payload.website)
    log_event(request, event, score=riesgo.score, flags=riesgo.flags,
              action=riesgo.accion, mode=config.SECURITY_MODE,
              behavior=behavior_resumen(payload.behavior),
              has_token=bool(payload.turnstile_token))

    if not config.should_enforce():
        return None, riesgo

    if riesgo.accion == "throttle":
        return JSONResponse(
            status_code=429,
            content={"ok": False, "error": "Demasiados intentos sospechosos. Intenta más tarde.",
                     "retry_after": config.RETRY_AFTER_SECONDS},
            headers={"Retry-After": str(config.RETRY_AFTER_SECONDS)},
        ), riesgo

    if riesgo.accion == "challenge":
        if not payload.turnstile_token:
            # Se pide el desafío. No se revela qué señales lo provocaron.
            return JSONResponse(status_code=403, content={
                "ok": False, "challenge_required": True,
                "sitekey": config.TURNSTILE_SITEKEY,
                "error": "Confirma que eres humano para continuar.",
            }), riesgo
        valido, errores = await verify_turnstile(payload.turnstile_token, client_ip(request))
        log_event(request, "turnstile_verify", success=valido, errors=errores)
        if not valido:
            return JSONResponse(status_code=403, content={
                "ok": False, "challenge_required": True,
                "sitekey": config.TURNSTILE_SITEKEY,
                "error": "La verificación no fue válida. Inténtalo de nuevo.",
            }), riesgo

    return None, riesgo
