import { isTauri } from "@tauri-apps/api/core"

import {
  clearDesktopCsrfToken,
  getDesktopCsrfToken,
  setDesktopCsrfToken,
} from "@/lib/desktop-auth-state"
import { desktopTelemetry } from "@/lib/desktop-telemetry"
import { runtimeConfig } from "@/lib/runtime-config"

export type Session = {
  user_id: string
  session_id: string
  email?: string | null
  display_name?: string | null
  automatic_pull_requests: boolean
}

export type GitHubConnectionStatus =
  "connected" | "never_connected" | "needs_reconnection"

export type GitHubConnection = {
  provider: "github"
  status: GitHubConnectionStatus
}

type ApiErrorPayload = {
  error?: {
    code?: string
    message?: string
    request_id?: string
  }
}

export type ProjectCategory =
  | "entertainment"
  | "educational"
  | "sports"
  | "gaming"
  | "business"
  | "health"
  | "finance"
  | "social"
  | "productivity"
  | "e_commerce"
  | "other"

export type Project = {
  id: string
  name: string
  source: "github" | "local"
  external_repository_id: string | null
  external_repository_connection_id: string | null
  repository_owner: string | null
  repository_name: string | null
  branch_name: string | null
  repository_visibility: string | null
  imported_at: string | null
  source_hash: string | null
  current_revision: string | null
  category: ProjectCategory
  auto_create_pull_requests: boolean
  created_at: string
  updated_at: string
  archived_at: string | null
  local_source_id?: string
  api_project_id?: string | null
}

export type ProjectPage = {
  items: Project[]
  next_offset: number | null
}

export type IssueProviderName = "github" | "linear"

export type ConnectedIssueProject = {
  provider: IssueProviderName
  owner: string
  project: string
}

export type IssueTrackingDetails = {
  connected_projects: ConnectedIssueProject[]
}

export type LinearTeam = {
  id: string
  name: string
  key: string
}

export type LinearProject = {
  id: string
  name: string
}

export type IssueLinkState = "pending" | "created" | "failed"

export type IssueLink = {
  id: string
  finding_id: string
  provider: IssueProviderName
  destination_id: string
  external_identifier: string | null
  external_url: string | null
  state: IssueLinkState
  failure_code: string | null
  created_at: string
  updated_at: string
}

export type IssuePreview = {
  title: string
  body_markdown: string
}

export type ReviewCategory =
  | "security"
  | "engineering"
  | "product"
  | "legal"
  | "accessibility"
  | "marketing"

export type ModelProvider = "openai" | "anthropic" | "google" | "xai"

export type AgentSkill = string | Record<string, object>

export type Agent = {
  id: string
  name: string
  personality: string | null
  review_category: ReviewCategory
  model_provider: ModelProvider
  model_name: string
  avatar: string | null
  skills: AgentSkill[]
  credential_id: string | null
  configuration_version: number
  created_at: string
  updated_at: string
  disabled_at: string | null
}

export type AgentCreate = {
  name: string
  personality?: string | null
  review_category: ReviewCategory
  model_provider: ModelProvider
  model_name: string
  avatar?: string | null
  skills: AgentSkill[]
  credential_id?: string | null
}

export type AgentUpdate = Partial<AgentCreate>

export type AgentPage = {
  items: Agent[]
  next_offset: number | null
}

export type AgentModel = {
  id: string
  label: string
}

export type AgentModelProvider = {
  id: ModelProvider
  label: string
  models: AgentModel[]
}

export type AgentModelCatalog = {
  providers: AgentModelProvider[]
}

export type CredentialProvider = ModelProvider | "github"

export type Credential = {
  id: string
  provider: CredentialProvider
  kind: "oauth" | "api_key"
  name: string | null
  active: boolean
  created_at: string
  updated_at: string
  revoked_at: string | null
}

export type CredentialPage = {
  items: Credential[]
  next_offset: number | null
}

export type CredentialCreate = {
  provider: ModelProvider
  kind: "api_key"
  name?: string | null
  payload: {
    api_key: string
  }
}

export type Repository = {
  source: "github"
  repository_id: string
  owner_login: string
  name: string
  full_name: string
  visibility: string
  private: boolean
  default_branch: string | null
  web_url: string
}

export type RepositoryPage = {
  items: Repository[]
  next_page: number | null
}

export type Branch = {
  source: "github"
  repository_id: string
  name: string
  commit_sha: string
  protected: boolean
}

export type BranchPage = {
  items: Branch[]
  next_page: number | null
}

export type GitHubProjectCreate = {
  name: string
  source: "github"
  repository_id: string
  branch_name: string
  category: ProjectCategory
  auto_create_pull_requests: boolean
}

export type LocalProjectCreate = {
  name: string
  source: "local"
  local_path_hash: string
  category: ProjectCategory
  auto_create_pull_requests: boolean
}

export type ProjectCreate = GitHubProjectCreate | LocalProjectCreate

export type LocalSourceSnapshot = {
  source_id: string
  integrity_algorithm: "sha256-directory-manifest-v1"
  digest: string
}

export type ReviewSourceSnapshot = {
  source_kind: "github" | "local"
  source_identifier: string
  integrity_algorithm: string
  revision: string
  captured_at: string
}

export type ReviewAgent = {
  assignment_id: string
  agent_id: string
  name: string
  review_category: ReviewCategory
  model_provider: ModelProvider
  model_name: string
  personality: string | null
  skills: AgentSkill[]
  configuration_version: number
  status: "assigned" | "running" | "completed" | "failed" | "cancelled"
  assigned_at: string
  started_at: string | null
  completed_at: string | null
}

export type Review = {
  id: string
  project_id: string
  source_revision: string
  source_snapshot: ReviewSourceSnapshot
  status: "queued" | "running" | "completed" | "failed" | "cancelled"
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  agents: ReviewAgent[]
  warnings?: string[]
  remediation_generation_failed_count?: number
}

export type ReviewPage = {
  items: Review[]
  next_offset: number | null
}

export type ReviewCreate = {
  project_id: string
  agent_ids: string[]
  local_source_snapshot?: LocalSourceSnapshot
  local_source_upload?: {
    digest: string
    entries: {
      path: string
      directory: boolean
      content_base64: string | null
      content_sha256?: string | null
    }[]
  }
}

export type FindingSeverity = "info" | "low" | "medium" | "high" | "critical"
export type FindingStatus = "open" | "accepted" | "resolved" | "dismissed"

export type ReviewingAgent = {
  assignment_id: string
  agent_id: string
  display_name: string
  specialization: ReviewCategory
}

export type Finding = {
  id: string
  review_id: string
  agent_id: string
  reviewing_agent: ReviewingAgent
  category: ReviewCategory
  severity: FindingSeverity
  title: string
  explanation: string
  evidence: string | null
  source_location: string | null
  recommendation: string | null
  status: FindingStatus
  created_at: string
  updated_at: string
}

export type FindingPage = {
  items: Finding[]
  next_offset: number | null
}

export type Remediation = {
  id: string
  project_id: string
  finding_id: string
  proposed_diff: string
  pull_request: PullRequestSummary | null
  status: "proposed" | "rejected" | "applied"
  approved_at: string | null
  created_at: string
  updated_at: string
  generation_status: "pending" | "running" | "ready" | "failed" | "legacy_unverified"
  generation_failure: { code: string; message: string } | null
  patch_available: boolean
  preview_is_redacted: boolean
}

export type ExecutablePatch = {
  diff: string
  sha256: string
  source_snapshot: { source_kind: string; source_identifier: string; revision: string }
  files: {
    path: string
    operation: "replace" | "create"
    original_sha256: string | null
    result_sha256: string
  }[]
  warnings: string[]
}

export type LocalRemediationApplyFile = {
  file_path: string
  backup_reference: string
  source_hash: string
  applied_hash: string
}

export type LocalRemediationApply = {
  files: LocalRemediationApplyFile[]
}

export type PullRequestSummary = {
  url: string
  number: number
  is_merged: boolean
}

export type RemediationPrompt = {
  prompt_text: string
}

export type NotificationCategory = "info" | "security" | "warning"

export type Notification = {
  id: string
  category: NotificationCategory
  event_type: string
  title: string
  body: string
  action_path: string | null
  data: Record<string, unknown>
  created_at: string
  read_at: string | null
}

export type NotificationPage = {
  items: Notification[]
  next_offset: number | null
  unread_count: number
}

export class ApiError extends Error {
  readonly code: string
  readonly requestId?: string
  readonly status: number
  readonly retryAfterSeconds?: number

  constructor(
    status: number,
    payload: ApiErrorPayload,
    retryAfterSeconds?: number,
  ) {
    super(payload.error?.message ?? "Unable to complete the request.")
    this.code = payload.error?.code ?? "request_failed"
    this.requestId = payload.error?.request_id
    this.status = status
    this.retryAfterSeconds = retryAfterSeconds
  }
}

const csrfFreePaths = new Set([
  "/auth/login",
  "/auth/register",
  "/auth/verify-email",
  "/auth/password-recovery",
  "/auth/password-recovery/confirm",
  "/auth/oauth/desktop/exchange",
])

async function csrfToken(path: string): Promise<string | undefined> {
  if (isTauri()) {
    return getDesktopCsrfToken() ?? undefined
  }

  const apiHost = new URL(runtimeConfig.apiBaseUrl).hostname
  let cookieToken: string | undefined
  if (apiHost === window.location.hostname) {
    cookieToken = document.cookie
      .split("; ")
      .find((entry) => entry.startsWith("trace_csrf="))
      ?.split("=", 2)[1]
  }

  if (cookieToken) {
    return decodeURIComponent(cookieToken)
  }
  if (csrfFreePaths.has(path)) {
    return undefined
  }

  try {
    const response = await request<{ csrf_token: string }>("/auth/csrf")
    return response.csrf_token
  } catch (error) {
    if (path === "/auth/logout" && isUnauthenticated(error)) {
      return undefined
    }
    throw error
  }
}

type RequestOptions = {
  requiresCsrf?: boolean
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers(init.headers)

  if (init.body) {
    headers.set("Content-Type", "application/json")
  }

  if (
    options.requiresCsrf ||
    (init.method && !["GET", "HEAD"].includes(init.method))
  ) {
    const csrf = await csrfToken(path)

    if (csrf) {
      headers.set("X-CSRF-Token", csrf)
    }
  }

  const response = await fetch(`${runtimeConfig.apiBaseUrl}${path}`, {
    ...init,
    credentials: "include",
    headers,
  })

  if (response.status === 204) {
    return undefined as T
  }

  const payload = (await response.json().catch(() => ({}))) as ApiErrorPayload

  if (!response.ok) {
    const retryAfter = Number(response.headers.get("Retry-After"))
    const error = new ApiError(
      response.status,
      payload,
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
    )
    void desktopTelemetry.record({
      event: "api.request.failed",
      serverRequestId: error.requestId,
      errorCode: error.code,
      httpStatus: error.status,
    })
    throw error
  }

  return payload as T
}

function post<T>(path: string, body?: unknown) {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

function patch<T>(path: string, body: unknown) {
  return request<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
}

function remove(path: string) {
  return request<void>(path, { method: "DELETE" })
}

function pageQuery(
  values: Record<string, string | number | boolean | undefined>,
) {
  const query = new URLSearchParams()

  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined) {
      query.set(key, String(value))
    }
  })

  return query.toString()
}

type AuthenticatedResponse = {
  message: string
  csrf_token: string
}

function rememberDesktopCsrf(response: AuthenticatedResponse) {
  if (isTauri()) {
    setDesktopCsrfToken(response.csrf_token)
  }

  return response
}

export const authApi = {
  session: () => request<Session>("/auth/session"),
  updateAutomaticPullRequests: (automaticPullRequests: boolean) =>
    patch<{ automatic_pull_requests: boolean }>("/auth/session", {
      automatic_pull_requests: automaticPullRequests,
    }),
  refresh: async () =>
    rememberDesktopCsrf(await post<AuthenticatedResponse>("/auth/refresh")),
  login: async (email: string, password: string) =>
    rememberDesktopCsrf(
      await post<AuthenticatedResponse>("/auth/login", { email, password }),
    ),
  register: (email: string, password: string) =>
    post<{ message: string }>("/auth/register", {
      email,
      password,
      return_to: window.location.origin,
    }),
  verifyEmail: (token: string) =>
    post<{ message: string }>("/auth/verify-email", { token }),
  recoverPassword: (email: string) =>
    post<{ message: string }>("/auth/password-recovery", {
      email,
      return_to: window.location.origin,
    }),
  resetPassword: (token: string, password: string) =>
    post<{ message: string }>("/auth/password-recovery/confirm", {
      token,
      password,
    }),
  logout: async () => {
    try {
      return await post<void>("/auth/logout")
    } finally {
      if (isTauri()) {
        clearDesktopCsrfToken()
      }
    }
  },
  githubConnection: () =>
    request<GitHubConnection>("/auth/oauth/github/connection"),
  beginGitHubConnection: () =>
    post<{ authorization_url: string }>("/auth/oauth/github/connect/start"),
  beginLinearConnection: () =>
    post<{ authorization_url: string }>("/auth/oauth/linear/connect/start"),
  oauthUrl: (provider: "github" | "google") =>
    `${runtimeConfig.apiBaseUrl}/auth/oauth/${provider}/start?return_to=${encodeURIComponent(
      window.location.origin,
    )}`,
  desktopOAuthUrl: (provider: "github" | "google", challenge: string) =>
    `${runtimeConfig.apiBaseUrl}/auth/oauth/${provider}/desktop/start?challenge=${encodeURIComponent(
      challenge,
    )}`,
  exchangeDesktopOAuth: async (code: string, verifier: string) =>
    rememberDesktopCsrf(
      await post<AuthenticatedResponse>("/auth/oauth/desktop/exchange", {
        code,
        verifier,
      }),
    ),
}

export const projectsApi = {
  list: ({ page, pageSize }: { page: number; pageSize: number }) =>
    request<ProjectPage>(
      `/api/v1/projects?${pageQuery({ page, page_size: pageSize })}`,
    ),
  get: (projectId: string) =>
    request<Project>(`/api/v1/projects/${encodeURIComponent(projectId)}`),
  create: (project: ProjectCreate) =>
    post<Project>("/api/v1/projects", project),
  issueTracking: (projectId: string) =>
    request<IssueTrackingDetails>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/issue-tracking`,
    ),
  updateIssueTracking: (
    projectId: string,
    details: IssueTrackingDetails,
  ) =>
    patch<IssueTrackingDetails>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/issue-tracking`,
      details,
    ),
}

export const agentsApi = {
  list: ({
    page,
    pageSize,
    includeDisabled,
  }: {
    page: number
    pageSize: number
    includeDisabled: boolean
  }) =>
    request<AgentPage>(
      `/api/v1/agents?${pageQuery({
        page,
        page_size: pageSize,
        include_disabled: includeDisabled,
      })}`,
    ),
  get: (agentId: string) =>
    request<Agent>(`/api/v1/agents/${encodeURIComponent(agentId)}`),
  catalog: () => request<AgentModelCatalog>("/api/v1/agents/catalog"),
  create: (agent: AgentCreate) => post<Agent>("/api/v1/agents", agent),
  update: (agentId: string, agent: AgentUpdate) =>
    patch<Agent>(`/api/v1/agents/${encodeURIComponent(agentId)}`, agent),
  disable: (agentId: string) =>
    remove(`/api/v1/agents/${encodeURIComponent(agentId)}`),
}

export const reviewsApi = {
  list: ({
    projectId,
    page,
    pageSize,
  }: {
    projectId: string
    page: number
    pageSize: number
  }) =>
    request<ReviewPage>(
      `/api/v1/reviews?${pageQuery({
        project_id: projectId,
        page,
        page_size: pageSize,
      })}`,
    ),
  create: (review: ReviewCreate, idempotencyKey: string) =>
    request<Review>("/api/v1/reviews", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(review),
    }),
  get: (reviewId: string) =>
    request<Review>(`/api/v1/reviews/${encodeURIComponent(reviewId)}`),
}

export const findingsApi = {
  list: ({
    reviewId,
    page,
    pageSize,
    category,
    severity,
    status,
    excludeStatus,
    agentId,
  }: {
    reviewId: string
    page: number
    pageSize: number
    category?: ReviewCategory
    severity?: FindingSeverity
    status?: FindingStatus
    excludeStatus?: FindingStatus
    agentId?: string
  }) =>
    request<FindingPage>(
      `/api/v1/reviews/${encodeURIComponent(reviewId)}/findings?${pageQuery({
        page,
        page_size: pageSize,
        category,
        severity,
        status,
        exclude_status: excludeStatus,
        agent_id: agentId,
      })}`,
    ),
  get: (findingId: string) =>
    request<Finding>(`/api/v1/findings/${encodeURIComponent(findingId)}`),
  updateStatus: (findingId: string, status: FindingStatus) =>
    patch<Finding>(`/api/v1/findings/${encodeURIComponent(findingId)}`, {
      status,
    }),
  previewIssue: (findingId: string, provider: IssueProviderName) =>
    post<IssuePreview>(
      `/api/v1/findings/${encodeURIComponent(findingId)}/issue-links/preview`,
      { provider },
    ),
  listIssueLinks: (findingId: string) =>
    request<IssueLink[]>(
      `/api/v1/findings/${encodeURIComponent(findingId)}/issue-links`,
    ),
}

export const issueTrackingApi = {
  listLinearTeams: () => request<LinearTeam[]>("/api/v1/issue-tracking/linear/teams"),
  listLinearProjects: (teamId: string) =>
    request<LinearProject[]>(
      `/api/v1/issue-tracking/linear/teams/${encodeURIComponent(teamId)}/projects`,
    ),
}

export const remediationsApi = {
  getPatch: (remediationId: string) =>
    request<ExecutablePatch>(
      `/api/v1/remediations/${encodeURIComponent(remediationId)}/patch`,
      { cache: "no-store" },
    ),
  listForFinding: (findingId: string) =>
    request<Remediation[]>(
      `/api/v1/findings/${encodeURIComponent(findingId)}/remediations`,
    ),
  getPrompt: (remediationId: string) =>
    request<RemediationPrompt>(
      `/api/v1/remediations/${encodeURIComponent(remediationId)}/prompt`,
      { method: "GET" },
      { requiresCsrf: true },
    ),
  createPullRequest: (remediationId: string) =>
    post<Remediation>(
      `/api/v1/remediations/${encodeURIComponent(remediationId)}/pull-request`,
      undefined,
    ),
  completeLocalApply: (
    remediationId: string,
    operation: LocalRemediationApply,
  ) =>
    post<Remediation>(
      `/api/v1/remediations/${encodeURIComponent(remediationId)}/apply-local`,
      operation,
    ),
  createIssue: (remediationId: string, provider: IssueProviderName) =>
    post<IssueLink>(
      `/api/v1/remediations/${encodeURIComponent(remediationId)}/issue`,
      { destination: { provider } },
    ),
}

export const notificationsApi = {
  list: ({ page, pageSize }: { page: number; pageSize: number }) =>
    request<NotificationPage>(
      `/api/v1/notifications?${pageQuery({ page, page_size: pageSize })}`,
    ),
  markRead: (notificationId: string) =>
    patch<{ item: Notification; changed: boolean }>(
      `/api/v1/notifications/${encodeURIComponent(notificationId)}/read`,
      {},
    ),
  markAllRead: () =>
    patch<{ marked_count: number; read_at: string | null }>(
      "/api/v1/notifications/read",
      {},
    ),
  streamUrl: () => `${runtimeConfig.apiBaseUrl}/api/v1/notifications/stream`,
}

export const credentialsApi = {
  list: ({ page, pageSize }: { page: number; pageSize: number }) =>
    request<CredentialPage>(
      `/api/v1/credentials?${pageQuery({ page, page_size: pageSize })}`,
    ),
  create: (credential: CredentialCreate) =>
    post<Credential>("/api/v1/credentials", credential),
  rotate: (credentialId: string, credential: CredentialCreate) =>
    post<Credential>(
      `/api/v1/credentials/${encodeURIComponent(credentialId)}/rotate`,
      credential,
    ),
  revoke: (credentialId: string) =>
    remove(`/api/v1/credentials/${encodeURIComponent(credentialId)}`),
}

export const repositoriesApi = {
  list: ({ page, query }: { page: number; query?: string }) =>
    request<RepositoryPage>(
      `/api/v1/repositories?${pageQuery({
        source: "github",
        page,
        page_size: 5,
        query,
      })}`,
    ),
  listBranches: ({
    repositoryId,
    page,
    query,
  }: {
    repositoryId: string
    page: number
    query?: string
  }) =>
    request<BranchPage>(
      `/api/v1/repositories/${encodeURIComponent(repositoryId)}/branches?${pageQuery(
        {
          source: "github",
          page,
          page_size: 5,
          query,
        },
      )}`,
    ),
}

export function isUnauthenticated(error: unknown) {
  return error instanceof ApiError && error.status === 401
}
