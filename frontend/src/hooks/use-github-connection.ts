import { useQuery } from "@tanstack/react-query"

import { authApi } from "@/lib/api"

export const githubConnectionQueryKey = ["github", "connection"] as const

export function useGitHubConnection() {
  return useQuery({
    queryKey: githubConnectionQueryKey,
    queryFn: authApi.githubConnection,
    staleTime: 30_000,
    retry: false,
  })
}
