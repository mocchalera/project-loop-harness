from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Any

from . import __version__
from .context_binding import _receipt_target_binding_agrees
from .context import _linked_master_trace_evidence, _master_trace_context_preflight
from .contracts.completion_packet import validate_completion_packet
from .contracts.handoff_packet import (
    HANDOFF_PACKET_CONTRACT_VERSION,
    canonical_json,
    finalize_handoff_packet,
    validate_handoff_packet,
)
from .db import connect
from .errors import EXIT_USAGE, DataStoreError, InvalidInputError, PclError
from .guards import require_initialized
from .paths import ProjectPaths
from .timeutil import utc_now_iso
from .work_briefs import current_approved_work_brief


COMPLETION_PACKET_EVIDENCE_TYPE = "completion_packet"
COMPLETION_PACKET_LINK_ROLE = "completion_packet"
CODE_CONTEXT_LINK_ROLE = "code_context"
TERMINAL_TASK_STATUSES = {"done", "cancelled", "waived"}
TERMINAL_GOAL_STATUSES = {"closed", "cancelled"}
ACTIVE_TASK_STATUSES = {"in_progress", "ready", "todo", "blocked"}
ACTIVE_GOAL_STATUSES = {"active", "open", "blocked"}
RESTART_PATH_LIMIT = 50
EVIDENCE_REF_PATTERN = re.compile(r"^evidence:(E-[0-9]{4,})$")


class ResumeTargetSelectionRequiredError(PclError):
    def __init__(self, *, candidates: list[dict[str, Any]]) -> None:
        super().__init__(
            message="Multiple active resume targets require an explicit --target.",
            code="context_pack_target_selection_required",
            exit_code=EXIT_USAGE,
            details={
                "candidates": candidates,
                "selection_command": "pcl resume --target <id> --json",
            },
        )


def build_handoff_packet(
    paths: ProjectPaths,
    *,
    target_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Build a target-bound handoff packet without mutating Project Loop state."""

    require_initialized(paths)
    conn = connect(paths.db_path)
    try:
        target = _resolve_target(conn, target_id=target_id)
        work_brief = current_approved_work_brief(
            paths,
            conn,
            target_type=target["type"],
            target_id=target["id"],
        )
        completion = _latest_completion_packet(paths, conn, target=target)
        decisions = _target_decisions(conn, target=target)
        context_refs, omitted = _context_refs(
            paths,
            conn,
            target=target,
            completion=completion,
            work_brief=work_brief,
        )
        trace_context = _trace_handoff_context(paths, conn, target=target)
        packet = _packet_body(
            paths,
            target=target,
            completion=completion,
            work_brief=work_brief,
            decisions=decisions,
            context_refs=context_refs,
            omitted_sections=omitted,
            trace_context=trace_context,
            generated_at=(now or utc_now_iso()).replace("+00:00", "Z"),
        )
    finally:
        conn.close()

    finalized = finalize_handoff_packet(packet)
    validation = validate_handoff_packet(finalized)
    if not validation.ok:
        raise DataStoreError(
            "Generated handoff packet failed validation.",
            details={"errors": list(validation.errors)},
        )
    return finalized


def render_handoff_markdown(packet: dict[str, Any]) -> str:
    """Render human-readable Markdown derived only from handoff-packet/v1 JSON."""

    validation = validate_handoff_packet(packet)
    if not validation.ok:
        raise InvalidInputError(
            "Cannot render an invalid handoff packet.",
            details={"errors": list(validation.errors)},
        )
    target = packet["target"]
    lines = [
        f"# Resume {target['type']} {target['id']}",
        "",
        packet["summary"],
        "",
        f"- Current state: {packet['current_state']}",
        f"- Generated: {packet['generated_at']}",
        f"- Packet: {packet['packet_id']}",
        "",
        "## Verified",
        "",
    ]
    lines.extend(_claim_lines(packet["verified"], verified=True))
    lines.extend(["", "## Unverified", ""])
    lines.extend(_claim_lines(packet["unverified"], verified=False))
    lines.extend(["", "## Decisions", ""])
    if packet["decisions"]:
        lines.extend(
            f"- {item['id']}: {item['summary']}" for item in packet["decisions"]
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {item}" for item in packet["blockers"] or ["None."])
    lines.extend(["", "## Risks", ""])
    lines.extend(f"- {item}" for item in packet["risks"] or ["None."])
    action = packet["next_safe_action"]
    lines.extend(["", "## Next safe action", "", action["text"]])
    if action["command"]:
        lines.extend(["", "```sh", action["command"], "```"])
    restart_context = packet.get("restart_context")
    if restart_context is not None:
        lines.extend(["", "## Restart context", ""])
        lines.extend(
            [
                f"- Target intent: {restart_context['target_intent']}",
                f"- Acceptance status: {restart_context['acceptance_status']}",
                f"- Acceptance ref: {restart_context['acceptance_ref'] or 'None.'}",
                f"- Target review: `{restart_context['target_review_command']}`",
                "- Replay status describes the completion packet; these commands were not rerun by resume.",
            ]
        )
        lines.extend(["", "### Verification commands", ""])
        if restart_context["verification_commands"]:
            for item in restart_context["verification_commands"]:
                refs = ", ".join(item["evidence_refs"]) or "none"
                lines.append(
                    f"- `{item['command']}` (previous: {item['previous_status']}; "
                    f"source: {item['proof_source']}; Evidence: {refs})"
                )
        else:
            lines.append("- None.")
        lines.extend(["", "### Evidence resolution commands", ""])
        lines.extend(
            f"- `{command}`" for command in restart_context["evidence_resolution_commands"]
        )
        if not restart_context["evidence_resolution_commands"]:
            lines.append("- None.")
        lines.extend(["", "### Changed paths", ""])
        lines.extend(f"- {path}" for path in restart_context["changed_paths"])
        if not restart_context["changed_paths"]:
            lines.append("- None.")
        lines.extend(["", "### Documentation candidates", ""])
        lines.extend(f"- {path}" for path in restart_context["documentation_candidates"])
        if not restart_context["documentation_candidates"]:
            lines.append("- None.")
    if "trace_claim_refs" in packet:
        lines.extend(["", "## Trace claim references (unverified)", ""])
        for claim_ref in packet["trace_claim_refs"]:
            lines.append(
                f"- {claim_ref['item_id']} [{claim_ref['kind']}]: {claim_ref['claim']}"
            )
            for source_ref in claim_ref["source_refs"]:
                lines.append(
                    f"  - {source_ref['evidence_id']} {source_ref['stored_path']} "
                    f"lines {source_ref['line_start']}-{source_ref['line_end']}"
                )
        if packet["trace_claim_ref_omissions"]:
            lines.extend(["", "Omitted claim references:"])
            lines.extend(
                f"- {item['item_id']}: {item['reason']}"
                for item in packet["trace_claim_ref_omissions"]
            )
    lines.extend(["", "## Context references", ""])
    if packet["context_refs"]:
        for item in packet["context_refs"]:
            digest = f"; {item['sha256']}" if item.get("sha256") else ""
            lines.append(
                f"- {item['ref']} ({item['kind']}; {item['freshness']}{digest})"
            )
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Packet bounds",
            "",
            f"- Canonical JSON bytes: {packet['size_bytes']}",
            (
                f"- Estimated tokens: {packet['estimated_token_count']} "
                f"({packet['token_estimator']})"
            ),
            "- Omitted sections: " + ", ".join(packet["omitted_sections"]),
            "",
        ]
    )
    return "\n".join(lines)


def _resolve_target(conn: sqlite3.Connection, *, target_id: str | None) -> dict[str, Any]:
    if target_id:
        if target_id.startswith("T-"):
            return _task_target(conn, target_id)
        if target_id.startswith("G-"):
            return _goal_target(conn, target_id)
        raise InvalidInputError(
            "--target must be a task or goal ID.",
            details={"target": target_id, "accepted_prefixes": ["T-", "G-"]},
        )

    tasks = _active_task_candidates(conn)
    if len(tasks) == 1:
        return _task_target(conn, str(tasks[0]["id"]))
    if len(tasks) > 1:
        raise ResumeTargetSelectionRequiredError(candidates=tasks)

    latest_packet_target = _latest_completion_packet_target(conn)
    if latest_packet_target is not None:
        return (
            _task_target(conn, latest_packet_target["id"])
            if latest_packet_target["type"] == "task"
            else _goal_target(conn, latest_packet_target["id"])
        )

    goals = _active_goal_candidates(conn)
    if len(goals) == 1:
        return _goal_target(conn, str(goals[0]["id"]))
    if len(goals) > 1:
        raise ResumeTargetSelectionRequiredError(candidates=goals)
    raise InvalidInputError(
        "No task, goal, or completion packet is available to resume.",
        details={"target": None},
    )


def _active_task_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, title, status, priority
        FROM tasks
        WHERE status IN ('in_progress', 'ready', 'todo', 'blocked')
        ORDER BY CASE status
          WHEN 'in_progress' THEN 0 WHEN 'ready' THEN 1
          WHEN 'todo' THEN 2 ELSE 3 END,
          priority, id
        """
    ).fetchall()
    return [
        {"type": "task", "id": str(row["id"]), "title": str(row["title"]), "status": str(row["status"])}
        for row in rows
    ]


def _active_goal_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, title, status
        FROM goals
        WHERE status IN ('active', 'open', 'blocked')
        ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'open' THEN 1 ELSE 2 END, id
        """
    ).fetchall()
    return [
        {"type": "goal", "id": str(row["id"]), "title": str(row["title"]), "status": str(row["status"])}
        for row in rows
    ]


def _latest_completion_packet_target(conn: sqlite3.Connection) -> dict[str, str] | None:
    row = conn.execute(
        """
        SELECT evidence_links.target_type, evidence_links.target_id
        FROM evidence_links
        JOIN evidence ON evidence.id = evidence_links.evidence_id
        WHERE evidence.type = ? AND evidence_links.link_role = ?
          AND evidence_links.target_type IN ('goal', 'task')
        ORDER BY evidence.created_at DESC, evidence.id DESC
        LIMIT 1
        """,
        (COMPLETION_PACKET_EVIDENCE_TYPE, COMPLETION_PACKET_LINK_ROLE),
    ).fetchone()
    if row is None:
        return None
    return {"type": str(row["target_type"]), "id": str(row["target_id"])}


def _task_target(conn: sqlite3.Connection, target_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT tasks.id, tasks.title, tasks.description, tasks.status, tasks.risk,
               tasks.related_goal_id, goals.budget_json AS related_goal_budget_json
        FROM tasks
        LEFT JOIN goals ON goals.id = tasks.related_goal_id
        WHERE tasks.id = ?
        """,
        (target_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(f"Task does not exist: {target_id}", details={"target": target_id})
    return {
        "type": "task",
        "id": str(row["id"]),
        "intent": str(row["description"] or row["title"]),
        "status": str(row["status"]),
        "risk": row["risk"],
        "goal_id": row["related_goal_id"],
        "budget_json": row["related_goal_budget_json"],
    }


def _goal_target(conn: sqlite3.Connection, target_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, title, status, budget_json FROM goals WHERE id = ?",
        (target_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(f"Goal does not exist: {target_id}", details={"target": target_id})
    return {
        "type": "goal",
        "id": str(row["id"]),
        "intent": str(row["title"]),
        "status": str(row["status"]),
        "risk": None,
        "goal_id": str(row["id"]),
        "budget_json": str(row["budget_json"] or "{}"),
    }


def _latest_completion_packet(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    target: dict[str, Any],
) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT evidence.id, evidence.path, evidence.created_at
        FROM evidence_links
        JOIN evidence ON evidence.id = evidence_links.evidence_id
        WHERE evidence.type = ?
          AND evidence_links.target_type = ?
          AND evidence_links.target_id = ?
          AND evidence_links.link_role = ?
        ORDER BY evidence.created_at DESC, evidence.id DESC
        """,
        (COMPLETION_PACKET_EVIDENCE_TYPE, target["type"], target["id"], COMPLETION_PACKET_LINK_ROLE),
    ).fetchall()
    for row in rows:
        artifact = _local_artifact_path(paths, str(row["path"]))
        if artifact is None or not artifact.is_file():
            continue
        try:
            packet = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not validate_completion_packet(packet).ok:
            continue
        if packet.get("target", {}).get("type") != target["type"]:
            continue
        if packet.get("target", {}).get("id") != target["id"]:
            continue
        return {
            "evidence_id": str(row["id"]),
            "path": str(row["path"]),
            "created_at": str(row["created_at"]),
            "packet": packet,
            "superseded_count": max(0, len(rows) - 1),
        }
    return None


def _target_decisions(
    conn: sqlite3.Connection,
    *,
    target: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, status, question, selected_option, reason, blocks_json, created_at
        FROM decisions
        ORDER BY created_at, id
        """
    ).fetchall()
    result = []
    for row in rows:
        try:
            blocks = json.loads(str(row["blocks_json"] or "[]"))
        except json.JSONDecodeError:
            blocks = []
        targets = {(target["type"], target["id"])}
        if target.get("goal_id"):
            targets.add(("goal", str(target["goal_id"])))
        if not any(
            isinstance(item, dict) and (item.get("type"), item.get("id")) in targets
            for item in blocks
        ):
            continue
        outcome = row["selected_option"] or row["reason"]
        summary = str(outcome or row["question"])
        result.append(
            {
                "id": str(row["id"]),
                "status": str(row["status"]),
                "summary": summary,
                "question": str(row["question"]),
            }
        )
    return result


def _context_refs(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    target: dict[str, Any],
    completion: dict[str, Any] | None,
    work_brief: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    refs: list[dict[str, Any]] = []
    omitted = ["full_transcript", "evidence_bodies"]
    selected_ids: set[str] = set()
    if completion is not None:
        evidence_id = completion["evidence_id"]
        selected_ids.add(evidence_id)
        refs.append(
            _context_ref(
                paths,
                evidence_id=evidence_id,
                path=completion["path"],
                kind="completion-packet/v1",
                freshness=_completion_freshness(paths, completion["packet"]),
            )
        )
        if completion["superseded_count"]:
            omitted.append("superseded_completion_packets")
    if work_brief is not None:
        evidence_id = str(work_brief["evidence_id"])
        selected_ids.add(evidence_id)
        refs.append(
            _context_ref(
                paths,
                evidence_id=evidence_id,
                path=str(work_brief["path"]),
                kind="work-brief/v1",
                freshness="current",
                sha256=str(work_brief["artifact_sha256"]),
            )
        )

    rows = conn.execute(
        """
        SELECT evidence.id, evidence.type, evidence.path, evidence.created_at,
               evidence_links.link_role
        FROM evidence_links
        JOIN evidence ON evidence.id = evidence_links.evidence_id
        WHERE evidence_links.target_type = ? AND evidence_links.target_id = ?
        ORDER BY CASE evidence_links.link_role
          WHEN 'code_context' THEN 0 WHEN 'supporting' THEN 1 ELSE 2 END,
          evidence.created_at DESC, evidence.id DESC
        """,
        (target["type"], target["id"]),
    ).fetchall()
    for row in rows:
        evidence_id = str(row["id"])
        if evidence_id in selected_ids or row["link_role"] == COMPLETION_PACKET_LINK_ROLE:
            continue
        freshness = "unknown"
        kind = str(row["type"])
        sha256 = None
        if row["link_role"] == CODE_CONTEXT_LINK_ROLE:
            binding = _bound_receipt_freshness(
                paths,
                target=target,
                path=str(row["path"]),
            )
            if binding is None:
                omitted.append("mismatched_code_context_receipt")
                continue
            freshness = binding
        elif row["link_role"] == "supporting":
            adhoc_context = _adhoc_context_metadata(paths, path=str(row["path"]))
            if adhoc_context is not None:
                kind = adhoc_context["kind"]
                freshness = adhoc_context["freshness"]
                sha256 = adhoc_context["sha256"]
        refs.append(
            _context_ref(
                paths,
                evidence_id=evidence_id,
                path=str(row["path"]),
                kind=kind,
                freshness=freshness,
                sha256=sha256,
            )
        )
        selected_ids.add(evidence_id)
    return refs, sorted(set(omitted))


def _packet_body(
    paths: ProjectPaths,
    *,
    target: dict[str, Any],
    completion: dict[str, Any] | None,
    work_brief: dict[str, Any] | None,
    decisions: list[dict[str, Any]],
    context_refs: list[dict[str, Any]],
    omitted_sections: list[str],
    trace_context: dict[str, Any] | None,
    generated_at: str,
) -> dict[str, Any]:
    completion_packet = completion["packet"] if completion else None
    repository_revision = (
        completion_packet.get("repository", {}).get("head_revision")
        if completion_packet
        else _git_head(paths.root)
    )
    verified = []
    unverified = []
    risks = []
    if completion_packet:
        verified = [
            {
                "text": str(claim["text"]),
                "proof_level": str(claim["proof_level"]),
                "evidence_refs": sorted(str(ref) for ref in claim["evidence_refs"]),
            }
            for claim in completion_packet.get("claims", [])
            if claim.get("evidence_refs") and claim.get("proof_level") != "L0"
        ]
        unverified = [
            {"text": str(item["text"]), "reason": str(item["reason"])}
            for item in completion_packet.get("unverified_claims", [])
        ]
        risks = [
            _risk_text(item)
            for item in completion_packet.get("risks", [])
        ]
    if not completion_packet:
        unverified.append(
            {
                "text": "No valid target-bound completion packet is available.",
                "reason": "Resume does not promote state or Evidence summaries into verified facts.",
            }
        )
    blockers = []
    if target["status"] == "blocked":
        blockers.append(f"{target['type']} {target['id']} is blocked.")
    if completion_packet and str(completion_packet.get("outcome", "")).startswith("INCOMPLETE_"):
        blockers.append(f"Latest completion outcome is {completion_packet['outcome']}.")
    blockers.extend(
        f"{item['id']}: {item['question']}"
        for item in decisions
        if item["status"] == "open"
    )
    if target.get("risk"):
        risks.append(f"Task risk is {target['risk']}.")
    action = _next_safe_action(target, completion_packet, decisions)
    restart_context = _restart_context(
        target=target,
        completion=completion,
        work_brief=work_brief,
        context_refs=context_refs,
    )
    packet: dict[str, Any] = {
        "contract_version": HANDOFF_PACKET_CONTRACT_VERSION,
        "packet_id": "hp-sha256:" + "0" * 64,
        "producer": {"name": "project-loop-harness", "version": __version__},
        "generated_at": generated_at,
        "target": {
            "type": target["type"],
            "id": target["id"],
            "work_brief_ref": restart_context["acceptance_ref"],
            "repository_revision": repository_revision,
        },
        "current_state": str(target["status"]).upper(),
        "summary": _summary(target, completion_packet),
        "verified": verified,
        "unverified": unverified,
        "decisions": [
            {"id": item["id"], "summary": item["summary"]}
            for item in decisions
        ],
        "blockers": blockers,
        "risks": sorted(set(risks)),
        "next_safe_action": action,
        "restart_context": restart_context,
        "context_refs": context_refs,
        "intent_index_ref": next(
            (
                item["ref"]
                for item in context_refs
                if item["kind"] in {"intent-index/v0", "intent_index"}
            ),
            None,
        ),
        "omitted_sections": omitted_sections,
    }
    if trace_context is not None and trace_context["status"] == "present":
        for field in (
            "trace_claim_refs",
            "trace_claim_ref_omissions",
            "trace_claim_ref_budget",
        ):
            packet[field] = trace_context[field]
    elif trace_context is not None:
        packet["omitted_sections"] = sorted(
            set(packet["omitted_sections"] + [f"trace_claim_refs:{trace_context['status']}"])
        )
    budget = _budget_remaining(target)
    if budget is not None:
        packet["budget_remaining"] = budget
    return packet


def _trace_handoff_context(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    target: dict[str, Any],
) -> dict[str, Any] | None:
    if target["type"] != "task":
        return None
    preflight = _master_trace_context_preflight(
        paths,
        target={"type": "task", "id": str(target["id"])},
        linked_evidence=_linked_master_trace_evidence(paths, conn, str(target["id"])),
    )
    candidates = preflight["candidates"]
    if not candidates["master_trace"] and not candidates["intent_index"]:
        return None
    if preflight["status"] != "present":
        return {"status": str(preflight["status"])}
    return {
        "status": "present",
        "trace_claim_refs": preflight["trace_claim_refs"],
        "trace_claim_ref_omissions": preflight["trace_claim_ref_omissions"],
        "trace_claim_ref_budget": preflight["trace_claim_ref_budget"],
    }


def _next_safe_action(
    target: dict[str, Any],
    completion_packet: dict[str, Any] | None,
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    open_decision = next((item for item in decisions if item["status"] == "open"), None)
    if open_decision:
        return {
            "text": f"Review and resolve decision {open_decision['id']} before continuing.",
            "command": f"pcl decision read {open_decision['id']} --json",
        }
    if completion_packet and completion_packet.get("next_action"):
        action = completion_packet["next_action"]
        return {"text": str(action["text"]), "command": action.get("command")}
    terminal = (
        target["status"] in TERMINAL_TASK_STATUSES
        if target["type"] == "task"
        else target["status"] in TERMINAL_GOAL_STATUSES
    )
    if terminal:
        replay_command = _first_passed_replay_command(completion_packet)
        if replay_command is not None:
            return {
                "text": "Rerun the first passed reproducible completion check.",
                "command": replay_command,
            }
        return {
            "text": "Review the verified, unverified, and residual risk sections before new work.",
            "command": None,
        }
    if target["type"] == "task":
        return {
            "text": "Review fresh target-bound context before continuing implementation.",
            "command": f"pcl context pack --task {target['id']} --include-code-context --json",
        }
    return {"text": "Inspect the next governed action for this goal.", "command": "pcl next --json"}


def _restart_context(
    *,
    target: dict[str, Any],
    completion: dict[str, Any] | None,
    context_refs: list[dict[str, Any]],
    work_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    completion_packet = completion["packet"] if completion else None
    packet_target = completion_packet.get("target", {}) if completion_packet else {}
    target_intent = str(packet_target.get("intent") or target["intent"])
    acceptance_ref = packet_target.get("work_brief_ref")
    if not isinstance(acceptance_ref, str):
        acceptance_ref = (
            f"evidence:{work_brief['evidence_id']}"
            if work_brief is not None
            else None
        )
    acceptance_status = "work_brief_linked" if acceptance_ref else "intent_only"
    approval = (
        work_brief.get("approval")
        if work_brief is not None and isinstance(work_brief.get("approval"), dict)
        else None
    )
    approval_provenance = None
    if approval is not None:
        approval_provenance = {
            "event_id": approval.get("event_id"),
            "actor_kind": approval.get("actor_kind"),
            "actor": approval.get("actor"),
            "recorder_kind": approval.get("recorder_kind"),
            "recorder": approval.get("recorder"),
            "source": approval.get("source"),
            "source_kind": approval.get("source_kind"),
            "source_ref": approval.get("source_ref"),
            "timestamp": approval.get("timestamp") or approval.get("created_at"),
            "target": approval.get("target"),
            "bound_evidence": approval.get("bound_evidence"),
        }
    verification_commands = _verification_commands(completion_packet)
    referenced_values: list[Any] = [context_refs]
    if completion_packet is not None:
        referenced_values.append(completion_packet)
    if completion is not None:
        referenced_values.append(f"evidence:{completion['evidence_id']}")
    evidence_ids = _referenced_evidence_ids(referenced_values)
    changes = completion_packet.get("changes", []) if completion_packet else []
    all_changed_paths = sorted(
        {
            str(item["path"])
            for item in changes
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
    )
    changed_paths = all_changed_paths[:RESTART_PATH_LIMIT]
    documentation_candidates = [
        path for path in all_changed_paths if _is_documentation_path(path)
    ][:RESTART_PATH_LIMIT]
    review_command = (
        f"pcl task read {target['id']} --json"
        if target["type"] == "task"
        else f"pcl report goal {target['id']} --json"
    )
    result = {
        "target_intent": target_intent,
        "acceptance_status": acceptance_status,
        "acceptance_ref": acceptance_ref,
        "target_review_command": review_command,
        "verification_commands": verification_commands,
        "evidence_resolution_commands": [
            f"pcl evidence show {evidence_id} --json" for evidence_id in evidence_ids
        ],
        "changed_paths": changed_paths,
        "documentation_candidates": documentation_candidates,
    }
    if approval_provenance is not None:
        result["approval_provenance"] = approval_provenance
    return result


def _verification_commands(completion_packet: dict[str, Any] | None) -> list[dict[str, Any]]:
    result = []
    for authoritative in _authoritative_reproducible_checks(completion_packet):
        item = authoritative["check"]
        result.append(
            {
                "command": item["command"],
                "previous_status": str(item.get("status") or "unknown"),
                "evidence_refs": authoritative["evidence_refs"],
                "proof_source": f"completion-packet/v1.checks/{item.get('id')}",
            }
        )
    return result


def _first_passed_replay_command(completion_packet: dict[str, Any] | None) -> str | None:
    return next(
        (
            str(authoritative["check"]["command"])
            for authoritative in _authoritative_reproducible_checks(completion_packet)
            if authoritative["check"].get("status") == "passed"
        ),
        None,
    )


def _authoritative_reproducible_checks(
    completion_packet: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if completion_packet is None or not isinstance(completion_packet.get("checks"), list):
        return []
    ordered = sorted(
        (
            item
            for item in completion_packet["checks"]
            if isinstance(item, dict)
            and item.get("reproducible") is True
            and isinstance(item.get("command"), str)
            and item["command"]
        ),
        key=_completion_check_sort_key,
    )
    by_command: dict[str, dict[str, Any]] = {}
    for item in ordered:
        command = str(item["command"])
        current = by_command.setdefault(command, {"check": item, "evidence_refs": []})
        current["check"] = item
        artifact_ref = item.get("artifact_ref")
        if isinstance(artifact_ref, str) and artifact_ref not in current["evidence_refs"]:
            current["evidence_refs"].append(artifact_ref)
    return sorted(
        by_command.values(),
        key=lambda authoritative: _completion_check_sort_key(authoritative["check"]),
    )


def _completion_check_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    check_id = str(item.get("id") or "")
    _, separator, suffix = check_id.rpartition("-")
    sequence = int(suffix) if separator and suffix.isdigit() else -1
    return sequence, check_id


def _referenced_evidence_ids(values: list[Any]) -> list[str]:
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, str):
            match = EVIDENCE_REF_PATTERN.fullmatch(value)
            if match:
                found.add(match.group(1))
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(values)
    return sorted(found, key=lambda value: int(value.removeprefix("E-")))


def _is_documentation_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    basename = parts[-1].upper()
    return parts[0].lower() == "docs" or basename.startswith(("README", "CONTRIBUTING"))


def _summary(target: dict[str, Any], completion_packet: dict[str, Any] | None) -> str:
    if completion_packet:
        return (
            f"{target['type'].title()} {target['id']} ({target['intent']}) is "
            f"{target['status']}; latest completion outcome: {completion_packet['outcome']}."
        )
    return (
        f"{target['type'].title()} {target['id']} ({target['intent']}) is "
        f"{target['status']}; no valid target-bound completion packet was found."
    )


def _budget_remaining(target: dict[str, Any]) -> dict[str, Any] | None:
    raw = target.get("budget_json")
    if not raw:
        return None
    try:
        budget = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    remaining = budget.get("remaining") if isinstance(budget, dict) else None
    return remaining if isinstance(remaining, dict) else None


def _risk_text(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)
    text = str(item.get("text") or "Unspecified risk")
    mitigation = item.get("mitigation")
    return f"{text} Mitigation: {mitigation}" if mitigation else text


def _context_ref(
    paths: ProjectPaths,
    *,
    evidence_id: str,
    path: str,
    kind: str,
    freshness: str,
    sha256: str | None = None,
) -> dict[str, Any]:
    artifact = _local_artifact_path(paths, path)
    digest = sha256 or (
        _sha256_file(artifact) if artifact is not None and artifact.is_file() else None
    )
    return {
        "ref": f"evidence:{evidence_id}",
        "kind": kind,
        "freshness": freshness if digest is not None else "unknown",
        "sha256": digest,
    }


def _adhoc_context_metadata(paths: ProjectPaths, *, path: str) -> dict[str, str] | None:
    manifest_path = _local_artifact_path(paths, path)
    if manifest_path is None or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    members = manifest.get("members") if isinstance(manifest, dict) else None
    if not isinstance(members, list):
        return None
    matched: list[tuple[str, str | None, str]] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        artifact = next(
            (
                candidate
                for candidate in (
                    _local_artifact_path(paths, str(member.get("stored_path") or "")),
                    _local_artifact_path(paths, str(member.get("path") or "")),
                )
                if candidate is not None and candidate.is_file()
            ),
            None,
        )
        contract_version = _artifact_contract_version(artifact)
        if contract_version not in {"master-trace/v0", "intent-index/v0"}:
            continue
        recorded_sha = member.get("sha256")
        actual_sha = _sha256_file(artifact) if artifact is not None else None
        freshness = (
            "current"
            if isinstance(recorded_sha, str)
            and actual_sha is not None
            and recorded_sha == actual_sha.removeprefix("sha256:")
            else "stale" if actual_sha is not None else "unknown"
        )
        matched.append((contract_version, actual_sha, freshness))
    if not matched:
        return None
    versions = {item[0] for item in matched}
    if versions == {"intent-index/v0"}:
        kind = "intent-index/v0"
    elif versions == {"master-trace/v0"}:
        kind = "master-trace/v0"
    else:
        kind = "master-trace-context/v0"
    freshness = (
        "stale"
        if any(item[2] == "stale" for item in matched)
        else "current" if all(item[2] == "current" for item in matched) else "unknown"
    )
    digest = matched[0][1] if len(matched) == 1 else _sha256_file(manifest_path)
    return {"kind": kind, "freshness": freshness, "sha256": digest or ""}


def _artifact_contract_version(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if text.startswith("---\n"):
        for line in text.splitlines()[1:]:
            if line == "---":
                break
            key, separator, value = line.partition(":")
            if separator and key.strip() == "contract_version":
                return value.strip().strip("\"'")
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("contract_version"), str):
        return None
    return str(payload["contract_version"])


def _bound_receipt_freshness(
    paths: ProjectPaths,
    *,
    target: dict[str, Any],
    path: str,
) -> str | None:
    artifact = _local_artifact_path(paths, path)
    if artifact is None or not artifact.is_file():
        return "unknown"
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    if not _receipt_target_binding_agrees(
        payload,
        target_type=target["type"],
        target_id=target["id"],
    ):
        return None
    warnings = payload.get("staleness_warnings")
    return "stale" if isinstance(warnings, list) and warnings else "current"


def _completion_freshness(paths: ProjectPaths, packet: dict[str, Any]) -> str:
    repository = packet.get("repository")
    if not isinstance(repository, dict):
        return "unknown"
    head = _git_head(paths.root)
    if head is None:
        return "unknown"
    if repository.get("head_revision") != head:
        return "stale"
    dirty = _git_dirty(paths.root)
    if dirty is None:
        return "unknown"
    return "current" if bool(repository.get("dirty")) == dirty else "stale"


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _git_dirty(root: Path) -> bool | None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    return bool(result.stdout) if result.returncode == 0 else None


def _local_artifact_path(paths: ProjectPaths, path: str) -> Path | None:
    if not path or path.startswith("inline:"):
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else paths.root / candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _claim_lines(items: list[dict[str, Any]], *, verified: bool) -> list[str]:
    if not items:
        return ["- None."]
    if verified:
        return [
            f"- [{item['proof_level']}] {item['text']} ({', '.join(item['evidence_refs'])})"
            for item in items
        ]
    return [f"- {item['text']} — {item['reason']}" for item in items]


def serialized_handoff_packet(packet: dict[str, Any]) -> str:
    return canonical_json(packet) + "\n"
