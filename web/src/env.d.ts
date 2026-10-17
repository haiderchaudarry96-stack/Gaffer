/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Gaffer FastAPI backend, e.g. https://gaffer.example.org. Empty = not connected. */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
