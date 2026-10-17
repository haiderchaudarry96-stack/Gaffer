/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * The Gaffer FastAPI backend. Empty / unset = not connected (static demo build);
   * "/" or "same-origin" = the API is on the server that serves this site (one uvicorn);
   * a URL (e.g. http://localhost:8000) = the API on another origin (Vite dev server).
   */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
