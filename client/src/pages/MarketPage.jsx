import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchAuctions } from '../api.js'
import AuctionCard from '../components/AuctionCard.jsx'
import Pagination from '../components/Pagination.jsx'
import useDynamicDom from '../hooks/useDynamicDom.js'
import styles from './Page.module.css'
import m from './Market.module.css'

const SOURCES = [['all', 'Todas'], ['house', 'De la casa'], ['users', 'De coleccionistas']]
const SORTS = [['ending', 'Terminan pronto'], ['newest', 'Más recientes'],
  ['price_asc', 'Precio: menor a mayor'], ['price_desc', 'Precio: mayor a menor']]
const REFRESH_MS = 15000   // el listado se refresca solo; el detalle lo hace cada 5 s

/**
 * Mercado de subastas: público (como el catálogo). Filtros y página en la URL:
 *   /subastas?source=house&sort=price_asc&page=2
 * Al abrirlo, el servidor cierra las subastas vencidas y repone las de la casa.
 */
export default function MarketPage() {
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const dyn = useDynamicDom()

  const page = Math.max(1, Number(params.get('page')) || 1)
  const source = params.get('source') || 'all'
  const sort = params.get('sort') || 'ending'

  const queryKey = params.toString()
  useEffect(() => {
    let cancelled = false
    const load = () => fetchAuctions({ page: String(page), source, sort })
      .then((res) => { if (!cancelled) { setData(res); setError(null) } })
      .catch((e) => { if (!cancelled) setError(e.message) })
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => { cancelled = true; clearInterval(t) }
  }, [queryKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const setParam = (name, value, def) => {
    const next = new URLSearchParams(params)
    if (value === def) next.delete(name)
    else next.set(name, value)
    next.delete('page')
    setParams(next)
  }

  return (
    <section>
      <h1 className={styles.title}>Subastas</h1>
      <p className={styles.subtitle}>
        {data ? `${data.total} subastas activas. La casa pone cartas nuevas a la venta conforme se cierran.`
          : error ? 'No se pudo cargar el mercado.' : 'Cargando mercado…'}
      </p>

      <div className={m.toolbar}>
        <div className={m.segmented} role="group" aria-label="Origen">
          {SOURCES.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={source === value}
                    onClick={() => setParam('source', value, 'all')}>{label}</button>
          ))}
        </div>
        <select className={m.select} name="sort" value={sort} aria-label="Ordenar"
                onChange={(e) => setParam('sort', e.target.value, 'ending')}>
          {SORTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>

      {error && <div className={`${styles.alert} ${styles.warn}`} role="alert">{error}</div>}

      {data && data.items.length === 0 ? (
        <p className={styles.loading}>No hay subastas con ese filtro.</p>
      ) : data ? (
        <>
          <div className={dyn.cls(styles.grid)} id={dyn.id('auction-list')}>
            {data.items.map((a) => <AuctionCard key={a.id} auction={a} />)}
          </div>
          <Pagination page={data.page} pages={data.pages} basePath="/subastas" />
        </>
      ) : !error && <p className={styles.loading}>Cargando…</p>}
    </section>
  )
}
