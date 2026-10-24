import { Link, useNavigate, useParams } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { Button } from "@/components/ui/button"
import { useReview } from "@/hooks/use-reviews"

function displaySourceKind(kind: "github" | "local") {
  return kind === "github" ? "GitHub" : "Local folder"
}

function displaySkills(skills: Array<string | Record<string, object>>) {
  return skills
    .map((skill) => (typeof skill === "string" ? skill : JSON.stringify(skill)))
    .join(", ")
}

export function ReviewDetailsPage() {
  const { reviewId } = useParams()
  const navigate = useNavigate()
  const review = useReview(reviewId)

  return (
    <AppShell>
      <section className="mx-auto w-full max-w-4xl px-6 py-8 md:px-10 md:py-10">
        <Link
          className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          to="/projects"
        >
          Projects
        </Link>

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
                <h1 className="text-xl font-medium tracking-tight">Review queued</h1>
                <p className="mt-2 text-sm text-muted-foreground">
                  This review is queued for the selected reviewers. Provider execution is
                  not started from this page.
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

            <dl className="mt-8 grid gap-4 rounded-lg border border-border bg-card p-5 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Status</dt>
                <dd className="mt-1 capitalize text-foreground">
                  {review.data.status}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Source</dt>
                <dd className="mt-1 text-foreground">
                  {displaySourceKind(review.data.source_snapshot.source_kind)}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-muted-foreground">Source identifier</dt>
                <dd className="mt-1 break-all font-mono text-foreground">
                  {review.data.source_snapshot.source_identifier}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-muted-foreground">Immutable revision</dt>
                <dd className="mt-1 break-all font-mono text-foreground">
                  {review.data.source_snapshot.revision}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Integrity algorithm</dt>
                <dd className="mt-1 font-mono text-foreground">
                  {review.data.source_snapshot.integrity_algorithm}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Captured</dt>
                <dd className="mt-1 text-foreground">
                  {new Date(review.data.source_snapshot.captured_at).toLocaleString()}
                </dd>
              </div>
            </dl>

            <section className="mt-8">
              <h2 className="text-base font-medium">Reviewer snapshots</h2>
              <div className="mt-3 grid gap-3">
                {review.data.agents.map((agent) => (
                  <article
                    key={agent.assignment_id}
                    className="rounded-lg border border-border bg-card p-4"
                  >
                    <h3 className="font-medium">{agent.name}</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {agent.review_category} · {agent.model_provider}/{agent.model_name}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Configuration version {agent.configuration_version} · {agent.status}
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
          </div>
        ) : null}
      </section>
    </AppShell>
  )
}
