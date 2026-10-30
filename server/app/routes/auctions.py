"""
Mercado de subastas:
    GET  /api/auctions               subastas activas (público, paginado)
    GET  /api/auctions/{id}          detalle + historial de pujas (público; el frontend lo consulta cada ~5 s)
    POST /api/auctions               subastar una carta propia
    POST /api/auctions/{id}/bid      pujar
    POST /api/auctions/{id}/buyout   compra inmediata
    POST /api/auctions/{id}/cancel   cancelar (solo el vendedor y sin pujas)

Ver es público (como el catálogo); actuar exige sesión. La lógica de dinero vive
en app/market.py.

Defensas:
  * Las lecturas usan RATE_LIMIT_POLL (holgado para el polling de 5 s).
  * Las acciones usan RATE_LIMIT_BIDS: frena bots de sniping que pujan en ráfaga.
  * Cada puja deja un evento `bid` en logs/access.jsonl con las huellas del cliente:
    permite detectar, por ejemplo, pujas idénticas a pocos milisegundos del cierre.
"""
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app import config
from app.auth import require_player, user_from_request
from app.market import (MarketError, cancel_auction, create_auction, place_bid, replenish_house,
                        serialize_auctions, settle_expired)
from app.pg import get_pg
from app.security.audit import header_flags, log_event
from app.security.ratelimit import key_ip, limiter

router = APIRouter()

SORTS = {
    "ending": "ends_at ASC",
    "newest": "created_at DESC",
    "price_asc": "COALESCE(current_bid, start_price) ASC",
    "price_desc": "COALESCE(current_bid, start_price) DESC",
}


class CreateAuctionIn(BaseModel):
    owned_card_id: int
    duration: str = Field(max_length=4)
    start_price: int = Field(ge=1, le=1_000_000)
    buyout_price: int | None = Field(default=None, ge=2, le=10_000_000)


class BidIn(BaseModel):
    amount: int = Field(ge=1, le=10_000_000)


@router.get("/auctions")
@limiter.limit(config.RATE_LIMIT_POLL)
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def list_auctions(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=48),
    source: Literal["all", "house", "users"] = "all",
    sort: Literal["ending", "newest", "price_asc", "price_desc"] = "ending",
):
    with get_pg() as conn:
        settle_expired(conn)
        replenish_house(conn)
        me = user_from_request(conn, request)
        where = "status = 'active'"
        if source == "house":
            where += " AND seller_id IS NULL"
        elif source == "users":
            where += " AND seller_id IS NOT NULL"
        total = conn.execute(f"SELECT count(*) AS n FROM auctions WHERE {where}").fetchone()["n"]
        # `where` y el ORDER BY solo contienen textos fijos del código (SORTS), nunca entrada del usuario
        rows = conn.execute(
            f"SELECT * FROM auctions WHERE {where} ORDER BY {SORTS[sort]}, id LIMIT %s OFFSET %s",
            (limit, (page - 1) * limit),
        ).fetchall()
        items = serialize_auctions(conn, rows, me["id"] if me else None)
    return {"items": items, "page": page, "limit": limit, "total": total,
            "pages": max(1, -(-total // limit))}


@router.get("/auctions/{auction_id}")
@limiter.limit(config.RATE_LIMIT_POLL)
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def get_auction(request: Request, auction_id: int):
    with get_pg() as conn:
        settle_expired(conn)
        me = user_from_request(conn, request)
        row = conn.execute("SELECT *, now() AS server_now FROM auctions WHERE id = %s",
                           (auction_id,)).fetchone()
        if row is None:
            raise MarketError(404, "Subasta no encontrada.")
        auction = serialize_auctions(conn, [row], me["id"] if me else None)[0]
        auction["bids"] = [
            {"user": b["username"], "amount": b["amount"], "at": b["created_at"].isoformat()}
            for b in conn.execute(
                "SELECT b.amount, b.created_at, u.username FROM bids b JOIN users u ON u.id = b.user_id "
                "WHERE b.auction_id = %s ORDER BY b.created_at DESC LIMIT 20", (auction_id,))
        ]
        auction["server_now"] = row["server_now"].isoformat()   # para sincronizar la cuenta regresiva
        auction["my_points"] = me["points"] if me else None
    return auction


@router.post("/auctions", status_code=201)
@limiter.limit(config.RATE_LIMIT_BIDS)
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def new_auction(request: Request, payload: CreateAuctionIn):
    with get_pg() as conn:
        user = require_player(conn, request)
        auction_id = create_auction(conn, user["id"], payload.owned_card_id, payload.duration,
                                    payload.start_price, payload.buyout_price)
    log_event(request, "auction_created", auction_id=auction_id, user=user["username"],
              duration=payload.duration, start_price=payload.start_price)
    return {"ok": True, "id": auction_id}


def _bid(request: Request, auction_id: int, amount: int | None) -> dict:
    with get_pg() as conn:
        user = require_player(conn, request)
        settle_expired(conn)
        if amount is None:   # compra inmediata
            row = conn.execute("SELECT buyout_price FROM auctions WHERE id = %s", (auction_id,)).fetchone()
            if row is None or row["buyout_price"] is None:
                raise MarketError(400, "Esta subasta no tiene compra inmediata.")
            amount = row["buyout_price"]
        try:
            result = place_bid(conn, auction_id, user["id"], amount)
        except MarketError as e:
            log_event(request, "bid", auction_id=auction_id, user=user["username"], amount=amount,
                      result="rechazada", reason=e.message, flags=header_flags(request.headers))
            raise
    log_event(request, "bid", auction_id=auction_id, user=user["username"], amount=result["amount"],
              result="buyout" if result["buyout"] else "aceptada", extended=result["extended"],
              flags=header_flags(request.headers))
    return result


@router.post("/auctions/{auction_id}/bid")
@limiter.limit(config.RATE_LIMIT_BIDS)
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def bid(request: Request, auction_id: int, payload: BidIn):
    return _bid(request, auction_id, payload.amount)


@router.post("/auctions/{auction_id}/buyout")
@limiter.limit(config.RATE_LIMIT_BIDS)
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def buyout(request: Request, auction_id: int):
    return _bid(request, auction_id, None)


@router.post("/auctions/{auction_id}/cancel")
@limiter.limit(config.RATE_LIMIT_BIDS)
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def cancel(request: Request, auction_id: int):
    with get_pg() as conn:
        user = require_player(conn, request)
        cancel_auction(conn, auction_id, user["id"])
    log_event(request, "auction_cancelled", auction_id=auction_id, user=user["username"])
    return {"ok": True}
