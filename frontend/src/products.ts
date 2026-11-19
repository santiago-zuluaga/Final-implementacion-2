import { api } from './api.ts'

export type ProductDetail = {
  id: number
  name: string
  category: string
  price_cop: number
  version: number
  active: boolean
  updated_at: string
}

export function getProductDetail(id: number, includeInactive = false) {
  const query = includeInactive ? '?include_inactive=true' : ''
  return api<ProductDetail>(`/api/products/${encodeURIComponent(id)}${query}`)
}

export function activateProduct(id: number) {
  return api<{ id: number; active: boolean; version: number }>(`/api/products/${encodeURIComponent(id)}/activate`, { method: 'POST' })
}
