CREATE TABLE IF NOT EXISTS verification_feedback (
  id TEXT PRIMARY KEY,
  suggestion_id TEXT NOT NULL,
  receipt_evidence_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('executed', 'skipped', 'not_applicable')),
  result TEXT CHECK(result IN ('passed', 'failed', 'inconclusive')),
  supporting_evidence_id TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  CHECK(
    (status = 'executed' AND result IS NOT NULL AND supporting_evidence_id IS NOT NULL)
    OR (status != 'executed' AND result IS NULL)
  ),
  FOREIGN KEY(receipt_evidence_id) REFERENCES evidence(id),
  FOREIGN KEY(supporting_evidence_id) REFERENCES evidence(id)
);
