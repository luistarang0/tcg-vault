"""
Importador del catálogo desde la API pública de TCGdex (en español).

Se ejecuta UNA SOLA VEZ (desde server/):
    python scripts/import_tcgdex.py              # importa las colecciones de SET_IDS
    python scripts/import_tcgdex.py --list-sets  # solo muestra las colecciones disponibles

Reglas de cortesía hacia TCGdex:
  * pausa de 0.3 s después de cada petición;
  * User-Agent propio que identifica al proyecto;
  * reintentos con espera creciente si el servidor responde 429/5xx.

Al terminar, una persona sube server/data/cards.db al repo para que todo el equipo
use el mismo catálogo.
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import requests

# Permite importar app.db al ejecutar el script desde server/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import DB_PATH, SCHEMA_SQL  # noqa: E402

BASE = "https://api.tcgdex.net/v2/es"
HEADERS = {"User-Agent": "tcg-vault-school-project/0.1"}
PAUSE_SECONDS = 0.3
MAX_PER_SET = 120

# Colecciones candidatas de distintas eras. Las que no existan en español se
# omiten automáticamente (se valida contra /sets antes de importar).
# Verifiquen con --list-sets y ajusten hasta tener ~900 cartas.
SET_IDS = [
    "base1",   # Base (Gen 1)
    "neo1",    # Neo Genesis (Gen 2)
    "ex1",     # Rubí y Zafiro (Gen 3)
    "dp1",     # Diamante y Perla (Gen 4)
    "bw1",     # Negro y Blanco (Gen 5)
    "xy1",     # XY (Gen 6)
    "sm1",     # Sol y Luna (Gen 7)
    "swsh1",   # Espada y Escudo (Gen 8)
    "swsh3",   # Oscuridad Incandescente (Gen 8)
    "sv01",    # Escarlata y Púrpura (Gen 9)
    "sv06",    # Máscaras del Crepúsculo (Gen 9)
]

# (desde, hasta, generación) según el número de Pokédex nacional
RANGES = [(1, 151, 1), (152, 251, 2), (252, 386, 3), (387, 493, 4), (494, 649, 5),
          (650, 721, 6), (722, 809, 7), (810, 905, 8), (906, 1025, 9)]


def generation(dex):
    """Devuelve la generación (1-9) para un número de Pokédex, o None."""
    if dex is None:
        return None
    for lo, hi, g in RANGES:
        if lo <= dex <= hi:
            return g
    return None


def get(path, retries=3):
    """GET a TCGdex con pausa cortés y reintentos con backoff exponencial."""
    url = f"{BASE}{path}"
    for attempt in range(retries):
        r = requests.get(url, headers=HEADERS, timeout=15)
        time.sleep(PAUSE_SECONDS)                       # pausa cortés siempre
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None                                 # carta/colección no existe en "es"
        if r.status_code in (429, 500, 502, 503, 504):
            wait = int(r.headers.get("Retry-After", 2 ** (attempt + 1)))
            print(f"  [{r.status_code}] esperando {wait}s antes de reintentar {path}")
            time.sleep(wait)
            continue
        r.raise_for_status()
    return None


def card_to_row(c):
    """Convierte la respuesta de /cards/{id} en una tupla para INSERT.

    Usa .get() en todo: las Energías y Entrenadores no tienen hp, types ni attacks.
    """
    dex = (c.get("dexId") or [None])[0]
    types = c.get("types") or []
    image = c.get("image")
    attacks = [
        {
            "name": a.get("name"),
            "cost": a.get("cost") or [],
            "damage": a.get("damage"),
            "effect": a.get("effect"),
        }
        for a in (c.get("attacks") or [])
    ]
    return (
        c["id"],
        c.get("name") or c["id"],
        c.get("category"),
        c.get("hp"),
        f"|{'|'.join(types)}|" if types else None,     # "|Fuego|" para filtrar con LIKE
        c.get("rarity"),
        (c.get("set") or {}).get("id"),
        (c.get("set") or {}).get("name"),
        c.get("localId"),
        dex,
        generation(dex),
        c.get("illustrator"),
        f"{image}/high.webp" if image else None,         # TCGdex entrega la base de la URL
        json.dumps(attacks, ensure_ascii=False),
    )


INSERT_SQL = """
INSERT OR REPLACE INTO cards
(id, name, category, hp, types, rarity, set_id, set_name, local_id,
 dex_id, generation, illustrator, image, attacks_json)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def list_sets():
    """Imprime id, nombre y número de cartas de cada colección en español."""
    for s in get("/sets") or []:
        total = (s.get("cardCount") or {}).get("total", "?")
        print(f"{s['id']:<12} {total:>5}  {s.get('name')}")


def main():
    parser = argparse.ArgumentParser(description="Importa cartas de TCGdex a SQLite")
    parser.add_argument("--list-sets", action="store_true", help="solo listar colecciones")
    args = parser.parse_args()

    if args.list_sets:
        list_sets()
        return

    # 1) Validar qué colecciones existen en español
    available = {s["id"] for s in (get("/sets") or [])}
    chosen = [s for s in SET_IDS if s in available]
    skipped = [s for s in SET_IDS if s not in available]
    if skipped:
        print(f"Omitidas (no disponibles en español): {', '.join(skipped)}")
    if not chosen:
        sys.exit("Ninguna colección válida. Revisen SET_IDS con --list-sets.")

    # 2) Crear tabla
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_SQL)

    # 3) Recorrer colecciones y cartas
    imported = 0
    for set_id in chosen:
        s = get(f"/sets/{set_id}")
        if not s:
            continue
        briefs = (s.get("cards") or [])[:MAX_PER_SET]
        print(f"{set_id}: {len(briefs)} cartas ({s.get('name')})")
        for i, brief in enumerate(briefs, 1):
            c = get(f"/cards/{brief['id']}")
            if not c:
                continue
            conn.execute(INSERT_SQL, card_to_row(c))
            imported += 1
            if i % 20 == 0:
                conn.commit()                              # guarda avance parcial
                print(f"  {i}/{len(briefs)}")
        conn.commit()

    # 4) Resumen para el checkpoint del paso 2
    total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    print(f"\nImportadas en esta ejecución: {imported}. Total en la base: {total}")
    for gen, n in conn.execute(
        "SELECT generation, COUNT(*) FROM cards GROUP BY generation ORDER BY generation"
    ):
        print(f"  Generación {gen}: {n}")
    conn.close()


if __name__ == "__main__":
    main()
