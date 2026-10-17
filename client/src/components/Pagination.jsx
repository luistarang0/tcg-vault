import { Link, useSearchParams } from 'react-router-dom'
import useDynamicDom from '../hooks/useDynamicDom.js'
import styles from './Pagination.module.css'

/**
 * Paginación con ENLACES reales (<a href="/cartas?page=N&...">), no botones.
 * Conserva los filtros activos. Un scraper puede seguir el enlace "Siguiente"
 * o construir las URLs directamente.
 */
export default function Pagination({ page, pages }) {
  const [params] = useSearchParams()
  const dyn = useDynamicDom()   // Defensa 5: los enlaces conservan href y rel, cambian id/clase
  if (!pages || pages <= 1) return null

  // Construye la URL de la página n manteniendo los demás parámetros
  const hrefFor = (n) => {
    const p = new URLSearchParams(params)
    p.set('page', String(n))
    return `/cartas?${p.toString()}`
  }

  // Ventana de números alrededor de la página actual: 1 … 4 5 [6] 7 8 … 45
  const nums = []
  for (let n = Math.max(1, page - 2); n <= Math.min(pages, page + 2); n++) nums.push(n)

  return (
    <nav className={dyn.cls(styles.pager)} id={dyn.id('paginacion')} aria-label="Paginación">
      {page > 1 ? (
        <Link to={hrefFor(page - 1)} rel="prev" id={dyn.id('btn-anterior')} className={dyn.cls(styles.btn)}>← Anterior</Link>
      ) : (
        <span className={`${styles.btn} ${styles.disabled}`}>← Anterior</span>
      )}

      {nums[0] > 1 && (<><Link to={hrefFor(1)} className={styles.num}>1</Link><span className={styles.dots}>…</span></>)}
      {nums.map((n) =>
        n === page ? (
          <span key={n} className={`${styles.num} ${styles.current}`} aria-current="page">{n}</span>
        ) : (
          <Link key={n} to={hrefFor(n)} className={styles.num}>{n}</Link>
        ),
      )}
      {nums[nums.length - 1] < pages && (<><span className={styles.dots}>…</span><Link to={hrefFor(pages)} className={styles.num}>{pages}</Link></>)}

      {page < pages ? (
        <Link to={hrefFor(page + 1)} rel="next" id={dyn.id('btn-siguiente')} className={dyn.cls(styles.btn)}>Siguiente →</Link>
      ) : (
        <span className={`${styles.btn} ${styles.disabled}`}>Siguiente →</span>
      )}
      <span className={styles.info} data-page={page} data-pages={pages}>
        Página {page} de {pages}
      </span>
    </nav>
  )
}
