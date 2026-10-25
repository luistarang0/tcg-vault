# Guía de capturas · TAD 2.4 Pruebas de funcionalidad

El documento `TARANGO_TAD_T2.4 Pruebas de funcionalidad.docx` ya trae todo el texto y las
tablas con resultados reales. Te faltan **45 capturas** (recuadros amarillos `[CAPTURA …]`) y
llenar las celdas resaltadas **Completar** de la auditoría (las pruebas en los sitios de tus
compañeros, que solo tú puedes hacer).

Cada captura indica: **dónde va** (sección y número de figura), **qué preparar**, **qué hacer**
y **qué debe verse**. Están en el orden en que conviene tomarlas, para no repetir pasos.

---

## 0. Preparación (una sola vez, ~5 min)

### Cómo pegar una captura en el Word

1. Toma la captura con **Win + Shift + S** → "Recorte rectangular". Queda copiada.
2. En el Word, haz triple clic sobre el texto del recuadro amarillo para seleccionarlo y pega
   con **Ctrl + V**: la imagen reemplaza el texto. Deja el pie "Figura N…" que está debajo.
3. Si quieres quitar el fondo amarillo y el borde punteado: con el párrafo seleccionado,
   Inicio → Bordes → **Sin borde** y Sombreado → **Sin color**.

### Abrir las 4 terminales (PowerShell)

Usa el `.venv` de la **raíz** del proyecto (el de `server/` está roto, apunta a otra computadora).

**Terminal 1: backend principal (puerto 8000).** Con este arranque sirve para las tres actividades:
enforce, Turnstile que siempre rechaza (`2x…`) y login limitado a 5 por minuto.

```powershell
cd "C:\Users\luist\OneDrive\9o Semestre\TAD\RePokemon\tcg-vault"
.\.venv\Scripts\Activate.ps1
cd server
$env:SECURITY_MODE="enforce"; $env:TURNSTILE_SECRET="2x0000000000000000000000000000000AA"; $env:RATE_LIMIT_LOGIN="5/minute"
uvicorn app.main:app --port 8000
```

**Terminal 2: backend secundario (puerto 8001).** Solo para la captura C1.3, con la secreta `1x…` que siempre acepta.

```powershell
cd "C:\Users\luist\OneDrive\9o Semestre\TAD\RePokemon\tcg-vault"
.\.venv\Scripts\Activate.ps1
cd server
$env:SECURITY_MODE="enforce"; $env:TURNSTILE_SECRET="1x0000000000000000000000000000000AA"
uvicorn app.main:app --port 8001
```

**Terminal 3: frontend.**

```powershell
cd "C:\Users\luist\OneDrive\9o Semestre\TAD\RePokemon\tcg-vault\client"
npm run dev
```

**Terminal 4: scripts.** Aquí correrás todo lo demás.

```powershell
cd "C:\Users\luist\OneDrive\9o Semestre\TAD\RePokemon\tcg-vault"
.\.venv\Scripts\Activate.ps1
$env:PYTHONIOENCODING="utf-8"
```

Comprueba que `http://localhost:8000/api/health` dice `"security_mode":"enforce"` y que
`http://localhost:5173/cartas` muestra el catálogo.

### DevTools

En Edge se abren con **F12**. Pestañas que usarás: **Red (Network)**, **Elementos (Elements)**,
**Aplicación (Application)** y **Consola (Console)**. Si Edge no te deja pegar código en la
Consola, escribe `allow pasting` y presiona Enter.

---

## 1. Actividad 1 · Laboratorio de mecanismos de verificación

Todas van en la sección **Actividad 1 → Evidencias**.

### C1.1 · Figura 1 · Validación del cliente
- **Hacer:** abre `http://localhost:5173/registro`, abre F12 → Red, y pulsa **Registrarme** sin llenar nada.
- **Debe verse:** los mensajes en rojo bajo cada campo y la pestaña Red **vacía** (el formulario no envió nada).
- **Qué demuestra:** A1-17. La validación del cliente es solo comodidad; el servidor se prueba en C1.2.

### C1.2 · Figura 2 · Los 15 casos contra el servidor
- **Hacer (Terminal 4):** `python scraper_tests/06_casos_verificacion.py`
- **Debe verse:** la tabla completa de los casos 01 a 15 con sus códigos (422, 201, 409, 429, 403).
- **Qué demuestra:** A1-01 a A1-15. El script se salta el formulario y aun así el servidor rechaza cada caso inválido.

### C1.3 · Figura 3 · Caso válido con token
- **Hacer (Terminal 4):** `python scraper_tests/06_casos_verificacion.py --solo-token-valido --base http://localhost:8001`
- **Debe verse:** el caso 16 con **201**.
- **Explicación para ti:** la secreta `1x…` es una clave de prueba oficial de Cloudflare que acepta cualquier token. Sirve para mostrar el camino feliz sin resolver el reto a mano.

### C1.4 · Figura 4 · Puntajes registrados por el servidor
- **Hacer:** ve a la **Terminal 1** (uvicorn) y sube hasta las líneas `[seguridad] register_attempt {"score": …}`.
- **Debe verse:** al menos los puntajes 60 (honeypot), 70 (untrusted_events, webdriver), 45 (fast_fill, robotic_typing) y 100.
- **Alternativa:** en la Terminal 4, `Get-Content server\logs\access.jsonl -Tail 40 | Select-String register_attempt`

### C1.5 · Figura 5 · Honeypot invisible
- **Hacer:** en `/registro`, F12 → Elementos → **Ctrl + F** dentro del panel → busca `name="website"`.
  Haz clic en el `<div>` que lo contiene: en el panel **Estilos** aparece `left: -10000px`.
- **Debe verse:** el input `website` seleccionado en el árbol, con `aria-hidden="true"` y `tabindex="-1"`, y el CSS que lo saca de la pantalla.

### C1.6 · Figura 6 · Bot de Selenium ingenuo
- **Hacer (Terminal 4):** `python scraper_tests/02_bot_formulario.py --modo ingenuo`
  (sin `--headless`, para que se vea la ventana).
- **Debe verse:** la ventana de Edge del bot con el **widget de Turnstile** y, en la terminal, el
  resumen: `403 … Confirma que eres humano`, `403 … Token Turnstile inventado`, `429 … Ráfaga`.
- **Atajo:** el script guarda la ventana en `scraper_tests\evidencia\02_bot_ingenuo_desafio.png`.
  Puedes pegar esa imagen y, al lado, la captura de la terminal.

### C1.7 · Figura 7 · Registro de una persona
- **Hacer:** en `/registro`, llena el formulario a mano con un nombre sin espacios (por ejemplo
  `luis_demo`), un correo y una contraseña de 8 caracteres o más. Pulsa Registrarme.
- **Debe verse:** el perfil con el mensaje verde de bienvenida, **1,000 puntos** y las 5 cartas.
- **Importante:** **no cierres esta sesión**, la usarás en la Actividad 2.

### C1.8 · Figura 8 · Huellas de automatización
- **Hacer (Terminal 4):** `python scraper_tests/04_huellas_log.py`
- **Debe verse:** la tabla `navegador False — / script True script_ua… / selenium True headless_ua` y `navigator.webdriver … = True`.

### C1.9 · Figura 9 · DOM dinámico
- **Hacer (Terminal 4):** `python scraper_tests/03_dom_dinamico.py`
- **Debe verse:** las 3 cargas con ids distintos (`card-list-xxxxxx`), `NoSuchElementException` en By.ID y **20** en la columna `data-*`.

---

## 2. Actividad 2 · Detectives de seguridad

Todas van en **Actividad 2 → Evidencias**. Usa la sesión de `luis_demo` (C1.7).

> El login está limitado a 5 por minuto. Si ves un 429 al iniciar sesión, espera 1 minuto: es la defensa funcionando.

### C2.1 y C2.2 · Figuras 10 y 11 · Qué envía el botón "Entrar"
- **Preparar:** pulsa **Salir** en el encabezado y ve a `/entrar`. F12 → Red → filtro **Fetch/XHR** → marca **Conservar registro**.
- **Hacer:** inicia sesión con `luis_demo`. En Red haz clic en la petición **login**.
- **C2.1 (pestaña Encabezados):** baja a **Encabezados de solicitud** y deja visibles `X-Csrf-Token` y `Cookie` (con `csrf_token=…` y `sid=…`). Arriba se ve `POST` y `200`.
- **C2.2 (pestaña Carga útil/Payload):** se ven `username`, `password`, `website: ""` y el objeto `behavior` con las métricas. Si cabe, incluye la pestaña **Respuesta** (`{"ok": true}`).

### C2.3 · Figura 12 · Qué envía el botón "Pujar"
- **Hacer:** ve a `/subastas`, abre una subasta de **la casa** y limpia Red (icono 🚫). Pulsa **Pujar** y espera unos 10 segundos.
- **Debe verse:** `bid` (POST, 200) seguido de varios `GET` a la subasta cada ~5 s y `me`. Eso es el polling.

### C2.4 · Figura 13 · El contenido llega por fetch
- **Hacer:** en `/cartas` presiona **Ctrl + U** (ver código fuente): solo hay `<div id="root"></div>` y scripts, sin cartas.
  Después, en Red, abre la petición `cards?page=1…` → pestaña **Respuesta** (el JSON con las cartas).
- **Debe verse:** ambas cosas. Pega las dos imágenes en el mismo recuadro.

### C2.5 y C2.6 · Figuras 14 y 15 · IDs que cambian al recargar
- **Hacer:** en `/cartas`, F12 → Elementos → **Ctrl + Shift + C** y haz clic en el espacio entre dos cartas. Queda seleccionado `<div id="card-list-xxxxxx" class="… dyn-xxxxxx">`.
- **C2.5:** captura con ese id visible. Despliega una carta para que se vea `data-card-id`.
- **C2.6:** presiona **F5**, repite la selección y captura: **el id cambió y los data-card-id son los mismos**.

### C2.7 · Figura 16 · Cookies y sus atributos
- **Hacer:** F12 → Aplicación → Almacenamiento → Cookies → `http://localhost:5173`.
- **Debe verse:** `vault_session` (HttpOnly ✓, SameSite Lax), `csrf_token` (HttpOnly vacío, SameSite **Strict**) y `sid`.
- **Explicación para ti:** `csrf_token` no es HttpOnly **a propósito**, porque el JavaScript de la página debe leerla para copiarla al encabezado.

### C2.8 · Figura 17 · El CSRF se valida en el backend
- **Hacer:** F12 → Consola. Pega este bloque y presiona Enter:

```js
const csrf = document.cookie.match(/csrf_token=([^;]+)/)[1]
const enviar = (url, body, token) => fetch(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', ...(token ? { 'X-CSRF-Token': token } : {}) },
  body: JSON.stringify(body),
}).then(async r => [r.status, await r.json()])
const cuenta = { username: 'nadie', password: 'x' }
```

  Después ejecuta una por una:

```js
await enviar('/api/login', cuenta)            // sin token
await enviar('/api/login', cuenta, 'falso')   // token falso
await enviar('/api/login', cuenta, csrf)      // token correcto
```

- **Debe verse:** `403 … csrf_failed`, `403 … csrf_failed` y luego `401 "Usuario o contraseña incorrectos"`. El 401 significa que con el token correcto **sí llegó a la ruta**.

### C2.9 · Figura 18 · Perder la sesión
- **Hacer:** abre una subasta de la casa. En Aplicación → Cookies, clic derecho sobre `vault_session` → **Eliminar**. Sin recargar, pulsa **Pujar**.
- **Debe verse:** el mensaje "Inicia sesión para continuar." y, en Red, el `bid` con **401**.
- **Extra:** abre `/perfil`: te manda a `/entrar`.

### C2.10 · Figura 19 · Datos inválidos en el cliente y en el servidor
- **Preparar:** vuelve a iniciar sesión. Abre una subasta y fíjate en su número en la URL (por ejemplo `/subastas/8`).
- **Hacer (cliente):** escribe `1` en el campo de la puja y pulsa Pujar. Aparece "La puja mínima es X puntos" **sin** petición en Red.
- **Hacer (servidor):** en la Consola, con el bloque de C2.8 ya cargado (si recargaste, pégalo otra vez) y cambiando `8` por tu número:

```js
await enviar('/api/auctions/8/bid', { amount: 1 }, csrf)
await enviar('/api/auctions/8/bid', { amount: -5 }, csrf)
```

- **Debe verse:** `400 "La puja mínima es … puntos."` y `422 … greater than or equal to 1`. Pega la interfaz y la consola en el mismo recuadro.

---

## 3. Actividad 3 · El reto de las n solicitudes

Todas van en **Actividad 3 → Evidencias**.

### C3.1 · Figura 20 · Configuración del límite
- **Debe verse:** la Terminal 1 con el comando que incluye `$env:RATE_LIMIT_LOGIN="5/minute"` y uvicorn corriendo, más `http://localhost:8000/api/health` en el navegador con `enforce`.

### C3.2, C3.3 y C3.4 · Figuras 21, 22 y 23 · El script
- **Hacer (Terminal 4):** `python scraper_tests/05_reto_n_solicitudes.py`. Tarda ~70 s porque espera a que se reinicie la ventana.
- **C3.2:** las fases **A** (200 ×5 y luego 429 con `Retry-After=60`) y **B** (sesión nueva: 200).
- **C3.3:** la fase **C** (tras la espera: 200 ×5 y 429 de nuevo).
- **C3.4:** la fase **D** (401 ×5, luego 429 con `Retry-After=900`, incluso con la contraseña correcta) y el bloque "Registro del servidor".

### C3.5 · Figura 24 · Registro de eventos
- **Hacer (Terminal 4):** `Get-Content server\logs\access.jsonl -Tail 15`
- **Debe verse:** líneas con `"status": 429` y `"event": "login_result", "result": "locked"`.

### C3.6 · Figura 25 · El límite no depende del botón
- **Preparar:** espera 1 minuto desde la última prueba de login.
- **Hacer:** en `http://localhost:5173` (cualquier página), Consola:

```js
const csrf = document.cookie.match(/csrf_token=([^;]+)/)[1], codigos = []
for (let i = 1; i <= 7; i++) {
  const r = await fetch('/api/login', { method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify({ username: 'prueba', password: 'x' }) })
  codigos.push(`${i}: ${r.status}`)
}
codigos
```

- **Debe verse:** `1: 401 … 5: 401, 6: 429, 7: 429`. Ningún botón intervino: lo frenó el servidor.

---

## 4. Auditoría · sitios de tus compañeros

Van en **Auditoría y comparativa → (sección de cada sitio)**, cuatro por sitio (`C4.n.1` a `C4.n.4`).
Además, en la tabla de cada sitio llena las celdas **Completar** con lo que pase. Escribe el código
HTTP que veas en Red y el mensaje, por ejemplo: *"400, 'Respuesta incorrecta' y reto nuevo"*.

**Reglas:** solo lo que pide la actividad, con datos ficticios (`prueba@ejemplo.com`, `Clave1234`),
sin crear cuentas ni insistir más allá de 6 intentos. Si un sitio te bloquea, eso **es** el resultado.

### Método general para cada sitio (las 4 capturas)
1. **C4.n.1:** abre el login o registro del sitio y captura el formulario con su CAPTCHA visible.
2. **C4.n.2:** F12. Según el sitio: en **Elementos**, el honeypot o el iframe del CAPTCHA; en **Aplicación → Cookies**, el token CSRF; o en **Red**, los encabezados del POST.
3. **C4.n.3:** con Red abierta, envía una **respuesta incorrecta** al CAPTCHA (o el formulario vacío) y captura el mensaje y la petición con su código.
4. **C4.n.4:** intenta iniciar sesión **6 veces** en menos de un minuto con credenciales falsas y captura el sexto resultado (mensaje o 429 en Red).

**Valor manipulado (fila "Valor manipulado"):** para llenar un honeypot, en Elementos selecciona el
contenedor del campo oculto y, en Estilos, desmarca la regla que lo esconde (`position`, `left`,
`opacity` o `display`). El campo aparece. Escribe algo en él y envía el formulario. Anota si el
servidor lo rechaza.

### Porké · cochinita-pibil-pwa.vercel.app (C4.1.x)
- Su página **`/seguridad`** tiene botones de prueba hechos por ellos: "Prueba cada CAPTCHA", "Prueba de CSRF (Enviar 3 peticiones)" y "Prueba de rate limiting (Enviar 8 intentos de login seguidos)". Úsalos para C4.1.3 y C4.1.4. Son pruebas que el equipo dispuso para eso.
- C4.1.2: en `/login`, Elementos muestra los nombres aleatorios (`em_…`, `pa_…`) y el honeypot `url_…`. Recarga y verás que cambian.
- Fila "Token CSRF": en Red, abre el POST que dispare la prueba de CSRF y busca `X-CSRF-Token`.

### Café & Charla · cafe-charla-app.vercel.app (C4.2.x)
- `/registro` tiene CAPTCHA de texto y `/login` uno aritmético. C4.2.3: escribe una respuesta equivocada.
- C4.2.2: en Elementos, selecciona los caracteres del CAPTCHA. Si se ven como texto en el HTML, captúralo: es el hallazgo descrito en el documento. Muestra también el honeypot `hp_confirm_site`.
- Llena también la fila "Rate limiting" y "Token CSRF" de la **tabla comparativa** con lo que veas en Red al hacer login (busca encabezados `x-csrf…` o cookies con "csrf").

### SurgePath · surgepath.netlify.app (C4.3.x)
- C4.3.3: pulsa "Iniciar Sesión" **sin** marcar el reCAPTCHA.
- Valor manipulado: en la Consola, `document.getElementById('g-recaptcha-response').value = 'token-falso'` y luego pulsa Iniciar Sesión. Anota la respuesta de su API (`surgepath-api-backend.onrender.com`) en Red.
- C4.3.4: el reCAPTCHA probablemente te obligue a resolverlo cada vez; anota hasta dónde llegaste.
- Fila "Autenticación": en DevTools → Fuentes → `api.js` se ve `Authorization: Bearer` y `localStorage.sp_token`.
- La API está en Render: la primera petición puede tardar ~1 min en despertar.

### TicketShield · ticketshield-ihy6.onrender.com (C4.4.x)
- La primera visita puede tardar o dar 503 (Render despertando): espera y recarga.
- C4.4.2: Aplicación → Cookies muestra `XSRF-TOKEN`; en Elementos, `<meta name="csrf-token">` dentro de `<head>`.
- Valor manipulado (POST sin token CSRF), en la Consola del sitio:
  ```js
  fetch('/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    body: JSON.stringify({ email: 'prueba@ejemplo.com', password: 'Clave1234' }) }).then(r => r.status)
  ```
  Lo esperado en Laravel es **419**.
- C4.4.3: envía el login sin resolver el reCAPTCHA.

### Clara · clara-mis-finanzas.vercel.app (C4.5.x)
- C4.5.3: responde mal la suma.
- C4.5.4: el sitio anuncia 5 intentos por IP cada 10 minutos, así que el sexto debería bloquearte. **Después tu IP quedará bloqueada ~10 min en ese sitio**: haz esta prueba al final.
- Honeypot: campo "Sitio web", con el método de "Valor manipulado".

---

## 5. Antes de entregar

1. Busca en el Word (**Ctrl + B**) la palabra **Completar**: no debe quedar ninguna, ni en las tablas de cada sitio ni en la tabla comparativa. Quita el resaltado amarillo.
2. Si algún resultado real difiere de lo esperado, **déjalo así**: es un hallazgo. Puedes agregar una frase en el párrafo de clasificación del sitio.
3. Actualiza el índice: clic derecho sobre él → **Actualizar campo** → **Actualizar toda la tabla**.
4. Revisa que los 45 recuadros tengan imagen.
5. Exporta a PDF si lo pide la entrega (Archivo → Exportar → PDF).
