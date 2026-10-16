"""
SIMULADOR LOCAL de un portal CKAN (solo para pruebas sin internet).

Reproduce el HTML de las plantillas de CKAN 2.10 (mismas clases y atributos que
usa el bot): buscador, facetas de formato y organización, paginación con "»",
fichas de detalle con la tabla "Información adicional" y robots.txt.
Los conjuntos de datos son FICTICIOS y se generan con una semilla fija.

Sirve para:
  * probar el bot sin depender de la red ni cargar al portal real;
  * demostrar la intervención humana: con --desafio, la página 2 muestra UNA vez
    una pantalla de verificación tipo Cloudflare.

Uso:
    python simulador_ckan.py                 # http://localhost:5050/busca/dataset
    python simulador_ckan.py --desafio       # con desafío en la página 2
    python bot_portal.py --base-url http://localhost:5050/busca
"""
from __future__ import annotations

import argparse
import html
import math
import random
import unicodedata
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

PREFIJO = "/busca"
POR_PAGINA = 20

ORGS = [("ssa", "Secretaría de Salud"), ("imss", "Instituto Mexicano del Seguro Social"),
        ("issste", "ISSSTE"), ("inegi", "INEGI"), ("conagua", "Comisión Nacional del Agua"),
        ("sep", "Secretaría de Educación Pública")]
TEMAS = ["Casos confirmados de dengue", "Egresos hospitalarios", "Unidades médicas en servicio",
         "Defunciones por causa", "Cobertura de vacunación", "Consultas externas otorgadas",
         "Camas censables por entidad", "Recursos humanos en salud", "Calidad del agua potable",
         "Matrícula escolar", "Programa de salud materna", "Abasto de medicamentos"]
FORMATOS = ["CSV", "XLSX", "JSON", "PDF", "ZIP", "SHP"]


def _quitar_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def generar_datasets() -> list[dict]:
    rng = random.Random(7)
    base = datetime(2026, 9, 30, tzinfo=timezone.utc)
    datos = []
    for i in range(78):
        tema = TEMAS[i % len(TEMAS)]
        anio = 2018 + (i % 9)
        slug_org, org = ORGS[i % len(ORGS)] if i % 13 else (None, None)   # algunos sin organización
        titulo = f"{tema} {anio}"
        if i % 9 == 0:   # títulos largos: CKAN los trunca a 80 caracteres en la lista
            titulo += " por entidad federativa, sexo y grupo de edad, información preliminar del sector salud"
        if i % 11 == 0:  # espacios sobrantes (texto "sucio")
            titulo = f"  {titulo}   "
        notas = "" if i % 7 == 0 else (
            f"Información de {tema.lower()} correspondiente a {anio}, publicada en el sector salud "
            f"para consulta pública.\n Se actualiza de forma periódica.")
        formatos = rng.sample(FORMATOS, rng.randint(1, 3)) if i % 17 else []
        creado = base - timedelta(days=rng.randint(400, 2600))
        modificado = None if i % 15 == 0 else creado + timedelta(days=rng.randint(10, 380))
        datos.append({
            "name": f"conjunto-{i + 1:03d}-{_quitar_acentos(tema).replace(' ', '-')}-{anio}",
            "title": titulo, "notes": notas, "org": org, "org_slug": slug_org,
            "formats": formatos, "created": creado, "modified": modificado,
            "tags": rng.sample(["salud", "hospitales", "epidemiologia", "estadistica", "agua", "educacion"], 2),
            "author": None if i % 4 == 0 else "Dirección General de Información en Salud",
        })
    return datos


DATASETS = generar_datasets()


def pagina_html(titulo: str, cuerpo: str) -> bytes:
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>{html.escape(titulo)} - Portal de Datos [SIMULADOR]</title>
<style>body{{font-family:sans-serif;margin:0;color:#222}} header{{background:#611232;color:#fff;padding:14px 24px}}
.wrap{{display:flex;gap:24px;max-width:1150px;margin:20px auto;padding:0 16px}} aside{{width:260px}}
.primary{{flex:1}} .dataset-item{{border-bottom:1px solid #ddd;padding:12px 0;list-style:none}}
.dataset-list{{padding:0}} .badge{{display:inline-block;background:#9d2449;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;text-decoration:none}}
.dataset-resources{{padding:0}} .dataset-resources li{{display:inline;margin-right:4px}}
.nav-facet{{padding:0}} .nav-facet li{{list-style:none;margin:4px 0}} .item-count{{background:#eee;color:#333}}
.pagination{{display:flex;gap:6px;list-style:none;padding:0}} .page-item a{{padding:4px 10px;border:1px solid #ccc;text-decoration:none}}
.page-item.active a{{background:#611232;color:#fff}} table{{border-collapse:collapse}} th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left}}
.aviso{{background:#fff4e5;padding:8px 24px;font-size:13px}}</style></head>
<body><header><strong>Portal de Datos Abiertos</strong> &middot; simulador local de CKAN</header>
<div class="aviso">Sitio de prueba con datos ficticios. No es un portal oficial.</div>
{cuerpo}</body></html>""".encode("utf-8")


def filtrar(q: str, fmt: str | None, org: str | None) -> list[dict]:
    qn = _quitar_acentos(q or "")
    res = [d for d in DATASETS if not qn or qn in _quitar_acentos(d["title"] + " " + d["notes"] + " " + " ".join(d["tags"]))]
    if fmt:
        res = [d for d in res if fmt in d["formats"]]
    if org:
        res = [d for d in res if d["org_slug"] == org]
    return res


def url_con(params: dict, **cambios) -> str:
    p = {k: v for k, v in {**params, **cambios}.items() if v}
    return f"{PREFIJO}/dataset?{urlencode(p)}"


def vista_busqueda(params: dict) -> bytes:
    q, fmt, org = params.get("q", ""), params.get("res_format"), params.get("organization")
    pagina = max(1, int(params.get("page", "1") or 1))
    res = filtrar(q, fmt, org)
    total, paginas = len(res), max(1, math.ceil(len(res) / POR_PAGINA))
    trozo = res[(pagina - 1) * POR_PAGINA: pagina * POR_PAGINA]

    items = []
    for d in trozo:
        t = d["title"] if len(d["title"]) <= 80 else d["title"][:77] + "..."
        notas = (f"<div>{html.escape(d['notes'][:180])}</div>" if d["notes"]
                 else '<p class="empty">There is no description for this dataset</p>')
        recursos = "".join(f'<li><a href="{PREFIJO}/dataset/{d["name"]}" class="badge badge-default" '
                           f'data-format="{f.lower()}">{f}</a></li>' for f in d["formats"])
        items.append(f"""<li class="dataset-item"><div class="dataset-content">
<h2 class="dataset-heading"><a href="{PREFIJO}/dataset/{d['name']}" title="{html.escape(d['title'])}">{html.escape(t)}</a></h2>
{notas}</div>{f'<ul class="dataset-resources list-unstyled">{recursos}</ul>' if recursos else ''}</li>""")

    def faceta(nombre: str, titulo: str, conteos: dict, etiquetas: dict) -> str:
        lis = "".join(
            f'<li class="nav-item"><a href="{url_con(params, **{nombre: k, "page": None})}" title="">'
            f'<span class="item-label">{html.escape(etiquetas.get(k, k))}</span>'
            f'<span class="hidden separator"> - </span><span class="item-count badge">{n}</span></a></li>'
            for k, n in sorted(conteos.items(), key=lambda x: -x[1]))
        return (f'<section class="module module-narrow module-shallow"><h2 class="module-heading">'
                f'<i class="fa fa-filter"></i> {titulo}</h2><nav aria-label="{titulo}">'
                f'<ul class="list-unstyled nav nav-simple nav-facet">{lis}</ul></nav></section>')

    c_fmt, c_org = {}, {}
    for d in res:
        for f in d["formats"]:
            c_fmt[f] = c_fmt.get(f, 0) + 1
        if d["org_slug"]:
            c_org[d["org_slug"]] = c_org.get(d["org_slug"], 0) + 1

    pag = ""
    if paginas > 1:
        lis = []
        if pagina > 1:
            lis.append(f'<li class="page-item"><a class="page-link" href="{url_con(params, page=pagina - 1)}">«</a></li>')
        for n in range(1, paginas + 1):
            cls = "page-item active" if n == pagina else "page-item"
            lis.append(f'<li class="{cls}"><a class="page-link" href="{url_con(params, page=n)}">{n}</a></li>')
        if pagina < paginas:
            lis.append(f'<li class="page-item"><a class="page-link" href="{url_con(params, page=pagina + 1)}">»</a></li>')
        pag = f'<div class="pagination-wrapper"><ul class="pagination justify-content-center">{"".join(lis)}</ul></div>'

    texto_total = (f'{total} conjuntos de datos encontrados para "{html.escape(q)}"' if q
                   else f"{total} conjuntos de datos encontrados")
    cuerpo = f"""<div class="wrap"><aside class="secondary">
{faceta('organization', 'Organizaciones', c_org, dict(ORGS))}
{faceta('res_format', 'Formatos', c_fmt, {})}</aside>
<section class="primary module"><div class="module-content">
<form id="dataset-search-form" class="search-form" method="get" action="{PREFIJO}/dataset">
<div class="input-group search-input-group"><input aria-label="Buscar conjuntos de datos..." id="field-giant-search"
 type="text" class="form-control input-lg" name="q" value="{html.escape(q)}" autocomplete="off" placeholder="Buscar conjuntos de datos...">
<button class="btn btn-default btn-lg" type="submit" value="search">Buscar</button></div>
{''.join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in params.items() if k in ('res_format', 'organization'))}
<h1>{texto_total}</h1></form>
<ul class="dataset-list list-unstyled">{''.join(items)}</ul></div>{pag}</section></div>"""
    return pagina_html("Conjuntos de datos", cuerpo)


def vista_detalle(nombre: str) -> bytes | None:
    d = next((x for x in DATASETS if x["name"] == nombre), None)
    if not d:
        return None

    def fecha(dt):
        if not dt:
            return ""
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                 "septiembre", "octubre", "noviembre", "diciembre"]
        visible = f"{dt.day} de {meses[dt.month - 1]} de {dt.year}, {dt:%H:%M} (UTC)"
        return f'<span class="automatic-local-datetime" data-datetime="{dt:%Y-%m-%dT%H:%M:%S%z}">{visible}</span>'

    filas = []
    if d["author"]:
        filas.append(("Autor", html.escape(d["author"])))
    if d["modified"]:
        filas.append(("Última actualización", fecha(d["modified"])))
    filas.append(("Creado", fecha(d["created"])))
    tabla = "".join(f'<tr><th scope="row" class="dataset-label">{k}</th><td class="dataset-details">{v}</td></tr>'
                    for k, v in filas)
    org = (f'<li><a href="{PREFIJO}/organization/{d["org_slug"]}">{html.escape(d["org"])}</a></li>'
           if d["org"] else "")
    recursos = "".join(f'<li class="resource-item"><a class="heading" href="#">Recurso {i + 1}'
                       f'<span class="format-label" data-format="{f.lower()}">{f}</span></a></li>'
                       for i, f in enumerate(d["formats"]))
    etiquetas = "".join(f'<li><a class="tag" href="{PREFIJO}/dataset?tags={t}">{t}</a></li>' for t in d["tags"])
    cuerpo = f"""<div class="wrap"><section class="primary">
<ol class="breadcrumb"><li><a href="/">Inicio</a></li>{org}<li class="active"><a href="#">{html.escape(d['title'][:35])}</a></li></ol>
<article class="module"><div class="module-content"><h1>{html.escape(d['title'])}</h1>
<div class="notes embedded-content"><p>{html.escape(d['notes'])}</p></div>
<section id="dataset-resources" class="resources"><h3>Datos y recursos</h3><ul class="resource-list">{recursos}</ul></section>
<section class="tags"><ul class="tag-list">{etiquetas}</ul></section>
<section class="additional-info"><h3>Información adicional</h3>
<table class="table table-striped table-bordered table-condensed"><thead><tr><th scope="col">Campo</th>
<th scope="col">Valor</th></tr></thead><tbody>{tabla}</tbody></table></section></div></article></section></div>"""
    return pagina_html(d["title"], cuerpo)


DESAFIO = """<!DOCTYPE html><html><head><title>Just a moment...</title></head><body style="font-family:sans-serif;padding:40px">
<h2>Verificando que eres humano</h2><p>Verify you are human by completing the action below.</p>
<form method="get"><input type="hidden" name="page" value="2"><input type="hidden" name="paso_desafio" value="1">
{ocultos}<label><input type="checkbox" required> No soy un robot</label> <button type="submit">Continuar</button></form>
<p style="color:#888">(Desafío simulado del entorno de pruebas)</p></body></html>"""


class Manejador(BaseHTTPRequestHandler):
    desafio_activo = False
    desafio_mostrado = False
    robots_403 = False
    bloqueo_waf = False

    def _responder(self, codigo: int, cuerpo: bytes, tipo: str = "text/html; charset=utf-8") -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(u.query).items()}
        if type(self).bloqueo_waf and u.path != "/robots.txt":
            cuerpo = ("<html><head><title>Access Denied</title></head><body><h1>Access Denied</h1>"
                      "<p>You don't have permission to access this server.</p>"
                      "<p>Reference #18.simulado</p></body></html>")
            return self._responder(403, cuerpo.encode())
        if u.path == "/robots.txt" and type(self).robots_403:
            return self._responder(403, b"Forbidden", "text/plain; charset=utf-8")
        if u.path == "/robots.txt":
            texto = "User-agent: *\nDisallow: /busca/dataset/edit/\nDisallow: /busca/api/\nCrawl-delay: 1\n"
            return self._responder(200, texto.encode(), "text/plain; charset=utf-8")
        if u.path in ("/", PREFIJO, PREFIJO + "/"):
            self.send_response(302); self.send_header("Location", f"{PREFIJO}/dataset"); self.end_headers(); return
        if u.path == f"{PREFIJO}/dataset":
            cls = type(self)
            if cls.desafio_activo and not cls.desafio_mostrado and params.get("page") == "2":
                cls.desafio_mostrado = True
                ocultos = "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">'
                                  for k, v in params.items() if k != "page")
                return self._responder(200, DESAFIO.format(ocultos=ocultos).encode())
            params.pop("paso_desafio", None)
            return self._responder(200, vista_busqueda(params))
        if u.path.startswith(f"{PREFIJO}/dataset/"):
            cuerpo = vista_detalle(u.path.rsplit("/", 1)[-1])
            if cuerpo:
                return self._responder(200, cuerpo)
        self._responder(404, pagina_html("No encontrado", "<h1>404 No encontrado</h1>"))

    def log_message(self, fmt, *args) -> None:
        print(f"[simulador] {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=5050)
    ap.add_argument("--desafio", action="store_true", help="muestra un desafío una vez en la página 2")
    ap.add_argument("--robots-403", action="store_true", help="robots.txt responde 403 (como algunos WAF)")
    ap.add_argument("--bloqueo-waf", action="store_true", help="todo responde 'Access Denied' (como Akamai)")
    a = ap.parse_args()
    Manejador.desafio_activo = a.desafio
    Manejador.robots_403 = a.robots_403
    Manejador.bloqueo_waf = a.bloqueo_waf
    print(f"Simulador CKAN en http://localhost:{a.puerto}{PREFIJO}/dataset  ({len(DATASETS)} conjuntos ficticios)")
    ThreadingHTTPServer(("127.0.0.1", a.puerto), Manejador).serve_forever()
