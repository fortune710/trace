import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi, isUnauthenticated, type Session } from '@/lib/api'
export const sessionQueryKey = ['auth', 'session'] as const
let refreshInFlight: Promise<void> | undefined
function refreshOnce() { if (!document.cookie.includes('trace_csrf=')) return Promise.reject(new Error('No active session')); refreshInFlight ??= authApi.refresh().then(() => undefined).finally(() => { refreshInFlight = undefined }); return refreshInFlight }
async function loadSession(): Promise<Session | null> { try { return await authApi.session() } catch (error) { if (!isUnauthenticated(error)) throw error } try { await refreshOnce(); return await authApi.session() } catch { return null } }
export function useSession() { return useQuery({ queryKey: sessionQueryKey, queryFn: loadSession, staleTime: 0, gcTime: 0, retry: false }) }
export function useLogout() { const queryClient = useQueryClient(); return useMutation({ mutationFn: authApi.logout, retry: false, onSettled: () => queryClient.setQueryData(sessionQueryKey, null) }) }
