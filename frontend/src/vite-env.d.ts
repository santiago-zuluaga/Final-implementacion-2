/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MLFLOW_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
