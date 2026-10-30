"""
Panel de seguridad del administrador (solo lectura):
    GET /api/admin/filtros       valores disponibles para los <select>
    GET /api/admin/resumen       indicadores, serie en el tiempo, top de IPs y señales
    GET /api/admin/eventos       eventos paginados
    GET /api/admin/eventos.csv   exportación de los eventos filtrados

Todas exigen la sesión del ÚNICO administrador (require_admin: 401 sin sesión,
403 a cualquier otra cuenta) y leen la tabla security_events.

Filtros comunes (query string):
    desde, hasta   ISO 8601 con zona (el frontend manda la hora local convertida)
    evento         register_attempt, login_result, csrf_invalid, rate_limited…
    accion         allow / log / throttle / challenge
    status         código exacto (429) o familia (4xx, 5xx)
    ip             IP exacta
    q              texto libre en ruta, User-Agent, sid y datos del evento
    tz             zona horaria IANA para agrupar la serie (por defecto America/Mexico_City)

Regla de seguridad: los valores del usuario viajan SIEMPRE como parámetros (%s);
lo único que se arma como texto es la estructura del WHERE con piezas fijas.
"""
import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app import config
from app.auth import require_admin
from app.pg import get_pg
from app.security.ratelimit import key_ip, limiter

router = APIRouter(prefix="/admin")

# Cada evento se clasifica en una de estas series para la gráfica (orden fijo de color)
SERIE_SQL = """CASE
  WHEN event = 'rate_limited' THEN 'limite'
  WHEN event = 'csrf_invalid' THEN 'csrf'
  WHEN action IN ('throttle', 'challenge') OR (event = 'turnstile_verify' AND data->>'success' = 'false') THEN 'riesgo'
  ELSE 'otros' END"""
TZ_RE = re.compile(r"^[A-Za-z]+(?:/[A-Za-z0-9_+-]+){0,2}$|^UTC$")


def _fecha(valor: str | None, defecto: datetime) -> datetime:
    if not valor:
        return defecto
    try:
        f = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Fecha inválida: {valor}")
    return f if f.tzinfo else f.replace(tzinfo=timezone.utc)


def filtros(desde, hasta, evento, accion, status, ip, q) -> tuple[str, list, datetime, datetime]:
    """WHERE parametrizado + rango efectivo. Por defecto, las últimas 24 horas."""
    ahora = datetime.now(timezone.utc)
    f_hasta = _fecha(hasta, ahora)
    f_desde = _fecha(desde, f_hasta - timedelta(hours=24))
    if f_desde >= f_hasta:
        raise HTTPException(status_code=422, detail="'desde' debe ser anterior a 'hasta'.")
    where, params = ["ts >= %s", "ts < %s"], [f_desde, f_hasta]
    if evento:
        where.append("event = %s")
        params.append(evento)
    if accion:
        where.append("action = %s")
        params.append(accion)
    if status:
        if re.fullmatch(r"[1-5]xx", status):
            where.append("status BETWEEN %s AND %s")
            params += [int(status[0]) * 100, int(status[0]) * 100 + 99]
        elif status.isdigit():
            where.append("status = %s")
            params.append(int(status))
        else:
            raise HTTPException(status_code=422, detail="status debe ser un código (429) o una familia (4xx).")
    if ip:
        where.append("ip = %s")
        params.append(ip)
    if q:
        where.append("(path ILIKE %s OR user_agent ILIKE %s OR sid ILIKE %s OR data::text ILIKE %s)")
        params += [f"%{q}%"] * 4
    return " AND ".join(where), params, f_desde, f_hasta


def _fila(r: dict) -> dict:
    return {"id": r["id"], "ts": r["ts"].isoformat(), "event": r["event"], "method": r["method"],
            "path": r["path"], "status": r["status"], "ip": r["ip"], "sid": r["sid"],
            "user_agent": r["user_agent"], "score": r["score"], "action": r["action"],
            "flags": r["flags"] or [], "data": r["data"] or {}}


@router.get("/filtros")
@limiter.limit(config.RATE_LIMIT_POLL)
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def opciones(request: Request):
    with get_pg() as conn:
        require_admin(conn, request)
        col = lambda c: [r["v"] for r in conn.execute(  # noqa: E731
            f"SELECT DISTINCT {c} AS v FROM security_events WHERE {c} IS NOT NULL "
            f"AND ts > now() - interval '90 days' ORDER BY 1")]
        primero = conn.execute("SELECT min(ts) AS t FROM security_events").fetchone()["t"]
        return {"eventos": col("event"), "acciones": col("action"), "status": col("status"),
                "primer_evento": primero.isoformat() if primero else None,
                "guardado_activo": config.SECURITY_EVENTS_DB}


@router.get("/resumen")
@limiter.limit(config.RATE_LIMIT_POLL)
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def resumen(request: Request, desde: str | None = None, hasta: str | None = None, evento: str | None = None,
            accion: str | None = None, status: str | None = None, ip: str | None = None,
            q: str | None = Query(None, max_length=80), tz: str = "America/Mexico_City"):
    where, params, f_desde, f_hasta = filtros(desde, hasta, evento, accion, status, ip, q)
    if not TZ_RE.match(tz):
        tz = "America/Mexico_City"
    horas = (f_hasta - f_desde).total_seconds() / 3600
    paso = "hour" if horas <= 48 else "day" if horas <= 24 * 92 else "week"   # texto fijo, no del usuario

    with get_pg() as conn:
        require_admin(conn, request)
        kpi = conn.execute(f"""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE event = 'rate_limited') AS limite,
                   count(*) FILTER (WHERE action = 'challenge') AS desafios,
                   count(*) FILTER (WHERE action = 'throttle') AS frenados,
                   count(*) FILTER (WHERE event = 'csrf_invalid') AS csrf,
                   count(*) FILTER (WHERE event = 'login_result' AND data->>'result' IN ('bad', 'locked')) AS login_fallidos,
                   count(*) FILTER (WHERE event = 'login_result' AND data->>'result' = 'locked') AS cuentas_bloqueadas,
                   count(*) FILTER (WHERE event = 'turnstile_verify' AND data->>'success' = 'false') AS turnstile_rechazados,
                   count(DISTINCT ip) AS ips, count(DISTINCT sid) AS sesiones
            FROM security_events WHERE {where}""", params).fetchone()

        serie = conn.execute(f"""
            SELECT date_trunc('{paso}', ts AT TIME ZONE %s) AS bucket, {SERIE_SQL} AS serie, count(*) AS n
            FROM security_events WHERE {where} GROUP BY 1, 2 ORDER BY 1""", [tz] + params).fetchall()

        top_ips = conn.execute(f"""
            SELECT ip, count(*) AS n, count(*) FILTER (WHERE status >= 400) AS rechazados,
                   max(ts) AS ultimo, count(DISTINCT sid) AS sesiones
            FROM security_events WHERE {where} AND ip IS NOT NULL
            GROUP BY ip ORDER BY n DESC LIMIT 10""", params).fetchall()

        top_flags = conn.execute(f"""
            SELECT f AS senal, count(*) AS n
            FROM security_events, jsonb_array_elements_text(coalesce(flags, '[]'::jsonb)) AS f
            WHERE {where} GROUP BY f ORDER BY n DESC LIMIT 10""", params).fetchall()

        por_evento = conn.execute(f"""
            SELECT event, count(*) AS n FROM security_events WHERE {where}
            GROUP BY event ORDER BY n DESC""", params).fetchall()

    # Serie con todos los intervalos (también los vacíos), en hora local de tz
    cubetas: dict[str, dict] = {}
    for r in serie:
        clave = r["bucket"].isoformat()
        cubetas.setdefault(clave, {"limite": 0, "riesgo": 0, "csrf": 0, "otros": 0})[r["serie"]] = r["n"]
    return {
        "rango": {"desde": f_desde.isoformat(), "hasta": f_hasta.isoformat(), "paso": paso, "tz": tz},
        "kpi": kpi,
        "serie": [{"bucket": k, **v} for k, v in sorted(cubetas.items())],
        "top_ips": [{**r, "ultimo": r["ultimo"].isoformat()} for r in top_ips],
        "top_senales": top_flags,
        "por_evento": por_evento,
    }


@router.get("/eventos")
@limiter.limit(config.RATE_LIMIT_POLL)
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def eventos(request: Request, desde: str | None = None, hasta: str | None = None, evento: str | None = None,
            accion: str | None = None, status: str | None = None, ip: str | None = None,
            q: str | None = Query(None, max_length=80),
            page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    where, params, _, _ = filtros(desde, hasta, evento, accion, status, ip, q)
    with get_pg() as conn:
        require_admin(conn, request)
        total = conn.execute(f"SELECT count(*) AS n FROM security_events WHERE {where}", params).fetchone()["n"]
        filas = conn.execute(
            f"SELECT * FROM security_events WHERE {where} ORDER BY ts DESC, id DESC LIMIT %s OFFSET %s",
            params + [limit, (page - 1) * limit]).fetchall()
    return {"items": [_fila(r) for r in filas], "page": page, "limit": limit, "total": total,
            "pages": max(1, -(-total // limit))}


@router.get("/eventos.csv")
@limiter.limit("10/minute")
def exportar(request: Request, desde: str | None = None, hasta: str | None = None, evento: str | None = None,
             accion: str | None = None, status: str | None = None, ip: str | None = None,
             q: str | None = Query(None, max_length=80)):
    where, params, f_desde, f_hasta = filtros(desde, hasta, evento, accion, status, ip, q)
    with get_pg() as conn:
        require_admin(conn, request)
        filas = conn.execute(f"SELECT * FROM security_events WHERE {where} ORDER BY ts DESC LIMIT 10000",
                             params).fetchall()
    salida = io.StringIO()
    salida.write("﻿")                       # BOM: Excel abre bien los acentos
    w = csv.writer(salida)
    w.writerow(["ts", "event", "method", "path", "status", "ip", "sid", "score", "action", "flags", "user_agent", "data"])
    for r in filas:
        f = _fila(r)
        w.writerow([f["ts"], f["event"], f["method"], f["path"], f["status"], f["ip"], f["sid"], f["score"],
                    f["action"], "|".join(f["flags"]), f["user_agent"], json.dumps(f["data"], ensure_ascii=False)])
    nombre = f"seguridad_{f_desde:%Y%m%d%H%M}_{f_hasta:%Y%m%d%H%M}.csv"
    return StreamingResponse(iter([salida.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
