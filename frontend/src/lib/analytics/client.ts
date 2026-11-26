import posthog, { type CaptureResult, type PostHog, type Properties } from "posthog-js"

import {
  getAnalyticsConfig,
  type AnalyticsConfig,
} from "@/lib/analytics/config"
import type {
  AnalyticsEventName,
  AnalyticsEventProperties,
} from "@/lib/analytics/events"
import { normalizeRoutePattern } from "@/lib/analytics/routes"
import {
  sanitizeLogAttributes,
  sanitizeProperties,
  sanitizeUrl,
} from "@/lib/analytics/sanitize"

export type IdentifyTraits = {
  email?: string | null
  display_name?: string | null
  automatic_pull_requests?: boolean
}

export type AnalyticsLogLevel = "trace" | "debug" | "info" | "warn" | "error" | "fatal"

type AnalyticsClientState = {
  config: AnalyticsConfig
  initialized: boolean
  identifiedUserId: string | null
}

const state: AnalyticsClientState = {
  config: getAnalyticsConfig(),
  initialized: false,
  identifiedUserId: null,
}

function client(): PostHog | null {
  if (!state.initialized || !state.config.enabled) return null
  return posthog
}

function enrichPageProperties(properties: Properties | undefined): Properties {
  const pathname =
    typeof window !== "undefined" ? window.location.pathname : "/"
  const href = typeof window !== "undefined" ? window.location.href : undefined
  return {
    ...sanitizeProperties(properties ?? {}),
    route_pattern: normalizeRoutePattern(pathname),
    ...(href ? { $current_url: sanitizeUrl(href) } : {}),
  }
}

function beforeSend(event: CaptureResult | null): CaptureResult | null {
  if (!event) return null

  const properties = sanitizeProperties(
    (event.properties ?? {}) as Record<string, unknown>,
  ) as Properties

  if (typeof properties.$current_url === "string") {
    properties.$current_url = sanitizeUrl(properties.$current_url)
  }
  if (typeof properties.$referrer === "string") {
    properties.$referrer = sanitizeUrl(properties.$referrer)
  }
  if (typeof properties.$pathname === "string") {
    properties.route_pattern =
      properties.route_pattern ?? normalizeRoutePattern(properties.$pathname)
  } else if (typeof window !== "undefined") {
    properties.route_pattern =
      properties.route_pattern ?? normalizeRoutePattern(window.location.pathname)
  }

  event.properties = properties
  return event
}

export function initAnalytics(
  overrides?: Parameters<typeof getAnalyticsConfig>[0],
): AnalyticsConfig {
  state.config = getAnalyticsConfig(overrides)

  if (!state.config.enabled || !state.config.key || state.initialized) {
    return state.config
  }

  posthog.init(state.config.key, {
    api_host: state.config.apiHost,
    ui_host: state.config.uiHost,
    defaults: "2026-08-30",
    capture_pageview: "history_change",
    capture_pageleave: "if_capture_pageview",
    capture_performance: true,
    capture_exceptions: true,
    enable_recording_console_log: true,
    persistence: "localStorage+cookie",
    person_profiles: "identified_only",
    before_send: beforeSend,
    session_recording: {
      maskAllInputs: true,
      maskInputOptions: {
        password: true,
      },
      maskTextSelector: ".ph-mask, [data-ph-mask]",
      blockClass: "ph-no-capture",
      maskCapturedNetworkRequestFn: (request) => {
        if (request.name) {
          request.name = sanitizeUrl(request.name)
        }
        return request
      },
    },
    logs: {
      serviceName: "trace-frontend",
      environment: state.config.environment,
      captureConsoleLogs: false,
      resourceAttributes: {
        "app.surface": state.config.appSurface,
      },
    },
    loaded: (instance) => {
      instance.register({
        app_surface: state.config.appSurface,
        app_environment: state.config.environment,
        app_version: import.meta.env.VITE_APP_VERSION ?? "0.0.0",
      })
    },
  })

  state.initialized = true
  return state.config
}

export function getAnalyticsStatus() {
  return {
    enabled: state.config.enabled,
    initialized: state.initialized,
    identifiedUserId: state.identifiedUserId,
    appSurface: state.config.appSurface,
    environment: state.config.environment,
  }
}

export function identifyUser(userId: string, traits: IdentifyTraits = {}) {
  const instance = client()
  if (!instance || !userId) return

  if (state.identifiedUserId === userId) {
    instance.setPersonProperties({
      ...(traits.email ? { email: traits.email } : {}),
      ...(traits.display_name ? { display_name: traits.display_name } : {}),
      ...(typeof traits.automatic_pull_requests === "boolean"
        ? { automatic_pull_requests: traits.automatic_pull_requests }
        : {}),
    })
    return
  }

  instance.identify(userId, {
    ...(traits.email ? { email: traits.email } : {}),
    ...(traits.display_name ? { display_name: traits.display_name } : {}),
    ...(typeof traits.automatic_pull_requests === "boolean"
      ? { automatic_pull_requests: traits.automatic_pull_requests }
      : {}),
  })
  state.identifiedUserId = userId
}

export function resetAnalytics() {
  const instance = client()
  state.identifiedUserId = null
  instance?.reset()
}

export function trackEvent<T extends AnalyticsEventName>(
  event: T,
  properties?: AnalyticsEventProperties<T>,
) {
  const instance = client()
  if (!instance) return

  instance.capture(
    event,
    sanitizeProperties(
      (properties ?? {}) as Record<string, unknown>,
    ) as Properties,
  )
}

export function captureAnalyticsException(
  error: unknown,
  properties?: Record<string, unknown>,
) {
  const instance = client()
  if (!instance) return

  const err =
    error instanceof Error
      ? error
      : new Error(typeof error === "string" ? error : "Unknown error")

  instance.captureException(
    err,
    sanitizeProperties(properties) as Properties | undefined,
  )
}

export function registerRouteContext(pathname: string) {
  const instance = client()
  if (!instance) return

  instance.register({
    route_pattern: normalizeRoutePattern(pathname),
  })
}

export function captureManualPageview(pathname: string) {
  const instance = client()
  if (!instance) return

  registerRouteContext(pathname)
  instance.capture("$pageview", enrichPageProperties({}))
}

export function logAnalytics(
  level: AnalyticsLogLevel,
  message: string,
  attributes?: Record<string, unknown>,
) {
  const instance = client()
  if (!instance?.logger) return

  const safeMessage = message.slice(0, 500)
  const safeAttributes = sanitizeLogAttributes(attributes) as
    | Record<string, string | number | boolean | null>
    | undefined

  switch (level) {
    case "trace":
      instance.logger.trace(safeMessage, safeAttributes)
      break
    case "debug":
      instance.logger.debug(safeMessage, safeAttributes)
      break
    case "info":
      instance.logger.info(safeMessage, safeAttributes)
      break
    case "warn":
      instance.logger.warn(safeMessage, safeAttributes)
      break
    case "error":
      instance.logger.error(safeMessage, safeAttributes)
      break
    case "fatal":
      instance.logger.fatal(safeMessage, safeAttributes)
      break
  }
}

/** Test-only helpers */
export function __resetAnalyticsForTests() {
  state.config = getAnalyticsConfig({ key: null, environment: "test" })
  state.initialized = false
  state.identifiedUserId = null
}

export function __setAnalyticsStateForTests(
  next: Partial<AnalyticsClientState>,
) {
  Object.assign(state, next)
}
