import { useState } from 'react'

/**
 * Defensa 5 (paso 9): DOM dinámico.
 *
 * Genera una "sal" aleatoria cada vez que se monta el componente (cada carga de
 * página) y la usa para construir IDs y clases DECORATIVAS que cambian siempre.
 * Un scraper con localizadores fijos (By.ID("card-list"), ".btn-buscar") deja de
 * funcionar, pero el sitio sigue siendo scrapeable con el contrato estable:
 *
 *   Cambia (decorativo)              Se mantiene (contenido)
 *   id="card-list-k3x9qa"            data-card-id, data-card-name, data-type,
 *   class="... dyn-k3x9qa"           data-collection, data-generation, ...
 *                                    URLs /cartas?page=N&...
 *
 * Nivel A ya venía incluido: CSS Modules genera nombres de clase con hash que
 * cambian entre compilaciones. Esto es el nivel B (cambia en cada carga).
 *
 * Reglas para no romper nada:
 *  - El estilo nunca depende de estas clases/IDs (sigue viniendo de styles.*).
 *  - No se tocan los data-* de contenido, ni `name` de los inputs, ni las
 *    etiquetas ARIA (accesibilidad).
 *  - Si un <label> apunta a un input con htmlFor, ambos usan el mismo id(),
 *    así la asociación se conserva aunque el valor cambie.
 *
 * Uso:
 *   const dyn = useDynamicDom()
 *   <button id={dyn.id('btn-buscar')} className={dyn.cls(styles.btn)}>Buscar</button>
 */
export default function useDynamicDom() {
  // Inicializador perezoso: la sal se genera una sola vez por montaje
  const [s] = useState(() => Math.random().toString(36).slice(2, 8))

  return {
    salt: s,
    /** ID único por carga: 'card-list' -> 'card-list-k3x9qa' */
    id: (name) => `${name}-${s}`,
    /** Agrega a las clases reales (CSS Modules) una clase señuelo 'dyn-<sal>' */
    cls: (...classes) => [...classes.filter(Boolean), `dyn-${s}`].join(' '),
  }
}
