import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const upstream = (name: string, fallback: string) => env[name] || fallback
  const proxy = {
    '/api/health/products': { target: upstream('VITE_PRODUCTS_API_URL', 'http://localhost:8001'), rewrite: () => '/health' },
    '/api/health/customers': { target: upstream('VITE_CUSTOMERS_API_URL', 'http://localhost:8002'), rewrite: () => '/health' },
    '/api/health/loans': { target: upstream('VITE_LOANS_API_URL', 'http://localhost:8003'), rewrite: () => '/health' },
    '/api/health/inventory': { target: upstream('VITE_INVENTORY_API_URL', 'http://localhost:8004'), rewrite: () => '/health' },
    '/api/auth': { target: upstream('VITE_CUSTOMERS_API_URL', 'http://localhost:8002'), rewrite: (path: string) => path.replace(/^\/api/, '') },
    '/api/products': { target: upstream('VITE_PRODUCTS_API_URL', 'http://localhost:8001'), rewrite: (path: string) => path.replace(/^\/api/, '') },
    '/api/customers': { target: upstream('VITE_CUSTOMERS_API_URL', 'http://localhost:8002'), rewrite: (path: string) => path.replace(/^\/api/, '') },
    '/api/inventory': { target: upstream('VITE_INVENTORY_API_URL', 'http://localhost:8004'), rewrite: (path: string) => path.replace(/^\/api/, '') },
    '/api/prestamos': { target: upstream('VITE_LOANS_API_URL', 'http://localhost:8003'), rewrite: (path: string) => path.replace(/^\/api/, '') },
    '/api/modelo': { target: upstream('VITE_LOANS_API_URL', 'http://localhost:8003'), rewrite: (path: string) => path.replace(/^\/api/, '') },
    '/api/monitoring': { target: upstream('VITE_LOANS_API_URL', 'http://localhost:8003'), rewrite: (path: string) => path.replace(/^\/api/, '') },
    '/api/drift': { target: upstream('VITE_LOANS_API_URL', 'http://localhost:8003'), rewrite: (path: string) => path.replace(/^\/api/, '') },
  }

  return {
    plugins: [react()],
    define: { 'process.env.NODE_ENV': JSON.stringify('production') },
    server: { proxy },
  }
})
