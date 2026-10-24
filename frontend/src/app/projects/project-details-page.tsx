import { useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"

import { ReviewSubmissionDialog } from "@/components/reviews/review-submission-dialog"
import { AppShell } from "@/components/layout/app-shell"
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
    !reviews.isLoading && reviews.data?.items.length === 0 && page === 1
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
    return <p className="text-sm text-muted-foreground">Loading reviews…</p>
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
      <section className="mx-auto w-full max-w-4xl px-6 py-8 md:px-10 md:py-10">
        <Link
          className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          to="/projects"
        >
          Projects
        </Link>

        {project.isLoading ? (
          <p className="mt-6 text-sm text-muted-foreground">Loading project…</p>
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

            <dl className="mt-8 grid gap-4 rounded-lg border border-border bg-card p-5 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Source</dt>
                <dd className="mt-1 text-foreground">
                  {project.data.source === "local" ? "Local folder" : "GitHub"}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Category</dt>
                <dd className="mt-1 capitalize text-foreground">
                  {categoryLabel(project.data.category)}
                </dd>
              </div>
              {project.data.source === "github" ? (
                <div>
                  <dt className="text-muted-foreground">Branch</dt>
                  <dd className="mt-1 font-mono text-foreground">
                    {project.data.branch_name}
                  </dd>
                </div>
              ) : null}
              {project.data.source === "github" ? (
                <div className="sm:col-span-2">
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
                <Empty className="min-h-56 border border-border bg-card/30">
                  <EmptyHeader>
                    <EmptyTitle>No findings yet</EmptyTitle>
                    <EmptyDescription>
                      Findings will appear here in a future update.
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
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
