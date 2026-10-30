import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { buyNow, cancelAuction, fetchAuction, placeBid } from '../api.js'
import Countdown from '../components/Countdown.jsx'
import MiniCard from '../components/MiniCard.jsx'
import useAuth from '../hooks/useAuth.jsx'
import useDynamicDom from '../hooks/useDynamicDom.js'
import styles from './Page.module.css'
import m from './Market.module.css'

const POLL_MS = 5000
const STATUS_TEXT = {
  sold: 'Subasta terminada: vendida.',
  expired: 'Subasta terminada sin pujas: la carta volvió a su dueño.',
  cancelled: 'El vendedor canceló esta subasta.',
}
const fmt = (n) => n.toLocaleString('es-MX')

/**
 * Detalle de una subasta. Se vuelve a consultar cada 5 s (polling) mientras la
 * pestaña está visible, así se ven las pujas de otros sin recargar. Si la
 * pestaña está oculta no se consulta: no tiene sentido gastar el rate limit.
 */
export default function AuctionPage() {
  const { id } = useParams()
  const { user, refresh } = useAuth()
  const [a, setA] = useState(null)
  const [offset, setOffset] = useState(0)     // reloj del servidor - reloj local
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)        // { kind, text }
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const dyn = useDynamicDom()

  const load = useCallback(async () => {
    try {
      const res = await fetchAuction(id)
      setA(res)
      setOffset(new Date(res.server_now).getTime() - Date.now())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [id])

  useEffect(() => {
    load()
    const t = setInterval(() => { if (!document.hidden) load() }, POLL_MS)
    return () => clearInterval(t)
  }, [load])

  // Propone la puja mínima cuando cambia (si el usuario no está escribiendo otra mayor)
  useEffect(() => {
    if (a && (amount === '' || Number(amount) < a.min_next_bid)) setAmount(String(a.min_next_bid))
  }, [a?.min_next_bid]) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn, okText) => {
    setBusy(true)
    setMsg(null)
    try {
      const res = await fn()
      setMsg({ kind: 'ok', text: typeof okText === 'function' ? okText(res) : okText })
    } catch (e) {
      setMsg({ kind: 'warn', text: e.message })
    } finally {
      setBusy(false)
      load()
      refresh()     // actualiza el saldo del encabezado
    }
  }

  if (error && !a) return <div className={`${styles.alert} ${styles.warn}`}>{error}</div>
  if (!a) return <p className={styles.loading}>Cargando…</p>

  const active = a.status === 'active'
  const canBid = active && user && !user.is_admin && !a.is_mine && !a.i_lead

  const onBid = (e) => {
    e.preventDefault()
    const n = Math.floor(Number(amount))
    if (!n || n < a.min_next_bid) {
      setMsg({ kind: 'warn', text: `La puja mínima es ${fmt(a.min_next_bid)} puntos.` })
      return
    }
    act(() => placeBid(a.id, n), (r) => r.buyout ? '¡Compraste la carta con compra inmediata!'
      : r.extended ? `Puja de ${fmt(r.amount)} registrada. Quedaban menos de 2 min: la subasta se extendió.`
        : `Puja de ${fmt(r.amount)} registrada. Vas ganando.`)
  }

  return (
    <section>
      <Link to="/subastas" className={styles.back}>← Volver a subastas</Link>
      <div className={m.detail} data-auction-id={a.id} data-status={a.status}>
        <MiniCard card={a.card} />

        <div className={m.panel}>
          <div>
            <h1 className={styles.title}>{a.card.name}</h1>
            <p className={m.hint}>
              Vende {a.is_house ? 'la casa' : <Link to={`/u/${a.seller}`}>@{a.seller}</Link>}
              {' · '}<Link to={`/cartas/${encodeURIComponent(a.card.id)}`}>Ver ficha de la carta</Link>
            </p>
          </div>

          <div className={m.stats}>
            <div className={m.stat}>
              <small className={m.label}>{a.current_bid ? 'Puja actual' : 'Precio de salida'}</small>
              <strong data-current-bid={a.current_bid ?? ''}>{fmt(a.current_bid ?? a.start_price)} pts</strong>
            </div>
            <div className={m.stat}>
              <small className={m.label}>{active ? 'Termina en' : 'Terminó'}</small>
              <strong>{active ? <Countdown endsAt={a.ends_at} offsetMs={offset} className={m.time} />
                : new Date(a.closed_at || a.ends_at).toLocaleString('es-MX')}</strong>
            </div>
            <div className={m.stat}>
              <small className={m.label}>Va ganando</small>
              <strong>{a.leader ? `@${a.leader}` : '—'}</strong>
            </div>
            {a.buyout_price && (
              <div className={m.stat}>
                <small className={m.label}>Compra inmediata</small>
                <strong>{fmt(a.buyout_price)} pts</strong>
              </div>
            )}
          </div>

          {!active && <div className={`${styles.alert} ${styles.ok}`}>
            {STATUS_TEXT[a.status]}{a.status === 'sold' && a.leader ? ` Ganó @${a.leader} con ${fmt(a.current_bid)} pts.` : ''}
          </div>}

          {active && user?.is_admin && (
            <p className={m.hint}>La cuenta de administrador no participa en subastas.</p>
          )}
          {active && !user && (
            <p className={m.hint}><Link to="/entrar">Inicia sesión</Link> o <Link to="/registro">regístrate</Link> para pujar.</p>
          )}
          {active && a.i_lead && <div className={`${styles.alert} ${styles.ok}`}>Vas ganando esta subasta. Tus puntos están congelados hasta que te superen o termine.</div>}

          {canBid && (
            <form className={dyn.cls(m.bidForm)} id={dyn.id('form-puja')} onSubmit={onBid}>
              <input name="amount" type="number" inputMode="numeric" min={a.min_next_bid} step="1"
                     value={amount} onChange={(e) => setAmount(e.target.value)} aria-label="Tu puja en puntos" />
              <button className={dyn.cls(m.btn)} id={dyn.id('btn-pujar')} type="submit" disabled={busy}>Pujar</button>
              {a.buyout_price && (
                <button type="button" className={m.btnGhost} disabled={busy}
                        onClick={() => act(() => buyNow(a.id), '¡Compraste la carta con compra inmediata!')}>
                  Comprar ya por {fmt(a.buyout_price)}
                </button>
              )}
            </form>
          )}
          {canBid && (
            <p className={m.hint}>
              Mínimo {fmt(a.min_next_bid)} pts · Disponibles: {fmt(a.my_points ?? 0)} pts.
              Al pujar, tus puntos se congelan; si alguien te supera, se te devuelven al instante.
            </p>
          )}

          {active && a.is_mine && (
            a.bid_count === 0
              ? <button type="button" className={m.btnGhost} disabled={busy}
                        onClick={() => act(() => cancelAuction(a.id), 'Subasta cancelada. La carta sigue en tu colección.')}>
                  Cancelar subasta
                </button>
              : <p className={m.hint}>Ya tiene pujas: no se puede cancelar.</p>
          )}

          {msg && <div className={`${styles.alert} ${styles[msg.kind]}`} role="status">{msg.text}</div>}

          <div>
            <h2 className={m.section}>Historial de pujas ({a.bid_count})</h2>
            {a.bids.length === 0 ? <p className={m.empty}>Aún no hay pujas.</p> : (
              <ol className={m.history}>
                {a.bids.map((b, i) => (
                  <li key={i} data-bid-amount={b.amount} data-bid-at={b.at}>
                    <span><Link to={`/u/${b.user}`}>@{b.user}</Link></span>
                    <span className={m.muted}>{new Date(b.at).toLocaleTimeString('es-MX')}</span>
                    <strong>{fmt(b.amount)} pts</strong>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
