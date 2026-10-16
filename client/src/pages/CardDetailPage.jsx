import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchCard } from '../api.js'
import styles from './Page.module.css'

/**
 * Detalle de una carta. Además del HTML visible, incluye un bloque JSON-LD
 * (<script type="application/ld+json">) con los mismos datos: otra forma de
 * "renderizado mixto" que un scraper puede aprovechar.
 */
export default function CardDetailPage() {
  const { id } = useParams()
  const [card, setCard] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setCard(null)
    setError(null)
    fetchCard(id).then(setCard).catch((e) => setError(e.message))
  }, [id])

  if (error) {
    return (
      <section>
        <Link to="/cartas" className={styles.back}>← Volver al catálogo</Link>
        <div className={`${styles.alert} ${styles.warn}`} role="alert">{error}</div>
      </section>
    )
  }
  if (!card) return <p className={styles.loading}>Cargando carta…</p>

  // Datos estructurados (schema.org) generados a partir de la respuesta de la API
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Product',
    sku: card.id,
    name: card.name,
    category: card.category,
    image: card.image || undefined,
    additionalProperty: [
      { '@type': 'PropertyValue', name: 'Tipo', value: card.types_list.join(', ') },
      { '@type': 'PropertyValue', name: 'Colección', value: card.set_name },
      { '@type': 'PropertyValue', name: 'Generación', value: card.generation },
      { '@type': 'PropertyValue', name: 'Rareza', value: card.rarity },
    ],
  }

  return (
    <section>
      <Link to="/cartas" className={styles.back}>← Volver al catálogo</Link>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <article
        className={styles.detail}
        data-card-id={card.id}
        data-card-name={card.name}
        data-type={card.types_list.join(',')}
        data-collection={card.set_name || ''}
        data-generation={card.generation ?? ''}
      >
        <div className={styles.detailArt}>
          {card.image ? <img src={card.image} alt={card.name} /> : <span>{card.category}</span>}
        </div>

        <div>
          <h1 className={styles.title}>{card.name}</h1>
          <p className={styles.subtitle}>{card.set_name} · #{card.local_id}</p>

          {/* Lista de definiciones: etiqueta / valor. Los campos ausentes se muestran como "—" */}
          <dl className={styles.facts}>
            <dt>Categoría</dt><dd>{card.category || '—'}</dd>
            <dt>Tipo</dt><dd>{card.types_list.join(', ') || '—'}</dd>
            <dt>PS</dt><dd>{card.hp ?? '—'}</dd>
            <dt>Rareza</dt><dd>{card.rarity || '—'}</dd>
            <dt>Generación</dt><dd>{card.generation ?? '—'}</dd>
            <dt>Pokédex</dt><dd>{card.dex_id ?? '—'}</dd>
            <dt>Ilustrador</dt><dd>{card.illustrator || '—'}</dd>
          </dl>

          <h2>Ataques</h2>
          {card.attacks.length === 0 ? (
            <p className={styles.subtitle}>Esta carta no tiene ataques.</p>
          ) : (
            card.attacks.map((a, i) => (
              <div key={i} className={styles.attack} data-attack-name={a.name}>
                <div className={styles.attackHead}>
                  <span>{a.name}</span>
                  <span>{a.damage || ''}</span>
                </div>
                <div className={styles.attackCost}>Costo: {a.cost.join(', ') || 'ninguno'}</div>
                {a.effect && <p>{a.effect}</p>}
              </div>
            ))
          )}
        </div>
      </article>
    </section>
  )
}
