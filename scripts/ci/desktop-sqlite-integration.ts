import assert from "node:assert/strict"
import { mkdtemp, rm } from "node:fs/promises"
import os from "node:os"
import path from "node:path"

import { Database } from "bun:sqlite"

const temporaryDirectory = await mkdtemp(path.join(os.tmpdir(), "trace-desktop-sqlite-"))
const database = new Database(path.join(temporaryDirectory, "trace.db"))

try {
  const migrationFiles = [
    "../../frontend/src-tauri/migrations/001_desktop_projects.sql",
    "../../frontend/src-tauri/migrations/002_local_project_uniqueness.sql",
  ]

  for (const migrationFile of migrationFiles) {
    const migrationUrl = new URL(migrationFile, import.meta.url)
    database.exec(await Bun.file(migrationUrl).text())
  }

  function count(table: "local_sources" | "desktop_projects", accountId: string) {
    const row = database
      .query(`SELECT COUNT(*) AS count FROM ${table} WHERE account_id = ?1`)
      .get(accountId) as { count: number }

    return row.count
  }

  database.exec(`
    INSERT INTO local_sources
      (account_id, source_id, display_name, canonical_path, availability, last_validated_at, created_at, updated_at)
    VALUES ('account-a', 'source-a', 'Trace project', '/tmp/trace-project', 'available', NULL, 'now', 'now');

    INSERT INTO desktop_projects
      (id, account_id, persistence, name, category, source_kind, local_source_id,
       created_at, updated_at, api_cache_status, local_canonical_path)
    VALUES ('local:a', 'account-a', 'local', 'Trace project', 'productivity', 'local', 'source-a',
            'now', 'now', 'not_applicable', '/tmp/trace-project');
  `)

  assert.equal(count("local_sources", "account-a"), 1)
  assert.equal(count("desktop_projects", "account-a"), 1)
  assert.equal(count("local_sources", "account-b"), 0)
  assert.equal(count("desktop_projects", "account-b"), 0)

  database.exec(`
    INSERT INTO desktop_projects
      (id, account_id, persistence, name, category, source_kind, api_project_id,
       created_at, updated_at, api_cache_status)
    VALUES ('api:a', 'account-a', 'api_cache', 'API project', 'productivity', 'github', 'remote-a',
            'now', 'now', 'fresh');
  `)

  database.exec("BEGIN IMMEDIATE")
  database.exec("DELETE FROM desktop_projects WHERE account_id = 'account-a' AND persistence = 'api_cache'")
  database.exec(`
    INSERT INTO desktop_projects
      (id, account_id, persistence, name, category, source_kind, api_project_id,
       created_at, updated_at, api_cache_status)
    VALUES ('api:b', 'account-a', 'api_cache', 'Refreshed API project', 'productivity', 'github', 'remote-b',
            'now', 'now', 'fresh');
  `)
  database.exec("COMMIT")

  assert.equal(count("desktop_projects", "account-a"), 2)
  assert.equal(
    database
      .query("SELECT COUNT(*) AS count FROM desktop_projects WHERE account_id = 'account-a' AND persistence = 'local'")
      .get()?.count,
    1,
  )

  let duplicateRejected = false
  try {
    database
      .query(`
        INSERT INTO desktop_projects
          (id, account_id, persistence, name, category, source_kind, local_source_id,
           created_at, updated_at, api_cache_status, local_canonical_path)
        VALUES ('local:duplicate', 'account-a', 'local', 'Duplicate', 'productivity', 'local', 'source-a',
                'now', 'now', 'not_applicable', '/tmp/trace-project');
      `)
      .run()
  } catch (error) {
    duplicateRejected = /UNIQUE/i.test(String(error))
  }
  assert.equal(duplicateRejected, true)

  database.exec("BEGIN IMMEDIATE")
  database.exec(`
    INSERT INTO local_sources
      (account_id, source_id, display_name, canonical_path, availability, last_validated_at, created_at, updated_at)
    VALUES ('account-a', 'source-rollback', 'Rollback project', '/tmp/rollback', 'available', NULL, 'now', 'now');

    INSERT INTO desktop_projects
      (id, account_id, persistence, name, category, source_kind, local_source_id,
       created_at, updated_at, api_cache_status, local_canonical_path)
    VALUES ('local:rollback', 'account-a', 'local', 'Rollback project', 'productivity', 'local', 'source-rollback',
            'now', 'now', 'not_applicable', '/tmp/rollback');
  `)
  database.exec("ROLLBACK")

  assert.equal(count("local_sources", "account-a"), 1)
  assert.equal(count("desktop_projects", "account-a"), 2)
  console.log("desktop SQLite integration checks passed")
} finally {
  database.close()
  await rm(temporaryDirectory, { recursive: true, force: true })
}
