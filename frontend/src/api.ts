export async function api<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = localStorage.getItem('cm_token')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(url, { ...init, headers })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }))
    if (response.status === 401 && token) {
      localStorage.removeItem('cm_token')
      localStorage.removeItem('cm_user')
      window.dispatchEvent(new Event('cm-auth-expired'))
    }
    throw Error(detail.detail || `Error ${response.status}`)
  }
  return response.json()
}
