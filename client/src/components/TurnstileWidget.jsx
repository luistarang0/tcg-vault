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
 *  - onError  callback si no se pudo cargar el script
 */
export default function TurnstileWidget({ sitekey, onToken, onError }) {
  const box = useRef(null)

  useEffect(() => {
    let widgetId = null
    let cancelled = false
    loadTurnstile()
      .then((ts) => {
        if (cancelled || !box.current) return
        widgetId = ts.render(box.current, {
          sitekey,
          language: 'es',
          callback: (token) => onToken(token),
          'expired-callback': () => onToken(null),
          'error-callback': () => onToken(null),
        })
      })
      .catch((e) => onError?.(e.message))
    return () => {
      cancelled = true
      if (widgetId !== null && window.turnstile) window.turnstile.remove(widgetId)
    }
  }, [sitekey]) // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={box} data-testid="turnstile" />
}
