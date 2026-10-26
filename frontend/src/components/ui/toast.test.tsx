// @vitest-environment jsdom

import { cleanup, render } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { ToastProvider, ToastViewport } from "@/components/ui/toast"

describe("ToastViewport", () => {
  afterEach(cleanup)

  it("positions the accessible toast stack in the top-right corner", () => {
    const { container } = render(
      <ToastProvider>
        <ToastViewport aria-label="Notifications" />
      </ToastProvider>,
    )
    const viewport = container.querySelector('[data-slot="toast-viewport"]')

    expect(viewport?.getAttribute("aria-label")).toBe("Notifications")
    expect(viewport?.className).toContain("top-4")
    expect(viewport?.className).toContain("sm:right-4")
    expect(viewport?.className).not.toContain("bottom-4")
  })
})
