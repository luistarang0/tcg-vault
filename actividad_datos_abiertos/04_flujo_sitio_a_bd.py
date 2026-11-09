"""
Actividad 3: del sitio a la base de datos.

  1. Selenium localiza las filas de la tabla por país de 4 indicadores del World Bank.
  2. Pandas limpia, normaliza, quita duplicados y separa los valores faltantes.
  3. Se guarda en SQLite con inserción idempotente y se exporta a CSV.
  4. Una consulta SQL genera un reporte pequeño.

Salidas: datos/world_bank.sqlite, datos/limpios/*.csv, datos/crudos_<fecha>.json
         y resultados/reporte_sql.md

Uso:  python actividad_datos_abiertos/04_flujo_sitio_a_bd.py [--headless]
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
import limpieza
import worldbank as wb
from comun import Bitacora, Bloqueado, Cliente, abrir_navegador, args_headless, guardar_json, tabla_md

DB = config.DATOS / "world_bank.sqlite"
CARPETA_CSV = config.DATOS / "limpios"

CONSULTAS = {
    "Cobertura por indicador": """
        SELECT i.indicador, count(*) AS paises_con_dato,
               (SELECT count(*) FROM faltantes f JOIN paises x USING (pais_id)
                WHERE f.indicador_id = i.indicador_id AND x.es_agregado = 0) AS paises_sin_dato,
               min(o.anio) AS anio_mas_antiguo, max(o.anio) AS anio_mas_reciente
        FROM observaciones o JOIN indicadores i USING (indicador_id) JOIN paises p USING (pais_id)
        WHERE p.es_agregado = 0
        GROUP BY i.indicador_id ORDER BY i.indicador""",
    "Los 10 países con mayor PIB per cápita (US$)": """
        SELECT p.pais, o.anio, round(o.valor, 2) AS pib_per_capita
        FROM observaciones o JOIN paises p USING (pais_id)
        WHERE o.indicador_id = 'NY.GDP.PCAP.CD' AND p.es_agregado = 0
        ORDER BY o.valor DESC LIMIT 10""",
    "México en los 4 indicadores": """
        SELECT i.indicador, o.anio, round(o.valor, 2) AS valor
        FROM observaciones o JOIN indicadores i USING (indicador_id)
        WHERE o.pais_id = 'MX' ORDER BY i.indicador""",
}


def extraer(headless: bool, b: Bitacora) -> list[dict]:
    """Recorre los indicadores. Ante un bloqueo se detiene y conserva lo obtenido."""
    c = Cliente(b)
    driver = abrir_navegador(headless)
    b.evento("herramienta", f"Selenium con {driver.nombre_navegador} y WebDriverWait")
    crudos = []
    try:
        paises = wb.paises_api(c)                     # solo para distinguir países de agregados
        for indicador in config.INDICADORES:
            try:
                bloque = wb.por_selenium(c, driver, indicador)
            except Bloqueado as e:
                b.evento("bloqueo", f"{e}. Se detiene la extracción.")
                break
            for fila in bloque["filas"]:
                fila["es_agregado"] = fila["pais_id"] not in paises
            crudos.append(bloque)
            print(f"  {indicador}: {len(bloque['filas'])} filas (unidad: {bloque['unidad_texto']})")
    finally:
        driver.quit()
    return crudos


def reporte(db: Path, salida: Path) -> str:
    con = sqlite3.connect(db)
    partes = [f"# Reporte SQL del World Bank\n\nGenerado el {datetime.now():%Y-%m-%d %H:%M} desde `{db.name}`.\n"]
    try:
        for titulo, sql in CONSULTAS.items():
            df = pd.read_sql(sql, con)
            partes.append(f"## {titulo}\n\n```sql\n{sql.strip()}\n```\n\n{tabla_md(df)}\n")
    finally:
        con.close()
    texto = "\n".join(partes)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(texto, encoding="utf-8")
    return texto


def procesar(crudos: list[dict], db: Path, carpeta_csv: Path, origen: str) -> dict:
    observaciones, faltantes, conteo = limpieza.limpiar(crudos)
    resumen = limpieza.guardar(observaciones, faltantes, conteo, db, config.INDICADORES, origen)
    limpieza.exportar_csv(db, carpeta_csv)
    return resumen


def main() -> None:
    b = Bitacora("04_flujo")
    crudos = extraer(args_headless(), b)
    if not crudos:
        raise SystemExit("No se obtuvieron datos: revisa resultados/bitacora.jsonl")
    guardar_json(config.DATOS / f"crudos_{datetime.now():%Y%m%d_%H%M%S}.json", crudos)
    resumen = procesar(crudos, DB, CARPETA_CSV, "selenium")
    b.evento("resultado", str(resumen))
    print("\n" + reporte(DB, config.RESULTADOS / "reporte_sql.md"))


if __name__ == "__main__":
    main()
