# Duelo HTTP vs Selenium vs API

| Fuente | Método | Registros | Campos faltantes | Tiempo (s) | Observación |
|---|---|---|---|---|---|
| World Bank | HTTP + BeautifulSoup | 0 | n/a | 2.18 | El HTML inicial no trae la tabla: la dibuja JavaScript |
| World Bank | Selenium + WebDriverWait | 247 | 0 | 18.06 | Con arranque del navegador: 19.32 s. Valores redondeados (unidad: Thousands). Incluye 30 agregados regionales |
| World Bank | API oficial v2 | 217 | 0 | 1.35 | Valores exactos; incluye la consulta de países para quitar agregados |
| catalog.data.gov | HTTP + BeautifulSoup | 20 | 0 | 1.39 | El HTML ya contiene los resultados |
| catalog.data.gov | Selenium + WebDriverWait | 20 | 0 | 4.34 | Con arranque del navegador: 5.61 s. 20 títulos iguales a los del HTML |
| catalog.data.gov | API oficial (GET /search) | 20 | 0 | 0.18 | JSON documentado. 20 títulos iguales a los del HTML; se omiten los contactos personales |

Consistencia de Selenium contra la API: {'coinciden_margen_0.5pct': 217, 'comparados': 217, 'agregados_regionales_solo_en_selenium': 30, 'paises_solo_en_selenium': [], 'paises_solo_en_api': []}
