import { Link, useParams } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { Button } from "@/components/ui/button"
import { useProject, type Project } from "@/hooks/use-projects"

function categoryLabel(category: Project["category"]) {
  return category.replace("_", " ")
}

export function ProjectDetailsPage() {
  const { projectId } = useParams()
  const project = useProject(projectId)

  return (
    <AppShell>
      <section className="mx-auto w-full max-w-4xl px-6 py-8 md:px-10 md:py-10">
        <Link className="text-sm text-muted-foreground transition-colors hover:text-foreground" to="/projects">
          Projects
        </Link>

        {project.isLoading ? <p className="mt-6 text-sm text-muted-foreground">Loading project…</p> : null}
        {project.isError ? <div className="mt-6 grid justify-items-start gap-3"><p className="text-sm text-muted-foreground">We could not load this project.</p><Button type="button" variant="outline" onClick={() => void project.refetch()}>Try again</Button></div> : null}
        {project.data ? <div className="mt-6"><h1 className="text-xl font-medium tracking-tight">{project.data.name}</h1><p className="mt-2 text-sm text-muted-foreground">{project.data.repository_owner}/{project.data.repository_name}</p><dl className="mt-8 grid gap-4 rounded-lg border border-border bg-card p-5 text-sm sm:grid-cols-2"><div><dt className="text-muted-foreground">Branch</dt><dd className="mt-1 font-mono text-foreground">{project.data.branch_name}</dd></div><div><dt className="text-muted-foreground">Category</dt><dd className="mt-1 capitalize text-foreground">{categoryLabel(project.data.category)}</dd></div><div className="sm:col-span-2"><dt className="text-muted-foreground">Imported commit</dt><dd className="mt-1 break-all font-mono text-foreground">{project.data.current_revision}</dd></div></dl></div> : null}
      </section>
    </AppShell>
  )
}
