import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"

import { ReviewFindings } from "@/components/findings/review-findings"
import { AppShell } from "@/components/layout/app-shell"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useProject } from "@/hooks/use-projects"
import { useReview } from "@/hooks/use-reviews"

function displaySourceKind(kind: "github" | "local") {
  return kind === "github" ? "GitHub" : "Local folder"
}

function displaySkills(skills: Array<string | Record<string, object>>) {
  return skills
    .map((skill) => (typeof skill === "string" ? skill : JSON.stringify(skill)))
    .join(", ")
}

const reviewStatusDescriptions = {
  queued: "This review is waiting for the selected reviewers to start.",
  running: "The selected reviewers are checking the source now.",
  completed: "The selected reviewers have finished this review.",
  failed: "This review could not be completed.",
  cancelled: "This review was cancelled before it finished.",
}

export function ReviewDetailsPage() {
  const { reviewId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const review = useReview(reviewId)
  const project = useProject(review.data?.project_id)
  const activeTab =
    searchParams.get("tab") === "findings" ? "findings" : "overview"
  const reviewLabel = review.data ? `Review ${review.data.id.slice(0, 8)}` : "Review"
  const projectPath = review.data
    ? `/projects/${encodeURIComponent(review.data.project_id)}`
    : null

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
              {projectPath ? (
                <BreadcrumbLink render={<Link to={projectPath} />}>
                  {project.data?.name ?? "Project"}
                </BreadcrumbLink>
              ) : (
                <span>Project</span>
              )}
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{reviewLabel}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        {review.isLoading ? (
          <p className="mt-6 text-sm text-muted-foreground">Loading review…</p>
        ) : null}
        {review.isError ? (
          <div className="mt-6 grid justify-items-start gap-3">
            <p className="text-sm text-muted-foreground">
              We could not load this review.
            </p>
            <Button
              type="button"
              variant="outline"
              onClick={() => void review.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : null}

        {review.data ? (
          <div className="mt-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-medium tracking-tight">
                  Review {review.data.status}
                </h1>
                <p className="mt-2 text-sm text-muted-foreground">
                  {reviewStatusDescriptions[review.data.status]}
                </p>
              </div>
              <Button
                type="button"
                onClick={() =>
                  navigate(`/projects/${review.data.project_id}?startReview=1`)
                }
              >
                Start another review
              </Button>
            </div>

            <dl
              className="mt-8 grid grid-cols-1 gap-x-6 gap-y-5 text-sm sm:grid-cols-2 md:grid-cols-4"
            >
              <div className="min-w-0">
                <dt className="text-muted-foreground">Status</dt>
                <dd className="mt-1 capitalize text-foreground">
                  {review.data.status}
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Source</dt>
                <dd className="mt-1 text-foreground">
                  {displaySourceKind(review.data.source_snapshot.source_kind)}
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Source identifier</dt>
                <dd className="mt-1 break-all font-mono text-foreground">
                  {review.data.source_snapshot.source_identifier}
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Captured</dt>
                <dd className="mt-1 text-foreground">
                  {new Date(review.data.source_snapshot.captured_at).toLocaleString()}
                </dd>
              </div>
            </dl>

            <div
              className="mt-8 border-b border-border"
              role="tablist"
              aria-label="Review content"
            >
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "overview"}
                onClick={() => setSearchParams({})}
                className={`mr-5 border-b-2 px-1 pb-3 text-sm ${
                  activeTab === "overview"
                    ? "border-foreground text-foreground"
                    : "border-transparent text-muted-foreground"
                }`}
              >
                Overview
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "findings"}
                onClick={() => setSearchParams({ tab: "findings" })}
                className={`border-b-2 px-1 pb-3 text-sm ${
                  activeTab === "findings"
                    ? "border-foreground text-foreground"
                    : "border-transparent text-muted-foreground"
                }`}
              >
                Findings
              </button>
            </div>

            {activeTab === "overview" ? (
              <section className="mt-8" role="tabpanel" aria-label="Overview">
                <h2 className="text-base font-medium">Reviewers</h2>
                <div className="mt-3 grid gap-3">
                  {review.data.agents.map((agent) => (
                    <article
                      key={agent.assignment_id}
                      className="rounded-lg border border-border bg-card p-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <h3 className="font-medium">{agent.name}</h3>
                        <Badge variant="outline" className="capitalize">
                          {agent.review_category}
                        </Badge>
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {agent.model_provider}/{agent.model_name}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Configuration version {agent.configuration_version} ·{" "}
                        {agent.status}
                      </p>
                      {agent.personality ? (
                        <p className="mt-3 text-sm text-muted-foreground">
                          {agent.personality}
                        </p>
                      ) : null}
                      {agent.skills.length > 0 ? (
                        <p className="mt-3 text-xs text-muted-foreground">
                          Snapshot skills: {displaySkills(agent.skills)}
                        </p>
                      ) : null}
                    </article>
                  ))}
                </div>
              </section>
            ) : (
              <div className="mt-8" role="tabpanel" aria-label="Findings">
                <ReviewFindings review={review.data} />
              </div>
            )}
          </div>
        ) : null}
      </section>
    </AppShell>
  )
}
