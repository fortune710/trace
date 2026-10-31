// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { FindingIssueActions } from "@/components/findings/finding-issue-actions"
import {
  useCreateRemediationIssue,
  useIssuePreview,
} from "@/hooks/use-issue-tracking"
import {
  useCreateRemediationPullRequest,
  useApplyLocalRemediation,
  useFindingRemediations,
} from "@/hooks/use-findings"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { useSession, useUpdateAutomaticPullRequests } from "@/hooks/use-session"

vi.mock("@/hooks/use-issue-tracking", () => ({
  useCreateRemediationIssue: vi.fn(),
  useIssuePreview: vi.fn(),
}))
vi.mock("@/hooks/use-findings", () => ({
  useCreateRemediationPullRequest: vi.fn(),
  useApplyLocalRemediation: vi.fn(),
  useFindingRemediations: vi.fn(),
}))
vi.mock("@/hooks/use-runtime-environment", () => ({
  useRuntimeEnvironment: vi.fn(),
}))
vi.mock("@/hooks/use-session", () => ({
  useSession: vi.fn(),
  useUpdateAutomaticPullRequests: vi.fn(),
}))
vi.mock("@/components/issue-tracking/issue-tracking-feedback", () => ({
  notifyIssueCreation: vi.fn(),
  notifyIssueTrackingError: vi.fn(),
}))

const mockedUseCreateRemediationIssue = vi.mocked(useCreateRemediationIssue)
const mockedUseIssuePreview = vi.mocked(useIssuePreview)
const mockedUseFindingRemediations = vi.mocked(useFindingRemediations)
const mockedUseCreateRemediationPullRequest = vi.mocked(
  useCreateRemediationPullRequest,
)
const mockedUseApplyLocalRemediation = vi.mocked(useApplyLocalRemediation)
const mockedUseRuntimeEnvironment = vi.mocked(useRuntimeEnvironment)
const mockedUseSession = vi.mocked(useSession)
const mockedUseUpdateAutomaticPullRequests = vi.mocked(
  useUpdateAutomaticPullRequests,
)

describe("FindingIssueActions", () => {
  beforeEach(() => {
    mockedUseRuntimeEnvironment.mockReturnValue({
      kind: "web",
      isTauri: false,
      isWeb: true,
    })
    mockedUseSession.mockReturnValue({
      data: {
        user_id: "account-a",
        email: "account@example.test",
        automatic_pull_requests: false,
      },
    } as ReturnType<typeof useSession>)
    mockedUseUpdateAutomaticPullRequests.mockReturnValue({
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useUpdateAutomaticPullRequests>)
    mockedUseApplyLocalRemediation.mockReturnValue({
      isPending: false,
      isError: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useApplyLocalRemediation>)
  })

  it("renders the disabled pull-request action and previews a selected provider", () => {
    const mutate = vi.fn()
    mockedUseFindingRemediations.mockReturnValue({
      data: [{ id: "remediation-a", patch_available: true }],
      isLoading: false,
    } as ReturnType<typeof useFindingRemediations>)
    mockedUseCreateRemediationIssue.mockReturnValue({
      isPending: false,
      mutate,
    } as unknown as ReturnType<typeof useCreateRemediationIssue>)
    mockedUseCreateRemediationPullRequest.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useCreateRemediationPullRequest>)
    mockedUseIssuePreview.mockReturnValue({
      data: { title: "Unsafe redirect", body_markdown: "## Finding" },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useIssuePreview>)

    render(<FindingIssueActions findingId="finding-a" status="open" />)

    expect(
      screen
        .getByRole("button", { name: /create pull request/i })
        .hasAttribute("disabled"),
    ).toBe(true)
    fireEvent.click(screen.getByLabelText("Choose issue tracker"))
    fireEvent.click(screen.getByText("GitHub issue"))

    expect(screen.getByRole("dialog")).toBeTruthy()
    expect(screen.getByText("Unsafe redirect")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Create issue" }))
    expect(mutate).toHaveBeenCalledWith("github", expect.any(Object))
    expect(mockedUseCreateRemediationIssue).toHaveBeenCalledWith(
      "remediation-a",
      "finding-a",
    )
  })

  it("uses the shadcn checkbox to make future PR creation automatic", () => {
    const createPullRequest = vi.fn()
    const updateAutomaticPullRequests = vi.fn()
    mockedUseFindingRemediations.mockReturnValue({
      data: [{ id: "remediation-a", patch_available: true }],
      isLoading: false,
    } as ReturnType<typeof useFindingRemediations>)
    mockedUseUpdateAutomaticPullRequests.mockReturnValue({
      mutate: updateAutomaticPullRequests,
    } as unknown as ReturnType<typeof useUpdateAutomaticPullRequests>)
    mockedUseCreateRemediationIssue.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useCreateRemediationIssue>)
    mockedUseCreateRemediationPullRequest.mockReturnValue({
      isPending: false,
      mutate: createPullRequest,
    } as unknown as ReturnType<typeof useCreateRemediationPullRequest>)
    mockedUseIssuePreview.mockReturnValue({
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useIssuePreview>)

    render(<FindingIssueActions findingId="finding-a" status="accepted" />)

    fireEvent.click(
      screen.getByRole("button", { name: /create pull request/i }),
    )
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /automatically create future pull requests/i,
      }),
    )
    fireEvent.click(screen.getByRole("button", { name: "Create pull request" }))

    expect(createPullRequest).toHaveBeenCalled()
    expect(updateAutomaticPullRequests).toHaveBeenCalledWith(true)
  })

  it("disables pull-request creation when a pull request already exists", () => {
    mockedUseFindingRemediations.mockReturnValue({
      data: [
        {
          id: "remediation-a",
          pull_request: {
            number: 42,
            url: "https://github.com/example/repository/pull/42",
          },
        },
      ],
      isLoading: false,
    } as ReturnType<typeof useFindingRemediations>)
    mockedUseCreateRemediationIssue.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useCreateRemediationIssue>)
    mockedUseCreateRemediationPullRequest.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useCreateRemediationPullRequest>)
    mockedUseIssuePreview.mockReturnValue({
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useIssuePreview>)

    render(<FindingIssueActions findingId="finding-a" status="accepted" />)

    expect(
      screen
        .getAllByRole("button", { name: /create pull request/i })
        .at(-1)
        ?.hasAttribute("disabled"),
    ).toBe(true)
  })

  it("applies the stored diff immediately for a desktop local project", () => {
    const apply = vi.fn()
    mockedUseRuntimeEnvironment.mockReturnValue({
      kind: "tauri",
      isTauri: true,
      isWeb: false,
    })
    mockedUseFindingRemediations.mockReturnValue({
      data: [{ id: "remediation-a", proposed_diff: "diff --git a/file b/file", patch_available: true }],
      isLoading: false,
    } as ReturnType<typeof useFindingRemediations>)
    mockedUseCreateRemediationIssue.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useCreateRemediationIssue>)
    mockedUseCreateRemediationPullRequest.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useCreateRemediationPullRequest>)
    mockedUseApplyLocalRemediation.mockReturnValue({
      isPending: false,
      isError: false,
      mutate: apply,
    } as unknown as ReturnType<typeof useApplyLocalRemediation>)
    mockedUseIssuePreview.mockReturnValue({
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useIssuePreview>)

    render(
      <FindingIssueActions
        findingId="finding-a"
        status="accepted"
        isLocalProject
      />,
    )

    fireEvent.click(screen.getByRole("button", { name: "Apply change" }))
    expect(apply).toHaveBeenCalledWith(
      expect.objectContaining({ id: "remediation-a" }),
    )
  })

  it("prevents duplicate local applies while an apply is pending", () => {
    mockedUseRuntimeEnvironment.mockReturnValue({
      kind: "tauri",
      isTauri: true,
      isWeb: false,
    })
    mockedUseFindingRemediations.mockReturnValue({
      data: [{ id: "remediation-a", proposed_diff: "diff --git a/file b/file" }],
      isLoading: false,
    } as ReturnType<typeof useFindingRemediations>)
    mockedUseCreateRemediationIssue.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useCreateRemediationIssue>)
    mockedUseCreateRemediationPullRequest.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useCreateRemediationPullRequest>)
    mockedUseApplyLocalRemediation.mockReturnValue({
      isPending: true,
      isError: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useApplyLocalRemediation>)
    mockedUseIssuePreview.mockReturnValue({
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useIssuePreview>)

    render(
      <FindingIssueActions
        findingId="finding-a"
        status="accepted"
        isLocalProject
      />,
    )

    const button = screen.getByRole("button", { name: "Applying change…" })
    expect(button.hasAttribute("disabled")).toBe(true)
  })
})
