"""
Consulta la bitácora de seguridad guardada en Postgres (tabla security_events).

Por defecto usa la DATABASE_URL de server/.env (rama dev de Neon). Para ver los
eventos de PRODUCCIÓN (lo que pasó en Vercel), pasa la cadena de la rama main
con --url, o usa el SQL Editor de la consola de Neon con las consultas del README.

Uso (desde server/, con el .venv activado):
    python scripts/ver_eventos.py                        # últimos 30 eventos
    python scripts/ver_eventos.py --evento rate_limited  # solo un tipo
    python scripts/ver_eventos.py --horas 24 --resumen   # conteo por evento y acción
    python scripts/ver_eventos.py --url "postgresql://…main…"
"""
import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.getenv("DATABASE_URL"), help="cadena de conexión (por defecto la de .env)")
    ap.add_argument("--limite", type=int, default=30)
    ap.add_argument("--evento", help="filtra por tipo: register_attempt, login_result, csrf_invalid, bid, rate_limited…")
    ap.add_argument("--horas", type=float, default=168, help="ventana hacia atrás (por defecto 7 días)")
    ap.add_argument("--resumen", action="store_true", help="conteo por evento y acción en lugar del detalle")
    a = ap.parse_args()
    if not a.url:
        sys.exit("Falta DATABASE_URL (en server/.env o con --url)")

    where, params = ["ts > now() - make_interval(secs => %s)"], [a.horas * 3600]
    if a.evento:
        where.append("event = %s")
        params.append(a.evento)
    w = " AND ".join(where)

    with psycopg.connect(a.url, row_factory=dict_row, connect_timeout=15) as conn:
        if a.resumen:
            filas = conn.execute(
                f"SELECT event, coalesce(action, '-') AS action, count(*) AS n, "
                f"count(DISTINCT ip) AS ips, max(ts) AS ultimo FROM security_events WHERE {w} "
                f"GROUP BY 1, 2 ORDER BY n DESC", params).fetchall()
            print(f"{'evento':<18} {'acción':<10} {'total':>6} {'IPs':>5}  último")
            for f in filas:
                print(f"{f['event']:<18} {f['action']:<10} {f['n']:>6} {f['ips']:>5}  {f['ultimo']:%Y-%m-%d %H:%M:%S}")
            return
        filas = conn.execute(
            f"SELECT ts, event, method, path, status, ip, score, action, flags, data FROM security_events "
            f"WHERE {w} ORDER BY ts DESC, id DESC LIMIT %s", params + [a.limite]).fetchall()
    for f in reversed(filas):
        extra = {k: v for k, v in (f["data"] or {}).items() if k in ("result", "reason", "user", "amount", "success", "errors")}
        print(f"{f['ts']:%m-%d %H:%M:%S}  {f['event']:<16} {f['status'] or '':<4} {f['method'] or '':<5} "
              f"{(f['path'] or '')[:28]:<28} ip={f['ip']:<15} "
              f"{'score=' + str(f['score']) if f['score'] is not None else '':<10} {f['action'] or '':<9} "
              f"{','.join(f['flags'] or [])} {json.dumps(extra, ensure_ascii=False) if extra else ''}")
    print(f"\n{len(filas)} eventos (últimas {a.horas:g} h)")


if __name__ == "__main__":
    main()
