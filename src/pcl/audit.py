from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Callable

from .db import connect_mutation, table_exists
from .errors import PclError, ProjectionPendingError, ProjectNotInitializedError
from .events import append_event
from .evidence import ADHOC_EVIDENCE_TYPES, assess_adhoc_evidence
from .locks import jsonl_projector_lock, project_operation_lock
from .outbox import canonical_event_bytes, canonical_event_record, project_pending_events
from .paths import ProjectPaths
from .profile_bundle_store import assess_profile_output_evidence


AUDIT_CHECK_CONTRACT_VERSION = "audit-check/v1"
AUDIT_REPAIR_CONTRACT_VERSION = "audit-repair/v1"
AUDIT_REBUILD_CONTRACT_VERSION = "audit-rebuild-jsonl/v1"
EXIT_AUDIT_ISSUES = 6
EXIT_AUDIT_UNSUPPORTED = 7
EXIT_AUDIT_INTERNAL = 8


class AuditCommandError(PclError):
    pass


def audit_check(paths: ProjectPaths) -> dict[str, Any]:
    _require_initialized(paths)
    conn = _connect_read_only(paths.db_path)
    try:
        db_events = _read_db_events(conn)
        outbox_rows = _read_outbox(conn)
        evidence_rows = _read_evidence(conn)
    finally:
        conn.close()

    jsonl = _scan_jsonl(paths.events_path)
    anomalies: dict[str, list[dict[str, Any]]] = {
        "repairable": [],
        "human_review": [],
        "unsupported": [],
    }
    _check_db_sequences(db_events, anomalies)
    _check_outbox(db_events, outbox_rows, anomalies)
    _check_jsonl(db_events, outbox_rows, jsonl, anomalies)
    evidence_counts = _check_evidence(paths, evidence_rows, anomalies)

    classification_counts = {key: len(value) for key, value in anomalies.items()}
    issue_count = sum(classification_counts.values())
    outbox_status_counts = {
        status: sum(1 for row in outbox_rows if row["status"] == status)
        for status in ["pending", "retry_wait", "delivered", "failed_needs_review"]
    }
    return {
        "contract_version": AUDIT_CHECK_CONTRACT_VERSION,
        "ok": issue_count == 0,
        "status": "clean" if issue_count == 0 else "issues_found",
        "counts": {
            "db_events": len(db_events),
            "jsonl_lines": jsonl["line_count"],
            "jsonl_events": len(jsonl["events"]),
            "outbox_records": len(outbox_rows),
            "outbox_by_status": outbox_status_counts,
            "evidence_metadata": len(evidence_rows),
            **evidence_counts,
            "anomalies": issue_count,
            "anomalies_by_classification": classification_counts,
        },
        "hashes": {
            "sqlite_sha256": _sha256_file(paths.db_path),
            "jsonl_sha256": _sha256_file(paths.events_path),
        },
        "anomalies": anomalies,
    }


def audit_check_exit_code(report: dict[str, Any]) -> int:
    if report["ok"]:
        return 0
    if report["anomalies"]["unsupported"]:
        return EXIT_AUDIT_UNSUPPORTED
    return EXIT_AUDIT_ISSUES


def audit_repair(
    paths: ProjectPaths,
    *,
    apply: bool,
) -> dict[str, Any]:
    before = audit_check(paths)
    repairable = before["anomalies"]["repairable"]
    blocking = [
        *before["anomalies"]["human_review"],
        *before["anomalies"]["unsupported"],
    ]
    action_types = sorted(
        {
            str(item["supported_action"])
            for item in repairable
            if item.get("supported_action") not in {None, "none"}
        }
    )
    plan = {
        "actions": action_types,
        "anomaly_types": sorted({str(item["type"]) for item in repairable}),
        "blocking_anomaly_types": sorted({str(item["type"]) for item in blocking}),
        "reason": "Project eligible committed SQLite events without changing domain history.",
    }
    plan_hash = _sha256_bytes(_canonical_json_bytes(plan))
    response: dict[str, Any] = {
        "contract_version": AUDIT_REPAIR_CONTRACT_VERSION,
        "ok": not blocking,
        "applied": False,
        "dry_run": not apply,
        "plan": {**plan, "sha256": plan_hash},
        "before": before,
        "backup": None,
        "artifact_hashes": {
            "before_jsonl_sha256": before["hashes"]["jsonl_sha256"],
            "after_jsonl_sha256": before["hashes"]["jsonl_sha256"],
        },
    }
    if not apply:
        return response
    if blocking:
        response["refused"] = True
        response["reason"] = "Repair refused because review-required or unsupported anomalies remain."
        return response
    if not repairable:
        return response

    unsupported_actions = sorted(set(action_types) - {"flush_outbox"})
    if unsupported_actions:
        response["refused"] = True
        response["ok"] = False
        response["reason"] = f"Repair plan contains unsupported actions: {unsupported_actions}."
        return response

    backup = _backup_events(paths, label="repair")
    projection = project_pending_events(paths)
    event_id, event_projection = _record_audit_action(
        paths,
        event_type="audit_repair_applied",
        payload={
            "contract_version": AUDIT_REPAIR_CONTRACT_VERSION,
            "plan_sha256": plan_hash,
            "actions": action_types,
            "backup_path": backup["path"],
            "backup_sha256": backup["sha256"],
            "projection": projection.to_dict(),
        },
    )
    after = audit_check(paths)
    response.update(
        {
            "ok": projection.ok and event_projection is None and after["ok"],
            "applied": True,
            "backup": backup,
            "projection": projection.to_dict(),
            "audit_event_id": event_id,
            "audit_event_projection": event_projection,
            "after": after,
            "artifact_hashes": {
                "before_jsonl_sha256": before["hashes"]["jsonl_sha256"],
                "backup_jsonl_sha256": backup["sha256"],
                "after_jsonl_sha256": after["hashes"]["jsonl_sha256"],
            },
        }
    )
    return response


def audit_repair_exit_code(report: dict[str, Any]) -> int:
    if report["before"]["anomalies"]["unsupported"]:
        return EXIT_AUDIT_UNSUPPORTED
    if report["ok"]:
        return 0
    return EXIT_AUDIT_ISSUES


def rebuild_jsonl_from_sqlite(
    paths: ProjectPaths,
    *,
    output: Path | None,
    apply: bool,
    fault: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    _require_initialized(paths)
    before = audit_check(paths)
    isolated_lines = _isolated_jsonl_lines(paths.events_path, before)

    if not apply:
        conn = _connect_read_only(paths.db_path)
        try:
            db_events = _read_db_events(conn)
        finally:
            conn.close()
        _require_rebuildable_db(db_events)
        output_path = output or paths.loop_dir / "tmp" / "events.rebuild-preview.jsonl"
        artifact = _write_verified_jsonl(output_path, db_events, fault=fault)
        return {
            "contract_version": AUDIT_REBUILD_CONTRACT_VERSION,
            "ok": True,
            "applied": False,
            "source": "sqlite",
            "output": artifact,
            "backup": None,
            "isolated_lines": isolated_lines,
            "before": before,
        }

    with project_operation_lock(paths.loop_dir, exclusive=True):
        with jsonl_projector_lock(paths.loop_dir):
            conn = _connect_read_only(paths.db_path)
            try:
                db_events = _read_db_events(conn)
            finally:
                conn.close()
            _require_rebuildable_db(db_events)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            temp_path = paths.events_path.with_name(
                f".{paths.events_path.name}.rebuild.{timestamp}.tmp"
            )
            rebuilt = _write_verified_jsonl(temp_path, db_events, fault=fault)
            backup = _backup_events(paths, label="rebuild")
            os.replace(temp_path, paths.events_path)
            _fsync_directory(paths.events_path.parent)

    event_id, event_projection = _record_audit_action(
        paths,
        event_type="audit_jsonl_rebuilt",
        payload={
            "contract_version": AUDIT_REBUILD_CONTRACT_VERSION,
            "source": "sqlite",
            "backup_path": backup["path"],
            "before_sha256": before["hashes"]["jsonl_sha256"],
            "rebuilt_sha256": rebuilt["sha256"],
            "event_count": rebuilt["event_count"],
            "first_sequence": rebuilt["first_sequence"],
            "last_sequence": rebuilt["last_sequence"],
            "isolated_line_count": len(isolated_lines),
        },
        reconcile_delivered_through_sequence=(
            int(rebuilt["last_sequence"]) if rebuilt["last_sequence"] is not None else 0
        ),
    )
    for item in isolated_lines:
        item["preserved_in"] = backup["path"]
    after = audit_check(paths)
    return {
        "contract_version": AUDIT_REBUILD_CONTRACT_VERSION,
        "ok": event_projection is None and not _audit_log_anomalies(after),
        "applied": True,
        "source": "sqlite",
        "output": {
            **rebuilt,
            "path": _relative_or_absolute(paths, paths.events_path),
            "final_sha256": after["hashes"]["jsonl_sha256"],
            "final_event_count": after["counts"]["jsonl_events"],
        },
        "backup": backup,
        "isolated_lines": isolated_lines,
        "audit_event_id": event_id,
        "audit_event_projection": event_projection,
        "before": before,
        "after": after,
    }


def audit_rebuild_exit_code(report: dict[str, Any]) -> int:
    return 0 if report["ok"] else EXIT_AUDIT_ISSUES


def _require_initialized(paths: ProjectPaths) -> None:
    if not paths.loop_dir.exists() or not paths.db_path.exists():
        raise ProjectNotInitializedError(root=str(paths.root))


def _connect_read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA query_only = ON")
    return conn


def _read_db_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_exists(conn, "events"):
        raise AuditCommandError(
            message="SQLite events table is missing.",
            code="audit_unsupported_sqlite",
            exit_code=EXIT_AUDIT_UNSUPPORTED,
        )
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(events)")}
    if "sequence" not in columns:
        raise AuditCommandError(
            message="SQLite events table does not support event sequences.",
            code="audit_unsupported_sqlite",
            exit_code=EXIT_AUDIT_UNSUPPORTED,
        )
    rows = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events ORDER BY sequence, id
        """
    ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        event = dict(row)
        try:
            payload = json.loads(str(event["payload_json"]))
        except json.JSONDecodeError:
            payload = None
        event["payload"] = payload
        events.append(event)
    return events


def _read_outbox(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_exists(conn, "outbox_records"):
        raise AuditCommandError(
            message="SQLite outbox_records table is missing.",
            code="audit_unsupported_sqlite",
            exit_code=EXIT_AUDIT_UNSUPPORTED,
        )
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT outbox_records.id, outbox_records.event_id, outbox_records.sink,
                   outbox_records.status, outbox_records.attempts,
                   outbox_records.next_attempt_at, outbox_records.last_error,
                   events.sequence
            FROM outbox_records
            LEFT JOIN events ON events.id = outbox_records.event_id
            ORDER BY events.sequence, outbox_records.id
            """
        ).fetchall()
    ]


def _read_evidence(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_exists(conn, "evidence"):
        return []
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id, type, path FROM evidence ORDER BY created_at, id"
        ).fetchall()
    ]


def _scan_jsonl(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"line_count": 0, "events": [], "invalid": [], "ends_with_lf": True}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AuditCommandError(
            message=f"Cannot read events.jsonl: {exc}",
            code="audit_internal_error",
            exit_code=EXIT_AUDIT_INTERNAL,
        ) from exc
    events: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    lines = raw.splitlines()
    for line_number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            invalid.append({"line": line_number, "reason": "malformed", "detail": str(exc)})
            continue
        required_fields = {
            "id",
            "event_type",
            "entity_type",
            "entity_id",
            "payload",
            "created_at",
        }
        if (
            not isinstance(value, dict)
            or not value.get("id")
            or not required_fields.issubset(value)
            or not isinstance(value.get("payload"), dict)
        ):
            invalid.append({"line": line_number, "reason": "unknown_record"})
            continue
        event = dict(value)
        event["_line"] = line_number
        events.append(event)
    if raw and not raw.endswith(b"\n"):
        invalid.append({"line": len(lines), "reason": "partial_trailing_line"})
    return {
        "line_count": len(lines),
        "events": events,
        "invalid": invalid,
        "ends_with_lf": not raw or raw.endswith(b"\n"),
    }


def _check_db_sequences(
    db_events: list[dict[str, Any]],
    anomalies: dict[str, list[dict[str, Any]]],
) -> None:
    sequences = [event["sequence"] for event in db_events]
    if sequences != list(range(1, len(sequences) + 1)):
        _add_anomaly(
            anomalies,
            "unsupported",
            "db_sequence_gap",
            "SQLite event sequence is not contiguous from 1.",
            "none",
            sequences=sequences[:20],
        )
    for event in db_events:
        if not isinstance(event["payload"], dict):
            _add_anomaly(
                anomalies,
                "unsupported",
                "db_event_payload_invalid",
                f"SQLite event {event['id']} payload_json is not a JSON object.",
                "none",
                event_id=event["id"],
            )


def _check_outbox(
    db_events: list[dict[str, Any]],
    outbox_rows: list[dict[str, Any]],
    anomalies: dict[str, list[dict[str, Any]]],
) -> None:
    outbox_by_event = {str(row["event_id"]): row for row in outbox_rows}
    for row in outbox_rows:
        event_id = str(row["event_id"])
        if row["sequence"] is None:
            _add_anomaly(
                anomalies,
                "unsupported",
                "orphan_outbox",
                f"Outbox record {row['id']} references missing event {event_id}.",
                "none",
                outbox_id=row["id"],
                event_id=event_id,
            )
            continue
        status = str(row["status"])
        if status in {"pending", "retry_wait"}:
            _add_anomaly(
                anomalies,
                "repairable",
                f"outbox_{status}",
                f"Event {event_id} has {status} JSONL delivery.",
                "flush_outbox",
                event_id=event_id,
                sequence=row["sequence"],
                outbox_id=row["id"],
            )
        elif status == "failed_needs_review":
            _add_anomaly(
                anomalies,
                "human_review",
                "outbox_failed_needs_review",
                f"Event {event_id} projection requires human review.",
                "rebuild_jsonl_from_sqlite",
                event_id=event_id,
                sequence=row["sequence"],
                outbox_id=row["id"],
                last_error=row["last_error"],
            )
    for event in db_events:
        event_id = str(event["id"])
        if event_id not in outbox_by_event:
            _add_anomaly(
                anomalies,
                "unsupported",
                "missing_outbox_record",
                f"SQLite event {event_id} has no JSONL outbox record.",
                "none",
                event_id=event_id,
                sequence=event["sequence"],
            )


def _check_jsonl(
    db_events: list[dict[str, Any]],
    outbox_rows: list[dict[str, Any]],
    jsonl: dict[str, Any],
    anomalies: dict[str, list[dict[str, Any]]],
) -> None:
    for invalid in jsonl["invalid"]:
        _add_anomaly(
            anomalies,
            "unsupported",
            "unknown_or_legacy_jsonl_line",
            f"events.jsonl line {invalid['line']} is not a supported event record.",
            "isolate_in_backup_then_rebuild",
            **invalid,
        )
    db_by_id = {str(event["id"]): event for event in db_events}
    outbox_by_event = {str(row["event_id"]): row for row in outbox_rows}
    jsonl_by_id: dict[str, dict[str, Any]] = {}
    first_line: dict[str, int] = {}
    for event in jsonl["events"]:
        event_id = str(event["id"])
        if event_id in jsonl_by_id:
            _add_anomaly(
                anomalies,
                "human_review",
                "duplicate_jsonl_event",
                f"events.jsonl event {event_id} is duplicated.",
                "rebuild_jsonl_from_sqlite",
                event_id=event_id,
                first_line=first_line[event_id],
                duplicate_line=event["_line"],
            )
            continue
        jsonl_by_id[event_id] = event
        first_line[event_id] = int(event["_line"])

    jsonl_ids = set(jsonl_by_id)
    db_ids = set(db_by_id)
    db_order = [str(event["id"]) for event in db_events]
    present_positions = [index for index, event_id in enumerate(db_order) if event_id in jsonl_ids]
    prefix_length = 0
    for event_id in db_order:
        if event_id not in jsonl_ids:
            break
        prefix_length += 1
    jsonl_is_db_prefix = jsonl_ids == set(db_order[:prefix_length])
    del present_positions
    for event_id in sorted(db_ids - jsonl_ids):
        event = db_by_id[event_id]
        row = outbox_by_event.get(event_id)
        is_pending_suffix = (
            jsonl_is_db_prefix
            and
            int(event["sequence"]) > prefix_length
            and row is not None
            and row["status"] in {"pending", "retry_wait"}
        )
        classification = "repairable" if is_pending_suffix else "human_review"
        action = "flush_outbox" if is_pending_suffix else "rebuild_jsonl_from_sqlite"
        _add_anomaly(
            anomalies,
            classification,
            "missing_jsonl_event",
            f"SQLite event {event_id} is missing from events.jsonl.",
            action,
            event_id=event_id,
            sequence=event["sequence"],
        )
    for event_id in sorted(jsonl_ids - db_ids):
        event = jsonl_by_id[event_id]
        _add_anomaly(
            anomalies,
            "unsupported",
            "jsonl_only_event",
            f"events.jsonl event {event_id} has no authoritative SQLite event.",
            "isolate_in_backup_then_rebuild",
            event_id=event_id,
            line=event["_line"],
        )

    comparable_order = [str(event["id"]) for event in jsonl["events"] if event["id"] in db_by_id]
    expected_order = [event_id for event_id in db_order if event_id in jsonl_ids]
    if comparable_order != expected_order:
        _add_anomaly(
            anomalies,
            "human_review",
            "jsonl_order_mismatch",
            "events.jsonl order does not match SQLite event sequence order.",
            "rebuild_jsonl_from_sqlite",
        )

    for event_id in sorted(db_ids & jsonl_ids):
        db_event = db_by_id[event_id]
        jsonl_event = jsonl_by_id[event_id]
        expected = canonical_event_record(db_event)
        actual = {key: jsonl_event.get(key) for key in expected}
        if actual.get("sequence") is None:
            actual["sequence"] = expected["sequence"]
        if actual != expected:
            _add_anomaly(
                anomalies,
                "human_review",
                "jsonl_event_mismatch",
                f"events.jsonl event {event_id} differs from authoritative SQLite content.",
                "rebuild_jsonl_from_sqlite",
                event_id=event_id,
                line=jsonl_event["_line"],
                sequence=db_event["sequence"],
            )


def _check_evidence(
    paths: ProjectPaths,
    evidence_rows: list[dict[str, Any]],
    anomalies: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    referenced: set[Path] = set()
    referenced_profile_directories: set[Path] = set()
    missing_count = 0
    mismatch_count = 0
    for row in evidence_rows:
        value = str(row["path"] or "").strip()
        if _is_virtual_or_external(value):
            continue
        artifact = Path(value)
        if not artifact.is_absolute():
            artifact = paths.root / artifact
        artifact = artifact.resolve()
        referenced.add(artifact)
        if row["type"] == "profile_output_bundle":
            referenced_profile_directories.add(artifact.parent)
        if not artifact.exists() or not artifact.is_file():
            missing_count += 1
            _add_anomaly(
                anomalies,
                "human_review",
                "evidence_file_missing",
                f"Evidence metadata {row['id']} references a missing file.",
                "report_only",
                evidence_id=row["id"],
                path=value,
            )
            continue
        if row["type"] in ADHOC_EVIDENCE_TYPES:
            assessment = assess_adhoc_evidence(
                paths,
                evidence_id=str(row["id"]),
                evidence_type=str(row["type"]),
                manifest_path_value=value,
                validate_optional_fields=True,
            )
            for finding in assessment["findings"]:
                mismatch_count += 1
                code = str(finding.get("code"))
                classification = (
                    "unsupported" if code == "contract_version_unsupported" else "human_review"
                )
                _add_anomaly(
                    anomalies,
                    classification,
                    "evidence_metadata_file_mismatch",
                    f"Evidence {row['id']} failed metadata/file reconciliation: {code}.",
                    "report_only",
                    evidence_id=row["id"],
                    finding=finding,
                )
        elif row["type"] == "profile_output_bundle":
            assessment = assess_profile_output_evidence(
                paths,
                evidence_id=str(row["id"]),
                manifest_path_value=value,
            )
            for finding in assessment["findings"]:
                mismatch_count += 1
                _add_anomaly(
                    anomalies,
                    "human_review",
                    "evidence_metadata_file_mismatch",
                    f"Profile bundle Evidence {row['id']} failed reconciliation.",
                    "report_only",
                    evidence_id=row["id"],
                    finding=finding,
                )

    orphan_temp_count = 0
    orphan_manifest_count = 0
    orphan_completion_packet_count = 0
    orphan_profile_temp_count = 0
    orphan_profile_bundle_count = 0
    profile_root = paths.evidence_dir / "profile-output-bundles"
    if paths.evidence_dir.exists():
        for candidate in sorted(paths.evidence_dir.rglob("*")):
            if not candidate.is_file():
                continue
            if profile_root in candidate.parents:
                continue
            if candidate.resolve() in referenced:
                continue
            if candidate.name.endswith((".tmp", ".temp")):
                orphan_temp_count += 1
                _add_anomaly(
                    anomalies,
                    "human_review",
                    "orphan_temp_evidence",
                    "Unreferenced temporary Evidence artifact requires review; it was not deleted.",
                    "quarantine_or_report",
                    path=_relative_or_absolute(paths, candidate),
                )
            elif candidate.parent == paths.evidence_dir / "adhoc" and candidate.name.endswith(
                "-adhoc-v0.json"
            ):
                orphan_manifest_count += 1
                _add_anomaly(
                    anomalies,
                    "human_review",
                    "orphan_evidence_manifest",
                    "Unreferenced finalized Evidence manifest requires review; it was not deleted.",
                    "quarantine_or_report",
                    path=_relative_or_absolute(paths, candidate),
                )
            elif candidate.parent == paths.evidence_dir / "completion-packets" and candidate.suffix == ".json":
                orphan_completion_packet_count += 1
                _add_anomaly(
                    anomalies,
                    "human_review",
                    "orphan_completion_packet",
                    "Unreferenced finalized completion packet requires review; it was not deleted.",
                    "quarantine_or_report",
                    path=_relative_or_absolute(paths, candidate),
                )
        if profile_root.exists():
            for candidate in sorted(profile_root.iterdir()):
                if not candidate.is_dir():
                    continue
                resolved = candidate.resolve()
                if candidate.name.startswith(".staging-"):
                    orphan_profile_temp_count += 1
                    _add_anomaly(
                        anomalies,
                        "human_review",
                        "orphan_profile_bundle_staging",
                        "Unreferenced Profile bundle staging directory requires review; it was not deleted.",
                        "quarantine_or_report",
                        path=_relative_or_absolute(paths, candidate),
                    )
                elif resolved not in referenced_profile_directories:
                    orphan_profile_bundle_count += 1
                    _add_anomaly(
                        anomalies,
                        "human_review",
                        "orphan_profile_bundle_directory",
                        "Finalized Profile bundle directory has no durable Evidence row.",
                        "quarantine_or_report",
                        path=_relative_or_absolute(paths, candidate),
                    )
    return {
        "evidence_missing_files": missing_count,
        "evidence_mismatches": mismatch_count,
        "orphan_temp_evidence": orphan_temp_count,
        "orphan_evidence_manifests": orphan_manifest_count,
        "orphan_completion_packets": orphan_completion_packet_count,
        "orphan_profile_bundle_staging": orphan_profile_temp_count,
        "orphan_profile_bundle_directories": orphan_profile_bundle_count,
    }


def _add_anomaly(
    anomalies: dict[str, list[dict[str, Any]]],
    classification: str,
    anomaly_type: str,
    message: str,
    supported_action: str,
    **details: Any,
) -> None:
    anomalies[classification].append(
        {
            "type": anomaly_type,
            "classification": classification,
            "message": message,
            "supported_action": supported_action,
            "details": details,
        }
    )


def _backup_events(paths: ProjectPaths, *, label: str) -> dict[str, Any]:
    backup_dir = paths.reports_dir / "audit-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_path = backup_dir / f"events.{label}.{timestamp}.jsonl"
    if paths.events_path.exists():
        with paths.events_path.open("rb") as source, backup_path.open("xb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
    else:
        with backup_path.open("xb") as target:
            target.flush()
            os.fsync(target.fileno())
    _fsync_directory(backup_dir)
    return {
        "path": _relative_or_absolute(paths, backup_path),
        "sha256": _sha256_file(backup_path),
        "size_bytes": backup_path.stat().st_size,
    }


def _record_audit_action(
    paths: ProjectPaths,
    *,
    event_type: str,
    payload: dict[str, Any],
    reconcile_delivered_through_sequence: int | None = None,
) -> tuple[str, dict[str, Any] | None]:
    conn = connect_mutation(paths)
    event_id = ""
    projection_error: dict[str, Any] | None = None
    try:
        if reconcile_delivered_through_sequence is not None:
            conn.execute(
                """
                UPDATE outbox_records
                SET status = 'delivered', next_attempt_at = NULL, last_error = NULL,
                    updated_at = ?, delivered_at = COALESCE(delivered_at, ?)
                WHERE event_id IN (SELECT id FROM events WHERE sequence <= ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    reconcile_delivered_through_sequence,
                ),
            )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=event_type,
            entity_type="audit",
            entity_id=None,
            payload=payload,
        )
        try:
            conn.commit()
        except ProjectionPendingError as exc:
            projection_error = exc.to_dict()
    finally:
        conn.close()
    return event_id, projection_error


def _write_verified_jsonl(
    path: Path,
    db_events: list[dict[str, Any]],
    *,
    fault: Callable[[str], None] | None,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as target:
            for event in db_events:
                target.write(canonical_event_bytes(canonical_event_record(event)))
            target.flush()
            os.fsync(target.fileno())
    except FileExistsError as exc:
        raise AuditCommandError(
            message=f"Refusing to overwrite existing rebuild artifact: {path}",
            code="audit_rebuild_output_exists",
            exit_code=EXIT_AUDIT_ISSUES,
            details={"path": str(path)},
        ) from exc
    _verify_rebuilt_file(path, db_events)
    if fault is not None:
        fault("after_temp_validation_before_replace")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
        "event_count": len(db_events),
        "first_sequence": db_events[0]["sequence"] if db_events else None,
        "last_sequence": db_events[-1]["sequence"] if db_events else None,
    }


def _verify_rebuilt_file(path: Path, db_events: list[dict[str, Any]]) -> None:
    scanned = _scan_jsonl(path)
    if scanned["invalid"] or len(scanned["events"]) != len(db_events):
        raise AuditCommandError(
            message="Generated JSONL failed structural verification.",
            code="audit_rebuild_verification_failed",
            exit_code=EXIT_AUDIT_INTERNAL,
        )
    for expected_event, actual_event in zip(db_events, scanned["events"], strict=True):
        expected = canonical_event_record(expected_event)
        actual = {key: actual_event.get(key) for key in expected}
        if actual != expected:
            raise AuditCommandError(
                message=f"Generated JSONL differs at event {expected['id']}.",
                code="audit_rebuild_verification_failed",
                exit_code=EXIT_AUDIT_INTERNAL,
            )


def _require_rebuildable_db(db_events: list[dict[str, Any]]) -> None:
    sequences = [event["sequence"] for event in db_events]
    if sequences != list(range(1, len(db_events) + 1)) or any(
        not isinstance(event["payload"], dict) for event in db_events
    ):
        raise AuditCommandError(
            message="SQLite event history is unsupported for JSONL rebuild.",
            code="audit_unsupported_sqlite",
            exit_code=EXIT_AUDIT_UNSUPPORTED,
            details={"sequences": sequences[:20]},
        )


def _isolated_jsonl_lines(path: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    isolated: list[dict[str, Any]] = []
    for classification in ["unsupported", "human_review"]:
        for anomaly in report["anomalies"][classification]:
            if anomaly["type"] not in {
                "unknown_or_legacy_jsonl_line",
                "jsonl_only_event",
                "duplicate_jsonl_event",
                "jsonl_event_mismatch",
            }:
                continue
            isolated.append(
                {
                    "type": anomaly["type"],
                    "line": anomaly["details"].get("line")
                    or anomaly["details"].get("duplicate_line"),
                    "event_id": anomaly["details"].get("event_id"),
                    "preserved_in": "original_file" if path.exists() else None,
                }
            )
    return isolated


def _audit_log_anomalies(report: dict[str, Any]) -> list[dict[str, Any]]:
    audit_types = {
        "db_sequence_gap",
        "db_event_payload_invalid",
        "orphan_outbox",
        "outbox_pending",
        "outbox_retry_wait",
        "outbox_failed_needs_review",
        "missing_outbox_record",
        "unknown_or_legacy_jsonl_line",
        "duplicate_jsonl_event",
        "missing_jsonl_event",
        "jsonl_only_event",
        "jsonl_order_mismatch",
        "jsonl_event_mismatch",
    }
    return [
        anomaly
        for classification in report["anomalies"].values()
        for anomaly in classification
        if anomaly["type"] in audit_types
    ]


def _is_virtual_or_external(value: str) -> bool:
    return not value or "://" in value or value.startswith(
        ("inline:", "external:", "virtual:", "command:")
    )


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _relative_or_absolute(paths: ProjectPaths, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(paths.root))
    except ValueError:
        return str(path.resolve())


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
