"""
Limpieza y estructuración con Pandas de los datos crudos del bot (Fase 3).

Entrada : datos/crudos_<fecha>.json  (por defecto, el más reciente)
Salida  : datos/datasets_limpios.csv (UTF-8 con BOM: abre bien en Excel)
          datos/datasets_limpios.xlsx (si está instalado openpyxl)

Pasos (cada uno imprime qué cambió, para el reporte):
  1. Cargar el JSON en un DataFrame y medir nulos iniciales.
  2. Normalizar texto: espacios, saltos de línea, Unicode y textos "vacíos" de CKAN.
  3. Completar el título truncado del listado con el título completo de la ficha.
  4. Eliminar duplicados (misma URL) y filas sin título o sin URL (nulos críticos).
  5. Normalizar formatos (lista -> "CSV, JSON") y derivar columnas.
  6. Convertir fechas (ISO 8601 o texto en español) a datetime y derivar año/antigüedad.
  7. Rellenar nulos no críticos con valores explícitos y ordenar columnas.

Uso:
    python limpieza.py
    python limpieza.py --entrada datos/crudos_20261016_101500.json
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

import config

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 45)

# Textos que CKAN muestra cuando un campo está vacío: se tratan como nulos
PLACEHOLDERS = re.compile(
    r"^(there is no description for this dataset|no hay (una )?descripci[oó]n.*|"
    r"sin descripci[oó]n|n/?a|none|null|-+)$",
    re.IGNORECASE,
)

MESES = {  # para fechas escritas en español: "3 de octubre de 2025"
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05", "junio": "06",
    "julio": "07", "agosto": "08", "septiembre": "09", "setiembre": "09", "octubre": "10",
    "noviembre": "11", "diciembre": "12",
}

# Nombres de campo de la tabla "Información adicional" (inglés o español) -> columna
CAMPOS_INFO = {
    "fecha_actualizacion_raw": ["last updated", "ultima actualizacion", "actualizado",
                                "fecha de actualizacion", "ultima modificacion"],
    "fecha_creacion_raw": ["created", "creado", "fecha de creacion", "fecha de publicacion"],
    "licencia": ["license", "licencia"],
    "frecuencia": ["frecuencia de actualizacion", "update frequency"],
    "fuente": ["source", "fuente"],
    "autor": ["author", "autor"],
    "mantenedor": ["maintainer", "mantenedor", "responsable"],
    "version": ["version"],
}


def titulo(texto: str) -> None:
    print(f"\n{'─' * 78}\n{texto}\n{'─' * 78}")


def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def limpiar_texto(valor):
    """Normaliza Unicode, colapsa espacios y convierte textos vacíos en NA."""
    if not isinstance(valor, str):
        return valor
    v = unicodedata.normalize("NFC", valor)
    v = re.sub(r"\s+", " ", v).strip()
    if not v or PLACEHOLDERS.match(v):
        return pd.NA
    return v


def parse_fecha(valor) -> pd.Timestamp:
    """ISO 8601 (atributo data-datetime de CKAN) o texto en español -> Timestamp sin zona."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor is pd.NA:
        return pd.NaT
    v = str(valor).strip().lower()
    v = re.sub(r"\(utc\)", "", v).strip()
    # "3 de octubre de 2025, 17:41" -> "2025-10-03 17:41"
    m = re.match(r"(\d{1,2}) de ([a-záéíóú]+) de (\d{4})(?:,?\s*(\d{1,2}:\d{2}))?", v)
    if m and sin_acentos(m.group(2)) in MESES:
        v = f"{m.group(3)}-{MESES[sin_acentos(m.group(2))]}-{int(m.group(1)):02d} {m.group(4) or '00:00'}"
    # "octubre 3, 2025, 17:41" (formato inglés traducido)
    m = re.match(r"([a-záéíóú]+) (\d{1,2}), (\d{4})(?:,?\s*(\d{1,2}:\d{2}))?", v)
    if m and sin_acentos(m.group(1)) in MESES:
        v = f"{m.group(3)}-{MESES[sin_acentos(m.group(1))]}-{int(m.group(2)):02d} {m.group(4) or '00:00'}"
    ts = pd.to_datetime(v, errors="coerce", format="mixed")
    if pd.isna(ts):
        return pd.NaT
    # ISO con zona horaria (CKAN data-datetime) -> hora de México; texto sin zona se deja tal cual
    if ts.tzinfo is not None:
        ts = ts.tz_convert("America/Mexico_City").tz_localize(None)
    return ts


def tabla_nulos(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    cols = [c for c in columnas if c in df.columns]
    return pd.DataFrame({"nulos": df[cols].isna().sum(), "% nulos": (df[cols].isna().mean() * 100).round(1)})


def ultimo_crudo() -> Path:
    archivos = sorted(config.CARPETA_DATOS.glob("crudos_*.json"))
    if not archivos:
        raise SystemExit("No hay datos crudos. Ejecuta primero: python bot_portal.py")
    return archivos[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", type=Path, help="JSON crudo (por defecto el más reciente)")
    args = ap.parse_args()
    ruta = args.entrada or ultimo_crudo()

    # ------------------------------------------------------------------ 1
    titulo(f"1. Carga de datos crudos: {ruta.name}")
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    meta, df = contenido["meta"], pd.DataFrame(contenido["datos"])
    print(f"Portal: {meta['portal']} | término: '{meta['termino']}' | filtro: {meta['filtro']}")
    filas_iniciales = len(df)
    print(f"Forma inicial: {df.shape[0]} filas x {df.shape[1]} columnas")

    # Las columnas "info::<Campo>" vienen de la tabla de detalle; se mapean a nombres fijos
    info_cols = {c: sin_acentos(c.split("::", 1)[1]).lower() for c in df.columns if c.startswith("info::")}
    for destino, alias in CAMPOS_INFO.items():
        origen = [c for c, nombre in info_cols.items() if nombre in alias]
        df[destino] = df[origen].bfill(axis=1).iloc[:, 0] if origen else pd.NA
    df = df.drop(columns=list(info_cols))
    for col in ["titulo_detalle", "organizacion", "organizacion_lista", "num_recursos", "etiquetas", "detalle_ok"]:
        if col not in df.columns:
            df[col] = pd.NA
    # La organización puede venir de la ficha o, en algunos portales, del propio listado
    df["organizacion"] = df["organizacion"].where(df["organizacion"].notna(), df["organizacion_lista"])

    clave = ["titulo", "url", "descripcion", "organizacion", "fecha_actualizacion_raw", "fecha_creacion_raw"]
    nulos_antes = tabla_nulos(df, clave)
    print("\nNulos iniciales en columnas clave:")
    print(nulos_antes.to_string())

    # ------------------------------------------------------------------ 2
    titulo("2. Normalización de texto")
    texto_cols = ["titulo", "titulo_detalle", "descripcion", "organizacion", "organizacion_lista", "fuente", "autor",
                  "mantenedor", "version", "licencia", "frecuencia", "url"]
    vacios_antes = df[texto_cols].isna().sum().sum()
    cambiados = 0
    for c in texto_cols:
        original = df[c].copy()
        df[c] = df[c].map(limpiar_texto).astype("string")
        cambiados += int(((original.astype("string") != df[c]) & original.notna() & df[c].notna()).sum())
    print(f"{cambiados} textos corregidos (espacios dobles, saltos de línea, espacios al inicio/fin).")
    print(f"{int(df[texto_cols].isna().sum().sum() - vacios_antes)} textos vacíos o de relleno convertidos a nulo.")

    # ------------------------------------------------------------------ 3
    titulo("3. Títulos completos")
    truncados = df["titulo"].str.endswith("...", na=False) | df["titulo"].str.endswith("…", na=False)
    # Solo se reemplaza el título si el listado lo cortó ("...") y la ficha trae uno que
    # empieza igual (evita tomar por error un <h1> genérico del sitio).
    base = df["titulo"].str.replace(r"(\.\.\.|…)$", "", regex=True).fillna("")
    reemplazables = (truncados & df["titulo_detalle"].notna()
                     & df.apply(lambda r: str(r["titulo_detalle"]).startswith(base[r.name][:30]), axis=1))
    df.loc[reemplazables, "titulo"] = df.loc[reemplazables, "titulo_detalle"]
    print(f"{int(truncados.sum())} títulos truncados en el listado; "
          f"{int(reemplazables.sum())} reemplazados por el título completo de la ficha.")

    # ------------------------------------------------------------------ 4
    titulo("4. Duplicados y nulos críticos")
    antes = len(df)
    df = df.drop_duplicates(subset="url", keep="first")
    duplicados = antes - len(df)
    antes = len(df)
    df = df.dropna(subset=["titulo", "url"])
    sin_clave = antes - len(df)
    print(f"Duplicados eliminados (misma URL): {duplicados}")
    print(f"Filas eliminadas por título o URL nulos: {sin_clave}")

    # ------------------------------------------------------------------ 5
    titulo("5. Formatos y columnas derivadas")

    def normalizar_formatos(lista) -> str | None:
        if not isinstance(lista, list):
            return None
        limpios = sorted({str(f).strip().upper().lstrip(".") for f in lista if str(f).strip()})
        return ", ".join(limpios) or None

    df["formatos"] = df["formatos"].map(normalizar_formatos).astype("string")
    df["num_formatos"] = df["formatos"].fillna("").map(lambda s: len([x for x in s.split(", ") if x])).astype("Int64")
    df["tiene_csv"] = df["formatos"].str.contains(r"\bCSV\b", na=False)
    df["etiquetas"] = df["etiquetas"].map(lambda l: ", ".join(l) if isinstance(l, list) and l else pd.NA).astype("string")
    df["num_recursos"] = pd.to_numeric(df["num_recursos"], errors="coerce").astype("Int64")
    df["id_dataset"] = df["url"].str.extract(r"/dataset/([^/?#]+)")[0]
    # Organismo: primer nivel de la jerarquía ("Ministerio de Salud. Dirección X" -> "Ministerio de Salud")
    df["organismo"] = (df["organizacion"].str.split(r"\.\s", n=1, regex=True).str[0]
                       .str.replace(r"\s+de la Naci[oó]n$", "", regex=True).str.strip(" ."))
    print(df["formatos"].value_counts().head(8).to_string())

    # ------------------------------------------------------------------ 6
    titulo("6. Fechas")
    for raw, limpia in [("fecha_actualizacion_raw", "fecha_actualizacion"), ("fecha_creacion_raw", "fecha_creacion")]:
        df[limpia] = df[raw].map(parse_fecha)
        df[limpia] = pd.to_datetime(df[limpia], errors="coerce")
        ok = df[limpia].notna().sum()
        print(f"{limpia}: {ok}/{len(df)} convertidas a fecha "
              f"(ej. '{df[raw].dropna().iloc[0] if df[raw].notna().any() else '—'}' -> "
              f"{df[limpia].dropna().iloc[0] if ok else '—'})")
    hoy = pd.Timestamp.now().normalize()
    # Si el portal no publica "última actualización", se usa la fecha de publicación
    referencia = df["fecha_actualizacion"].fillna(df["fecha_creacion"])
    df["anio_actualizacion"] = referencia.dt.year.astype("Int64")
    df["dias_sin_actualizar"] = (hoy - referencia.dt.normalize()).dt.days.astype("Int64")
    df["extraido_en"] = pd.to_datetime(df["extraido_en"], errors="coerce")

    # ------------------------------------------------------------------ 7
    titulo("7. Relleno de nulos no críticos y orden final")
    # Distinguir "la ficha no tiene organización" de "no se visitó la ficha"
    con_ficha = df["detalle_ok"].fillna(False).astype(bool) | df["organizacion_lista"].notna()
    df.loc[con_ficha, "organizacion"] = df.loc[con_ficha, "organizacion"].fillna("Sin organización")
    df["organizacion"] = df["organizacion"].fillna("No consultada (sin ficha)")
    fichas = int(df["detalle_ok"].fillna(False).astype(bool).sum())
    print(f"Fichas de detalle consultadas: {fichas}/{len(df)}.")
    if con_ficha.sum() < len(df):
        print("Las demás no tienen organización ni fechas porque el bot no visitó su ficha (límite --detalles).")
    df["descripcion"] = df["descripcion"].fillna("Sin descripción")
    df["formatos"] = df["formatos"].fillna("Sin recursos")
    df["organismo"] = df["organismo"].fillna(df["organizacion"])
    columnas = ["id_dataset", "titulo", "organismo", "organizacion", "formatos", "num_formatos", "tiene_csv",
                "num_recursos", "fecha_creacion", "fecha_actualizacion", "anio_actualizacion",
                "dias_sin_actualizar", "frecuencia", "licencia", "etiquetas", "descripcion", "fuente",
                "autor", "mantenedor", "url", "pagina", "posicion", "extraido_en"]
    df = df[columnas].sort_values("fecha_actualizacion", ascending=False, na_position="last").reset_index(drop=True)
    print(tabla_nulos(df, ["titulo", "url", "descripcion", "organizacion", "fecha_actualizacion", "fecha_creacion"]).to_string())

    # ----------------------------------------------------------------- salida
    salida = config.CARPETA_DATOS / "datasets_limpios.csv"
    df.to_csv(salida, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M")
    try:
        df.to_excel(salida.with_suffix(".xlsx"), index=False)
        extra = f" y {salida.with_suffix('.xlsx').name}"
    except ImportError:
        extra = ""

    titulo("RESULTADO")
    print(f"Filas: {filas_iniciales} crudas -> {len(df)} limpias | columnas: {df.shape[1]}")
    print(f"Archivo: {salida}{extra}\n")
    vista = df[["titulo", "organismo", "formatos", "num_recursos", "fecha_creacion"]].head(15).copy()
    vista["fecha_creacion"] = vista["fecha_creacion"].dt.strftime("%Y-%m-%d")
    vista["titulo"] = vista["titulo"].str.slice(0, 55)              # solo para que quepa en pantalla
    vista["organismo"] = vista["organismo"].str.slice(0, 30)
    print(vista.to_string())

    print("\nConjuntos por organismo (top 5):")
    print(df["organismo"].value_counts().head(5).to_string())
    print("\nConjuntos por año de última actualización:")
    print(df["anio_actualizacion"].value_counts(dropna=False).sort_index().to_string())
    print("\nTipos de dato finales:")
    print(df.dtypes.to_string())


if __name__ == "__main__":
    main()
