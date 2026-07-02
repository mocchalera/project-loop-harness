PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL CHECK(status IN ('todo', 'ready', 'in_progress', 'blocked', 'done', 'cancelled', 'waived')),
  priority INTEGER NOT NULL DEFAULT 100,
  owner TEXT,
  risk TEXT CHECK(risk IN ('low', 'medium', 'high')),
  effort TEXT,
  related_goal_id TEXT,
  related_feature_id TEXT,
  related_defect_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(related_goal_id) REFERENCES goals(id),
  FOREIGN KEY(related_feature_id) REFERENCES features(id),
  FOREIGN KEY(related_defect_id) REFERENCES defects(id)
);

CREATE TABLE IF NOT EXISTS task_dependencies (
  task_id TEXT NOT NULL,
  depends_on_task_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(task_id, depends_on_task_id),
  CHECK(task_id != depends_on_task_id),
  FOREIGN KEY(task_id) REFERENCES tasks(id),
  FOREIGN KEY(depends_on_task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority);
CREATE INDEX IF NOT EXISTS idx_task_dependencies_depends_on ON task_dependencies(depends_on_task_id);
