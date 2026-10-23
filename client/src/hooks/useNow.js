import { useEffect, useState } from 'react'

/**
 * Hora actual que se actualiza cada `intervalMs` (para cuentas regresivas).
 * `offsetMs` corrige la diferencia entre el reloj del navegador y el del servidor:
 * la hora de cierre la decide el servidor, no la computadora del usuario.
 */
export default function useNow(intervalMs = 1000, offsetMs = 0) {
  const [now, setNow] = useState(() => Date.now() + offsetMs)
  useEffect(() => {
    setNow(Date.now() + offsetMs)
    const t = setInterval(() => setNow(Date.now() + offsetMs), intervalMs)
    return () => clearInterval(t)
  }, [intervalMs, offsetMs])
  return now
}
