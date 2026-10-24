import { projectsApi, type ProjectPage } from "@/lib/api"
import {
  mergeApiProjectCache,
  type ApiProjectSync,
  type ApiProjectSyncResult,
  type LocalProjectStore,
} from "@/lib/desktop-projects"

const SYNC_PAGE_SIZE = 100

export type FetchProjectPage = (input: { page: number; pageSize: number }) => Promise<ProjectPage>

export class DesktopApiProjectSynchronizer implements ApiProjectSync {
  private readonly store: LocalProjectStore
  private readonly fetchPage: FetchProjectPage

  constructor(
    store: LocalProjectStore,
    fetchPage: FetchProjectPage = projectsApi.list,
  ) {
    this.store = store
    this.fetchPage = fetchPage
  }

  async sync(accountId: string): Promise<ApiProjectSyncResult> {
    const fetchedAt = new Date().toISOString()

    try {
      const apiProjects = await this.fetchAllPages()
      const existing = await this.store.list(accountId)
      const merged = mergeApiProjectCache(existing, apiProjects, accountId, fetchedAt)
      await this.store.replaceApiCache(
        accountId,
        merged.filter((project) => project.persistence === "api_cache"),
        fetchedAt,
      )

      return {
        projects: await this.store.list(accountId),
        fetchedAt,
        status: "fresh",
      }
    } catch (error) {
      await this.store.markApiCache(accountId, "unavailable", null)

      return {
        projects: await this.store.list(accountId),
        fetchedAt,
        status: "unavailable",
        error,
      }
    }
  }

  private async fetchAllPages() {
    const projects = [] as Awaited<ReturnType<FetchProjectPage>>["items"]
    let page = 1

    while (true) {
      const result = await this.fetchPage({ page, pageSize: SYNC_PAGE_SIZE })
      projects.push(...result.items)
      if (result.next_offset === null) return projects

      page = Math.floor(result.next_offset / SYNC_PAGE_SIZE) + 1
    }
  }
}
