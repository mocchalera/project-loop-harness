PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  checksum TEXT NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  sequence INTEGER NOT NULL UNIQUE CHECK(sequence > 0),
  event_type TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox_records (
  id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  sink TEXT NOT NULL CHECK(sink IN ('jsonl')),
  idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN ('pending', 'retry_wait', 'delivered', 'failed_needs_review')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
  next_attempt_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  delivered_at TEXT,
  UNIQUE(event_id, sink)
);

CREATE TABLE IF NOT EXISTS goals (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('open', 'active', 'blocked', 'closed', 'cancelled')),
  completion_json TEXT NOT NULL DEFAULT '{}',
  stop_conditions_json TEXT NOT NULL DEFAULT '{}',
  budget_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflows (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  template_path TEXT,
  version TEXT NOT NULL DEFAULT '0.1.0',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_runs (
  id TEXT PRIMARY KEY,
  goal_id TEXT,
  workflow_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'blocked', 'failed', 'passed', 'cancelled')),
  iteration INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  summary TEXT,
  FOREIGN KEY(goal_id) REFERENCES goals(id)
);

CREATE TABLE IF NOT EXISTS agent_jobs (
  id TEXT PRIMARY KEY,
  workflow_run_id TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'blocked', 'failed', 'passed', 'cancelled')),
  worktree_path TEXT,
  prompt_path TEXT,
  output_path TEXT,
  token_input INTEGER,
  token_output INTEGER,
  started_at TEXT,
  ended_at TEXT,
  summary TEXT,
  FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs(id)
);

CREATE TABLE IF NOT EXISTS features (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  surface TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL CHECK(status IN ('discovered', 'specified', 'needs_test', 'needs_fix', 'passing', 'done', 'waived')),
  confidence TEXT NOT NULL CHECK(confidence IN ('low', 'medium', 'high')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_stories (
  id TEXT PRIMARY KEY,
  feature_id TEXT NOT NULL,
  actor TEXT NOT NULL,
  goal TEXT NOT NULL,
  benefit TEXT,
  expected_behavior TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('draft', 'review', 'approved', 'waived')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(feature_id) REFERENCES features(id)
);

CREATE TABLE IF NOT EXISTS test_cases (
  id TEXT PRIMARY KEY,
  feature_id TEXT NOT NULL,
  story_id TEXT,
  type TEXT NOT NULL,
  scenario TEXT NOT NULL,
  expected TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('planned', 'missing', 'passing', 'failing', 'blocked', 'waived')),
  last_run_id TEXT,
  evidence_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(feature_id) REFERENCES features(id),
  FOREIGN KEY(story_id) REFERENCES user_stories(id),
  FOREIGN KEY(last_run_id) REFERENCES workflow_runs(id)
);

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  path TEXT NOT NULL,
  command TEXT,
  summary TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS defects (
  id TEXT PRIMARY KEY,
  feature_id TEXT NOT NULL,
  test_case_id TEXT,
  severity TEXT NOT NULL CHECK(severity IN ('critical', 'high', 'medium', 'low')),
  expected TEXT NOT NULL,
  actual TEXT NOT NULL,
  reproduction TEXT,
  status TEXT NOT NULL CHECK(status IN ('open', 'triaged', 'in_progress', 'fixed', 'verified', 'closed', 'waived')),
  evidence_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(feature_id) REFERENCES features(id),
  FOREIGN KEY(test_case_id) REFERENCES test_cases(id),
  FOREIGN KEY(evidence_id) REFERENCES evidence(id)
);

CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN ('open', 'resolved', 'waived')),
  question TEXT NOT NULL,
  recommendation TEXT,
  selected_option TEXT,
  reason TEXT,
  blocks_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS verifications (
  id TEXT PRIMARY KEY,
  workflow_run_id TEXT NOT NULL,
  target_job_id TEXT,
  verifier_role TEXT NOT NULL,
  rubric_json TEXT NOT NULL,
  result TEXT NOT NULL CHECK(result IN ('approved', 'rejected', 'needs_human', 'inconclusive')),
  reasons_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs(id),
  FOREIGN KEY(target_job_id) REFERENCES agent_jobs(id)
);

CREATE TABLE IF NOT EXISTS escalations (
  id TEXT PRIMARY KEY,
  workflow_run_id TEXT,
  severity TEXT NOT NULL CHECK(severity IN ('critical', 'high', 'medium', 'low')),
  question TEXT NOT NULL,
  recommendation TEXT,
  status TEXT NOT NULL CHECK(status IN ('open', 'resolved', 'cancelled')),
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_outbox_delivery
  ON outbox_records(sink, status, next_attempt_at, event_id);
CREATE INDEX IF NOT EXISTS idx_defects_status ON defects(status, severity);
CREATE INDEX IF NOT EXISTS idx_features_status ON features(status);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_goal ON workflow_runs(goal_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_run ON agent_jobs(workflow_run_id, status);
