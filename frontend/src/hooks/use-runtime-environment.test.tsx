// @vitest-environment jsdom
import { renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { isTauri } from "@tauri-apps/api/core"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"

vi.mock("@tauri-apps/api/core", () => ({
  isTauri: vi.fn(),
}))

const mockedIsTauri = vi.mocked(isTauri)

describe("useRuntimeEnvironment", () => {
  beforeEach(() => {
    mockedIsTauri.mockReset()
  })

  it("identifies a browser runtime", () => {
    mockedIsTauri.mockReturnValue(false)

    const { result } = renderHook(() => useRuntimeEnvironment())

    expect(result.current).toEqual({ kind: "web", isTauri: false, isWeb: true })
  })

  it("identifies a Tauri runtime", () => {
    mockedIsTauri.mockReturnValue(true)

    const { result } = renderHook(() => useRuntimeEnvironment())

    expect(result.current).toEqual({ kind: "tauri", isTauri: true, isWeb: false })
  })
})
