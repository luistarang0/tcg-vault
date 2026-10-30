"""
Rutas del catálogo:
    GET /api/cards          lista paginada con filtros
    GET /api/cards/{id}     detalle de una carta
    GET /api/filters        valores válidos para los filtros

Regla de seguridad: los valores que manda el usuario SIEMPRE viajan como
parámetros (?) de sqlite3, nunca concatenados en el texto SQL (evita inyección SQL).
Lo único que se arma con f-string es la cláusula WHERE con textos fijos del código.

Defensa 1: cada ruta declara su límite con decorador (RATE_LIMIT_CATALOG por
IP + sesión y RATE_LIMIT_IP solo por IP). Se hace explícito porque, con las
versiones recientes de FastAPI, SlowAPIMiddleware no encuentra las rutas que
vienen de un APIRouter incluido y el límite por defecto no se aplicaría.
"""
import json

from fastapi import APIRouter, HTTPException, Query, Request


from app import config
from app.db import get_conn
from app.security.ratelimit import key_ip, limiter

router = APIRouter()


def row_to_card(row) -> dict:
    """Convierte una fila de SQLite en el JSON que consume el frontend."""
    card = dict(row)
    card["attacks"] = json.loads(card.pop("attacks_json") or "[]")
    # "|Fuego|Agua|" -> ["Fuego", "Agua"] (más cómodo en el frontend)
    card["types_list"] = [t for t in (card.get("types") or "").split("|") if t]
    return card


@router.get("/cards")
@limiter.limit(config.RATE_LIMIT_CATALOG)                          # IP + sesión
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip) # solo IP
def list_cards(
    request: Request,
    page: int = Query(1, ge=1, description="Página (desde 1)"),
    limit: int = Query(20, ge=1, le=50, description="Cartas por página (máx. 50)"),
    card_type: str | None = Query(None, alias="type", description="Tipo, ej. Fuego"),
    set_id: str | None = Query(None, description="Id de colección"),
    generation: int | None = Query(None, ge=1, le=9),
    rarity: str | None = None,
    category: str | None = Query(None, description="Pokémon / Entrenador / Energía"),
    q: str | None = Query(None, max_length=50, description="Búsqueda por nombre"),
):
    # Se construye el WHERE dinámicamente según los filtros presentes
    where, params = [], []
    if card_type:
        where.append("types LIKE ?")
        params.append(f"%|{card_type}|%")
    if set_id:
        where.append("set_id = ?")
        params.append(set_id)
    if generation:
        where.append("generation = ?")
        params.append(generation)
    if rarity:
        where.append("rarity = ?")
        params.append(rarity)
    if category:
        where.append("category = ?")
        params.append(category)
    if q:
        where.append("name LIKE ?")
        params.append(f"%{q}%")
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_conn()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM cards {sql_where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM cards {sql_where} "
            f"ORDER BY set_id, CAST(local_id AS INTEGER), local_id "
            f"LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
    finally:
        conn.close()

    return {
        "items": [row_to_card(r) for r in rows],
        "page": page,
        "limit": limit,
        "total": total,
        "pages": -(-total // limit),   # división hacia arriba: ceil(total / limit)
    }


@router.get("/cards/{card_id}")
@limiter.limit(config.RATE_LIMIT_CATALOG)                          # IP + sesión
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip) # solo IP
def get_card(request: Request, card_id: str):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Carta no encontrada")
    return row_to_card(row)


@router.get("/filters")
@limiter.limit(config.RATE_LIMIT_CATALOG)                          # IP + sesión
@limiter.limit(config.RATE_LIMIT_IP, key_func=key_ip) # solo IP
def get_filters(request: Request):
    """Valores distintos para poblar los <select> del frontend."""
    conn = get_conn()
    try:
        # Los tipos vienen como "|Fuego|Agua|": se separan en Python
        types = set()
        for (t,) in conn.execute("SELECT DISTINCT types FROM cards WHERE types IS NOT NULL"):
            types.update(x for x in t.split("|") if x)
        sets = [
            {"id": r["set_id"], "name": r["set_name"], "count": r["n"]}
            for r in conn.execute(
                "SELECT set_id, set_name, COUNT(*) AS n FROM cards "
                "GROUP BY set_id, set_name ORDER BY set_id"
            )
        ]
        generations = [r[0] for r in conn.execute(
            "SELECT DISTINCT generation FROM cards WHERE generation IS NOT NULL ORDER BY generation"
        )]
        rarities = [r[0] for r in conn.execute(
            "SELECT DISTINCT rarity FROM cards WHERE rarity IS NOT NULL ORDER BY rarity"
        )]
        categories = [r[0] for r in conn.execute(
            "SELECT DISTINCT category FROM cards WHERE category IS NOT NULL ORDER BY category"
        )]
    finally:
        conn.close()
    return {
        "types": sorted(types),
        "sets": sets,
        "generations": generations,
        "rarities": rarities,
        "categories": categories,
    }
