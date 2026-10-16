import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './global.css'
import App from './App.jsx'
import CardsPage from './pages/CardsPage.jsx'
import CardDetailPage from './pages/CardDetailPage.jsx'
import RegisterPage from './pages/RegisterPage.jsx'

// Rutas de la SPA:
//   /cartas         catálogo con filtros y paginación en la URL
//   /cartas/:id     detalle de una carta
//   /registro       formulario principal (con honeypot)
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Navigate to="/cartas" replace />} />
          <Route path="cartas" element={<CardsPage />} />
          <Route path="cartas/:id" element={<CardDetailPage />} />
          <Route path="registro" element={<RegisterPage />} />
          <Route path="*" element={<p>Página no encontrada.</p>} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
