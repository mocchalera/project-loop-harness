PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS code_index_runs (
  id TEXT PRIMARY KEY,
  root_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  git_head TEXT,
  file_count INTEGER NOT NULL,
  indexed_bytes INTEGER NOT NULL,
  ignored_count INTEGER NOT NULL,
  index_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('built', 'failed')),
  summary_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS code_index_files (
  id TEXT PRIMARY KEY,
  index_run_id TEXT NOT NULL,
  path TEXT NOT NULL,
  language TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  mtime INTEGER NOT NULL,
  sha256 TEXT,
  line_count INTEGER NOT NULL,
  symbol_summary_json TEXT NOT NULL,
  test_hint_json TEXT NOT NULL,
  FOREIGN KEY(index_run_id) REFERENCES code_index_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_code_index_files_run_path ON code_index_files(index_run_id, path);
