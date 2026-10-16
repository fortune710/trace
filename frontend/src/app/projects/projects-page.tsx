import { useState } from "react"

import { AppShell } from "@/components/layout/app-shell"
import { Button } from "@/components/ui/button"
import { CreateProjectDialog } from "@/components/projects/create-project-dialog"
import {
  EmptyProjects,
  ProjectList,
  ProjectPagination,
} from "@/components/projects/project-list"
import { useProjectErrorToast } from "@/hooks/use-project-feedback"
import { useProjects } from "@/hooks/use-projects"
import { useShortcut } from "@/hooks/use-shortcut"

export function ProjectsPage() {
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [page, setPage] = useState(1)
  const { projects, hasNextPage, isError, isFetching, isLoading, error, refetch } = useProjects(page)
  useProjectErrorToast(error, "projects")
  useShortcut({ key: "n", enabled: !isCreateOpen, onTrigger: () => setIsCreateOpen(true) })

  return (
    <AppShell>
      <section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-xl font-medium tracking-tight">Projects</h1>
          <Button type="button" onClick={() => setIsCreateOpen(true)}>
            <span aria-hidden="true">+</span>
            Create project
          </Button>
        </div>

        <div className="mt-8">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading projects…</p>
          ) : isError ? (
            <Button type="button" variant="outline" onClick={() => void refetch()}>
              Try again
            </Button>
          ) : projects.length === 0 ? (
            <EmptyProjects onCreate={() => setIsCreateOpen(true)} />
          ) : (
            <>
              <ProjectList projects={projects} />
              <ProjectPagination
                page={page}
                hasNextPage={hasNextPage}
                isFetching={isFetching}
                onPrevious={() => setPage((currentPage) => currentPage - 1)}
                onNext={() => setPage((currentPage) => currentPage + 1)}
              />
            </>
          )}
        </div>
      </section>
      <CreateProjectDialog open={isCreateOpen} onOpenChange={setIsCreateOpen} />
    </AppShell>
  )
}
