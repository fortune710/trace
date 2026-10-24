PRAGMA foreign_keys = OFF;

CREATE TABLE desktop_projects_next (
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
  local_canonical_path TEXT,
  FOREIGN KEY (account_id, local_source_id)
    REFERENCES local_sources (account_id, source_id)
    ON DELETE CASCADE,
  CHECK (
    (persistence = 'local'
      AND source_kind = 'local'
      AND local_source_id IS NOT NULL
      AND api_cache_status = 'not_applicable')
    OR
    (persistence = 'api_cache'
      AND source_kind = 'github'
      AND local_source_id IS NULL
      AND api_project_id IS NOT NULL
      AND api_cache_status IN ('fresh', 'stale', 'unavailable'))
  )
);

INSERT INTO desktop_projects_next
SELECT * FROM desktop_projects;

DROP TABLE desktop_projects;
ALTER TABLE desktop_projects_next RENAME TO desktop_projects;

CREATE UNIQUE INDEX desktop_projects_api_project_key
  ON desktop_projects (account_id, api_project_id)
  WHERE api_project_id IS NOT NULL;

CREATE INDEX desktop_projects_account_created_idx
  ON desktop_projects (account_id, created_at DESC, id DESC);

CREATE UNIQUE INDEX desktop_projects_local_path_key
  ON desktop_projects (account_id, local_canonical_path)
  WHERE persistence = 'local' AND local_canonical_path IS NOT NULL;

PRAGMA foreign_keys = ON;
