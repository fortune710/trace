/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_APP_MODE?: string
  readonly VITE_APP_VERSION?: string
  readonly VITE_POSTHOG_HOST?: string
  readonly VITE_POSTHOG_KEY?: string
  readonly VITEST?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
