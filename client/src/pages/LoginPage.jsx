import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { postLogin } from '../api.js'
import TurnstileWidget from '../components/TurnstileWidget.jsx'
import useAuth from '../hooks/useAuth.jsx'
import useBehaviorTracker from '../hooks/useBehaviorTracker.js'
import useDynamicDom from '../hooks/useDynamicDom.js'
import styles from './Page.module.css'

const EMPTY = { username: '', password: '', website: '' }

/**
 * Inicio de sesión con las mismas defensas del registro:
 * rate limit (429 con cuenta regresiva), métricas de interacción + honeypot,
 * Turnstile escalonado y DOM dinámico. Además el servidor bloquea la CUENTA
 * tras varios fallos seguidos, aunque el atacante cambie de IP.
 */
export default function LoginPage() {
  const [form, setForm] = useState(EMPTY)
  const [status, setStatus] = useState(null)
  const [sending, setSending] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const [challenge, setChallenge] = useState(null)
  const [token, setToken] = useState(null)
  const [widgetKey, setWidgetKey] = useState(0)
  const tracker = useBehaviorTracker()
  const dyn = useDynamicDom()
  const { refresh } = useAuth()
  const navigate = useNavigate()

  const update = (e) => setForm({ ...form, [e.target.name]: e.target.value })

  const startCooldown = (seconds) => {
    setCooldown(seconds)
    const timer = setInterval(() => {
      setCooldown((s) => {
        if (s <= 1) { clearInterval(timer); return 0 }
        return s - 1
      })
    }, 1000)
  }

  const onSubmit = async (e) => {
    e.preventDefault()
    setStatus(null)
    if (form.username.trim().length < 3 || !form.password) {
      setStatus({ kind: 'warn', text: 'Escribe tu nombre (o correo) y tu contraseña.' })
      return
    }
    setSending(true)
    try {
      await postLogin({ ...form, behavior: tracker.snapshot(), turnstile_token: token })
      const u = await refresh()
      navigate(u?.is_admin ? '/admin' : '/perfil')   // el administrador va directo a seguridad
    } catch (err) {
      if (err.status === 429) startCooldown(err.retryAfter)
      if (err.status === 403 && err.details?.challenge_required) {
        setChallenge({ sitekey: err.details.sitekey || import.meta.env.VITE_TURNSTILE_SITEKEY })
        setWidgetKey((k) => k + 1)
        setStatus({ kind: 'warn', text: err.details.error || 'Confirma que eres humano.' })
      } else {
        setStatus({ kind: 'warn', text: err.message })
      }
      setForm((f) => ({ ...f, password: '' }))
    } finally {
      setToken(null)
      setSending(false)
    }
  }

  const blocked = sending || cooldown > 0 || (challenge && !token)

  return (
    <section>
      <h1 className={styles.title}>Iniciar sesión</h1>
      <p className={styles.subtitle}>
        ¿Aún no tienes cuenta? <Link to="/registro">Regístrate</Link> y recibe puntos y un sobre de cartas.
      </p>

      <form className={dyn.cls(styles.form)} id={dyn.id('form-login')} onSubmit={onSubmit} noValidate {...tracker.handlers}>
        <label className={styles.field}>
          <span>Nombre de coleccionista o correo</span>
          <input className={dyn.cls(styles.input)} id={dyn.id('usuario')} name="username" value={form.username}
                 onChange={update} autoComplete="username" required />
        </label>
        <label className={styles.field}>
          <span>Contraseña</span>
          <input className={dyn.cls(styles.input)} id={dyn.id('contrasena')} name="password" type="password"
                 value={form.password} onChange={update} autoComplete="current-password" required />
        </label>

        <div className={styles.honeypot} aria-hidden="true">
          <label>
            Sitio web
            <input name="website" value={form.website} onChange={update} tabIndex={-1} autoComplete="off" />
          </label>
        </div>

        {challenge && (
          <div className={styles.challenge}>
            <p>Verificación de seguridad</p>
            <TurnstileWidget key={widgetKey} sitekey={challenge.sitekey} onToken={setToken}
                             onError={(msg) => setStatus({ kind: 'warn', text: msg })} />
          </div>
        )}

        <button className={dyn.cls(styles.submit)} id={dyn.id('btn-entrar')} type="submit" disabled={blocked}>
          {sending ? 'Entrando…'
            : cooldown > 0 ? `Espera ${cooldown} s`
              : challenge && !token ? 'Completa la verificación'
                : 'Entrar'}
        </button>

        {status && <div className={`${styles.alert} ${styles[status.kind]}`} role="status">{status.text}</div>}
      </form>
    </section>
  )
}
