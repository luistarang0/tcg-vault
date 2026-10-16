import { useCallback, useEffect, useRef } from 'react'

/**
 * Defensa 3 (lado del cliente): recopila métricas de interacción mientras una
 * persona llena el formulario. El cliente SOLO informa; quien decide es el
 * servidor (server/app/security/risk.py), porque un bot puede mentir aquí.
 *
 * Métricas que devuelve snapshot():
 *  - fillTimeMs          tiempo desde la primera interacción hasta el envío
 *  - fieldTimesMs        tiempo con el foco en cada campo { nombre: ms }
 *  - keyCount            pulsaciones de tecla
 *  - keyIntervalMeanMs   promedio entre pulsaciones
 *  - keyIntervalStdMs    desviación estándar entre pulsaciones (≈0 = ritmo robótico)
 *  - mouseMoves          eventos mousemove en la página
 *  - totalEvents         eventos observados (teclas, mouse, clics, foco, input)
 *  - trustedEvents       de ellos, cuántos generó el usuario (event.isTrusted === true).
 *                        Los eventos creados por JavaScript (dispatchEvent) son false.
 *  - webdriver           navigator.webdriver (true en navegadores automatizados)
 *  - pluginsLength       navigator.plugins.length
 *  - languagesLength     navigator.languages.length
 *
 * Uso:
 *   const tracker = useBehaviorTracker()
 *   <form {...tracker.handlers}> ... </form>
 *   postRegister({ ...form, behavior: tracker.snapshot() })
 */
export default function useBehaviorTracker() {
  const m = useRef(null)

  const reset = useCallback(() => {
    m.current = {
      firstInteraction: null,   // performance.now() del primer evento
      keyTimes: [],             // marcas de tiempo de cada keydown
      mouseMoves: 0,
      totalEvents: 0,
      trustedEvents: 0,
      fieldTimes: {},           // acumulado por campo
      focusField: null,
      focusStart: 0,
    }
  }, [])

  if (m.current === null) reset()

  // Cuenta un evento y si fue generado por una persona (isTrusted)
  const count = useCallback((e) => {
    const s = m.current
    const native = e.nativeEvent || e
    s.totalEvents += 1
    if (native.isTrusted) s.trustedEvents += 1
    if (s.firstInteraction === null && native.type !== 'mousemove') s.firstInteraction = performance.now()
  }, [])

  // mousemove se escucha en toda la ventana (no solo sobre el formulario)
  useEffect(() => {
    const onMove = (e) => {
      m.current.mouseMoves += 1
      count(e)
    }
    window.addEventListener('mousemove', onMove, { passive: true })
    return () => window.removeEventListener('mousemove', onMove)
  }, [count])

  const closeFocus = () => {
    const s = m.current
    if (s.focusField) {
      s.fieldTimes[s.focusField] = (s.fieldTimes[s.focusField] || 0) + (performance.now() - s.focusStart)
      s.focusField = null
    }
  }

  // Manejadores para esparcir en el <form>. Los eventos de los inputs "burbujean" hasta aquí.
  const handlers = {
    onKeyDown: (e) => {
      count(e)
      m.current.keyTimes.push(performance.now())
    },
    onFocus: (e) => {
      count(e)
      closeFocus()
      m.current.focusField = e.target.name || e.target.tagName
      m.current.focusStart = performance.now()
    },
    onBlur: () => closeFocus(),
    onInput: (e) => count(e),
    onClick: (e) => count(e),
    onPaste: (e) => count(e),
  }

  /** Calcula el resumen que se envía al servidor junto con el formulario. */
  const snapshot = useCallback(() => {
    closeFocus()
    const s = m.current
    const now = performance.now()
    const intervals = s.keyTimes.slice(1).map((t, i) => t - s.keyTimes[i])
    const mean = intervals.length ? intervals.reduce((a, b) => a + b, 0) / intervals.length : 0
    const std = intervals.length
      ? Math.sqrt(intervals.reduce((a, b) => a + (b - mean) ** 2, 0) / intervals.length)
      : 0
    const round = (x) => Math.round(x)
    return {
      fillTimeMs: s.firstInteraction === null ? 0 : round(now - s.firstInteraction),
      fieldTimesMs: Object.fromEntries(Object.entries(s.fieldTimes).map(([k, v]) => [k, round(v)])),
      keyCount: s.keyTimes.length,
      keyIntervalMeanMs: round(mean),
      keyIntervalStdMs: round(std),
      mouseMoves: s.mouseMoves,
      totalEvents: s.totalEvents,
      trustedEvents: s.trustedEvents,
      webdriver: navigator.webdriver === true,
      pluginsLength: navigator.plugins?.length ?? 0,
      languagesLength: navigator.languages?.length ?? 0,
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return { handlers, snapshot, reset }
}
