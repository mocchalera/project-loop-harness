PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS evidence_links (
  evidence_id TEXT NOT NULL REFERENCES evidence(id),
  target_type TEXT NOT NULL,
  target_id   TEXT NOT NULL,
  link_role   TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  PRIMARY KEY (evidence_id, target_type, target_id, link_role)
);

CREATE INDEX IF NOT EXISTS idx_evidence_links_target
  ON evidence_links(target_type, target_id, link_role, created_at);

-- Backfill existing task-linked evidence as role 'supporting'.
INSERT OR IGNORE INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
SELECT id, 'task', linked_task_id, 'supporting', created_at
FROM evidence
WHERE linked_task_id IS NOT NULL;
