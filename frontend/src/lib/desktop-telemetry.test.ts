import { describe, expect, it, vi } from "vitest"

import { createDesktopTelemetry } from "@/lib/desktop-telemetry"

function dependencies() {
  const execute = vi.fn().mockResolvedValue({ rowsAffected: 1 })
  return {
    execute,
    isDesktop: () => true,
    loadDatabase: vi.fn().mockResolvedValue({ execute }),
    platform: vi.fn().mockResolvedValue({
      operatingSystem: "windows",
      architecture: "x86_64",
    }),
    compress: vi.fn(async (payload: string) =>
      JSON.stringify({ v: 1, codec: "gzip+base64", data: btoa(payload) }),
    ),
    now: () => "2026-10-29T00:00:00.000Z",
    createRequestId: () => "client-request-1",
  }
}

describe("desktop telemetry", () => {
  it("writes a compressed, redacted local log with OS and request IDs", async () => {
    const values = dependencies()
    const telemetry = createDesktopTelemetry(values)

    await telemetry.record({
      event: "api.request.failed",
      userId: "user-1",
      serverRequestId: "server-request-1",
      errorCode: "request_failed",
      httpStatus: 500,
    })

    expect(values.compress).toHaveBeenCalledOnce()
    const payload = JSON.parse(values.compress.mock.calls[0][0])
    expect(payload).toEqual({
      event: "api.request.failed",
      occurred_at: "2026-10-29T00:00:00.000Z",
      operating_system: "windows",
      architecture: "x86_64",
      user_id: "user-1",
      request_id: "client-request-1",
      server_request_id: "server-request-1",
      error_code: "request_failed",
      http_status: 500,
    })
    expect(JSON.stringify(payload)).not.toContain("canonical_path")
    expect(values.execute).toHaveBeenNthCalledWith(1, "BEGIN IMMEDIATE")
    expect(values.execute).toHaveBeenNthCalledWith(
      2,
      "INSERT INTO desktop_telemetry (log_data) VALUES ($1)",
      [expect.stringContaining('"codec":"gzip+base64"')],
    )
    expect(values.execute).toHaveBeenNthCalledWith(
      3,
      expect.stringContaining("MAX(id) - 10000"),
    )
    expect(values.execute).toHaveBeenNthCalledWith(4, "COMMIT")
  })

  it("does not write telemetry outside the desktop runtime", async () => {
    const values = dependencies()
    const telemetry = createDesktopTelemetry({ ...values, isDesktop: () => false })

    await telemetry.record({ event: "local_remediation.apply.started" })

    expect(values.loadDatabase).not.toHaveBeenCalled()
    expect(values.compress).not.toHaveBeenCalled()
  })

  it("swallows a local telemetry storage failure", async () => {
    const values = dependencies()
    values.execute.mockRejectedValueOnce(new Error("disk full"))
    const telemetry = createDesktopTelemetry(values)

    await expect(
      telemetry.record({ event: "local_remediation.apply.failed" }),
    ).resolves.toBeUndefined()
  })
})
