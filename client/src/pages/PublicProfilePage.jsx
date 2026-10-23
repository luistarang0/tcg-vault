import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchProfile } from '../api.js'
import AuctionCard from '../components/AuctionCard.jsx'
import MiniCard from '../components/MiniCard.jsx'
import useDynamicDom from '../hooks/useDynamicDom.js'
import styles from './Page.module.css'
import m from './Market.module.css'

/** Perfil público /u/:username: colección y subastas activas (sin correo ni saldo). */
export default function PublicProfilePage() {
  const { username } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const dyn = useDynamicDom()

  useEffect(() => {
    setData(null)
    setError(null)
    fetchProfile(username).then(setData).catch((e) => setError(e.message))
  }, [username])

  if (error) return <div className={`${styles.alert} ${styles.warn}`}>{error}</div>
  if (!data) return <p className={styles.loading}>Cargando…</p>

  return (
    <section data-username={data.username}>
      <Link to="/subastas" className={styles.back}>← Subastas</Link>
      <h1 className={styles.title}>@{data.username}</h1>
      <p className={styles.subtitle}>
        Coleccionista desde {new Date(data.member_since).toLocaleDateString('es-MX', { dateStyle: 'long' })}
        {' · '}{data.cards.length} cartas
      </p>

      {data.auctions.length > 0 && (
        <>
          <h2 className={m.section}>Subastas activas</h2>
          <div className={styles.grid}>{data.auctions.map((a) => <AuctionCard key={a.id} auction={a} />)}</div>
        </>
      )}

      <h2 className={m.section}>Colección</h2>
      {data.cards.length === 0 ? <p className={m.empty}>Aún no tiene cartas.</p> : (
        <div className={dyn.cls(styles.grid)} id={dyn.id('user-cards')}>
          {data.cards.map((item) => (
            <MiniCard key={item.owned_card_id} card={item.card} data-card-id={item.card.id}
                      detail={{ from: `/u/${data.username}`, label: `Volver al perfil de @${data.username}` }}>
              {item.auction_id && <Link className={m.inUse} to={`/subastas/${item.auction_id}`}>En subasta →</Link>}
            </MiniCard>
          ))}
        </div>
      )}
    </section>
  )
}
