import { runtimeConfig } from "@/lib/runtime-config"

export const DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"
export const DEFAULT_POSTHOG_UI_HOST = "https://us.posthog.com"
export const POSTHOG_PROXY_PATH = "/ingest"

export type AnalyticsEnvironment = "development" | "test" | "production"

export type AnalyticsConfig = {
  apiHost: string
  appSurface: "web" | "desktop"
  enabled: boolean
  environment: AnalyticsEnvironment
  key: string | null
  uiHost: string
}

function readEnvironment(): AnalyticsEnvironment {
  if (import.meta.env.MODE === "test" || import.meta.env.VITEST) {
    return "test"
  }
  if (import.meta.env.PROD) {
    return "production"
  }
  return "development"
}

function readKey(): string | null {
  const key = import.meta.env.VITE_POSTHOG_KEY
  if (typeof key !== "string") return null
  const trimmed = key.trim()
  return trimmed.length > 0 ? trimmed : null
}

function readHost(): string {
  const host = import.meta.env.VITE_POSTHOG_HOST
  if (typeof host === "string" && host.trim().length > 0) {
    return host.trim().replace(/\/$/, "")
  }
  return DEFAULT_POSTHOG_HOST
}

export function getAnalyticsConfig(
  overrides: Partial<{
    appMode: "web" | "desktop"
    environment: AnalyticsEnvironment
    host: string
    key: string | null
  }> = {},
): AnalyticsConfig {
  const key = overrides.key === undefined ? readKey() : overrides.key
  const environment = overrides.environment ?? readEnvironment()
  const apiHost = overrides.host ?? readHost()
  const appSurface = overrides.appMode ?? runtimeConfig.appMode

  return {
    apiHost,
    appSurface,
    enabled: Boolean(key) && environment !== "test",
    environment,
    key,
    uiHost:
      apiHost.includes("eu.") || apiHost.startsWith("/eu")
        ? "https://eu.posthog.com"
        : DEFAULT_POSTHOG_UI_HOST,
  }
}
