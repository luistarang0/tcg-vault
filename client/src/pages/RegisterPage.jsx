import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { postRegister } from '../api.js'
import TurnstileWidget from '../components/TurnstileWidget.jsx'
import useAuth from '../hooks/useAuth.jsx'
import useBehaviorTracker from '../hooks/useBehaviorTracker.js'
import useDynamicDom from '../hooks/useDynamicDom.js'
import styles from './Page.module.css'

const EMPTY = { collector_name: '', email: '', password: '', website: '' }

/**
 * Registro de coleccionista: crea la cuenta, da puntos iniciales y un sobre de
 * cartas, y deja la sesión iniciada. Lo protegen las cinco defensas:
 *  1. Rate limiting (servidor): 429 con cuenta regresiva.
 *  2. Huellas de automatización (servidor): se registran en logs/access.jsonl.
 *  3. Métricas de interacción (useBehaviorTracker) + honeypot `website`.
 *  4. Turnstile: si el servidor responde 403 con challenge_required, se muestra
 *     el widget y se reenvía el formulario con el token.
 *  5. DOM dinámico: IDs y clases del formulario cambian en cada carga (useDynamicDom).
 *     Los `name` de los inputs no cambian: el servidor los necesita.
 * El cliente valida para dar retroalimentación; el servidor vuelve a validar y decide.
 */
export default function RegisterPage() {
  const [form, setForm] = useState(EMPTY)
  const [errors, setErrors] = useState({})
  const [status, setStatus] = useState(null)       // { kind: 'ok' | 'warn', text }
  const [sending, setSending] = useState(false)
  const [cooldown, setCooldown] = useState(0)      // segundos restantes tras un 429
  const [challenge, setChallenge] = useState(null) // { sitekey } cuando el servidor pide desafío
  const [token, setToken] = useState(null)         // token de Turnstile (un solo uso)
  const [widgetKey, setWidgetKey] = useState(0)    // cambiarlo vuelve a crear el widget
  const tracker = useBehaviorTracker()
  const dyn = useDynamicDom()
  const { refresh } = useAuth()
  const navigate = useNavigate()

  const update = (e) => setForm({ ...form, [e.target.name]: e.target.value })

  // Validación del lado del cliente (las mismas reglas que el modelo Pydantic)
  const validate = () => {
    const errs = {}
    if (!/^[\p{L}\p{N}_.-]{3,24}$/u.test(form.collector_name.trim())) {
      errs.collector_name = 'De 3 a 24 letras, números, punto, guion o guion bajo (sin espacios).'
    }
    if (!/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(form.email)) errs.email = 'Correo inválido.'
    if (form.password.length < 8) errs.password = 'Mínimo 8 caracteres.'
    return errs
  }

  // Cuenta regresiva visible tras recibir 429
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
    const errs = validate()
    setErrors(errs)
    if (Object.keys(errs).length) return

    setSending(true)
    try {
      const res = await postRegister({
        ...form,
        behavior: tracker.snapshot(),          // métricas de interacción (Defensa 3)
        turnstile_token: token,                // solo existe si se resolvió el desafío
      })
      setStatus({ kind: 'ok', text: res.message })
      setForm(EMPTY)                           // no se conserva la contraseña en memoria
      setChallenge(null)
      tracker.reset()
      await refresh()                          // el servidor ya dejó la sesión iniciada
      navigate('/perfil', { state: { welcome: res.message } })
    } catch (err) {
      if (err.status === 429) startCooldown(err.retryAfter)
      if (err.status === 403 && err.details?.challenge_required) {
        setChallenge({ sitekey: err.details.sitekey || import.meta.env.VITE_TURNSTILE_SITEKEY })
        setWidgetKey((k) => k + 1)             // widget nuevo: el token anterior ya se usó
        setStatus({ kind: 'warn', text: err.details.error || 'Confirma que eres humano.' })
      } else {
        setStatus({ kind: 'warn', text: err.message })
      }
    } finally {
      setToken(null)                           // los tokens de Turnstile son de un solo uso
      setSending(false)
    }
  }

  const blocked = sending || cooldown > 0 || (challenge && !token)

  return (
    <section>
      <h1 className={styles.title}>Registro de coleccionista</h1>
      <p className={styles.subtitle}>
        Crea tu cuenta y recibe puntos para pujar y un sobre con cartas aleatorias.
        ¿Ya tienes cuenta? <Link to="/entrar">Inicia sesión</Link>.
      </p>

      <form className={dyn.cls(styles.form)} id={dyn.id('form-registro')} onSubmit={onSubmit} noValidate {...tracker.handlers}>
        <label className={styles.field}>
          <span>Nombre de coleccionista</span>
          <input className={dyn.cls(styles.input)} id={dyn.id('nombre')} name="collector_name" value={form.collector_name}
                 onChange={update} autoComplete="nickname" required />
          {errors.collector_name && <small className={styles.error}>{errors.collector_name}</small>}
        </label>

        <label className={styles.field}>
          <span>Correo</span>
          <input className={dyn.cls(styles.input)} id={dyn.id('correo')} name="email" type="email" value={form.email}
                 onChange={update} autoComplete="email" required />
          {errors.email && <small className={styles.error}>{errors.email}</small>}
        </label>

        <label className={styles.field}>
          <span>Contraseña</span>
          <input className={dyn.cls(styles.input)} id={dyn.id('contrasena')} name="password" type="password" value={form.password}
                 onChange={update} autoComplete="new-password" required />
          {errors.password && <small className={styles.error}>{errors.password}</small>}
        </label>

        {/* Honeypot: no lo ve una persona ni un lector de pantalla, ni se alcanza con Tab */}
        <div className={styles.honeypot} aria-hidden="true">
          <label>
            Sitio web
            <input name="website" value={form.website} onChange={update}
                   tabIndex={-1} autoComplete="off" />
          </label>
        </div>

        {/* Defensa 4: solo aparece cuando el servidor exige el desafío */}
        {challenge && (
          <div className={styles.challenge}>
            <p>Verificación de seguridad</p>
            <TurnstileWidget
              key={widgetKey}
              sitekey={challenge.sitekey}
              onToken={setToken}
              onError={(msg) => setStatus({ kind: 'warn', text: msg })}
            />
          </div>
        )}

        <button className={dyn.cls(styles.submit)} id={dyn.id('btn-registrar')} type="submit" disabled={blocked}>
          {sending ? 'Enviando…'
            : cooldown > 0 ? `Espera ${cooldown} s`
              : challenge && !token ? 'Completa la verificación'
                : 'Registrarme'}
        </button>

        {status && (
          <div className={`${styles.alert} ${styles[status.kind]}`} role="status">{status.text}</div>
        )}
      </form>
    </section>
  )
}
