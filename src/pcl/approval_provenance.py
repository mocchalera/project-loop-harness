from __future__ import annotations

from typing import Any

from .errors import InvalidInputError


APPROVAL_PROVENANCE_CONTRACT_VERSION = "approval-provenance/v1"
ACTOR_KINDS = {"human", "agent", "system"}
SOURCE_KINDS = {"cli", "conversation", "cockpit", "api"}


def resolve_actor_kind(*, actor: str, actor_kind: str | None) -> str:
    explicit = str(actor_kind or "").strip()
    prefix = actor.partition(":")[0].strip() if ":" in actor else ""
    inferred = prefix if prefix in ACTOR_KINDS else ""
    if explicit and explicit not in ACTOR_KINDS:
        raise InvalidInputError(
            f"Invalid actor kind: {explicit}",
            details={"actor_kind": explicit, "allowed": sorted(ACTOR_KINDS)},
        )
    if explicit and inferred and explicit != inferred:
        raise InvalidInputError(
            "--actor-kind must match the namespace in --actor.",
            details={"actor": actor, "actor_kind": explicit, "inferred_actor_kind": inferred},
        )
    resolved = explicit or inferred
    if not resolved:
        raise InvalidInputError(
            "--actor-kind is required when --actor has no human:, agent:, or system: namespace.",
            details={"actor": actor, "allowed": sorted(ACTOR_KINDS)},
        )
    return resolved


def approval_provenance(
    *,
    action: str,
    actor_kind: str,
    actor: str,
    source: str,
    source_kind: str = "cli",
    source_ref: str = "",
    recorder_kind: str | None = None,
    recorder: str | None = None,
    timestamp: str,
    target: dict[str, str],
    evidence_id: str,
    artifact_sha256: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "contract_version": APPROVAL_PROVENANCE_CONTRACT_VERSION,
        "action": action,
        "actor_kind": actor_kind,
        "actor": actor,
        "recorder_kind": recorder_kind or actor_kind,
        "recorder": recorder or actor,
        "source": source,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "timestamp": timestamp,
        "target": {"type": str(target["type"]), "id": str(target["id"])},
        "bound_evidence": {
            "id": evidence_id,
            "artifact_sha256": artifact_sha256,
        },
        "reason": reason,
    }


def resolve_recording_provenance(
    *,
    actor: str,
    actor_kind: str,
    recorded_by: str | None,
    recorder_kind: str | None,
    source_kind: str | None,
    source_ref: str | None,
    command: str,
) -> dict[str, str]:
    recorder = str(recorded_by or actor).strip()
    resolved_recorder_kind = resolve_actor_kind(
        actor=recorder,
        actor_kind=recorder_kind or (actor_kind if recorder == actor else None),
    )
    resolved_source_kind = str(source_kind or "cli").strip()
    if resolved_source_kind not in SOURCE_KINDS:
        raise InvalidInputError(
            f"Invalid approval source kind: {resolved_source_kind}",
            details={"source_kind": resolved_source_kind, "allowed": sorted(SOURCE_KINDS)},
        )
    resolved_source_ref = str(source_ref or "").strip()
    mediated = recorder != actor or resolved_recorder_kind != actor_kind
    if mediated and resolved_source_kind not in {"conversation", "cockpit"}:
        raise InvalidInputError(
            "Agent/system-mediated human approval requires conversation or cockpit source provenance.",
            details={
                "actor": actor,
                "actor_kind": actor_kind,
                "recorder": recorder,
                "recorder_kind": resolved_recorder_kind,
                "source_kind": resolved_source_kind,
            },
        )
    if resolved_source_kind != "cli" and not resolved_source_ref:
        raise InvalidInputError(
            "--source-ref is required for non-CLI approval provenance.",
            details={"source_kind": resolved_source_kind},
        )
    return {
        "recorder": recorder,
        "recorder_kind": resolved_recorder_kind,
        "source": command if resolved_source_kind == "cli" else resolved_source_kind,
        "source_kind": resolved_source_kind,
        "source_ref": resolved_source_ref,
    }


def provenance_from_event_payload(
    *,
    event_id: str,
    created_at: str,
    payload: dict[str, Any],
    default_action: str,
) -> dict[str, Any] | None:
    value = payload.get("approval_provenance")
    if isinstance(value, dict):
        receipt = dict(value)
    else:
        actor = str(payload.get("actor") or "")
        if not actor:
            return None
        prefix = actor.partition(":")[0] if ":" in actor else ""
        actor_kind = prefix if prefix in ACTOR_KINDS else "human"
        target = payload.get("target")
        if not isinstance(target, dict) or not target.get("type") or not target.get("id"):
            return None
        receipt = approval_provenance(
            action=default_action,
            actor_kind=actor_kind,
            actor=actor,
            source=str(payload.get("source") or "legacy:event"),
            source_kind=str(payload.get("source_kind") or "cli"),
            source_ref=str(payload.get("source_ref") or ""),
            recorder_kind=str(payload.get("recorder_kind") or actor_kind),
            recorder=str(payload.get("recorder") or actor),
            timestamp=created_at,
            target={"type": str(target["type"]), "id": str(target["id"])},
            evidence_id=str(payload.get("evidence_id") or ""),
            artifact_sha256=str(payload.get("artifact_sha256") or ""),
            reason=str(payload.get("reason") or ""),
        )
    receipt.setdefault("recorder_kind", receipt.get("actor_kind"))
    receipt.setdefault("recorder", receipt.get("actor"))
    receipt.setdefault("source_kind", "cli")
    receipt.setdefault("source_ref", "")
    receipt["event_id"] = event_id
    receipt["created_at"] = created_at
    return receipt
