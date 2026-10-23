"""
Bot que intenta enviar el formulario local /registro, para demostrar cómo el
servidor lo detecta y lo bloquea por capas (Revisión 2).

Modos:
  ingenuo    Llena TODOS los inputs al instante (incluido el honeypot oculto, que
             rellena con JavaScript porque no es visible) y envía.
             Esperado en enforce: 403 + desafío Turnstile (puntaje ≥ 80).
             Después "dice" que pasó el CAPTCHA mandando un token inventado
             -> 403 (el servidor lo valida con Cloudflare y no es válido).
             Por último insiste en ráfaga -> 429 del limitador.
             Con --resolver-humano se pausa para que una PERSONA resuelva el
             CAPTCHA en la ventana; entonces el envío sí pasa (201).
  cuidadoso  Mueve el mouse, escribe letra por letra con pausas variables y no toca
             campos ocultos. Solo lo delata navigator.webdriver (+30).
             Esperado en enforce: 201, pero queda registrado como sospechoso.
             Con --headless se suma "HeadlessChrome" (+30) -> 429.

Al final imprime una tabla de resultados y los eventos de seguridad que el
servidor escribió en server/logs/access.jsonl (puntaje y señales).

Requisitos: backend en SECURITY_MODE=enforce y frontend corriendo.
Uso:
    python scraper_tests/02_bot_formulario.py --modo ingenuo
    python scraper_tests/02_bot_formulario.py --modo cuidadoso
"""
from __future__ import annotations

import argparse
import json
import random
import time

from selenium.common.exceptions import ElementNotInteractableException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from selenium_comun import EVIDENCIA, LOG_SERVIDOR, crear_driver, solo_localhost

# El registro ahora crea cuentas reales y rechaza nombres/correos repetidos (409):
# se agrega un sufijo por ejecución para poder correr el script varias veces.
RUN = time.strftime("%H%M%S")
DATOS = {"collector_name": f"BotColeccionista{RUN}", "email": f"bot{RUN}@ejemplo.mx",
         "password": "contrasena123", "website": "https://spam.example"}

# Establece el valor de un input controlado por React y dispara el evento "input".
# Es lo que hace un bot que no puede escribir en un campo oculto. El evento
# creado así tiene isTrusted = false (lo detecta useBehaviorTracker).
JS_SET_VALUE = """
const el = arguments[0], value = arguments[1];
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
setter.call(el, value);
el.dispatchEvent(new Event('input', { bubbles: true }));
"""

# Envía el formulario directamente a la API desde la página (con la cookie de sesión)
JS_FETCH = """
const done = arguments[arguments.length - 1];
fetch('/api/register', {method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(arguments[0])})
  .then(async r => done([r.status, await r.text()]))
  .catch(e => done([0, String(e)]));
"""


class BotFormulario:
    def __init__(self, a):
        self.a = a
        self.d = crear_driver(a.headless, a.chrome_bin, a.driver, a.navegador)
        self.w = WebDriverWait(self.d, 15)
        self.resultados: list[tuple[str, str, str]] = []
        self.inicio_log = LOG_SERVIDOR.stat().st_size if LOG_SERVIDOR.exists() else 0
        EVIDENCIA.mkdir(exist_ok=True)

    def anotar(self, paso: str, codigo: str, detalle: str) -> None:
        self.resultados.append((paso, codigo, detalle))
        print(f"  {paso:<38} {codigo:<6} {detalle}")

    def abrir_formulario(self) -> None:
        self.d.get(self.a.url)
        self.w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "form input[name='collector_name']")))

    def leer_estado(self, anterior: str | None = None) -> str:
        """Espera el mensaje de resultado del formulario (role=status).
        Si el registro tiene éxito la SPA redirige a /perfil y el formulario desaparece."""
        def nuevo(d):
            if d.current_url.rstrip("/").endswith("/perfil"):
                return "Cuenta creada (redirigido a /perfil)"
            els = d.find_elements(By.CSS_SELECTOR, "form [role='status']")
            return els and els[0].text and els[0].text != anterior and els[0].text
        try:
            return self.w.until(nuevo)
        except TimeoutException:
            return "(sin respuesta visible)"

    # ------------------------------------------------------------- ingenuo
    def ingenuo(self) -> None:
        print("\n[Modo ingenuo] llena todos los campos al instante y envía")
        self.abrir_formulario()
        for el in self.d.find_elements(By.CSS_SELECTOR, "form input"):
            nombre = el.get_attribute("name")
            valor = DATOS.get(nombre, "x")
            try:
                el.send_keys(valor)                     # campos visibles
            except ElementNotInteractableException:
                self.d.execute_script(JS_SET_VALUE, el, valor)   # honeypot oculto
                print(f"  (campo oculto '{nombre}' rellenado con JavaScript)")
        self.d.find_element(By.CSS_SELECTOR, "form button[type='submit']").click()
        estado = self.leer_estado()
        reto = bool(self.d.find_elements(By.CSS_SELECTOR, "[data-testid='turnstile']"))
        self.d.save_screenshot(str(EVIDENCIA / "02_bot_ingenuo_desafio.png"))
        self.anotar("1. Envío por el formulario", "403" if reto else "?", estado[:70])
        if reto:
            boton = self.d.find_element(By.CSS_SELECTOR, "form button[type='submit']")
            print(f"  El botón quedó: '{boton.text}' (habilitado={boton.is_enabled()})")

        if reto and self.a.resolver_humano:
            # Intervención humana: el bot NO resuelve el CAPTCHA; lo hace una persona
            print("\n  >> Resuelve la verificación en la ventana de Chrome y presiona Enter aquí.")
            input("  > ")
            boton = self.d.find_element(By.CSS_SELECTOR, "form button[type='submit']")
            if boton.is_enabled():
                anterior = estado
                boton.click()
                estado = self.leer_estado(anterior)
                self.d.save_screenshot(str(EVIDENCIA / "02_bot_ingenuo_humano_resolvio.png"))
                codigo = "201" if "Cuenta creada" in estado else "403"
                self.anotar("1b. Persona resuelve el CAPTCHA", codigo, estado[:70])
            else:
                self.anotar("1b. Persona resuelve el CAPTCHA", "—", "el widget no entregó token")

        # El bot no puede resolver el CAPTCHA, así que intenta engañar al servidor
        cuerpo = {k: v for k, v in DATOS.items()}
        cuerpo["behavior"] = {"fillTimeMs": 200, "keyCount": 0, "mouseMoves": 0,
                              "totalEvents": 1, "trustedEvents": 0, "webdriver": True}
        cuerpo["turnstile_token"] = "token-inventado-por-el-bot"
        status, texto = self.d.execute_async_script(JS_FETCH, cuerpo)
        self.anotar("2. Token Turnstile inventado", str(status), json.loads(texto).get("error", texto)[:70])

        # Ráfaga: el limitador corta por volumen sin importar el puntaje
        codigos = []
        for _ in range(self.a.rafaga):
            status, _ = self.d.execute_async_script(JS_FETCH, cuerpo)
            codigos.append(status)
        resumen = ", ".join(f"{c}×{codigos.count(c)}" for c in sorted(set(codigos)))
        self.anotar(f"3. Ráfaga de {self.a.rafaga} envíos", "429" if 429 in codigos else "?", resumen)

    # ------------------------------------------------------------ cuidadoso
    def cuidadoso(self) -> None:
        print("\n[Modo cuidadoso] mouse, tecleo con pausas y sin tocar campos ocultos")
        for intento in range(1, self.a.intentos + 1):
            self.abrir_formulario()
            acciones = ActionChains(self.d)
            for nombre in ("collector_name", "email", "password"):
                el = self.d.find_element(By.NAME, nombre)
                if not el.is_displayed():
                    continue
                acciones.move_to_element_with_offset(el, random.randint(-20, 20), 0).pause(0.3).click().perform()
                valor = DATOS[nombre]
                if nombre == "collector_name":
                    valor += str(intento)
                elif nombre == "email":
                    valor = valor.replace("@", f"{intento}@")   # un correo distinto por intento
                for letra in valor:
                    el.send_keys(letra)
                    time.sleep(random.uniform(0.06, 0.22))
                time.sleep(random.uniform(0.3, 0.8))
            boton = self.d.find_element(By.CSS_SELECTOR, "form button[type='submit']")
            acciones.move_to_element(boton).pause(0.4).click().perform()
            estado = self.leer_estado()
            if intento == 1:
                self.d.save_screenshot(str(EVIDENCIA / "02_bot_cuidadoso.png"))
            codigo = "201" if "Cuenta creada" in estado else ("429" if "Demasiad" in estado or "Espera" in estado
                                                        else "403" if "humano" in estado else "?")
            self.anotar(f"Intento {intento}", codigo, estado[:70])

    # ------------------------------------------------------------- informe
    def eventos_servidor(self) -> None:
        if not LOG_SERVIDOR.exists():
            print("\n(No se encontró server/logs/access.jsonl: ¿el backend está en observe/enforce?)")
            return
        with LOG_SERVIDOR.open(encoding="utf-8") as f:
            f.seek(self.inicio_log)
            lineas = [json.loads(l) for l in f if l.strip()]
        eventos = [e for e in lineas if e.get("type") == "event"]
        peticiones = [e for e in lineas if e.get("type") == "request" and e.get("path") == "/api/register"]
        print("\nEventos de seguridad registrados por el servidor (repetidos se agrupan):")
        textos = []
        for e in eventos:
            if e["event"] == "register_attempt":
                textos.append(f"puntaje={e['score']:>3}  acción={e['action']:<9}  "
                              f"señales={', '.join(e['flags']) or '—'}")
            else:
                textos.append(f"{e['event']}: success={e.get('success')} errores={e.get('errors')}")
        vistos: dict[str, int] = {}
        for t in textos:
            vistos[t] = vistos.get(t, 0) + 1
        for t, n in vistos.items():
            print(f"  {t}" + (f"   (×{n})" if n > 1 else ""))
        if peticiones:
            p = peticiones[0]
            print(f"\nHuellas en la petición: UA='{(p.get('user_agent') or '')[:70]}...'")
            print(f"  flags={p.get('flags')}  automation_suspected={p.get('automation_suspected')}")

    def ejecutar(self) -> None:
        try:
            print(f"Navegador: {self.d.capabilities.get('browserName')} "
                  f"{self.d.capabilities.get('browserVersion')} ({self.d.origen_driver})")
            print(f"navigator.webdriver = {self.d.execute_script('return navigator.webdriver')}")
            self.ingenuo() if self.a.modo == "ingenuo" else self.cuidadoso()
        finally:
            if not self.a.headless:
                time.sleep(2)
            self.d.quit()
        print("\nResumen:")
        for paso, codigo, detalle in self.resultados:
            print(f"  {codigo:<5} {paso:<38} {detalle}")
        time.sleep(0.5)
        self.eventos_servidor()
        print(f"\nCapturas en {EVIDENCIA}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["ingenuo", "cuidadoso"], default="ingenuo")
    ap.add_argument("--url", default="http://localhost:5173/registro")
    ap.add_argument("--intentos", type=int, default=2, help="envíos en modo cuidadoso")
    ap.add_argument("--rafaga", type=int, default=12, help="envíos rápidos al final del modo ingenuo")
    ap.add_argument("--resolver-humano", action="store_true",
                    help="modo ingenuo: pausa para que una persona resuelva el CAPTCHA y reenvía")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--chrome-bin")
    ap.add_argument("--driver")
    ap.add_argument("--navegador", choices=["auto", "chrome", "edge"], default="auto")
    a = ap.parse_args()
    solo_localhost(a.url)
    BotFormulario(a).ejecutar()


if __name__ == "__main__":
    main()
