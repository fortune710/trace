import { describe, expect, it } from "vitest"

import {
  DEFAULT_POSTHOG_HOST,
  getAnalyticsConfig,
} from "@/lib/analytics/config"

describe("getAnalyticsConfig", () => {
  it("defaults the host and disables when key is missing", () => {
    const config = getAnalyticsConfig({
      key: null,
      environment: "development",
      appMode: "web",
    })

    expect(config.apiHost).toBe(DEFAULT_POSTHOG_HOST)
    expect(config.enabled).toBe(false)
    expect(config.appSurface).toBe("web")
  })

  it("enables only outside test when a key is present", () => {
    expect(
      getAnalyticsConfig({
        key: "phc_test",
        environment: "production",
        appMode: "desktop",
      }).enabled,
    ).toBe(true)

    expect(
      getAnalyticsConfig({
        key: "phc_test",
        environment: "test",
        appMode: "web",
      }).enabled,
    ).toBe(false)
  })
})
