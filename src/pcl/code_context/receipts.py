from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .scan import LARGE_FILE_BYTES, _detect_language, _line_count, _looks_binary, _relative_path, _sha256_file
from .store import IndexSnapshot, _snapshot_consistency_for_path
from ..db import connect
from ..errors import DataStoreError
from ..events import append_event
from ..ids import next_prefixed_id
from ..paths import ProjectPaths
from ..timeutil import utc_now_iso


IMPACT_CONTRACT_VERSION = "impact/v0"


CONTEXT_RECEIPT_VERSION = "context-receipt/v0"
CONTEXT_RECEIPT_EVIDENCE_TYPE = "context_receipt"


def latest_context_receipt_ref(paths: ProjectPaths) -> dict[str, str] | None:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, path, created_at
            FROM evidence
            WHERE type = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (CONTEXT_RECEIPT_EVIDENCE_TYPE,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "evidence_id": str(row["id"]),
        "receipt_path": str(row["path"]),
        "created_at": str(row["created_at"]),
    }


def evidence_ref_by_id(paths: ProjectPaths, evidence_id: str) -> dict[str, str] | None:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, type, path, created_at
            FROM evidence
            WHERE id = ?
            """,
            (evidence_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "evidence_id": str(row["id"]),
        "evidence_type": str(row["type"]),
        "receipt_path": str(row["path"]),
        "created_at": str(row["created_at"]),
    }


def resolve_context_receipt_path(paths: ProjectPaths, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return paths.root / path


def _record_context_receipt(
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    impact: dict[str, Any],
) -> tuple[str, str]:
    receipt_dir = paths.context_receipts_dir
    receipt_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(paths.db_path)
    receipt_path: Path | None = None
    tmp_path: Path | None = None
    try:
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        receipt_name = f"{evidence_id.lower()}-impact-v0.json"
        receipt_path = receipt_dir / receipt_name
        relative_receipt_path = _relative_path(paths.root, receipt_path)
        receipt = _receipt_payload(
            paths=paths,
            snapshot=snapshot,
            impact=impact,
            evidence_id=evidence_id,
            receipt_path=relative_receipt_path,
        )
        tmp_path = receipt_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(receipt_path)
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                CONTEXT_RECEIPT_EVIDENCE_TYPE,
                relative_receipt_path,
                "pcl impact --diff",
                "Impact candidate context receipt.",
                utc_now_iso(),
            ),
        )
        event_payload = {
            "contract_version": CONTEXT_RECEIPT_VERSION,
            "impact_contract_version": IMPACT_CONTRACT_VERSION,
            "diff_source": impact["diff_source"],
            "receipt_path": relative_receipt_path,
            "index_run_id": snapshot.run["id"],
            "changed_file_count": len(impact["changed_files"]),
            "excluded_changed_file_count": len(impact.get("excluded_changed_files", [])),
            "included_candidate_context_count": len(receipt["included_candidate_context"]),
            "omitted_count": len(receipt["omitted"]),
        }
        if impact.get("untracked_included_count") is not None:
            event_payload["untracked_included_count"] = impact["untracked_included_count"]
        if impact.get("base_ref") is not None:
            event_payload["base_ref"] = impact["base_ref"]
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="context_receipt_recorded",
            entity_type="evidence",
            entity_id=evidence_id,
            payload=event_payload,
        )
        conn.commit()
        return evidence_id, relative_receipt_path
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
        if receipt_path and receipt_path.exists():
            receipt_path.unlink()
        raise DataStoreError(
            f"Could not record context receipt: {exc}",
            details={"contract_version": CONTEXT_RECEIPT_VERSION},
        ) from exc
    finally:
        conn.close()


def _receipt_payload(
    *,
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    impact: dict[str, Any],
    evidence_id: str,
    receipt_path: str,
) -> dict[str, Any]:
    payload = {
        "contract_version": CONTEXT_RECEIPT_VERSION,
        "created_at": utc_now_iso(),
        "evidence_id": evidence_id,
        "receipt_path": receipt_path,
        "root_path": str(paths.root),
        "source_command": "pcl impact --diff",
        "diff_source": impact["diff_source"],
        "diff_provenance": impact.get("diff_provenance", {}),
        "index_run": impact["index_run"],
        "changed_files": impact.get("changed_files", []),
        "included_candidate_context": _included_candidate_context(paths, snapshot, impact),
        "excluded_changed_files": impact.get("excluded_changed_files", []),
        "omitted": impact["omitted"],
        "sensitive_omitted_count": impact["sensitive_omitted_count"],
        "staleness_warnings": impact["staleness_warnings"],
        "verification_suggestions": impact["verification_suggestions"],
    }
    if impact.get("untracked_included_count") is not None:
        payload["untracked_included_count"] = impact["untracked_included_count"]
        payload["untracked_included_paths"] = impact.get("untracked_included_paths", [])
    if impact.get("base_ref") is not None:
        payload["base_ref"] = impact["base_ref"]
    return payload


def _included_candidate_context(
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    impact: dict[str, Any],
) -> list[dict[str, Any]]:
    files_by_path = snapshot.files_by_path
    included: list[dict[str, Any]] = []
    for item in impact["changed_files"]:
        if item.get("untracked"):
            candidate = _untracked_added_candidate(paths, item)
            if candidate:
                included.append(candidate)
            continue
        if not item["indexed"]:
            continue
        row = files_by_path[str(item["path"])]
        candidate = {
            "path": item["path"],
            "role": "changed_file",
            "reason": item["reason"],
            "confidence": 1.0,
            "language": row["language"],
            "sha256": row["sha256"],
        }
        candidate.update(_snapshot_consistency_for_path(paths, snapshot, str(item["path"])))
        included.append(candidate)
    for item in impact["likely_impacted"]:
        row = files_by_path[str(item["path"])]
        candidate = {
            "path": item["path"],
            "role": "likely_impacted",
            "reason": item["reason"],
            "confidence": item["confidence"],
            "language": row["language"],
            "sha256": row["sha256"],
        }
        candidate.update(_snapshot_consistency_for_path(paths, snapshot, str(item["path"])))
        included.append(candidate)
    return included


def _untracked_added_candidate(paths: ProjectPaths, item: dict[str, Any]) -> dict[str, Any] | None:
    relative_path = str(item["path"])
    absolute_path = paths.root / relative_path
    try:
        stat = absolute_path.stat()
    except OSError:
        return None
    if not absolute_path.is_file():
        return None
    size = int(stat.st_size)
    if size > LARGE_FILE_BYTES:
        return None
    try:
        sample = absolute_path.read_bytes()[:8192]
    except OSError:
        return None
    if _looks_binary(sample):
        return None
    try:
        text = absolute_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        sha256 = _sha256_file(absolute_path)
    except OSError:
        sha256 = None
    return {
        "path": relative_path,
        "role": "added_file",
        "reason": str(item.get("reason") or "untracked file included as added file"),
        "confidence": 1.0,
        "language": _detect_language(absolute_path),
        "sha256": sha256,
        "size_bytes": size,
        "line_count": _line_count(text),
        "snapshot_consistency": "untracked",
        "snapshot_consistency_reason": "untracked file included from current working tree",
    }
