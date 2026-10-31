import { Link, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { FindingDetailsPageSkeleton } from "@/components/findings/finding-details-page-skeleton";
import { CodingAgentPrompt } from "@/components/findings/coding-agent-prompt";
import { FindingIssueActions } from "@/components/findings/finding-issue-actions";
import { FindingIssueLinks } from "@/components/findings/finding-issue-links";
import { ProposedDiff } from "@/components/findings/proposed-diff";
import { sourceFiles } from "@/components/findings/source-files";
import { AppShell } from "@/components/layout/app-shell";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useFinding } from "@/hooks/use-findings";
import { useProject } from "@/hooks/use-projects";
import { useReview } from "@/hooks/use-reviews";
import type { FindingSeverity, FindingStatus } from "@/lib/api";

function truncateBreadcrumbTitle(title: string) {
  const maximumLength = 50;

  return title.length > maximumLength
    ? `${title.slice(0, maximumLength - 1)}…`
    : title;
}

function severityBadgeClassName(severity: FindingSeverity) {
  switch (severity) {
    case "low":
      return "bg-green-500/15 text-green-700 dark:text-green-300";
    case "medium":
      return "bg-yellow-500/15 text-yellow-800 dark:text-yellow-300";
    case "high":
    case "critical":
      return "bg-red-500/15 text-red-700 dark:text-red-300";
    case "info":
      return "bg-blue-500/15 text-blue-700 dark:text-blue-300";
  }
}

function findingStatusBadgeClassName(status: FindingStatus) {
  switch (status) {
    case "open":
      return "bg-white text-black";
    case "accepted":
      return "bg-green-500/15 text-green-700 dark:text-green-300";
    case "resolved":
      return "bg-purple-500/15 text-purple-700 dark:text-purple-300";
    case "dismissed":
      return "bg-red-500/15 text-red-700 dark:text-red-300";
  }
}

function findingStatusLabel(status: FindingStatus) {
  return `${status.slice(0, 1).toUpperCase()}${status.slice(1)}`;
}

export function FindingDetailsPage() {
  const { reviewId, findingId } = useParams();
  const finding = useFinding(findingId);
  const review = useReview(reviewId);
  const project = useProject(review.data?.project_id);
  const reviewPath = `/reviews/${encodeURIComponent(reviewId ?? "")}?tab=findings`;
  const reviewLabel = review.data
    ? `Review ${review.data.id.slice(0, 8)}`
    : "Review";
  const projectPath = review.data
    ? `/projects/${encodeURIComponent(review.data.project_id)}`
    : null;
  const sourceFilesForFinding = finding.data?.source_location
    ? sourceFiles(finding.data.source_location)
    : [];

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
        {finding.isLoading ? <FindingDetailsPageSkeleton /> : null}
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
          <article className="mt-6">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Badge
                    className={`rounded-md border-0 uppercase ${severityBadgeClassName(finding.data.severity)}`}
                  >
                    {finding.data.severity}
                  </Badge>
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {finding.data.category}
                  </p>
                </div>
                <h1 className="mt-2 text-xl font-medium tracking-tight">
                  {finding.data.title}
                </h1>
              </div>
              <div className="shrink-0">
                <FindingIssueActions
                  findingId={finding.data.id}
                  status={finding.data.status}
                  isLocalProject={project.data?.source === "local"}
                  reviewCompleted={review.data?.status === "completed"}
                />
              </div>
            </div>
            <p className="mt-5 whitespace-pre-wrap text-sm text-muted-foreground">
              {finding.data.explanation}
            </p>
            <dl className="mt-6 grid gap-5 text-sm">
              <div>
                <dt className="text-muted-foreground">Triage status</dt>
                <dd className="mt-1">
                  <Badge
                    className={`h-auto rounded-sm px-1.5 py-0.5 text-sm font-semibold ${findingStatusBadgeClassName(finding.data.status)}`}
                  >
                    {findingStatusLabel(finding.data.status)}
                  </Badge>
                </dd>
              </div>
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
                  <dd className="mt-1 text-sm leading-6 [&_a]:text-link [&_a]:underline [&_a]:underline-offset-4 [&_code]:rounded-sm [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_ol]:list-decimal [&_ol]:space-y-1 [&_ol]:pl-5 [&_p]:not-last:mb-3 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-muted/50 [&_pre]:p-3 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-5">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {finding.data.evidence}
                    </ReactMarkdown>
                  </dd>
                </div>
              ) : null}
              {sourceFilesForFinding.length > 0 ? (
                <div>
                  <dt className="text-muted-foreground">Source location</dt>
                  <dd className="mt-1 flex flex-wrap gap-1">
                    {sourceFilesForFinding.map((file) => (
                      <Badge
                        key={file}
                        variant="outline"
                        className="max-w-full shrink-0 truncate rounded-sm font-mono text-xs"
                        title={file}
                      >
                        {file}
                      </Badge>
                    ))}
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
            <ProposedDiff findingId={finding.data.id} />
            {review.data?.status === "completed" ? (
              <CodingAgentPrompt findingId={finding.data.id} />
            ) : (
              <p className="mt-6 text-sm text-muted-foreground">
                The coding prompt is available when the review completes.
              </p>
            )}
            <FindingIssueLinks findingId={finding.data.id} />
          </article>
        ) : null}
      </section>
    </AppShell>
  );
}
