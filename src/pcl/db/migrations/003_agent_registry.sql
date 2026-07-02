PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL,
  adapter TEXT NOT NULL CHECK(adapter IN ('manual', 'codex_exec', 'claude_manual', 'generic_shell')),
  max_concurrency INTEGER NOT NULL DEFAULT 1 CHECK(max_concurrency >= 1),
  status TEXT NOT NULL CHECK(status IN ('active', 'paused', 'retired')),
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

ALTER TABLE agent_jobs ADD COLUMN assigned_agent_id TEXT REFERENCES agents(id);
ALTER TABLE agent_jobs ADD COLUMN lease_expires_at TEXT;
ALTER TABLE agent_jobs ADD COLUMN last_heartbeat_at TEXT;
ALTER TABLE agent_jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_assigned_agent_status ON agent_jobs(assigned_agent_id, status);
