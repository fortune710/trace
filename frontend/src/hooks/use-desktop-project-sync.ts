import { useQuery } from "@tanstack/react-query"

import { DesktopApiProjectSynchronizer } from "@/lib/desktop-project-sync"
import { getLocalProjectsDatabase } from "@/lib/local-projects-database"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { useSession } from "@/hooks/use-session"

export const desktopProjectSyncQueryKey = ["desktop-project-sync"] as const
const inFlightSyncs = new Map<string, ReturnType<DesktopApiProjectSynchronizer["sync"]>>()

function syncAccount(accountId: string) {
  const current = inFlightSyncs.get(accountId)
  if (current) return current

  const sync = getLocalProjectsDatabase()
    .then((database) => new DesktopApiProjectSynchronizer(database).sync(accountId))
    .finally(() => {
      inFlightSyncs.delete(accountId)
    })
  inFlightSyncs.set(accountId, sync)
  return sync
}

export function useDesktopProjectSync() {
  const runtime = useRuntimeEnvironment()
  const session = useSession()
  const accountId = session.data?.user_id
  const query = useQuery({
    queryKey: [...desktopProjectSyncQueryKey, accountId],
    queryFn: () => syncAccount(accountId!),
    enabled: runtime.isTauri && Boolean(accountId),
    staleTime: Infinity,
    retry: false,
  })

  const syncNow = () => query.refetch().then((result) => result.data)

  return {
    ...query,
    accountId,
    isReady: !runtime.isTauri || query.isSuccess,
    isSyncing: query.isFetching,
    error: query.data?.error ?? query.error ?? null,
    syncNow,
  }
}
