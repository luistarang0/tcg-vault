"""
Perfil público:
    GET /api/users/{username}   colección y subastas activas de un coleccionista

No expone correo ni saldo: solo lo que cualquiera podría ver en el mercado.
"""
from fastapi import APIRouter, HTTPException, Request

from app import config
from app.market import serialize_auctions, settle_expired
from app.pg import get_pg
from app.routes.collection import owned_cards_of
from app.security.ratelimit import key_ip, limiter

router = APIRouter()


@router.get("/users/{username}")
@limiter.limit(config.RATE_LIMIT_CATALOG)
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip)
def public_profile(request: Request, username: str):
    with get_pg() as conn:
        settle_expired(conn)
        # El administrador no es coleccionista: su perfil no existe para el público
        user = conn.execute("SELECT id, username, created_at FROM users "
                            "WHERE lower(username) = lower(%s) AND NOT is_admin", (username[:40],)).fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="Coleccionista no encontrado.")
        auctions = conn.execute("SELECT * FROM auctions WHERE seller_id = %s AND status = 'active' "
                                "ORDER BY ends_at", (user["id"],)).fetchall()
        cards = owned_cards_of(conn, user["id"])
        for c in cards:
            c.pop("source", None)
        return {
            "username": user["username"],
            "member_since": user["created_at"].isoformat(),
            "cards": cards,
            "auctions": serialize_auctions(conn, auctions),
        }
