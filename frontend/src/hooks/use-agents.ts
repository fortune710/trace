import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import {
  agentsApi,
  credentialsApi,
  type Agent,
  type AgentCreate,
  type AgentUpdate,
  type Credential,
  type CredentialCreate,
} from "@/lib/api"

export type { Agent, AgentCreate, AgentUpdate, Credential }

export const agentsQueryKey = ["agents"] as const
export const credentialsQueryKey = ["credentials"] as const
export const AGENTS_PAGE_SIZE = 9

export function useAgents(page: number) {
  const query = useQuery({
    queryKey: [...agentsQueryKey, page, AGENTS_PAGE_SIZE, "all"],
    queryFn: () =>
      agentsApi.list({
        page,
        pageSize: AGENTS_PAGE_SIZE,
        includeDisabled: true,
      }),
    placeholderData: keepPreviousData,
    retry: false,
  })

  return {
    ...query,
    agents: query.data?.items ?? [],
    hasNextPage: query.data?.next_offset !== null,
  }
}

export function useAgent(agentId: string | undefined) {
  return useQuery({
    queryKey: [...agentsQueryKey, "detail", agentId],
    queryFn: () => agentsApi.get(agentId!),
    enabled: Boolean(agentId),
    retry: false,
  })
}

export function useAgentModelCatalog() {
  return useQuery({
    queryKey: [...agentsQueryKey, "catalog"],
    queryFn: agentsApi.catalog,
    staleTime: Infinity,
    retry: false,
  })
}

export function useProviderCredentials() {
  const query = useQuery({
    queryKey: [...credentialsQueryKey, "active"],
    queryFn: () => credentialsApi.list({ page: 1, pageSize: 100 }),
    retry: false,
  })
  return {
    ...query,
    credentials: (query.data?.items ?? []).filter(
      (credential) => credential.active && credential.kind === "api_key",
    ),
  }
}

export function useCreateAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (agent: AgentCreate) => agentsApi.create(agent),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: agentsQueryKey }),
  })
}

export function useUpdateAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, agent }: { agentId: string; agent: AgentUpdate }) =>
      agentsApi.update(agentId, agent),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: agentsQueryKey }),
  })
}

export function useDisableAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (agentId: string) => agentsApi.disable(agentId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: agentsQueryKey }),
  })
}

export function useCreateProviderCredential() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: credentialsApi.create,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: credentialsQueryKey }),
  })
}

export function useRevokeProviderCredential() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: credentialsApi.revoke,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: credentialsQueryKey }),
  })
}

export function useRotateProviderCredential() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      credentialId,
      credential,
    }: {
      credentialId: string
      credential: CredentialCreate
    }) => credentialsApi.rotate(credentialId, credential),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: credentialsQueryKey }),
  })
}
