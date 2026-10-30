"""
Acceso a la base de datos Postgres (Neon) del mercado: usuarios, sesiones,
cartas en posesión, subastas, pujas y movimientos de puntos.

El catálogo sigue en SQLite (app/db.py): es de solo lectura y viaja dentro de la
función de Vercel. Todo lo que se ESCRIBE vive aquí, porque en Vercel el disco
es de solo lectura (solo /tmp admite escritura y se borra entre ejecuciones).

* DATABASE_URL: en local, la rama `dev` de Neon (server/.env); en Vercel, la
  variable que crea la integración con Neon (rama `main`).
* Se abre una conexión por petición contra el endpoint con pooling de Neon
  (`-pooler` en el host): en serverless no hay un proceso vivo que mantenga un pool.
* El esquema se crea solo la primera vez que una instancia abre conexión
  (CREATE ... IF NOT EXISTS), así un despliegue nuevo no necesita pasos extra.

Regla de seguridad: igual que en SQLite, los valores del usuario SIEMPRE viajan
como parámetros (%s) de psycopg, nunca concatenados en el texto SQL.
"""
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from app import config

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  id            SERIAL PRIMARY KEY,
  username      TEXT NOT NULL,
  email         TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  points        INTEGER NOT NULL DEFAULT 0 CHECK (points >= 0),  -- saldo disponible
  last_bonus    DATE,                                             -- último bono diario
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username ON users (lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users (lower(email));

-- Se guarda el SHA-256 del token, no el token: si la tabla se filtra, las
-- cookies siguen sin poder falsificarse.
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL
);

-- Cada fila es UNA copia física de una carta del catálogo (puede haber duplicados).
-- owner_id NULL = la copia pertenece a la casa (subastas automáticas).
CREATE TABLE IF NOT EXISTS owned_cards (
  id          BIGSERIAL PRIMARY KEY,
  card_id     TEXT NOT NULL,                 -- id del catálogo SQLite
  owner_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
  source      TEXT NOT NULL,                 -- sobre_inicial / subasta / casa
  acquired_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_owned_owner ON owned_cards (owner_id);

CREATE TABLE IF NOT EXISTS auctions (
  id            BIGSERIAL PRIMARY KEY,
  owned_card_id BIGINT NOT NULL REFERENCES owned_cards(id) ON DELETE CASCADE,
  card_id       TEXT NOT NULL,               -- copia del catálogo para listar sin JOIN
  seller_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,  -- NULL = la casa
  start_price   INTEGER NOT NULL CHECK (start_price > 0),
  buyout_price  INTEGER CHECK (buyout_price IS NULL OR buyout_price > start_price),
  current_bid   INTEGER,
  leader_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  bid_count     INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'active',  -- active / sold / expired / cancelled
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  ends_at       TIMESTAMPTZ NOT NULL,
  closed_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_auctions_active ON auctions (status, ends_at);
-- Una copia no puede estar en dos subastas activas a la vez
CREATE UNIQUE INDEX IF NOT EXISTS ux_auctions_card_active
  ON auctions (owned_card_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS bids (
  id         BIGSERIAL PRIMARY KEY,
  auction_id BIGINT NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount     INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_bids_auction ON bids (auction_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_bids_user ON bids (user_id);

-- Libro de movimientos: cada cambio de saldo deja una fila. No se muestra en la
-- interfaz, pero permite auditar que la suma de movimientos = saldo.
CREATE TABLE IF NOT EXISTS ledger (
  id         BIGSERIAL PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  delta      INTEGER NOT NULL,
  reason     TEXT NOT NULL,
  auction_id BIGINT REFERENCES auctions(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Intentos de login: el límite por CUENTA vive aquí y no en memoria, porque en
-- Vercel cada instancia tiene su propia memoria y un atacante las repartiría.
CREATE TABLE IF NOT EXISTS login_attempts (
  id         BIGSERIAL PRIMARY KEY,
  username   TEXT NOT NULL,
  ip         TEXT,
  ok         BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_login_attempts ON login_attempts (lower(username), created_at);

-- Bitácora de seguridad persistente (Defensa 2). En Vercel el archivo access.jsonl
-- vive en /tmp y se pierde con cada instancia; aquí quedan los eventos de las
-- defensas (puntajes, desafíos, CSRF, pujas, logins) y cada respuesta 429.
-- Las peticiones normales NO se guardan: solo lo que tiene valor de auditoría.
CREATE TABLE IF NOT EXISTS security_events (
  id         BIGSERIAL PRIMARY KEY,
  ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
  event      TEXT NOT NULL,          -- register_attempt, login_result, csrf_invalid, rate_limited…
  method     TEXT,
  path       TEXT,
  status     INTEGER,                -- código HTTP con el que terminó la petición
  ip         TEXT,
  sid        TEXT,                   -- cookie anónima del limitador (no identifica a la persona)
  user_agent TEXT,
  score      INTEGER,                -- puntaje de riesgo, si el evento lo trae
  action     TEXT,                   -- allow / log / throttle / challenge
  flags      JSONB,                  -- señales (honeypot, webdriver, headless_ua…)
  data       JSONB                   -- el resto de campos del evento
);
CREATE INDEX IF NOT EXISTS ix_security_events_ts ON security_events (ts DESC);
CREATE INDEX IF NOT EXISTS ix_security_events_event ON security_events (event, ts DESC);

-- Rol de administrador: solo puede revisar la bitácora de seguridad (/admin).
-- El índice único sobre una expresión constante permite UNA sola fila con
-- is_admin = true: Postgres rechaza un segundo administrador aunque se intente
-- directamente en la base. Se crea con server/scripts/crear_admin.py.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_un_admin ON users ((true)) WHERE is_admin;
"""

_schema_ready = False


def _ensure_schema(conn: psycopg.Connection) -> None:
    global _schema_ready
    if _schema_ready:
        return
    # El candado evita que dos instancias que arrancan a la vez choquen al crear tablas
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(7311)")
        conn.execute(SCHEMA_SQL)
    _schema_ready = True


@contextmanager
def get_pg():
    """
    Conexión con filas como diccionarios. Uso:
        with get_pg() as conn:
            with conn.transaction():
                ...
    Fuera de un bloque transaction() cada sentencia se confirma sola (autocommit).
    """
    if not config.DATABASE_URL:
        raise RuntimeError("Falta DATABASE_URL (ver server/.env.example)")
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row,
                           autocommit=True, connect_timeout=10)
    try:
        _ensure_schema(conn)
        yield conn
    finally:
        conn.close()
