// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ReviewDetailsPage } from "@/app/reviews/review-details-page"
import { useProject } from "@/hooks/use-projects"
import { useReview } from "@/hooks/use-reviews"
import type { Project, Review } from "@/lib/api"

vi.mock("@/hooks/use-projects", () => ({ useProject: vi.fn() }))
vi.mock("@/hooks/use-reviews", () => ({ useReview: vi.fn() }))
vi.mock("@/components/findings/review-findings", () => ({
  ReviewFindings: ({ review }: { review: Review }) => (
    <p>Findings for {review.id}</p>
  ),
}))
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

const mockedUseReview = vi.mocked(useReview)
const mockedUseProject = vi.mocked(useProject)

const project = {
  id: "project-a",
  name: "Trace",
} as Project

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
    mockedUseProject.mockReturnValue({
      data: project,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useProject>)
    mockedUseReview.mockReturnValue({
      data: review,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useReview>)
  })

  it("renders review metadata and reviewers without implementation details", () => {
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

    expect(screen.getByRole("navigation", { name: "breadcrumb" })).toBeTruthy()
    expect(screen.getByRole("link", { name: "Projects" }).getAttribute("href")).toBe("/projects")
    expect(screen.getByRole("link", { name: "Trace" }).getAttribute("href")).toBe(
      "/projects/project-a",
    )
    expect(screen.getByText("Review review-a", { selector: "[aria-current=page]" })).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Review review-a" })).toBeTruthy()
    expect(screen.getAllByText("Queued", { selector: "[data-slot=badge]" })).toHaveLength(1)
    expect(screen.getByText("GitHub")).toBeTruthy()
    expect(screen.getByText("123")).toBeTruthy()
    expect(screen.getByText("Status").closest("dl")?.className).toContain("grid-cols-1")
    expect(screen.getByText("Status").closest("dl")?.className).toContain("sm:grid-cols-2")
    expect(screen.getByText("Status").closest("dl")?.className).toContain("md:grid-cols-4")
    expect(screen.getByText("Status").closest("dl")?.className).not.toContain("rounded-lg")
    expect(screen.queryByText("Immutable revision")).toBeNull()
    expect(screen.queryByText("Integrity algorithm")).toBeNull()
    expect(screen.queryByText(review.source_revision)).toBeNull()
    expect(screen.getByRole("heading", { name: "Reviewers" })).toBeTruthy()
    expect(screen.getByText("Security Scout")).toBeTruthy()
    expect(screen.getByText("security", { selector: "[data-slot=badge]" })).toBeTruthy()
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

  it.each([
    ["completed", "Completed", "bg-green-500/15"],
    ["running", "Running", "bg-amber-500/15"],
    ["failed", "Failed", "bg-red-500/15"],
    ["queued", "Queued", "bg-blue-500/15"],
  ] as const)("shows %s status with its colored badge", (status, label, colorClass) => {
    mockedUseReview.mockReturnValue({
      data: { ...review, status },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useReview>)

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

    const badge = screen.getByText(label, { selector: "[data-slot=badge]" })

    expect(badge.className).toContain(colorClass)
    expect(badge.className).toContain("rounded-sm")
    expect(badge.className).toContain("px-1.5")
    expect(badge.className).toContain("py-0.5")
    expect(badge.className).toContain("text-sm")
    expect(badge.className).toContain("font-semibold")
  })

  it("opens the findings tab from its URL state", () => {
    render(
      <MemoryRouter initialEntries={["/reviews/review-a?tab=findings"]}>
        <Routes>
          <Route
            path="/reviews/:reviewId"
            element={<ReviewDetailsPage />}
          />
        </Routes>
      </MemoryRouter>,
    )

    expect(
      screen.getByRole("tab", { name: "Findings" }).getAttribute("aria-selected"),
    ).toBe("true")
    expect(screen.getByText("Findings for review-a")).toBeTruthy()
  })
})
