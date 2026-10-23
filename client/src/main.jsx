import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './global.css'
import App from './App.jsx'
import { AuthProvider } from './hooks/useAuth.jsx'
import AuctionPage from './pages/AuctionPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import MarketPage from './pages/MarketPage.jsx'
import ProfilePage from './pages/ProfilePage.jsx'
import PublicProfilePage from './pages/PublicProfilePage.jsx'
import CardsPage from './pages/CardsPage.jsx'
import CardDetailPage from './pages/CardDetailPage.jsx'
import RegisterPage from './pages/RegisterPage.jsx'

// Rutas de la SPA:
//   /cartas         catálogo con filtros y paginación en la URL
//   /cartas/:id     detalle de una carta
//   /subastas       mercado de subastas (público)
//   /subastas/:id   detalle y pujas
//   /registro       crear cuenta (con honeypot y demás defensas)
//   /entrar         iniciar sesión
//   /perfil         colección, subastas y pujas propias (requiere sesión)
//   /u/:username    perfil público
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Navigate to="/cartas" replace />} />
          <Route path="cartas" element={<CardsPage />} />
          <Route path="cartas/:id" element={<CardDetailPage />} />
          <Route path="subastas" element={<MarketPage />} />
          <Route path="subastas/:id" element={<AuctionPage />} />
          <Route path="registro" element={<RegisterPage />} />
          <Route path="entrar" element={<LoginPage />} />
          <Route path="perfil" element={<ProfilePage />} />
          <Route path="u/:username" element={<PublicProfilePage />} />
          <Route path="*" element={<p>Página no encontrada.</p>} />
        </Route>
      </Routes>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
