import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Configuración de Vite.
// El proxy reenvía todo lo que empiece con /api al backend FastAPI (puerto 8000).
// Así el navegador ve un solo origen (localhost:5173): no hay problemas de CORS
// y la cookie `sid` del backend se guarda como cookie del mismo sitio.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
