export {
  captureAnalyticsException,
  captureManualPageview,
  getAnalyticsStatus,
  identifyUser,
  initAnalytics,
  logAnalytics,
  registerRouteContext,
  resetAnalytics,
  trackEvent,
  type AnalyticsLogLevel,
  type IdentifyTraits,
} from "@/lib/analytics/client"
export {
  DEFAULT_POSTHOG_HOST,
  getAnalyticsConfig,
  POSTHOG_PROXY_PATH,
  type AnalyticsConfig,
  type AnalyticsEnvironment,
} from "@/lib/analytics/config"
export type {
  AnalyticsEventMap,
  AnalyticsEventName,
  AnalyticsEventProperties,
} from "@/lib/analytics/events"
export { normalizeRoutePattern } from "@/lib/analytics/routes"
export {
  REDACTED,
  sanitizeLogAttributes,
  sanitizeProperties,
  sanitizeUrl,
  scrubString,
} from "@/lib/analytics/sanitize"
