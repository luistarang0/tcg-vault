import { NavLink, Outlet } from 'react-router-dom'
import styles from './App.module.css'

// Plantilla común: encabezado con navegación y el contenido de la ruta (<Outlet />).
export default function App() {
  const linkClass = ({ isActive }) => (isActive ? `${styles.link} ${styles.active}` : styles.link)
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.logo}>TCG Vault</span>
        <nav className={styles.nav}>
          <NavLink to="/cartas" className={linkClass}>Catálogo</NavLink>
          <NavLink to="/registro" className={linkClass}>Registro</NavLink>
        </nav>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
      <footer className={styles.footer}>
        Proyecto escolar: práctica de scraping y defensas web. Solo para uso en localhost.
      </footer>
    </div>
  )
}
