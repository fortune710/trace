import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import {
  projectsApi,
  repositoriesApi,
  type Project,
  type ProjectCategory,
} from "@/lib/api"
import { toProjectResponse, type DesktopProjectRecord } from "@/lib/desktop-projects"
import { getLocalProjectsDatabase } from "@/lib/local-projects-database"
import { useDesktopProjectSync } from "@/hooks/use-desktop-project-sync"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { useSession } from "@/hooks/use-session"

export type { Project, ProjectCategory }

export type CreateProjectInput = {
  name: string
  category: ProjectCategory
  repositoryId: string
  branchName: string
}

export type CreateLocalProjectInput = {
  name: string
  category: ProjectCategory
  sourceId: string
}

export const projectsQueryKey = ["projects"] as const
const PROJECTS_PAGE_SIZE = 9

export function useProjects(page: number) {
  const runtime = useRuntimeEnvironment()
  const session = useSession()
  const sync = useDesktopProjectSync()
  const accountId = session.data?.user_id
  const webQuery = useQuery({
    queryKey: [...projectsQueryKey, page, PROJECTS_PAGE_SIZE],
    queryFn: () => projectsApi.list({ page, pageSize: PROJECTS_PAGE_SIZE }),
    placeholderData: keepPreviousData,
    enabled: runtime.isWeb,
    retry: false,
  })
  const desktopQuery = useQuery({
    queryKey: [...projectsQueryKey, "desktop", accountId, page, PROJECTS_PAGE_SIZE],
    queryFn: async () => {
      const database = await getLocalProjectsDatabase()
      const allProjects = (await database.list(accountId!)).map(toProjectResponse)
      const start = (page - 1) * PROJECTS_PAGE_SIZE
      const items = allProjects.slice(start, start + PROJECTS_PAGE_SIZE)
      const nextStart = start + PROJECTS_PAGE_SIZE
      return {
        items,
        next_offset: nextStart < allProjects.length ? nextStart : null,
      }
    },
    enabled: runtime.isTauri && Boolean(accountId) && sync.isReady,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  })
  const query = runtime.isTauri ? desktopQuery : webQuery

  return {
    ...query,
    projects: query.data?.items ?? [],
    hasNextPage: query.data?.next_offset !== null,
  }
}

export function useProject(projectId: string | undefined) {
  const runtime = useRuntimeEnvironment()
  const session = useSession()
  const sync = useDesktopProjectSync()
  const accountId = session.data?.user_id
  const webQuery = useQuery({
    queryKey: [...projectsQueryKey, "detail", projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: runtime.isWeb && Boolean(projectId),
    retry: false,
  })
  const desktopQuery = useQuery({
    queryKey: [...projectsQueryKey, "desktop", "detail", accountId, projectId],
    queryFn: async () => {
      const database = await getLocalProjectsDatabase()
      const project =
        (await database.get(accountId!, projectId!)) ??
        (await database.getByApiProjectId(accountId!, projectId!))
      return project ? toProjectResponse(project) : null
    },
    enabled: runtime.isTauri && Boolean(accountId) && Boolean(projectId) && sync.isReady,
    staleTime: Infinity,
    retry: false,
  })

  return runtime.isTauri ? desktopQuery : webQuery
}

export function useCreateProject() {
  const queryClient = useQueryClient()
  const runtime = useRuntimeEnvironment()
  const sync = useDesktopProjectSync()

  return useMutation({
    mutationFn: (input: CreateProjectInput) =>
      projectsApi.create({
        name: input.name,
        source: "github",
        repository_id: input.repositoryId,
        branch_name: input.branchName,
        category: input.category,
        auto_create_pull_requests: false,
    }),
    onSuccess: async () => {
      void queryClient.invalidateQueries({ queryKey: projectsQueryKey })
      if (runtime.isTauri) await sync.syncNow()
    },
  })
}

export function useCreateLocalProject() {
  const queryClient = useQueryClient()
  const runtime = useRuntimeEnvironment()
  const session = useSession()

  return useMutation({
    mutationFn: async (input: CreateLocalProjectInput) => {
      if (!runtime.isTauri) throw new Error("Local projects are available in the desktop app only")
      const accountId = session.data?.user_id
      if (!accountId) throw new Error("Sign in before creating a local project")

      const database = await getLocalProjectsDatabase()
      const source = await database.revalidate(accountId, input.sourceId)
      const timestamp = new Date().toISOString()
      const project: DesktopProjectRecord = {
        id: `local:${crypto.randomUUID()}`,
        accountId,
        persistence: "local",
        name: input.name.trim(),
        category: input.category,
        source,
        createdAt: timestamp,
        updatedAt: timestamp,
        apiLastFetchedAt: null,
        apiCacheStatus: "not_applicable",
      }

      await database.insertLocal(project)
      return toProjectResponse(project)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: projectsQueryKey })
    },
  })
}

export function useRepositories(query: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: ["repositories", "github", query],
    queryFn: ({ pageParam }) =>
      repositoriesApi.list({ page: pageParam, query: query || undefined }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => lastPage.next_page ?? undefined,
    enabled,
    retry: false,
  })
}

export function useBranches(repositoryId: string | null, query: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: ["branches", "github", repositoryId, query],
    queryFn: ({ pageParam }) =>
      repositoriesApi.listBranches({
        repositoryId: repositoryId!,
        page: pageParam,
        query: query || undefined,
      }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => lastPage.next_page ?? undefined,
    enabled: enabled && repositoryId !== null,
    retry: false,
  })
}
