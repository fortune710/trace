// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest"

import { desktopRequest, parseDesktopRequest } from "@/lib/desktop-http"

const invoke = vi.hoisted(() => vi.fn())
vi.mock("@tauri-apps/api/core", () => ({ invoke }))

describe("parseDesktopRequest", () => {
  it("parses a JSON request and normalizes its method and headers", async () => {
    await expect(parseDesktopRequest("/auth/oauth/desktop/exchange", {
      method: "post",
      headers: new Headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ code: "ticket", verifier: "proof" }),
    })).resolves.toEqual({
      baseUrl: "http://localhost:8000",
      path: "/auth/oauth/desktop/exchange",
      method: "POST",
      headers: { "content-type": "application/json" },
      body: { kind: "text", value: '{"code":"ticket","verifier":"proof"}' },
    })
  })

  it("parses a multipart file without losing its bytes", async () => {
    const form = new FormData()
    form.append("config", '{"eyes":"open"}')
    form.append("file", new File([new Uint8Array([0, 1, 255])], "avatar.png", { type: "image/png" }))

    const parsed = await parseDesktopRequest("/api/v1/agents/agent-1/avatar", {
      method: "POST",
      body: form,
    })

    expect(parsed.body).toEqual({
      kind: "multipart",
      fields: [
        { name: "config", value: '{"eyes":"open"}' },
        { name: "file", value: [0, 1, 255], filename: "avatar.png", contentType: "image/png" },
      ],
    })
  })

  it.each([
    ["external URL", "https://example.com/auth/session", { method: "GET" }],
    ["protocol-relative URL", "//example.com/auth/session", { method: "GET" }],
    ["unsupported method", "/auth/session", { method: "PUT" }],
    ["unsupported header", "/auth/session", { headers: { Cookie: "secret" } }],
    ["unsupported body", "/auth/session", { method: "POST", body: new Blob(["data"]) }],
    ["GET with body", "/auth/session", { method: "GET", body: "data" }],
    ["unsupported request option", "/auth/session", { cache: "no-store" }],
  ])("rejects %s", async (_description, path, init) => {
    await expect(parseDesktopRequest(path as string, init as RequestInit)).rejects.toThrow()
  })

  it("passes the parsed request to the desktop command", async () => {
    invoke.mockResolvedValueOnce({ status: 200, body: "{}", retryAfter: null, requestId: null })

    await desktopRequest("/auth/session", { method: "GET" })

    expect(invoke).toHaveBeenCalledWith("desktop_http_request", {
      request: {
        baseUrl: "http://localhost:8000",
        path: "/auth/session",
        method: "GET",
        headers: {},
        body: null,
      },
    })
  })
})
