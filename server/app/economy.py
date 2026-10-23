"""
Reglas de la economía: puntos, precios por rareza, sobres aleatorios y
consulta de cartas del catálogo (SQLite) por id.

Todos los números del juego viven aquí para ajustarlos en un solo lugar.
"""
from __future__ import annotations

import math
import random

from app.db import get_conn

STARTING_POINTS = 1000       # saldo al registrarse
DAILY_BONUS = 100            # una vez por día (fecha UTC) al iniciar sesión o abrir el sitio
STARTER_PACK_SIZE = 5        # cartas del sobre inicial

MIN_INCREMENT_PCT = 0.05     # cada puja supera la actual en 5 %...
MIN_INCREMENT_ABS = 10       # ...o en 10 puntos, lo que sea mayor
ANTI_SNIPE_SECONDS = 120     # una puja en los últimos 2 min deja 2 min por delante

HOUSE_ACTIVE_TARGET = 8      # subastas de la casa activas que se mantienen
HOUSE_DURATIONS_MIN = [15, 60, 180, 360]   # la casa elige al azar entre estas

# Duraciones que puede elegir un usuario (clave -> minutos)
USER_DURATIONS = {"5m": 5, "1h": 60, "6h": 360, "24h": 1440, "3d": 4320}

# Precio al que la casa compra al instante, por rareza (nombres tal cual en cards.db)
HOUSE_BUY_PRICE = {
    "Común": 10, "Uncommon": 20, "Rara": 50, "Holo Rara": 100, "Rara Doble": 150,
    "Holo Rara V": 150, "Ultra Rara": 250, "Holo Rara VMAX": 300, "Rara Secreta": 500,
}
DEFAULT_BUY_PRICE = 10
HOUSE_START_MULTIPLIER = 2   # la casa sale al doble de lo que paga: vender y recomprar no es negocio

# Niveles de rareza para los sorteos y su peso relativo
TIERS = {
    "comun": ["Común"],
    "poco_comun": ["Uncommon"],
    "rara": ["Rara"],
    "holo": ["Holo Rara", "Rara Doble", "Holo Rara V"],
    "top": ["Ultra Rara", "Holo Rara VMAX", "Rara Secreta"],
}
PACK_WEIGHTS = {"comun": 55, "poco_comun": 25, "rara": 12, "holo": 6, "top": 2}
HOUSE_WEIGHTS = {"comun": 25, "poco_comun": 25, "rara": 25, "holo": 17, "top": 8}

_ids_by_tier: dict[str, list[str]] | None = None


def _load_tiers() -> dict[str, list[str]]:
    """Ids del catálogo agrupados por nivel (835 filas: se cargan una vez por instancia)."""
    global _ids_by_tier
    if _ids_by_tier is None:
        rarity_to_tier = {r: t for t, rs in TIERS.items() for r in rs}
        grouped: dict[str, list[str]] = {t: [] for t in TIERS}
        conn = get_conn()
        try:
            for row in conn.execute("SELECT id, rarity FROM cards"):
                grouped[rarity_to_tier.get(row["rarity"], "comun")].append(row["id"])
        finally:
            conn.close()
        _ids_by_tier = {t: ids for t, ids in grouped.items() if ids}
    return _ids_by_tier


def random_cards(n: int, weights: dict[str, int]) -> list[str]:
    """Sortea n ids del catálogo: primero el nivel según su peso, luego una carta del nivel."""
    tiers = _load_tiers()
    names = [t for t in weights if t in tiers]
    picks = random.choices(names, weights=[weights[t] for t in names], k=n)
    return [random.choice(tiers[t]) for t in picks]


def house_buy_price(rarity: str | None) -> int:
    return HOUSE_BUY_PRICE.get(rarity or "", DEFAULT_BUY_PRICE)


def min_next_bid(start_price: int, current_bid: int | None) -> int:
    """Puja mínima aceptada: el precio de salida o la actual + incremento."""
    if current_bid is None:
        return start_price
    return current_bid + max(MIN_INCREMENT_ABS, math.ceil(current_bid * MIN_INCREMENT_PCT))


def cards_by_ids(ids) -> dict[str, dict]:
    """Datos de catálogo para mostrar (nombre, imagen, rareza...) indexados por id."""
    ids = list({i for i in ids if i})
    if not ids:
        return {}
    conn = get_conn()
    try:
        marks = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id, name, category, hp, types, rarity, set_name, local_id, image "
            f"FROM cards WHERE id IN ({marks})", ids,
        ).fetchall()
    finally:
        conn.close()
    out = {}
    for r in rows:
        card = dict(r)
        card["types_list"] = [t for t in (card.pop("types") or "").split("|") if t]
        card["house_price"] = house_buy_price(card["rarity"])
        out[card["id"]] = card
    return out


def public_rules() -> dict:
    """Reglas que el frontend muestra o necesita (duraciones, incrementos...)."""
    return {
        "starting_points": STARTING_POINTS,
        "daily_bonus": DAILY_BONUS,
        "min_increment_pct": MIN_INCREMENT_PCT,
        "min_increment_abs": MIN_INCREMENT_ABS,
        "anti_snipe_seconds": ANTI_SNIPE_SECONDS,
        "durations": list(USER_DURATIONS),
        "house_buy_price": HOUSE_BUY_PRICE,
    }
