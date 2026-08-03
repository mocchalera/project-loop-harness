from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import importlib.resources
import json
import re
from typing import Any

from ..redaction import redact_value


PROOF_REUSE_CANDIDATE_CONTRACT_VERSION = "proof-reuse-candidate/v1"
PROOF_REUSE_CANDIDATE_RESULT_CONTRACT_VERSION = "proof-reuse-candidate-result/v1"
MAX_CANDIDATE_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = MAX_CANDIDATE_BYTES + 131_072
MAX_PUBLIC_ID_BYTES = 4_096
MAX_PARTICIPANTS = 256
MAX_ROLES = 4_096
MAX_ANCHOR_ROWS = 64

REUSE_CANDIDATE_REASON_STATUS = {
    "source_anchor_authority_corrupt": "invalid",
    "source_anchor_parallel_chain": "invalid",
    "source_authorization_invalid": "invalid",
    "source_anchor_exhaustion_pending": "unavailable",
    "source_anchor_exhaustion_tombstoned": "unavailable",
    "source_anchor_not_current": "unavailable",
    "source_anchor_not_found": "unavailable",
    "source_current_proof_changed": "unavailable",
    "source_live_basis_changed": "unavailable",
    "source_anchor_recovery_required": "withheld",
    "source_anchor_unhealthy": "withheld",
    "source_reuse_forbidden": "withheld",
    "source_role_coverage_incomplete": "withheld",
    "source_verdict_not_passed": "withheld",
    "source_output_uncommitted": "withheld",
    "source_effect_not_read_only": "withheld",
    "source_declared_outputs_present": "withheld",
    "source_private_identity": "withheld",
}
REUSE_CANDIDATE_REASON_CODES = tuple(sorted(REUSE_CANDIDATE_REASON_STATUS))
REUSE_CANDIDATE_STATUS_RANK = {
    "recordable": 0,
    "withheld": 1,
    "unavailable": 2,
    "invalid": 3,
}
REUSE_CANDIDATE_HARD_ERROR_CODES = (
    "reuse_candidate_input_type_invalid",
    "reuse_candidate_contract_invalid",
    "reuse_candidate_capacity_exceeded",
    "reuse_candidate_secret_shaped_identifier",
    "reuse_candidate_platform_unsupported",
    "reuse_candidate_lock_unavailable",
    "reuse_candidate_lock_identity_invalid",
    "reuse_candidate_database_schema_unsupported",
    "reuse_candidate_projection_pending",
    "reuse_candidate_idempotency_conflict",
    "reuse_candidate_store_invalid",
    "reuse_candidate_live_domain_error",
    "reuse_candidate_internal_error",
)
REUSE_CANDIDATE_ERROR_PHASES = (
    "preflight",
    "lock",
    "authority",
    "live",
    "identity",
    "replay",
    "publication",
    "transaction",
    "final_guard",
    "projection",
    "postcommit",
    "cleanup",
)

REUSE_CANDIDATE_AUTHORIZATION = {
    "candidate_recorded": True,
    "reuse_authorized": False,
    "direct_input_right": False,
    "check_skip_authorized": False,
    "result_substitution_authorized": False,
    "terminal_authority": False,
    "lifecycle_authority": False,
    "mandatory_evidence": False,
    "promotion_authorized": False,
    "publication_authorized": False,
}
REUSE_CANDIDATE_HANDOFF = {
    "status": "durable_candidate",
    "consumer_enabled": False,
    "separate_authorization_required": True,
}
REUSE_CANDIDATE_EFFECTS_SUCCESS = {
    "schema_version": 8,
    "migrations_applied": 0,
    "dependencies_added": 0,
    "evidence_rows_inserted": 1,
    "evidence_links_inserted": 1,
    "events_appended": 1,
    "outbox_records_appended": 1,
    "directories_published": 1,
    "rows_updated": 0,
    "rows_deleted": 0,
    "rendered": 0,
    "lifecycle_transitions": 0,
    "network_requests": 0,
}
REUSE_CANDIDATE_EFFECTS_ZERO = {
    **REUSE_CANDIDATE_EFFECTS_SUCCESS,
    "evidence_rows_inserted": 0,
    "evidence_links_inserted": 0,
    "events_appended": 0,
    "outbox_records_appended": 0,
    "directories_published": 0,
}

_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_CANDIDATE_ID = re.compile(r"^PRC-[0-9A-F]{64}$")
_EVENT_ID = re.compile(r"^EV-[0-9A-F]{64}$")
_EVIDENCE_ID = re.compile(r"^E-[0-9A-Z]+$")
_OUTBOX_ID = re.compile(r"^OB-[0-9A-F]{64}$")
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,4095}$")
_OID = re.compile(r"^[0-9a-f]+$")


@dataclass(frozen=True)
class ProofReuseCandidateValidationResult:
    contract_version: str
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "ok": self.ok,
            "errors": list(self.errors),
        }


def proof_reuse_candidate_schema() -> dict[str, Any]:
    return _schema("proof-reuse-candidate-v1.schema.json")


def proof_reuse_candidate_result_schema() -> dict[str, Any]:
    return _schema("proof-reuse-candidate-result-v1.schema.json")


def canonical_proof_reuse_candidate_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _json_ready(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Proof-reuse candidate canonical JSON is invalid.") from exc


def domain_sha256(domain: str, value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        b"pcl:" + domain.encode("utf-8") + b"\0" + canonical_proof_reuse_candidate_bytes(value)
    ).hexdigest()


def proof_reuse_candidate_id(value: Mapping[str, Any]) -> str:
    source = value.get("source")
    current = value.get("current_proof")
    if not isinstance(source, Mapping) or not isinstance(current, Mapping):
        raise ValueError("Candidate identity inputs are invalid.")
    identity = {
        "anchor_event_id": source.get("anchor_event_id"),
        "anchor_generation": source.get("anchor_generation"),
        "basis_sha256": source.get("basis_sha256"),
        "current_proof_sha256": current.get("proof_sha256"),
        "normalized_role_projection": _json_ready(value.get("roles")),
    }
    digest = domain_sha256("proof-reuse-candidate-id/v1", identity)[7:]
    return "PRC-" + digest.upper()


def proof_reuse_candidate_sha256(value: Mapping[str, Any]) -> str:
    return domain_sha256(
        PROOF_REUSE_CANDIDATE_CONTRACT_VERSION,
        _without(value, "candidate_sha256"),
    )


def proof_reuse_candidate_result_sha256(value: Mapping[str, Any]) -> str:
    return domain_sha256(
        PROOF_REUSE_CANDIDATE_RESULT_CONTRACT_VERSION,
        _without(value, "result_sha256"),
    )


def finalize_proof_reuse_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _json_ready(value)
    if not isinstance(result, dict):
        raise TypeError("Proof-reuse candidate must be an object.")
    result["candidate_id"] = proof_reuse_candidate_id(result)
    result["candidate_sha256"] = proof_reuse_candidate_sha256(result)
    return result


def finalize_proof_reuse_candidate_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _json_ready(value)
    if not isinstance(result, dict):
        raise TypeError("Proof-reuse candidate result must be an object.")
    result["result_sha256"] = proof_reuse_candidate_result_sha256(result)
    return result


def validate_proof_reuse_candidate(value: Any) -> ProofReuseCandidateValidationResult:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return _result(PROOF_REUSE_CANDIDATE_CONTRACT_VERSION, ["candidate must be an object"])
    try:
        encoded = canonical_proof_reuse_candidate_bytes(value)
    except ValueError:
        return _result(PROOF_REUSE_CANDIDATE_CONTRACT_VERSION, ["candidate must be canonical JSON"])
    if len(encoded) > MAX_CANDIDATE_BYTES:
        errors.append("candidate exceeds canonical byte cap")
    _exact(
        value,
        {
            "contract_version",
            "candidate_id",
            "source",
            "observation",
            "target",
            "candidate",
            "current_proof",
            "roles",
            "authorization",
            "handoff",
            "effects",
            "candidate_sha256",
        },
        "candidate",
        errors,
    )
    if value.get("contract_version") != PROOF_REUSE_CANDIDATE_CONTRACT_VERSION:
        errors.append("candidate contract_version is invalid")
    _validate_source(value.get("source"), errors)
    _validate_observation(value.get("observation"), value.get("source"), errors)
    _validate_target(value.get("target"), errors)
    _validate_git_candidate(value.get("candidate"), errors)
    _validate_current_proof(value.get("current_proof"), errors)
    _validate_roles(value.get("roles"), errors)
    if value.get("authorization") != REUSE_CANDIDATE_AUTHORIZATION:
        errors.append("authorization must be the C7 const object")
    if value.get("handoff") != REUSE_CANDIDATE_HANDOFF:
        errors.append("handoff must be the C7 const object")
    if value.get("effects") != REUSE_CANDIDATE_EFFECTS_SUCCESS:
        errors.append("effects must be the C7 success const object")
    if not _CANDIDATE_ID.fullmatch(str(value.get("candidate_id") or "")):
        errors.append("candidate_id is invalid")
    else:
        try:
            if value["candidate_id"] != proof_reuse_candidate_id(value):
                errors.append("candidate_id mismatch")
        except (TypeError, ValueError):
            errors.append("candidate_id cannot be computed")
    if not _is_sha(value.get("candidate_sha256")):
        errors.append("candidate_sha256 is invalid")
    else:
        try:
            if value["candidate_sha256"] != proof_reuse_candidate_sha256(value):
                errors.append("candidate_sha256 mismatch")
        except (TypeError, ValueError):
            errors.append("candidate_sha256 cannot be computed")
    _sensitive(value, "candidate", errors)
    return _result(PROOF_REUSE_CANDIDATE_CONTRACT_VERSION, errors)


def validate_proof_reuse_candidate_result(value: Any) -> ProofReuseCandidateValidationResult:
    errors: list[str] = []
    version = PROOF_REUSE_CANDIDATE_RESULT_CONTRACT_VERSION
    if not isinstance(value, Mapping):
        return _result(version, ["result must be an object"])
    try:
        encoded = canonical_proof_reuse_candidate_bytes(value)
    except ValueError:
        return _result(version, ["result must be canonical JSON"])
    if len(encoded) > MAX_RESULT_BYTES:
        errors.append("result exceeds canonical byte cap")
    _exact(
        value,
        {
            "contract_version",
            "ok",
            "status",
            "status_rank",
            "changed",
            "idempotent",
            "mutation_committed",
            "safe_to_retry_original",
            "candidate_id",
            "candidate",
            "reason_codes",
            "projection",
            "outbox_delivery",
            "health",
            "effects",
            "result_sha256",
        },
        "result",
        errors,
    )
    if value.get("contract_version") != version:
        errors.append("result contract_version is invalid")
    status = value.get("status")
    if status not in REUSE_CANDIDATE_STATUS_RANK:
        errors.append("status is invalid")
    elif value.get("status_rank") != REUSE_CANDIDATE_STATUS_RANK[status]:
        errors.append("status_rank mismatch")
    for name in (
        "ok",
        "changed",
        "idempotent",
        "mutation_committed",
        "safe_to_retry_original",
    ):
        if type(value.get(name)) is not bool:
            errors.append(f"{name} must be boolean")
    candidate_value = value.get("candidate")
    candidate_id_value = value.get("candidate_id")
    if candidate_value is None:
        if candidate_id_value is not None:
            errors.append("candidate_id must be null without candidate")
    else:
        validation = validate_proof_reuse_candidate(candidate_value)
        if not validation.ok:
            errors.append("candidate is invalid")
        if not _CANDIDATE_ID.fullmatch(str(candidate_id_value or "")):
            errors.append("candidate_id is invalid")
        elif candidate_value.get("candidate_id") != candidate_id_value:
            errors.append("candidate_id does not match candidate")
    reasons = value.get("reason_codes")
    if (
        not isinstance(reasons, list)
        or reasons != sorted(set(reasons))
        or any(reason not in REUSE_CANDIDATE_REASON_STATUS for reason in reasons)
    ):
        errors.append("reason_codes must be closed sorted unique")
        reasons = []
    projection = value.get("projection")
    _validate_projection(projection, errors)
    if value.get("outbox_delivery") not in {
        "not_applicable",
        "pending",
        "delivered",
        "failed_needs_review",
    }:
        errors.append("outbox_delivery is invalid")
    _validate_health(value.get("health"), errors)
    if value.get("effects") not in (
        REUSE_CANDIDATE_EFFECTS_SUCCESS,
        REUSE_CANDIDATE_EFFECTS_ZERO,
    ):
        errors.append("effects are invalid")
    if status in REUSE_CANDIDATE_STATUS_RANK:
        _validate_result_profile(value, status, reasons, errors)
    if not _is_sha(value.get("result_sha256")):
        errors.append("result_sha256 is invalid")
    else:
        try:
            if value["result_sha256"] != proof_reuse_candidate_result_sha256(value):
                errors.append("result_sha256 mismatch")
        except (TypeError, ValueError):
            errors.append("result_sha256 cannot be computed")
    _sensitive(value, "result", errors)
    return _result(version, errors)


def status_for_reasons(reasons: Sequence[str]) -> str:
    if not reasons:
        return "recordable"
    statuses = [REUSE_CANDIDATE_REASON_STATUS[reason] for reason in reasons]
    return max(statuses, key=REUSE_CANDIDATE_STATUS_RANK.__getitem__)


def _validate_source(value: Any, errors: list[str]) -> None:
    fields = {
        "anchor_event_id",
        "anchor_event_sequence",
        "anchor_generation",
        "anchor_sha256",
        "manifest_file_sha256",
        "basis_sha256",
        "policy_sha256",
        "coverage_group_sha256",
        "admission_sha256",
    }
    if not isinstance(value, Mapping):
        errors.append("source must be an object")
        return
    _exact(value, fields, "source", errors)
    if not _EVENT_ID.fullmatch(str(value.get("anchor_event_id") or "")):
        errors.append("source.anchor_event_id is invalid")
    if type(value.get("anchor_event_sequence")) is not int or value["anchor_event_sequence"] < 1:
        errors.append("source.anchor_event_sequence is invalid")
    if type(value.get("anchor_generation")) is not int or not 0 <= value["anchor_generation"] <= 3:
        errors.append("source.anchor_generation is invalid")
    for name in fields - {"anchor_event_id", "anchor_event_sequence", "anchor_generation"}:
        if not _is_sha(value.get(name)):
            errors.append(f"source.{name} is invalid")


def _validate_observation(value: Any, source: Any, errors: list[str]) -> None:
    fields = {
        "observed_through_event_sequence",
        "observed_through_event_id",
        "observed_through_anchor_event_id",
    }
    if not isinstance(value, Mapping):
        errors.append("observation must be an object")
        return
    _exact(value, fields, "observation", errors)
    sequence = value.get("observed_through_event_sequence")
    if type(sequence) is not int or sequence < 1:
        errors.append("observation sequence is invalid")
    if not _public_id(value.get("observed_through_event_id")):
        errors.append("observation event id is invalid")
    if not _EVENT_ID.fullmatch(str(value.get("observed_through_anchor_event_id") or "")):
        errors.append("observation anchor id is invalid")
    if isinstance(source, Mapping):
        if type(sequence) is int and sequence < int(source.get("anchor_event_sequence") or 0):
            errors.append("observation precedes anchor")
        if value.get("observed_through_anchor_event_id") != source.get("anchor_event_id"):
            errors.append("observation anchor mismatch")


def _validate_target(value: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("target must be an object")
        return
    _exact(value, {"type", "id"}, "target", errors)
    if value.get("type") != "task" or not _public_id(value.get("id")):
        errors.append("target is invalid")


def _validate_git_candidate(value: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("candidate Git identity must be an object")
        return
    _exact(value, {"object_format", "commit_oid", "tree_oid"}, "git_candidate", errors)
    object_format = value.get("object_format")
    width = 40 if object_format == "sha1" else 64 if object_format == "sha256" else 0
    if not width:
        errors.append("candidate object_format is invalid")
    for name in ("commit_oid", "tree_oid"):
        item = value.get(name)
        if not isinstance(item, str) or len(item) != width or not _OID.fullmatch(item):
            errors.append(f"candidate {name} is invalid")


def _validate_current_proof(value: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("current_proof must be an object")
        return
    _exact(value, {"scope", "status", "match_status", "proof_sha256"}, "current_proof", errors)
    if value.get("scope") != "feature":
        errors.append("current_proof.scope must be feature")
    if value.get("status") != "healthy":
        errors.append("current_proof.status must be healthy")
    if value.get("match_status") != "matched":
        errors.append("current_proof.match_status must be matched")
    if not _is_sha(value.get("proof_sha256")):
        errors.append("current_proof.proof_sha256 is invalid")


def _validate_roles(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ROLES:
        errors.append("roles must contain 1..4096 objects")
        return
    expected_fields = {
        "role",
        "kind",
        "canary_id",
        "requirement_sha256",
        "participant_sha256",
        "check_id",
        "plan_sha256",
        "tool_identity_sha256",
        "public_execution_sha256",
        "spawn_vector_sha256",
        "external_input_binding_sha256",
        "execution_binding_sha256",
        "packet_sha256",
        "final_authority_checkpoint_sha256",
        "result_sha256",
        "receipt_sha256",
        "aggregate_sha256",
        "bundle_sha256",
        "verdict",
        "output_commitment_status",
        "effect_classification",
    }
    sort_keys: list[tuple[str, str, str, str]] = []
    for index, role in enumerate(value):
        path = f"roles[{index}]"
        if not isinstance(role, Mapping):
            errors.append(f"{path} must be an object")
            continue
        _exact(role, expected_fields, path, errors)
        for name in ("role", "kind", "check_id"):
            if not _public_id(role.get(name)):
                errors.append(f"{path}.{name} is invalid")
        canary = role.get("canary_id")
        if canary is not None and not _public_id(canary):
            errors.append(f"{path}.canary_id is invalid")
        for name in expected_fields - {
            "role",
            "kind",
            "canary_id",
            "check_id",
            "verdict",
            "output_commitment_status",
            "effect_classification",
        }:
            if not _is_sha(role.get(name)):
                errors.append(f"{path}.{name} is invalid")
        if role.get("verdict") != "passed":
            errors.append(f"{path}.verdict must be passed")
        if role.get("output_commitment_status") != "committed":
            errors.append(f"{path}.output_commitment_status must be committed")
        if role.get("effect_classification") != "read_only":
            errors.append(f"{path}.effect_classification must be read_only")
        sort_keys.append(
            (
                str(role.get("kind") or ""),
                str(role.get("role") or ""),
                str(role.get("check_id") or ""),
                str(role.get("participant_sha256") or ""),
            )
        )
    if sort_keys != sorted(sort_keys) or len(sort_keys) != len(set(sort_keys)):
        errors.append("roles must be sorted and unique")


def _validate_projection(value: Any, errors: list[str]) -> None:
    fields = {"status", "evidence_id", "event_id", "event_sequence", "outbox_id", "artifact_id"}
    if not isinstance(value, Mapping):
        errors.append("projection must be an object")
        return
    _exact(value, fields, "projection", errors)
    status = value.get("status")
    if status not in {"none", "committed", "replayed"}:
        errors.append("projection status is invalid")
        return
    identifiers = {
        "evidence_id": _EVIDENCE_ID,
        "event_id": _EVENT_ID,
        "outbox_id": _OUTBOX_ID,
        "artifact_id": _CANDIDATE_ID,
    }
    if status == "none":
        if any(value.get(name) is not None for name in fields - {"status"}):
            errors.append("none projection identifiers must be null")
        return
    for name, pattern in identifiers.items():
        if not pattern.fullmatch(str(value.get(name) or "")):
            errors.append(f"projection {name} is invalid")
    if type(value.get("event_sequence")) is not int or value["event_sequence"] < 1:
        errors.append("projection event_sequence is invalid")


def _validate_health(value: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("health must be an object")
        return
    _exact(value, {"source_anchor", "candidate_artifact", "postcommit_checked"}, "health", errors)
    if value.get("source_anchor") not in {
        "invalid",
        "unavailable",
        "recovery_required",
        "unhealthy",
        "healthy",
    }:
        errors.append("health.source_anchor is invalid")
    if value.get("candidate_artifact") not in {
        "not_applicable",
        "healthy",
        "postcommit_unhealthy",
    }:
        errors.append("health.candidate_artifact is invalid")
    if type(value.get("postcommit_checked")) is not bool:
        errors.append("health.postcommit_checked must be boolean")


def _validate_result_profile(
    value: Mapping[str, Any],
    status: str,
    reasons: Sequence[str],
    errors: list[str],
) -> None:
    if status != "recordable":
        expected_status = status_for_reasons(reasons) if reasons else None
        if not reasons or expected_status != status:
            errors.append("non-recordable status/reasons mismatch")
        expected = {
            "ok": False,
            "changed": False,
            "idempotent": False,
            "mutation_committed": False,
            "safe_to_retry_original": True,
            "candidate_id": None,
            "candidate": None,
            "effects": REUSE_CANDIDATE_EFFECTS_ZERO,
            "outbox_delivery": "not_applicable",
        }
        for name, item in expected.items():
            if value.get(name) != item:
                errors.append(f"non-recordable {name} mismatch")
        if isinstance(value.get("projection"), Mapping) and value["projection"].get("status") != "none":
            errors.append("non-recordable projection must be none")
        if isinstance(value.get("health"), Mapping):
            if value["health"].get("candidate_artifact") != "not_applicable":
                errors.append("non-recordable candidate health mismatch")
            if value["health"].get("postcommit_checked") is not False:
                errors.append("non-recordable postcommit flag mismatch")
        return
    if reasons:
        errors.append("recordable reasons must be empty")
    candidate = value.get("candidate")
    if candidate is None:
        errors.append("recordable candidate must be present")
        return
    projection = value.get("projection")
    projection_status = projection.get("status") if isinstance(projection, Mapping) else None
    artifact_health = value.get("health", {}).get("candidate_artifact") if isinstance(value.get("health"), Mapping) else None
    if value.get("health", {}).get("source_anchor") != "healthy":
        errors.append("recordable source anchor must be healthy")
    if value.get("health", {}).get("postcommit_checked") is not True:
        errors.append("recordable postcommit flag must be true")
    if projection_status == "replayed":
        expected = {
            "ok": True,
            "changed": False,
            "idempotent": True,
            "mutation_committed": False,
            "safe_to_retry_original": True,
            "effects": REUSE_CANDIDATE_EFFECTS_ZERO,
        }
        if artifact_health != "healthy":
            errors.append("replay artifact must be healthy")
    elif projection_status == "committed":
        expected = {
            "ok": artifact_health == "healthy",
            "changed": True,
            "idempotent": False,
            "mutation_committed": True,
            "safe_to_retry_original": False,
            "effects": REUSE_CANDIDATE_EFFECTS_SUCCESS,
        }
        if artifact_health not in {"healthy", "postcommit_unhealthy"}:
            errors.append("committed artifact health is invalid")
    else:
        errors.append("recordable projection must be committed or replayed")
        return
    for name, item in expected.items():
        if value.get(name) != item:
            errors.append(f"recordable {name} mismatch")
    if value.get("outbox_delivery") == "not_applicable":
        errors.append("recordable outbox delivery cannot be not_applicable")


def _sensitive(value: Any, path: str, errors: list[str]) -> None:
    redacted, changed = redact_value(_json_ready(value))
    del redacted
    if changed:
        errors.append(f"{path} contains a secret-shaped value")


def _exact(value: Mapping[str, Any], expected: set[str], path: str, errors: list[str]) -> None:
    actual = set(value)
    if actual != expected:
        errors.append(f"{path} fields differ: missing={sorted(expected - actual)} extra={sorted(actual - expected)}")


def _public_id(value: Any) -> bool:
    return isinstance(value, str) and len(value.encode("utf-8")) <= MAX_PUBLIC_ID_BYTES and bool(_PUBLIC_ID.fullmatch(value))


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA.fullmatch(value))


def _without(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = _json_ready(value)
    if not isinstance(result, dict):
        raise TypeError("Expected object.")
    result.pop(field, None)
    return result


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _schema(resource: str) -> dict[str, Any]:
    path = importlib.resources.files("pcl.contracts.schemas").joinpath(resource)
    return json.loads(path.read_text(encoding="utf-8"))


def _result(version: str, errors: Sequence[str]) -> ProofReuseCandidateValidationResult:
    return ProofReuseCandidateValidationResult(version, tuple(errors))


__all__ = [
    "MAX_ANCHOR_ROWS",
    "MAX_CANDIDATE_BYTES",
    "MAX_PARTICIPANTS",
    "MAX_PUBLIC_ID_BYTES",
    "MAX_ROLES",
    "PROOF_REUSE_CANDIDATE_CONTRACT_VERSION",
    "PROOF_REUSE_CANDIDATE_RESULT_CONTRACT_VERSION",
    "REUSE_CANDIDATE_AUTHORIZATION",
    "REUSE_CANDIDATE_EFFECTS_SUCCESS",
    "REUSE_CANDIDATE_EFFECTS_ZERO",
    "REUSE_CANDIDATE_ERROR_PHASES",
    "REUSE_CANDIDATE_HANDOFF",
    "REUSE_CANDIDATE_HARD_ERROR_CODES",
    "REUSE_CANDIDATE_REASON_CODES",
    "REUSE_CANDIDATE_REASON_STATUS",
    "REUSE_CANDIDATE_STATUS_RANK",
    "ProofReuseCandidateValidationResult",
    "canonical_proof_reuse_candidate_bytes",
    "domain_sha256",
    "finalize_proof_reuse_candidate",
    "finalize_proof_reuse_candidate_result",
    "proof_reuse_candidate_id",
    "proof_reuse_candidate_result_schema",
    "proof_reuse_candidate_result_sha256",
    "proof_reuse_candidate_schema",
    "proof_reuse_candidate_sha256",
    "status_for_reasons",
    "validate_proof_reuse_candidate",
    "validate_proof_reuse_candidate_result",
]
