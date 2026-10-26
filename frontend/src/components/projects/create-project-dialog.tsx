import { useState, type FormEvent, type UIEvent } from "react"
import { FolderOpenIcon, Search01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import { useNavigate } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { toast } from "@/components/ui/toast"
import githubLogo from "@/assets/github-invertocat-white.svg"
import { useDebounce } from "@/hooks/use-debounce"
import { useGitHubConnection } from "@/hooks/use-github-connection"
import { useLocalFolderPicker } from "@/hooks/use-local-folder-picker"
import { type Branch, type Repository } from "@/lib/api"
import { LocalProjectCreationError } from "@/lib/desktop-projects"
import { projectCreatedToast, projectErrorCopy, useProjectErrorToast } from "@/hooks/use-project-feedback"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import {
  type ProjectCategory,
  useBranches,
  useCreateLocalProject,
  useCreateProject,
  useRepositories,
} from "@/hooks/use-projects"

type Step = 1 | 2 | 3

const categories: { value: ProjectCategory; label: string }[] = [
  { value: "business", label: "Business" },
  { value: "e_commerce", label: "E-commerce" },
  { value: "educational", label: "Educational" },
  { value: "entertainment", label: "Entertainment" },
  { value: "finance", label: "Finance" },
  { value: "gaming", label: "Gaming" },
  { value: "health", label: "Health" },
  { value: "other", label: "Other" },
  { value: "productivity", label: "Productivity" },
  { value: "social", label: "Social" },
  { value: "sports", label: "Sports" },
]

function fieldClassName() {
  return "w-full rounded-md border-white/25 bg-input/30 hover:border-white/40"
}

function SelectSearch({ value, placeholder, onChange }: { value: string; placeholder: string; onChange: (value: string) => void }) {
  return (
    <div className="border-b border-border p-2">
      <div className="relative">
        <HugeiconsIcon icon={Search01Icon} size={15} strokeWidth={2} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
        <Input value={value} onChange={(event) => onChange(event.target.value)} onKeyDown={(event) => event.stopPropagation()} placeholder={placeholder} className="h-8 border-0 bg-transparent pl-8 shadow-none focus-visible:ring-0" autoFocus />
      </div>
    </div>
  )
}

function fetchNextOnScroll(
  event: UIEvent<HTMLElement>,
  hasNextPage: boolean,
  isFetchingNextPage: boolean,
  fetchNextPage: () => Promise<unknown>,
) {
  const element = event.currentTarget
  if (!hasNextPage || isFetchingNextPage || element.scrollHeight - element.scrollTop - element.clientHeight > 32) return
  void fetchNextPage()
}

function menuStatus({ isLoading, isFetchingNextPage, isError }: { isLoading: boolean; isFetchingNextPage: boolean; isError: boolean }) {
  if (isLoading) return "Loading…"
  if (isError) return "Unable to load. Try again."
  if (isFetchingNextPage) return "Loading more…"
  return null
}

function RepositoryPickerEmpty({ searchQuery }: { searchQuery: string }) {
  const hasSearchQuery = Boolean(searchQuery)

  return (
    <Empty className="min-h-40 gap-2 border-0 p-5">
      <EmptyHeader className="gap-1.5">
        <EmptyMedia variant="icon" className="mb-0 size-8 rounded-md [&_svg:not([class*='size-'])]:size-4">
          <HugeiconsIcon icon={FolderOpenIcon} strokeWidth={2} />
        </EmptyMedia>
        <EmptyTitle className="text-sm">{hasSearchQuery ? "No matching repositories" : "No repositories available"}</EmptyTitle>
        <EmptyDescription className="text-xs/relaxed">{hasSearchQuery ? "Try a different repository name." : "We couldn't find a GitHub repository available to import."}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

function BranchPickerEmpty({ searchQuery }: { searchQuery: string }) {
  const hasSearchQuery = Boolean(searchQuery)

  return (
    <Empty className="min-h-40 gap-2 border-0 p-5">
      <EmptyHeader className="gap-1.5">
        <EmptyMedia variant="icon" className="mb-0 size-8 rounded-md [&_svg:not([class*='size-'])]:size-4">
          <HugeiconsIcon icon={FolderOpenIcon} strokeWidth={2} />
        </EmptyMedia>
        <EmptyTitle className="text-sm">{hasSearchQuery ? "No matching branches" : "No branches available"}</EmptyTitle>
        <EmptyDescription className="text-xs/relaxed">{hasSearchQuery ? "Try a different branch name." : "Choose another repository or refresh the repository connection."}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

export function CreateProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate()
  const runtime = useRuntimeEnvironment()
  const localFolderPicker = useLocalFolderPicker()
  const githubConnection = useGitHubConnection()
  const [step, setStep] = useState<Step>(1)
  const [source, setSource] = useState<"github" | "local" | null>(null)
  const [name, setName] = useState("")
  const [category, setCategory] = useState<ProjectCategory>("business")
  const [selectedRepository, setSelectedRepository] = useState<Repository | null>(null)
  const [selectedBranch, setSelectedBranch] = useState<Branch | null>(null)
  const [sourceSearch, setSourceSearch] = useState("")
  const [repositorySearch, setRepositorySearch] = useState("")
  const [branchSearch, setBranchSearch] = useState("")
  const debouncedRepositorySearch = useDebounce(repositorySearch.trim())
  const debouncedBranchSearch = useDebounce(branchSearch.trim())
  const isGitHubConnected = githubConnection.data?.status === "connected"
  const isGitHubUnavailable = githubConnection.data !== undefined && !isGitHubConnected
  const repositories = useRepositories(
    debouncedRepositorySearch,
    open && step === 2 && isGitHubConnected,
  )
  const branches = useBranches(
    selectedRepository?.repository_id ?? null,
    debouncedBranchSearch,
    open && step === 2 && isGitHubConnected,
  )
  const createProject = useCreateProject()
  const createLocalProject = useCreateLocalProject()
  const repositoryItems = repositories.data?.pages.flatMap((page) => page.items) ?? []
  const branchItems = branches.data?.pages.flatMap((page) => page.items) ?? []

  useProjectErrorToast(repositories.error, "repositories")
  useProjectErrorToast(branches.error, "branches")

  function resetForm() {
    setStep(1)
    setSource(null)
    setName("")
    setCategory("business")
    setSelectedRepository(null)
    setSelectedBranch(null)
    setSourceSearch("")
    setRepositorySearch("")
    setBranchSearch("")
    createProject.reset()
    createLocalProject.reset()
  }

  function closeDialog(nextOpen: boolean) {
    onOpenChange(nextOpen)
    if (!nextOpen) {
      void localFolderPicker.clearSelection().catch(() => undefined)
      resetForm()
    }
  }

  async function handleLocalFolderSelect() {
    const selection = await localFolderPicker.selectFolder()
    if (!selection) return
    setSource("local")
    setName(selection.displayName)
    setStep(3)
  }

  async function handleGitHubSelect() {
    if (!isGitHubConnected) return

    if (source === "local") {
      try {
        await localFolderPicker.clearSelection()
      } catch {
        return
      }
    }
    setSource("github")
    setName("")
    setStep(2)
  }

  function handleRepositoryChange(repositoryId: string) {
    const repository = repositoryItems.find((item) => item.repository_id === repositoryId)
    if (!repository) return
    setSource("github")
    setSelectedRepository(repository)
    setSelectedBranch(null)
    setName(repository.name)
    setBranchSearch("")
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (source === "local") {
      if (!localFolderPicker.selection) return
      createLocalProject.mutate(
        {
          name: name.trim(),
          category,
          sourceId: localFolderPicker.selection.sourceId,
        },
        {
          onSuccess: (project) => {
            localFolderPicker.commitSelection()
            toast.add(projectCreatedToast)
            closeDialog(false)
            void navigate(`/projects/${project.id}`)
          },
          onError: (error) => {
            toast.add(projectErrorCopy(error, "create"))
            if (error instanceof LocalProjectCreationError && error.code === "already_exists") {
              return
            }
            void localFolderPicker.clearSelection().catch(() => undefined)
            setSource(null)
            setStep(1)
          },
        },
      )
      return
    }

    if (!selectedRepository || !selectedBranch) return
    createProject.mutate(
      {
        name: name.trim(),
        category,
        repositoryId: selectedRepository.repository_id,
        branchName: selectedBranch.name,
      },
      {
        onSuccess: (project) => {
          toast.add(projectCreatedToast)
          closeDialog(false)
          void navigate(`/projects/${project.id}`)
        },
        onError: (error) => toast.add(projectErrorCopy(error, "create")),
      },
    )
  }

  const sourceSearchMatches = sourceSearch.trim().toLowerCase()
  const showGitHub = "github repository".includes(sourceSearchMatches)
  const showLocal = runtime.isTauri && "local folder".includes(sourceSearchMatches)
  const repositoryStatus = menuStatus({ isLoading: repositories.isLoading, isFetchingNextPage: repositories.isFetchingNextPage, isError: repositories.isError })
  const branchStatus = menuStatus({ isLoading: branches.isLoading, isFetchingNextPage: branches.isFetchingNextPage, isError: branches.isError })
  const selectedCategoryLabel = categories.find((item) => item.value === category)?.label
  const isLocalProject = source === "local"
  const isCreating = createProject.isPending || createLocalProject.isPending

  return (
    <Dialog open={open} onOpenChange={closeDialog}>
      <DialogContent showCloseButton={false} className="max-w-md gap-0 overflow-hidden bg-sidebar p-0">
        <DialogHeader className="gap-0 px-3.5 py-2.5">
          <DialogTitle className="sr-only">Create project</DialogTitle>
          <DialogDescription className="sr-only">Choose a source, repository, branch, and project details.</DialogDescription>
          {step === 1 ? (
            <label className="flex h-9 min-w-0 items-center gap-3">
              <HugeiconsIcon icon={Search01Icon} size={16} strokeWidth={2} className="shrink-0 text-muted-foreground" />
              <span className="sr-only">Search sources</span>
              <input type="search" value={sourceSearch} onChange={(event) => setSourceSearch(event.target.value)} placeholder="Search..." className="h-9 min-w-0 flex-1 bg-transparent p-0 text-sm text-foreground outline-none placeholder:text-muted-foreground" autoFocus />
            </label>
          ) : <span className="pt-2 text-sm font-medium text-foreground">{step === 2 ? "Choose a repository" : "Add project details"}</span>}
        </DialogHeader>

        <form id="create-project-form" className="grid gap-4 px-2.5 pt-1 pb-5" onSubmit={handleSubmit}>
          {step === 1 ? <div className="grid gap-2">
            <p className="px-2 pb-1 text-xs text-muted-foreground">Sources</p>
            {showGitHub ? (
              <button
                type="button"
                disabled={!isGitHubConnected}
                onClick={() => void handleGitHubSelect()}
                className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:bg-sidebar-accent focus-visible:text-sidebar-accent-foreground focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-black ring-1 ring-white/10">
                  <img src={githubLogo} alt="" className="size-4 object-contain" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">GitHub repository</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    Import a repository and choose a branch
                  </span>
                </span>
                {isGitHubUnavailable ? (
                  <Badge
                    variant="destructive"
                    className="shrink-0"
                  >
                    Not connected
                  </Badge>
                ) : null}
              </button>
            ) : null}
            {showLocal ? <button type="button" onClick={handleLocalFolderSelect} disabled={localFolderPicker.isSelecting} className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:bg-sidebar-accent focus-visible:text-sidebar-accent-foreground focus-visible:outline-none disabled:cursor-wait disabled:opacity-60">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-secondary text-muted-foreground">
                <HugeiconsIcon icon={FolderOpenIcon} size={16} strokeWidth={2} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">Local folder</span>
                <span className="mt-0.5 block truncate text-xs">
                  {localFolderPicker.isSelecting ? "Choosing folder…" : "Choose a folder on this device"}
                </span>
                {localFolderPicker.error ? <span role="alert" className="mt-1 block text-xs text-destructive">{localFolderPicker.error.message}</span> : null}
              </span>
            </button> : null}
          </div> : null}

          {step === 2 ? <div className="grid gap-4 p-2">
            <div className="grid gap-2"><Label htmlFor="project-repository">Repository</Label><Select value={selectedRepository?.repository_id ?? ""} onValueChange={(value) => value && handleRepositoryChange(value)}><SelectTrigger type="button" id="project-repository" className={fieldClassName()}><SelectValue>{selectedRepository?.name ?? "Choose repository"}</SelectValue></SelectTrigger><SelectContent side="bottom" align="start" alignItemWithTrigger={false} collisionAvoidance={{ side: "shift", align: "shift", fallbackAxisSide: "none" }} search={<SelectSearch value={repositorySearch} onChange={setRepositorySearch} placeholder="Search repositories..." />} onScroll={(event) => fetchNextOnScroll(event, Boolean(repositories.hasNextPage), repositories.isFetchingNextPage, repositories.fetchNextPage)}>{!repositories.isLoading && !repositories.isError && repositoryItems.length === 0 ? <RepositoryPickerEmpty searchQuery={repositorySearch.trim()} /> : null}{repositoryItems.map((repository) => <SelectItem key={repository.repository_id} value={repository.repository_id}>{repository.full_name}</SelectItem>)}{repositoryStatus ? <p className="px-3 py-2 text-xs text-muted-foreground">{repositoryStatus}</p> : null}</SelectContent></Select></div>
            <div className="grid gap-2"><Label htmlFor="project-branch">Branch</Label><Select value={selectedBranch?.name ?? ""} onValueChange={(value) => { const branch = branchItems.find((item) => item.name === value); if (branch) setSelectedBranch(branch) }} disabled={!selectedRepository}><SelectTrigger type="button" id="project-branch" className={fieldClassName()}><SelectValue>{selectedBranch?.name ?? "Choose branch"}</SelectValue></SelectTrigger><SelectContent side="bottom" align="start" alignItemWithTrigger={false} collisionAvoidance={{ side: "shift", align: "shift", fallbackAxisSide: "none" }} search={<SelectSearch value={branchSearch} onChange={setBranchSearch} placeholder="Search branches..." />} onScroll={(event) => fetchNextOnScroll(event, Boolean(branches.hasNextPage), branches.isFetchingNextPage, branches.fetchNextPage)}>{!branches.isLoading && !branches.isError && branchItems.length === 0 ? <BranchPickerEmpty searchQuery={branchSearch.trim()} /> : null}{branchItems.map((branch) => <SelectItem key={branch.name} value={branch.name}>{branch.name}</SelectItem>)}{branchStatus ? <p className="px-3 py-2 text-xs text-muted-foreground">{branchStatus}</p> : null}</SelectContent></Select></div>
          </div> : null}

          {step === 3 ? <div className="grid gap-4 p-2"><div className="grid gap-2"><Label htmlFor="project-name">Project name</Label><Input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Trace Dashboard" required /></div><div className="grid gap-2"><Label htmlFor="project-category">Category</Label><Select value={category} onValueChange={(value) => value && setCategory(value as ProjectCategory)}><SelectTrigger type="button" id="project-category" className={fieldClassName()}><SelectValue>{selectedCategoryLabel}</SelectValue></SelectTrigger><SelectContent>{categories.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent></Select></div>{isLocalProject ? <div className="rounded-md border border-border bg-input/30 px-3 py-2.5"><p className="text-xs text-muted-foreground">Local folder</p><p className="mt-1 truncate text-xs text-foreground">{localFolderPicker.selection?.displayName}</p><p className="mt-1 text-xs text-muted-foreground">Trace will verify access before creating the project.</p></div> : <div className="rounded-md border border-border bg-input/30 px-3 py-2.5"><p className="text-xs text-muted-foreground">Selected commit</p><p className="mt-1 truncate font-mono text-xs text-foreground" title={selectedBranch?.commit_sha}>{selectedBranch?.commit_sha}</p><p className="mt-1 text-xs text-muted-foreground">Trace verifies this branch again before creating the project.</p></div>}{createLocalProject.error ? <p role="alert" className="text-xs text-destructive">{createLocalProject.error instanceof LocalProjectCreationError && createLocalProject.error.code === "already_exists" ? "This folder is already connected as a project. Choose another folder." : "That local folder is no longer available. Re-select the folder and try again."}</p> : null}</div> : null}
        </form>
        <DialogFooter className="flex-row items-center justify-between bg-[#242428] px-5 py-2.5">
          <Button type="button" variant="ghost" onClick={() => step === 1 ? closeDialog(false) : isLocalProject ? setStep(1) : setStep((current) => (current - 1) as Step)}>
            {step === 1 ? "Cancel" : "Back"}
          </Button>
          {step < 3 ? (
            <Button
              key="continue-to-details"
              type="button"
              disabled={step === 2 && (!selectedRepository || !selectedBranch)}
              onClick={() => setStep((current) => (current + 1) as Step)}
            >
              Continue
            </Button>
          ) : (
            <Button
              key="create-project"
              type="submit"
              form="create-project-form"
              disabled={isCreating || !name.trim() || (isLocalProject && !localFolderPicker.selection)}
            >
              {isCreating ? "Creating…" : "Create project"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
