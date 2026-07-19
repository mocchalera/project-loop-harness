from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .approval_provenance import (
    approval_provenance,
    provenance_from_event_payload,
    resolve_actor_kind,
    resolve_recording_provenance,
)
from .contracts.gap_report import (
    GAP_CLASSES,
    gap_lesson_sha256,
    gap_report_sha256,
    load_gap_report,
    serialized_gap_report,
    validate_gap_report,
)
from .db import connect, connect_mutation, table_exists
from .errors import DataStoreError, InvalidInputError, PclError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .strict_evidence import strict_read_canonical_file
from .timeutil import utc_now_iso


GAP_REPORT_EVIDENCE_TYPE = "gap_report"
GAP_REPORT_LINK_ROLE = "gap_report"
GAP_REPORT_EVENT_TYPE = "gap_report_recorded"
GAP_LESSON_PROMOTION_EVENT_TYPE = "gap_lesson_promotion_approved"

_TARGET_TABLES = {
    "goal": "goals",
    "task": "tasks",
    "feature": "features",
    "defect": "defects",
    "workflow_run": "workflow_runs",
    "agent_job": "agent_jobs",
}


class GapReportError(PclError):
    pass


def add_gap_report(
    paths: ProjectPaths,
    *,
    file: str,
    summary: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    summary = _required(summary, "summary")
    report = _load_valid_report(file)
    target = _report_target(report)
    artifact_sha256 = gap_report_sha256(report)
    serialized = serialized_gap_report(report)
    byte_size = len(serialized.encode("utf-8"))
    _preflight_report(paths, report, artifact_sha256)

    planned = {
        "target": target,
        "gap_class": report["gap_class"],
        "candidate_lesson_count": len(report["candidate_lessons"]),
        "artifact_sha256": artifact_sha256,
        "byte_size": byte_size,
    }
    if dry_run:
        return {"ok": True, "changed": False, "dry_run": True, "planned": planned}

    conn = connect_mutation(paths)
    final_path: Path | None = None
    temp_path: Path | None = None
    try:
        _validate_report_references(conn, report)
        _reject_duplicate(conn, artifact_sha256)
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        artifact_dir = paths.evidence_dir / "gap-reports"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        final_path = artifact_dir / f"{evidence_id.lower()}-gap-report-v1.json"
        temp_path = final_path.with_suffix(".json.tmp")
        temp_path.write_text(serialized, encoding="utf-8")
        temp_path.replace(final_path)
        now = utc_now_iso()
        relative_path = final_path.relative_to(paths.root).as_posix()
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (evidence_id, GAP_REPORT_EVIDENCE_TYPE, relative_path, summary, now),
        )
        conn.execute(
            """
            INSERT INTO evidence_links(
              evidence_id, target_type, target_id, link_role, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                target["type"],
                target["id"],
                GAP_REPORT_LINK_ROLE,
                now,
            ),
        )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=GAP_REPORT_EVENT_TYPE,
            entity_type="evidence",
            entity_id=evidence_id,
            payload={
                **planned,
                "evidence_id": evidence_id,
                "path": relative_path,
                "summary": summary,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "changed": True,
            "dry_run": False,
            "event_id": event_id,
            "evidence": {
                "id": evidence_id,
                "type": GAP_REPORT_EVIDENCE_TYPE,
                "path": relative_path,
                "summary": summary,
                **planned,
            },
        }
    except PclError:
        conn.rollback()
        _remove_uncommitted_file(conn, temp_path, final_path)
        raise
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        _remove_uncommitted_file(conn, temp_path, final_path)
        raise DataStoreError(
            f"Could not record Gap Report Evidence: {exc}",
            details={"file": file},
        ) from exc
    finally:
        conn.close()


def show_gap_report(paths: ProjectPaths, *, evidence_id: str) -> dict[str, Any]:
    require_initialized(paths)
    conn = connect(paths.db_path)
    try:
        return {"ok": True, "gap_report": _show_gap_report(conn, paths, evidence_id)}
    finally:
        conn.close()


def list_gap_reports(
    paths: ProjectPaths,
    *,
    target_ref: str | None = None,
    gap_class: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    if gap_class is not None and gap_class not in GAP_CLASSES:
        raise InvalidInputError(
            f"Invalid gap class: {gap_class}",
            details={"gap_class": gap_class, "allowed": sorted(GAP_CLASSES)},
        )
    target = parse_gap_target_ref(target_ref) if target_ref is not None else None
    conn = connect(paths.db_path)
    try:
        if target is not None:
            _validate_target(conn, target)
            rows = conn.execute(
                """
                SELECT evidence.id
                FROM evidence
                JOIN evidence_links ON evidence_links.evidence_id = evidence.id
                WHERE evidence.type = ? AND evidence_links.target_type = ?
                  AND evidence_links.target_id = ? AND evidence_links.link_role = ?
                ORDER BY evidence.created_at, evidence.id
                """,
                (
                    GAP_REPORT_EVIDENCE_TYPE,
                    target["type"],
                    target["id"],
                    GAP_REPORT_LINK_ROLE,
                ),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM evidence WHERE type = ? ORDER BY created_at, id",
                (GAP_REPORT_EVIDENCE_TYPE,),
            ).fetchall()
        reports = [_show_gap_report(conn, paths, str(row["id"])) for row in rows]
        if gap_class is not None:
            reports = [item for item in reports if item.get("gap_class") == gap_class]
        return {
            "ok": True,
            "filters": {"target": target, "gap_class": gap_class},
            "gap_reports": reports,
        }
    finally:
        conn.close()


def promote_gap_lesson(
    paths: ProjectPaths,
    *,
    evidence_id: str,
    lesson_id: str,
    actor: str,
    actor_kind: str | None = None,
    recorded_by: str | None = None,
    recorder_kind: str | None = None,
    source_kind: str | None = None,
    source_ref: str | None = None,
    reason: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    actor = _required(actor, "actor")
    lesson_id = _required(lesson_id, "lesson")
    reason = _required(reason, "reason")
    resolved_actor_kind = resolve_actor_kind(actor=actor, actor_kind=actor_kind)
    if resolved_actor_kind != "human":
        raise _error(
            "gap_lesson_human_approval_required",
            "Candidate lesson promotion requires human-origin provenance.",
            actor=actor,
            actor_kind=resolved_actor_kind,
            evidence_id=evidence_id,
            lesson_id=lesson_id,
        )
    recording = resolve_recording_provenance(
        actor=actor,
        actor_kind=resolved_actor_kind,
        recorded_by=recorded_by,
        recorder_kind=recorder_kind,
        source_kind=source_kind,
        source_ref=source_ref,
        command="pcl gap promote",
    )
    preview = show_gap_report(paths, evidence_id=evidence_id)["gap_report"]
    _require_healthy_report(preview)
    lesson = _find_lesson(preview, lesson_id)
    evidence_refs = list(lesson["evidence_refs"])
    if not evidence_refs:
        raise _error(
            "gap_lesson_evidence_required",
            "Candidate lesson promotion requires at least one supporting Evidence reference.",
            evidence_id=evidence_id,
            lesson_id=lesson_id,
        )
    now = utc_now_iso()
    receipt = approval_provenance(
        action="promotion_approval",
        actor_kind=resolved_actor_kind,
        actor=actor,
        source=recording["source"],
        source_kind=recording["source_kind"],
        source_ref=recording["source_ref"],
        recorder_kind=recording["recorder_kind"],
        recorder=recording["recorder"],
        timestamp=now,
        target=preview["target"],
        evidence_id=evidence_id,
        artifact_sha256=preview["artifact_sha256"],
        reason=reason,
    )
    lesson_sha256 = gap_lesson_sha256(_lesson_content(lesson))
    planned = {
        "evidence_id": evidence_id,
        "target": preview["target"],
        "artifact_sha256": preview["artifact_sha256"],
        "lesson_id": lesson_id,
        "lesson_sha256": lesson_sha256,
        "durable_owner": lesson["durable_owner"],
        "supporting_evidence_refs": evidence_refs,
        "application_status": "pending",
        "actor": actor,
        "actor_kind": resolved_actor_kind,
        "recorder": recording["recorder"],
        "recorder_kind": recording["recorder_kind"],
        "source": recording["source"],
        "source_kind": recording["source_kind"],
        "source_ref": recording["source_ref"],
        "reason": reason,
        "approval_provenance": receipt,
    }
    if dry_run:
        return {"ok": True, "changed": False, "dry_run": True, "planned": planned}

    conn = connect_mutation(paths)
    try:
        current = _show_gap_report(conn, paths, evidence_id)
        _require_healthy_report(current)
        current_lesson = _find_lesson(current, lesson_id)
        current_lesson_sha256 = gap_lesson_sha256(_lesson_content(current_lesson))
        if (
            current["artifact_sha256"] != planned["artifact_sha256"]
            or current_lesson_sha256 != lesson_sha256
        ):
            raise _error(
                "gap_report_unhealthy",
                f"Gap Report Evidence {evidence_id} changed before promotion approval.",
                evidence_id=evidence_id,
                lesson_id=lesson_id,
            )
        _validate_evidence_refs(conn, evidence_refs)
        matching = [
            item
            for item in _promotion_events(conn, evidence_id)
            if item.get("artifact_sha256") == current["artifact_sha256"]
            and item.get("lesson_id") == lesson_id
            and item.get("lesson_sha256") == lesson_sha256
        ]
        if matching:
            conn.rollback()
            return {
                "ok": True,
                "changed": False,
                "dry_run": False,
                "event_id": matching[-1]["event_id"],
                "promotion": matching[-1],
            }
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=GAP_LESSON_PROMOTION_EVENT_TYPE,
            entity_type="evidence",
            entity_id=evidence_id,
            payload=planned,
        )
        conn.commit()
        return {
            "ok": True,
            "changed": True,
            "dry_run": False,
            "event_id": event_id,
            "promotion": {**planned, "event_id": event_id, "created_at": now},
        }
    except PclError:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise DataStoreError(
            f"Could not approve Gap Report candidate lesson promotion: {exc}",
            details={"evidence_id": evidence_id, "lesson_id": lesson_id},
        ) from exc
    finally:
        conn.close()


def parse_gap_target_ref(value: str) -> dict[str, str]:
    target_type, separator, target_id = str(value or "").partition(":")
    if not separator or not target_type or not target_id:
        raise InvalidInputError(
            "Target must be formatted as <target-type>:<target-id>.",
            details={"target": value},
        )
    return {"type": target_type, "id": target_id}


def _load_valid_report(file: str) -> dict[str, Any]:
    try:
        value = load_gap_report(file)
    except OSError as exc:
        raise InvalidInputError(
            f"Could not read Gap Report file: {file}",
            details={"file": file, "reason": str(exc)},
        ) from exc
    except json.JSONDecodeError as exc:
        raise InvalidInputError(
            f"Gap Report file is not valid JSON: {file}",
            details={"file": file, "line": exc.lineno, "column": exc.colno},
        ) from exc
    except ValueError as exc:
        raise InvalidInputError(
            f"Gap Report file contains an invalid JSON value: {file}",
            details={"file": file, "reason": str(exc)},
        ) from exc
    result = validate_gap_report(value)
    if not result.ok:
        raise _error(
            "gap_report_contract_invalid",
            f"Gap Report contract validation failed: {file}",
            file=file,
            errors=list(result.errors),
        )
    return value


def _report_target(report: dict[str, Any]) -> dict[str, str]:
    target = report["target"]
    return {"type": str(target["type"]), "id": str(target["id"])}


def _preflight_report(
    paths: ProjectPaths,
    report: dict[str, Any],
    artifact_sha256: str,
) -> None:
    conn = connect(paths.db_path)
    try:
        _validate_report_references(conn, report)
        _reject_duplicate(conn, artifact_sha256)
    finally:
        conn.close()


def _validate_report_references(conn: sqlite3.Connection, report: dict[str, Any]) -> None:
    if not table_exists(conn, "evidence_links"):
        raise _error(
            "gap_report_evidence_links_required",
            "Gap Reports require schema 7 evidence_links support.",
        )
    _validate_target(conn, _report_target(report))
    related = report.get("related")
    if isinstance(related, dict):
        _validate_evidence_refs(conn, list(related.get("evidence_refs") or []))
        workflow_run = related.get("workflow_run")
        if workflow_run is not None:
            _validate_target(conn, {"type": "workflow_run", "id": str(workflow_run)})
    lesson_refs = [
        ref
        for lesson in report["candidate_lessons"]
        for ref in lesson["evidence_refs"]
    ]
    _validate_evidence_refs(conn, lesson_refs)


def _validate_target(conn: sqlite3.Connection, target: dict[str, str]) -> None:
    table = _TARGET_TABLES.get(target["type"])
    if table is None:
        raise _error(
            "gap_report_unknown_target_type",
            f"Unsupported Gap Report target type: {target['type']}",
            target=target,
        )
    if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (target["id"],)).fetchone() is None:
        raise _error(
            "gap_report_unknown_target",
            f"Gap Report target does not exist: {target['type']}:{target['id']}",
            target=target,
        )


def _validate_evidence_refs(conn: sqlite3.Connection, refs: list[str]) -> None:
    missing: list[str] = []
    for ref in sorted(set(refs)):
        evidence_id = ref.removeprefix("evidence:")
        if conn.execute("SELECT 1 FROM evidence WHERE id = ?", (evidence_id,)).fetchone() is None:
            missing.append(ref)
    if missing:
        raise _error(
            "gap_report_unknown_evidence_ref",
            "Gap Report references Evidence that does not exist.",
            evidence_refs=missing,
        )


def _reject_duplicate(conn: sqlite3.Connection, artifact_sha256: str) -> None:
    rows = conn.execute(
        """
        SELECT entity_id, payload_json
        FROM events
        WHERE event_type = ? AND entity_type = 'evidence'
        ORDER BY sequence, id
        """,
        (GAP_REPORT_EVENT_TYPE,),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("artifact_sha256") == artifact_sha256:
            raise _error(
                "gap_report_duplicate",
                "The same canonical Gap Report has already been recorded.",
                artifact_sha256=artifact_sha256,
                evidence_id=str(row["entity_id"]),
            )


def _show_gap_report(
    conn: sqlite3.Connection,
    paths: ProjectPaths,
    evidence_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, type, path, summary, created_at FROM evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if row is None or row["type"] != GAP_REPORT_EVIDENCE_TYPE:
        raise _error(
            "gap_report_unknown_evidence",
            f"Gap Report Evidence does not exist: {evidence_id}",
            evidence_id=evidence_id,
        )

    findings: list[dict[str, Any]] = []
    links = conn.execute(
        """
        SELECT target_type, target_id
        FROM evidence_links
        WHERE evidence_id = ? AND link_role = ?
        ORDER BY target_type, target_id
        """,
        (evidence_id, GAP_REPORT_LINK_ROLE),
    ).fetchall()
    if len(links) != 1:
        findings.append({"code": "target_link_count", "actual": len(links), "expected": 1})
        target = {"type": "", "id": ""}
    else:
        target = {"type": str(links[0]["target_type"]), "id": str(links[0]["target_id"])}

    anchors = conn.execute(
        """
        SELECT id, payload_json, created_at
        FROM events
        WHERE event_type = ? AND entity_type = 'evidence' AND entity_id = ?
        ORDER BY sequence, id
        """,
        (GAP_REPORT_EVENT_TYPE, evidence_id),
    ).fetchall()
    anchor: dict[str, Any] | None = None
    anchor_event_id: str | None = None
    if len(anchors) != 1:
        findings.append({"code": "anchor_event_count", "actual": len(anchors), "expected": 1})
    else:
        anchor_event_id = str(anchors[0]["id"])
        try:
            value = json.loads(str(anchors[0]["payload_json"]))
        except json.JSONDecodeError as exc:
            findings.append({"code": "anchor_invalid", "reason": str(exc)})
        else:
            if isinstance(value, dict):
                anchor = value
            else:
                findings.append({"code": "anchor_invalid", "reason": "payload is not an object"})

    expected_dir = paths.evidence_dir / "gap-reports"
    expected_path = expected_dir / f"{evidence_id.lower()}-gap-report-v1.json"
    row_path = paths.root / str(row["path"])
    if row_path != expected_path:
        findings.append(
            {"code": "artifact_path_invalid", "actual": str(row["path"]), "expected": str(expected_path.relative_to(paths.root))}
        )
    if anchor is not None:
        if anchor.get("evidence_id") != evidence_id:
            findings.append({"code": "anchor_evidence_mismatch"})
        if anchor.get("path") != str(row["path"]):
            findings.append({"code": "anchor_path_mismatch"})
        if anchor.get("target") != target:
            findings.append({"code": "anchor_target_mismatch"})

    expected_size = anchor.get("byte_size") if isinstance(anchor, dict) else None
    if isinstance(anchor, dict) and (
        not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0
    ):
        findings.append({"code": "anchor_byte_size_invalid", "actual": expected_size})
        expected_size = None
    read = strict_read_canonical_file(
        row_path,
        expected_parent=expected_dir,
        expected_size=expected_size if isinstance(expected_size, int) else None,
    )
    report: dict[str, Any] | None = None
    artifact_sha256: str | None = None
    if not read.ok or read.content is None:
        findings.append({"code": "artifact_read_failed", "status": read.status, "detail": read.detail})
    else:
        try:
            value = json.loads(read.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            findings.append({"code": "artifact_unreadable", "reason": str(exc)})
        else:
            validation = validate_gap_report(value)
            if not validation.ok:
                findings.append({"code": "contract_invalid", "errors": list(validation.errors)})
            elif isinstance(value, dict):
                report = value
                artifact_sha256 = gap_report_sha256(value)
                if _report_target(value) != target:
                    findings.append(
                        {"code": "target_mismatch", "artifact": _report_target(value), "link": target}
                    )
                if anchor is not None and anchor.get("artifact_sha256") != artifact_sha256:
                    findings.append(
                        {
                            "code": "artifact_hash_mismatch",
                            "expected": anchor.get("artifact_sha256"),
                            "actual": artifact_sha256,
                        }
                    )
                if anchor is not None and anchor.get("gap_class") != value["gap_class"]:
                    findings.append({"code": "anchor_gap_class_mismatch"})
                if (
                    anchor is not None
                    and anchor.get("candidate_lesson_count") != len(value["candidate_lessons"])
                ):
                    findings.append({"code": "anchor_candidate_count_mismatch"})

    promotions = _promotion_events(conn, evidence_id)
    valid_promotions: list[dict[str, Any]] = []
    for promotion in promotions:
        receipt = promotion.get("approval_provenance")
        bound = receipt.get("bound_evidence") if isinstance(receipt, dict) else None
        if (
            not isinstance(receipt, dict)
            or receipt.get("actor_kind") != "human"
            or receipt.get("action") != "promotion_approval"
            or receipt.get("target") != target
            or not isinstance(bound, dict)
            or bound.get("id") != evidence_id
            or bound.get("artifact_sha256") != promotion.get("artifact_sha256")
            or promotion.get("application_status") != "pending"
        ):
            findings.append(
                {
                    "code": "promotion_provenance_invalid",
                    "event_id": promotion.get("event_id"),
                }
            )
            continue
        valid_promotions.append(promotion)
    lessons: list[dict[str, Any]] = []
    if report is not None:
        for raw_lesson in report["candidate_lessons"]:
            lesson = dict(raw_lesson)
            lesson_sha256 = gap_lesson_sha256(_lesson_content(lesson))
            matching = [
                item
                for item in valid_promotions
                if item.get("artifact_sha256") == artifact_sha256
                and item.get("lesson_id") == lesson["lesson_id"]
                and item.get("lesson_sha256") == lesson_sha256
                and item.get("durable_owner") == lesson["durable_owner"]
                and item.get("supporting_evidence_refs") == lesson["evidence_refs"]
            ]
            promotion = matching[-1] if matching else None
            lesson["lesson_sha256"] = lesson_sha256
            lesson["promotion_status"] = (
                "approved_pending_application" if promotion is not None else "candidate"
            )
            lesson["promotion"] = promotion
            lessons.append(lesson)

    return {
        "evidence_id": evidence_id,
        "target": target,
        "path": str(row["path"]),
        "summary": str(row["summary"]),
        "created_at": str(row["created_at"]),
        "anchor_event_id": anchor_event_id,
        "artifact_sha256": artifact_sha256,
        "producer": None if report is None else report["producer"],
        "generated_at": None if report is None else report["generated_at"],
        "related": None if report is None else report.get("related"),
        "earliest_failed_handoff": (
            None if report is None else report["earliest_failed_handoff"]
        ),
        "gap_class": None if report is None else report["gap_class"],
        "candidate_lessons": lessons,
        "claims_are_facts": False,
        "health": "ok" if not findings else "warning",
        "findings": findings,
    }


def _promotion_events(conn: sqlite3.Connection, evidence_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, payload_json, created_at
        FROM events
        WHERE event_type = ? AND entity_type = 'evidence' AND entity_id = ?
        ORDER BY sequence, id
        """,
        (GAP_LESSON_PROMOTION_EVENT_TYPE, evidence_id),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        receipt = provenance_from_event_payload(
            event_id=str(row["id"]),
            created_at=str(row["created_at"]),
            payload=payload,
            default_action="promotion_approval",
        )
        if receipt is None:
            continue
        result.append(
            {
                **payload,
                "approval_provenance": receipt,
                "event_id": str(row["id"]),
                "created_at": str(row["created_at"]),
            }
        )
    return result


def _find_lesson(report: dict[str, Any], lesson_id: str) -> dict[str, Any]:
    for lesson in report["candidate_lessons"]:
        if lesson.get("lesson_id") == lesson_id:
            return lesson
    raise _error(
        "gap_lesson_unknown",
        f"Gap Report candidate lesson does not exist: {lesson_id}",
        evidence_id=report["evidence_id"],
        lesson_id=lesson_id,
    )


def _lesson_content(lesson: dict[str, Any]) -> dict[str, Any]:
    return {
        key: lesson[key]
        for key in ("lesson_id", "lesson", "durable_owner", "evidence_refs")
    }


def _require_healthy_report(report: dict[str, Any]) -> None:
    if report["health"] != "ok":
        raise _error(
            "gap_report_unhealthy",
            f"Gap Report Evidence {report['evidence_id']} is not healthy enough for promotion approval.",
            evidence_id=report["evidence_id"],
            findings=report["findings"],
        )


def _required(value: str, field: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise InvalidInputError(
            f"--{field.replace('_', '-')} must not be empty.",
            details={"field": field},
        )
    return cleaned


def _remove_uncommitted_file(
    conn: sqlite3.Connection,
    temp_path: Path | None,
    final_path: Path | None,
) -> None:
    if getattr(conn, "_authoritative_commit_completed", False):
        return
    for path in (temp_path, final_path):
        if path is not None and path.exists():
            path.unlink()


def _error(code: str, message: str, **details: Any) -> GapReportError:
    return GapReportError(message=message, code=code, details=details)
