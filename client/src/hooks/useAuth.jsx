import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { fetchMe, postLogout } from '../api.js'

const AuthContext = createContext(null)

/**
 * Estado de la sesión compartido por toda la SPA.
 *
 * La cookie `vault_session` es httponly: JavaScript no puede leerla, así que la
 * única forma de saber si hay sesión es preguntarle al servidor (GET /api/me).
 * Se consulta al montar y cada vez que una página llama a refresh() (después de
 * pujar, vender, iniciar sesión...), así el saldo del encabezado está al día.
 *
 *   user   null (sin sesión), undefined (cargando) o { username, points, frozen }
 *   rules  reglas públicas del mercado (duraciones, incrementos...)
 *   bonus  puntos del bono diario recién otorgado (para mostrar un aviso)
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined)
  const [rules, setRules] = useState(null)
  const [bonus, setBonus] = useState(0)

  const refresh = useCallback(async () => {
    try {
      const res = await fetchMe()
      setUser(res.user)
      setRules(res.rules)
      if (res.user?.bonus_granted) setBonus(res.user.bonus_granted)
      return res.user                                // el login lo usa para decidir a dónde ir
    } catch {
      setUser((u) => (u === undefined ? null : u))   // si falla la red, no se cierra la sesión visible
      return null
    }
  }, [])

  const logout = useCallback(async () => {
    try { await postLogout() } finally { setUser(null) }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  return (
    <AuthContext.Provider value={{ user, rules, bonus, clearBonus: () => setBonus(0), refresh, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export default function useAuth() {
  return useContext(AuthContext)
}
