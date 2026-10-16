"""
Generador de un catálogo de DEMOSTRACIÓN (datos ficticios) para pruebas sin red.

NO reemplaza al importador real. Úsenlo solo si todavía no han ejecutado
scripts/import_tcgdex.py y necesitan levantar el sitio para probar la API,
la paginación o el rate limiting. Todas las cartas llevan set_id "demo-*".

    python scripts/seed_demo.py           # crea data/cards.db con 900 cartas ficticias
    python scripts/seed_demo.py --force   # sobrescribe una base existente
"""
import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import DB_PATH, SCHEMA_SQL  # noqa: E402

TYPES = ["Planta", "Fuego", "Agua", "Rayo", "Psíquico", "Lucha",
         "Oscuridad", "Metal", "Dragón", "Incoloro"]
RARITIES = ["Común", "Poco común", "Rara", "Rara Holo"]
SETS = [(f"demo-{g}", f"Colección Demo Gen {g}", g) for g in range(1, 10)]
PER_SET = 100   # 9 colecciones x 100 = 900 cartas (~45 páginas de 20)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if DB_PATH.exists() and not args.force:
        sys.exit(f"{DB_PATH} ya existe. Usa --force para sobrescribir.")

    rng = random.Random(42)                       # semilla fija -> datos reproducibles
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_SQL)

    for set_id, set_name, gen in SETS:
        for n in range(1, PER_SET + 1):
            # 80 % Pokémon, 15 % Entrenador, 5 % Energía (para campos ausentes)
            roll = rng.random()
            if roll < 0.80:
                category, t = "Pokémon", rng.choice(TYPES)
                types, hp = f"|{t}|", rng.choice(range(40, 330, 10))
                attacks = [{"name": f"Ataque {t} {k}", "cost": [t] * k,
                            "damage": str(10 * k * rng.randint(1, 5)), "effect": None}
                           for k in range(1, rng.randint(2, 3))]
                generation, dex = gen, None
            elif roll < 0.95:
                category, types, hp, attacks, generation, dex = "Entrenador", None, None, [], None, None
            else:
                category, types, hp, attacks, generation, dex = "Energía", None, None, [], None, None
            conn.execute(
                "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"{set_id}-{n}", f"Demo {category} {gen}-{n:03d}", category, hp, types,
                 rng.choice(RARITIES), set_id, set_name, str(n), dex, generation,
                 "Ilustrador Demo", None, json.dumps(attacks, ensure_ascii=False)),
            )
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    print(f"Catálogo DEMO creado: {total} cartas ficticias en {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()
