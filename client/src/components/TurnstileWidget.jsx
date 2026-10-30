import { useEffect, useRef } from 'react'

// Script oficial de Cloudflare Turnstile. Se carga una sola vez y solo cuando
// el servidor exige el desafío (así la página normal no depende de Cloudflare).
const SCRIPT_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
let scriptPromise = null

function loadTurnstile() {
  if (window.turnstile) return Promise.resolve(window.turnstile)
  if (!scriptPromise) {
    scriptPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script')
      s.src = SCRIPT_URL
      s.async = true
      s.onload = () => resolve(window.turnstile)
      s.onerror = () => { scriptPromise = null; reject(new Error('No se pudo cargar Turnstile')) }
      document.head.appendChild(s)
    })
  }
  return scriptPromise
}

/**
 * Defensa 4 (lado del cliente): muestra el widget de Cloudflare Turnstile.
 * Cuando la persona lo supera, entrega un token con onToken(token).
 * El token NO se valida aquí: lo valida el servidor con la clave secreta.
 *
 * Props:
 *  - sitekey  clave pública (la manda el servidor en la respuesta 403)
 *  - onToken  callback con el token, o null si expira o falla
 *  - onError  callback con un mensaje si el script no carga, Cloudflare devuelve un
 *             error o el reto no se completa a tiempo (así el usuario no ve un recuadro vacío)
 */
const ESPERA_MS = 25000

/** Mensaje legible para los códigos de error de Turnstile (documentación de Cloudflare). */
function mensajeError(codigo) {
  const c = String(codigo || '')
  if (c.startsWith('1102')) return `Este dominio no está autorizado en el widget de Cloudflare (código ${c}).`
  if (c.startsWith('1101')) return `La clave pública de Turnstile no es válida (código ${c}).`
  if (c.startsWith('3') || c.startsWith('6')) {
    return `Cloudflare no pudo verificar este navegador (código ${c}). Si usas un navegador automatizado, `
      + 'el reto no se completará; en uno normal, recarga e inténtalo de nuevo.'
  }
  return `No se pudo completar la verificación de seguridad (código ${c || 'desconocido'}).`
}

export default function TurnstileWidget({ sitekey, onToken, onError }) {
  const box = useRef(null)

  useEffect(() => {
    let widgetId = null
    let cancelled = false
    let resuelto = false
    // Si en ESPERA_MS no hubo token ni error, se avisa en lugar de dejar el recuadro en blanco
    const reloj = setTimeout(() => {
      if (!resuelto && !cancelled) onError?.('La verificación de seguridad no se completó. Recarga la página e inténtalo de nuevo.')
    }, ESPERA_MS)
    loadTurnstile()
      .then((ts) => {
        if (cancelled || !box.current) return
        widgetId = ts.render(box.current, {
          sitekey,
          language: 'es',
          callback: (token) => { resuelto = true; onToken(token) },
          'expired-callback': () => onToken(null),
          'error-callback': (codigo) => {
            resuelto = true
            onToken(null)
            onError?.(mensajeError(codigo))
            return true                       // indica a Turnstile que el error ya se manejó
          },
          'unsupported-callback': () => { resuelto = true; onError?.('Este navegador no es compatible con la verificación de Cloudflare.') },
        })
      })
      .catch((e) => { resuelto = true; onError?.(e.message) })
    return () => {
      cancelled = true
      clearTimeout(reloj)
      if (widgetId !== null && window.turnstile) window.turnstile.remove(widgetId)
    }
  }, [sitekey]) // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={box} data-testid="turnstile" />
}
