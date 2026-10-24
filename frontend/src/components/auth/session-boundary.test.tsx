// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SessionBoundary } from "@/components/auth/session-boundary"
import { useSessionBoundary } from "@/components/auth/session-boundary-context"
import { AuthenticatedOnly } from "@/app/auth/route-guards"

const sessionState = {
    data: { user_id: "user-1", email: "user@example.test" } as { user_id: string; email: string } | null,
    isPending: false,
    isSuccess: true,
}

vi.mock("@/hooks/use-session", () => ({
  useSession: () => sessionState,
}))

function Location() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>
}

function IntentionalLogoutMarker() {
  const boundary = useSessionBoundary()
  return <button onClick={boundary.markIntentionalLogout}>Mark logout</button>
}

function renderBoundary(route = "/projects?tab=local") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <SessionBoundary>
        <Location />
      </SessionBoundary>
    </MemoryRouter>,
  )
}

function renderGuardedBoundary(route = "/projects") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <SessionBoundary>
        <Routes>
          <Route path="/sign-in" element={<output data-testid="sign-in-page">sign in</output>} />
          <Route element={<AuthenticatedOnly />}>
            <Route path="/projects" element={<output data-testid="protected-page">projects</output>} />
          </Route>
        </Routes>
        <Location />
      </SessionBoundary>
    </MemoryRouter>,
  )
}

describe("SessionBoundary", () => {
  afterEach(() => {
    cleanup()
    sessionState.data = { user_id: "user-1", email: "user@example.test" }
    sessionState.isSuccess = true
    sessionStorage.clear()
  })

  it("shows a blocking dialog after an authenticated session becomes inactive", async () => {
    const view = renderBoundary()

    sessionState.data = null
    view.rerender(
      <MemoryRouter initialEntries={["/projects?tab=local"]}>
        <SessionBoundary>
          <Location />
        </SessionBoundary>
      </MemoryRouter>,
    )

    expect(await screen.findByRole("dialog")).toBeTruthy()
    expect(screen.getByText("Your session has ended")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Go to sign in" })).toBeTruthy()
  })

  it("does not show the expiration dialog for initial unauthenticated access", () => {
    sessionState.data = null
    renderGuardedBoundary()

    expect(screen.queryByRole("dialog")).toBeNull()
    expect(screen.getByTestId("sign-in-page")).toBeTruthy()
  })

  it("keeps the protected route mounted while the expiration dialog is shown", async () => {
    const view = renderGuardedBoundary()

    sessionState.data = null
    view.rerender(
      <MemoryRouter initialEntries={["/projects"]}>
        <SessionBoundary>
          <Routes>
            <Route path="/sign-in" element={<output data-testid="sign-in-page">sign in</output>} />
            <Route element={<AuthenticatedOnly />}>
              <Route path="/projects" element={<output data-testid="protected-page">projects</output>} />
            </Route>
          </Routes>
          <Location />
        </SessionBoundary>
      </MemoryRouter>,
    )

    expect(await screen.findByTestId("protected-page")).toBeTruthy()
    expect(screen.getByRole("dialog")).toBeTruthy()
  })

  it("preserves the protected route when sending the user to sign in", async () => {
    const user = userEvent.setup()
    const view = renderBoundary()

    sessionState.data = null
    view.rerender(
      <MemoryRouter initialEntries={["/projects?tab=local"]}>
        <SessionBoundary>
          <Location />
        </SessionBoundary>
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole("button", { name: "Go to sign in" }))

    expect(screen.getByTestId("location").textContent).toBe("/sign-in")
    expect(sessionStorage.getItem("trace.auth.return_to")).toBe("/projects?tab=local")
  })

  it("does not show the dialog on guest routes", () => {
    const view = renderBoundary("/sign-in")

    sessionState.data = null
    view.rerender(
      <MemoryRouter initialEntries={["/sign-in"]}>
        <SessionBoundary>
          <Location />
        </SessionBoundary>
      </MemoryRouter>,
    )

    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("does not treat an intentional logout as an expired session", () => {
    const view = render(
      <MemoryRouter initialEntries={["/projects"]}>
        <SessionBoundary>
          <IntentionalLogoutMarker />
        </SessionBoundary>
      </MemoryRouter>,
    )

    screen.getByRole("button", { name: "Mark logout" }).click()
    sessionState.data = null
    view.rerender(
      <MemoryRouter initialEntries={["/projects"]}>
        <SessionBoundary>
          <IntentionalLogoutMarker />
        </SessionBoundary>
      </MemoryRouter>,
    )

    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("does not treat a session query error as expiration", () => {
    const view = renderBoundary()

    sessionState.data = null
    sessionState.isSuccess = false
    view.rerender(
      <MemoryRouter initialEntries={["/projects?tab=local"]}>
        <SessionBoundary>
          <Location />
        </SessionBoundary>
      </MemoryRouter>,
    )

    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("keeps the dialog open when escape is pressed", async () => {
    const user = userEvent.setup()
    const view = renderBoundary()

    sessionState.data = null
    view.rerender(
      <MemoryRouter initialEntries={["/projects?tab=local"]}>
        <SessionBoundary>
          <Location />
        </SessionBoundary>
      </MemoryRouter>,
    )

    await screen.findByRole("dialog")
    await user.keyboard("{Escape}")

    expect(screen.getByRole("dialog")).toBeTruthy()
    expect(screen.queryByRole("button", { name: /close/i })).toBeNull()
  })
})
