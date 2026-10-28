"""
Configuración del extractor (TAD 2.4).

Solo se extraen los sitios que la auditoría clasificó como de extracción VIABLE:
catálogos públicos, sin login y sin datos personales. SurgePath (salud) y Clara
(finanzas) quedan fuera a propósito.

Reglas de uso responsable que el código respeta:
  * Solo hosts de esta lista (ALLOWED_HOSTS); cualquier otro se rechaza.
  * Se consulta robots.txt antes de cada sitio y se respetan sus Disallow.
  * Pausa entre páginas (PAUSA_S) y límites de páginas y fichas por sitio.
  * No se inicia sesión, no se envían formularios y no se evade ninguna defensa:
    el navegador se identifica como automatizado (navigator.webdriver = true).
  * No se guardan teléfonos, nombres de personas ni contenido de usuarios.
"""
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
DATOS = CARPETA / "datos"
CAPTURAS = CARPETA / "capturas"

PAUSA_S = 1.5            # segundos entre páginas del mismo sitio (cortesía)
ESPERA_S = 25            # tiempo máximo de las esperas explícitas
REINTENTOS = 3           # intentos por página antes de registrarla como error

SITIOS = {
    "porke": {
        "nombre": "Porké",
        "base": "https://cochinita-pibil-pwa.vercel.app",
        "tecnologia": "Next.js en Vercel",
        "clasificacion": "Dinámica (alto)",
        "max_fichas": 50,            # fichas de producto a visitar (el menú tiene ~22)
    },
    "cafe": {
        "nombre": "Café & Charla",
        "base": "https://cafe-charla-app.vercel.app",
        "tecnologia": "Next.js en Vercel",
        "clasificacion": "Estática/dinámica (medio)",
    },
    "ticketshield": {
        "nombre": "TicketShield / MyTicket",
        "base": "https://ticketshield-ihy6.onrender.com",
        "tecnologia": "Laravel + Inertia en Render (Cloudflare)",
        "clasificacion": "CDN/WAF + dinámica",
        "max_paginas": 25,           # 12 eventos por página (~22 páginas)
        "max_fichas": 100,           # fichas con tipos de boleto y fecha completa (de ~260)
    },
    "tcgvault": {
        "nombre": "TCG Vault (sitio propio)",
        "base": "https://tcg-vault-eight.vercel.app",
        "tecnologia": "React + FastAPI en Vercel",
        "clasificacion": "Dinámica (5 defensas)",
        "max_paginas": 50,           # 20 cartas por página (~42 páginas)
    },
}

ALLOWED_HOSTS = {s["base"].split("://", 1)[1] for s in SITIOS.values()}
