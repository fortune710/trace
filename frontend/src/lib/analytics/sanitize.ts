const SENSITIVE_QUERY_PARAMS = new Set([
  "token",
  "access_token",
  "refresh_token",
  "id_token",
  "code",
  "password",
  "secret",
  "api_key",
  "apikey",
  "auth",
  "authorization",
  "session",
  "session_id",
  "csrf",
  "csrf_token",
  "key",
  "private_key",
  "client_secret",
])

const SENSITIVE_PROPERTY_KEYS = new Set([
  "password",
  "token",
  "access_token",
  "refresh_token",
  "id_token",
  "api_key",
  "apikey",
  "secret",
  "authorization",
  "auth",
  "cookie",
  "csrf",
  "csrf_token",
  "private_key",
  "client_secret",
  "payload",
  "diff",
  "proposed_diff",
  "patch",
  "raw_code",
  "source_code",
  "file_contents",
  "body_markdown",
  "prompt",
  "prompt_text",
])

const SECRET_PATTERN =
  /(?:(?:password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]\s*\S+)|(?:bearer\s+[a-z0-9._-]+)|(?:sk-[a-z0-9]+)|(?:phc_[a-z0-9]+)/gi

export const REDACTED = "[redacted]"

function isSensitiveKey(key: string) {
  const normalized = key.toLowerCase()
  if (SENSITIVE_PROPERTY_KEYS.has(normalized)) return true
  return (
    normalized.includes("password") ||
    normalized.includes("secret") ||
    normalized.includes("token") ||
    normalized.includes("api_key") ||
    normalized.includes("apikey") ||
    normalized.includes("private_key") ||
    normalized === "key" ||
    normalized.endsWith("_secret")
  )
}

export function sanitizeUrl(url: string): string {
  try {
    const parsed = new URL(url, typeof window !== "undefined" ? window.location.origin : "https://trace.local")
    for (const key of [...parsed.searchParams.keys()]) {
      if (SENSITIVE_QUERY_PARAMS.has(key.toLowerCase())) {
        parsed.searchParams.set(key, REDACTED)
      }
    }
    return `${parsed.origin}${parsed.pathname}${parsed.search}${parsed.hash}`
  } catch {
    return url.replace(/([?&](token|code|password|secret|api_key|auth)=)[^&]*/gi, `$1${REDACTED}`)
  }
}

export function scrubString(value: string): string {
  return value.replace(SECRET_PATTERN, REDACTED)
}

export function sanitizeProperties(
  properties: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  if (!properties) return undefined

  const sanitized: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(properties)) {
    if (isSensitiveKey(key)) {
      sanitized[key] = REDACTED
      continue
    }
    sanitized[key] = sanitizeValue(value)
  }
  return sanitized
}

function sanitizeValue(value: unknown): unknown {
  if (value == null) return value
  if (typeof value === "string") return scrubString(value)
  if (typeof value === "number" || typeof value === "boolean") return value
  if (Array.isArray(value)) return value.map(sanitizeValue)
  if (typeof value === "object") {
    return sanitizeProperties(value as Record<string, unknown>)
  }
  return undefined
}

export function sanitizeLogAttributes(
  attributes: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  return sanitizeProperties(attributes)
}
