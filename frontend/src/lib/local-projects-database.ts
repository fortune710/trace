import { invoke } from "@tauri-apps/api/core"

import {
  LocalProjectCreationError,
  LocalSourceValidationError,
  type DesktopLocalSource,
  type DesktopProjectRecord,
  type LocalProjectStore,
  type LocalSourceValidationCode,
  type LocalSourceAvailability,
  type LocalSourceRegistry,
} from "@/lib/desktop-projects"

type SqlDatabase = {
  execute(query: string, bindValues?: unknown[]): Promise<{ rowsAffected: number }>
  select<T>(query: string, bindValues?: unknown[]): Promise<T[]>
}

type ProjectRow = {
  id: string
  account_id: string
  persistence: "local" | "api_cache"
  name: string
  category: DesktopProjectRecord["category"]
  source_kind: "local" | "github"
  local_source_id: string | null
  api_project_id: string | null
  repository_owner: string | null
  repository_name: string | null
  branch_name: string | null
  current_revision: string | null
  created_at: string
  updated_at: string
  api_last_fetched_at: string | null
  api_cache_status: DesktopProjectRecord["apiCacheStatus"]
  local_display_name: string | null
  local_canonical_path: string | null
  local_availability: LocalSourceAvailability | null
  local_last_validated_at: string | null
}

type LocalSourceRow = {
  source_id: string
  display_name: string
  canonical_path: string
  availability: LocalSourceAvailability
  last_validated_at: string | null
}

type NativeFolderValidation = {
  displayName: string
}

type NativeFolderError = {
  code?: string
}

const databasePath = "sqlite:trace.db"
const busyTimeoutMilliseconds = 5000
let databasePromise: Promise<LocalProjectsDatabase> | undefined

async function loadDatabase(): Promise<SqlDatabase> {
  const { default: Database } = await import("@tauri-apps/plugin-sql")
  const database = await Database.load(databasePath)
  await database.execute(`PRAGMA busy_timeout = ${busyTimeoutMilliseconds}`)
  return database
}

function now() {
  return new Date().toISOString()
}

function validationCode(error: unknown): LocalSourceValidationCode {
  const code = (error as NativeFolderError | null)?.code
  switch (code) {
    case "missing":
    case "not_directory":
    case "permission_denied":
    case "unreadable":
    case "validation_failed":
      return code
    default:
      return "validation_failed"
  }
}

function availabilityFor(code: LocalSourceValidationCode): LocalSourceAvailability {
  if (code === "missing") return "missing"
  if (code === "permission_denied") return "permission_denied"
  return "unreadable"
}

function localSourceFromRow(row: ProjectRow): DesktopLocalSource {
  if (
    row.local_source_id === null ||
    row.local_display_name === null ||
    row.local_canonical_path === null ||
    row.local_availability === null
  ) {
    throw new Error("Local desktop project is missing its source mapping")
  }

  return {
    kind: "local",
    sourceId: row.local_source_id,
    displayName: row.local_display_name,
    canonicalPath: row.local_canonical_path,
    availability: row.local_availability,
    lastValidatedAt: row.local_last_validated_at,
  }
}

function projectFromRow(row: ProjectRow): DesktopProjectRecord {
  const source = row.source_kind === "local"
    ? localSourceFromRow(row)
    : {
      kind: "github" as const,
      apiProjectId: row.api_project_id ?? "",
      repositoryOwner: row.repository_owner,
      repositoryName: row.repository_name,
      branchName: row.branch_name,
      currentRevision: row.current_revision,
    }

  return {
    id: row.id,
    accountId: row.account_id,
    persistence: row.persistence,
    name: row.name,
    category: row.category,
    source,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    apiLastFetchedAt: row.api_last_fetched_at,
    apiCacheStatus: row.api_cache_status,
  }
}

export class LocalProjectsDatabase implements LocalProjectStore, LocalSourceRegistry {
  private readonly database: Promise<SqlDatabase>

  constructor(database: Promise<SqlDatabase> = loadDatabase()) {
    this.database = database
  }

  async list(accountId: string): Promise<DesktopProjectRecord[]> {
    const database = await this.database
    const rows = await database.select<ProjectRow>(projectQuery, [accountId])
    return rows.map(projectFromRow)
  }

  async get(accountId: string, projectId: string): Promise<DesktopProjectRecord | null> {
    const database = await this.database
    const rows = await database.select<ProjectRow>(`${projectQuery} AND p.id = $2 ORDER BY p.created_at DESC, p.id DESC`, [accountId, projectId])
    return rows[0] ? projectFromRow(rows[0]) : null
  }

  async insertLocal(project: DesktopProjectRecord): Promise<void> {
    this.assertLocalProject(project)
    try {
      await this.withTransaction(async (database) => {
        const existing = await database.select<{ id: string }>(
          `SELECT id
           FROM desktop_projects
           WHERE account_id = $1
             AND persistence = 'local'
             AND local_canonical_path = $2
           LIMIT 1`,
          [project.accountId, project.source.canonicalPath],
        )
        if (existing[0]) throw new LocalProjectCreationError("already_exists")

        await this.upsertSource(database, project.accountId, project.source)
        await this.insertProject(database, project)
      })
    } catch (error) {
      if (isLocalProjectPathConstraint(error)) {
        throw new LocalProjectCreationError("already_exists")
      }
      throw error
    }
  }

  async updateLocal(project: DesktopProjectRecord): Promise<void> {
    this.assertLocalProject(project)
    await this.withTransaction(async (database) => {
      await this.upsertSource(database, project.accountId, project.source)
      await database.execute(
         `UPDATE desktop_projects
         SET name = $1, category = $2, local_canonical_path = $3, updated_at = $4, api_cache_status = 'not_applicable'
         WHERE id = $5 AND account_id = $6 AND persistence = 'local'`,
        [project.name, project.category, project.source.canonicalPath, project.updatedAt, project.id, project.accountId],
      )
    })
  }

  async removeLocal(accountId: string, projectId: string): Promise<void> {
    await this.withTransaction(async (database) => {
      const rows = await database.select<{ local_source_id: string | null }>(
        "SELECT local_source_id FROM desktop_projects WHERE id = $1 AND account_id = $2 AND persistence = 'local'",
        [projectId, accountId],
      )
      await database.execute(
        "DELETE FROM desktop_projects WHERE id = $1 AND account_id = $2 AND persistence = 'local'",
        [projectId, accountId],
      )
      if (rows[0]?.local_source_id) {
        await database.execute(
          "DELETE FROM local_sources WHERE account_id = $1 AND source_id = $2",
          [accountId, rows[0].local_source_id],
        )
      }
    })
  }

  async replaceApiCache(accountId: string, projects: DesktopProjectRecord[], fetchedAt: string): Promise<void> {
    const apiProjects = projects.filter(
      (project) => project.accountId === accountId && project.persistence === "api_cache" && project.source.kind === "github",
    )

    await this.withTransaction(async (database) => {
      await database.execute(
        "DELETE FROM desktop_projects WHERE account_id = $1 AND persistence = 'api_cache'",
        [accountId],
      )
      for (const project of apiProjects) {
        await this.insertProject(database, { ...project, apiLastFetchedAt: fetchedAt, apiCacheStatus: "fresh" })
      }
    })
  }

  async markApiCache(accountId: string, status: "fresh" | "stale" | "unavailable", fetchedAt: string | null): Promise<void> {
    const database = await this.database
    await database.execute(
      `UPDATE desktop_projects
       SET api_cache_status = $1,
           api_last_fetched_at = COALESCE($2, api_last_fetched_at),
           updated_at = $3
       WHERE account_id = $4 AND persistence = 'api_cache'`,
      [status, fetchedAt, now(), accountId],
    )
  }

  async register(accountId: string, source: Omit<DesktopLocalSource, "sourceId">): Promise<DesktopLocalSource> {
    const registered = { ...source, sourceId: crypto.randomUUID() }
    const database = await this.database
    await database.execute(
      `INSERT INTO local_sources
       (account_id, source_id, display_name, canonical_path, availability, last_validated_at, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $7)`,
      [accountId, registered.sourceId, registered.displayName, registered.canonicalPath, registered.availability, registered.lastValidatedAt, now()],
    )
    return registered
  }

  async resolve(accountId: string, sourceId: string): Promise<DesktopLocalSource | null> {
    const database = await this.database
    const rows = await database.select<LocalSourceRow>(
      `SELECT source_id, display_name, canonical_path, availability, last_validated_at
       FROM local_sources WHERE account_id = $1 AND source_id = $2`,
      [accountId, sourceId],
    )
    const row = rows[0]
    return row
      ? { kind: "local", sourceId: row.source_id, displayName: row.display_name, canonicalPath: row.canonical_path, availability: row.availability, lastValidatedAt: row.last_validated_at }
      : null
  }

  async revalidate(accountId: string, sourceId: string): Promise<DesktopLocalSource> {
    const source = await this.resolve(accountId, sourceId)
    if (!source) throw new LocalSourceValidationError("missing")

    const validatedAt = now()
    try {
      const result = await invoke<NativeFolderValidation>("validate_local_folder", {
        canonicalPath: source.canonicalPath,
      })
      const database = await this.database
      await database.execute(
        `UPDATE local_sources
         SET display_name = $1, availability = 'available', last_validated_at = $2, updated_at = $2
         WHERE account_id = $3 AND source_id = $4`,
        [result.displayName, validatedAt, accountId, sourceId],
      )
      return {
        ...source,
        displayName: result.displayName,
        availability: "available",
        lastValidatedAt: validatedAt,
      }
    } catch (error) {
      const code = validationCode(error)
      const database = await this.database
      await database.execute(
        `UPDATE local_sources
         SET availability = $1, last_validated_at = $2, updated_at = $2
         WHERE account_id = $3 AND source_id = $4`,
        [availabilityFor(code), validatedAt, accountId, sourceId],
      )
      throw new LocalSourceValidationError(code)
    }
  }

  async disconnect(accountId: string, sourceId: string): Promise<void> {
    await this.withTransaction(async (database) => {
      await database.execute(
        "DELETE FROM desktop_projects WHERE account_id = $1 AND persistence = 'local' AND local_source_id = $2",
        [accountId, sourceId],
      )
      await database.execute(
        "DELETE FROM local_sources WHERE account_id = $1 AND source_id = $2",
        [accountId, sourceId],
      )
    })
  }

  private async insertProject(database: SqlDatabase, project: DesktopProjectRecord): Promise<void> {
    const source = project.source
    await database.execute(
      `INSERT INTO desktop_projects
       (id, account_id, persistence, name, category, source_kind, local_source_id, api_project_id,
        repository_owner, repository_name, branch_name, current_revision, created_at, updated_at,
        api_last_fetched_at, api_cache_status, local_canonical_path)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)`,
      [
        project.id,
        project.accountId,
        project.persistence,
        project.name,
        project.category,
        source.kind,
        source.kind === "local" ? source.sourceId : null,
        source.kind === "github" ? source.apiProjectId : null,
        source.kind === "github" ? source.repositoryOwner : null,
        source.kind === "github" ? source.repositoryName : null,
        source.kind === "github" ? source.branchName : null,
        source.kind === "github" ? source.currentRevision : null,
        project.createdAt,
        project.updatedAt,
        project.apiLastFetchedAt,
        project.apiCacheStatus,
        source.kind === "local" ? source.canonicalPath : null,
      ],
    )
  }

  private async upsertSource(database: SqlDatabase, accountId: string, source: DesktopLocalSource): Promise<void> {
    await database.execute(
      `INSERT INTO local_sources
       (account_id, source_id, display_name, canonical_path, availability, last_validated_at, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
       ON CONFLICT (account_id, source_id) DO UPDATE SET
         display_name = excluded.display_name,
         canonical_path = excluded.canonical_path,
         availability = excluded.availability,
         last_validated_at = excluded.last_validated_at,
         updated_at = excluded.updated_at`,
      [accountId, source.sourceId, source.displayName, source.canonicalPath, source.availability, source.lastValidatedAt, now()],
    )
  }

  private assertLocalProject(project: DesktopProjectRecord): asserts project is DesktopProjectRecord & { source: DesktopLocalSource } {
    if (project.persistence !== "local" || project.source.kind !== "local") {
      throw new Error("Only local projects can be written through the local project store")
    }
  }

  private async withTransaction<T>(operation: (database: SqlDatabase) => Promise<T>): Promise<T> {
    const database = await this.database
    await database.execute("BEGIN IMMEDIATE")
    try {
      const result = await operation(database)
      await database.execute("COMMIT")
      return result
    } catch (error) {
      await database.execute("ROLLBACK")
      throw error
    }
  }
}

function isLocalProjectPathConstraint(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  return error.message.includes("desktop_projects_local_path_key")
    || error.message.includes("desktop_projects.account_id, desktop_projects.local_canonical_path")
}

export function getLocalProjectsDatabase(): Promise<LocalProjectsDatabase> {
  databasePromise ??= Promise.resolve(new LocalProjectsDatabase())
  return databasePromise
}

const projectQuery = `
  SELECT
    p.id, p.account_id, p.persistence, p.name, p.category, p.source_kind,
    p.local_source_id, p.api_project_id, p.repository_owner, p.repository_name,
    p.branch_name, p.current_revision, p.created_at, p.updated_at,
    p.api_last_fetched_at, p.api_cache_status,
    s.display_name AS local_display_name,
    s.canonical_path AS local_canonical_path,
    s.availability AS local_availability,
    s.last_validated_at AS local_last_validated_at
  FROM desktop_projects p
  LEFT JOIN local_sources s
    ON s.account_id = p.account_id AND s.source_id = p.local_source_id
  WHERE p.account_id = $1`
