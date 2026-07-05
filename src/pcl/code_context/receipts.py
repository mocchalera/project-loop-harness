from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .scan import _relative_path
from .store import IndexSnapshot, _snapshot_consistency_for_path
from ..db import connect
from ..errors import DataStoreError
from ..events import append_event
from ..ids import next_prefixed_id
from ..paths import ProjectPaths
from ..timeutil import utc_now_iso


IMPACT_CONTRACT_VERSION = "impact/v0"


CONTEXT_RECEIPT_VERSION = "context-receipt/v0"


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
                "context_receipt",
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
        "included_candidate_context": _included_candidate_context(paths, snapshot, impact),
        "excluded_changed_files": impact.get("excluded_changed_files", []),
        "omitted": impact["omitted"],
        "sensitive_omitted_count": impact["sensitive_omitted_count"],
        "staleness_warnings": impact["staleness_warnings"],
        "verification_suggestions": impact["verification_suggestions"],
    }
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
