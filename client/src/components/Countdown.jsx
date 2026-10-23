import useNow from '../hooks/useNow.js'

/** "2 d 4 h", "1 h 05 min", "4:07" o "Terminada". */
export function formatRemaining(ms) {
  if (ms <= 0) return 'Terminada'
  const s = Math.floor(ms / 1000)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (d > 0) return `${d} d ${h} h`
  if (h > 0) return `${h} h ${String(m).padStart(2, '0')} min`
  return `${m}:${String(sec).padStart(2, '0')}`
}

/**
 * Tiempo restante de una subasta. data-ends-at conserva la hora exacta (ISO)
 * como contrato estable para quien quiera leerla sin interpretar el texto.
 */
export default function Countdown({ endsAt, offsetMs = 0, className }) {
  const now = useNow(1000, offsetMs)
  const left = new Date(endsAt).getTime() - now
  return (
    <span className={className} data-ends-at={endsAt} data-urgent={left > 0 && left < 120000}>
      {formatRemaining(left)}
    </span>
  )
}
