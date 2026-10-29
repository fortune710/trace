CREATE TABLE local_review_sessions (
  review_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  local_project_id TEXT NOT NULL,
  snapshot_id TEXT NOT NULL UNIQUE,
  snapshot_digest TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'completed', 'failed')),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX local_review_sessions_account_status_idx
  ON local_review_sessions (account_id, status, expires_at);

CREATE TABLE local_remediation_operations (
  remediation_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  local_project_id TEXT NOT NULL,
  file_path TEXT NOT NULL,
  backup_reference TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  applied_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending_confirmation', 'applied', 'reverted')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX local_remediation_operations_account_status_idx
  ON local_remediation_operations (account_id, status, updated_at DESC);
