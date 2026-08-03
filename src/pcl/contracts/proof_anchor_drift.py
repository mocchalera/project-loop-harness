from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import importlib.resources
import json
import re
from typing import Any

from ..redaction import redact_value


PROOF_ANCHOR_DRIFT_SUBJECT_CONTRACT_VERSION = "proof-anchor-drift-subject/v1"
PROOF_ANCHOR_DRIFT_ELIGIBILITY_CONTRACT_VERSION = "proof-anchor-drift-eligibility/v1"
MAX_RECEIPT_BYTES = 131_072
MAX_SUBJECT_BYTES = 16_384
MAX_PUBLIC_ID_BYTES = 4_096
MAX_REASONS = 32
MAX_ANCHOR_ROWS = 64
MAX_PARTICIPANTS = 256
MAX_CHECKS = 4_096

DRIFT_REASON_CODES = tuple(
    sorted(
        (
            "anchor_actor_independence_changed",
            "anchor_authority_corrupt",
            "anchor_authorization_document_invalid",
            "anchor_basis_mismatch",
            "anchor_candidate_mismatch",
            "anchor_exhaustion_pending",
            "anchor_exhaustion_tombstoned",
            "anchor_not_current_head",
            "anchor_not_found",
            "anchor_parallel_chain_conflict",
            "anchor_recovery_required",
            "anchor_target_mismatch",
            "computed_verdict_not_passed",
            "live_authority_changed",
            "live_basis_mismatch",
            "live_canary_changed",
            "live_candidate_changed",
            "live_chain_unavailable",
            "live_current_proof_changed",
            "live_execution_binding_changed",
            "live_policy_changed",
            "live_reconstruction_indeterminate",
        )
    )
)

DRIFT_HARD_ERROR_CODES = (
    "drift_input_type_invalid",
    "drift_contract_invalid",
    "drift_capacity_exceeded",
    "drift_secret_shaped_identifier",
    "drift_platform_unsupported",
    "drift_lock_unavailable",
    "drift_lock_identity_invalid",
    "drift_snapshot_unavailable",
    "drift_database_recovery_required",
    "drift_database_journal_mode_unsupported",
    "drift_database_schema_unsupported",
    "drift_live_domain_error",
    "drift_internal_error",
)

DRIFT_ERROR_PHASES = (
    "preflight",
    "lock",
    "snapshot",
    "authority",
    "live",
    "receipt",
    "cleanup",
)

DRIFT_EFFECTS = {
    "schema_version": 8,
    "migrations_applied": 0,
    "dependencies_added": 0,
    "database_read_only_transaction": True,
    "shared_existing_lock_acquired": True,
    "filesystem_reads": True,
    "filesystem_read_effect_class": "non_authoritative_atime_page_cache_only",
    "database_writes": 0,
    "filesystem_authoritative_writes": 0,
    "evidence_rows_inserted": 0,
    "evidence_links_inserted": 0,
    "events_appended": 0,
    "outbox_records_appended": 0,
    "directories_published": 0,
    "rendered": 0,
    "checks_executed": 0,
    "checks_skipped": 0,
    "results_substituted": 0,
    "lifecycle_transitions": 0,
    "network_requests": 0,
    "telemetry_records": 0,
    "publications": 0,
}

_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVENT_ID = re.compile(r"^EV-[0-9A-F]{64}$")
_REQUEST_ID = re.compile(r"^PA-[0-9A-F]{64}$")
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,4095}$")
_HEX = re.compile(r"^[0-9a-f]+$")


@dataclass(frozen=True)
class ProofAnchorDriftValidationResult:
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


def proof_anchor_drift_eligibility_schema() -> dict[str, Any]:
    resource = importlib.resources.files("pcl.contracts.schemas").joinpath(
        "proof-anchor-drift-eligibility-v1.schema.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def canonical_proof_anchor_drift_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _json_ready(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Proof-anchor drift canonical JSON is invalid.") from exc


def _domain_sha256(domain: str, value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        b"pcl:" + domain.encode("utf-8") + b"\0" + canonical_proof_anchor_drift_bytes(value)
    ).hexdigest()


def subject_sha256(value: Mapping[str, Any]) -> str:
    return _domain_sha256(
        PROOF_ANCHOR_DRIFT_SUBJECT_CONTRACT_VERSION,
        _without(value, "subject_sha256"),
    )


def eligibility_sha256(value: Mapping[str, Any]) -> str:
    return _domain_sha256(
        PROOF_ANCHOR_DRIFT_ELIGIBILITY_CONTRACT_VERSION,
        _without(value, "eligibility_sha256"),
    )


def finalize_proof_anchor_drift_eligibility(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _json_ready(value)
    if not isinstance(result, dict):
        raise TypeError("Proof-anchor drift receipt must be an object.")
    subject = result.get("subject")
    if isinstance(subject, dict):
        subject["subject_sha256"] = subject_sha256(subject)
    result["eligibility_sha256"] = eligibility_sha256(result)
    return result


def validate_proof_anchor_drift_eligibility(value: Any) -> ProofAnchorDriftValidationResult:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return _result(["receipt must be an object"])
    try:
        encoded = canonical_proof_anchor_drift_bytes(value)
    except ValueError:
        return _result(["receipt must be canonical JSON"])
    if len(encoded) > MAX_RECEIPT_BYTES:
        errors.append("receipt exceeds canonical byte cap")
    _exact_fields(
        value,
        {
            "contract_version",
            "subject",
            "anchor",
            "observation",
            "eligibility",
            "reason_codes",
            "authorization_status",
            "handoff",
            "effects",
            "eligibility_sha256",
        },
        "receipt",
        errors,
    )
    if value.get("contract_version") != PROOF_ANCHOR_DRIFT_ELIGIBILITY_CONTRACT_VERSION:
        errors.append("receipt contract_version is invalid")
    _validate_subject(value.get("subject"), errors)
    _validate_anchor(value.get("anchor"), errors)
    _validate_observation(value.get("observation"), value.get("anchor"), errors)
    _validate_eligibility(value.get("eligibility"), value.get("reason_codes"), errors)
    _validate_authorization(value.get("authorization_status"), errors)
    _validate_handoff(value.get("handoff"), errors)
    if value.get("effects") != DRIFT_EFFECTS:
        errors.append("effects must be the C6 effect-zero object")
    if not _is_sha(value.get("eligibility_sha256")):
        errors.append("eligibility_sha256 is invalid")
    else:
        try:
            if value["eligibility_sha256"] != eligibility_sha256(value):
                errors.append("eligibility_sha256 mismatch")
        except (TypeError, ValueError):
            errors.append("eligibility_sha256 cannot be computed")
    redacted, changed = redact_value(_json_ready(value))
    del redacted
    if changed:
        errors.append("receipt contains a secret-shaped value")
    return _result(errors)


def _validate_subject(value: Any, errors: list[str]) -> None:
    fields = {
        "contract_version",
        "project_instance_id",
        "target",
        "candidate",
        "expected_basis_sha256",
        "anchor_event_id",
        "requested_use",
        "subject_sha256",
    }
    if not isinstance(value, Mapping):
        errors.append("subject must be an object")
        return
    _exact_fields(value, fields, "subject", errors)
    try:
        if len(canonical_proof_anchor_drift_bytes(value)) > MAX_SUBJECT_BYTES:
            errors.append("subject exceeds canonical byte cap")
    except ValueError:
        errors.append("subject canonical JSON is invalid")
    if value.get("contract_version") != PROOF_ANCHOR_DRIFT_SUBJECT_CONTRACT_VERSION:
        errors.append("subject contract_version is invalid")
    if not _public_id(value.get("project_instance_id")):
        errors.append("project_instance_id is invalid")
    target = value.get("target")
    if not isinstance(target, Mapping):
        errors.append("subject target must be an object")
    else:
        _exact_fields(target, {"type", "id"}, "subject target", errors)
        if target.get("type") != "task" or not _public_id(target.get("id")):
            errors.append("subject target is invalid")
    _validate_candidate(value.get("candidate"), "subject candidate", errors)
    if not _is_sha(value.get("expected_basis_sha256")):
        errors.append("expected_basis_sha256 is invalid")
    if not _event_id(value.get("anchor_event_id")):
        errors.append("anchor_event_id is invalid")
    if value.get("requested_use") != "drift_eligibility_predicate":
        errors.append("requested_use is invalid")
    if not _is_sha(value.get("subject_sha256")):
        errors.append("subject_sha256 is invalid")
    else:
        try:
            if value["subject_sha256"] != subject_sha256(value):
                errors.append("subject_sha256 mismatch")
        except (TypeError, ValueError):
            errors.append("subject_sha256 cannot be computed")


def _validate_anchor(value: Any, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        errors.append("anchor must be an object or null")
        return
    fields = {
        "event_id",
        "event_sequence",
        "request_id",
        "base_request_sha256",
        "anchor_generation",
        "basis_sha256",
        "anchor_sha256",
        "manifest_file_sha256",
        "evidence_id",
        "health_status",
        "chain_head",
    }
    _exact_fields(value, fields, "anchor", errors)
    if not _event_id(value.get("event_id")):
        errors.append("anchor event_id is invalid")
    if not _integer(value.get("event_sequence"), 1, 2**63 - 1):
        errors.append("anchor event_sequence is invalid")
    if not isinstance(value.get("request_id"), str) or not _REQUEST_ID.fullmatch(
        value["request_id"]
    ):
        errors.append("anchor request_id is invalid")
    for field in (
        "base_request_sha256",
        "basis_sha256",
        "anchor_sha256",
        "manifest_file_sha256",
    ):
        if not _is_sha(value.get(field)):
            errors.append(f"anchor {field} is invalid")
    if not _integer(value.get("anchor_generation"), 0, 3):
        errors.append("anchor_generation is invalid")
    if not _public_id(value.get("evidence_id")):
        errors.append("anchor evidence_id is invalid")
    if value.get("health_status") not in {"healthy", "postcommit_unhealthy"}:
        errors.append("anchor health_status is invalid")
    if value.get("chain_head") not in {True, None}:
        errors.append("anchor chain_head is invalid")


def _validate_observation(value: Any, anchor: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("observation must be an object")
        return
    _exact_fields(value, {"snapshot", "chain", "stored", "live"}, "observation", errors)
    snapshot = value.get("snapshot")
    if not isinstance(snapshot, Mapping):
        errors.append("snapshot must be an object")
    else:
        _exact_fields(
            snapshot,
            {"schema_version", "evaluated_through_event_sequence", "evaluated_through_event_id"},
            "snapshot",
            errors,
        )
        if snapshot.get("schema_version") != 8:
            errors.append("snapshot schema_version is invalid")
        sequence = snapshot.get("evaluated_through_event_sequence")
        event_id = snapshot.get("evaluated_through_event_id")
        if not _integer(sequence, 0, 2**63 - 1):
            errors.append("snapshot sequence is invalid")
        elif (sequence == 0) != (event_id is None):
            errors.append("snapshot HWM nullability is invalid")
        if event_id is not None and not _public_id(event_id):
            errors.append("snapshot event ID is invalid")
    chain = value.get("chain")
    if not isinstance(chain, Mapping):
        errors.append("chain must be an object")
    else:
        _validate_chain(chain, anchor, errors)
    stored = value.get("stored")
    if not isinstance(stored, Mapping):
        errors.append("stored must be an object")
    else:
        _exact_fields(
            stored,
            {
                "basis_document_status",
                "authorization_documents_status",
                "recorded_actor_independence",
                "anchor_authorization_granted",
                "issuer_capability_validation",
            },
            "stored",
            errors,
        )
        if stored.get("basis_document_status") not in {"valid", "invalid", "unavailable"}:
            errors.append("stored basis status is invalid")
        if stored.get("authorization_documents_status") not in {
            "valid",
            "invalid",
            "unavailable",
        }:
            errors.append("stored authorization status is invalid")
        if stored.get("recorded_actor_independence") not in {
            "matched",
            "mismatched",
            "not_observed",
        }:
            errors.append("recorded actor independence is invalid")
        if stored.get("anchor_authorization_granted") not in {True, None}:
            errors.append("anchor_authorization_granted is invalid")
        if stored.get("issuer_capability_validation") != "write_time_only_not_reconstituted":
            errors.append("issuer capability status is invalid")
    live = value.get("live")
    if not isinstance(live, Mapping):
        errors.append("live must be an object")
    else:
        _validate_live(live, errors)


def _validate_chain(value: Mapping[str, Any], anchor: Any, errors: list[str]) -> None:
    _exact_fields(
        value,
        {
            "valid_chain_count",
            "malformed_group_present",
            "tombstone_status",
            "tombstone_event_id",
            "exhaustion_witness_status",
            "selected_head_event_id",
            "selected_head_generation",
        },
        "chain",
        errors,
    )
    tombstone = value.get("tombstone_status")
    if tombstone not in {"absent", "valid", "invalid", "multiple"}:
        errors.append("tombstone_status is invalid")
        return
    non_absent = tombstone in {"valid", "invalid", "multiple"}
    valid_count = value.get("valid_chain_count")
    malformed = value.get("malformed_group_present")
    if non_absent:
        if valid_count is not None or malformed is not None:
            errors.append("non-absent tombstone chain fields must be null")
    else:
        if not _integer(valid_count, 0, MAX_ANCHOR_ROWS) or type(malformed) is not bool:
            errors.append("absent tombstone chain fields are invalid")
    tombstone_event = value.get("tombstone_event_id")
    if (tombstone == "valid") != (tombstone_event is not None):
        errors.append("tombstone event nullability is invalid")
    if tombstone_event is not None and not _event_id(tombstone_event):
        errors.append("tombstone event ID is invalid")
    witness = value.get("exhaustion_witness_status")
    if witness not in {"not_evaluated", "absent", "present"}:
        errors.append("exhaustion witness status is invalid")
    if tombstone in {"invalid", "multiple"} and witness != "not_evaluated":
        errors.append("invalid tombstone must not evaluate a witness")
    if tombstone == "valid" and witness != "present":
        errors.append("valid tombstone must bind a witness")
    selected_id = value.get("selected_head_event_id")
    selected_generation = value.get("selected_head_generation")
    if isinstance(anchor, Mapping):
        if selected_id != anchor.get("event_id") or selected_generation != anchor.get(
            "anchor_generation"
        ):
            errors.append("selected head does not match anchor")
        if tombstone == "valid" and anchor.get("chain_head") is not None:
            errors.append("tombstone witness chain_head must be null")
        if tombstone != "valid" and anchor.get("chain_head") is not True:
            errors.append("enumerated anchor chain_head must be true")
    elif selected_id is not None or selected_generation is not None:
        errors.append("selected head requires an anchor")


def _validate_live(value: Mapping[str, Any], errors: list[str]) -> None:
    digest_fields = {
        "basis_sha256",
        "policy_sha256",
        "coverage_group_sha256",
        "admission_sha256",
        "current_proof_sha256",
        "authority_surface_resolution_sha256",
    }
    _exact_fields(value, {"reconstruction_status", *digest_fields}, "live", errors)
    status = value.get("reconstruction_status")
    if status not in {"not_run", "matched", "mismatched", "indeterminate", "unavailable"}:
        errors.append("live reconstruction status is invalid")
        return
    for field in digest_fields:
        item = value.get(field)
        if item is not None and not _is_sha(item):
            errors.append(f"live {field} is invalid")
    if status in {"matched", "mismatched"} and any(value.get(field) is None for field in digest_fields):
        errors.append("completed live reconstruction requires all digests")
    if status == "not_run" and any(value.get(field) is not None for field in digest_fields):
        errors.append("not-run live reconstruction requires null digests")


def _validate_eligibility(value: Any, reasons: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("eligibility must be an object")
        return
    _exact_fields(
        value,
        {
            "status",
            "predicate_kind",
            "matched",
            "direct_input_right",
            "check_skip_authorized",
            "result_substitution_authorized",
        },
        "eligibility",
        errors,
    )
    status = value.get("status")
    if status not in {"eligible", "withheld", "unavailable", "invalid"}:
        errors.append("eligibility status is invalid")
    if value.get("predicate_kind") != "drift_eligibility_only":
        errors.append("predicate kind is invalid")
    if any(
        value.get(field) is not False
        for field in (
            "direct_input_right",
            "check_skip_authorized",
            "result_substitution_authorized",
        )
    ):
        errors.append("C6 rights must remain false")
    if not isinstance(reasons, list):
        errors.append("reason_codes must be an array")
        return
    if (
        len(reasons) > MAX_REASONS
        or reasons != sorted(set(reasons))
        or any(reason not in DRIFT_REASON_CODES for reason in reasons)
    ):
        errors.append("reason_codes are invalid")
    eligible = status == "eligible"
    if value.get("matched") is not eligible or eligible != (not reasons):
        errors.append("eligibility matched/reason relation is invalid")


def _validate_authorization(value: Any, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        errors.append("authorization_status must be an object or null")
        return
    expected = {
        "independent_review": "pending",
        "anchoring_authorized": False,
        "reuse_authorized": False,
        "terminal_authority": False,
        "mandatory_evidence": False,
    }
    _exact_fields(value, {*expected, "human_gate"}, "authorization_status", errors)
    if any(value.get(field) != expected_value for field, expected_value in expected.items()):
        errors.append("authorization_status changed C4 facts")
    if value.get("human_gate") not in {"pending", "not_required"}:
        errors.append("authorization human_gate is invalid")


def _validate_handoff(value: Any, errors: list[str]) -> None:
    if value is None:
        return
    expected = {
        "status": "anchored_candidate",
        "reuse_consumable": False,
        "terminal_consumable": False,
        "promotion_authorized": False,
    }
    if not isinstance(value, Mapping):
        errors.append("handoff must be an object or null")
        return
    _exact_fields(value, set(expected), "handoff", errors)
    if any(value.get(field) != expected_value for field, expected_value in expected.items()):
        errors.append("handoff changed C5 facts")


def _validate_candidate(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append(f"{label} must be an object")
        return
    _exact_fields(value, {"object_format", "commit_oid", "tree_oid"}, label, errors)
    object_format = value.get("object_format")
    length = {"sha1": 40, "sha256": 64}.get(object_format)
    if length is None:
        errors.append(f"{label} object_format is invalid")
        return
    for field in ("commit_oid", "tree_oid"):
        item = value.get(field)
        if not isinstance(item, str) or len(item) != length or not _HEX.fullmatch(item):
            errors.append(f"{label} {field} is invalid")


def _exact_fields(
    value: Mapping[str, Any], expected: set[str], label: str, errors: list[str]
) -> None:
    if set(value) != expected:
        errors.append(f"{label} fields are invalid")


def _public_id(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value.encode("utf-8")) <= MAX_PUBLIC_ID_BYTES
        and _PUBLIC_ID.fullmatch(value)
    )


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA.fullmatch(value))


def _event_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_EVENT_ID.fullmatch(value))


def _integer(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _without(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {str(key): _json_ready(item) for key, item in value.items() if key != field}


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings.")
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError("Value is not JSON-compatible.")


def _result(errors: list[str]) -> ProofAnchorDriftValidationResult:
    return ProofAnchorDriftValidationResult(
        PROOF_ANCHOR_DRIFT_ELIGIBILITY_CONTRACT_VERSION,
        tuple(errors),
    )


__all__ = [
    "DRIFT_EFFECTS",
    "DRIFT_ERROR_PHASES",
    "DRIFT_HARD_ERROR_CODES",
    "DRIFT_REASON_CODES",
    "MAX_ANCHOR_ROWS",
    "MAX_CHECKS",
    "MAX_PARTICIPANTS",
    "MAX_RECEIPT_BYTES",
    "MAX_REASONS",
    "MAX_SUBJECT_BYTES",
    "PROOF_ANCHOR_DRIFT_ELIGIBILITY_CONTRACT_VERSION",
    "PROOF_ANCHOR_DRIFT_SUBJECT_CONTRACT_VERSION",
    "ProofAnchorDriftValidationResult",
    "canonical_proof_anchor_drift_bytes",
    "eligibility_sha256",
    "finalize_proof_anchor_drift_eligibility",
    "proof_anchor_drift_eligibility_schema",
    "subject_sha256",
    "validate_proof_anchor_drift_eligibility",
]
