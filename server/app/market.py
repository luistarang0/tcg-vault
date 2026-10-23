"""
Lógica del mercado: pujas, cierre de subastas, subastas de la casa y movimientos
de puntos. Las rutas (routes/auctions.py, routes/collection.py) solo validan la
entrada y llaman a estas funciones.

Dos ideas clave para que funcione en Vercel (sin procesos vivos ni cron frecuente):

* Cierre perezoso: nadie "despierta" cuando vence una subasta. Cada vez que
  alguien consulta el mercado, una subasta o su perfil, settle_expired() liquida
  las vencidas. El resultado es el mismo que si se cerraran a la hora exacta.
* Reposición perezosa: al listar el mercado, si hay menos de HOUSE_ACTIVE_TARGET
  subastas de la casa activas, se crean las que falten.

Concurrencia: todo cambio de dinero ocurre en una transacción que bloquea primero
la subasta y luego a los usuarios en orden de id (SELECT ... FOR UPDATE). Dos pujas
simultáneas se forman en fila: la segunda ve el resultado de la primera.

Puntos congelados: al pujar se descuentan del saldo disponible; si alguien te
supera se devuelven en el acto. Lo congelado de un usuario es la suma de las
subastas activas en las que va ganando (no hace falta una columna aparte).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from psycopg import errors as pg_errors

from app import economy as eco


class MarketError(Exception):
    """Error de negocio que la ruta convierte en respuesta HTTP."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Puntos -------------------------------------------------------------------

def add_points(conn, user_id: int, delta: int, reason: str, auction_id: int | None = None) -> None:
    """Único camino para mover saldo: actualiza al usuario y deja la fila en el libro."""
    conn.execute("UPDATE users SET points = points + %s WHERE id = %s", (delta, user_id))
    conn.execute("INSERT INTO ledger (user_id, delta, reason, auction_id) VALUES (%s, %s, %s, %s)",
                 (user_id, delta, reason, auction_id))


def grant_daily_bonus(conn, user_id: int) -> int:
    """Da el bono si hoy (UTC) aún no lo recibió. Devuelve los puntos otorgados."""
    with conn.transaction():
        row = conn.execute(
            "UPDATE users SET last_bonus = (now() AT TIME ZONE 'UTC')::date "
            "WHERE id = %s AND (last_bonus IS NULL OR last_bonus < (now() AT TIME ZONE 'UTC')::date) "
            "RETURNING id", (user_id,),
        ).fetchone()
        if row is None:
            return 0
        add_points(conn, user_id, eco.DAILY_BONUS, "bono_diario")
    return eco.DAILY_BONUS


def give_starter_pack(conn, user_id: int) -> list[str]:
    """Reparte el sobre inicial. Se llama dentro de la transacción del registro."""
    ids = eco.random_cards(eco.STARTER_PACK_SIZE, eco.PACK_WEIGHTS)
    for card_id in ids:
        conn.execute("INSERT INTO owned_cards (card_id, owner_id, source) VALUES (%s, %s, 'sobre_inicial')",
                     (card_id, user_id))
    return ids


# --- Cierre de subastas ---------------------------------------------------------

def _settle(conn, a: dict) -> str:
    """Liquida una subasta YA bloqueada. Devuelve el estado final."""
    if a["leader_id"] is not None:
        # Los puntos del ganador ya estaban descontados (congelados) desde su puja
        conn.execute("UPDATE owned_cards SET owner_id = %s, source = 'subasta', acquired_at = now() "
                     "WHERE id = %s", (a["leader_id"], a["owned_card_id"]))
        if a["seller_id"] is not None:
            add_points(conn, a["seller_id"], a["current_bid"], "venta_subasta", a["id"])
        status = "sold"
    else:
        # Sin pujas: la copia nunca cambió de dueño, así que sigue siendo del vendedor
        status = "expired"
    conn.execute("UPDATE auctions SET status = %s, closed_at = now(), ends_at = LEAST(ends_at, now()) "
                 "WHERE id = %s", (status, a["id"]))
    return status


def settle_expired(conn, limit: int = 50) -> int:
    """Liquida las subastas vencidas. SKIP LOCKED: si otra petición ya cierra una, se salta."""
    # Camino rápido (una sola consulta): casi siempre no hay nada vencido
    if not conn.execute("SELECT EXISTS (SELECT 1 FROM auctions WHERE status = 'active' "
                        "AND ends_at <= now()) AS due").fetchone()["due"]:
        return 0
    with conn.transaction():
        rows = conn.execute(
            "SELECT * FROM auctions WHERE status = 'active' AND ends_at <= now() "
            "ORDER BY ends_at LIMIT %s FOR UPDATE SKIP LOCKED", (limit,),
        ).fetchall()
        for a in rows:
            _settle(conn, a)
    return len(rows)


# --- Subastas de la casa -----------------------------------------------------

def replenish_house(conn) -> int:
    """Crea subastas de la casa hasta llegar a HOUSE_ACTIVE_TARGET activas."""
    count_sql = "SELECT count(*) AS n FROM auctions WHERE seller_id IS NULL AND status = 'active'"
    # Camino rápido sin transacción ni candado: lo normal es que no falte ninguna
    if conn.execute(count_sql).fetchone()["n"] >= eco.HOUSE_ACTIVE_TARGET:
        return 0
    with conn.transaction():
        # try_lock: si otra petición ya está reponiendo, esta no espera ni duplica
        if not conn.execute("SELECT pg_try_advisory_xact_lock(7312) AS ok").fetchone()["ok"]:
            return 0
        missing = eco.HOUSE_ACTIVE_TARGET - conn.execute(count_sql).fetchone()["n"]
        if missing <= 0:
            return 0
        ids = eco.random_cards(missing, eco.HOUSE_WEIGHTS)
        cards = eco.cards_by_ids(ids)
        for card_id in ids:
            price = cards[card_id]["house_price"] * eco.HOUSE_START_MULTIPLIER
            minutes = random.choice(eco.HOUSE_DURATIONS_MIN)
            owned = conn.execute("INSERT INTO owned_cards (card_id, owner_id, source) "
                                 "VALUES (%s, NULL, 'casa') RETURNING id", (card_id,)).fetchone()
            # La casa ofrece compra inmediata al quíntuple de lo que paga por la carta
            conn.execute(
                "INSERT INTO auctions (owned_card_id, card_id, seller_id, start_price, buyout_price, ends_at) "
                "VALUES (%s, %s, NULL, %s, %s, now() + make_interval(mins => %s))",
                (owned["id"], card_id, price, price * 5 // 2, minutes),
            )
    return missing


# --- Acciones del usuario -------------------------------------------------------

def place_bid(conn, auction_id: int, user_id: int, amount: int) -> dict:
    """Puja (o compra inmediata si alcanza buyout_price). Lanza MarketError si no procede."""
    with conn.transaction():
        a = conn.execute("SELECT * FROM auctions WHERE id = %s FOR UPDATE", (auction_id,)).fetchone()
        if a is None:
            raise MarketError(404, "Subasta no encontrada.")
        if a["status"] != "active" or a["ends_at"] <= _now():
            raise MarketError(409, "Esta subasta ya terminó.")
        if a["seller_id"] == user_id:
            raise MarketError(403, "No puedes pujar en tu propia subasta.")
        if a["leader_id"] == user_id:
            raise MarketError(409, "Ya vas ganando esta subasta.")

        is_buyout = a["buyout_price"] is not None and amount >= a["buyout_price"]
        if is_buyout:
            amount = a["buyout_price"]     # nunca se cobra más que la compra inmediata
        minimo = eco.min_next_bid(a["start_price"], a["current_bid"])
        if not is_buyout and amount < minimo:
            raise MarketError(400, f"La puja mínima es {minimo} puntos.")

        # Bloquea a los usuarios implicados en orden de id (evita interbloqueos)
        ids = sorted({user_id} | ({a["leader_id"]} if a["leader_id"] else set()))
        users = {u["id"]: u for u in conn.execute(
            "SELECT id, points FROM users WHERE id = ANY(%s) ORDER BY id FOR UPDATE", (ids,))}
        if users[user_id]["points"] < amount:
            raise MarketError(400, f"Saldo insuficiente: tienes {users[user_id]['points']} puntos disponibles.")

        add_points(conn, user_id, -amount, "puja_congelada", auction_id)
        if a["leader_id"]:
            add_points(conn, a["leader_id"], a["current_bid"], "puja_superada", auction_id)

        # Anti-sniping: si quedaban menos de 2 min, se extiende para que haya respuesta
        ends_at = max(a["ends_at"], _now() + timedelta(seconds=eco.ANTI_SNIPE_SECONDS))
        extended = ends_at > a["ends_at"]
        conn.execute("UPDATE auctions SET current_bid = %s, leader_id = %s, bid_count = bid_count + 1, "
                     "ends_at = %s WHERE id = %s", (amount, user_id, ends_at, auction_id))
        conn.execute("INSERT INTO bids (auction_id, user_id, amount) VALUES (%s, %s, %s)",
                     (auction_id, user_id, amount))

        if is_buyout:
            a.update(current_bid=amount, leader_id=user_id)
            _settle(conn, a)
    return {"ok": True, "amount": amount, "buyout": is_buyout, "extended": extended and not is_buyout}


def create_auction(conn, user_id: int, owned_card_id: int, duration: str,
                   start_price: int, buyout_price: int | None) -> int:
    if duration not in eco.USER_DURATIONS:
        raise MarketError(400, "Duración no válida.")
    if buyout_price is not None and buyout_price <= start_price:
        raise MarketError(400, "La compra inmediata debe ser mayor que el precio de salida.")
    try:
        with conn.transaction():
            owned = conn.execute("SELECT id, card_id FROM owned_cards WHERE id = %s AND owner_id = %s "
                                 "FOR UPDATE", (owned_card_id, user_id)).fetchone()
            if owned is None:
                raise MarketError(404, "Esa carta no está en tu colección.")
            row = conn.execute(
                "INSERT INTO auctions (owned_card_id, card_id, seller_id, start_price, buyout_price, ends_at) "
                "VALUES (%s, %s, %s, %s, %s, now() + make_interval(mins => %s)) RETURNING id",
                (owned["id"], owned["card_id"], user_id, start_price, buyout_price,
                 eco.USER_DURATIONS[duration]),
            ).fetchone()
    except pg_errors.UniqueViolation:
        raise MarketError(409, "Esa carta ya está en una subasta activa.")
    return row["id"]


def cancel_auction(conn, auction_id: int, user_id: int) -> None:
    with conn.transaction():
        a = conn.execute("SELECT * FROM auctions WHERE id = %s FOR UPDATE", (auction_id,)).fetchone()
        if a is None or a["seller_id"] != user_id:
            raise MarketError(404, "Subasta no encontrada.")
        if a["status"] != "active":
            raise MarketError(409, "Esta subasta ya terminó.")
        if a["bid_count"] > 0:
            raise MarketError(409, "No se puede cancelar: ya tiene pujas.")
        conn.execute("UPDATE auctions SET status = 'cancelled', closed_at = now() WHERE id = %s",
                     (auction_id,))


def sell_to_house(conn, owned_card_id: int, user_id: int) -> int:
    """Vende una copia a la casa al precio fijo de su rareza. Devuelve los puntos recibidos."""
    with conn.transaction():
        owned = conn.execute("SELECT id, card_id FROM owned_cards WHERE id = %s AND owner_id = %s "
                             "FOR UPDATE", (owned_card_id, user_id)).fetchone()
        if owned is None:
            raise MarketError(404, "Esa carta no está en tu colección.")
        busy = conn.execute("SELECT 1 FROM auctions WHERE owned_card_id = %s AND status = 'active'",
                            (owned_card_id,)).fetchone()
        if busy:
            raise MarketError(409, "Esa carta está en una subasta activa.")
        price = eco.cards_by_ids([owned["card_id"]]).get(owned["card_id"], {}).get(
            "house_price", eco.DEFAULT_BUY_PRICE)
        conn.execute("UPDATE owned_cards SET owner_id = NULL, source = 'vendida_casa' WHERE id = %s",
                     (owned_card_id,))
        add_points(conn, user_id, price, "venta_casa")
    return price


# --- Lectura -------------------------------------------------------------------

def frozen_points(conn, user_id: int) -> int:
    return conn.execute("SELECT COALESCE(sum(current_bid), 0) AS n FROM auctions "
                        "WHERE status = 'active' AND leader_id = %s", (user_id,)).fetchone()["n"]


def serialize_auctions(conn, rows: list[dict], me: int | None = None) -> list[dict]:
    """Agrega datos de la carta y nombres de usuario a filas de `auctions`."""
    user_ids = {r["seller_id"] for r in rows} | {r["leader_id"] for r in rows}
    user_ids.discard(None)
    names = {}
    if user_ids:
        names = {u["id"]: u["username"] for u in conn.execute(
            "SELECT id, username FROM users WHERE id = ANY(%s)", (list(user_ids),))}
    cards = eco.cards_by_ids(r["card_id"] for r in rows)
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "card": cards.get(r["card_id"], {"id": r["card_id"], "name": r["card_id"]}),
            "owned_card_id": r["owned_card_id"],
            "seller": names.get(r["seller_id"]),          # None = la casa
            "is_house": r["seller_id"] is None,
            "start_price": r["start_price"],
            "buyout_price": r["buyout_price"],
            "current_bid": r["current_bid"],
            "leader": names.get(r["leader_id"]),
            "bid_count": r["bid_count"],
            "min_next_bid": eco.min_next_bid(r["start_price"], r["current_bid"]),
            "status": r["status"],
            "created_at": r["created_at"].isoformat(),
            "ends_at": r["ends_at"].isoformat(),
            "closed_at": r["closed_at"].isoformat() if r["closed_at"] else None,
            "is_mine": me is not None and r["seller_id"] == me,
            "i_lead": me is not None and r["leader_id"] == me,
        })
    return out
