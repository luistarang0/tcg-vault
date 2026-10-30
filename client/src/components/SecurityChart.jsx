import { useEffect, useMemo, useRef, useState } from 'react'
import styles from '../pages/Admin.module.css'

// Orden fijo (de abajo hacia arriba y en la leyenda): el color sigue a la serie, nunca a su posición
export const SERIES = [
  { key: 'otros', label: 'Otros eventos', color: 'var(--s-otros)' },
  { key: 'limite', label: 'Límite superado (429)', color: 'var(--s-limite)' },
  { key: 'csrf', label: 'CSRF inválido', color: 'var(--s-csrf)' },
  { key: 'riesgo', label: 'Riesgo alto (frenado/desafío)', color: 'var(--s-riesgo)' },
]
const H = 220
const M = { top: 10, right: 8, bottom: 24, left: 38 }
const GAP = 2                                   // separación entre segmentos apilados
const fmt = (n) => n.toLocaleString('es-MX')

const pad = (n) => String(n).padStart(2, '0')
/** Fecha local -> 'YYYY-MM-DDTHH:MM:SS' (mismo formato que manda el servidor para cada intervalo). */
const claveLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00:00`

/** Todos los intervalos del rango, también los que no tienen eventos. */
function intervalos(desde, hasta, paso) {
  const d = new Date(desde)
  if (paso === 'hour') d.setMinutes(0, 0, 0)
  else {
    d.setHours(0, 0, 0, 0)
    if (paso === 'week') d.setDate(d.getDate() - ((d.getDay() + 6) % 7))   // lunes, como date_trunc
  }
  const fin = new Date(hasta)
  const out = []
  while (d < fin && out.length < 400) {
    out.push(new Date(d))
    if (paso === 'hour') d.setHours(d.getHours() + 1)
    else d.setDate(d.getDate() + (paso === 'week' ? 7 : 1))
  }
  return out
}

function etiqueta(d, paso, variosDias) {
  const dia = d.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' })
  if (paso === 'hour') return variosDias ? `${dia} ${pad(d.getHours())}h` : `${pad(d.getHours())}:00`
  return paso === 'week' ? `sem. ${dia}` : dia
}

function techo(n) {                             // máximo del eje: 4 intervalos de tamaño "redondo"
  if (n <= 4) return 4
  const crudo = n / 4
  const p = 10 ** Math.floor(Math.log10(crudo))
  return [1, 2, 5, 10].map((m) => m * p).find((v) => v >= crudo) * 4
}

/** Barra apilada: rectángulos y, arriba, un path con las esquinas superiores redondeadas (4 px). */
function Segmento({ x, y, w, h, color, arriba }) {
  if (h <= 0) return null
  if (!arriba) return <rect x={x} y={y} width={w} height={h} fill={color} />
  const r = Math.min(4, w / 2, h)
  return <path d={`M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`} fill={color} />
}

/**
 * Eventos de seguridad en el tiempo, apilados por tipo.
 * props: serie [{bucket, otros, limite, csrf, riesgo}], rango {desde, hasta, paso}
 */
export default function SecurityChart({ serie, rango }) {
  const box = useRef(null)
  const [ancho, setAncho] = useState(720)
  const [activo, setActivo] = useState(null)
  const [tabla, setTabla] = useState(false)

  useEffect(() => {
    if (!box.current) return
    const ro = new ResizeObserver(([e]) => setAncho(Math.max(280, e.contentRect.width)))
    ro.observe(box.current)
    return () => ro.disconnect()
  }, [tabla])

  const datos = useMemo(() => {
    const porClave = Object.fromEntries(serie.map((s) => [s.bucket.slice(0, 19), s]))
    return intervalos(rango.desde, rango.hasta, rango.paso).map((d) => {
      const s = porClave[claveLocal(d)] || {}
      const fila = { fecha: d }
      let total = 0
      for (const { key } of SERIES) { fila[key] = s[key] || 0; total += fila[key] }
      fila.total = total
      return fila
    })
  }, [serie, rango])

  const variosDias = datos.length > 1 && datos[0].fecha.toDateString() !== datos[datos.length - 1].fecha.toDateString()
  const max = techo(Math.max(0, ...datos.map((d) => d.total)))
  const plotW = ancho - M.left - M.right
  const plotH = H - M.top - M.bottom
  const banda = plotW / Math.max(1, datos.length)
  const barW = Math.max(2, Math.min(28, banda * 0.7))
  const y = (v) => (v / max) * plotH
  const cadaEtiqueta = Math.max(1, Math.ceil(datos.length / Math.max(2, Math.floor(plotW / 70))))
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(max * f))

  const leyenda = (
    <div className={styles.legend}>
      {SERIES.map((s) => (
        <span key={s.key}><i className={styles.swatch} style={{ background: s.color }} />{s.label}</span>
      ))}
    </div>
  )

  return (
    <div>
      <div className={styles.cardHead}>
        {leyenda}
        <button type="button" className={styles.btnGhost} onClick={() => setTabla((t) => !t)}>
          {tabla ? 'Ver gráfica' : 'Ver tabla'}
        </button>
      </div>

      {tabla ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr><th>Intervalo</th>{SERIES.map((s) => <th key={s.key} className={styles.num}>{s.label}</th>)}<th className={styles.num}>Total</th></tr>
            </thead>
            <tbody>
              {datos.filter((d) => d.total > 0).map((d) => (
                <tr key={+d.fecha}>
                  <td>{d.fecha.toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: rango.paso === 'hour' ? 'short' : undefined })}</td>
                  {SERIES.map((s) => <td key={s.key} className={styles.num}>{fmt(d[s.key])}</td>)}
                  <td className={styles.num}><b>{fmt(d.total)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
          {datos.every((d) => d.total === 0) && <p className={styles.empty}>Sin eventos en este rango.</p>}
        </div>
      ) : (
        <div className={styles.chartBox} ref={box} onMouseLeave={() => setActivo(null)}>
          <svg viewBox={`0 0 ${ancho} ${H}`} height={H} role="img"
               aria-label={`Eventos de seguridad por ${rango.paso === 'hour' ? 'hora' : rango.paso === 'day' ? 'día' : 'semana'}`}>
            {ticks.map((t) => (
              <g key={t}>
                <line className={styles.gridline} x1={M.left} x2={ancho - M.right} y1={M.top + plotH - y(t)} y2={M.top + plotH - y(t)} />
                <text className={styles.tick} x={M.left - 6} y={M.top + plotH - y(t) + 4} textAnchor="end">{fmt(t)}</text>
              </g>
            ))}
            {datos.map((d, i) => {
              const cx = M.left + banda * i + banda / 2
              const x = cx - barW / 2
              let base = M.top + plotH
              const visibles = SERIES.filter((s) => d[s.key] > 0)
              return (
                <g key={+d.fecha} className={activo === i ? styles.barActive : undefined}>
                  {visibles.map((s, k) => {
                    const h = y(d[s.key])
                    const alto = k < visibles.length - 1 ? Math.max(1, h - GAP) : h
                    base -= h
                    return <Segmento key={s.key} x={x} y={base + (h - alto)} w={barW} h={alto} color={s.color} arriba={k === visibles.length - 1} />
                  })}
                  {i % cadaEtiqueta === 0 && (
                    <text className={styles.tick} x={cx} y={H - 6} textAnchor="middle">{etiqueta(d.fecha, rango.paso, variosDias)}</text>
                  )}
                  {/* Zona de hover más grande que la barra */}
                  <rect className={styles.hit} x={M.left + banda * i} y={M.top} width={banda} height={plotH}
                        onMouseEnter={() => setActivo(i)} />
                </g>
              )
            })}
          </svg>

          {activo !== null && datos[activo] && (() => {
            const d = datos[activo]
            const cx = M.left + banda * activo + banda / 2
            const izquierda = Math.min(Math.max(0, cx - 85), ancho - 180)
            return (
              <div className={styles.tooltip} style={{ left: izquierda, top: 0 }}>
                <strong>{d.fecha.toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: rango.paso === 'hour' ? 'short' : undefined })}</strong>
                {[...SERIES].reverse().map((s) => (
                  <div key={s.key}><span><i className={styles.swatch} style={{ background: s.color }} />{s.label}</span><b>{fmt(d[s.key])}</b></div>
                ))}
                <div><span>Total</span><b>{fmt(d.total)}</b></div>
              </div>
            )
          })()}
        </div>
      )}
    </div>
  )
}
