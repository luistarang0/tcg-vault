"""
Defensa 4: CAPTCHA con Cloudflare Turnstile, validado en el SERVIDOR.

El navegador resuelve el widget y obtiene un token. Ese token no prueba nada por
sí mismo: el servidor lo envía a Cloudflare junto con la clave SECRETA y solo
Cloudflare responde si es válido. Por eso un bot que "dice" que pasó el CAPTCHA
(mandando cualquier texto como token) es rechazado igual.

Claves de prueba oficiales de Cloudflare (sección Testing de su documentación):
  sitekey 1x00000000000000000000AA          -> el widget siempre pasa (visible)
  sitekey 3x00000000000000000000FF          -> fuerza un desafío interactivo
  secret  1x0000000000000000000000000000000AA -> la validación siempre pasa
  secret  2x0000000000000000000000000000000AA -> la validación siempre falla

Si la verificación no se puede completar (sin red, timeout), se RECHAZA
(falla cerrada): ante la duda, no se deja pasar.
"""
from __future__ import annotations

import httpx

from app import config

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(token: str | None, ip: str) -> tuple[bool, list[str]]:
    """Devuelve (válido, códigos_de_error). El token es de un solo uso."""
    if not token:
        return False, ["missing-input-response"]
    if not config.TURNSTILE_SECRET:
        return False, ["missing-input-secret"]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(config.TURNSTILE_VERIFY_URL, data={
                "secret": config.TURNSTILE_SECRET,
                "response": token,
                "remoteip": ip,
            })
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return False, [f"verify-unavailable:{e.__class__.__name__}"]
    return bool(data.get("success")), list(data.get("error-codes", []))
