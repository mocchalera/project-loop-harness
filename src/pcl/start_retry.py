from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from .evidence import (
    EXECUTION_PROVENANCE_EVIDENCE_TYPE,
    assess_execution_provenance,
)
from .paths import ProjectPaths


START_RETRY_IDENTITY_CONTRACT_VERSION = "start-retry-identity/v1"


def build_start_request_identity(
    *,
    intent: str,
    task_id: str,
    repository_revision: str | None,
    skills: list[dict[str, str]],
) -> str:
    semantic = {
        "contract_version": START_RETRY_IDENTITY_CONTRACT_VERSION,
        "intent": intent,
        "target": {"type": "task", "id": task_id},
        "repository_revision": repository_revision,
        "skills": [
            {
                "name": skill["name"],
                "path_scope": skill["path_scope"],
                "sha256": skill["sha256"],
            }
            for skill in skills
        ],
    }
    encoded = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def load_compatible_start_retry(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    task_id: str,
    request_identity_sha256: str,
    repository_revision: str | None,
    skills: list[dict[str, str]],
    receipt_contract_version: str,
) -> dict[str, Any] | None:
    """Return the latest exact anchored Task start receipt, or fail closed."""

    event = conn.execute(
        """
        SELECT id, payload_json
        FROM events
        WHERE event_type = 'work_started'
          AND entity_type = 'task'
          AND entity_id = ?
        ORDER BY sequence DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if event is None:
        return None
    try:
        payload = json.loads(str(event["payload_json"]))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    receipt = payload.get("receipt")
    evidence_id = payload.get("evidence_id")
    if (
        not isinstance(receipt, dict)
        or receipt.get("contract_version") != receipt_contract_version
        or receipt.get("request_identity_sha256") != request_identity_sha256
        or receipt.get("target") != {"type": "task", "id": task_id}
        or receipt.get("repository_revision") != repository_revision
        or not isinstance(evidence_id, str)
    ):
        return None
    evidence = conn.execute(
        """
        SELECT type, path, command, summary
        FROM evidence
        WHERE id = ?
        """,
        (evidence_id,),
    ).fetchone()
    if (
        evidence is None
        or str(evidence["type"]) != receipt_contract_version
        or str(evidence["path"]) != f"inline:start:{task_id}"
        or str(evidence["command"]) != "pcl start"
    ):
        return None
    try:
        evidence_receipt = json.loads(str(evidence["summary"]))
    except json.JSONDecodeError:
        return None
    if evidence_receipt != receipt:
        return None

    provenance = _compatible_provenance(
        paths,
        conn,
        payload=payload,
        task_id=task_id,
        repository_revision=repository_revision,
        skills=skills,
    )
    if provenance is False:
        return None
    event_id = str(event["id"])
    return {
        "receipt": {
            **receipt,
            "evidence_id": evidence_id,
            "event_id": event_id,
        },
        "provenance": provenance,
        "reused_ids": {
            "evidence": evidence_id,
            "event": event_id,
        },
    }


def _compatible_provenance(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    payload: dict[str, Any],
    task_id: str,
    repository_revision: str | None,
    skills: list[dict[str, str]],
) -> dict[str, Any] | None | bool:
    anchor = payload.get("execution_provenance")
    if not skills:
        return None if anchor is None else False
    if not isinstance(anchor, dict):
        return False
    evidence_id = anchor.get("evidence_id")
    if not isinstance(evidence_id, str):
        return False
    assessment = assess_execution_provenance(paths, evidence_id=evidence_id)
    assessed_payload = assessment.get("payload")
    if (
        assessment.get("artifact_health") != "ok"
        or not isinstance(assessed_payload, dict)
        or assessed_payload.get("skills") != skills
        or assessed_payload.get("repository_revision") != repository_revision
        or assessed_payload.get("target") != {"type": "task", "id": task_id}
        or any(item.get("health") != "ok" for item in assessment.get("skills", []))
    ):
        return False
    evidence = conn.execute(
        "SELECT type, path FROM evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if (
        evidence is None
        or str(evidence["type"]) != EXECUTION_PROVENANCE_EVIDENCE_TYPE
        or not isinstance(evidence["path"], str)
    ):
        return False
    return {
        **anchor,
        "path": str(evidence["path"]),
    }
