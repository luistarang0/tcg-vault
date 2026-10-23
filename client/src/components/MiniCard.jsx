import { Link } from 'react-router-dom'
import { TYPE_COLORS } from './CardItem.jsx'
import styles from '../pages/Market.module.css'

/**
 * Arte + nombre + rareza de una carta. Lo usan las subastas y las colecciones.
 * `children` se dibuja debajo (precio, botones...).
 * Con `detail` (estado para la navegación, ej. { from, label }) el arte y el
 * nombre enlazan a la ficha completa /cartas/:id; los botones de `children` quedan fuera del enlace.
 */
export default function MiniCard({ card, detail, children, className = '', ...rest }) {
  const color = TYPE_COLORS[card.types_list?.[0]] || '#a8a49a'
  const art = (
    <div className={styles.miniArt} style={{ '--type-color': color }}>
      {card.image ? <img src={card.image} alt={card.name} loading="lazy" />
        : <span>{card.category || card.name}</span>}
    </div>
  )
  const href = `/cartas/${encodeURIComponent(card.id)}`
  return (
    <article className={`${styles.mini} ${className}`} {...rest}>
      {detail ? <Link to={href} state={detail} className={styles.zoom} aria-label={`Ver ficha de ${card.name}`}>{art}</Link> : art}
      <div className={styles.miniBody}>
        <h3 className={styles.miniName}>
          {detail ? <Link to={href} state={detail} className={styles.plainLink}>{card.name}</Link> : card.name}
        </h3>
        <p className={styles.miniMeta}>
          <span className={styles.rarity} data-rarity={card.rarity || ''}>{card.rarity}</span>
          {card.set_name ? ` · ${card.set_name}` : ''}
        </p>
        {children}
      </div>
    </article>
  )
}
