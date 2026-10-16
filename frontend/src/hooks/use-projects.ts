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

export type { Project, ProjectCategory }

export type CreateProjectInput = {
  name: string
  category: ProjectCategory
  repositoryId: string
  branchName: string
}

export const projectsQueryKey = ["projects"] as const
const PROJECTS_PAGE_SIZE = 9

export function useProjects(page: number) {
  const query = useQuery({
    queryKey: [...projectsQueryKey, page, PROJECTS_PAGE_SIZE],
    queryFn: () => projectsApi.list({ page, pageSize: PROJECTS_PAGE_SIZE }),
    placeholderData: keepPreviousData,
    retry: false,
  })

  return {
    ...query,
    projects: query.data?.items ?? [],
    hasNextPage: query.data?.next_offset !== null,
  }
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: [...projectsQueryKey, "detail", projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  })
}

export function useCreateProject() {
  const queryClient = useQueryClient()

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
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: projectsQueryKey })
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
