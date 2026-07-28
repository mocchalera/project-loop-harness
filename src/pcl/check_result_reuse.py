from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .db import connect
from .paths import ProjectPaths


CHECK_RESULT_REUSE_CONTRACT_VERSION = "check-result-reuse/v1"
_CHECK_RESULT_CONTRACT_VERSION = "finish-check-result/v2"
_CHECK_EVIDENCE_TYPE = "completion_check"
_CHECK_LINK_ROLE = "verification_check"
_ANCHOR_EVENT_TYPES = ("completion_packet_created", "finish_attempt_recorded")
_HISTORY_SCAN_LIMIT = 100


def load_compatible_check_history(
    paths: ProjectPaths,
    *,
    target_type: str,
    target_id: str,
    execution_identity_sha256: str,
    maximum_attempts: int,
) -> dict[str, Any]:
    """Load only exact-target check results anchored by append-only events."""

    history_limit = max(0, maximum_attempts - 1)
    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            """
            SELECT evidence.id, evidence.path, evidence.created_at
            FROM evidence
            JOIN evidence_links
              ON evidence_links.evidence_id = evidence.id
            WHERE evidence.type = ?
              AND evidence_links.target_type = ?
              AND evidence_links.target_id = ?
              AND evidence_links.link_role = ?
            ORDER BY evidence.created_at DESC, evidence.id DESC
            LIMIT ?
            """,
            (
                _CHECK_EVIDENCE_TYPE,
                target_type,
                target_id,
                _CHECK_LINK_ROLE,
                _HISTORY_SCAN_LIMIT,
            ),
        ).fetchall()
        event_rows = conn.execute(
            """
            SELECT payload_json
            FROM events
            WHERE event_type IN (?, ?)
              AND entity_type = ?
              AND entity_id = ?
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (
                *_ANCHOR_EVENT_TYPES,
                target_type,
                target_id,
                _HISTORY_SCAN_LIMIT,
            ),
        ).fetchall()
    finally:
        conn.close()

    anchors, conflicting_anchors = _event_anchors(event_rows)
    compatible: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    for row in rows:
        evidence_id = str(row["id"])
        if evidence_id in conflicting_anchors:
            rejections["conflicting_event_anchor"] += 1
            continue
        expected_sha256 = anchors.get(evidence_id)
        if expected_sha256 is None:
            rejections["event_anchor_missing"] += 1
            continue
        result_path = _canonical_result_path(paths, evidence_id)
        if str(row["path"]) != str(result_path.relative_to(paths.root)):
            rejections["artifact_path_mismatch"] += 1
            continue
        if not _is_regular_unlinked_path(paths.evidence_dir, result_path):
            rejections["artifact_unavailable"] += 1
            continue
        try:
            result_bytes = result_path.read_bytes()
        except OSError:
            rejections["artifact_unavailable"] += 1
            continue
        artifact_sha256 = f"sha256:{hashlib.sha256(result_bytes).hexdigest()}"
        if artifact_sha256 != expected_sha256:
            rejections["artifact_hash_mismatch"] += 1
            continue
        try:
            payload = json.loads(result_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError):
            rejections["artifact_invalid"] += 1
            continue
        rejection = _payload_rejection(
            payload,
            evidence_id=evidence_id,
            execution_identity_sha256=execution_identity_sha256,
        )
        if rejection is not None:
            rejections[rejection] += 1
            continue
        attempt_identity = dict(payload["attempt_identity"])
        assertion_result = dict(payload["assertion_result"])
        stability_stratum = _stability_stratum(attempt_identity)
        compatible.append(
            {
                "public": {
                    "evidence_id": evidence_id,
                    "artifact_sha256": artifact_sha256,
                    "assertion_status": str(assertion_result["status"]),
                    "stability_stratum": stability_stratum,
                },
                "attempt": {
                    "attempt_identity": attempt_identity,
                    "assertion_result": assertion_result,
                    "stratum": stability_stratum,
                },
            }
        )
        if len(compatible) >= history_limit:
            break

    compatible.reverse()
    return {
        "compatible": compatible,
        "rejections": dict(sorted(rejections.items())),
        "candidate_count": len(rows),
        "scan_limit": _HISTORY_SCAN_LIMIT,
    }


def _event_anchors(
    rows: list[Mapping[str, Any]],
) -> tuple[dict[str, str], set[str]]:
    anchors: dict[str, str] = {}
    conflicts: set[str] = set()
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        check_results = payload.get("check_results")
        if not isinstance(check_results, list):
            continue
        for item in check_results:
            if not isinstance(item, Mapping):
                continue
            evidence_id = item.get("evidence_id")
            sha256 = item.get("sha256")
            if not isinstance(evidence_id, str) or not isinstance(sha256, str):
                continue
            existing = anchors.get(evidence_id)
            if existing is not None and existing != sha256:
                conflicts.add(evidence_id)
            else:
                anchors[evidence_id] = sha256
    return anchors, conflicts


def _canonical_result_path(paths: ProjectPaths, evidence_id: str) -> Path:
    return paths.evidence_dir / "completion-checks" / evidence_id / "result.json"


def _is_regular_unlinked_path(evidence_dir: Path, result_path: Path) -> bool:
    try:
        relative = result_path.relative_to(evidence_dir)
        current = evidence_dir
        if current.is_symlink():
            return False
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        return result_path.is_file()
    except (OSError, ValueError):
        return False


def _payload_rejection(
    payload: Any,
    *,
    evidence_id: str,
    execution_identity_sha256: str,
) -> str | None:
    if not isinstance(payload, Mapping):
        return "artifact_invalid"
    if payload.get("contract_version") != _CHECK_RESULT_CONTRACT_VERSION:
        return "result_contract_incompatible"
    if payload.get("evidence_id") != evidence_id:
        return "evidence_id_mismatch"
    attempt_identity = payload.get("attempt_identity")
    if not isinstance(attempt_identity, Mapping):
        return "attempt_identity_missing"
    recorded_identity = attempt_identity.get("execution_identity_sha256")
    if not isinstance(recorded_identity, str):
        return "execution_identity_missing"
    if recorded_identity != execution_identity_sha256:
        return "execution_identity_mismatch"
    assertion_result = payload.get("assertion_result")
    if not isinstance(assertion_result, Mapping):
        return "assertion_result_missing"
    if assertion_result.get("status") not in {
        "passed",
        "failed",
        "not_evaluated",
        "unknown",
    }:
        return "assertion_result_invalid"
    return None


def _stability_stratum(attempt_identity: Mapping[str, Any]) -> str:
    execution = attempt_identity.get("execution")
    value = execution.get("stability_stratum") if isinstance(execution, Mapping) else None
    return str(value) if value in {"cold", "warm"} else "cold"
