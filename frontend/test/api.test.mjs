import { afterEach, beforeEach, test } from 'node:test'
import assert from 'node:assert/strict'
import { api } from '../src/api.ts'
import { getLoanDetail, loansToPoll } from '../src/loans.ts'
import { LoanSubmissionAttempt } from '../src/loanSubmission.ts'
import { activateProduct, getProductDetail } from '../src/products.ts'

const originalFetch = globalThis.fetch
const values = new Map()
const authEvents = []

globalThis.localStorage = {
  getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
}
globalThis.window = { dispatchEvent: (event) => authEvents.push(event.type) }

beforeEach(() => {
  values.clear()
  authEvents.length = 0
})

afterEach(() => {
  globalThis.fetch = originalFetch
})

test('attaches the JWT and parses a real JSON response', async () => {
  values.set('cm_token', 'test-jwt')
  globalThis.fetch = async (_url, init) => {
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer test-jwt')
    return new Response(JSON.stringify([{ id: 17, name: 'Laptop' }]), { status: 200 })
  }
  assert.deepEqual(await api('/api/products'), [{ id: 17, name: 'Laptop' }])
})

test('loan detail uses the complete UUID and authenticated API request', async () => {
  const id = '124d5d25-183d-44d0-85f0-160f8d936878'
  values.set('cm_token', 'customer-jwt')
  globalThis.fetch = async (url, init) => {
    assert.equal(url, `/api/prestamos/${id}`)
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer customer-jwt')
    return new Response(JSON.stringify({ id, status: 'RECHAZADA' }), { status: 200 })
  }
  assert.equal((await getLoanDetail(id)).id, id)
})

test('loan polling includes only nonterminal records from the already-owned loan list', () => {
  const ownLoans = [
    { id: 'pending', status: 'PENDIENTE_INVENTARIO' },
    { id: 'canceling', status: 'CANCELACION_PENDIENTE' },
    { id: 'done', status: 'COMPLETADA' },
  ]
  assert.deepEqual(loansToPoll(ownLoans).map((loan) => loan.id), ['pending', 'canceling'])
})

test('loan retries preserve the idempotency key and original body until explicitly discarded', () => {
  const attempt = new LoanSubmissionAttempt()
  const firstBody = { customer_id: 'C-1', product_id: 2, quantity: 1, term_months: 12 }
  const first = attempt.getOrCreate(firstBody, () => 'fixed-key')
  const retry = attempt.getOrCreate({ ...firstBody, term_months: 24 }, () => { throw new Error('must reuse attempt') })
  assert.equal(retry.key, 'fixed-key')
  assert.deepEqual(retry.body, firstBody)
  firstBody.quantity = 3
  assert.equal(retry.body.quantity, 1)
  attempt.clear()
  assert.equal(attempt.current(), null)
  assert.equal(attempt.getOrCreate({ ...first.body, term_months: 24 }, () => 'new-key').key, 'new-key')
})

test('product details use the product service for CUSTOMER and ADMIN sessions', async () => {
  for (const [role, token] of [['CUSTOMER', 'customer-jwt'], ['ADMIN', 'admin-jwt']]) {
    values.set('cm_token', token)
    const productId = role === 'CUSTOMER' ? 17 : 23
    globalThis.fetch = async (url, init) => {
      assert.equal(url, `/api/products/${productId}`)
      assert.equal(new Headers(init.headers).get('Authorization'), `Bearer ${token}`)
      return new Response(JSON.stringify({ id: productId, name: `Producto ${productId}`, category: 'Accesorios', price_cop: 90000, version: 2, active: true, updated_at: '2026-11-18T12:00:00Z' }), { status: 200 })
    }
    assert.equal((await getProductDetail(productId)).id, productId)
  }
})

test('product detail reports a missing product and a service communication error', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Product not found' }), { status: 404 })
  await assert.rejects(getProductDetail(999999), /Product not found/)
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
  await assert.rejects(getProductDetail(1), /No fue posible conectar con CrediMarket/)
})

test('ADMIN requests inactive product details and can reactivate the original product', async () => {
  values.set('cm_token', 'admin-jwt')
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/api/products/2?include_inactive=true')
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer admin-jwt')
    return new Response(JSON.stringify({ id: 2, name: 'Teléfono de demostración', active: false }), { status: 200 })
  }
  assert.equal((await getProductDetail(2, true)).active, false)
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/api/products/2/activate')
    assert.equal(init.method, 'POST')
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer admin-jwt')
    return new Response(JSON.stringify({ id: 2, active: true, version: 5 }), { status: 200 })
  }
  assert.deepEqual(await activateProduct(2), { id: 2, active: true, version: 5 })
})

test('clears expired credentials and emits the session-expired event', async () => {
  values.set('cm_token', 'expired-jwt')
  values.set('cm_user', '{"username":"demo"}')
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Token expired' }), { status: 401 })
  await assert.rejects(api('/api/auth/me'), /Token expired/)
  assert.equal(values.has('cm_token'), false)
  assert.equal(values.has('cm_user'), false)
  assert.deepEqual(authEvents, ['cm-auth-expired'])
})

test('returns a useful HTTP message for an HTML gateway error', async () => {
  globalThis.fetch = async () => new Response('<html>upstream unavailable</html>', {
    status: 502,
    statusText: 'Bad Gateway',
    headers: { 'Content-Type': 'text/html' },
  })
  await assert.rejects(api('/api/inventory'), /Error 502: Bad Gateway/)
})

test('returns a user-facing message for a network failure', async () => {
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
  await assert.rejects(api('/api/products'), /No fue posible conectar con CrediMarket/)
})

test('accepts an empty successful response', async () => {
  globalThis.fetch = async () => new Response(null, { status: 204 })
  assert.equal(await api('/api/operation'), undefined)
})

test('preserves valid JSON string responses', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify('ok'), { status: 200 })
  assert.equal(await api('/api/status'), 'ok')
})
