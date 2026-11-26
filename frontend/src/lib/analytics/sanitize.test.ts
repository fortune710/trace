import { describe, expect, it } from "vitest"

import {
  REDACTED,
  sanitizeLogAttributes,
  sanitizeProperties,
  sanitizeUrl,
  scrubString,
} from "@/lib/analytics/sanitize"

describe("analytics sanitize", () => {
  it("redacts sensitive query params from URLs", () => {
    expect(
      sanitizeUrl("https://trace.app/auth/callback?token=abc&next=/projects"),
    ).toBe(
      `https://trace.app/auth/callback?token=${encodeURIComponent(REDACTED)}&next=%2Fprojects`,
    )
  })

  it("scrubs secret-looking substrings", () => {
    expect(scrubString("Authorization Bearer sk-live-secret")).toContain(REDACTED)
  })

  it("redacts sensitive property keys and nested values", () => {
    expect(
      sanitizeProperties({
        project_id: "proj_1",
        api_key: "should-not-leak",
        nested: { password: "hunter2", count: 2 },
      }),
    ).toEqual({
      project_id: "proj_1",
      api_key: REDACTED,
      nested: { password: REDACTED, count: 2 },
    })
  })

  it("sanitizes log attributes", () => {
    expect(
      sanitizeLogAttributes({
        message: "ok",
        token: "secret",
      }),
    ).toEqual({
      message: "ok",
      token: REDACTED,
    })
  })
})
