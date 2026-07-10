from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable

from .db import connect
from .locks import jsonl_projector_lock, project_operation_lock
from .paths import ProjectPaths
from .timeutil import utc_now_iso


MAX_ATTEMPTS = 5
MAX_SYNCHRONOUS_RECORDS = 100


@dataclass(frozen=True)
class ProjectionResult:
    committed: bool
    projection: str
    delivered: int
    pending_count: int
    first_pending_sequence: int | None
    event_id: str | None = None
    event_sequence: int | None = None
    safe_next_action: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.projection == "delivered"

    def to_dict(self) -> dict[str, Any]:
        return {
            "committed": self.committed,
            "projection": self.projection,
            "delivered": self.delivered,
            "pending_count": self.pending_count,
            "first_pending_sequence": self.first_pending_sequence,
            "event_id": self.event_id,
            "event_sequence": self.event_sequence,
            "safe_next_action": self.safe_next_action,
            "error": self.error,
        }


def canonical_event_record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "created_at": str(row["created_at"]),
        "entity_id": row["entity_id"],
        "entity_type": str(row["entity_type"]),
        "event_type": str(row["event_type"]),
        "id": str(row["event_id"] if "event_id" in row.keys() else row["id"]),
        "payload": json.loads(str(row["payload_json"])),
        "sequence": int(row["sequence"]),
    }


def canonical_event_bytes(record: dict[str, Any]) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def project_pending_events(
    paths: ProjectPaths,
    *,
    operation_lock_held: bool = False,
    max_records: int = MAX_SYNCHRONOUS_RECORDS,
    fault: Callable[[str], None] | None = None,
) -> ProjectionResult:
    if operation_lock_held:
        return _project_with_jsonl_lock(paths, max_records=max_records, fault=fault)
    with project_operation_lock(paths.loop_dir, exclusive=False):
        return _project_with_jsonl_lock(paths, max_records=max_records, fault=fault)


def pending_projection_result(paths: ProjectPaths, *, error: str) -> ProjectionResult:
    pending_count, first_pending_sequence, first_status, first_error = _pending_summary(paths.db_path)
    return ProjectionResult(
        committed=True,
        projection=(
            "failed_needs_review" if first_status == "failed_needs_review" else "pending"
        ),
        delivered=0,
        pending_count=pending_count,
        first_pending_sequence=first_pending_sequence,
        safe_next_action="Run `pcl audit flush --json`; do not retry the committed mutation.",
        error=error or first_error,
    )
def _project_with_jsonl_lock(
    paths: ProjectPaths,
    *,
    max_records: int,
    fault: Callable[[str], None] | None,
) -> ProjectionResult:
    with jsonl_projector_lock(paths.loop_dir):
        delivered = 0
        last_event_id: str | None = None
        last_sequence: int | None = None
        error: str | None = None
        for _ in range(max_records):
            conn = connect(paths.db_path)
            try:
                row = _next_outbox_row(conn)
            finally:
                conn.close()
            if row is None:
                break
            last_event_id = str(row["event_id"])
            last_sequence = int(row["sequence"])
            if str(row["status"]) == "failed_needs_review":
                error = str(row["last_error"] or "Projection record requires review.")
                break
            if str(row["status"]) == "retry_wait" and not _retry_is_due(row["next_attempt_at"]):
                break
            attempt = _start_attempt(paths.db_path, str(row["outbox_id"]))
            try:
                disposition = _append_or_match(
                    paths.db_path,
                    paths.events_path,
                    row,
                    fault=fault,
                )
            except (OSError, UnicodeError) as exc:
                error = str(exc)
                _record_transient_failure(paths.db_path, str(row["outbox_id"]), attempt, error)
                break
            except ValueError as exc:
                error = str(exc)
                _mark_failed_needs_review(paths.db_path, str(row["outbox_id"]), error)
                break
            _mark_delivered(paths.db_path, str(row["outbox_id"]))
            delivered += 1
            if disposition not in {"appended", "matched"}:  # pragma: no cover - defensive
                raise AssertionError(disposition)

        pending_count, first_pending_sequence, first_status, first_error = _pending_summary(
            paths.db_path
        )
        if pending_count:
            error = error or first_error
            projection = "failed_needs_review" if first_status == "failed_needs_review" else "pending"
            next_action = "Run `pcl audit flush --json`; do not retry the committed mutation."
        else:
            projection = "delivered"
            next_action = None
        return ProjectionResult(
            committed=True,
            projection=projection,
            delivered=delivered,
            pending_count=pending_count,
            first_pending_sequence=first_pending_sequence,
            event_id=last_event_id,
            event_sequence=last_sequence,
            safe_next_action=next_action,
            error=error,
        )


def _next_outbox_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
          outbox_records.id AS outbox_id,
          outbox_records.event_id,
          outbox_records.status,
          outbox_records.attempts,
          outbox_records.next_attempt_at,
          outbox_records.last_error,
          events.sequence,
          events.event_type,
          events.entity_type,
          events.entity_id,
          events.payload_json,
          events.created_at
        FROM outbox_records
        JOIN events ON events.id = outbox_records.event_id
        WHERE outbox_records.sink = 'jsonl'
          AND outbox_records.status != 'delivered'
        ORDER BY events.sequence
        LIMIT 1
        """
    ).fetchone()


def _start_attempt(db_path: Path, outbox_id: str) -> int:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE outbox_records SET attempts = attempts + 1, updated_at = ? WHERE id = ?",
            (utc_now_iso(), outbox_id),
        )
        row = conn.execute(
            "SELECT attempts FROM outbox_records WHERE id = ?", (outbox_id,)
        ).fetchone()
        conn.commit()
        return int(row["attempts"])
    finally:
        conn.close()


def _append_or_match(
    db_path: Path,
    events_path: Path,
    row: sqlite3.Row,
    *,
    fault: Callable[[str], None] | None,
) -> str:
    expected = canonical_event_record(row)
    sequence = int(row["sequence"])
    expected_prefix = _event_prefix(db_path, sequence)
    parsed = _read_existing_lines(events_path)
    if len(parsed) > sequence:
        raise ValueError(
            f"events.jsonl contains an unknown suffix after pending sequence {sequence}."
        )
    for position, actual in enumerate(parsed, start=1):
        _assert_logical_match(actual, expected_prefix[position - 1], position)
    if len(parsed) >= sequence:
        actual = parsed[sequence - 1]
        _assert_logical_match(actual, expected, sequence)
        return "matched"
    if len(parsed) != sequence - 1:
        raise ValueError(
            f"events.jsonl has a gap before sequence {sequence}: found {len(parsed)} complete lines."
        )
    if fault is not None:
        fault("before_jsonl_append")
    events_path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_event_bytes(expected)
    with events_path.open("ab", buffering=0) as file:
        written = file.write(payload)
        if written != len(payload):
            raise OSError(f"Short events.jsonl write: expected {len(payload)} bytes, wrote {written}.")
        file.flush()
        os.fsync(file.fileno())
    if fault is not None:
        fault("after_jsonl_fsync_before_delivered_commit")
    return "appended"


def _read_existing_lines(events_path: Path) -> list[dict[str, Any]]:
    if not events_path.exists():
        return []
    raw = events_path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("events.jsonl has a partial trailing line and requires reviewed repair.")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"events.jsonl line {line_number} is blank.")
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"events.jsonl line {line_number} is malformed: {exc}.") from exc
        if not isinstance(value, dict) or not value.get("id"):
            raise ValueError(f"events.jsonl line {line_number} is an unknown event record.")
        records.append(value)
    return records


def _event_prefix(db_path: Path, sequence: int) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
            FROM events WHERE sequence <= ? ORDER BY sequence
            """,
            (sequence,),
        ).fetchall()
        if len(rows) != sequence:
            raise ValueError(
                f"SQLite event sequence is not contiguous through sequence {sequence}."
            )
        return [canonical_event_record(row) for row in rows]
    finally:
        conn.close()


def _assert_logical_match(
    actual: dict[str, Any],
    expected: dict[str, Any],
    sequence: int,
) -> None:
    actual_sequence = actual.get("sequence")
    if actual_sequence is not None and actual_sequence != sequence:
        raise ValueError(
            f"events.jsonl sequence mismatch at position {sequence}: {actual_sequence!r}."
        )
    comparable = {key: value for key, value in expected.items() if key != "sequence"}
    actual_comparable = {key: actual.get(key) for key in comparable}
    if actual_comparable != comparable:
        raise ValueError(
            f"events.jsonl event mismatch for sequence {sequence} / {expected['id']}."
        )


def _record_transient_failure(db_path: Path, outbox_id: str, attempt: int, error: str) -> None:
    now = datetime.now(timezone.utc)
    if attempt >= MAX_ATTEMPTS:
        status = "failed_needs_review"
        next_attempt_at = None
    else:
        status = "retry_wait"
        delay = min(2 ** (attempt - 1), 300)
        next_attempt_at = (now + timedelta(seconds=delay)).isoformat().replace("+00:00", "Z")
    _update_outbox_failure(db_path, outbox_id, status, next_attempt_at, error)


def _mark_failed_needs_review(db_path: Path, outbox_id: str, error: str) -> None:
    _update_outbox_failure(db_path, outbox_id, "failed_needs_review", None, error)


def _update_outbox_failure(
    db_path: Path,
    outbox_id: str,
    status: str,
    next_attempt_at: str | None,
    error: str,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE outbox_records
            SET status = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, next_attempt_at, error, utc_now_iso(), outbox_id),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_delivered(db_path: Path, outbox_id: str) -> None:
    now = utc_now_iso()
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE outbox_records
            SET status = 'delivered', next_attempt_at = NULL, last_error = NULL,
                updated_at = ?, delivered_at = ?
            WHERE id = ?
            """,
            (now, now, outbox_id),
        )
        conn.commit()
    finally:
        conn.close()


def _pending_summary(db_path: Path) -> tuple[int, int | None, str | None, str | None]:
    conn = connect(db_path)
    try:
        count = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM outbox_records WHERE status != 'delivered'"
            ).fetchone()["n"]
        )
        row = _next_outbox_row(conn)
        if row is None:
            return count, None, None, None
        return count, int(row["sequence"]), str(row["status"]), row["last_error"]
    finally:
        conn.close()


def _retry_is_due(next_attempt_at: object) -> bool:
    if next_attempt_at is None:
        return True
    value = str(next_attempt_at).replace("Z", "+00:00")
    return datetime.fromisoformat(value) <= datetime.now(timezone.utc)
