PRAGMA foreign_keys = ON;

ALTER TABLE evidence ADD COLUMN linked_task_id TEXT REFERENCES tasks(id);

CREATE INDEX IF NOT EXISTS idx_evidence_linked_task ON evidence(linked_task_id, created_at, id);
