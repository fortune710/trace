// @vitest-environment jsdom

import { render } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { toast } from "@/components/ui/toast"
import { ApiError } from "@/lib/api"
import {
  projectCreatedToast,
  projectErrorCopy,
  useProjectErrorToast,
} from "@/hooks/use-project-feedback"

function ErrorToastHarness({ error }: { error: unknown }) {
  useProjectErrorToast(error, "repositories")
  return null
}

describe("project feedback", () => {
  it("defines the project-created success toast", () => {
    expect(projectCreatedToast).toEqual({
      type: "success",
      title: "Project created",
      description: "Your repository is ready to review.",
    })
  })

  it("maps rate limits to a retry-safe warning", () => {
    expect(projectErrorCopy(new ApiError(429, { error: { code: "provider_rate_limited" } }, 17), "repositories")).toEqual({
      type: "warning",
      title: "Rate limit reached",
      description: "Try again in 17 seconds.",
    })
  })

  it.each([
    ["github_authorization_required", "Reconnect GitHub"],
    ["repository_not_found", "Repository unavailable"],
    ["branch_not_found", "Branch unavailable"],
    ["resource_conflict", "Project already imported"],
  ])("maps %s to the expected error toast", (code, title) => {
    expect(projectErrorCopy(new ApiError(400, { error: { code } }), "create")).toMatchObject({ type: "error", title })
  })

  it("uses an operation-safe fallback for fetch and create failures", () => {
    expect(projectErrorCopy(new Error("network"), "branches")).toMatchObject({ title: "Could not load branches" })
    expect(projectErrorCopy(new Error("network"), "create")).toMatchObject({ title: "Project could not be created" })
  })

  it("shows a single toast for a repository-fetch failure", () => {
    const addToast = vi.spyOn(toast, "add")
    const error = new ApiError(429, { error: { code: "provider_rate_limited" } }, 17)
    const { rerender } = render(<ErrorToastHarness error={error} />)

    expect(addToast).toHaveBeenCalledWith({
      type: "warning",
      title: "Rate limit reached",
      description: "Try again in 17 seconds.",
    })

    rerender(<ErrorToastHarness error={error} />)
    expect(addToast).toHaveBeenCalledTimes(1)
  })
})
