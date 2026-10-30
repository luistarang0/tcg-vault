import { useEffect } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import useAuth from './hooks/useAuth.jsx'
import styles from './App.module.css'
import m from './pages/Market.module.css'

// Plantilla común: encabezado con navegación, saldo y el contenido de la ruta (<Outlet />).
export default function App() {
  const { user, bonus, clearBonus, logout } = useAuth()
  const navigate = useNavigate()
  const linkClass = ({ isActive }) => (isActive ? `${styles.link} ${styles.active}` : styles.link)

  // El aviso del bono diario se oculta solo
  useEffect(() => {
    if (!bonus) return
    const t = setTimeout(clearBonus, 6000)
    return () => clearTimeout(t)
  }, [bonus]) // eslint-disable-line react-hooks/exhaustive-deps

  const onLogout = async () => {
    await logout()
    navigate('/subastas')
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.logo}>TCG Vault</span>
        <nav className={styles.nav}>
          {user?.is_admin ? (
            // La cuenta de administrador es solo de seguridad: sin mercado, perfil ni puntos
            <>
              <NavLink to="/admin" className={linkClass}>Seguridad</NavLink>
              <span className={styles.link} title="Cuenta de administrador">@{user.username} · admin</span>
              <button type="button" className={styles.link} onClick={onLogout}>Salir</button>
            </>
          ) : user ? (
            <>
              <NavLink to="/cartas" className={linkClass}>Catálogo</NavLink>
              <NavLink to="/subastas" className={linkClass}>Subastas</NavLink>
              <NavLink to="/perfil" className={linkClass}>@{user.username}</NavLink>
              <span className={m.points} title="Puntos disponibles" data-points={user.points}>
                {user.points.toLocaleString('es-MX')} pts
              </span>
              <button type="button" className={styles.link} onClick={onLogout}>Salir</button>
            </>
          ) : user === null && (
            <>
              <NavLink to="/cartas" className={linkClass}>Catálogo</NavLink>
              <NavLink to="/subastas" className={linkClass}>Subastas</NavLink>
              <NavLink to="/entrar" className={linkClass}>Entrar</NavLink>
              <NavLink to="/registro" className={linkClass}>Registro</NavLink>
            </>
          )}
        </nav>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
      {bonus > 0 && (
        <div className={m.toast} role="status">
          <span>¡Bono diario! Recibiste {bonus} puntos.</span>
          <button type="button" onClick={clearBonus} aria-label="Cerrar">✕</button>
        </div>
      )}
      <footer className={styles.footer}>
        Proyecto escolar: práctica de scraping y defensas web. Los puntos no tienen valor real.
      </footer>
    </div>
  )
}
