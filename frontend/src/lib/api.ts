export type Session = { user_id: string; session_id: string }
type ApiErrorPayload = { error?: { code?: string; message?: string; request_id?: string } }

export class ApiError extends Error {
  readonly code: string
  readonly requestId?: string
  readonly status: number
  constructor(status: number, payload: ApiErrorPayload) { super(payload.error?.message ?? 'Unable to complete the request.'); this.code = payload.error?.code ?? 'request_failed'; this.requestId = payload.error?.request_id; this.status = status }
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
function csrfToken() { return document.cookie.split('; ').find((entry) => entry.startsWith('trace_csrf='))?.split('=', 2)[1] }
async function request<T>(path: string, init: RequestInit = {}): Promise<T> { const headers = new Headers(init.headers); if (init.body) headers.set('Content-Type', 'application/json'); if (init.method && !['GET', 'HEAD'].includes(init.method)) { const csrf = csrfToken(); if (csrf) headers.set('X-CSRF-Token', decodeURIComponent(csrf)) }; const response = await fetch(`${apiBaseUrl}${path}`, { ...init, credentials: 'include', headers }); if (response.status === 204) return undefined as T; const payload = await response.json().catch(() => ({})) as ApiErrorPayload; if (!response.ok) throw new ApiError(response.status, payload); return payload as T }
function post<T>(path: string, body?: unknown) { return request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }) }
export const authApi = { session: () => request<Session>('/auth/session'), refresh: () => post<{ message: string }>('/auth/refresh'), login: (email: string, password: string) => post<{ message: string }>('/auth/login', { email, password }), register: (email: string, password: string) => post<{ message: string }>('/auth/register', { email, password, return_to: window.location.origin }), verifyEmail: (token: string) => post<{ message: string }>('/auth/verify-email', { token }), recoverPassword: (email: string) => post<{ message: string }>('/auth/password-recovery', { email, return_to: window.location.origin }), resetPassword: (token: string, password: string) => post<{ message: string }>('/auth/password-recovery/confirm', { token, password }), logout: () => post<void>('/auth/logout'), oauthUrl: (provider: 'github' | 'google') => `${apiBaseUrl}/auth/oauth/${provider}/start?return_to=${encodeURIComponent(window.location.origin)}` }
export function isUnauthenticated(error: unknown) { return error instanceof ApiError && error.status === 401 }
