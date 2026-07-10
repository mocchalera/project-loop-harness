ALTER TABLE events RENAME TO events_pre_outbox_008;

CREATE TABLE events (
  id TEXT PRIMARY KEY,
  sequence INTEGER NOT NULL UNIQUE CHECK(sequence > 0),
  event_type TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

INSERT INTO events(id, sequence, event_type, entity_type, entity_id, payload_json, created_at)
SELECT
  source.id,
  (SELECT COUNT(*) FROM events_pre_outbox_008 AS preceding WHERE preceding.rowid <= source.rowid),
  source.event_type,
  source.entity_type,
  source.entity_id,
  source.payload_json,
  source.created_at
FROM events_pre_outbox_008 AS source
ORDER BY source.rowid;

DROP TABLE events_pre_outbox_008;

CREATE INDEX idx_events_entity ON events(entity_type, entity_id);

CREATE TABLE outbox_records (
  id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  sink TEXT NOT NULL CHECK(sink IN ('jsonl')),
  idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN (
    'pending', 'retry_wait', 'delivered', 'failed_needs_review'
  )),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
  next_attempt_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  delivered_at TEXT,
  UNIQUE(event_id, sink)
);

CREATE INDEX idx_outbox_delivery
  ON outbox_records(sink, status, next_attempt_at, event_id);
