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

/** Valor de la cookie `csrf_token` que entrega el backend (no es httponly a propósito). */
function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

/**
 * Hace la petición y devuelve el JSON, o lanza ApiError.
 * credentials: 'same-origin' -> el navegador envía las cookies del backend
 * (`sid` del rate limiter y `vault_session` de la sesión de usuario).
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
  // El backend manda {error: "..."} en errores propios y {detail: "..."} en HTTPException
  const message = body?.error || (typeof body?.detail === 'string' ? body.detail : null)
  if (res.status === 422) throw new ApiError('Datos inválidos.', 422, null, body)
  if (res.status === 404) throw new ApiError(message || 'No encontrado.', 404, null, body)
  throw new ApiError(message || `Error ${res.status}`, res.status, null, body)
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

/**
 * POST con cuerpo JSON (o sin cuerpo si `data` es undefined).
 * Toda operación que modifica datos lleva X-CSRF-Token = cookie csrf_token; el
 * servidor compara ambos (security/csrf.py). Si es la primera visita y aún no
 * hay cookie, se pide /api/health para obtenerla.
 */
async function post(path, data) {
  if (!csrfToken()) await fetch('/api/health', { credentials: 'same-origin' })
  const headers = { 'X-CSRF-Token': csrfToken() }
  if (data !== undefined) headers['Content-Type'] = 'application/json'
  return request(path, {
    method: 'POST',
    headers,
    body: data === undefined ? undefined : JSON.stringify(data),
  })
}

// --- Cuentas ---
/** Crea la cuenta (y deja la sesión iniciada). */
export const postRegister = (data) => post('/api/register', data)
export const postLogin = (data) => post('/api/login', data)
export const postLogout = () => post('/api/logout')
/** Usuario actual: { user: {...} | null, rules } */
export const fetchMe = () => request('/api/me')

// --- Colección ---
export const fetchMyCards = () => request('/api/me/cards')
export const fetchMyAuctions = () => request('/api/me/auctions')
export const sellToHouse = (ownedCardId) => post(`/api/me/cards/${ownedCardId}/sell`)
export const fetchProfile = (username) => request(`/api/users/${encodeURIComponent(username)}`)

// --- Subastas ---
export function fetchAuctions(params) {
  const qs = new URLSearchParams(params).toString()
  return request(`/api/auctions?${qs}`)
}
export const fetchAuction = (id) => request(`/api/auctions/${id}`)
export const createAuction = (data) => post('/api/auctions', data)
export const placeBid = (id, amount) => post(`/api/auctions/${id}/bid`, { amount })
export const buyNow = (id) => post(`/api/auctions/${id}/buyout`)
export const cancelAuction = (id) => post(`/api/auctions/${id}/cancel`)

// --- Administración (solo el administrador; el servidor responde 401/403 a los demás) ---
export const fetchAdminFiltros = () => request('/api/admin/filtros')
export const fetchAdminResumen = (params) => request(`/api/admin/resumen?${new URLSearchParams(params)}`)
export const fetchAdminEventos = (params) => request(`/api/admin/eventos?${new URLSearchParams(params)}`)
/** URL de descarga del CSV con los mismos filtros (el navegador manda la cookie de sesión). */
export const adminCsvUrl = (params) => `/api/admin/eventos.csv?${new URLSearchParams(params)}`
