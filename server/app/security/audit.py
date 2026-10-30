"""
Defensa 2: logging de peticiones y detección de huellas de automatización.

Cada petición a /api/* se escribe como UNA línea JSON en server/logs/access.jsonl.
Se ETIQUETA (no se bloquea) cuando aparecen señales típicas de un navegador
automatizado o de un script:

  * headless_ua         : el User-Agent contiene "HeadlessChrome" (Chrome sin ventana)
  * empty_ua            : no hay User-Agent
  * script_ua           : el User-Agent es de una librería (python-requests, curl, etc.)
  * no_accept_language  : falta Accept-Language (los navegadores reales siempre lo envían)
  * sec_ch_ua_mismatch  : Sec-CH-UA dice una cosa y el User-Agent otra
  * bot_id              : el cliente se identifica como bot (ej. nuestro TCGVaultEduBot)

Además expone `log_event()` para que otras defensas (puntaje de riesgo, Turnstile)
agreguen eventos al mismo archivo. Nunca se registran contraseñas ni el cuerpo
de los formularios.

Bitácora persistente: los eventos de log_event() y cada respuesta 429 también se
guardan en Postgres (tabla security_events) si config.SECURITY_EVENTS_DB está
activo (por defecto en Vercel, donde el archivo de /tmp se pierde). Se acumulan
durante la petición y se insertan juntos al final, con una sola conexión; si la
base falla, la respuesta sale igual (la bitácora nunca tumba al sitio).

Solo escribe en modos observe y enforce (config.should_log()).
"""
from __future__ import annotations

import json
import logging
import random
import threading
from datetime import datetime, timezone

from psycopg.types.json import Jsonb
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app import config
from app.pg import get_pg

LOG_DIR = config.LOG_DIR                    # server/logs en local, /tmp en Vercel
LOG_FILE = LOG_DIR / "access.jsonl"
_lock = threading.Lock()                    # evita líneas mezcladas entre hilos
consola = logging.getLogger("uvicorn.error")  # mismo canal que usa uvicorn para imprimir

SCRIPT_UAS = ("python-requests", "python-urllib", "curl/", "wget/", "httpx", "aiohttp",
              "go-http-client", "java/", "okhttp", "scrapy", "node-fetch", "axios")


def client_ip(request: Request) -> str:
    # En Vercel request.client es el proxy de la plataforma; la IP real la agrega
    # Vercel en X-Forwarded-For (sobrescribe lo que mande el cliente). En local no
    # se confía en ese encabezado porque cualquiera podría inventarlo.
    if config.ON_VERCEL:
        reenviada = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if reenviada:
            return reenviada
    return request.client.host if request.client else "desconocida"


def header_flags(headers) -> list[str]:
    """Señales de automatización que se pueden leer en los encabezados HTTP."""
    flags: list[str] = []
    ua = headers.get("user-agent", "") or ""
    ua_l = ua.lower()
    if not ua:
        flags.append("empty_ua")
    if "headlesschrome" in ua_l:
        flags.append("headless_ua")
    if any(s in ua_l for s in SCRIPT_UAS):
        flags.append("script_ua")
    if "bot" in ua_l or "crawler" in ua_l or "spider" in ua_l:
        flags.append("bot_id")
    if not headers.get("accept-language"):
        flags.append("no_accept_language")

    # Sec-CH-UA (Client Hints) solo lo envían Chrome/Edge reales. Si existe, debe ser
    # coherente con el User-Agent; si el UA dice Chrome pero el hint dice "HeadlessChrome",
    # o el hint existe y el UA no es de Chromium, hay incoherencia.
    ch = (headers.get("sec-ch-ua") or "").lower()
    if ch:
        if "headless" in ch and "headless" not in ua_l:
            flags.append("sec_ch_ua_mismatch")
        elif "chrom" not in ua_l and "edg" not in ua_l:
            flags.append("sec_ch_ua_mismatch")
    return flags


def _write(record: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with _lock, LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_event(request: Request, event: str, **data) -> None:
    """Agrega un evento de seguridad (puntaje, desafío, rechazo) al log."""
    if not config.should_log():
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "type": "event",
        "event": event,
        "ip": client_ip(request),
        "sid": request.cookies.get("sid"),
        "path": request.url.path,
        **data,
    }
    _write(record)
    consola.info("[seguridad] %s %s", event, json.dumps(data, ensure_ascii=False))
    # Pendiente de guardar en Postgres: el middleware lo inserta al terminar la petición
    pendientes = getattr(request.state, "security_events", None)
    if pendientes is not None:
        pendientes.append(record)


CAMPOS_FIJOS = {"ts", "type", "event", "ip", "sid", "path", "score", "action", "flags"}


def _guardar_en_bd(eventos: list[dict], method: str, status: int, user_agent: str | None) -> None:
    filas = [(e.get("ts"), e["event"], method, e.get("path"), status, e.get("ip"), e.get("sid"), user_agent,
              e.get("score") if isinstance(e.get("score"), int) else None,
              e.get("action"), Jsonb(e.get("flags") or []),
              Jsonb({k: v for k, v in e.items() if k not in CAMPOS_FIJOS}))
             for e in eventos]
    with get_pg() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO security_events (ts, event, method, path, status, ip, sid, user_agent, "
                    "score, action, flags, data) VALUES (coalesce(%s::timestamptz, now()), "
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", filas)
            if random.random() < 0.01:        # de vez en cuando se purga lo que tenga más de 90 días
                conn.execute("DELETE FROM security_events WHERE ts < now() - interval '90 days'")


class AuditMiddleware(BaseHTTPMiddleware):
    """Registra cada petición a /api/* con sus huellas. Etiqueta, no bloquea."""

    async def dispatch(self, request: Request, call_next):
        # request.state vive en el scope: las rutas y los otros middlewares agregan aquí
        request.state.security_events = []
        response = await call_next(request)
        if config.should_log() and request.url.path.startswith("/api/"):
            flags = header_flags(request.headers)
            _write({
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "type": "request",
                "ip": client_ip(request),
                "sid": request.cookies.get("sid"),
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "status": response.status_code,
                "user_agent": request.headers.get("user-agent"),
                "accept_language": request.headers.get("accept-language"),
                "sec_ch_ua": request.headers.get("sec-ch-ua"),
                "automation_suspected": bool(flags),
                "flags": flags,
            })
            eventos = request.state.security_events
            if response.status_code == 429:   # límite superado: siempre tiene valor de auditoría
                eventos.append({"event": "rate_limited", "ip": client_ip(request),
                                "sid": request.cookies.get("sid"), "path": request.url.path,
                                "flags": flags, "query": str(request.url.query)})
            if eventos and config.SECURITY_EVENTS_DB:
                try:
                    await run_in_threadpool(_guardar_en_bd, eventos, request.method,
                                            response.status_code, request.headers.get("user-agent"))
                except Exception as e:  # noqa: BLE001 - la bitácora nunca debe tumbar la respuesta
                    consola.warning("[seguridad] no se pudo guardar en security_events: %s", e)
        return response
