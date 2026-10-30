import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { adminCsvUrl, fetchAdminEventos, fetchAdminFiltros, fetchAdminResumen } from '../api.js'
import SecurityChart from '../components/SecurityChart.jsx'
import useAuth from '../hooks/useAuth.jsx'
import styles from './Page.module.css'
import a from './Admin.module.css'

const PRESETS = [['1h', '1 h', 1], ['24h', '24 h', 24], ['7d', '7 días', 24 * 7], ['30d', '30 días', 24 * 30], ['custom', 'Personalizado', 0]]
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone
const AUTO_MS = 30000
const fmt = (n) => (n ?? 0).toLocaleString('es-MX')
const pad = (n) => String(n).padStart(2, '0')
/** Date -> valor de <input type="datetime-local"> (hora local). */
const aLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
const fechaHora = (iso) => new Date(iso).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'medium' })

/** Rango efectivo en ISO (con zona) a partir de los parámetros de la URL. */
function rangoDe(params, ahora) {
  const preset = params.get('rango') || '24h'
  if (preset === 'custom' && params.get('desde') && params.get('hasta')) {
    return { desde: new Date(params.get('desde')).toISOString(), hasta: new Date(params.get('hasta')).toISOString() }
  }
  const horas = (PRESETS.find((p) => p[0] === preset) || PRESETS[1])[2] || 24
  return { desde: new Date(ahora - horas * 3600e3).toISOString(), hasta: new Date(ahora).toISOString() }
}

/**
 * Panel de seguridad del administrador (/admin): bitácora de security_events con
 * filtros por fecha, tipo de evento, acción, código HTTP, IP y texto. Los filtros
 * viven en la URL, así una vista concreta se puede guardar o compartir.
 * El servidor vuelve a comprobar que la sesión sea la del administrador (403 si no).
 */
export default function AdminPage() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const [opciones, setOpciones] = useState(null)
  const [resumen, setResumen] = useState(null)
  const [eventos, setEventos] = useState(null)
  const [error, setError] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [abierto, setAbierto] = useState(null)        // id del evento con el detalle desplegado
  const [ahora, setAhora] = useState(() => Date.now())
  const [texto, setTexto] = useState(params.get('q') || '')

  const preset = params.get('rango') || '24h'
  const page = Math.max(1, Number(params.get('page')) || 1)
  const rango = useMemo(() => rangoDe(params, ahora), [params, ahora])
  const filtros = useMemo(() => {
    const f = { ...rango }
    for (const k of ['evento', 'accion', 'status', 'ip', 'q']) if (params.get(k)) f[k] = params.get(k)
    return f
  }, [params, rango])

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      const [r, e] = await Promise.all([
        fetchAdminResumen({ ...filtros, tz: TZ }),
        fetchAdminEventos({ ...filtros, page: String(page), limit: '50' }),
      ])
      setResumen(r)
      setEventos(e)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setCargando(false)
    }
  }, [filtros, page])

  useEffect(() => { if (user?.is_admin) fetchAdminFiltros().then(setOpciones).catch(() => {}) }, [user?.is_admin])
  useEffect(() => { if (user?.is_admin) cargar() }, [cargar, user?.is_admin])
  // Con un rango relativo (1 h, 24 h…) la vista se actualiza sola cada 30 s
  useEffect(() => {
    if (preset === 'custom' || !user?.is_admin) return
    const t = setInterval(() => { if (!document.hidden) setAhora(Date.now()) }, AUTO_MS)
    return () => clearInterval(t)
  }, [preset, user?.is_admin])
  // Búsqueda por texto con retardo, para no consultar en cada tecla
  useEffect(() => {
    if (texto === (params.get('q') || '')) return
    const t = setTimeout(() => cambiar({ q: texto }), 400)
    return () => clearTimeout(t)
  }, [texto]) // eslint-disable-line react-hooks/exhaustive-deps

  if (user === undefined) return <p className={styles.loading}>Cargando…</p>
  if (user === null) return <Navigate to="/entrar" replace />
  if (!user.is_admin) {
    return <div className={`${styles.alert} ${styles.warn}`}>Solo el administrador puede ver esta sección.</div>
  }

  /** Cambia filtros en la URL; cualquier cambio vuelve a la página 1. */
  function cambiar(cambios) {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) {
      if (v === '' || v === null || v === undefined) next.delete(k)
      else next.set(k, v)
    }
    if (!('page' in cambios)) next.delete('page')
    setParams(next)
  }

  const elegirPreset = (p) => {
    if (p === 'custom') {
      cambiar({ rango: 'custom', desde: aLocal(new Date(rango.desde)), hasta: aLocal(new Date(rango.hasta)) })
    } else {
      cambiar({ rango: p === '24h' ? '' : p, desde: '', hasta: '' })
      setAhora(Date.now())
    }
  }

  const k = resumen?.kpi
  const sinFiltros = !['evento', 'accion', 'status', 'ip', 'q'].some((x) => params.get(x))

  return (
    <section className={a.root}>
      <div className={a.head}>
        <h1 className={styles.title}>Seguridad</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className={a.btnGhost} disabled={cargando} onClick={() => setAhora(Date.now())}>
            {cargando ? 'Actualizando…' : 'Actualizar'}
          </button>
          <a className={a.btn} href={adminCsvUrl(filtros)}>Exportar CSV</a>
        </div>
      </div>
      <p className={a.range}>
        Del {fechaHora(rango.desde)} al {fechaHora(rango.hasta)} · hora local ({TZ})
        {preset !== 'custom' && ' · se actualiza cada 30 s'}
      </p>

      {opciones && !opciones.guardado_activo && (
        <div className={`${styles.alert} ${styles.warn}`}>
          En este entorno no se están guardando eventos nuevos en la base (SECURITY_EVENTS_DB está apagado).
          Solo verás lo que ya existía. En Vercel se guardan siempre; en local arranca el backend con
          <code> $env:SECURITY_EVENTS_DB="1"</code>.
        </div>
      )}

      {/* ---- Filtros (una sola fila) ---- */}
      <div className={a.filters}>
        <label className={a.field}>
          <span>Periodo</span>
          <div className={a.segmented} role="group" aria-label="Periodo">
            {PRESETS.map(([v, label]) => (
              <button key={v} type="button" aria-pressed={preset === v} onClick={() => elegirPreset(v)}>{label}</button>
            ))}
          </div>
        </label>
        {preset === 'custom' && (
          <>
            <label className={a.field}>
              <span>Desde</span>
              <input type="datetime-local" value={params.get('desde') || ''} max={params.get('hasta') || undefined}
                     onChange={(e) => cambiar({ desde: e.target.value })} />
            </label>
            <label className={a.field}>
              <span>Hasta</span>
              <input type="datetime-local" value={params.get('hasta') || ''} min={params.get('desde') || undefined}
                     onChange={(e) => cambiar({ hasta: e.target.value })} />
            </label>
          </>
        )}
        <label className={a.field}>
          <span>Evento</span>
          <select value={params.get('evento') || ''} onChange={(e) => cambiar({ evento: e.target.value })}>
            <option value="">Todos</option>
            {opciones?.eventos.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className={a.field}>
          <span>Acción</span>
          <select value={params.get('accion') || ''} onChange={(e) => cambiar({ accion: e.target.value })}>
            <option value="">Todas</option>
            {opciones?.acciones.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className={a.field}>
          <span>Código</span>
          <select value={params.get('status') || ''} onChange={(e) => cambiar({ status: e.target.value })}>
            <option value="">Todos</option>
            <option value="4xx">4xx (rechazos)</option>
            <option value="5xx">5xx (errores)</option>
            {opciones?.status.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className={a.field}>
          <span>IP</span>
          <input value={params.get('ip') || ''} placeholder="Todas" size={13}
                 onChange={(e) => cambiar({ ip: e.target.value.trim() })} />
        </label>
        <label className={`${a.field} ${a.grow}`}>
          <span>Buscar</span>
          <input value={texto} placeholder="Ruta, User-Agent, sid o datos" onChange={(e) => setTexto(e.target.value)} />
        </label>
        {!sinFiltros && (
          <button type="button" className={a.btnGhost} onClick={() => { setTexto(''); cambiar({ evento: '', accion: '', status: '', ip: '', q: '' }) }}>
            Quitar filtros
          </button>
        )}
      </div>

      {error && <div className={`${styles.alert} ${styles.warn}`} role="alert">{error}</div>}
      {!resumen && !error && <p className={styles.loading}>Cargando…</p>}

      {resumen && (
        <>
          {/* ---- Indicadores ---- */}
          <div className={a.kpis}>
            <div className={a.kpi}><small>Eventos</small><strong>{fmt(k.total)}</strong><span>{fmt(k.ips)} IPs · {fmt(k.sesiones)} sesiones</span></div>
            <div className={a.kpi}><small>Límite superado</small><strong>{fmt(k.limite)}</strong><span>respuestas 429</span></div>
            <div className={a.kpi}><small>Desafíos Turnstile</small><strong>{fmt(k.desafios)}</strong><span>{fmt(k.turnstile_rechazados)} tokens rechazados</span></div>
            <div className={a.kpi}><small>Frenados por riesgo</small><strong>{fmt(k.frenados)}</strong><span>puntaje 60-79</span></div>
            <div className={a.kpi}><small>CSRF inválido</small><strong>{fmt(k.csrf)}</strong><span>403 sin token válido</span></div>
            <div className={a.kpi}><small>Logins fallidos</small><strong>{fmt(k.login_fallidos)}</strong><span>{fmt(k.cuentas_bloqueadas)} con cuenta bloqueada</span></div>
          </div>

          {/* ---- Serie en el tiempo ---- */}
          <div className={a.card}>
            <div className={a.cardHead}>
              <h2>Eventos por {resumen.rango.paso === 'hour' ? 'hora' : resumen.rango.paso === 'day' ? 'día' : 'semana'}</h2>
            </div>
            <SecurityChart serie={resumen.serie} rango={resumen.rango} />
          </div>

          {/* ---- Top de IPs y señales ---- */}
          <div className={`${a.cols} ${a.colsWrap}`}>
            <div className={a.card}>
              <div className={a.cardHead}><h2>IPs con más eventos</h2></div>
              {resumen.top_ips.length === 0 ? <p className={a.empty}>Sin datos.</p> : (
                <div className={a.tableWrap}>
                  <table className={a.table}>
                    <thead><tr><th>IP</th><th className={a.num}>Eventos</th><th className={a.num}>Rechazos</th><th className={a.num}>Sesiones</th><th>Último</th></tr></thead>
                    <tbody>
                      {resumen.top_ips.map((r) => (
                        <tr key={r.ip}>
                          <td><button type="button" className={`${a.link} ${a.mono}`} title="Filtrar por esta IP" onClick={() => cambiar({ ip: r.ip })}>{r.ip}</button></td>
                          <td className={a.num}>{fmt(r.n)}</td>
                          <td className={a.num}>{fmt(r.rechazados)}</td>
                          <td className={a.num}>{fmt(r.sesiones)}</td>
                          <td>{fechaHora(r.ultimo)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div className={a.card}>
              <div className={a.cardHead}><h2>Señales de automatización</h2></div>
              {resumen.top_senales.length === 0 ? <p className={a.empty}>Sin señales en este rango.</p> : (
                <div className={a.hbars}>
                  {resumen.top_senales.map((s) => (
                    <div key={s.senal} className={a.hbar}>
                      <code>{s.senal}</code>
                      <div className={a.track}><div className={a.fill} style={{ width: `${(s.n / resumen.top_senales[0].n) * 100}%` }} /></div>
                      <b>{fmt(s.n)}</b>
                    </div>
                  ))}
                </div>
              )}
              <h2 style={{ fontSize: '1rem', margin: '16px 0 8px' }}>Por tipo de evento</h2>
              <ul className={a.list}>
                {resumen.por_evento.map((e) => (
                  <li key={e.event}>
                    <button type="button" className={a.link} onClick={() => cambiar({ evento: e.event })}>{e.event}</button>
                    <b>{fmt(e.n)}</b>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* ---- Bitácora ---- */}
          <div className={a.card}>
            <div className={a.cardHead}>
              <h2>Bitácora ({fmt(eventos?.total)} eventos)</h2>
              <small style={{ color: 'var(--muted)' }}>Clic en una fila para ver el detalle</small>
            </div>
            {!eventos || eventos.items.length === 0 ? <p className={a.empty}>No hay eventos con estos filtros.</p> : (
              <>
                <div className={a.tableWrap}>
                  <table className={a.table}>
                    <thead>
                      <tr><th>Fecha y hora</th><th>Evento</th><th className={a.num}>Código</th><th>Petición</th><th>IP</th><th className={a.num}>Puntaje</th><th>Acción</th><th>Señales</th></tr>
                    </thead>
                    <tbody>
                      {eventos.items.map((ev) => (
                        <Fragment key={ev.id}>
                          <tr className={a.row} onClick={() => setAbierto(abierto === ev.id ? null : ev.id)} aria-expanded={abierto === ev.id}>
                            <td style={{ whiteSpace: 'nowrap' }}>{fechaHora(ev.ts)}</td>
                            <td><span className={a.badge}>{ev.event}</span></td>
                            <td className={`${a.num} ${ev.status >= 400 ? a.code4 : ''}`}>{ev.status ?? '—'}</td>
                            <td className={a.mono}>{ev.method} {ev.path}</td>
                            <td><button type="button" className={`${a.link} ${a.mono}`} onClick={(e) => { e.stopPropagation(); cambiar({ ip: ev.ip }) }}>{ev.ip}</button></td>
                            <td className={a.num}>{ev.score ?? '—'}</td>
                            <td>{ev.action || '—'}</td>
                            <td><div className={a.chips}>{ev.flags.map((f) => <span key={f} className={a.chip}>{f}</span>)}</div></td>
                          </tr>
                          {abierto === ev.id && (
                            <tr className={a.detail}>
                              <td colSpan={8}>
                                <dl>
                                  <dt>Sesión (sid)</dt><dd className={a.mono}>{ev.sid || '—'}</dd>
                                  <dt>User-Agent</dt><dd className={a.mono}>{ev.user_agent || '—'}</dd>
                                  <dt>Hora exacta</dt><dd>{new Date(ev.ts).toLocaleString('es-MX')} ({ev.ts})</dd>
                                </dl>
                                <pre className={a.mono}>{JSON.stringify(ev.data, null, 2)}</pre>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className={a.pager}>
                  <button type="button" className={a.btnGhost} disabled={page <= 1} onClick={() => cambiar({ page: String(page - 1) })}>← Anterior</button>
                  <span>Página {page} de {eventos.pages}</span>
                  <button type="button" className={a.btnGhost} disabled={page >= eventos.pages} onClick={() => cambiar({ page: String(page + 1) })}>Siguiente →</button>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </section>
  )
}
