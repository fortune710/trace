import { invoke, isTauri } from "@tauri-apps/api/core"

type SqlDatabase = {
  execute(query: string, bindValues?: unknown[]): Promise<{ rowsAffected: number }>
}

type DesktopPlatform = {
  operatingSystem: string
  architecture: string
}

type DesktopTelemetryDependencies = {
  isDesktop: () => boolean
  loadDatabase: () => Promise<SqlDatabase>
  platform: () => Promise<DesktopPlatform>
  compress: (payload: string) => Promise<string>
  now: () => string
  createRequestId: () => string
}

export type DesktopTelemetryEvent =
  | "api.request.failed"
  | "local_remediation.apply.started"
  | "local_remediation.apply.succeeded"
  | "local_remediation.apply.failed"
  | "local_remediation.record.succeeded"
  | "local_remediation.record.failed"
  | "local_remediation.restore.succeeded"
  | "local_remediation.restore.failed"

export type DesktopTelemetryEntry = {
  event: DesktopTelemetryEvent
  userId?: string
  requestId?: string
  serverRequestId?: string
  errorCode?: string
  httpStatus?: number
}

const databasePath = "sqlite:trace.db"

async function loadDatabase(): Promise<SqlDatabase> {
  const { default: Database } = await import("@tauri-apps/plugin-sql")
  const database = await Database.load(databasePath)
  await database.execute("PRAGMA busy_timeout = 5000")
  return database
}

async function platform(): Promise<DesktopPlatform> {
  return invoke<DesktopPlatform>("desktop_telemetry_platform")
}

async function compress(payload: string): Promise<string> {
  return invoke<string>("compress_desktop_telemetry", { json: payload })
}

function requestId() {
  return crypto.randomUUID()
}

export function createDesktopTelemetry(
  dependencies: DesktopTelemetryDependencies,
) {
  let databasePromise: Promise<SqlDatabase> | undefined
  let platformPromise: Promise<DesktopPlatform> | undefined
  let writeQueue = Promise.resolve()

  async function write(entry: DesktopTelemetryEntry) {
    if (!dependencies.isDesktop()) return

    const [database, operatingSystem] = await Promise.all([
      databasePromise ??= dependencies.loadDatabase(),
      platformPromise ??= dependencies.platform(),
    ])
    const payload = JSON.stringify({
      event: entry.event,
      occurred_at: dependencies.now(),
      operating_system: operatingSystem.operatingSystem,
      architecture: operatingSystem.architecture,
      user_id: entry.userId ?? null,
      request_id: entry.requestId ?? dependencies.createRequestId(),
      server_request_id: entry.serverRequestId ?? null,
      error_code: entry.errorCode ?? null,
      http_status: entry.httpStatus ?? null,
    })
    const logData = await dependencies.compress(payload)

    await database.execute(
      "INSERT INTO desktop_telemetry (log_data) VALUES ($1)",
      [logData],
    )
  }

  return {
    record(entry: DesktopTelemetryEntry) {
      writeQueue = writeQueue
        .catch(() => undefined)
        .then(() => write(entry))
        .catch(() => undefined)
      return writeQueue
    },
  }
}

export const desktopTelemetry = createDesktopTelemetry({
  isDesktop: isTauri,
  loadDatabase,
  platform,
  compress,
  now: () => new Date().toISOString(),
  createRequestId: requestId,
})
