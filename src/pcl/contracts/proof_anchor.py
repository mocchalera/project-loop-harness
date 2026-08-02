from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import importlib.resources
import json
import re
from typing import Any


PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION = "proof-admission-anchor-basis/v1"
PROOF_ADMISSION_AUTHORIZATION_CONTRACT_VERSION = "proof-admission-authorization/v1"
PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION = "proof-admission-anchor/v1"
PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION = "proof-admission-anchor-result/v1"
PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION = "proof-admission-anchor-event/v1"
PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION = (
    "proof-admission-anchor-recovery-exhausted-event/v1"
)
PROOF_ADMISSION_ANCHOR_HEALTH_CONTRACT_VERSION = "proof-admission-anchor-health/v1"
PROOF_ADMISSION_ANCHOR_EPOCH_CONTRACT_VERSION = "proof-admission-anchor-epoch/v1"
INDEPENDENT_REVIEW_SUBJECT_CONTRACT_VERSION = (
    "proof-admission-independent-review-subject/v1"
)
HUMAN_GATE_SUBJECT_CONTRACT_VERSION = "proof-admission-human-gate-subject/v1"

MAX_BASIS_BYTES = 34_603_008
MAX_AUTHORIZATION_BYTES = 65_536
MAX_ANCHOR_BYTES = 1_048_576
MAX_EVENT_PAYLOAD_BYTES = 131_072
MAX_FINAL_DIRECTORY_BYTES = 37_748_736
MAX_RECOVERY_GENERATIONS = 3
MAX_HEALTH_FINDING_CODES = 16
MAX_HEALTH_OBSERVATIONS = 4

ANCHOR_SCOPE = {
    "anchor": True,
    "reuse": False,
    "terminal": False,
    "publication": False,
}
ANCHOR_AUTHORIZATION_PROJECTION = {
    "independent_review": "approved",
    "human_gate": "not_required",
    "authorized_actions": ["anchor"],
    "anchor_authorization_granted": True,
    "reuse_authorized": False,
    "terminal_authority": False,
    "mandatory_evidence": False,
    "publication_authorized": False,
}
ANCHOR_HANDOFF = {
    "status": "anchored_candidate",
    "reuse_consumable": False,
    "terminal_consumable": False,
    "promotion_authorized": False,
}
ANCHOR_EFFECTS_SUCCESS = {
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
ANCHOR_EFFECTS_ZERO = {
    **ANCHOR_EFFECTS_SUCCESS,
    "evidence_rows_inserted": 0,
    "evidence_links_inserted": 0,
    "events_appended": 0,
    "outbox_records_appended": 0,
    "directories_published": 0,
}
EXHAUSTION_EFFECTS_SUCCESS = {
    **ANCHOR_EFFECTS_ZERO,
    "events_appended": 1,
    "outbox_records_appended": 1,
}

_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^PA-[0-9A-F]{64}$")
_EVENT_ID = re.compile(r"^EV-[0-9A-F]{64}$")
_OUTBOX_ID = re.compile(r"^OB-[0-9A-F]{64}$")
_EVIDENCE_ID = re.compile(r"^E-[0-9A-Z]+$")
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,4095}$")
_RFC3339_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|\+00:00)$"
)
_OID_LENGTHS = {"sha1": 40, "sha256": 64}

_BASIS_FIELDS = {
    "contract_version",
    "target",
    "candidate",
    "policy",
    "admission",
    "bindings",
    "scope",
    "basis_sha256",
}
_AUTHORIZATION_FIELDS = {
    "contract_version",
    "authorization_id",
    "authorization_kind",
    "decision",
    "authority",
    "target",
    "candidate",
    "bindings",
    "authorization_subject_sha256",
    "review",
    "scope",
    "issued_at",
    "reason",
    "authorization_sha256",
}
_ANCHOR_FIELDS = {
    "contract_version",
    "request",
    "epoch",
    "target",
    "candidate",
    "bindings",
    "members",
    "authorization_projection",
    "handoff",
    "effects",
    "anchor_sha256",
}
_ANCHOR_BINDING_FIELDS = {
    "basis_sha256",
    "policy_sha256",
    "coverage_group_sha256",
    "admission_sha256",
    "independent_review_authorization_sha256",
    "independent_review_subject_sha256",
    "human_gate_authorization_sha256",
    "human_gate_subject_sha256",
}
_AUTHORIZATION_BINDING_FIELDS = {
    "basis_sha256",
    "policy_sha256",
    "coverage_group_sha256",
    "admission_sha256",
    "producer_sha256",
}
_AUTHORITY_FIELDS = {
    "actor_kind",
    "actor_id",
    "recorder_kind",
    "recorder_id",
    "source_kind",
    "source_ref",
    "candidate_controlled",
}
_MEMBER_ORDER = (
    ("basis", "basis.json"),
    ("independent_review", "independent-review.json"),
    ("human_gate", "human-gate.json"),
)
_EFFECT_FIELDS = set(ANCHOR_EFFECTS_SUCCESS)


@dataclass(frozen=True)
class ProofAnchorValidationResult:
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


def proof_admission_anchor_basis_schema() -> dict[str, Any]:
    return _schema("proof-admission-anchor-basis-v1.schema.json")


def proof_admission_authorization_schema() -> dict[str, Any]:
    return _schema("proof-admission-authorization-v1.schema.json")


def proof_admission_anchor_schema() -> dict[str, Any]:
    return _schema("proof-admission-anchor-v1.schema.json")


def proof_admission_anchor_result_schema() -> dict[str, Any]:
    return _schema("proof-admission-anchor-result-v1.schema.json")


def canonical_proof_anchor_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _json_ready(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except ValueError as exc:
        raise ValueError("Proof-anchor canonical JSON rejects NaN and Infinity.") from exc


def domain_sha256(domain: str, value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        b"pcl:" + domain.encode("utf-8") + b"\0" + canonical_proof_anchor_bytes(value)
    ).hexdigest()


def manifest_file_sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def basis_sha256(value: Mapping[str, Any]) -> str:
    content = _without(value, "basis_sha256")
    return domain_sha256(PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION, content)


def authorization_subject_sha256(value: Mapping[str, Any]) -> str:
    kind = str(value.get("authorization_kind") or "")
    authority = value.get("authority")
    actor = {
        "actor_kind": authority.get("actor_kind") if isinstance(authority, Mapping) else None,
        "actor_id": authority.get("actor_id") if isinstance(authority, Mapping) else None,
        "candidate_controlled": (
            authority.get("candidate_controlled") if isinstance(authority, Mapping) else None
        ),
    }
    if kind == "independent_review":
        contract_version = INDEPENDENT_REVIEW_SUBJECT_CONTRACT_VERSION
    elif kind == "human_gate":
        contract_version = HUMAN_GATE_SUBJECT_CONTRACT_VERSION
    else:
        raise ValueError("Unsupported proof-admission authorization kind.")
    preimage = {
        "contract_version": contract_version,
        "authorization_kind": kind,
        "actor": actor,
        "target": _json_ready(value.get("target")),
        "candidate": _json_ready(value.get("candidate")),
        "bindings": _json_ready(value.get("bindings")),
        "scope": _json_ready(value.get("scope")),
    }
    return domain_sha256(contract_version, preimage)


def authorization_sha256(value: Mapping[str, Any]) -> str:
    return domain_sha256(
        PROOF_ADMISSION_AUTHORIZATION_CONTRACT_VERSION,
        _without(value, "authorization_sha256"),
    )


def base_request_sha256(
    *,
    project_instance_id: str,
    target: Mapping[str, Any],
    candidate: Mapping[str, Any],
    basis_sha256_value: str,
    independent_review_subject_sha256: str,
    human_gate_subject_sha256: str | None,
) -> str:
    preimage = {
        "contract_version": "proof-admission-anchor-request-subject/v1",
        "project_instance_id": project_instance_id,
        "target": _json_ready(target),
        "candidate": _json_ready(candidate),
        "basis_sha256": basis_sha256_value,
        "independent_review_subject_sha256": independent_review_subject_sha256,
        "human_gate_subject_sha256": human_gate_subject_sha256,
    }
    return domain_sha256("proof-admission-anchor-request-subject/v1", preimage)


def proof_anchor_request_id(
    *,
    base_request_sha256_value: str,
    anchor_generation: int,
    recovery_predecessor: Mapping[str, Any] | None,
) -> str:
    preimage = {
        "contract_version": "proof-admission-anchor-request/v1",
        "base_request_sha256": base_request_sha256_value,
        "anchor_generation": anchor_generation,
        "recovery_predecessor": _json_ready(recovery_predecessor),
    }
    return "PA-" + _hraw_hex("proof-admission-anchor-request/v1", preimage).upper()


def epoch_sha256(value: Mapping[str, Any]) -> str:
    return domain_sha256(PROOF_ADMISSION_ANCHOR_EPOCH_CONTRACT_VERSION, _without(value, "epoch_sha256"))


def anchor_sha256(value: Mapping[str, Any]) -> str:
    return domain_sha256(PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION, _without(value, "anchor_sha256"))


def health_sha256(value: Mapping[str, Any]) -> str:
    return domain_sha256(PROOF_ADMISSION_ANCHOR_HEALTH_CONTRACT_VERSION, _without(value, "health_sha256"))


def proof_anchor_event_id(request_id: str) -> str:
    preimage = {
        "contract_version": PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION,
        "request_id": request_id,
    }
    return "EV-" + _hraw_hex("proof-admission-anchor-event/v1", preimage).upper()


def proof_anchor_outbox_id(request_id: str) -> str:
    preimage = {
        "contract_version": "proof-admission-anchor-outbox/v1",
        "request_id": request_id,
    }
    return "OB-" + _hraw_hex("proof-admission-anchor-outbox/v1", preimage).upper()


def exhaustion_event_id(
    *, project_instance_id: str, target: Mapping[str, Any], basis_sha256_value: str
) -> str:
    preimage = _exhaustion_identity(project_instance_id, target, basis_sha256_value)
    return "EV-" + _hraw_hex(
        "proof-admission-anchor-recovery-exhaustion-event/v1", preimage
    ).upper()


def exhaustion_outbox_id(
    *, project_instance_id: str, target: Mapping[str, Any], basis_sha256_value: str
) -> str:
    preimage = _exhaustion_identity(project_instance_id, target, basis_sha256_value)
    return "OB-" + _hraw_hex(
        "proof-admission-anchor-recovery-exhaustion-outbox/v1", preimage
    ).upper()


def finalize_proof_admission_anchor_basis(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _json_copy(value)
    result["basis_sha256"] = basis_sha256(result)
    return result


def finalize_proof_admission_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _json_copy(value)
    result["authorization_subject_sha256"] = authorization_subject_sha256(result)
    result["authorization_sha256"] = authorization_sha256(result)
    return result


def finalize_proof_admission_anchor(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _json_copy(value)
    epoch = result.get("epoch")
    if isinstance(epoch, dict):
        epoch["epoch_sha256"] = epoch_sha256(epoch)
    result["anchor_sha256"] = anchor_sha256(result)
    return result


def finalize_proof_anchor_health(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _json_copy(value)
    result["health_sha256"] = health_sha256(result)
    return result


def validate_proof_admission_anchor_basis(value: Any) -> ProofAnchorValidationResult:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return _result(PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION, ["$: must be an object"])
    document = _json_ready(value)
    _exact(document, _BASIS_FIELDS, "$", errors)
    if document.get("contract_version") != PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION:
        errors.append("$.contract_version: unsupported")
    _target(document.get("target"), "$.target", errors)
    _candidate(document.get("candidate"), "$.candidate", errors)
    if not isinstance(document.get("policy"), dict):
        errors.append("$.policy: must be an object")
    if not isinstance(document.get("admission"), dict):
        errors.append("$.admission: must be an object")
    bindings = document.get("bindings")
    if not isinstance(bindings, dict):
        errors.append("$.bindings: must be an object")
        bindings = {}
    else:
        _exact(bindings, {"policy_sha256", "coverage_group_sha256", "admission_sha256"}, "$.bindings", errors)
        for field in ("policy_sha256", "coverage_group_sha256", "admission_sha256"):
            _sha(bindings.get(field), f"$.bindings.{field}", errors)
    if document.get("scope") != ANCHOR_SCOPE:
        errors.append("$.scope: must be the fixed anchor-only scope")
    policy = document.get("policy") if isinstance(document.get("policy"), dict) else {}
    admission = document.get("admission") if isinstance(document.get("admission"), dict) else {}
    relationships = (
        (document.get("target"), policy.get("target"), "$.target"),
        (document.get("candidate"), policy.get("candidate"), "$.candidate"),
        (bindings.get("policy_sha256"), policy.get("policy_sha256"), "$.bindings.policy_sha256"),
        (
            bindings.get("coverage_group_sha256"),
            policy.get("coverage_group_sha256"),
            "$.bindings.coverage_group_sha256",
        ),
        (
            bindings.get("coverage_group_sha256"),
            admission.get("coverage_group_sha256"),
            "$.admission.coverage_group_sha256",
        ),
        (
            bindings.get("admission_sha256"),
            admission.get("admission_sha256"),
            "$.bindings.admission_sha256",
        ),
        (admission.get("policy_sha256"), policy.get("policy_sha256"), "$.admission.policy_sha256"),
    )
    for left, right, path in relationships:
        if left != right:
            errors.append(f"{path}: binding mismatch")
    if admission:
        if admission.get("admission_state") != "reviewable":
            errors.append("$.admission.admission_state: must equal reviewable")
        if admission.get("state_reason_codes") != []:
            errors.append("$.admission.state_reason_codes: must be empty")
        if admission.get("review_readiness") != "ready":
            errors.append("$.admission.review_readiness: must equal ready")
        if admission.get("promotion_suitability") != "candidate":
            errors.append("$.admission.promotion_suitability: must equal candidate")
        if admission.get("promotion_withholding_codes") != []:
            errors.append("$.admission.promotion_withholding_codes: must be empty")
        expected_auth = {
            "independent_review": "pending",
            "human_gate": (
                "pending"
                if policy.get("authorization_requirements", {}).get("human_gate") == "required"
                else "not_required"
            ),
            "anchoring_authorized": False,
            "reuse_authorized": False,
            "terminal_authority": False,
            "mandatory_evidence": False,
        }
        if admission.get("authorization_status") != expected_auth:
            errors.append("$.admission.authorization_status: embedded C4 authority changed")
    _sha(document.get("basis_sha256"), "$.basis_sha256", errors)
    try:
        if document.get("basis_sha256") != basis_sha256(document):
            errors.append("$.basis_sha256: digest mismatch")
        if len(canonical_proof_anchor_bytes(document)) > MAX_BASIS_BYTES:
            errors.append("$: basis capacity exceeded")
    except (TypeError, ValueError):
        errors.append("$: invalid canonical basis")
    return _result(PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION, errors)


def validate_proof_admission_authorization(value: Any) -> ProofAnchorValidationResult:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return _result(PROOF_ADMISSION_AUTHORIZATION_CONTRACT_VERSION, ["$: must be an object"])
    document = _json_ready(value)
    _exact(document, _AUTHORIZATION_FIELDS, "$", errors)
    if document.get("contract_version") != PROOF_ADMISSION_AUTHORIZATION_CONTRACT_VERSION:
        errors.append("$.contract_version: unsupported")
    _identifier(document.get("authorization_id"), "$.authorization_id", errors)
    kind = document.get("authorization_kind")
    if kind not in {"independent_review", "human_gate"}:
        errors.append("$.authorization_kind: unsupported")
    if document.get("decision") not in {"approved", "rejected", "inconclusive"}:
        errors.append("$.decision: unsupported")
    authority = document.get("authority")
    if not isinstance(authority, dict):
        errors.append("$.authority: must be an object")
        authority = {}
    else:
        _exact(authority, _AUTHORITY_FIELDS, "$.authority", errors)
    actor_kind = authority.get("actor_kind")
    if actor_kind not in {"human", "agent", "system"}:
        errors.append("$.authority.actor_kind: unsupported")
    if authority.get("recorder_kind") not in {"human", "agent", "system"}:
        errors.append("$.authority.recorder_kind: unsupported")
    if authority.get("source_kind") not in {"cli", "conversation", "cockpit", "api"}:
        errors.append("$.authority.source_kind: unsupported")
    for field in ("actor_id", "recorder_id"):
        _identifier(authority.get(field), f"$.authority.{field}", errors)
    if not isinstance(authority.get("source_ref"), str) or len(authority.get("source_ref", "").encode()) > 4096:
        errors.append("$.authority.source_ref: invalid")
    if authority.get("candidate_controlled") is not False:
        errors.append("$.authority.candidate_controlled: must equal false")
    if kind == "independent_review" and actor_kind not in {"human", "agent"}:
        errors.append("$.authority.actor_kind: independent review requires human or agent")
    if kind == "human_gate" and actor_kind != "human":
        errors.append("$.authority.actor_kind: human gate requires human")
    _target(document.get("target"), "$.target", errors)
    _candidate(document.get("candidate"), "$.candidate", errors)
    bindings = document.get("bindings")
    if not isinstance(bindings, dict):
        errors.append("$.bindings: must be an object")
        bindings = {}
    else:
        _exact(bindings, _AUTHORIZATION_BINDING_FIELDS, "$.bindings", errors)
        for field in _AUTHORIZATION_BINDING_FIELDS:
            _sha(bindings.get(field), f"$.bindings.{field}", errors)
    review = document.get("review")
    if kind == "independent_review":
        if not isinstance(review, dict):
            errors.append("$.review: independent review requires review facts")
        else:
            _exact(review, {"report_sha256", "report_size_bytes", "findings"}, "$.review", errors)
            _sha(review.get("report_sha256"), "$.review.report_sha256", errors)
            _bounded_int(review.get("report_size_bytes"), "$.review.report_size_bytes", 0, MAX_AUTHORIZATION_BYTES, errors)
            findings = review.get("findings")
            if not isinstance(findings, dict):
                errors.append("$.review.findings: must be an object")
            else:
                _exact(findings, {"high", "medium", "low"}, "$.review.findings", errors)
                for field in ("high", "medium", "low"):
                    _bounded_int(findings.get(field), f"$.review.findings.{field}", 0, 1_000_000, errors)
                if document.get("decision") == "approved" and (
                    findings.get("high") != 0 or findings.get("medium") != 0
                ):
                    errors.append("$.review.findings: approval requires High 0 and Medium 0")
    elif review is not None:
        errors.append("$.review: human gate requires null")
    if document.get("scope") != ANCHOR_SCOPE:
        errors.append("$.scope: must be the fixed anchor-only scope")
    if not isinstance(document.get("issued_at"), str) or not _RFC3339_UTC.fullmatch(document.get("issued_at", "")):
        errors.append("$.issued_at: must be RFC3339 UTC")
    if not isinstance(document.get("reason"), str) or not document.get("reason") or len(document.get("reason", "").encode()) > 16_384:
        errors.append("$.reason: invalid")
    _sha(document.get("authorization_subject_sha256"), "$.authorization_subject_sha256", errors)
    _sha(document.get("authorization_sha256"), "$.authorization_sha256", errors)
    try:
        if document.get("authorization_subject_sha256") != authorization_subject_sha256(document):
            errors.append("$.authorization_subject_sha256: digest mismatch")
        if document.get("authorization_sha256") != authorization_sha256(document):
            errors.append("$.authorization_sha256: digest mismatch")
        if len(canonical_proof_anchor_bytes(document)) > MAX_AUTHORIZATION_BYTES:
            errors.append("$: authorization capacity exceeded")
    except (TypeError, ValueError):
        errors.append("$: invalid canonical authorization")
    return _result(PROOF_ADMISSION_AUTHORIZATION_CONTRACT_VERSION, errors)


def validate_proof_admission_anchor(value: Any) -> ProofAnchorValidationResult:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return _result(PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION, ["$: must be an object"])
    document = _json_ready(value)
    _exact(document, _ANCHOR_FIELDS, "$", errors)
    if document.get("contract_version") != PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION:
        errors.append("$.contract_version: unsupported")
    request = document.get("request")
    if not isinstance(request, dict):
        errors.append("$.request: must be an object")
        request = {}
    else:
        _exact(request, {"request_id", "base_request_sha256", "anchor_generation", "recovery"}, "$.request", errors)
        _request_id(request.get("request_id"), "$.request.request_id", errors)
        _sha(request.get("base_request_sha256"), "$.request.base_request_sha256", errors)
        _bounded_int(request.get("anchor_generation"), "$.request.anchor_generation", 0, MAX_RECOVERY_GENERATIONS, errors)
        _recovery_health(
            request.get("recovery"),
            int(request.get("anchor_generation") or 0),
            "$.request.recovery",
            errors,
        )
    epoch = document.get("epoch")
    _epoch(epoch, request, errors)
    _target(document.get("target"), "$.target", errors)
    _candidate(document.get("candidate"), "$.candidate", errors)
    bindings = document.get("bindings")
    if not isinstance(bindings, dict):
        errors.append("$.bindings: must be an object")
        bindings = {}
    else:
        _exact(bindings, _ANCHOR_BINDING_FIELDS, "$.bindings", errors)
        for field in _ANCHOR_BINDING_FIELDS:
            value_at = bindings.get(field)
            if field.startswith("human_gate_") and value_at is None:
                continue
            _sha(value_at, f"$.bindings.{field}", errors)
        if (bindings.get("human_gate_authorization_sha256") is None) != (
            bindings.get("human_gate_subject_sha256") is None
        ):
            errors.append("$.bindings: human-gate bindings must be both null or both digests")
    members = document.get("members")
    expected_member_count = 2 if bindings.get("human_gate_subject_sha256") is None else 3
    if not isinstance(members, list) or len(members) != expected_member_count:
        errors.append("$.members: must contain the fixed two or three members")
        members = []
    for index, member in enumerate(members):
        path = f"$.members[{index}]"
        if not isinstance(member, dict):
            errors.append(f"{path}: must be an object")
            continue
        _exact(member, {"role", "storage_name", "size_bytes", "file_sha256"}, path, errors)
        expected = _MEMBER_ORDER[index]
        if (member.get("role"), member.get("storage_name")) != expected:
            errors.append(f"{path}: member order/name mismatch")
        _bounded_int(member.get("size_bytes"), f"{path}.size_bytes", 1, MAX_BASIS_BYTES, errors)
        _sha(member.get("file_sha256"), f"{path}.file_sha256", errors)
    expected_projection = dict(ANCHOR_AUTHORIZATION_PROJECTION)
    if bindings.get("human_gate_subject_sha256") is not None:
        expected_projection["human_gate"] = "approved"
    if document.get("authorization_projection") != expected_projection:
        errors.append("$.authorization_projection: authority namespace mismatch")
    if document.get("handoff") != ANCHOR_HANDOFF:
        errors.append("$.handoff: must preserve non-consumable handoff")
    if document.get("effects") != ANCHOR_EFFECTS_SUCCESS:
        errors.append("$.effects: must equal the fresh anchor effect matrix")
    _sha(document.get("anchor_sha256"), "$.anchor_sha256", errors)
    try:
        if document.get("anchor_sha256") != anchor_sha256(document):
            errors.append("$.anchor_sha256: digest mismatch")
        if len(canonical_proof_anchor_bytes(document)) > MAX_ANCHOR_BYTES:
            errors.append("$: anchor capacity exceeded")
    except (TypeError, ValueError):
        errors.append("$: invalid canonical anchor")
    return _result(PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION, errors)


def validate_proof_anchor_event(value: Any) -> ProofAnchorValidationResult:
    fields = {
        "contract_version",
        "request_id",
        "base_request_sha256",
        "anchor_generation",
        "basis_sha256",
        "anchor_sha256",
        "manifest_file_sha256",
        "evidence_id",
    }
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return _result(PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION, ["$: must be an object"])
    document = _json_ready(value)
    _exact(document, fields, "$", errors)
    if document.get("contract_version") != PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION:
        errors.append("$.contract_version: unsupported")
    _request_id(document.get("request_id"), "$.request_id", errors)
    for field in ("base_request_sha256", "basis_sha256", "anchor_sha256", "manifest_file_sha256"):
        _sha(document.get(field), f"$.{field}", errors)
    _bounded_int(document.get("anchor_generation"), "$.anchor_generation", 0, MAX_RECOVERY_GENERATIONS, errors)
    if not isinstance(document.get("evidence_id"), str) or not _EVIDENCE_ID.fullmatch(document.get("evidence_id", "")):
        errors.append("$.evidence_id: invalid")
    _event_cap(document, errors)
    return _result(PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION, errors)


def validate_proof_anchor_exhaustion_event(value: Any) -> ProofAnchorValidationResult:
    fields = {
        "contract_version",
        "base_request_sha256",
        "anchor_generation",
        "basis_sha256",
        "anchor_sha256",
        "manifest_file_sha256",
        "exhausted_request_id",
        "exhausted_anchor_event_id",
        "health_sha256",
        "disposition",
    }
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return _result(PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION, ["$: must be an object"])
    document = _json_ready(value)
    _exact(document, fields, "$", errors)
    if document.get("contract_version") != PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION:
        errors.append("$.contract_version: unsupported")
    for field in ("base_request_sha256", "basis_sha256", "anchor_sha256", "manifest_file_sha256", "health_sha256"):
        _sha(document.get(field), f"$.{field}", errors)
    if document.get("anchor_generation") != 3:
        errors.append("$.anchor_generation: must equal 3")
    _request_id(document.get("exhausted_request_id"), "$.exhausted_request_id", errors)
    _event_id(document.get("exhausted_anchor_event_id"), "$.exhausted_anchor_event_id", errors)
    if document.get("disposition") != "human_design_required":
        errors.append("$.disposition: must equal human_design_required")
    _event_cap(document, errors)
    return _result(PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION, errors)


def validate_proof_anchor_health(value: Any) -> ProofAnchorValidationResult:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return _result(PROOF_ADMISSION_ANCHOR_HEALTH_CONTRACT_VERSION, ["$: must be an object"])
    document = _json_ready(value)
    _exact(document, {"contract_version", "predecessor", "authority_components", "artifact_observations", "finding_codes", "health_sha256"}, "$", errors)
    if document.get("contract_version") != PROOF_ADMISSION_ANCHOR_HEALTH_CONTRACT_VERSION:
        errors.append("$.contract_version: unsupported")
    predecessor = document.get("predecessor")
    if not isinstance(predecessor, dict):
        errors.append("$.predecessor: must be an object")
    else:
        _exact(predecessor, {"request_id", "anchor_generation", "event_id", "anchor_sha256", "manifest_file_sha256"}, "$.predecessor", errors)
        _request_id(predecessor.get("request_id"), "$.predecessor.request_id", errors)
        _bounded_int(predecessor.get("anchor_generation"), "$.predecessor.anchor_generation", 0, MAX_RECOVERY_GENERATIONS, errors)
        _event_id(predecessor.get("event_id"), "$.predecessor.event_id", errors)
        _sha(predecessor.get("anchor_sha256"), "$.predecessor.anchor_sha256", errors)
        _sha(predecessor.get("manifest_file_sha256"), "$.predecessor.manifest_file_sha256", errors)
    authority = document.get("authority_components")
    if not isinstance(authority, dict) or authority != {
        "evidence_row": "matched",
        "evidence_link": "matched",
        "event": "matched",
        "outbox": "matched",
    }:
        errors.append("$.authority_components: quartet must be matched")
    observations = document.get("artifact_observations")
    if (
        not isinstance(observations, list)
        or not 1 <= len(observations) <= MAX_HEALTH_OBSERVATIONS
    ):
        errors.append("$.artifact_observations: invalid")
        observations = []
    expected_observations = (
        ("manifest", "evidence-manifest.json"),
        ("basis", "basis.json"),
        ("independent_review", "independent-review.json"),
        ("human_gate", "human-gate.json"),
    )
    for index, observation in enumerate(observations):
        path = f"$.artifact_observations[{index}]"
        if not isinstance(observation, dict):
            errors.append(f"{path}: must be an object")
            continue
        _exact(
            observation,
            {
                "role",
                "storage_name",
                "status",
                "expected_size_bytes",
                "observed_size_bytes",
                "expected_file_sha256",
                "observed_file_sha256",
            },
            path,
            errors,
        )
        if (observation.get("role"), observation.get("storage_name")) != (
            expected_observations[index]
        ):
            errors.append(f"{path}: observation order/name mismatch")
        if observation.get("status") not in {
            "ok",
            "missing",
            "not_regular",
            "symlink",
            "redirected",
            "changed",
            "size_mismatch",
            "hash_mismatch",
        }:
            errors.append(f"{path}.status: unsupported")
        for field in ("expected_size_bytes", "observed_size_bytes"):
            item = observation.get(field)
            if item is not None:
                _bounded_int(item, f"{path}.{field}", 0, MAX_FINAL_DIRECTORY_BYTES, errors)
        for field in ("expected_file_sha256", "observed_file_sha256"):
            item = observation.get(field)
            if item is not None:
                _sha(item, f"{path}.{field}", errors)
    findings = document.get("finding_codes")
    if (
        not isinstance(findings, list)
        or len(findings) > MAX_HEALTH_FINDING_CODES
        or findings != sorted(set(findings))
        or any(not isinstance(item, str) or not _PUBLIC_ID.fullmatch(item) for item in findings)
    ):
        errors.append("$.finding_codes: must be sorted unique and bounded")
    _sha(document.get("health_sha256"), "$.health_sha256", errors)
    try:
        if document.get("health_sha256") != health_sha256(document):
            errors.append("$.health_sha256: digest mismatch")
    except (TypeError, ValueError):
        errors.append("$: invalid canonical health receipt")
    return _result(PROOF_ADMISSION_ANCHOR_HEALTH_CONTRACT_VERSION, errors)


def validate_proof_admission_anchor_result(value: Any) -> ProofAnchorValidationResult:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return _result(PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION, ["$: must be an object"])
    document = _json_ready(value)
    fields = {
        "contract_version",
        "ok",
        "status",
        "changed",
        "idempotent",
        "mutation_committed",
        "safe_to_retry_original",
        "request_id",
        "base_request_sha256",
        "anchor_generation",
        "basis_sha256",
        "anchor_sha256",
        "manifest_file_sha256",
        "evidence_id",
        "event_id",
        "outbox_id",
        "projection",
        "health",
        "effects",
        "recovery_action",
    }
    allowed = set(fields)
    allowed.add("disposition")
    actual = set(document)
    if not fields.issubset(actual) or not actual.issubset(allowed):
        errors.append(
            f"$: fields mismatch missing={sorted(fields - actual)} extra={sorted(actual - allowed)}"
        )
    if document.get("contract_version") != PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION:
        errors.append("$.contract_version: unsupported")
    for field in (
        "ok",
        "changed",
        "idempotent",
        "mutation_committed",
        "safe_to_retry_original",
    ):
        if type(document.get(field)) is not bool:
            errors.append(f"$.{field}: must be a boolean")
    status = document.get("status")
    if status not in {
        "anchored",
        "already_anchored",
        "proof_anchor_recovery_generation_exhausted",
    }:
        errors.append("$.status: unsupported")
    if document.get("request_id") is not None:
        _request_id(document.get("request_id"), "$.request_id", errors)
    for field in (
        "base_request_sha256",
        "basis_sha256",
        "anchor_sha256",
        "manifest_file_sha256",
    ):
        if document.get(field) is not None:
            _sha(document.get(field), f"$.{field}", errors)
    if document.get("anchor_generation") is not None:
        _bounded_int(
            document.get("anchor_generation"),
            "$.anchor_generation",
            0,
            MAX_RECOVERY_GENERATIONS,
            errors,
        )
    if document.get("evidence_id") is not None and not _EVIDENCE_ID.fullmatch(
        str(document.get("evidence_id"))
    ):
        errors.append("$.evidence_id: invalid")
    if document.get("event_id") is not None:
        _event_id(document.get("event_id"), "$.event_id", errors)
    if document.get("outbox_id") is not None and not _OUTBOX_ID.fullmatch(
        str(document.get("outbox_id"))
    ):
        errors.append("$.outbox_id: invalid")
    if document.get("projection") not in {
        "not_applicable",
        "pending",
        "delivered",
        "failed_needs_review",
    }:
        errors.append("$.projection: unsupported")
    if document.get("health") not in {None, "healthy", "postcommit_unhealthy"}:
        errors.append("$.health: unsupported")
    if not any(
        document.get("effects") == expected
        for expected in (
            ANCHOR_EFFECTS_SUCCESS,
            ANCHOR_EFFECTS_ZERO,
            EXHAUSTION_EFFECTS_SUCCESS,
        )
    ):
        errors.append("$.effects: unsupported effect matrix")
    if document.get("recovery_action") is not None and not isinstance(
        document.get("recovery_action"), str
    ):
        errors.append("$.recovery_action: invalid")
    if "disposition" in document and document.get("disposition") != "human_design_required":
        errors.append("$.disposition: unsupported")
    if status == "anchored" and (
        document.get("ok") is not True
        or document.get("changed") is not True
        or document.get("idempotent") is not False
        or document.get("mutation_committed") is not True
        or document.get("safe_to_retry_original") is not False
        or document.get("projection") != "delivered"
        or document.get("health") != "healthy"
        or document.get("effects") != ANCHOR_EFFECTS_SUCCESS
        or document.get("evidence_id") is None
        or document.get("recovery_action") is not None
        or "disposition" in document
    ):
        errors.append("$: anchored result relationship mismatch")
    if status == "already_anchored" and (
        document.get("ok") is not True
        or document.get("changed") is not False
        or document.get("idempotent") is not True
        or document.get("mutation_committed") is not False
        or document.get("safe_to_retry_original") is not False
        or document.get("projection") != "delivered"
        or document.get("health") != "healthy"
        or document.get("effects") != ANCHOR_EFFECTS_ZERO
        or document.get("evidence_id") is None
        or document.get("recovery_action") is not None
        or "disposition" in document
    ):
        errors.append("$: replay result relationship mismatch")
    if status == "proof_anchor_recovery_generation_exhausted" and (
        document.get("ok") is not False
        or document.get("safe_to_retry_original") is not False
        or document.get("anchor_generation") != MAX_RECOVERY_GENERATIONS
        or document.get("evidence_id") is not None
        or document.get("health") != "postcommit_unhealthy"
        or document.get("recovery_action") != "human_design_required"
        or document.get("disposition") != "human_design_required"
        or (
            document.get("changed"),
            document.get("idempotent"),
            document.get("mutation_committed"),
            document.get("projection"),
            _frozen_effects(document.get("effects"))
            if isinstance(document.get("effects"), Mapping)
            else (),
        )
        not in {
            (
                True,
                False,
                True,
                "delivered",
                _frozen_effects(EXHAUSTION_EFFECTS_SUCCESS),
            ),
            (
                False,
                True,
                False,
                "not_applicable",
                _frozen_effects(ANCHOR_EFFECTS_ZERO),
            ),
        }
    ):
        errors.append("$: exhaustion result relationship mismatch")
    return _result(PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION, errors)


def _frozen_effects(value: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted(value.items()))


def _epoch(value: Any, request: Mapping[str, Any], errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("$.epoch: must be an object")
        return
    _exact(value, {"contract_version", "request_id", "base_request_sha256", "anchor_generation", "precommit_hwm", "ledger_predecessor", "recovery_predecessor", "epoch_sha256"}, "$.epoch", errors)
    if value.get("contract_version") != PROOF_ADMISSION_ANCHOR_EPOCH_CONTRACT_VERSION:
        errors.append("$.epoch.contract_version: unsupported")
    for field in ("request_id", "base_request_sha256", "anchor_generation"):
        if value.get(field) != request.get(field):
            errors.append(f"$.epoch.{field}: request mismatch")
    hwm = value.get("precommit_hwm")
    if not isinstance(hwm, dict):
        errors.append("$.epoch.precommit_hwm: must be an object")
    else:
        _exact(hwm, {"sequence", "event_id"}, "$.epoch.precommit_hwm", errors)
        _bounded_int(hwm.get("sequence"), "$.epoch.precommit_hwm.sequence", 0, 2**63 - 1, errors)
        if hwm.get("event_id") is not None:
            _identifier(hwm.get("event_id"), "$.epoch.precommit_hwm.event_id", errors)
    ledger = value.get("ledger_predecessor")
    if not isinstance(ledger, dict):
        errors.append("$.epoch.ledger_predecessor: must be an object")
    else:
        _exact(ledger, {"event_id", "anchor_sha256"}, "$.epoch.ledger_predecessor", errors)
        if (ledger.get("event_id") is None) != (ledger.get("anchor_sha256") is None):
            errors.append("$.epoch.ledger_predecessor: values must both be null or populated")
        if ledger.get("event_id") is not None:
            _event_id(ledger.get("event_id"), "$.epoch.ledger_predecessor.event_id", errors)
            _sha(ledger.get("anchor_sha256"), "$.epoch.ledger_predecessor.anchor_sha256", errors)
    generation = int(request.get("anchor_generation") or 0)
    predecessor = value.get("recovery_predecessor")
    _recovery_predecessor(
        predecessor,
        generation,
        "$.epoch.recovery_predecessor",
        errors,
    )
    expected_predecessor = _health_recovery_predecessor(request.get("recovery"))
    if predecessor != expected_predecessor:
        errors.append("$.epoch.recovery_predecessor: request health mismatch")
    try:
        expected_request_id = proof_anchor_request_id(
            base_request_sha256_value=str(request.get("base_request_sha256")),
            anchor_generation=generation,
            recovery_predecessor=expected_predecessor,
        )
        if request.get("request_id") != expected_request_id:
            errors.append("$.request.request_id: digest mismatch")
    except (TypeError, ValueError):
        errors.append("$.request: invalid request identity")
    _sha(value.get("epoch_sha256"), "$.epoch.epoch_sha256", errors)
    try:
        if value.get("epoch_sha256") != epoch_sha256(value):
            errors.append("$.epoch.epoch_sha256: digest mismatch")
    except (TypeError, ValueError):
        errors.append("$.epoch: invalid canonical epoch")


def _recovery_health(value: Any, generation: int, path: str, errors: list[str]) -> None:
    if generation == 0:
        if value is not None:
            errors.append(f"{path}: generation zero requires null")
        return
    if not isinstance(value, dict):
        errors.append(f"{path}: recovery generation requires a health receipt")
        return
    health = validate_proof_anchor_health(value)
    errors.extend(f"{path}: {error}" for error in health.errors)
    predecessor = value.get("predecessor")
    if (
        not isinstance(predecessor, dict)
        or predecessor.get("anchor_generation") != generation - 1
    ):
        errors.append(
            f"{path}.predecessor.anchor_generation: must name immediate predecessor"
        )
    if not value.get("finding_codes"):
        errors.append(f"{path}.finding_codes: recovery requires an unhealthy receipt")


def _recovery_predecessor(
    value: Any,
    generation: int,
    path: str,
    errors: list[str],
) -> None:
    if generation == 0:
        if value is not None:
            errors.append(f"{path}: generation zero requires null")
        return
    if not isinstance(value, dict):
        errors.append(f"{path}: recovery generation requires a predecessor")
        return
    _exact(value, {"request_id", "anchor_generation", "event_id", "anchor_sha256", "health_sha256"}, path, errors)
    _request_id(value.get("request_id"), f"{path}.request_id", errors)
    if value.get("anchor_generation") != generation - 1:
        errors.append(f"{path}.anchor_generation: must name immediate predecessor")
    _event_id(value.get("event_id"), f"{path}.event_id", errors)
    _sha(value.get("anchor_sha256"), f"{path}.anchor_sha256", errors)
    _sha(value.get("health_sha256"), f"{path}.health_sha256", errors)


def _health_recovery_predecessor(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    predecessor = value.get("predecessor")
    if not isinstance(predecessor, Mapping):
        return None
    return {
        "request_id": predecessor.get("request_id"),
        "anchor_generation": predecessor.get("anchor_generation"),
        "event_id": predecessor.get("event_id"),
        "anchor_sha256": predecessor.get("anchor_sha256"),
        "health_sha256": value.get("health_sha256"),
    }


def _target(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    _exact(value, {"type", "id"}, path, errors)
    if value.get("type") != "task":
        errors.append(f"{path}.type: must equal task")
    _identifier(value.get("id"), f"{path}.id", errors)


def _candidate(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    _exact(value, {"object_format", "commit_oid", "tree_oid"}, path, errors)
    object_format = value.get("object_format")
    if object_format not in _OID_LENGTHS:
        errors.append(f"{path}.object_format: unsupported")
        return
    length = _OID_LENGTHS[object_format]
    for field in ("commit_oid", "tree_oid"):
        item = value.get(field)
        if not isinstance(item, str) or len(item) != length or any(char not in "0123456789abcdef" for char in item):
            errors.append(f"{path}.{field}: invalid {object_format} OID")


def _exact(value: Mapping[str, Any], expected: set[str], path: str, errors: list[str]) -> None:
    actual = set(value)
    if actual != expected:
        errors.append(f"{path}: fields mismatch missing={sorted(expected - actual)} extra={sorted(actual - expected)}")


def _identifier(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _PUBLIC_ID.fullmatch(value):
        errors.append(f"{path}: invalid public identifier")


def _sha(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        errors.append(f"{path}: invalid sha256 digest")


def _request_id(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _REQUEST_ID.fullmatch(value):
        errors.append(f"{path}: invalid request ID")


def _event_id(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _EVENT_ID.fullmatch(value):
        errors.append(f"{path}: invalid event ID")


def _bounded_int(value: Any, path: str, minimum: int, maximum: int, errors: list[str]) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        errors.append(f"{path}: integer outside {minimum}..{maximum}")


def _event_cap(value: Mapping[str, Any], errors: list[str]) -> None:
    try:
        if len(canonical_proof_anchor_bytes(value)) > MAX_EVENT_PAYLOAD_BYTES:
            errors.append("$: event payload capacity exceeded")
    except (TypeError, ValueError):
        errors.append("$: invalid canonical event")


def _without(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = _json_ready(value)
    if not isinstance(result, dict):
        raise TypeError("Expected a mapping.")
    result.pop(field, None)
    return result


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    return value


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(canonical_proof_anchor_bytes(value))


def _hraw_hex(domain: str, value: Any) -> str:
    return hashlib.sha256(
        b"pcl:" + domain.encode("utf-8") + b"\0" + canonical_proof_anchor_bytes(value)
    ).hexdigest()


def _exhaustion_identity(
    project_instance_id: str,
    target: Mapping[str, Any],
    basis_sha256_value: str,
) -> dict[str, Any]:
    return {
        "contract_version": "proof-admission-anchor-recovery-exhaustion-id/v1",
        "project_instance_id": project_instance_id,
        "target": _json_ready(target),
        "basis_sha256": basis_sha256_value,
    }


def _schema(resource: str) -> dict[str, Any]:
    return json.loads(
        importlib.resources.files("pcl.contracts.schemas").joinpath(resource).read_text("utf-8")
    )


def _result(contract_version: str, errors: list[str]) -> ProofAnchorValidationResult:
    return ProofAnchorValidationResult(contract_version, tuple(errors))


__all__ = [
    "ANCHOR_AUTHORIZATION_PROJECTION",
    "ANCHOR_EFFECTS_SUCCESS",
    "ANCHOR_EFFECTS_ZERO",
    "ANCHOR_HANDOFF",
    "ANCHOR_SCOPE",
    "EXHAUSTION_EFFECTS_SUCCESS",
    "HUMAN_GATE_SUBJECT_CONTRACT_VERSION",
    "INDEPENDENT_REVIEW_SUBJECT_CONTRACT_VERSION",
    "MAX_ANCHOR_BYTES",
    "MAX_AUTHORIZATION_BYTES",
    "MAX_BASIS_BYTES",
    "MAX_EVENT_PAYLOAD_BYTES",
    "MAX_FINAL_DIRECTORY_BYTES",
    "MAX_HEALTH_FINDING_CODES",
    "MAX_HEALTH_OBSERVATIONS",
    "MAX_RECOVERY_GENERATIONS",
    "PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION",
    "PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION",
    "PROOF_ADMISSION_ANCHOR_EPOCH_CONTRACT_VERSION",
    "PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION",
    "PROOF_ADMISSION_ANCHOR_HEALTH_CONTRACT_VERSION",
    "PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION",
    "PROOF_ADMISSION_AUTHORIZATION_CONTRACT_VERSION",
    "PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION",
    "ProofAnchorValidationResult",
    "anchor_sha256",
    "authorization_sha256",
    "authorization_subject_sha256",
    "base_request_sha256",
    "basis_sha256",
    "canonical_proof_anchor_bytes",
    "domain_sha256",
    "epoch_sha256",
    "exhaustion_event_id",
    "exhaustion_outbox_id",
    "finalize_proof_admission_anchor",
    "finalize_proof_admission_anchor_basis",
    "finalize_proof_admission_authorization",
    "finalize_proof_anchor_health",
    "health_sha256",
    "manifest_file_sha256",
    "proof_admission_anchor_basis_schema",
    "proof_admission_anchor_result_schema",
    "proof_admission_anchor_schema",
    "proof_admission_authorization_schema",
    "proof_anchor_event_id",
    "proof_anchor_outbox_id",
    "proof_anchor_request_id",
    "validate_proof_admission_anchor",
    "validate_proof_admission_anchor_basis",
    "validate_proof_admission_anchor_result",
    "validate_proof_admission_authorization",
    "validate_proof_anchor_event",
    "validate_proof_anchor_exhaustion_event",
    "validate_proof_anchor_health",
]
