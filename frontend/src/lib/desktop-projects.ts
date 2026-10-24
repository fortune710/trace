import type { Project, ProjectCategory } from "@/lib/api"

export type LocalSourceAvailability =
  | "available"
  | "missing"
  | "unreadable"
  | "permission_denied"

export type LocalSourceValidationCode =
  | "missing"
  | "not_directory"
  | "permission_denied"
  | "unreadable"
  | "validation_failed"

export type LocalProjectCreationErrorCode = "already_exists"

export type DesktopLocalSource = {
  kind: "local"
  sourceId: string
  displayName: string
  canonicalPath: string
  availability: LocalSourceAvailability
  lastValidatedAt: string | null
  apiProjectId?: string | null
}

export type DesktopApiSource = {
  kind: "github"
  apiProjectId: string
  repositoryOwner: string | null
  repositoryName: string | null
  branchName: string | null
  currentRevision: string | null
}

export type DesktopProjectRecord = {
  id: string
  accountId: string
  persistence: "local" | "api_cache"
  name: string
  category: ProjectCategory
  source: DesktopLocalSource | DesktopApiSource
  createdAt: string
  updatedAt: string
  apiLastFetchedAt: string | null
  apiCacheStatus: "not_applicable" | "fresh" | "stale" | "unavailable"
}

export class LocalSourceValidationError extends Error {
  readonly code: LocalSourceValidationCode

  constructor(code: LocalSourceValidationCode) {
    super(code)
    this.name = "LocalSourceValidationError"
    this.code = code
  }
}

export class LocalProjectCreationError extends Error {
  readonly code: LocalProjectCreationErrorCode

  constructor(code: LocalProjectCreationErrorCode) {
    super(code)
    this.name = "LocalProjectCreationError"
    this.code = code
  }
}

export interface LocalProjectStore {
  list(accountId: string): Promise<DesktopProjectRecord[]>
  get(accountId: string, projectId: string): Promise<DesktopProjectRecord | null>
  getByApiProjectId(
    accountId: string,
    apiProjectId: string,
  ): Promise<DesktopProjectRecord | null>
  insertLocal(project: DesktopProjectRecord): Promise<void>
  updateLocal(project: DesktopProjectRecord): Promise<void>
  removeLocal(accountId: string, projectId: string): Promise<void>
  replaceApiCache(accountId: string, projects: DesktopProjectRecord[], fetchedAt: string): Promise<void>
  markApiCache(accountId: string, status: "fresh" | "stale" | "unavailable", fetchedAt: string | null): Promise<void>
}

export interface LocalSourceRegistry {
  register(accountId: string, source: Omit<DesktopLocalSource, "sourceId">): Promise<DesktopLocalSource>
  resolve(accountId: string, sourceId: string): Promise<DesktopLocalSource | null>
  revalidate(accountId: string, sourceId: string): Promise<DesktopLocalSource>
  disconnect(accountId: string, sourceId: string): Promise<void>
}

export type ApiProjectSyncResult = {
  projects: DesktopProjectRecord[]
  fetchedAt: string
  status: "fresh" | "stale" | "unavailable"
  error?: unknown
}

export interface ApiProjectSync {
  sync(accountId: string): Promise<ApiProjectSyncResult>
}

export function desktopApiSource(project: Project): DesktopApiSource | null {
  if (project.source !== "github") return null

  return {
    kind: "github",
    apiProjectId: project.id,
    repositoryOwner: project.repository_owner,
    repositoryName: project.repository_name,
    branchName: project.branch_name,
    currentRevision: project.current_revision,
  }
}

export function toDesktopApiProject(project: Project, accountId: string, fetchedAt: string): DesktopProjectRecord | null {
  const source = desktopApiSource(project)
  if (!source) return null

  return {
    id: `api:${accountId}:${project.id}`,
    accountId,
    persistence: "api_cache",
    name: project.name,
    category: project.category,
    source,
    createdAt: project.created_at,
    updatedAt: project.updated_at,
    apiLastFetchedAt: fetchedAt,
    apiCacheStatus: "fresh",
  }
}

export function mergeApiProjectCache(
  existing: DesktopProjectRecord[],
  apiProjects: Project[],
  accountId: string,
  fetchedAt: string,
): DesktopProjectRecord[] {
  const localProjects = existing.filter(
    (project) => project.accountId === accountId && project.persistence === "local",
  )
  const apiCache = apiProjects
    .map((project) => toDesktopApiProject(project, accountId, fetchedAt))
    .filter((project): project is DesktopProjectRecord => project !== null)

  return [...localProjects, ...apiCache]
}

export function toProjectResponse(project: DesktopProjectRecord): Project {
  if (project.source.kind === "local") {
    return {
      id: project.id,
      name: project.name,
      source: "local",
      external_repository_id: null,
      external_repository_connection_id: null,
      repository_owner: null,
      repository_name: project.source.displayName,
      branch_name: null,
      repository_visibility: null,
      imported_at: project.createdAt,
      source_hash: null,
      current_revision: null,
      category: project.category,
      auto_create_pull_requests: false,
      created_at: project.createdAt,
      updated_at: project.updatedAt,
      archived_at: null,
      local_source_id: project.source.sourceId,
      api_project_id: project.source.apiProjectId,
    }
  }

  return {
    id: project.id,
    name: project.name,
    source: "github",
    external_repository_id: null,
    external_repository_connection_id: null,
    repository_owner: project.source.repositoryOwner,
    repository_name: project.source.repositoryName,
    branch_name: project.source.branchName,
    repository_visibility: null,
    imported_at: project.createdAt,
    source_hash: null,
    current_revision: project.source.currentRevision,
    category: project.category,
    auto_create_pull_requests: false,
    created_at: project.createdAt,
    updated_at: project.updatedAt,
    archived_at: null,
    api_project_id: project.source.apiProjectId,
  }
}
