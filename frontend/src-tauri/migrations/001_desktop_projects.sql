PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS local_sources (
  account_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  canonical_path TEXT NOT NULL,
  availability TEXT NOT NULL CHECK (availability IN ('available', 'missing', 'unreadable', 'permission_denied')),
  last_validated_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (account_id, source_id)
);

CREATE TABLE IF NOT EXISTS desktop_projects (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  persistence TEXT NOT NULL CHECK (persistence IN ('local', 'api_cache')),
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  source_kind TEXT NOT NULL CHECK (source_kind IN ('local', 'github')),
  local_source_id TEXT,
  api_project_id TEXT,
  repository_owner TEXT,
  repository_name TEXT,
  branch_name TEXT,
  current_revision TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  api_last_fetched_at TEXT,
  api_cache_status TEXT NOT NULL CHECK (api_cache_status IN ('not_applicable', 'fresh', 'stale', 'unavailable')),
  FOREIGN KEY (account_id, local_source_id)
    REFERENCES local_sources (account_id, source_id)
    ON DELETE CASCADE,
  CHECK (
    (persistence = 'local'
      AND source_kind = 'local'
      AND local_source_id IS NOT NULL
      AND api_project_id IS NULL
      AND api_cache_status = 'not_applicable')
    OR
    (persistence = 'api_cache'
      AND source_kind = 'github'
      AND local_source_id IS NULL
      AND api_project_id IS NOT NULL
      AND api_cache_status IN ('fresh', 'stale', 'unavailable'))
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS desktop_projects_api_project_key
  ON desktop_projects (account_id, api_project_id)
  WHERE persistence = 'api_cache';

CREATE INDEX IF NOT EXISTS desktop_projects_account_created_idx
  ON desktop_projects (account_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS local_sources_account_idx
  ON local_sources (account_id);
