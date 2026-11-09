"""
Reto de la Actividad 3: volver a ejecutar sin duplicar.

Trabaja en una base aparte (datos/prueba_reejecucion.sqlite), que se crea vacía para
partir de cero. No toca datos/world_bank.sqlite.

  Corrida 1  extracción real con Selenium; la base está vacía, todo se inserta.
  Corrida 2  extracción real otra vez; no debe crecer la base.
  Corrida 3  prueba forzada: los crudos de la corrida 2 repetidos dos veces y con
             filas sin país agregadas. La limpieza debe descartarlas.

Salida: resultados/reto_reejecucion.md

Uso:  python actividad_datos_abiertos/05_reto_reejecucion.py [--headless]
"""
from __future__ import annotations

import copy
import importlib
import sqlite3

import pandas as pd

import config
from comun import Bitacora, args_headless, guardar_csv, tabla_md

flujo = importlib.import_module("04_flujo_sitio_a_bd")

DB = config.DATOS / "prueba_reejecucion.sqlite"
CSV = config.DATOS / "prueba_reejecucion_csv"
COLUMNAS = ["filas_crudas", "duplicados", "sin_pais", "faltantes", "insertadas", "actualizadas", "sin_cambio",
            "total_observaciones"]


def filas_csv() -> int:
    return len(pd.read_csv(CSV / "observaciones.csv"))


def llaves_repetidas() -> int:
    con = sqlite3.connect(DB)
    try:
        return con.execute("SELECT count(*) FROM (SELECT 1 FROM observaciones "
                           "GROUP BY pais_id, indicador_id, anio HAVING count(*) > 1)").fetchone()[0]
    finally:
        con.close()


def main() -> None:
    b = Bitacora("05_reto")
    if DB.exists():
        DB.unlink()                                   # solo la base de esta prueba
    resultados = []

    for numero in (1, 2):
        print(f"\n--- Corrida {numero}: extracción real con Selenium")
        crudos = flujo.extraer(args_headless(), b)
        if not crudos:
            raise SystemExit("La extracción no devolvió datos: revisa resultados/bitacora.jsonl")
        resumen = flujo.procesar(crudos, DB, CSV, f"corrida {numero}")
        resultados.append({"corrida": f"{numero}: Selenium", **resumen, "filas_csv": filas_csv()})

    print("\n--- Corrida 3: mismos crudos repetidos y filas sin país")
    forzados = copy.deepcopy(crudos) + copy.deepcopy(crudos)
    forzados[0]["filas"].append({"pais": None, "pais_id": None, "anio_texto": "2025", "valor_texto": "1.0"})
    resumen = flujo.procesar(forzados, DB, CSV, "corrida 3 forzada")
    resultados.append({"corrida": "3: duplicados forzados", **resumen, "filas_csv": filas_csv()})

    df = pd.DataFrame(resultados)[["corrida", *COLUMNAS, "filas_csv"]]
    repetidas = llaves_repetidas()
    primera, ultima = df.iloc[0], df.iloc[-1]
    # Si el sitio publicó un año nuevo entre corridas, la diferencia aparece en `insertadas`
    nuevas = int(df["insertadas"].iloc[1:].sum())
    correcto = repetidas == 0 and ultima["total_observaciones"] == primera["total_observaciones"] + nuevas \
        and df.iloc[2]["insertadas"] == 0 and df.iloc[2]["sin_pais"] == 1 and df.iloc[2]["duplicados"] > 0

    veredicto = "SUPERADO" if correcto else "NO SUPERADO"
    guardar_csv(config.RESULTADOS / "reto_reejecucion.csv", df)
    (config.RESULTADOS / "reto_reejecucion.md").write_text(
        f"# Reto de re-ejecución: {veredicto}\n\n{tabla_md(df)}\n\n"
        f"Llaves (pais_id, indicador_id, anio) repetidas en SQLite: **{repetidas}**.\n", encoding="utf-8")
    b.evento("resultado", f"Reto {veredicto}: {repetidas} llaves repetidas; {nuevas} filas nuevas tras la corrida 1")
    print("\n" + df.to_string(index=False))
    print(f"\nLlaves repetidas: {repetidas}\nReto: {veredicto}")


if __name__ == "__main__":
    main()
