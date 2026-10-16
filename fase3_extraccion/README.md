# Fase 3: extracción, procesamiento y almacenamiento de datos oficiales

Bot de Selenium que navega un portal de datos abiertos **CKAN** (por defecto
`https://datos.gob.mx/busca`), busca, filtra, pagina, visita fichas de detalle y
guarda los datos crudos; después `limpieza.py` los estructura con Pandas.

| Archivo | Qué hace |
|---|---|
| `config.py` | Portal, término, filtro, límites de páginas/fichas y pausas |
| `bot_portal.py` | Bot de Selenium (búsqueda, filtro, paginación, detalle) |
| `limpieza.py` | Limpieza con Pandas: nulos, texto, fechas, duplicados, formatos |
| `simulador_ckan.py` | Portal CKAN falso en `localhost` para probar sin internet |
| `datos/` | Salidas: `crudos_*.json/.csv` y `datasets_limpios.csv/.xlsx` |
| `capturas/` | Capturas automáticas de cada paso (evidencia) |

## Instalación (Windows, PowerShell)

Necesitas Google Chrome instalado. El driver lo descarga Selenium solo.

```powershell
cd fase3_extraccion
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Ejecución

```powershell
# 1) Extraer (se abre Chrome y verás al bot trabajar)
python bot_portal.py

# Otras búsquedas
python bot_portal.py --termino "educacion" --paginas 2 --detalles 10
python bot_portal.py --filtro-param organization --filtro-valor imss

# 2) Limpiar y ver la tabla procesada
python limpieza.py
```

Si el portal muestra un CAPTCHA o una pantalla de verificación, el bot se
detiene y te pide resolverlo en la ventana de Chrome; luego presionas Enter.
Con `--headless` no hay ventana, así que ante un desafío se detiene y guarda lo
obtenido.

## Probar sin internet (simulador)

```powershell
# Terminal 1
python simulador_ckan.py --desafio
# Terminal 2
python bot_portal.py --base-url http://localhost:5050/busca
```

El simulador usa datos **ficticios** y el mismo HTML de CKAN 2.10. Con
`--desafio` muestra una vez una verificación en la página 2 para practicar la
intervención humana.

## Reglas de uso responsable

- Revisa `robots.txt` antes de navegar y respeta `Disallow` y `Crawl-delay`.
- Pausas aleatorias de 2 a 5 s entre páginas; máximo 3 páginas y 30 fichas por defecto.
- User-Agent identificable (`TCGVaultEduBot/0.1`).
- No resuelve ni evade CAPTCHA: pide intervención humana.
- No oculta que es un navegador automatizado.
- Si el portal ofrece API (`/api/3/action/package_search`), para uso real es preferible la API.
