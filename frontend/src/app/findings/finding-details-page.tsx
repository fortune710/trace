import { Link, useParams } from "react-router-dom"

import { FindingDetailsPageSkeleton } from "@/components/findings/finding-details-page-skeleton"
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
import { useFinding } from "@/hooks/use-findings"
import { useProject } from "@/hooks/use-projects"
import { useReview } from "@/hooks/use-reviews"

function truncateBreadcrumbTitle(title: string) {
  const maximumLength = 50

  return title.length > maximumLength
    ? `${title.slice(0, maximumLength - 1)}…`
    : title
}

export function FindingDetailsPage() {
  const { reviewId, findingId } = useParams()
  const finding = useFinding(findingId)
  const review = useReview(reviewId)
  const project = useProject(review.data?.project_id)
  const reviewPath = `/reviews/${encodeURIComponent(reviewId ?? "")}?tab=findings`
  const reviewLabel = review.data
    ? `Review ${review.data.id.slice(0, 8)}`
    : "Review"
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
              <BreadcrumbLink render={<Link to={reviewPath} />}>
                {reviewLabel}
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage title={finding.data?.title}>
                {finding.data
                  ? truncateBreadcrumbTitle(finding.data.title)
                  : "Finding"}
              </BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        {finding.isLoading ? (
          <FindingDetailsPageSkeleton />
        ) : null}
        {finding.isError ? (
          <div className="mt-6 grid justify-items-start gap-3">
            <p className="text-sm text-muted-foreground">
              We could not load this finding.
            </p>
            <Button
              type="button"
              variant="outline"
              onClick={() => void finding.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : null}
        {finding.data ? (
          <article className="mt-6 rounded-lg border border-border bg-card p-6">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {finding.data.severity} · {finding.data.category}
            </p>
            <h1 className="mt-2 text-xl font-medium tracking-tight">
              {finding.data.title}
            </h1>
            <p className="mt-5 whitespace-pre-wrap text-sm text-muted-foreground">
              {finding.data.explanation}
            </p>
            <dl className="mt-6 grid gap-5 text-sm">
              <div>
                <dt className="text-muted-foreground">Reviewer</dt>
                <dd className="mt-1">
                  {finding.data.reviewing_agent.display_name} ·{" "}
                  {finding.data.reviewing_agent.specialization}
                </dd>
              </div>
              {finding.data.evidence ? (
                <div>
                  <dt className="text-muted-foreground">Evidence</dt>
                  <dd className="mt-1 whitespace-pre-wrap">
                    {finding.data.evidence}
                  </dd>
                </div>
              ) : null}
              {finding.data.source_location ? (
                <div>
                  <dt className="text-muted-foreground">Source location</dt>
                  <dd className="mt-1 break-all font-mono text-xs">
                    {finding.data.source_location}
                  </dd>
                </div>
              ) : null}
              {finding.data.recommendation ? (
                <div>
                  <dt className="text-muted-foreground">Recommendation</dt>
                  <dd className="mt-1 whitespace-pre-wrap">
                    {finding.data.recommendation}
                  </dd>
                </div>
              ) : null}
            </dl>
          </article>
        ) : null}
      </section>
    </AppShell>
  )
}
