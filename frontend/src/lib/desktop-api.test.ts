// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest"

import { authApi } from "@/lib/api"

const invoke = vi.hoisted(() => vi.fn())
vi.mock("@tauri-apps/api/core", () => ({
  isTauri: () => true,
  invoke,
}))

describe("desktop API transport", () => {
  beforeEach(() => {
    invoke.mockReset()
  })

  it("parses a native JSON response and sends the session request through Rust", async () => {
    invoke.mockResolvedValueOnce({
      status: 200,
      body: JSON.stringify({ user_id: "user-1", session_id: "session-1" }),
      retryAfter: null,
      requestId: "request-1",
    })

    await expect(authApi.session()).resolves.toMatchObject({ user_id: "user-1" })
    expect(invoke).toHaveBeenCalledWith("desktop_http_request", {
      request: expect.objectContaining({
        path: "/auth/session",
        method: "GET",
      }),
    })
  })

  it("preserves native HTTP error status and request ID", async () => {
    invoke.mockResolvedValueOnce({
      status: 401,
      body: JSON.stringify({
        error: { code: "session_expired", message: "Session expired", request_id: "request-2" },
      }),
      retryAfter: null,
      requestId: "request-2",
    })

    await expect(authApi.session()).rejects.toMatchObject({
      status: 401,
      code: "session_expired",
      requestId: "request-2",
    })
  })
})
