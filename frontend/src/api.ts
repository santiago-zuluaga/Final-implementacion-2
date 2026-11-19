export async function api<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = localStorage.getItem('cm_token')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response: Response
  try {
    response = await fetch(url, { ...init, headers })
  } catch {
    throw Error('No fue posible conectar con CrediMarket. Verifica que el frontend y las APIs estén disponibles.')
  }

  const raw = await response.text()
  let payload: unknown
  let validJson = false
  if (raw) {
    try {
      payload = JSON.parse(raw)
      validJson = true
    } catch {
      payload = raw
    }
  }

  if (!response.ok) {
    if (response.status === 401 && token) {
      localStorage.removeItem('cm_token')
      localStorage.removeItem('cm_user')
      window.dispatchEvent(new Event('cm-auth-expired'))
    }
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload
      ? payload.detail
      : undefined
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => typeof item === 'object' && item !== null && 'msg' in item ? item.msg : String(item)).join('; ')
        : `Error ${response.status}${response.statusText ? `: ${response.statusText}` : ''}`
    throw Error(message)
  }

  if (!raw) return undefined as T
  if (!validJson) throw Error('El servicio devolvió una respuesta que no es JSON válido.')
  return payload as T
}
