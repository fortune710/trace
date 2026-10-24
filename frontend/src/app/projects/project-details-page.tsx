import { useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"

import { ReviewSubmissionDialog } from "@/components/reviews/review-submission-dialog"
import { AppShell } from "@/components/layout/app-shell"
import { Button } from "@/components/ui/button"
import { useProject, type Project } from "@/hooks/use-projects"

function categoryLabel(category: Project["category"]) {
  return category.replace("_", " ")
}

function sourceLabel(project: Project) {
  if (project.source === "local") {
    return "Local folder"
  }

  return `${project.repository_owner}/${project.repository_name}`
}

export function ProjectDetailsPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const project = useProject(projectId)
  const [isReviewDialogOpen, setReviewDialogOpen] = useState(
    searchParams.get("startReview") === "1",
  )

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
