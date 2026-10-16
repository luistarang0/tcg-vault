# Auditoría de mecanismos anti-bot en sitios reales (Fase 2) · BORRADOR

## Metodología

1. `python auditoria/auditar_sitios.py --archivo auditoria/sitios.txt --selenium`
   revisa cada sitio con muy pocas peticiones: `robots.txt`, una visita con
   User-Agent de navegador, una con el User-Agent por defecto de `python-requests`
   y una visita con Selenium.
2. Se revisa a mano con las DevTools del navegador (pestaña Red y Aplicación):
   cookies, encabezados de respuesta y scripts de terceros.
3. Cada barrera se clasifica:

| Tipo | Qué es | Cómo se detecta |
|---|---|---|
| **Estática** | Regla visible en la respuesta HTTP, sin ejecutar JavaScript | `robots.txt` (Disallow, Crawl-delay), bloqueo por User-Agent, encabezados `X-RateLimit-*`/`Retry-After`, honeypots y tokens CSRF en el HTML |
| **Dinámica** | Necesita JavaScript o interacción | Contenido pintado con JS (SPA), CAPTCHA (reCAPTCHA, hCaptcha, Turnstile), scripts de huella digital, `navigator.webdriver` |
| **CDN / WAF** | Infraestructura que filtra antes de llegar al sitio | Encabezados y cookies de Cloudflare (`cf-ray`, `__cf_bm`), Akamai (`_abck`, `bm_sz`), Imperva (`incap_ses`), AWS (`x-amz-cf-id`), etc. |

## Tabla comparativa

> Completar con los 3 sitios asignados. Las columnas automáticas se copian de
> `auditoria/resultados/auditoria_<fecha>.md`; las de observación son manuales.

| Criterio | Sitio 1 | Sitio 2 | Sitio 3 |
|---|---|---|---|
| URL | | | |
| Código HTTP (navegador) | | | |
| CDN / WAF detectado | | | |
| `robots.txt` (reglas, Crawl-delay) | | | |
| Respuesta a `python-requests` | | | |
| Encabezados de rate limit | | | |
| ¿Contenido requiere JavaScript? | | | |
| CAPTCHA / desafío visible | | | |
| Desafío al abrir con Selenium | | | |
| Honeypot / token CSRF en formularios | | | |
| Scripts de huella digital | | | |
| **Clasificación** (Estática / Dinámica / CDN-WAF) | | | |
| Observaciones manuales | | | |

## Comparación con TCG Vault (sitio propio)

| Barrera | TCG Vault | Tipo |
|---|---|---|
| Rate limiting 429 + Retry-After (IP+sesión y solo IP) | Sí | Estática |
| Log de huellas (UA headless, Accept-Language, Sec-CH-UA) | Sí | Estática |
| Honeypot en el formulario | Sí | Estática |
| Métricas de interacción + puntaje de riesgo | Sí | Dinámica |
| CAPTCHA Turnstile validado en servidor | Sí | Dinámica |
| Contenido por fetch (SPA) | Sí | Dinámica |
| CDN / WAF | No (localhost) | — |
