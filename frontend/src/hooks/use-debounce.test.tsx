// @vitest-environment jsdom

import { render, screen } from "@testing-library/react"
import { act } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useDebounce } from "@/hooks/use-debounce"

function DebounceHarness({ value }: { value: string }) {
  return <output>{useDebounce(value)}</output>
}

describe("useDebounce", () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("waits for the configured delay before updating a search term", () => {
    const { rerender } = render(<DebounceHarness value="trace" />)
    rerender(<DebounceHarness value="trace dashboard" />)

    expect(screen.getByText("trace")).toBeTruthy()

    act(() => {
      vi.advanceTimersByTime(299)
    })
    expect(screen.getByText("trace")).toBeTruthy()

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(screen.getByText("trace dashboard")).toBeTruthy()
  })
})
