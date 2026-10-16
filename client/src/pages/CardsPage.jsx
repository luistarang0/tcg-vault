import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchCards, fetchFilters } from '../api.js'
import CardItem from '../components/CardItem.jsx'
import FilterBar from '../components/FilterBar.jsx'
import Pagination from '../components/Pagination.jsx'
import styles from './Page.module.css'

// Parámetros de la URL que se reenvían tal cual a /api/cards
const FILTER_KEYS = ['type', 'set_id', 'generation', 'rarity', 'category', 'q']

/**
 * Catálogo: la página y los filtros viven en la URL (useSearchParams).
 *   /cartas?page=3&type=Fuego&generation=1
 * El listado se carga con fetch después del primer render (contenido dinámico):
 * un scraper necesita Selenium con esperas explícitas para verlo.
 */
export default function CardsPage() {
  const [params, setParams] = useSearchParams()
  const [filters, setFilters] = useState(null)   // opciones de los <select>
  const [data, setData] = useState(null)         // respuesta de /api/cards
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const page = Math.max(1, Number(params.get('page')) || 1)
  const values = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) || '']))

  // Opciones de filtros: se piden una sola vez al montar la página
  useEffect(() => {
    fetchFilters().then(setFilters).catch((e) => setError(e.message))
  }, [])

  // Cada vez que cambia la URL, se vuelve a pedir el listado
  const queryKey = params.toString()
  useEffect(() => {
    let cancelled = false                     // evita pisar resultados si la URL cambia rápido
    setLoading(true)
    setError(null)
    const query = { page: String(page), limit: '20' }
    FILTER_KEYS.forEach((k) => { if (values[k]) query[k] = values[k] })

    fetchCards(query)
      .then((res) => { if (!cancelled) setData(res) })
      .catch((e) => { if (!cancelled) setError(e.message) })   // incluye el aviso de 429
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [queryKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // Al cambiar un filtro se vuelve a la página 1 y se reemplaza la URL
  const onFilterChange = (name, value) => {
    const next = new URLSearchParams(params)
    if (value) next.set(name, value)
    else next.delete(name)
    next.delete('page')
    setParams(next)
  }

  return (
    <section>
      <h1 className={styles.title}>Catálogo de cartas</h1>
      <p className={styles.subtitle}>
        {data ? `${data.total} cartas encontradas` : error ? 'No se pudo cargar el catálogo.' : 'Cargando catálogo…'}
      </p>

      <FilterBar options={filters} values={values} onChange={onFilterChange} />

      {error && <div className={`${styles.alert} ${styles.warn}`} role="alert">{error}</div>}

      {loading && !data ? (
        <p className={styles.loading}>Cargando…</p>
      ) : data && data.items.length === 0 ? (
        <p className={styles.loading}>Sin resultados con esos filtros.</p>
      ) : (
        data && (
          <>
            <div className={styles.grid} id="card-list" aria-busy={loading}>
              {data.items.map((card) => <CardItem key={card.id} card={card} />)}
            </div>
            <Pagination page={data.page} pages={data.pages} />
          </>
        )
      )}
    </section>
  )
}
