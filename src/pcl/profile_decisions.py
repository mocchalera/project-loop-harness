from __future__ import annotations

import hashlib
import json
from typing import Any
import uuid

from .approval_provenance import (
    approval_provenance,
    resolve_actor_kind,
    resolve_recording_provenance,
)
from .contracts._profile_contract import load_strict_json, loads_strict_json
from .contracts.decision_proposal import validate_decision_proposal
from .db import connect, connect_mutation
from .errors import EXIT_USAGE, PclError
from .events import append_event
from .paths import ProjectPaths
from .profile_bundle_store import assess_profile_output_evidence
from .timeutil import utc_now_iso


PROFILE_DECISION_SELECTED_CONTRACT_VERSION = "profile-decision-selected/v1"
DECLINED_ALL_CANDIDATES = "declined_all_candidates"


class ProfileDecisionError(PclError):
    pass


def show_profile_proposal(paths: ProjectPaths, decision_id: str) -> dict[str, Any]:
    conn = connect(paths.db_path)
    try:
        decision = conn.execute(
            "SELECT * FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        if decision is None:
            raise _error("profile_decision_missing", f"Decision does not exist: {decision_id}")
        event = conn.execute(
            """
            SELECT id, payload_json, created_at FROM events
            WHERE event_type = 'profile_decision_proposed'
              AND entity_type = 'decision' AND entity_id = ?
            ORDER BY sequence LIMIT 1
            """,
            (decision_id,),
        ).fetchone()
        if event is None:
            raise _error(
                "decision_proposal_not_linked",
                f"Decision {decision_id} is not a Profile proposal Decision.",
            )
        payload = json.loads(str(event["payload_json"]))
        evidence_id = str(payload["bundle_evidence_id"])
        evidence = conn.execute(
            "SELECT type, path FROM evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        if evidence is None or evidence["type"] != "profile_output_bundle":
            raise _error(
                "profile_decision_evidence_missing",
                "Proposal bundle Evidence is missing or has the wrong type.",
            )
        assessment = assess_profile_output_evidence(
            paths,
            evidence_id=evidence_id,
            manifest_path_value=str(evidence["path"]),
        )
        if assessment["health"] != "ok":
            raise _error(
                "profile_decision_evidence_drifted",
                "Proposal bundle Evidence failed immutable byte reconciliation.",
                assessment=assessment,
            )
        manifest_path = paths.root / str(evidence["path"])
        manifest = load_strict_json(manifest_path)
        member = next(
            (
                item
                for item in manifest["members"]
                if item.get("artifact_id") == payload.get("artifact_id")
            ),
            None,
        )
        if not isinstance(member, dict):
            raise _error(
                "profile_decision_artifact_missing",
                "Proposal artifact is absent from the immutable Evidence manifest.",
            )
        if (
            member.get("logical_path") != payload.get("artifact_path")
            or member.get("sha256") != payload.get("artifact_sha256")
        ):
            raise _error(
                "profile_decision_event_binding_mismatch",
                "Proposal event binding differs from the immutable Evidence manifest.",
            )
        proposal_path = manifest_path.parent / str(member["storage_path"])
        proposal_bytes = proposal_path.read_bytes()
        proposal = loads_strict_json(proposal_bytes)
        validation = validate_decision_proposal(proposal)
        if not validation.ok:
            raise _error(
                "profile_decision_proposal_invalid",
                "Stored proposal no longer validates.",
                errors=list(validation.errors),
            )
        actual_hash = hashlib.sha256(proposal_bytes).hexdigest()
        if actual_hash != payload.get("artifact_sha256"):
            raise _error(
                "profile_decision_proposal_hash_mismatch",
                "Stored proposal hash differs from the proposal event.",
            )
        if (
            proposal.get("proposal_id") != payload.get("proposal_id")
            or [item["candidate_id"] for item in proposal["candidates"]]
            != payload.get("candidate_ids")
            or proposal.get("recommended_candidate_id")
            != payload.get("recommended_candidate_id")
        ):
            raise _error(
                "profile_decision_event_binding_mismatch",
                "Proposal content differs from the proposal event binding.",
            )
        return {
            "ok": True,
            "decision": dict(decision),
            "proposal_event_id": event["id"],
            "bundle_evidence_id": evidence_id,
            "artifact_sha256": actual_hash,
            "proposal": proposal,
        }
    finally:
        conn.close()


def select_profile_proposal(
    paths: ProjectPaths,
    *,
    decision_id: str,
    candidate_id: str | None,
    decline: bool,
    actor: str,
    actor_kind: str | None,
    recorded_by: str | None,
    recorder_kind: str | None,
    source_kind: str | None,
    source_ref: str | None,
    reason: str,
    override_reason: str | None,
) -> dict[str, Any]:
    if decline == bool(str(candidate_id or "").strip()):
        raise _error(
            "profile_decision_selection_required",
            "Choose exactly one candidate or --decline.",
        )
    cleaned_reason = str(reason or "").strip()
    if not cleaned_reason:
        raise _error("profile_decision_reason_required", "--reason is required.")
    if not str(source_kind or "").strip() or not str(source_ref or "").strip():
        raise _error(
            "profile_decision_source_required",
            "--source-kind and --source-ref are required for human selection provenance.",
        )
    resolved_actor_kind = resolve_actor_kind(actor=actor, actor_kind=actor_kind)
    if resolved_actor_kind != "human":
        raise _error(
            "profile_decision_human_required",
            "Only a human actor can select or decline a Profile proposal.",
        )
    recording = resolve_recording_provenance(
        actor=actor,
        actor_kind=resolved_actor_kind,
        recorded_by=recorded_by,
        recorder_kind=recorder_kind,
        source_kind=source_kind,
        source_ref=source_ref,
        command="pcl decision proposal select",
    )
    shown = show_profile_proposal(paths, decision_id)
    proposal = shown["proposal"]
    selected = DECLINED_ALL_CANDIDATES if decline else str(candidate_id).strip()
    candidate_ids = {str(item["candidate_id"]) for item in proposal["candidates"]}
    if not decline and selected not in candidate_ids:
        raise _error(
            "profile_decision_candidate_missing",
            f"Candidate does not exist in the immutable proposal: {selected}",
        )
    recommended = str(proposal["recommended_candidate_id"])
    cleaned_override = str(override_reason or "").strip()
    if not decline and selected != recommended and not cleaned_override:
        raise _error(
            "profile_decision_override_reason_required",
            "A non-recommended candidate requires --override-reason.",
        )

    conn = connect_mutation(paths)
    try:
        decision = conn.execute(
            "SELECT status, selected_option, reason FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        if decision is None:
            raise _error("profile_decision_missing", f"Decision does not exist: {decision_id}")
        if decision["status"] == "resolved":
            if decision["selected_option"] == selected:
                event = conn.execute(
                    """
                    SELECT id FROM events
                    WHERE event_type = 'profile_decision_selected'
                      AND entity_type = 'decision' AND entity_id = ?
                    ORDER BY sequence LIMIT 1
                    """,
                    (decision_id,),
                ).fetchone()
                conn.rollback()
                return {
                    "ok": True,
                    "changed": False,
                    "replayed": True,
                    "decision_id": decision_id,
                    "selected_option": selected,
                    "event_id": None if event is None else event["id"],
                }
            raise _error(
                "profile_decision_selection_conflict",
                "Proposal Decision was already resolved with another selection.",
            )
        if decision["status"] != "open":
            raise _error(
                "profile_decision_not_open",
                f"Proposal Decision is {decision['status']} and cannot be selected.",
            )
        stored_reason = cleaned_reason
        if cleaned_override:
            stored_reason += f" Override: {cleaned_override}"
        updated = conn.execute(
            """
            UPDATE decisions
            SET status = 'resolved', selected_option = ?, reason = ?, resolved_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (selected, stored_reason, utc_now_iso(), decision_id),
        )
        if updated.rowcount != 1:
            raise _error(
                "profile_decision_selection_conflict",
                "Proposal Decision changed concurrently; retry from pcl decision proposal show.",
            )
        event_id = f"EV-{uuid.uuid4().hex[:12].upper()}"
        receipt = approval_provenance(
            action="profile_decision_selected",
            actor_kind=resolved_actor_kind,
            actor=actor,
            source=recording["source"],
            source_kind=recording["source_kind"],
            source_ref=recording["source_ref"],
            recorder_kind=recording["recorder_kind"],
            recorder=recording["recorder"],
            timestamp=utc_now_iso(),
            target=proposal["target"],
            evidence_id=shown["bundle_evidence_id"],
            artifact_sha256=shown["artifact_sha256"],
            reason=cleaned_reason,
        )
        receipt["event_id"] = event_id
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="profile_decision_selected",
            entity_type="decision",
            entity_id=decision_id,
            event_id=event_id,
            payload={
                "contract_version": PROFILE_DECISION_SELECTED_CONTRACT_VERSION,
                "decision_id": decision_id,
                "proposal_id": proposal["proposal_id"],
                "selected_option": selected,
                "declined": decline,
                "recommended_candidate_id": recommended,
                "override_reason": cleaned_override or None,
                "bundle_evidence_id": shown["bundle_evidence_id"],
                "artifact_sha256": shown["artifact_sha256"],
                "approval_provenance": receipt,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "changed": True,
            "replayed": False,
            "decision_id": decision_id,
            "selected_option": selected,
            "event_id": event_id,
        }
    finally:
        conn.close()


def _error(code: str, message: str, **details: Any) -> ProfileDecisionError:
    return ProfileDecisionError(
        message=message,
        code=code,
        exit_code=EXIT_USAGE,
        details=details,
    )
