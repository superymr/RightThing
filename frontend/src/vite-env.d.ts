/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端地址；留空则用同源（生产由 FastAPI 托管 dist，开发由 Vite 代理） */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
