import { TYPE_COLORS } from './CardItem.jsx'
import styles from '../pages/Market.module.css'

/**
 * Arte + nombre + rareza de una carta. Lo usan las subastas y las colecciones.
 * `children` se dibuja debajo (precio, botones...).
 */
export default function MiniCard({ card, children, className = '', ...rest }) {
  const color = TYPE_COLORS[card.types_list?.[0]] || '#a8a49a'
  return (
    <article className={`${styles.mini} ${className}`} {...rest}>
      <div className={styles.miniArt} style={{ '--type-color': color }}>
        {card.image ? <img src={card.image} alt={card.name} loading="lazy" />
          : <span>{card.category || card.name}</span>}
      </div>
      <div className={styles.miniBody}>
        <h3 className={styles.miniName}>{card.name}</h3>
        <p className={styles.miniMeta}>
          <span className={styles.rarity} data-rarity={card.rarity || ''}>{card.rarity}</span>
          {card.set_name ? ` · ${card.set_name}` : ''}
        </p>
        {children}
      </div>
    </article>
  )
}
