import { useEffect, useState } from 'react'
import useDynamicDom from '../hooks/useDynamicDom.js'
import styles from './FilterBar.module.css'

/**
 * Barra de filtros. No guarda estado propio de los filtros: lee los valores
 * de la URL (props `values`) y avisa cambios con `onChange(nombre, valor)`.
 * Así la URL es la única fuente de verdad y cualquier combinación de filtros
 * se puede visitar directamente (/cartas?type=Fuego&generation=1).
 */
export default function FilterBar({ options, values, onChange }) {
  // La búsqueda por texto se aplica con un pequeño retardo (debounce) para no
  // disparar una petición por cada tecla y no gastar el rate limit.
  const [text, setText] = useState(values.q || '')
  const dyn = useDynamicDom()           // Defensa 5: el `name` de cada campo no cambia
  useEffect(() => setText(values.q || ''), [values.q])
  useEffect(() => {
    if (text === (values.q || '')) return
    const t = setTimeout(() => onChange('q', text), 400)
    return () => clearTimeout(t)
  }, [text]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!options) return null

  // Pequeño helper para no repetir el mismo <select> cinco veces
  const select = (name, label, items) => (
    <label className={styles.field}>
      <span className={styles.label}>{label}</span>
      <select
        name={name}
        id={dyn.id(`filtro-${name}`)}
        className={dyn.cls(styles.select)}
        value={values[name] || ''}
        onChange={(e) => onChange(name, e.target.value)}
      >
        <option value="">Todos</option>
        {items.map((it) => (
          <option key={it.value} value={it.value}>{it.label}</option>
        ))}
      </select>
    </label>
  )

  return (
    <form className={dyn.cls(styles.bar)} id={dyn.id('filtros')} role="search" onSubmit={(e) => e.preventDefault()}>
      <label className={`${styles.field} ${styles.grow}`}>
        <span className={styles.label}>Nombre</span>
        <input
          name="q"
          type="search"
          id={dyn.id('buscar')}
          className={dyn.cls(styles.select)}
          placeholder="Buscar carta…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      {select('type', 'Tipo', options.types.map((t) => ({ value: t, label: t })))}
      {select('set_id', 'Colección', options.sets.map((s) => ({ value: s.id, label: s.name })))}
      {select('generation', 'Generación', options.generations.map((g) => ({ value: String(g), label: `Gen ${g}` })))}
      {select('rarity', 'Rareza', options.rarities.map((r) => ({ value: r, label: r })))}
      {select('category', 'Categoría', options.categories.map((c) => ({ value: c, label: c })))}
    </form>
  )
}
