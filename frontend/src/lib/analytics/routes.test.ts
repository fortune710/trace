import { describe, expect, it } from "vitest"

import { normalizeRoutePattern } from "@/lib/analytics/routes"

describe("normalizeRoutePattern", () => {
  it("maps dynamic segments to stable patterns", () => {
    expect(normalizeRoutePattern("/projects/abc-123")).toBe("/projects/:projectId")
    expect(normalizeRoutePattern("/reviews/r1/findings/f2")).toBe(
      "/reviews/:reviewId/findings/:findingId",
    )
    expect(normalizeRoutePattern("/agents/agent-9")).toBe("/agents/:agentId")
  })

  it("keeps static routes intact", () => {
    expect(normalizeRoutePattern("/sign-in")).toBe("/sign-in")
    expect(normalizeRoutePattern("/settings/api-keys")).toBe("/settings/api-keys")
    expect(normalizeRoutePattern("/")).toBe("/")
  })
})
