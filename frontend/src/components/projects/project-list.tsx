import { ArrowLeft01Icon, ArrowRight01Icon, Folder01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { Button } from "@/components/ui/button"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import type { Project } from "@/hooks/use-projects"

function formatCategory(category: Project["category"]) {
  return category.replaceAll("_", " ")
}

function formatImportedAt(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value))
}

function ProjectCard({ project }: { project: Project }) {
  return (
    <article className="group rounded-lg border border-border bg-card p-5 transition-colors hover:border-white/20">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-secondary text-muted-foreground">
            <HugeiconsIcon icon={Folder01Icon} size={18} strokeWidth={2} />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-medium text-foreground">{project.name}</h2>
            <p className="truncate text-xs text-muted-foreground">
              {project.source === "github"
                ? `${project.repository_owner}/${project.repository_name}`
                : project.repository_name}
            </p>
          </div>
        </div>
        {project.repository_visibility !== null ? (
          <span className="rounded-full border border-border px-2 py-1 text-[11px] capitalize text-muted-foreground">
            {project.repository_visibility}
          </span>
        ) : null}
      </div>

      <div className="mt-5 grid grid-cols-2 gap-4 border-t border-border pt-4 text-xs">
        <div>
          <p className="text-muted-foreground">Branch</p>
          <p className="mt-1 font-mono text-foreground">{project.branch_name ?? "local"}</p>
        </div>
        <div>
          <p className="text-muted-foreground">Category</p>
          <p className="mt-1 capitalize text-foreground">{formatCategory(project.category)}</p>
        </div>
      </div>

      <p className="mt-5 text-xs text-muted-foreground">
        {project.imported_at ? `Imported ${formatImportedAt(project.imported_at)}` : "Not imported"}
      </p>
    </article>
  )
}

export function ProjectList({ projects }: { projects: Project[] }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {projects.map((project) => (
        <ProjectCard key={project.id} project={project} />
      ))}
    </div>
  )
}

export function EmptyProjects({ onCreate }: { onCreate: () => void }) {
  return (
    <Empty className="min-h-80 border-border bg-card/30">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <HugeiconsIcon icon={Folder01Icon} strokeWidth={2} />
        </EmptyMedia>
        <EmptyTitle>No projects yet</EmptyTitle>
        <EmptyDescription>
          Create a project from a GitHub repository to start reviewing code in Trace.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button type="button" onClick={onCreate}>
          <span aria-hidden="true">+</span>
          Create project
        </Button>
      </EmptyContent>
    </Empty>
  )
}

export function ProjectPagination({
  page,
  hasNextPage,
  isFetching,
  onPrevious,
  onNext,
}: {
  page: number
  hasNextPage: boolean
  isFetching: boolean
  onPrevious: () => void
  onNext: () => void
}) {
  return (
    <nav className="mt-6 flex justify-end" aria-label="Project pagination">
      <div className="flex items-center gap-2">
        <Button type="button" variant="outline" size="sm" disabled={page === 1 || isFetching} onClick={onPrevious}>
          <HugeiconsIcon icon={ArrowLeft01Icon} size={15} strokeWidth={2} />
          Previous
        </Button>
        <span className="min-w-16 text-center text-xs text-muted-foreground" aria-live="polite">
          Page {page}
        </span>
        <Button type="button" variant="outline" size="sm" disabled={!hasNextPage || isFetching} onClick={onNext}>
          Next
          <HugeiconsIcon icon={ArrowRight01Icon} size={15} strokeWidth={2} />
        </Button>
      </div>
    </nav>
  )
}
