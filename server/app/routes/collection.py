"""
Colección y actividad del usuario con sesión:
    GET  /api/me/cards              cartas en posesión (copias individuales)
    POST /api/me/cards/{id}/sell    vender una copia a la casa al precio de su rareza
    GET  /api/me/auctions           mis subastas como vendedor y en las que he pujado
"""
from fastapi import APIRouter, Request
from slowapi.util import get_remote_address

from app import config, economy as eco
from app.auth import require_player
from app.market import sell_to_house, serialize_auctions, settle_expired
from app.pg import get_pg
from app.security.audit import log_event
from app.security.ratelimit import limiter

router = APIRouter()


def owned_cards_of(conn, user_id: int) -> list[dict]:
    """Copias de un usuario con datos de catálogo y, si aplica, su subasta activa."""
    rows = conn.execute(
        "SELECT o.id, o.card_id, o.source, o.acquired_at, a.id AS auction_id "
        "FROM owned_cards o LEFT JOIN auctions a ON a.owned_card_id = o.id AND a.status = 'active' "
        "WHERE o.owner_id = %s ORDER BY o.acquired_at DESC, o.id DESC LIMIT 1000", (user_id,),
    ).fetchall()
    cards = eco.cards_by_ids(r["card_id"] for r in rows)
    return [{
        "owned_card_id": r["id"],
        "source": r["source"],
        "acquired_at": r["acquired_at"].isoformat(),
        "auction_id": r["auction_id"],
        "card": cards.get(r["card_id"], {"id": r["card_id"], "name": r["card_id"]}),
    } for r in rows]


@router.get("/me/cards")
@limiter.limit(config.RATE_LIMIT_CATALOG)
@limiter.limit(config.RATE_LIMIT_IP, key_func=get_remote_address)
def my_cards(request: Request):
    with get_pg() as conn:
        user = require_player(conn, request)
        settle_expired(conn)          # una subasta ganada que ya venció aparece aquí
        return {"items": owned_cards_of(conn, user["id"])}


@router.post("/me/cards/{owned_card_id}/sell")
@limiter.limit(config.RATE_LIMIT_BIDS)
@limiter.limit(config.RATE_LIMIT_IP, key_func=get_remote_address)
def sell_card(request: Request, owned_card_id: int):
    with get_pg() as conn:
        user = require_player(conn, request)
        price = sell_to_house(conn, owned_card_id, user["id"])
    log_event(request, "sold_to_house", user=user["username"], owned_card_id=owned_card_id, price=price)
    return {"ok": True, "points": price}


@router.get("/me/auctions")
@limiter.limit(config.RATE_LIMIT_POLL)
@limiter.limit(config.RATE_LIMIT_IP, key_func=get_remote_address)
def my_auctions(request: Request):
    with get_pg() as conn:
        user = require_player(conn, request)
        settle_expired(conn)
        selling = conn.execute(
            "SELECT * FROM auctions WHERE seller_id = %s ORDER BY (status = 'active') DESC, "
            "created_at DESC LIMIT 50", (user["id"],)).fetchall()
        bidding = conn.execute(
            "SELECT * FROM auctions WHERE id IN (SELECT DISTINCT auction_id FROM bids WHERE user_id = %s) "
            "ORDER BY (status = 'active') DESC, ends_at DESC LIMIT 50", (user["id"],)).fetchall()
        return {
            "selling": serialize_auctions(conn, selling, user["id"]),
            "bidding": serialize_auctions(conn, bidding, user["id"]),
        }
