"""
Limpieza con Pandas y almacenamiento idempotente en SQLite.

Limpieza:
  * Texto: Unicode NFC y espacios colapsados.
  * Números: "131,946.90" -> 131946.9, aplicando la unidad del encabezado (Thousands, ...).
  * Duplicados: se conservan una vez por (pais_id, indicador_id).
  * Faltantes: nunca se inventa un valor. La fila sin año o valor pasa a la tabla `faltantes`.
  * Agregados: "World" o "Euro area" se marcan con es_agregado = 1 para no mezclarlos con países.

Por qué no se duplica al volver a ejecutar:
  La llave primaria es (pais_id, indicador_id, anio) e `INSERT ... ON CONFLICT DO UPDATE`
  convierte una fila repetida en una actualización. No se borra la base en ningún momento.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

MULTIPLICADORES = {"thousands": 1e3, "millions": 1e6, "billions": 1e9, "trillions": 1e12}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS paises (
  pais_id TEXT PRIMARY KEY, pais TEXT NOT NULL,
  es_agregado INTEGER NOT NULL CHECK (es_agregado IN (0, 1))   -- 1 = región o grupo, no país
);
CREATE TABLE IF NOT EXISTS indicadores (
  indicador_id TEXT PRIMARY KEY, indicador TEXT NOT NULL, unidad_pagina TEXT
);
CREATE TABLE IF NOT EXISTS observaciones (
  pais_id TEXT NOT NULL REFERENCES paises(pais_id),
  indicador_id TEXT NOT NULL REFERENCES indicadores(indicador_id),
  anio INTEGER NOT NULL,
  valor REAL NOT NULL,
  primera_vez TEXT NOT NULL,
  ultima_vez TEXT NOT NULL,
  PRIMARY KEY (pais_id, indicador_id, anio)
);
CREATE TABLE IF NOT EXISTS faltantes (
  pais_id TEXT NOT NULL REFERENCES paises(pais_id),
  indicador_id TEXT NOT NULL REFERENCES indicadores(indicador_id),
  ultima_vez TEXT NOT NULL,
  PRIMARY KEY (pais_id, indicador_id)
);
CREATE TABLE IF NOT EXISTS corridas (
  id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, origen TEXT NOT NULL,
  filas_crudas INTEGER, duplicados INTEGER, sin_pais INTEGER, faltantes INTEGER,
  insertadas INTEGER, actualizadas INTEGER, sin_cambio INTEGER, total_observaciones INTEGER
);
"""


def limpiar_texto(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    limpio = re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(valor))).strip()
    return limpio or None


def numero(texto) -> float | None:
    limpio = re.sub(r"[^\d.\-]", "", limpiar_texto(texto) or "")
    try:
        return float(limpio)
    except ValueError:
        return None


def limpiar(crudos: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """De los crudos por indicador a dos tablas limpias: observaciones y faltantes."""
    registros = [{**fila, "indicador_id": bloque["indicador"], "unidad_pagina": bloque["unidad_texto"]}
                 for bloque in crudos for fila in bloque["filas"]]
    df = pd.DataFrame(registros, columns=["pais", "pais_id", "es_agregado", "anio_texto", "valor_texto",
                                          "indicador_id", "unidad_pagina"])
    conteo = {"filas_crudas": len(df)}

    df["pais"] = df["pais"].map(limpiar_texto)
    df["pais_id"] = df["pais_id"].map(limpiar_texto)

    antes = len(df)
    df = df.dropna(subset=["pais", "pais_id"])         # sin país no hay llave: no se puede guardar
    conteo["sin_pais"] = antes - len(df)

    antes = len(df)
    df = df.drop_duplicates(subset=["pais_id", "indicador_id"], keep="first")
    conteo["duplicados"] = antes - len(df)

    factor = df["unidad_pagina"].fillna("").str.lower().map(MULTIPLICADORES).fillna(1)
    df = df.assign(anio=pd.to_numeric(df["anio_texto"], errors="coerce").astype("Int64"),
                   valor=df["valor_texto"].map(numero).astype("Float64") * factor,
                   es_agregado=df["es_agregado"].fillna(False).astype(int))

    incompletas = df["anio"].isna() | df["valor"].isna()
    conteo["faltantes"] = int(incompletas.sum())
    columnas = ["pais_id", "pais", "es_agregado", "indicador_id", "unidad_pagina", "anio", "valor"]
    return df.loc[~incompletas, columnas].reset_index(drop=True), df.loc[incompletas, columnas].reset_index(drop=True), conteo


def guardar(obs: pd.DataFrame, falt: pd.DataFrame, conteo: dict, db: Path, nombres: dict[str, str], origen: str) -> dict:
    """Inserta o actualiza dentro de una transacción. Si algo falla, no queda nada a medias."""
    ahora = datetime.now().isoformat(timespec="seconds")
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(ESQUEMA)
        with con:
            todas = pd.concat([obs, falt])
            con.executemany("INSERT INTO paises VALUES (?, ?, ?) ON CONFLICT(pais_id) DO UPDATE SET "
                            "pais = excluded.pais, es_agregado = excluded.es_agregado",
                            [(r.pais_id, r.pais, int(r.es_agregado))
                             for r in todas.drop_duplicates("pais_id").itertuples(index=False)])
            unidades = todas.groupby("indicador_id")["unidad_pagina"].first().to_dict()
            con.executemany("INSERT INTO indicadores VALUES (?, ?, ?) ON CONFLICT(indicador_id) DO UPDATE SET "
                            "indicador = excluded.indicador, unidad_pagina = excluded.unidad_pagina",
                            [(i, nombres.get(i, i), None if pd.isna(u) else u) for i, u in unidades.items()])

            existentes = {(p, i, a): v for p, i, a, v in con.execute(
                "SELECT pais_id, indicador_id, anio, valor FROM observaciones")}
            insertadas = actualizadas = sin_cambio = 0
            for fila in obs.itertuples(index=False):
                llave = (fila.pais_id, fila.indicador_id, int(fila.anio))
                valor = float(fila.valor)
                if llave not in existentes:
                    insertadas += 1
                elif existentes[llave] != valor:
                    actualizadas += 1
                else:
                    sin_cambio += 1
                con.execute("INSERT INTO observaciones VALUES (?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT(pais_id, indicador_id, anio) DO UPDATE SET "
                            "valor = excluded.valor, ultima_vez = excluded.ultima_vez",
                            (*llave, valor, ahora, ahora))

            con.executemany("INSERT INTO faltantes VALUES (?, ?, ?) ON CONFLICT(pais_id, indicador_id) "
                            "DO UPDATE SET ultima_vez = excluded.ultima_vez",
                            [(r.pais_id, r.indicador_id, ahora) for r in falt.itertuples(index=False)])
            # Si un país ya publicó el dato, deja de contar como faltante
            con.executemany("DELETE FROM faltantes WHERE pais_id = ? AND indicador_id = ?",
                            [(r.pais_id, r.indicador_id) for r in obs.itertuples(index=False)])

            total = con.execute("SELECT count(*) FROM observaciones").fetchone()[0]
            resumen = {**conteo, "insertadas": insertadas, "actualizadas": actualizadas, "sin_cambio": sin_cambio,
                       "total_observaciones": total}
            con.execute("INSERT INTO corridas (fecha, origen, filas_crudas, duplicados, sin_pais, faltantes, insertadas, "
                        "actualizadas, sin_cambio, total_observaciones) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (ahora, origen, conteo["filas_crudas"], conteo["duplicados"], conteo["sin_pais"],
                         conteo["faltantes"], insertadas, actualizadas, sin_cambio, total))
    finally:
        con.close()
    return resumen


def exportar_csv(db: Path, carpeta: Path) -> None:
    """Los CSV salen siempre de la base: no acumulan filas entre corridas."""
    carpeta.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    try:
        pd.read_sql("""SELECT o.pais_id, p.pais, p.es_agregado, o.indicador_id, i.indicador, o.anio, o.valor,
                              o.primera_vez, o.ultima_vez
                       FROM observaciones o JOIN paises p USING (pais_id) JOIN indicadores i USING (indicador_id)
                       ORDER BY o.indicador_id, o.pais_id, o.anio""", con).to_csv(
            carpeta / "observaciones.csv", index=False, encoding="utf-8-sig")
        pd.read_sql("""SELECT f.pais_id, p.pais, p.es_agregado, f.indicador_id, i.indicador, f.ultima_vez
                       FROM faltantes f JOIN paises p USING (pais_id) JOIN indicadores i USING (indicador_id)
                       ORDER BY f.indicador_id, f.pais_id""", con).to_csv(
            carpeta / "faltantes.csv", index=False, encoding="utf-8-sig")
    finally:
        con.close()
