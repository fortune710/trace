import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import {
  ApiError,
  agentsApi,
  credentialsApi,
  type Agent,
  type AgentCreate,
  type AgentUpdate,
  type AvatarConfig,
  type Credential,
  type CredentialCreate,
} from "@/lib/api"
import { trackEvent } from "@/lib/analytics"

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
    mutationFn: (agent: AgentCreate) => {
      trackEvent("agent_create_submitted", {
        review_category: agent.review_category,
        model_provider: agent.model_provider,
      })
      return agentsApi.create(agent)
    },
    onSuccess: (created, agent) => {
      trackEvent("agent_create_succeeded", {
        agent_id: created.id,
        review_category: agent.review_category,
        model_provider: agent.model_provider,
      })
      queryClient.invalidateQueries({ queryKey: agentsQueryKey })
    },
    onError: (error, agent) => {
      trackEvent("agent_create_failed", {
        review_category: agent.review_category,
        model_provider: agent.model_provider,
        error_code: error instanceof ApiError ? error.code : undefined,
      })
    },
  })
}

export function useUpdateAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, agent }: { agentId: string; agent: AgentUpdate }) =>
      agentsApi.update(agentId, agent),
    onSuccess: (_updated, { agentId, agent }) => {
      trackEvent("agent_updated", {
        agent_id: agentId,
        fields: Object.keys(agent),
      })
      queryClient.invalidateQueries({ queryKey: agentsQueryKey })
    },
  })
}

export function useDisableAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (agentId: string) => agentsApi.disable(agentId),
    onSuccess: (_result, agentId) => {
      trackEvent("agent_disabled", { agent_id: agentId })
      queryClient.invalidateQueries({ queryKey: agentsQueryKey })
    },
  })
}

export function useUploadAgentAvatar() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentId,
      file,
      config,
    }: {
      agentId: string
      file: Blob
      config: AvatarConfig
    }) => agentsApi.uploadAvatar(agentId, file, config),
    onSuccess: (_result, { agentId }) => {
      trackEvent("agent_avatar_uploaded", { agent_id: agentId })
      queryClient.invalidateQueries({ queryKey: agentsQueryKey })
    },
  })
}

export function useDeleteAgentAvatar() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (agentId: string) => agentsApi.deleteAvatar(agentId),
    onSuccess: (_result, agentId) => {
      trackEvent("agent_avatar_deleted", { agent_id: agentId })
      queryClient.invalidateQueries({ queryKey: agentsQueryKey })
    },
  })
}

export function useCreateProviderCredential() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: credentialsApi.create,
    onSuccess: (_created, credential) => {
      trackEvent("settings_api_key_saved", {
        provider: credential.provider,
        action: "create",
      })
      queryClient.invalidateQueries({ queryKey: credentialsQueryKey })
    },
    onError: (error, credential) => {
      trackEvent("settings_api_key_save_failed", {
        provider: credential.provider,
        action: "create",
        error_code: error instanceof ApiError ? error.code : undefined,
      })
    },
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
    onSuccess: (_rotated, { credential }) => {
      trackEvent("settings_api_key_saved", {
        provider: credential.provider,
        action: "rotate",
      })
      queryClient.invalidateQueries({ queryKey: credentialsQueryKey })
    },
    onError: (error, { credential }) => {
      trackEvent("settings_api_key_save_failed", {
        provider: credential.provider,
        action: "rotate",
        error_code: error instanceof ApiError ? error.code : undefined,
      })
    },
  })
}
