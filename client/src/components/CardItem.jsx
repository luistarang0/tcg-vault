import { Link } from 'react-router-dom'
import useDynamicDom from '../hooks/useDynamicDom.js'
import styles from './CardItem.module.css'

// Color de acento por tipo (solo decorativo; si no hay imagen se usa de fondo).
export const TYPE_COLORS = {
  Planta: '#4f9a3d', Fuego: '#e2553b', Agua: '#3a83d1', Rayo: '#e8b923',
  Psíquico: '#9b59b6', Lucha: '#b5651d', Oscuridad: '#3d3d4a', Metal: '#8a97a3',
  Dragón: '#b8962e', Hada: '#e48bb5', Incoloro: '#a8a49a',
}

/**
 * Tarjeta de una carta en el listado.
 *
 * Los atributos data-* son el CONTRATO ESTABLE para el scraper: el paso 9
 * (DOM dinámico) cambia IDs y clases en cada carga, pero estos atributos no se tocan.
 */
export default function CardItem({ card }) {
  const mainType = card.types_list?.[0]
  const color = TYPE_COLORS[mainType] || '#a8a49a'
  const dyn = useDynamicDom()

  return (
    <article
      className={dyn.cls(styles.card)}
      data-card-id={card.id}
      data-card-name={card.name}
      data-type={card.types_list?.join(',') || ''}
      data-collection={card.set_name || ''}
      data-generation={card.generation ?? ''}
      data-rarity={card.rarity || ''}
      data-category={card.category || ''}
    >
      <Link to={`/cartas/${encodeURIComponent(card.id)}`} className={dyn.cls(styles.link)}>
        <div className={styles.art} style={{ '--type-color': color }}>
          {card.image ? (
            <img src={card.image} alt={card.name} loading="lazy" className={styles.img} />
          ) : (
            <span className={styles.placeholder}>{card.category}</span>
          )}
        </div>
        <div className={styles.body}>
          <h3 className={dyn.cls(styles.name)}>{card.name}</h3>
          <p className={styles.meta}>
            {card.set_name} · #{card.local_id}
          </p>
          <div className={styles.tags}>
            {card.types_list?.map((t) => (
              <span key={t} className={styles.tag} style={{ '--type-color': TYPE_COLORS[t] }}>
                {t}
              </span>
            ))}
            {card.hp ? <span className={styles.hp}>PS {card.hp}</span> : null}
          </div>
        </div>
      </Link>
    </article>
  )
}
