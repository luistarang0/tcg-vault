import { Link } from 'react-router-dom'
import useDynamicDom from '../hooks/useDynamicDom.js'
import Countdown from './Countdown.jsx'
import MiniCard from './MiniCard.jsx'
import styles from '../pages/Market.module.css'

const STATUS_LABEL = { sold: 'Vendida', expired: 'Sin pujas', cancelled: 'Cancelada' }

/**
 * Tarjeta de una subasta en el mercado o en el perfil.
 * Los data-* (data-auction-id, data-current-bid, data-ends-at...) son el
 * contrato estable para el scraper, igual que en el catálogo; IDs y clases
 * decorativas cambian en cada carga (Defensa 5).
 */
export default function AuctionCard({ auction: a }) {
  const dyn = useDynamicDom()
  const price = a.current_bid ?? a.start_price
  return (
    <Link to={`/subastas/${a.id}`} className={styles.plain}>
      <MiniCard
        card={a.card}
        className={dyn.cls(styles.auction, a.i_lead && styles.leading)}
        data-auction-id={a.id}
        data-card-id={a.card.id}
        data-seller={a.is_house ? 'casa' : a.seller}
        data-current-bid={a.current_bid ?? ''}
        data-min-next-bid={a.min_next_bid}
        data-buyout={a.buyout_price ?? ''}
        data-bids={a.bid_count}
        data-status={a.status}
      >
        <div className={styles.priceRow}>
          <div>
            <small className={styles.label}>{a.current_bid ? 'Puja actual' : 'Salida'}</small>
            <strong className={styles.price}>{price.toLocaleString('es-MX')} pts</strong>
          </div>
          <div className={styles.right}>
            <small className={styles.label}>{a.status === 'active' ? 'Termina en' : 'Estado'}</small>
            {a.status === 'active'
              ? <Countdown endsAt={a.ends_at} className={styles.time} />
              : <span className={styles.time}>{STATUS_LABEL[a.status]}</span>}
          </div>
        </div>
        <p className={styles.miniMeta}>
          {a.is_house ? 'La casa' : `@${a.seller}`} · {a.bid_count} {a.bid_count === 1 ? 'puja' : 'pujas'}
          {a.buyout_price ? ` · Compra ya: ${a.buyout_price.toLocaleString('es-MX')}` : ''}
        </p>
        {a.i_lead && <span className={styles.badge}>{a.status === 'active' ? 'Vas ganando' : 'Ganaste'}</span>}
      </MiniCard>
    </Link>
  )
}
