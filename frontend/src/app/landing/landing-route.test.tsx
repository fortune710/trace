// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { LandingRoute } from "@/app/landing/landing-route"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"

vi.mock("@/hooks/use-runtime-environment", () => ({
  useRuntimeEnvironment: vi.fn(),
}))
vi.mock("@/hooks/use-session", () => ({
  useSession: vi.fn(() => ({ data: null })),
}))

const mockedRuntime = vi.mocked(useRuntimeEnvironment)

function renderRoutes() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route
          path="/"
          element={<LandingRoute />}
        />
        <Route
          path="/account"
          element={<p>Account page</p>}
        />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe("LandingRoute", () => {
  it("renders the landing page in the browser", async () => {
    mockedRuntime.mockReturnValue({
      kind: "web",
      isTauri: false,
      isWeb: true,
    })

    renderRoutes()

    expect(
      await screen.findByRole(
        "heading",
        {
          level: 1,
          name: "Review your app before the world does.",
        },
        { timeout: 15_000 },
      ),
    ).toBeTruthy()
    expect(screen.queryByText("Account page")).toBeNull()
  }, 20_000)

  it("skips the landing page in the desktop app", () => {
    mockedRuntime.mockReturnValue({
      kind: "tauri",
      isTauri: true,
      isWeb: false,
    })

    renderRoutes()

    expect(screen.getByText("Account page")).toBeTruthy()
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull()
    expect(screen.queryByText("Download for macOS")).toBeNull()
  })
})
