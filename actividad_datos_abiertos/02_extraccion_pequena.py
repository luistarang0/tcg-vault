"""
Actividad 1: extracción pequeña, documentada y reproducible.

Fuente: API oficial del World Bank (sin clave, licencia CC BY 4.0). Es el método
permitido más apropiado para este sitio: documentado, con paginación y valores exactos.
Pide 20 años de 4 indicadores para México: 4 peticiones en total.

Salidas: datos/api_mexico.json y datos/api_mexico.csv

Uso:  python actividad_datos_abiertos/02_extraccion_pequena.py [--pais MX] [--anios 2006:2025]
"""
from __future__ import annotations

import argparse
from datetime import datetime

import pandas as pd

import config
from comun import Bitacora, Cliente, guardar_csv, guardar_json


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pais", default="MX", help="código ISO de 2 letras")
    ap.add_argument("--anios", default="2006:2025", help="rango inicio:fin")
    a = ap.parse_args()

    b = Bitacora("02_extraccion_pequena")
    c = Cliente(b)
    b.evento("herramienta", "requests contra api.worldbank.org/v2 (API oficial)")
    filas = []
    for indicador, nombre in config.INDICADORES.items():
        url = (f"https://api.worldbank.org/v2/country/{a.pais}/indicator/{indicador}"
               f"?format=json&date={a.anios}&per_page=100")
        r = c.get(url)
        r.raise_for_status()
        meta, datos = r.json()
        filas += [{"pais_id": d["country"]["id"], "pais": d["country"]["value"], "indicador_id": indicador,
                   "indicador": nombre, "anio": int(d["date"]), "valor": d["value"]} for d in datos]
        print(f"  {indicador}: {len(datos)} de {meta['total']} registros")

    df = pd.DataFrame(filas).sort_values(["indicador_id", "anio"]).reset_index(drop=True)
    guardar_json(config.DATOS / "api_mexico.json", {
        "fuente": "https://api.worldbank.org/v2", "licencia": "CC BY 4.0",
        "pais": a.pais, "anios": a.anios, "extraido_en": datetime.now().isoformat(timespec="seconds"),
        "datos": filas})
    guardar_csv(config.DATOS / "api_mexico.csv", df)
    b.evento("resultado", f"{len(df)} registros; {int(df['valor'].isna().sum())} sin valor publicado")
    print(f"\nListo: {config.DATOS / 'api_mexico.csv'}")


if __name__ == "__main__":
    main()
