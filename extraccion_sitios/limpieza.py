"""
Limpieza y almacenamiento del dataset extraído (TAD 2.4).

Lee el JSON crudo más reciente de extractor.py y produce datos estructurados:

  datos/extraccion_sitios.sqlite   base de datos con llaves primarias, foráneas y vistas
  datos/limpios/<tabla>.csv        una tabla por archivo (UTF-8 con BOM para Excel)
  datos/dataset_limpio.xlsx        una hoja por tabla

Transformaciones (todas con pandas):
  * Texto: espacios recortados y colapsados, Unicode NFC, cadenas vacías -> nulo.
  * Precios: "$8.49" -> 8.49, "$ 26.000,00" (formato es-MX con punto de miles) -> 26000.0,
    "Gratis" -> 0. Moneda: MXN solo donde el sitio lo declara; si no, "no_indicada".
  * Fechas: "Octubre 23 , 2026 11:52 A. M." y "oct. 23 , 11:52 a. m." -> ISO 8601.
    Si la tarjeta no trae año se infiere el más cercano a la fecha de extracción
    (columna anio_inferido = 1).
  * Duración "1 hrs 33 mins" -> 93 minutos; calorías "480 cal" -> 480; PS "PS 60" -> 60.
  * Campos compuestos separados: "Postres · Pieza · Agotado" -> categoría, presentación,
    disponible; "Planta,Agua" -> tipo_principal y num_tipos.
  * Duplicados eliminados por llave natural; precios atípicos marcados (más de 3 veces
    o menos de un tercio de la mediana de su sitio).

Uso:
    python extraccion_sitios/limpieza.py                     # crudo más reciente
    python extraccion_sitios/limpieza.py --archivo datos/crudos_20261028_011627.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATOS  # noqa: E402

MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
         "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}

ENTEROS = {"calorias", "disponible", "precio_atipico", "descuento_pct", "dias_vigencia", "duracion_min",
           "anio_inferido", "num_tipos_boleto", "tiene_gratis", "pagina", "es_gratis", "num_tipos",
           "generacion", "hp", "id", "es_casa", "puja_actual", "puja_minima", "compra_inmediata", "num_pujas"}

SCHEMA = """
CREATE TABLE sitios (
  clave TEXT PRIMARY KEY, nombre TEXT NOT NULL, url TEXT NOT NULL, tecnologia TEXT,
  clasificacion TEXT, estado TEXT, segundos REAL, extraido_en TEXT
);
CREATE TABLE productos (
  sitio TEXT NOT NULL REFERENCES sitios(clave), id_externo TEXT NOT NULL, nombre TEXT NOT NULL,
  categoria TEXT, descripcion TEXT, detalle TEXT, precio REAL, moneda TEXT, calorias INTEGER,
  porcion TEXT, ingredientes TEXT, presentacion TEXT, disponible INTEGER, precio_atipico INTEGER,
  url TEXT, imagen TEXT, PRIMARY KEY (sitio, id_externo)
);
CREATE TABLE promociones (
  sitio TEXT NOT NULL REFERENCES sitios(clave), titulo TEXT NOT NULL, descuento_pct INTEGER,
  descripcion TEXT, vigencia_inicio TEXT, vigencia_fin TEXT, dias_vigencia INTEGER,
  PRIMARY KEY (sitio, titulo)
);
CREATE TABLE eventos (
  slug TEXT PRIMARY KEY, sitio TEXT NOT NULL REFERENCES sitios(clave), titulo TEXT NOT NULL,
  categoria TEXT, lugar TEXT, direccion TEXT, duracion_min INTEGER, fecha TEXT, anio_inferido INTEGER,
  precio_min REAL, precio_max REAL, num_tipos_boleto INTEGER, tiene_gratis INTEGER, moneda TEXT,
  url TEXT, pagina INTEGER
);
CREATE TABLE boletos (
  evento_slug TEXT NOT NULL REFERENCES eventos(slug), tipo TEXT NOT NULL, precio REAL, es_gratis INTEGER,
  PRIMARY KEY (evento_slug, tipo, precio)
);
CREATE TABLE cartas (
  id TEXT PRIMARY KEY, sitio TEXT NOT NULL REFERENCES sitios(clave), nombre TEXT NOT NULL, categoria TEXT,
  tipos TEXT, tipo_principal TEXT, num_tipos INTEGER, rareza TEXT, coleccion TEXT, numero TEXT,
  generacion INTEGER, hp INTEGER
);
CREATE TABLE subastas (
  id INTEGER PRIMARY KEY, sitio TEXT NOT NULL REFERENCES sitios(clave), carta_id TEXT, carta TEXT,
  vendedor TEXT, es_casa INTEGER, puja_actual INTEGER, puja_minima INTEGER, compra_inmediata INTEGER,
  num_pujas INTEGER, estado TEXT, termina_en TEXT
);
CREATE VIEW v_resumen_sitios AS
  SELECT s.nombre AS sitio, s.clasificacion,
         (SELECT count(*) FROM productos p WHERE p.sitio = s.clave) AS productos,
         (SELECT count(*) FROM promociones p WHERE p.sitio = s.clave) AS promociones,
         (SELECT count(*) FROM eventos e WHERE e.sitio = s.clave) AS eventos,
         (SELECT count(*) FROM cartas c WHERE c.sitio = s.clave) AS cartas,
         (SELECT count(*) FROM subastas u WHERE u.sitio = s.clave) AS subastas,
         s.estado, s.segundos
  FROM sitios s;
CREATE VIEW v_precios_productos AS
  SELECT sitio, categoria, count(*) AS n, round(avg(precio), 2) AS precio_promedio,
         min(precio) AS precio_min, max(precio) AS precio_max, moneda
  FROM productos WHERE precio_atipico = 0 GROUP BY sitio, categoria, moneda;
CREATE VIEW v_eventos_por_categoria AS
  SELECT categoria, count(*) AS eventos, round(avg(duracion_min)) AS duracion_promedio_min,
         sum(tiene_gratis) AS con_boleto_gratis, round(avg(precio_max), 2) AS precio_max_promedio
  FROM eventos GROUP BY categoria ORDER BY eventos DESC;
CREATE VIEW v_cartas_por_rareza AS
  SELECT rareza, count(*) AS cartas, round(avg(hp)) AS hp_promedio FROM cartas GROUP BY rareza ORDER BY cartas DESC;
"""


# ------------------------------------------------------------------ utilidades
def limpiar_texto(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = unicodedata.normalize("NFC", str(v))
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def precio(texto) -> float | None:
    """'$8.49' -> 8.49 · '$ 26.000,00' -> 26000.0 · 'Gratis' -> 0.0"""
    t = limpiar_texto(texto)
    if not t:
        return None
    if "gratis" in t.lower():
        return 0.0
    t = re.sub(r"[^\d.,]", "", t)
    if "," in t and t.rfind(",") > t.rfind("."):   # formato 26.000,00
        t = t.replace(".", "").replace(",", ".")
    else:                                          # formato 1,234.56 o 8.49
        t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def entero(texto) -> int | None:
    m = re.search(r"\d+", limpiar_texto(texto) or "")
    return int(m.group()) if m else None


def minutos(texto) -> int | None:
    t = (limpiar_texto(texto) or "").lower()
    h = re.search(r"(\d+)\s*h", t)
    m = re.search(r"(\d+)\s*min", t)
    if not h and not m:
        return None
    return (int(h.group(1)) if h else 0) * 60 + (int(m.group(1)) if m else 0)


def fecha_es(texto, referencia: datetime) -> tuple[str | None, int]:
    """'Octubre 23 , 2026 11:52 A. M.' / 'oct. 23 , 11:52 a. m.' -> (ISO, año_inferido)."""
    t = (limpiar_texto(texto) or "").lower().replace(".", "")
    m = re.search(r"([a-záéíóú]+)\s*(\d{1,2})\s*,?\s*(\d{4})?\s*(\d{1,2}):(\d{2})\s*([ap])\s*m", t)
    if not m:
        return None, 0
    mes = MESES.get(m.group(1)[:3])
    if not mes:
        return None, 0
    hora = int(m.group(4)) % 12 + (12 if m.group(6) == "p" else 0)
    if m.group(3):
        anio, inferido = int(m.group(3)), 0
    else:   # año más cercano a la fecha de extracción
        anio = min((referencia.year + d for d in (-1, 0, 1)),
                   key=lambda y: abs((datetime(y, mes, int(m.group(2))) - referencia).days))
        inferido = 1
    return datetime(anio, mes, int(m.group(2)), hora, int(m.group(5))).isoformat(timespec="minutes"), inferido


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def marcar_atipicos(df: pd.DataFrame) -> pd.Series:
    mediana = df.groupby("sitio")["precio"].transform("median")
    return ((df["precio"] > mediana * 3) | (df["precio"] < mediana / 3)).astype(int)


# ------------------------------------------------------------------ tablas
def construir(crudo: dict) -> dict[str, pd.DataFrame]:
    meta = crudo["meta"]
    ref = datetime.fromisoformat(meta["inicio"])
    t: dict[str, pd.DataFrame] = {}

    t["sitios"] = pd.DataFrame([{"clave": k, "nombre": v["nombre"], "url": v["base"], "tecnologia": v["tecnologia"],
                                 "clasificacion": v["clasificacion"], "estado": v["estado"],
                                 "segundos": v["segundos"], "extraido_en": meta["inicio"]}
                                for k, v in meta["sitios"].items()])

    # Productos de Porké y del menú de Café & Charla en una sola tabla
    filas = []
    for p in crudo.get("porke_productos", []):
        filas.append({"sitio": "porke", "id_externo": p["id_externo"], "nombre": p["nombre"],
                      "categoria": p["categoria"], "descripcion": p["descripcion"], "detalle": p.get("detalle"),
                      "precio": precio(p["precio_texto"]), "moneda": "no_indicada",
                      "calorias": entero(p.get("calorias_texto")), "porcion": p.get("porcion"),
                      "ingredientes": p.get("ingredientes"), "presentacion": None, "disponible": 1,
                      "url": p["url"], "imagen": p["imagen"]})
    for p in crudo.get("cafe_menu", []):
        partes = [x.strip() for x in (p.get("meta") or "").split("·")]
        filas.append({"sitio": "cafe", "id_externo": slug(p["nombre"]), "nombre": p["nombre"],
                      "categoria": partes[0] if partes and partes[0] else None, "descripcion": p["descripcion"],
                      "detalle": None, "precio": precio(p["precio_texto"]), "moneda": "MXN",
                      "calorias": None, "porcion": None, "ingredientes": None,
                      "presentacion": partes[1] if len(partes) > 1 and partes[1] != "Agotado" else None,
                      "disponible": 0 if "Agotado" in partes else 1, "url": p["url"], "imagen": p["imagen"]})
    t["productos"] = pd.DataFrame(filas)
    if not t["productos"].empty:
        t["productos"]["precio_atipico"] = marcar_atipicos(t["productos"])

    filas = []
    for p in crudo.get("cafe_promociones", []):
        fechas = re.findall(r"\d{4}-\d{2}-\d{2}", p.get("vigencia_texto") or "")
        ini, fin = (fechas + [None, None])[:2]
        filas.append({"sitio": "cafe", "titulo": p["titulo"], "descuento_pct": entero(p["descuento_texto"]),
                      "descripcion": p["descripcion"], "vigencia_inicio": ini, "vigencia_fin": fin,
                      "dias_vigencia": (datetime.fromisoformat(fin) - datetime.fromisoformat(ini)).days
                      if ini and fin else None})
    t["promociones"] = pd.DataFrame(filas)

    eventos, boletos = [], []
    for e in crudo.get("ticketshield_eventos", []):
        fecha, inferido = fecha_es(e.get("fecha_ficha"), ref)
        if not fecha:
            fecha, inferido = fecha_es(e.get("fecha_tarjeta"), ref)
        precios = [precio(b["precio_texto"]) for b in e.get("boletos", [])]
        precios = [x for x in precios if x is not None]
        tiene_ficha = "boletos" in e
        eventos.append({"slug": e["slug"], "sitio": "ticketshield", "titulo": e["titulo"].rstrip("."),
                        "categoria": e["categoria"], "lugar": e["lugar"], "direccion": e.get("direccion"),
                        "duracion_min": minutos(e["duracion_texto"]), "fecha": fecha, "anio_inferido": inferido,
                        "precio_min": min(precios) if precios else None, "precio_max": max(precios) if precios else None,
                        "num_tipos_boleto": len(e["boletos"]) if tiene_ficha else None,
                        "tiene_gratis": int(0.0 in precios) if tiene_ficha else None,
                        "moneda": "no_indicada", "url": e["url"], "pagina": e["pagina"]})
        for b in e.get("boletos", []):
            p = precio(b["precio_texto"])
            boletos.append({"evento_slug": e["slug"], "tipo": b["tipo"], "precio": p, "es_gratis": int(p == 0.0)})
    t["eventos"] = pd.DataFrame(eventos)
    t["boletos"] = pd.DataFrame(boletos)

    filas = []
    for c in crudo.get("tcgvault_cartas", []):
        tipos = [x for x in (c.get("tipos") or "").split(",") if x]
        numero = re.search(r"#\s*(\S+)", c.get("meta") or "")
        filas.append({"id": c["id"], "sitio": "tcgvault", "nombre": c["nombre"], "categoria": c["categoria"],
                      "tipos": ", ".join(tipos) or None, "tipo_principal": tipos[0] if tipos else None,
                      "num_tipos": len(tipos), "rareza": c["rareza"], "coleccion": c["coleccion"],
                      "numero": numero.group(1) if numero else None,
                      "generacion": entero(c["generacion"]), "hp": entero(c.get("hp_texto"))})
    t["cartas"] = pd.DataFrame(filas)

    filas = []
    for s in crudo.get("tcgvault_subastas", []):
        termina = s.get("termina_en")
        filas.append({"id": int(s["id"]), "sitio": "tcgvault", "carta_id": s["carta_id"], "carta": s["carta"],
                      "vendedor": s["vendedor"], "es_casa": int(s["vendedor"] == "casa"),
                      "puja_actual": entero(s["puja_actual"]), "puja_minima": entero(s["puja_minima"]),
                      "compra_inmediata": entero(s["compra_inmediata"]), "num_pujas": entero(s["num_pujas"]),
                      "estado": s["estado"],
                      "termina_en": datetime.fromisoformat(termina).astimezone(timezone.utc).isoformat(timespec="seconds")
                      if termina else None})
    t["subastas"] = pd.DataFrame(filas)

    llaves = {"productos": ["sitio", "id_externo"], "promociones": ["sitio", "titulo"], "eventos": ["slug"],
              "boletos": ["evento_slug", "tipo", "precio"], "cartas": ["id"], "subastas": ["id"]}
    for nombre, df in t.items():
        if df.empty:
            continue
        for col in df.select_dtypes(include=["object", "str"]).columns:
            df[col] = df[col].map(limpiar_texto)
        enteros = ENTEROS - ({"id"} if nombre == "cartas" else set())   # el id de una carta es texto (bw1-1)
        for col in enteros.intersection(df.columns):     # enteros que admiten nulo (no 3.0)
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        antes = len(df)
        if nombre in llaves:
            df = df.drop_duplicates(subset=llaves[nombre], keep="first")
        t[nombre] = df.reset_index(drop=True)
        if len(df) != antes:
            print(f"  {nombre}: {antes - len(df)} duplicados eliminados")
    return t


def guardar(tablas: dict[str, pd.DataFrame]) -> Path:
    db = DATOS / "extraccion_sitios.sqlite"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    try:
        con.executescript(SCHEMA)
        for nombre, df in tablas.items():
            if not df.empty:
                df.to_sql(nombre, con, if_exists="append", index=False)
        con.commit()
    finally:
        con.close()

    carpeta = DATOS / "limpios"
    carpeta.mkdir(exist_ok=True)
    for nombre, df in tablas.items():
        df.to_csv(carpeta / f"{nombre}.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(DATOS / "dataset_limpio.xlsx") as xls:
        for nombre, df in tablas.items():
            df.to_excel(xls, sheet_name=nombre, index=False)
    return db


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archivo", help="JSON crudo a procesar (por defecto, el más reciente)")
    a = ap.parse_args()
    archivo = Path(a.archivo) if a.archivo else max(DATOS.glob("crudos_*.json"), default=None,
                                                    key=lambda p: p.stat().st_mtime)
    if not archivo or not archivo.exists():
        raise SystemExit("No hay datos crudos. Ejecuta primero: python extraccion_sitios/extractor.py")
    print(f"Crudo: {archivo.name}")
    tablas = construir(json.loads(archivo.read_text(encoding="utf-8")))
    db = guardar(tablas)

    print("\nTablas limpias")
    for nombre, df in tablas.items():
        nulos = int(df.isna().sum().sum()) if not df.empty else 0
        print(f"  {nombre:<12} {len(df):>4} filas · {len(df.columns):>2} columnas · {nulos} valores nulos")
    if not tablas["productos"].empty:
        at = tablas["productos"][tablas["productos"]["precio_atipico"] == 1]
        for _, r in at.iterrows():
            print(f"  precio atípico: {r['sitio']} · {r['nombre']} · {r['precio']}")
    con = sqlite3.connect(db)
    print("\nv_resumen_sitios")
    print(pd.read_sql("SELECT * FROM v_resumen_sitios", con).to_string(index=False))
    con.close()
    print(f"\nSQLite: {db}\nCSV:    {DATOS / 'limpios'}\nExcel:  {DATOS / 'dataset_limpio.xlsx'}")


if __name__ == "__main__":
    main()
