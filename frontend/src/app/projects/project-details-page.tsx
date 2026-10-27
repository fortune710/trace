import { useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"

import { ReviewSubmissionDialog } from "@/components/reviews/review-submission-dialog"
import { clearFindingSearchParams } from "@/components/findings/finding-search-params"
import { ReviewFindings } from "@/components/findings/review-findings"
import {
  ProjectActivitySkeleton,
  ProjectDetailsPageSkeleton,
} from "@/components/projects/project-details-page-skeleton"
import { AppShell } from "@/components/layout/app-shell"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Button } from "@/components/ui/button"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import { useProject, type Project } from "@/hooks/use-projects"
import { useProjectReviews } from "@/hooks/use-reviews"
import type { Review } from "@/lib/api"

type ProjectTab = "reviews" | "findings"

const projectTabs: Array<{ id: ProjectTab; label: string }> = [
  { id: "reviews", label: "Reviews" },
  { id: "findings", label: "Findings" },
]

function categoryLabel(category: Project["category"]) {
  return category.replace("_", " ")
}

function sourceLabel(project: Project) {
  if (project.source === "local") {
    return "Local folder"
  }

  return `${project.repository_owner}/${project.repository_name}`
}

function reviewDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

function ProjectReviews({ project }: { project: Project }) {
  const [page, setPage] = useState(1)
  const projectId =
    project.api_project_id ?? (project.source === "github" ? project.id : null)
  const reviews = useProjectReviews(projectId, page)
  const hasNoReviews =
    !reviews.isLoading &&
    !reviews.isError &&
    reviews.data?.items.length === 0 &&
    page === 1
  const hasNextPage = reviews.data?.next_offset != null

  if (projectId === null || hasNoReviews) {
    return (
      <Empty className="min-h-56 border border-border bg-card/30">
        <EmptyHeader>
          <EmptyTitle>No reviews yet</EmptyTitle>
          <EmptyDescription>
            Start a review to see its progress and reviewer snapshots here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  if (reviews.isLoading) {
    return <ProjectActivitySkeleton />
  }

  if (reviews.isError) {
    return (
      <div className="grid justify-items-start gap-3">
        <p className="text-sm text-muted-foreground">
          We could not load this project’s reviews.
        </p>
        <Button
          type="button"
          variant="outline"
          onClick={() => void reviews.refetch()}
        >
          Try again
        </Button>
      </div>
    )
  }

  return (
    <div>
      <div className="grid gap-3">
        {reviews.data?.items.map((review: Review) => (
          <Link
            key={review.id}
            to={`/reviews/${encodeURIComponent(review.id)}`}
            className="block rounded-lg border border-border bg-card p-4 transition-colors hover:border-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-foreground">
                Review {review.id.slice(0, 8)}
              </span>
              <span className="rounded-full border border-border px-2.5 py-1 text-xs capitalize text-muted-foreground">
                {review.status}
              </span>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              <time dateTime={review.created_at}>
                {reviewDate(review.created_at)}
              </time>
              {" · "}
              {review.agents.length} {review.agents.length === 1 ? "reviewer" : "reviewers"}
              {review.source_snapshot.source_kind === "github" ? (
                <> · Commit {review.source_revision.slice(0, 12)}</>
              ) : (
                <> · Local snapshot</>
              )}
            </p>
          </Link>
        ))}
      </div>

      {page > 1 || hasNextPage ? (
        <nav
          className="mt-5 flex items-center justify-end gap-3"
          aria-label="Review pagination"
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page === 1 || reviews.isFetching}
            onClick={() => setPage((currentPage) => currentPage - 1)}
          >
            Previous
          </Button>
          <span className="text-xs text-muted-foreground" aria-live="polite">
            Page {page}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!hasNextPage || reviews.isFetching}
            onClick={() => setPage((currentPage) => currentPage + 1)}
          >
            Next
          </Button>
        </nav>
      ) : null}
    </div>
  )
}

function ProjectFindings({ project }: { project: Project }) {
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null)
  const [, setSearchParams] = useSearchParams()
  const projectId =
    project.api_project_id ?? (project.source === "github" ? project.id : null)
  const reviews = useProjectReviews(projectId, 1)
  const selectedReview =
    reviews.data?.items.find((review) => review.id === selectedReviewId) ??
    reviews.data?.items[0]

  if (projectId === null) {
    return (
      <Empty className="min-h-56 border border-border bg-card/30">
        <EmptyHeader>
          <EmptyTitle>Findings are unavailable</EmptyTitle>
          <EmptyDescription>
            Connect this local project before viewing review findings.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  if (reviews.isLoading) {
    return <ProjectActivitySkeleton />
  }

  if (reviews.isError) {
    return (
      <div className="grid justify-items-start gap-3">
        <p className="text-sm text-muted-foreground">
          We could not load the project’s reviews.
        </p>
        <Button
          type="button"
          variant="outline"
          onClick={() => void reviews.refetch()}
        >
          Try again
        </Button>
      </div>
    )
  }

  if (!selectedReview) {
    return (
      <Empty className="min-h-56 border border-border bg-card/30">
        <EmptyHeader>
          <EmptyTitle>No findings yet</EmptyTitle>
          <EmptyDescription>
            Findings will appear after a review reports a risk.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <div>
      <label className="grid max-w-sm gap-1 text-sm">
        Review
        <select
          value={selectedReview.id}
          onChange={(event) => {
            setSelectedReviewId(event.target.value)
            setSearchParams(clearFindingSearchParams)
          }}
        >
          {reviews.data?.items.map((review) => (
            <option key={review.id} value={review.id}>
              {`Review ${review.id.slice(0, 8)} · ${review.status}`}
            </option>
          ))}
        </select>
      </label>
      <div className="mt-6">
        <ReviewFindings review={selectedReview} />
      </div>
    </div>
  )
}

export function ProjectDetailsPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const project = useProject(projectId)
  const [isReviewDialogOpen, setReviewDialogOpen] = useState(
    searchParams.get("startReview") === "1",
  )
  const [activeTab, setActiveTab] = useState<ProjectTab>("reviews")

  function handleReviewDialogChange(open: boolean) {
    setReviewDialogOpen(open)
    if (!open && searchParams.has("startReview")) {
      setSearchParams({}, { replace: true })
    }
  }

  return (
    <AppShell>
      <section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink render={<Link to="/projects" />}>
                Projects
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{project.data?.name ?? "Project"}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        {project.isLoading ? (
          <ProjectDetailsPageSkeleton />
        ) : null}

        {project.isError ? (
          <div className="mt-6 grid justify-items-start gap-3">
            <p className="text-sm text-muted-foreground">
              We could not load this project.
            </p>
            <Button
              type="button"
              variant="outline"
              onClick={() => void project.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : null}

        {project.data ? (
          <div className="mt-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-medium tracking-tight">
                  {project.data.name}
                </h1>
                <p className="mt-2 text-sm text-muted-foreground">
                  {sourceLabel(project.data)}
                </p>
              </div>
              <Button
                type="button"
                onClick={() => setReviewDialogOpen(true)}
              >
                Start review
              </Button>
            </div>

            <dl
              className="mt-8 grid grid-cols-1 gap-x-6 gap-y-5 text-sm sm:grid-cols-2 md:grid-cols-4"
            >
              <div className="min-w-0">
                <dt className="text-muted-foreground">Source</dt>
                <dd className="mt-1 text-foreground">
                  {project.data.source === "local" ? "Local folder" : "GitHub"}
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Category</dt>
                <dd className="mt-1 capitalize text-foreground">
                  {categoryLabel(project.data.category)}
                </dd>
              </div>
              {project.data.source === "github" ? (
                <div className="min-w-0">
                  <dt className="text-muted-foreground">Branch</dt>
                  <dd className="mt-1 font-mono text-foreground">
                    {project.data.branch_name}
                  </dd>
                </div>
              ) : null}
              {project.data.source === "github" ? (
                <div className="min-w-0">
                  <dt className="text-muted-foreground">Last imported commit</dt>
                  <dd className="mt-1 break-all font-mono text-foreground">
                    {project.data.current_revision}
                  </dd>
                </div>
              ) : null}
            </dl>

            <div
              className="mt-8 border-b border-white/10"
              role="tablist"
              aria-label="Project activity"
            >
              {projectTabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  id={`project-${tab.id}-tab`}
                  aria-selected={activeTab === tab.id}
                  aria-controls={`project-${tab.id}-panel`}
                  onClick={() => setActiveTab(tab.id)}
                  className={`mr-5 border-b-2 px-1 pb-3 text-sm transition-colors ${
                    activeTab === tab.id
                      ? "border-foreground text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {activeTab === "reviews" ? (
              <section
                role="tabpanel"
                id="project-reviews-panel"
                aria-labelledby="project-reviews-tab"
                className="mt-6"
              >
                <ProjectReviews project={project.data} />
              </section>
            ) : (
              <section
                role="tabpanel"
                id="project-findings-panel"
                aria-labelledby="project-findings-tab"
                className="mt-6"
              >
                <ProjectFindings project={project.data} />
              </section>
            )}

            <ReviewSubmissionDialog
              open={isReviewDialogOpen}
              project={project.data}
              onOpenChange={handleReviewDialogChange}
              onCreated={(reviewId) => navigate(`/reviews/${reviewId}`)}
            />
          </div>
        ) : null}
      </section>
    </AppShell>
  )
}
