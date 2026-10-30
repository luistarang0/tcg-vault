import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { createAuction, fetchMyAuctions, fetchMyCards, sellToHouse } from '../api.js'
import AuctionCard from '../components/AuctionCard.jsx'
import MiniCard from '../components/MiniCard.jsx'
import useAuth from '../hooks/useAuth.jsx'
import useDynamicDom from '../hooks/useDynamicDom.js'
import styles from './Page.module.css'
import m from './Market.module.css'

const DURATION_LABEL = { '5m': '5 minutos', '1h': '1 hora', '6h': '6 horas', '24h': '24 horas', '3d': '3 días' }
const fmt = (n) => n.toLocaleString('es-MX')

/** Formulario en línea para subastar una copia propia. */
function SellForm({ item, durations, onDone, onCancel }) {
  const suggested = item.card.house_price * 2
  const [duration, setDuration] = useState('1h')
  const [start, setStart] = useState(String(suggested))
  const [buyout, setBuyout] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    const startN = Math.floor(Number(start))
    const buyoutN = buyout ? Math.floor(Number(buyout)) : null
    if (!startN || startN < 1) return setError('El precio de salida debe ser al menos 1.')
    if (buyoutN !== null && buyoutN <= startN) return setError('La compra inmediata debe ser mayor que la salida.')
    setBusy(true)
    setError(null)
    try {
      const res = await createAuction({ owned_card_id: item.owned_card_id, duration,
        start_price: startN, buyout_price: buyoutN })
      onDone(res.id)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <form className={m.inline} onSubmit={submit}>
      <label>Duración
        <select name="duration" value={duration} onChange={(e) => setDuration(e.target.value)}>
          {durations.map((d) => <option key={d} value={d}>{DURATION_LABEL[d] || d}</option>)}
        </select>
      </label>
      <label>Precio de salida (pts)
        <input name="start_price" type="number" min="1" value={start} onChange={(e) => setStart(e.target.value)} />
      </label>
      <label>Compra inmediata (opcional)
        <input name="buyout_price" type="number" min="2" value={buyout} placeholder="Sin compra inmediata"
               onChange={(e) => setBuyout(e.target.value)} />
      </label>
      <p className={m.hint}>Si nadie puja antes de que termine, la carta sigue siendo tuya.</p>
      {error && <small className={styles.error}>{error}</small>}
      <div className={m.actions}>
        <button className={`${m.btn} ${m.btnSmall}`} type="submit" disabled={busy}>Publicar</button>
        <button className={`${m.btnGhost} ${m.btnSmall}`} type="button" onClick={onCancel}>Cancelar</button>
      </div>
    </form>
  )
}

/**
 * Perfil privado: saldo, colección (subastar o vender a la casa) y actividad.
 * Requiere sesión; sin ella redirige a /entrar.
 */
export default function ProfilePage() {
  const { user, rules, refresh } = useAuth()
  const location = useLocation()
  const [tab, setTab] = useState('cards')
  const [cards, setCards] = useState(null)
  const [activity, setActivity] = useState(null)
  const [selling, setSelling] = useState(null)       // owned_card_id con el formulario abierto
  const [msg, setMsg] = useState(location.state?.welcome ? { kind: 'ok', text: location.state.welcome } : null)
  const [rarity, setRarity] = useState('')
  const dyn = useDynamicDom()

  const load = useCallback(() => {
    fetchMyCards().then((r) => setCards(r.items)).catch((e) => setMsg({ kind: 'warn', text: e.message }))
    fetchMyAuctions().then(setActivity).catch(() => {})
  }, [])

  useEffect(() => { if (user) load() }, [user?.username]) // eslint-disable-line react-hooks/exhaustive-deps

  if (user === null) return <Navigate to="/entrar" replace />
  if (user?.is_admin) return <Navigate to="/admin" replace />     // el admin no tiene colección
  if (!user) return <p className={styles.loading}>Cargando…</p>

  const sell = async (item) => {
    if (!window.confirm(`¿Vender ${item.card.name} a la casa por ${item.card.house_price} puntos?`)) return
    try {
      const res = await sellToHouse(item.owned_card_id)
      setMsg({ kind: 'ok', text: `Vendiste ${item.card.name} por ${res.points} puntos.` })
    } catch (e) {
      setMsg({ kind: 'warn', text: e.message })
    }
    load()
    refresh()
  }

  const rarities = [...new Set((cards || []).map((c) => c.card.rarity).filter(Boolean))].sort()
  const shown = (cards || []).filter((c) => !rarity || c.card.rarity === rarity)
  const activeSelling = activity?.selling.filter((a) => a.status === 'active').length ?? 0
  const activeBids = activity?.bidding.filter((a) => a.status === 'active').length ?? 0

  return (
    <section>
      <h1 className={styles.title}>@{user.username}</h1>
      <p className={styles.subtitle}>
        Tu perfil público: <Link to={`/u/${user.username}`}>/u/{user.username}</Link>
      </p>

      <div className={m.wallet}>
        <div className={m.walletItem}>
          <small className={m.label}>Puntos disponibles</small>
          <strong data-points={user.points}>{fmt(user.points)}</strong>
        </div>
        <div className={m.walletItem}>
          <small className={m.label}>Congelados en pujas</small>
          <strong>{fmt(user.frozen)}</strong>
        </div>
        <div className={m.walletItem}>
          <small className={m.label}>Cartas</small>
          <strong>{cards ? cards.length : '…'}</strong>
        </div>
      </div>
      {rules && <p className={m.hint}>Cada día recibes {rules.daily_bonus} puntos al entrar.</p>}

      {msg && <div className={`${styles.alert} ${styles[msg.kind]}`} role="status">{msg.text}</div>}

      <div className={m.tabs} role="tablist">
        <button role="tab" aria-selected={tab === 'cards'} onClick={() => setTab('cards')}>Mi colección</button>
        <button role="tab" aria-selected={tab === 'selling'} onClick={() => setTab('selling')}>
          Mis subastas{activeSelling ? ` (${activeSelling})` : ''}
        </button>
        <button role="tab" aria-selected={tab === 'bidding'} onClick={() => setTab('bidding')}>
          Mis pujas{activeBids ? ` (${activeBids})` : ''}
        </button>
      </div>

      {tab === 'cards' && (
        !cards ? <p className={styles.loading}>Cargando…</p>
          : cards.length === 0 ? <p className={m.empty}>No tienes cartas. <Link to="/subastas">Ve a las subastas</Link>.</p>
            : (
              <>
                {rarities.length > 1 && (
                  <div className={m.toolbar}>
                    <select className={m.select} name="rarity" value={rarity} aria-label="Filtrar por rareza"
                            onChange={(e) => setRarity(e.target.value)}>
                      <option value="">Todas las rarezas</option>
                      {rarities.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </div>
                )}
                <div className={dyn.cls(styles.grid)} id={dyn.id('my-cards')}>
                  {shown.map((item) => (
                    <MiniCard key={item.owned_card_id} card={item.card}
                              detail={{ from: '/perfil', label: 'Volver a mi colección' }}
                              data-owned-card-id={item.owned_card_id} data-card-id={item.card.id}>
                      {item.auction_id ? (
                        <Link className={m.inUse} to={`/subastas/${item.auction_id}`}>En subasta →</Link>
                      ) : selling === item.owned_card_id ? (
                        <SellForm item={item} durations={rules?.durations || Object.keys(DURATION_LABEL)}
                                  onCancel={() => setSelling(null)}
                                  onDone={(id) => {
                                    setSelling(null)
                                    setMsg({ kind: 'ok', text: <>Publicaste {item.card.name}. <Link to={`/subastas/${id}`}>Ver subasta</Link></> })
                                    load()
                                  }} />
                      ) : (
                        <div className={m.actions}>
                          <button className={`${m.btn} ${m.btnSmall}`} onClick={() => setSelling(item.owned_card_id)}>Subastar</button>
                          <button className={`${m.btnGhost} ${m.btnSmall}`} onClick={() => sell(item)}>
                            Vender ({item.card.house_price})
                          </button>
                        </div>
                      )}
                    </MiniCard>
                  ))}
                </div>
              </>
            )
      )}

      {tab === 'selling' && <AuctionGrid items={activity?.selling} empty="No has puesto cartas en subasta." />}
      {tab === 'bidding' && <AuctionGrid items={activity?.bidding} empty="No has pujado en ninguna subasta." />}
    </section>
  )
}

function AuctionGrid({ items, empty }) {
  if (!items) return <p className={styles.loading}>Cargando…</p>
  if (items.length === 0) return <p className={m.empty}>{empty}</p>
  return <div className={styles.grid}>{items.map((a) => <AuctionCard key={a.id} auction={a} />)}</div>
}
