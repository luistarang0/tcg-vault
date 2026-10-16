// Funciones de acceso al backend. Todas las páginas usan este módulo,
// así el manejo de errores (sobre todo el 429) vive en un solo lugar.

/** Error con información extra para mostrar mensajes útiles en la interfaz. */
export class ApiError extends Error {
  constructor(message, status, retryAfter = null, details = null) {
    super(message)
    this.status = status          // código HTTP (404, 422, 429...)
    this.retryAfter = retryAfter  // segundos del encabezado Retry-After (solo 429)
    this.details = details        // cuerpo JSON de error, si lo hay
  }
}

/**
 * Hace la petición y devuelve el JSON, o lanza ApiError.
 * credentials: 'same-origin' -> el navegador envía la cookie `sid` del backend.
 */
async function request(path, options = {}) {
  const res = await fetch(path, { credentials: 'same-origin', ...options })
  let body = null
  try {
    body = await res.json()
  } catch {
    body = null // respuesta sin JSON
  }

  if (res.ok) return body

  if (res.status === 429) {
    const retryAfter = Number(res.headers.get('Retry-After')) || 60
    throw new ApiError(
      `Demasiadas peticiones. Intenta de nuevo en ${retryAfter} s.`,
      429, retryAfter, body,
    )
  }
  if (res.status === 404) throw new ApiError('No encontrado.', 404, null, body)
  if (res.status === 422) throw new ApiError('Datos inválidos.', 422, null, body)
  throw new ApiError(body?.error || `Error ${res.status}`, res.status, null, body)
}

/** Lista paginada. `params` es un URLSearchParams o un objeto plano. */
export function fetchCards(params) {
  const qs = new URLSearchParams(params).toString()
  return request(`/api/cards?${qs}`)
}

export function fetchCard(id) {
  return request(`/api/cards/${encodeURIComponent(id)}`)
}

export function fetchFilters() {
  return request('/api/filters')
}

/** Envía el formulario de registro de práctica. */
export function postRegister(data) {
  return request('/api/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}
