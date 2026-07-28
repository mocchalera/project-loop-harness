from __future__ import annotations

from json import JSONDecodeError
import sqlite3
from typing import Any

from .contracts.completion_packet import (
    load_completion_packet,
    validate_completion_packet,
)
from .evidence import EvidenceAddError, require_healthy_terminal_evidence
from .paths import ProjectPaths


def require_completed_goal_packet(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    goal_id: str,
    evidence_id: str,
) -> dict[str, Any]:
    row = require_healthy_terminal_evidence(
        paths,
        conn,
        evidence_id=evidence_id,
        error_code="goal_close_verification_required",
        allowed_types={"completion_packet"},
    )
    link = conn.execute(
        """
        SELECT 1 FROM evidence_links
        WHERE evidence_id = ? AND target_type = 'goal' AND target_id = ?
          AND link_role = 'completion_packet'
        """,
        (evidence_id, goal_id),
    ).fetchone()
    if link is None:
        raise EvidenceAddError(
            f"Completion packet Evidence {evidence_id} is not bound to goal {goal_id}.",
            code="goal_close_verification_required",
            details={
                "goal_id": goal_id,
                "evidence_id": evidence_id,
                "reason": "target_link_mismatch",
            },
        )
    packet_path = (paths.root / str(row["path"])).resolve()
    try:
        packet = load_completion_packet(packet_path)
    except (OSError, JSONDecodeError) as exc:
        raise EvidenceAddError(
            f"Completion packet Evidence {evidence_id} cannot be read.",
            code="goal_close_verification_required",
            details={
                "goal_id": goal_id,
                "evidence_id": evidence_id,
                "reason": "packet_unreadable",
                "detail": str(exc),
            },
        ) from exc
    validation = validate_completion_packet(packet)
    target = packet.get("target", {}) if isinstance(packet, dict) else {}
    outcome = str(packet.get("outcome") or "") if isinstance(packet, dict) else ""
    risks = packet.get("risks", []) if isinstance(packet, dict) else []
    low_risk = all(isinstance(risk, dict) and risk.get("severity") == "low" for risk in risks)
    if (
        not validation.ok
        or target.get("type") != "goal"
        or target.get("id") != goal_id
        or outcome not in {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"}
        or not low_risk
    ):
        raise EvidenceAddError(
            (
                f"Completion packet Evidence {evidence_id} is not valid "
                f"low-risk closure proof for goal {goal_id}."
            ),
            code="goal_close_verification_required",
            details={
                "goal_id": goal_id,
                "evidence_id": evidence_id,
                "reason": "packet_invalid",
                "outcome": outcome,
                "target": target,
                "contract_errors": list(validation.errors),
            },
        )
    return {
        "evidence_id": evidence_id,
        "outcome": outcome,
        "packet": packet,
        "path": str(row["path"]),
    }
