// @vitest-environment jsdom

import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { AgentDetailsPageSkeleton } from "@/components/agents/agent-details-page-skeleton"
import { AgentsPageSkeleton } from "@/components/agents/agents-page-skeleton"
import { AuthPageSkeleton } from "@/components/auth/layout"
import { FindingDetailsPageSkeleton } from "@/components/findings/finding-details-page-skeleton"
import { ReviewFindingsSkeleton } from "@/components/findings/review-findings-skeleton"
import { IntegrationsPageSkeleton } from "@/components/integrations/integrations-page-skeleton"
import { LandingPageSkeleton } from "@/components/landing/landing-page-skeleton"
import { NotificationsPageSkeleton } from "@/components/notifications/notifications-page-skeleton"
import {
  ProjectDetailsPageSkeleton,
} from "@/components/projects/project-details-page-skeleton"
import { ProjectsPageSkeleton } from "@/components/projects/projects-page-skeleton"
import { ReviewDetailsPageSkeleton } from "@/components/reviews/review-details-page-skeleton"
import { ApiKeysPageSkeleton } from "@/components/settings/api-keys-page-skeleton"
import { WorkspacePageSkeleton } from "@/components/workspace/workspace-page-skeleton"

describe("page loading skeletons", () => {
  it("renders each routed page layout with the shared Skeleton primitive", () => {
    const { container } = render(
      <MemoryRouter>
        <AuthPageSkeleton />
        <ProjectsPageSkeleton />
        <ProjectDetailsPageSkeleton />
        <ReviewDetailsPageSkeleton />
        <FindingDetailsPageSkeleton />
        <ReviewFindingsSkeleton />
        <AgentsPageSkeleton />
        <AgentDetailsPageSkeleton />
        <IntegrationsPageSkeleton />
        <NotificationsPageSkeleton />
        <ApiKeysPageSkeleton />
        <WorkspacePageSkeleton />
        <LandingPageSkeleton />
      </MemoryRouter>,
    )

    const loadingLabels = [
      "Loading authentication page",
      "Loading projects",
      "Loading project",
      "Loading review",
      "Loading finding",
      "Loading findings",
      "Loading agents",
      "Loading agent",
      "Loading integrations",
      "Loading notifications",
      "Loading API keys",
      "Loading workspace page",
      "Loading landing page",
    ]

    for (const label of loadingLabels) {
      expect(screen.getByLabelText(label).getAttribute("aria-busy")).toBe("true")
    }

    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0)
  })
})
