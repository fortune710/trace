// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, describe, expect, it } from "vitest"

import type { Project } from "@/lib/api"
import { ProjectList } from "@/components/projects/project-list"

const project: Project = {
  id: "project-1",
  name: "Trace project",
  source: "local",
  external_repository_id: null,
  external_repository_connection_id: null,
  repository_owner: null,
  repository_name: "Trace project",
  branch_name: null,
  repository_visibility: null,
  imported_at: "2026-10-16T00:00:00Z",
  source_hash: null,
  current_revision: null,
  category: "productivity",
  auto_create_pull_requests: false,
  created_at: "2026-10-16T00:00:00Z",
  updated_at: "2026-10-16T00:00:00Z",
  archived_at: null,
}

describe("ProjectList", () => {
  afterEach(cleanup)

  function LocationProbe() {
    const location = useLocation()
    return (
      <output data-testid="location">
        {location.pathname}
      </output>
    )
  }

  function renderProjects(projects: Project[]) {
    return render(
      <MemoryRouter>
        <ProjectList projects={projects} />
        <LocationProbe />
      </MemoryRouter>,
    )
  }

  it("does not render a visibility badge when visibility is null", () => {
    renderProjects([project])

    expect(screen.queryByText("private")).toBeNull()
  })

  it("renders the visibility badge when visibility is available", () => {
    renderProjects([{ ...project, repository_visibility: "private" }])

    expect(screen.getByText("private")).toBeTruthy()
  })

  it("opens the selected project's detail route", () => {
    renderProjects([project])

    fireEvent.click(screen.getByRole("link", { name: "View project Trace project" }))

    expect(screen.getByTestId("location").textContent).toBe("/projects/project-1")
  })
})
