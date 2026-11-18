import { useState, type FormEvent } from 'react'

export type SessionUser = { username: string; role: 'ADMIN' | 'CUSTOMER'; customer_id: string | null }
type AuthResponse = { access_token: string; user: SessionUser }

export default function Access({ onLogin }: { onLogin: (token: string, user: SessionUser) => void }) {
  const [register, setRegister] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    const form = new FormData(event.currentTarget)
    const username = String(form.get('username'))
    const password = String(form.get('password'))
    const body: Record<string, unknown> = { username, password }
    let path = '/api/auth/login'
    if (register) {
      path = '/api/auth/register'
      body.customer = {
        id: String(form.get('customer_id')),
        name: String(form.get('name')),
        income: Number(form.get('income')),
        obligations: Number(form.get('obligations')),
        employment: String(form.get('employment')),
        prior_credits: 0,
        late_payments: 0,
      }
    }
    try {
      const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await response.json()
      if (!response.ok) throw Error(data.detail || `Error ${response.status}`)
      const auth = data as AuthResponse
      onLogin(auth.access_token, auth.user)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return <main className="access-page"><section className="panel access-panel">
    <div className="brand access-brand"><div className="brand-mark">C</div><div><b>credi<span>market</span></b><small>PLATAFORMA DE CRÉDITO</small></div></div>
    <h1>{register ? 'Crea tu cuenta' : 'Ingresa a CrediMarket'}</h1>
    <p className="body-copy">{register ? 'Registra tu perfil para solicitar financiación.' : 'Usa tu cuenta de cliente o administrador.'}</p>
    {error && <div className="alert error" role="alert"><span>{error}</span></div>}
    <form className="form-panel access-form" onSubmit={submit}>
      <label className="field-label">Usuario<input name="username" minLength={3} maxLength={64} autoComplete="username" required /></label>
      <label className="field-label">Contraseña<input name="password" type="password" minLength={register ? 12 : 1} autoComplete={register ? 'new-password' : 'current-password'} required /></label>
      {register && <>
        <label className="field-label">Identificación de cliente<input name="customer_id" minLength={3} required /></label>
        <label className="field-label">Nombre<input name="name" required /></label>
        <div className="form-row"><label className="field-label">Ingreso mensual<input name="income" type="number" min="1" required /></label><label className="field-label">Obligaciones mensuales<input name="obligations" type="number" min="0" required /></label></div>
        <label className="field-label">Tipo de empleo<select name="employment" required><option value="dependiente">Dependiente</option><option value="independiente">Independiente</option><option value="temporal">Temporal</option></select></label>
      </>}
      <button className="primary access-submit" disabled={busy}>{busy ? 'Procesando…' : register ? 'Crear cuenta' : 'Iniciar sesión'}</button>
    </form>
    <button className="link-button access-switch" type="button" onClick={() => { setRegister(!register); setError('') }}>
      {register ? 'Ya tienes cuenta · Iniciar sesión' : '¿Eres nuevo? · Crear cuenta de cliente'}
    </button>
  </section></main>
}
