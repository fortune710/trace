// @vitest-environment jsdom

import { act, cleanup, render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { LandingPage } from "@/app/landing/landing-page"
import {
  DEFAULT_DESKTOP_DOWNLOAD_URL,
  resolveDesktopDownloadUrl,
} from "@/components/landing/desktop-download"
import { useSession } from "@/hooks/use-session"

vi.mock("@/hooks/use-session", () => ({
  useSession: vi.fn(),
}))

const mockedSession = vi.mocked(useSession)

function renderPage() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe("LandingPage", () => {
  it("leads with the headline and both calls to action", () => {
    mockedSession.mockReturnValue({ data: null } as ReturnType<
      typeof useSession
    >)

    renderPage()

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Review your app before the world does.",
      }),
    ).toBeTruthy()

    const hero = screen.getByRole("region", {
      name: "Review your app before the world does.",
    })
    const download = within(hero).getByRole("link", {
      name: "Download for macOS",
    })
    const web = within(hero).getByRole("link", { name: "Continue on web" })

    expect(download.getAttribute("href")).toBe(DEFAULT_DESKTOP_DOWNLOAD_URL)
    expect(web.getAttribute("href")).toBe("/sign-in")
  })

  it("offers sign in to signed-out visitors", () => {
    mockedSession.mockReturnValue({ data: null } as ReturnType<
      typeof useSession
    >)

    renderPage()

    const nav = screen.getByRole("banner")
    const link = within(nav).getByRole("link", { name: "Sign in" })

    expect(link.getAttribute("href")).toBe("/sign-in")
  })

  it("offers the app to signed-in visitors without hiding the page", () => {
    mockedSession.mockReturnValue({
      data: { id: "user-1" },
    } as unknown as ReturnType<typeof useSession>)

    renderPage()

    const nav = screen.getByRole("banner")
    const link = within(nav).getByRole("link", { name: "Open app" })

    expect(link.getAttribute("href")).toBe("/account")
    expect(screen.getByRole("heading", { level: 1 })).toBeTruthy()
  })

  it("previews the current review findings screen", () => {
    mockedSession.mockReturnValue({ data: null } as ReturnType<
      typeof useSession
    >)

    const { container } = renderPage()
    const preview = container.querySelector("figure")

    expect(preview).not.toBeNull()

    const mockup = within(preview as HTMLElement)

    for (const item of ["Projects", "Agents", "Notifications", "Settings"]) {
      expect(mockup.getAllByText(item).length).toBeGreaterThan(0)
    }

    expect(mockup.getByText("Findings", { selector: "span" })).toBeTruthy()
    expect(mockup.getAllByRole("article", { hidden: true })).toHaveLength(4)
    expect(mockup.getAllByText("Accept")).toHaveLength(3)
    expect(mockup.getAllByText("Resolve")).toHaveLength(1)
    expect(
      mockup.getByText(/accepted findings offer a Resolve action/i),
    ).toBeTruthy()
    expect(preview?.querySelector("[inert]")).not.toBeNull()
  })

  it("lays the features out as a four-card bento grid", () => {
    mockedSession.mockReturnValue({ data: null } as ReturnType<
      typeof useSession
    >)

    renderPage()

    const features = screen.getByRole("region", {
      name: "A review team that reports to you",
    })
    const titles = within(features)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent)

    expect(titles).toEqual([
      "Review from every angle",
      "Findings that show their work",
      "Reviewers you configure",
      "Open a pull request or file an issue",
    ])
    expect(
      within(features).getByText(/open a pull request straight from its proposed diff/i),
    ).toBeTruthy()
    expect(within(features).getByText(/GitHub or Linear as an issue/i)).toBeTruthy()
    expect(within(features).getByText("Create pull request")).toBeTruthy()
    expect(within(features).getByText("GitHub issue")).toBeTruthy()
    expect(within(features).getByText("Linear issue")).toBeTruthy()
  })

  it("does not promise capabilities the product lacks", () => {
    mockedSession.mockReturnValue({ data: null } as ReturnType<
      typeof useSession
    >)

    renderPage()

    expect(screen.queryByText(/fallback provider/i)).toBeNull()
    expect(screen.queryByText(/pricing/i)).toBeNull()
  })
})

describe("LandingPage navigation", () => {
  type ObserverCallback = (entries: Array<Partial<IntersectionObserverEntry>>) => void

  let observerCallback: ObserverCallback | undefined
  const observe = vi.fn()
  const disconnect = vi.fn()

  beforeEach(() => {
    observerCallback = undefined
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: ObserverCallback) {
          observerCallback = callback
        }

        observe = observe
        disconnect = disconnect
      },
    )
    mockedSession.mockReturnValue({ data: null } as ReturnType<
      typeof useSession
    >)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    observe.mockClear()
    disconnect.mockClear()
  })

  function reportRegion(
    regionIndex: number,
    entry: Partial<IntersectionObserverEntry>,
  ) {
    act(() => {
      observerCallback?.([
        {
          ...entry,
          target: observe.mock.calls[regionIndex][0] as Element,
        },
      ])
    })
  }

  it("starts in the page flow with no separator", () => {
    renderPage()

    const nav = screen.getByRole("banner")

    expect(observe).toHaveBeenCalledTimes(2)
    expect(nav.getAttribute("data-pinned")).toBe("false")
    expect(nav.className).not.toContain("fixed")
    expect(nav.className).toContain("border-transparent")
  })

  it("pins with a separator once the product preview is reached", () => {
    renderPage()

    reportRegion(0, { isIntersecting: true })

    const nav = screen.getByRole("banner")

    expect(nav.getAttribute("data-pinned")).toBe("true")
    expect(nav.className).toContain("fixed")
    expect(nav.className).toContain("border-white/6")
  })

  it("returns to the page flow when scrolled back above the preview", () => {
    renderPage()

    reportRegion(0, { isIntersecting: true })
    reportRegion(0, { isIntersecting: false })

    const nav = screen.getByRole("banner")

    expect(nav.getAttribute("data-pinned")).toBe("false")
    expect(nav.className).not.toContain("fixed")
    expect(nav.className).toContain("border-transparent")
  })

  it("stays pinned while only the footer is under the top of the viewport", () => {
    renderPage()

    reportRegion(0, { isIntersecting: true })
    reportRegion(1, { isIntersecting: true })
    reportRegion(0, { isIntersecting: false })

    expect(screen.getByRole("banner").getAttribute("data-pinned")).toBe("true")

    reportRegion(1, { isIntersecting: false })

    expect(screen.getByRole("banner").getAttribute("data-pinned")).toBe("false")
  })

  it("disconnects the observer on unmount", () => {
    const { unmount } = renderPage()

    unmount()

    expect(disconnect).toHaveBeenCalled()
  })
})

describe("resolveDesktopDownloadUrl", () => {
  it("falls back to the latest GitHub release", () => {
    expect(resolveDesktopDownloadUrl(undefined)).toBe(
      DEFAULT_DESKTOP_DOWNLOAD_URL,
    )
    expect(resolveDesktopDownloadUrl("   ")).toBe(DEFAULT_DESKTOP_DOWNLOAD_URL)
  })

  it("uses an https override", () => {
    expect(resolveDesktopDownloadUrl("https://example.test/Trace.dmg")).toBe(
      "https://example.test/Trace.dmg",
    )
  })

  it("ignores insecure or malformed overrides", () => {
    expect(resolveDesktopDownloadUrl("http://example.test/Trace.dmg")).toBe(
      DEFAULT_DESKTOP_DOWNLOAD_URL,
    )
    expect(resolveDesktopDownloadUrl("javascript:alert(1)")).toBe(
      DEFAULT_DESKTOP_DOWNLOAD_URL,
    )
    expect(resolveDesktopDownloadUrl("not a url")).toBe(
      DEFAULT_DESKTOP_DOWNLOAD_URL,
    )
  })
})
