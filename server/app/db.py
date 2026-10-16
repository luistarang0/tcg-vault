"""
Acceso a la base de datos SQLite del catálogo (server/data/cards.db).

Se abre una conexión por petición: SQLite es un archivo local, abrirla es barato
y así se evitan problemas de concurrencia entre hilos de uvicorn.
"""
import sqlite3
from pathlib import Path

# Ruta absoluta a server/data/cards.db, sin importar desde dónde se ejecute uvicorn
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cards.db"

# Esquema único compartido por el importador real y el generador de demo
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cards (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT,          -- Pokémon / Entrenador / Energía
  hp INTEGER,
  types TEXT,             -- guardado como "|Fuego|Agua|" para filtrar con LIKE
  rarity TEXT,
  set_id TEXT,
  set_name TEXT,
  local_id TEXT,
  dex_id INTEGER,
  generation INTEGER,
  illustrator TEXT,
  image TEXT,
  attacks_json TEXT       -- lista de ataques en JSON
);
CREATE INDEX IF NOT EXISTS idx_cards_set ON cards(set_id);
CREATE INDEX IF NOT EXISTS idx_cards_gen ON cards(generation);
CREATE INDEX IF NOT EXISTS idx_cards_rarity ON cards(rarity);
"""


def get_conn() -> sqlite3.Connection:
    """Abre una conexión cuyas filas se comportan como diccionarios (row['name'])."""
    if not DB_PATH.exists():
        raise RuntimeError(
            f"No existe {DB_PATH}. Ejecuten primero: python scripts/import_tcgdex.py"
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
