import { beforeEach, describe, expect, it, vi } from "vitest"

const posthogMocks = vi.hoisted(() => ({
  init: vi.fn(),
  identify: vi.fn(),
  reset: vi.fn(),
  capture: vi.fn(),
  captureException: vi.fn(),
  register: vi.fn(),
  setPersonProperties: vi.fn(),
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    trace: vi.fn(),
    fatal: vi.fn(),
  },
}))

vi.mock("posthog-js", () => ({
  default: posthogMocks,
}))

import {
  __resetAnalyticsForTests,
  __setAnalyticsStateForTests,
  captureAnalyticsException,
  getAnalyticsStatus,
  identifyUser,
  initAnalytics,
  logAnalytics,
  resetAnalytics,
  trackEvent,
} from "@/lib/analytics/client"
import { REDACTED } from "@/lib/analytics/sanitize"

describe("analytics client", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    __resetAnalyticsForTests()
  })

  it("no-ops when the PostHog key is unset", () => {
    const config = initAnalytics({ key: null, environment: "development" })

    expect(config.enabled).toBe(false)
    expect(posthogMocks.init).not.toHaveBeenCalled()

    trackEvent("auth_logout_clicked")
    identifyUser("user-1")
    resetAnalytics()
    logAnalytics("info", "hello")
    captureAnalyticsException(new Error("boom"))

    expect(posthogMocks.capture).not.toHaveBeenCalled()
    expect(posthogMocks.identify).not.toHaveBeenCalled()
    expect(posthogMocks.reset).not.toHaveBeenCalled()
    expect(posthogMocks.logger.info).not.toHaveBeenCalled()
    expect(posthogMocks.captureException).not.toHaveBeenCalled()
  })

  it("no-ops in the test environment even with a key", () => {
    const config = initAnalytics({
      key: "phc_test",
      environment: "test",
    })

    expect(config.enabled).toBe(false)
    expect(posthogMocks.init).not.toHaveBeenCalled()
  })

  it("initializes PostHog with privacy defaults when configured", () => {
    const config = initAnalytics({
      key: "phc_test",
      environment: "production",
      host: "https://us.i.posthog.com",
      appMode: "web",
    })

    expect(config.enabled).toBe(true)
    expect(posthogMocks.init).toHaveBeenCalledOnce()
    const [, options] = posthogMocks.init.mock.calls[0]
    expect(options.capture_pageview).toBe("history_change")
    expect(options.capture_pageleave).toBe("if_capture_pageview")
    expect(options.capture_performance).toBe(true)
    expect(options.capture_exceptions).toBe(true)
    expect(options.enable_recording_console_log).toBe(true)
    expect(options.session_recording.maskAllInputs).toBe(true)
    expect(options.logs.captureConsoleLogs).toBe(false)
  })

  it("identifies once and resets on logout", () => {
    initAnalytics({
      key: "phc_test",
      environment: "production",
      appMode: "web",
    })
    __setAnalyticsStateForTests({ initialized: true })

    identifyUser("user-1", { email: "a@example.com", display_name: "Ada" })
    identifyUser("user-1", { email: "a@example.com" })
    expect(posthogMocks.identify).toHaveBeenCalledOnce()
    expect(posthogMocks.setPersonProperties).toHaveBeenCalledOnce()
    expect(getAnalyticsStatus().identifiedUserId).toBe("user-1")

    resetAnalytics()
    expect(posthogMocks.reset).toHaveBeenCalledOnce()
    expect(getAnalyticsStatus().identifiedUserId).toBeNull()
  })

  it("tracks typed events with sanitized properties", () => {
    initAnalytics({
      key: "phc_test",
      environment: "production",
      appMode: "desktop",
    })
    __setAnalyticsStateForTests({ initialized: true })

    trackEvent("project_create_succeeded", {
      source: "github",
      category: "business",
    })

    expect(posthogMocks.capture).toHaveBeenCalledWith(
      "project_create_succeeded",
      expect.objectContaining({
        source: "github",
        category: "business",
      }),
    )

    trackEvent("settings_api_key_saved", {
      provider: "openai",
      action: "create",
    })
    expect(posthogMocks.capture).toHaveBeenCalledWith(
      "settings_api_key_saved",
      expect.objectContaining({ provider: "openai", action: "create" }),
    )
  })

  it("sanitizes exception and log payloads", () => {
    initAnalytics({
      key: "phc_test",
      environment: "production",
    })
    __setAnalyticsStateForTests({ initialized: true })

    captureAnalyticsException(new Error("failed"), {
      api_key: "secret",
      finding_id: "f1",
    })
    expect(posthogMocks.captureException).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({
        api_key: REDACTED,
        finding_id: "f1",
      }),
    )

    logAnalytics("warn", "retry", { token: "abc", attempt: 2 })
    expect(posthogMocks.logger.warn).toHaveBeenCalledWith(
      "retry",
      expect.objectContaining({ token: REDACTED, attempt: 2 }),
    )
  })
})
