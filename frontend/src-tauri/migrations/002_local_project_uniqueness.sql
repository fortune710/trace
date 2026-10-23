ALTER TABLE desktop_projects ADD COLUMN local_canonical_path TEXT;

UPDATE desktop_projects
SET local_canonical_path = (
  SELECT canonical_path
  FROM local_sources
  WHERE local_sources.account_id = desktop_projects.account_id
    AND local_sources.source_id = desktop_projects.local_source_id
)
WHERE persistence = 'local';

CREATE UNIQUE INDEX IF NOT EXISTS desktop_projects_local_path_key
  ON desktop_projects (account_id, local_canonical_path)
  WHERE persistence = 'local' AND local_canonical_path IS NOT NULL;
