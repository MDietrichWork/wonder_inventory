/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Password for the MVP client-side Admin gate. Set in .env / build env. */
  readonly VITE_ADMIN_PASSWORD?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
