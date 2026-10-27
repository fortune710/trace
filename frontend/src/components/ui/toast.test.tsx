// @vitest-environment jsdom

import { act, cleanup, render } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import {
  createToastManager,
  Toaster,
  ToastProvider,
  ToastViewport,
} from "@/components/ui/toast"

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

  it("stacks older toasts down from the top anchor", () => {
    const toastManager = createToastManager()
    render(<Toaster toastManager={toastManager} />)

    act(() => {
      toastManager.add({
        title: "Review queued",
        description: "Your review has been queued.",
      })
    })

    const toast = document.querySelector('[data-slot="toast"]')

    expect(toast?.className).toContain(
      "calc(var(--toast-index)*var(--gap))",
    )
    expect(toast?.className).toContain(
      "+(var(--toast-index)*var(--peek))",
    )
    expect(toast?.className).toContain(
      "+(var(--shrink)*var(--height))",
    )
  })
})
