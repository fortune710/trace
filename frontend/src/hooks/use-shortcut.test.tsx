// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react"
import { useState } from "react"
import { describe, expect, it } from "vitest"

import { useShortcut } from "@/hooks/use-shortcut"

function ShortcutHarness({ enabled = true }: { enabled?: boolean }) {
  const [count, setCount] = useState(0)
  useShortcut({ enabled, key: "n", onTrigger: () => setCount((value) => value + 1) })
  return <output>{count}</output>
}

describe("useShortcut", () => {
  it.each(["metaKey", "ctrlKey"] as const)("triggers and prevents the default for %s + N", (modifier) => {
    render(<ShortcutHarness />)
    const event = new KeyboardEvent("keydown", { key: "n", [modifier]: true, cancelable: true })

    fireEvent(window, event)

    expect(event.defaultPrevented).toBe(true)
    expect(screen.getByText("1")).toBeTruthy()
  })

  it("ignores repeated and disabled shortcuts", () => {
    const { rerender } = render(<ShortcutHarness />)
    fireEvent(window, new KeyboardEvent("keydown", { key: "n", metaKey: true, repeat: true, cancelable: true }))
    expect(screen.getByText("0")).toBeTruthy()

    rerender(<ShortcutHarness enabled={false} />)
    fireEvent(window, new KeyboardEvent("keydown", { key: "n", ctrlKey: true, cancelable: true }))
    expect(screen.getByText("0")).toBeTruthy()
  })
})
