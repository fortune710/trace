// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ReviewDetailsPage } from "@/app/reviews/review-details-page"
import { useReview } from "@/hooks/use-reviews"
import type { Review } from "@/lib/api"

vi.mock("@/hooks/use-reviews", () => ({ useReview: vi.fn() }))
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

const mockedUseReview = vi.mocked(useReview)

const review: Review = {
  id: "review-a",
  project_id: "project-a",
  source_revision: "a".repeat(40),
  source_snapshot: {
    source_kind: "github",
    source_identifier: "123",
    integrity_algorithm: "git-commit-sha1-v1",
    revision: "a".repeat(40),
    captured_at: "2026-10-21T00:00:00Z",
  },
  status: "queued",
  started_at: null,
  completed_at: null,
  created_at: "2026-10-21T00:00:00Z",
  updated_at: "2026-10-21T00:00:00Z",
  agents: [
    {
      assignment_id: "assignment-a",
      agent_id: "agent-a",
      name: "Security Scout",
      review_category: "security",
      model_provider: "openai",
      model_name: "gpt-5.1",
      personality: "Find vulnerabilities.",
      skills: ["auth"],
      configuration_version: 1,
      status: "assigned",
      assigned_at: "2026-10-21T00:00:00Z",
      started_at: null,
      completed_at: null,
    },
  ],
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

describe("ReviewDetailsPage", () => {
  afterEach(cleanup)

  beforeEach(() => {
    mockedUseReview.mockReturnValue({
      data: review,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useReview>)
  })

  it("renders immutable source and reviewer snapshots", () => {
    render(
      <MemoryRouter initialEntries={["/reviews/review-a"]}>
        <Routes>
          <Route
            path="/reviews/:reviewId"
            element={<ReviewDetailsPage />}
          />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText("Review queued")).toBeTruthy()
    expect(screen.getByText("GitHub")).toBeTruthy()
    expect(screen.getByText("123")).toBeTruthy()
    expect(screen.getByText("git-commit-sha1-v1")).toBeTruthy()
    expect(screen.getByText("Security Scout")).toBeTruthy()
    expect(screen.getByText(/configuration version 1/i)).toBeTruthy()
    expect(screen.queryByText(/credential/i)).toBeNull()
  })

  it("starts another review through the project submission flow", () => {
    render(
      <MemoryRouter initialEntries={["/reviews/review-a"]}>
        <LocationProbe />
        <Routes>
          <Route
            path="/reviews/:reviewId"
            element={<ReviewDetailsPage />}
          />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole("button", { name: "Start another review" }))

    expect(screen.getByTestId("location").textContent).toBe(
      "/projects/project-a?startReview=1",
    )
  })
})
