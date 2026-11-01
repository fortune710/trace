// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { DEFAULT_AVATAR_CONFIG } from "@/components/agents/avatar-editor/avatar-config"
import {
  AVATAR_PNG_SIZE,
  renderAvatarPng,
} from "@/components/agents/avatar-editor/render-avatar-png"

// jsdom has neither an image decoder nor a canvas, so both are replaced.
class FakeImage {
  static shouldFail = false
  static lastSource = ""
  onload: (() => void) | null = null
  onerror: (() => void) | null = null

  set src(value: string) {
    FakeImage.lastSource = value
    queueMicrotask(() => {
      if (FakeImage.shouldFail) {
        this.onerror?.()
      } else {
        this.onload?.()
      }
    })
  }
}

describe("renderAvatarPng", () => {
  const drawImage = vi.fn()
  let blob: Blob | null = new Blob(["png"], { type: "image/png" })
  let toBlob: ReturnType<typeof vi.fn>

  beforeEach(() => {
    FakeImage.shouldFail = false
    FakeImage.lastSource = ""
    blob = new Blob(["png"], { type: "image/png" })
    drawImage.mockReset()
    toBlob = vi.fn((callback: (result: Blob | null) => void) => callback(blob))
    vi.stubGlobal("Image", FakeImage)
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage,
    } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
      toBlob as unknown as HTMLCanvasElement["toBlob"],
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("draws the svg onto a square canvas and resolves with the PNG blob", async () => {
    const result = await renderAvatarPng(DEFAULT_AVATAR_CONFIG)

    expect(result).toBe(blob)
    expect(FakeImage.lastSource.startsWith("data:image/svg+xml")).toBe(true)
    expect(decodeURIComponent(FakeImage.lastSource)).toContain(
      `width="${AVATAR_PNG_SIZE}"`,
    )
    expect(drawImage).toHaveBeenCalledWith(
      expect.any(FakeImage),
      0,
      0,
      AVATAR_PNG_SIZE,
      AVATAR_PNG_SIZE,
    )
    expect(toBlob).toHaveBeenCalledWith(expect.any(Function), "image/png")
  })

  it("rejects when the svg cannot be loaded", async () => {
    FakeImage.shouldFail = true

    await expect(renderAvatarPng(DEFAULT_AVATAR_CONFIG)).rejects.toThrow(
      "could not be loaded",
    )
  })

  it("rejects when the canvas produces no blob", async () => {
    blob = null

    await expect(renderAvatarPng(DEFAULT_AVATAR_CONFIG)).rejects.toThrow(
      "PNG",
    )
  })
})
