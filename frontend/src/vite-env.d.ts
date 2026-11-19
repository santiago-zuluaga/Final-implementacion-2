/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MLFLOW_URL?: string
  readonly VITE_PRODUCTS_API_URL?: string
  readonly VITE_CUSTOMERS_API_URL?: string
  readonly VITE_LOANS_API_URL?: string
  readonly VITE_INVENTORY_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
