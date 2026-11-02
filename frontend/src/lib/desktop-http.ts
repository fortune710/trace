import { invoke } from "@tauri-apps/api/core"
import { runtimeConfig } from "@/lib/runtime-config"

type DesktopBody =
  | { kind: "text"; value: string }
  | {
      kind: "multipart"
      fields: Array<{
        name: string
        value: string | number[]
        filename?: string
        contentType?: string
      }>
    }

export type DesktopRequest = {
  baseUrl: string
  path: string
  method: "GET" | "POST" | "PATCH" | "DELETE"
  headers: Record<string, string>
  body: DesktopBody | null
}

export type DesktopResponse = {
  status: number
  body: string
  retryAfter: string | null
  requestId: string | null
}

export async function parseDesktopRequest(
  path: string,
  init: RequestInit,
): Promise<DesktopRequest> {
  if (Object.keys(init).some((key) => !["method", "headers", "body"].includes(key))) {
    throw new TypeError("Unsupported desktop API request option")
  }

  if (
    !path.startsWith("/") ||
    path.startsWith("//") ||
    path.includes("\\") ||
    path.includes("#")
  ) {
    throw new TypeError("Invalid desktop API path")
  }

  const method = (init.method ?? "GET").toUpperCase()
  if (!["GET", "POST", "PATCH", "DELETE"].includes(method)) {
    throw new TypeError("Unsupported desktop API method")
  }

  const headers = Object.fromEntries(new Headers(init.headers).entries())
  for (const name of Object.keys(headers)) {
    if (
      !["content-type", "x-csrf-token", "idempotency-key"].includes(
        name.toLowerCase(),
      )
    ) {
      throw new TypeError("Unsupported desktop API header")
    }
  }

  let body: DesktopBody | null = null
  if (typeof init.body === "string") {
    body = { kind: "text", value: init.body }
  } else if (init.body instanceof FormData) {
    const fields: Extract<DesktopBody, { kind: "multipart" }>["fields"] = []
    for (const [name, value] of init.body.entries()) {
      if (typeof value === "string") {
        fields.push({ name, value })
      } else {
        fields.push({
          name,
          value: Array.from(new Uint8Array(await value.arrayBuffer())),
          filename: value.name,
          contentType: value.type || "application/octet-stream",
        })
      }
    }
    delete headers["content-type"]
    body = { kind: "multipart", fields }
  } else if (init.body != null) {
    throw new TypeError("Unsupported desktop API body")
  }

  if ((method === "GET" || method === "DELETE") && body !== null) {
    throw new TypeError("Desktop API method cannot include a body")
  }

  return {
    baseUrl: runtimeConfig.apiBaseUrl,
    path,
    method: method as DesktopRequest["method"],
    headers,
    body,
  }
}

export async function desktopRequest(
  path: string,
  init: RequestInit,
): Promise<DesktopResponse> {
  const request = await parseDesktopRequest(path, init)
  return invoke<DesktopResponse>("desktop_http_request", { request })
}
