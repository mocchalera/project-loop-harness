from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
import json
from pathlib import PurePosixPath
import re
from typing import Any
import unicodedata

from .proof_workspace import proof_document_sha256


PROOF_COVERAGE_POLICY_CONTRACT_VERSION = "proof-coverage-policy/v1"
PROOF_COVERAGE_ADMISSION_CONTRACT_VERSION = "proof-coverage-admission/v1"
PROOF_COVERAGE_OBSERVATION_CONTRACT_VERSION = "proof-coverage-observation/v1"

PROOF_COVERAGE_POLICY_SCHEMA_RESOURCE = "schemas/proof-coverage-policy-v1.schema.json"
PROOF_COVERAGE_ADMISSION_SCHEMA_RESOURCE = "schemas/proof-coverage-admission-v1.schema.json"

MAX_CANONICAL_DOCUMENT_BYTES = 16_777_216
MAX_PARTICIPANTS = 256
MAX_CHECKS = 4096
MAX_REQUIRED_ROLES = 4096
MAX_REASON_CODES = 64

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_CANARY_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_OID = {
    "sha1": re.compile(r"^[0-9a-f]{40}$"),
    "sha256": re.compile(r"^[0-9a-f]{64}$"),
}
_VERDICTS = {
    "passed",
    "failed",
    "cancelled",
    "timed_out",
    "spawn_failed",
    "blocked",
    "invalid",
    "indeterminate",
}
_AGGREGATE_CURRENT_STATUSES = {
    "healthy",
    "unhealthy",
    "not_applicable",
    "changed",
    "indeterminate",
}
_REASON_RANKS: dict[str, tuple[str, ...]] = {
    "invalid": (
        "coverage_group_mismatch",
        "duplicate_bundle",
        "duplicate_proof_key",
        "duplicate_required_role",
        "participant_without_required_role",
        "participant_policy_mismatch",
        "canary_plan_mismatch",
        "candidate_blob_missing",
        "candidate_blob_oid_mismatch",
        "candidate_blob_type_unsupported",
        "canary_effect_expectation_unsupported",
        "participant_aggregate_invalid",
    ),
    "indeterminate": (
        "authority_current_indeterminate",
        "current_proof_indeterminate",
        "participant_current_proof_indeterminate",
        "candidate_blob_resolution_indeterminate",
        "participant_aggregate_indeterminate",
    ),
    "stale": (
        "authority_current_mismatch",
        "current_proof_mismatch",
        "participant_current_proof_changed",
    ),
    "blocked": (
        "current_proof_unhealthy",
        "canary_effect_mismatch",
        "canary_pcl_state_effect_unproved",
        "participant_aggregate_blocked",
        "participant_aggregate_cancelled",
        "participant_aggregate_failed",
        "participant_aggregate_spawn_failed",
        "participant_aggregate_timed_out",
    ),
    "incomplete": ("required_role_missing", "required_role_not_run"),
}
REASON_TO_RANK = {
    reason: rank for rank, reasons in _REASON_RANKS.items() for reason in reasons
}
STATE_PRECEDENCE = (
    "invalid",
    "indeterminate",
    "stale",
    "blocked",
    "incomplete",
)
PROMOTION_WITHHOLDING_CODES = (
    "participant_anchoring_ineligible",
    "participant_fresh_only",
    "participant_handoff_withheld",
    "participant_output_uncommitted",
)
EFFECTS_ZERO = {
    "schema": 0,
    "migration": 0,
    "database_write": 0,
    "filesystem_write": 0,
    "evidence": 0,
    "event": 0,
    "outbox": 0,
    "render": 0,
    "lifecycle": 0,
}

_POLICY_FIELDS = {
    "contract_version",
    "policy_id",
    "producer",
    "target",
    "candidate",
    "authority_bindings",
    "coverage_group_sha256",
    "required_roles",
    "authorization_requirements",
    "terminal_authority",
    "mandatory_evidence",
    "policy_sha256",
}
_REQUIREMENT_FIELDS = {
    "role",
    "kind",
    "canary_id",
    "canary_item_sha256",
    "expected_outcome",
    "expected_check",
    "selector_audit_labels",
    "required_candidate_blobs",
    "expected_execution",
    "requirement_sha256",
}
_EXPECTED_CHECK_FIELDS = {
    "check_id",
    "role",
    "argv",
    "cwd",
    "selectors",
    "referenced_git_blobs",
    "input_ids",
    "environment",
    "timeout_seconds",
    "max_output_bytes",
    "declared_outputs",
}
_EXPECTED_EXECUTION_FIELDS = {
    "plan_sha256",
    "tool_identity_sha256",
    "environment_binding_sha256",
    "public_execution_sha256",
    "spawn_vector_sha256",
    "external_input_binding_sha256",
    "execution_binding_sha256",
}
_PARTICIPANT_FIELDS = {
    "participant_sha256",
    "participant_group_sha256",
    "spec_sha256",
    "workspace_binding_sha256",
    "proof_key_sha256",
    "verification_profile_sha256",
    "check_plan_sha256",
    "external_input_binding_sha256",
    "packet_sha256",
    "executor_contract_sha256",
    "aggregate_sha256",
    "bundle_sha256",
    "aggregate_verdict",
    "aggregate_output_commitment_status",
    "aggregate_reuse_disposition",
    "aggregate_anchoring_eligible",
    "aggregate_positive_proof_handoff",
    "aggregate_current_proof",
}
_OBSERVATION_FIELDS = {
    "contract_version",
    "role",
    "kind",
    "canary_id",
    "requirement_sha256",
    "matching_checks",
    "selected_participant_sha256",
    "check_id",
    "attempt_status",
    "attempt_sha256",
    "result_sha256",
    "receipt_sha256",
    "c3_verdict",
    "aggregate_verdict",
    "aggregate_reuse_disposition",
    "aggregate_anchoring_eligible",
    "aggregate_positive_proof_handoff",
    "output_commitment_status",
    "plan_binding_status",
    "selector_audit_status",
    "candidate_blob_status",
    "candidate_blob_resolution_sha256",
    "effect_status",
    "freshness",
    "observation_sha256",
}
_ADMISSION_FIELDS = {
    "contract_version",
    "policy_sha256",
    "coverage_group_sha256",
    "participants",
    "role_observations",
    "current_proof",
    "admission_state",
    "state_reason_codes",
    "review_readiness",
    "promotion_suitability",
    "promotion_withholding_codes",
    "authorization_status",
    "effects",
    "admission_sha256",
}


@dataclass(frozen=True)
class ProofCoverageValidationResult:
    contract_type: str
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def proof_coverage_policy_schema() -> dict[str, Any]:
    return _schema(PROOF_COVERAGE_POLICY_SCHEMA_RESOURCE)


def proof_coverage_admission_schema() -> dict[str, Any]:
    return _schema(PROOF_COVERAGE_ADMISSION_SCHEMA_RESOURCE)


def canonical_proof_coverage_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def producer_sha256(producer: Mapping[str, Any]) -> str:
    return proof_document_sha256(
        {
            "contract_version": "proof-coverage-producer/v1",
            "kind": producer["kind"],
            "producer_id": producer["producer_id"],
            "candidate_controlled": False,
        }
    )


def environment_binding_sha256(environment: Mapping[str, Any]) -> str:
    return proof_document_sha256(
        {
            "contract_version": "proof-coverage-environment-binding/v1",
            "environment": dict(environment),
        }
    )


def execution_binding_sha256(
    check_id: str,
    execution: Mapping[str, Any],
) -> str:
    return proof_document_sha256(
        {
            "contract_version": "proof-coverage-expected-execution/v1",
            "check_id": check_id,
            "plan_sha256": execution["plan_sha256"],
            "tool_identity_sha256": execution["tool_identity_sha256"],
            "environment_binding_sha256": execution["environment_binding_sha256"],
            "public_execution_sha256": execution["public_execution_sha256"],
            "spawn_vector_sha256": execution["spawn_vector_sha256"],
            "external_input_binding_sha256": execution[
                "external_input_binding_sha256"
            ],
        }
    )


def canary_item_sha256(item: Mapping[str, Any]) -> str:
    return proof_document_sha256(
        {
            "contract_version": "proof-canary-item-binding/v1",
            "item": {
                "id": item["id"],
                "authority_claim_ids": list(item["authority_claim_ids"]),
                "command": list(item["command"]),
                "selectors": list(item["selectors"]),
                "required_outcome": item["required_outcome"],
                "referenced_blob_oids": list(item["referenced_blob_oids"]),
                "effect_expectations": list(item["effect_expectations"]),
                "supported_platform_conditions": list(
                    item["supported_platform_conditions"]
                ),
            },
        }
    )


def coverage_group_sha256(policy: Mapping[str, Any]) -> str:
    return proof_document_sha256(
        {
            "contract_version": "proof-coverage-group/v1",
            "target": dict(policy["target"]),
            "candidate": dict(policy["candidate"]),
            "authority_surface_resolution_sha256": policy["authority_bindings"][
                "authority_surface_resolution_sha256"
            ],
            "bootstrap_profile_sha256": policy["authority_bindings"][
                "bootstrap_profile_sha256"
            ],
            "canary_union_sha256": policy["authority_bindings"][
                "canary_union_sha256"
            ],
            "isolation_contract_version": policy["authority_bindings"][
                "isolation_contract_version"
            ],
        }
    )


def finalize_proof_coverage_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _json_copy(value)
    normalized["producer"]["producer_sha256"] = producer_sha256(
        normalized["producer"]
    )
    authority_digest = normalized["authority_bindings"][
        "authority_surface_resolution_sha256"
    ]
    for requirement in normalized["required_roles"]:
        execution = requirement["expected_execution"]
        execution["execution_binding_sha256"] = execution_binding_sha256(
            requirement["expected_check"]["check_id"], execution
        )
        content = {field: requirement[field] for field in _REQUIREMENT_FIELDS}
        content.pop("requirement_sha256", None)
        content["authority_surface_resolution_sha256"] = authority_digest
        requirement["requirement_sha256"] = proof_document_sha256(content)
    normalized["coverage_group_sha256"] = coverage_group_sha256(normalized)
    normalized.pop("policy_sha256", None)
    normalized["policy_sha256"] = proof_document_sha256(normalized)
    return normalized


def finalize_proof_coverage_participant(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _json_copy(value)
    normalized.pop("participant_sha256", None)
    normalized["participant_sha256"] = proof_document_sha256(
        {
            "contract_version": "proof-coverage-participant/v1",
            **normalized,
        }
    )
    return normalized


def finalize_proof_coverage_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _json_copy(value)
    normalized.pop("observation_sha256", None)
    normalized["observation_sha256"] = proof_document_sha256(normalized)
    return normalized


def finalize_proof_coverage_admission(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _json_copy(value)
    normalized.pop("admission_sha256", None)
    normalized["admission_sha256"] = proof_document_sha256(normalized)
    return normalized


def derive_current_proof_match_status(
    participants: Sequence[Mapping[str, Any]],
    final: Mapping[str, Any],
) -> str:
    if _final_indeterminate(final) or any(
        participant["aggregate_current_proof"]["status"] == "indeterminate"
        for participant in participants
    ):
        return "indeterminate"
    final_tuple = _current_tuple(final)
    if any(
        participant["aggregate_current_proof"]["status"] == "changed"
        or _current_tuple(participant["aggregate_current_proof"]) != final_tuple
        for participant in participants
    ):
        return "mismatched"
    return "matched"


def derive_role_freshness(
    attempt_status: str,
    participant_current: Mapping[str, Any] | None,
    final: Mapping[str, Any],
) -> str:
    if attempt_status in {"missing", "not_run"}:
        return "not_observed"
    if participant_current is None:
        raise ValueError("executed observations require participant current proof")
    if (
        participant_current.get("status") == "indeterminate"
        or _final_indeterminate(final)
    ):
        return "indeterminate"
    if (
        participant_current.get("status") == "changed"
        or _current_tuple(participant_current) != _current_tuple(final)
    ):
        return "stale"
    return "current"


def derive_effect_status(
    *,
    kind: str,
    attempt_status: str,
    expectations: Sequence[str],
    canonical_unchanged: bool,
    hwm_equality: bool | None,
) -> str:
    if attempt_status in {"missing", "not_run"}:
        return "not_observed"
    if kind == "full_regression":
        return "not_applicable"
    supported = {"canonical-product-inputs-unchanged", "pcl-state-effect0"}
    expected = set(expectations)
    if expected - supported:
        return "unsupported"
    if "canonical-product-inputs-unchanged" in expected and not canonical_unchanged:
        return "mismatched"
    if "pcl-state-effect0" in expected:
        return "not_disproved" if hwm_equality is True else "unproved"
    return "satisfied"


def derive_admission_state(reason_codes: Sequence[str]) -> str:
    reasons = set(reason_codes)
    for rank in STATE_PRECEDENCE:
        if any(reason in reasons for reason in _REASON_RANKS[rank]):
            return rank
    return "reviewable"


def validate_proof_coverage_policy(value: Any) -> ProofCoverageValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ProofCoverageValidationResult(
            PROOF_COVERAGE_POLICY_CONTRACT_VERSION,
            ("$: must be an object",),
        )
    _policy(value, errors)
    _document_cap(value, "$", errors)
    return ProofCoverageValidationResult(
        PROOF_COVERAGE_POLICY_CONTRACT_VERSION,
        tuple(errors),
    )


def validate_proof_coverage_admission(value: Any) -> ProofCoverageValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ProofCoverageValidationResult(
            PROOF_COVERAGE_ADMISSION_CONTRACT_VERSION,
            ("$: must be an object",),
        )
    _admission(value, errors)
    _document_cap(value, "$", errors)
    return ProofCoverageValidationResult(
        PROOF_COVERAGE_ADMISSION_CONTRACT_VERSION,
        tuple(errors),
    )


def _policy(value: dict[str, Any], errors: list[str]) -> None:
    _exact(value, "$", _POLICY_FIELDS, errors)
    if value.get("contract_version") != PROOF_COVERAGE_POLICY_CONTRACT_VERSION:
        errors.append("$.contract_version: unsupported policy contract")
    _identifier(value.get("policy_id"), "$.policy_id", errors)
    producer = value.get("producer")
    if not isinstance(producer, dict):
        errors.append("$.producer: must be an object")
    else:
        _exact(
            producer,
            "$.producer",
            {"kind", "producer_id", "producer_sha256", "candidate_controlled"},
            errors,
        )
        _enum(
            producer.get("kind"),
            {"external_bootstrap", "pinned_installed", "trusted_planner"},
            "$.producer.kind",
            errors,
        )
        _identifier(producer.get("producer_id"), "$.producer.producer_id", errors)
        _sha(producer.get("producer_sha256"), "$.producer.producer_sha256", errors)
        if producer.get("candidate_controlled") is not False:
            errors.append("$.producer.candidate_controlled: must equal false")
        try:
            if producer.get("producer_sha256") != producer_sha256(producer):
                errors.append("$.producer.producer_sha256: digest mismatch")
        except (KeyError, TypeError, ValueError):
            pass
    target = value.get("target")
    if not isinstance(target, dict):
        errors.append("$.target: must be an object")
    else:
        _exact(target, "$.target", {"type", "id"}, errors)
        if target.get("type") != "task":
            errors.append("$.target.type: must equal 'task'")
        _identifier(target.get("id"), "$.target.id", errors)
    candidate = value.get("candidate")
    object_format: str | None = None
    if not isinstance(candidate, dict):
        errors.append("$.candidate: must be an object")
    else:
        _exact(candidate, "$.candidate", {"object_format", "commit_oid", "tree_oid"}, errors)
        object_format = candidate.get("object_format")
        _enum(object_format, set(_OID), "$.candidate.object_format", errors)
        for field in ("commit_oid", "tree_oid"):
            _oid(candidate.get(field), object_format, f"$.candidate.{field}", errors)
    authority = value.get("authority_bindings")
    if not isinstance(authority, dict):
        errors.append("$.authority_bindings: must be an object")
    else:
        _exact(
            authority,
            "$.authority_bindings",
            {
                "authority_surface_resolution_sha256",
                "bootstrap_profile_sha256",
                "canary_union_sha256",
                "isolation_contract_version",
            },
            errors,
        )
        for field in (
            "authority_surface_resolution_sha256",
            "bootstrap_profile_sha256",
            "canary_union_sha256",
        ):
            _sha(authority.get(field), f"$.authority_bindings.{field}", errors)
        if authority.get("isolation_contract_version") != "proof-workspace-isolation/v1":
            errors.append("$.authority_bindings.isolation_contract_version: invalid")
    _sha(value.get("coverage_group_sha256"), "$.coverage_group_sha256", errors)
    requirements = value.get("required_roles")
    if not isinstance(requirements, list) or not (1 <= len(requirements) <= MAX_REQUIRED_ROLES):
        errors.append("$.required_roles: must contain 1..4096 requirements")
        requirements = []
    roles: list[str] = []
    canary_ids: list[str] = []
    full_count = 0
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            errors.append(f"$.required_roles[{index}]: must be an object")
            continue
        _requirement(
            requirement,
            f"$.required_roles[{index}]",
            object_format,
            authority.get("authority_surface_resolution_sha256")
            if isinstance(authority, dict)
            else None,
            errors,
        )
        role = requirement.get("role")
        if isinstance(role, str):
            roles.append(role)
        if requirement.get("kind") == "full_regression":
            full_count += 1
        canary_id = requirement.get("canary_id")
        if isinstance(canary_id, str):
            canary_ids.append(canary_id)
    if full_count != 1:
        errors.append("$.required_roles: exactly one full_regression is required")
    if len(roles) != len(set(roles)):
        errors.append("$.required_roles: roles must be unique")
    if len(canary_ids) != len(set(canary_ids)):
        errors.append("$.required_roles: canary IDs must be unique")
    if isinstance(requirements, list):
        expected_order = sorted(
            requirements,
            key=lambda item: (
                0 if isinstance(item, dict) and item.get("kind") == "full_regression" else 1,
                str(item.get("role")) if isinstance(item, dict) else "",
            ),
        )
        if requirements != expected_order:
            errors.append("$.required_roles: requirements must be canonically ordered")
    authorization = value.get("authorization_requirements")
    if not isinstance(authorization, dict):
        errors.append("$.authorization_requirements: must be an object")
    else:
        _exact(
            authorization,
            "$.authorization_requirements",
            {"independent_review", "human_gate", "self_certification_allowed"},
            errors,
        )
        if authorization.get("independent_review") != "required":
            errors.append("$.authorization_requirements.independent_review: must be required")
        _enum(
            authorization.get("human_gate"),
            {"required", "not_required"},
            "$.authorization_requirements.human_gate",
            errors,
        )
        if authorization.get("self_certification_allowed") is not False:
            errors.append(
                "$.authorization_requirements.self_certification_allowed: must equal false"
            )
    for field in ("terminal_authority", "mandatory_evidence"):
        if value.get(field) is not False:
            errors.append(f"$.{field}: must equal false")
    _sha(value.get("policy_sha256"), "$.policy_sha256", errors)
    try:
        if value.get("coverage_group_sha256") != coverage_group_sha256(value):
            errors.append("$.coverage_group_sha256: digest mismatch")
        content = dict(value)
        recorded = content.pop("policy_sha256", None)
        if recorded != proof_document_sha256(content):
            errors.append("$.policy_sha256: digest mismatch")
    except (KeyError, TypeError, ValueError):
        errors.append("$: policy digest preimage is invalid")


def _requirement(
    value: dict[str, Any],
    path: str,
    object_format: str | None,
    authority_digest: Any,
    errors: list[str],
) -> None:
    _exact(value, path, _REQUIREMENT_FIELDS, errors)
    role = value.get("role")
    _identifier(role, f"{path}.role", errors)
    kind = value.get("kind")
    _enum(kind, {"full_regression", "authority_canary"}, f"{path}.kind", errors)
    canary_id = value.get("canary_id")
    canary_digest = value.get("canary_item_sha256")
    labels = value.get("selector_audit_labels")
    if kind == "full_regression":
        if canary_id is not None or canary_digest is not None:
            errors.append(f"{path}: full_regression canary fields must be null")
    elif kind == "authority_canary":
        _canary_identifier(canary_id, f"{path}.canary_id", errors)
        _sha(canary_digest, f"{path}.canary_item_sha256", errors)
        if isinstance(canary_id, str) and role != f"authority_canary.{canary_id}":
            errors.append(f"{path}.role: must bind the canary ID")
        if not isinstance(labels, list) or not labels:
            errors.append(f"{path}.selector_audit_labels: canary labels must be non-empty")
    if value.get("expected_outcome") != "pass":
        errors.append(f"{path}.expected_outcome: must equal 'pass'")
    check = value.get("expected_check")
    if not isinstance(check, dict):
        errors.append(f"{path}.expected_check: must be an object")
    else:
        _expected_check(check, f"{path}.expected_check", object_format, errors)
        if check.get("role") != role:
            errors.append(f"{path}.expected_check.role: must equal requirement role")
        selectors = check.get("selectors")
        if isinstance(selectors, list) and labels != sorted(selectors):
            errors.append(f"{path}.selector_audit_labels: must equal sorted selectors")
    _sorted_unique_strings(labels, f"{path}.selector_audit_labels", errors, 4096)
    required_blobs = value.get("required_candidate_blobs")
    _blobs(required_blobs, f"{path}.required_candidate_blobs", object_format, errors)
    if isinstance(check, dict) and required_blobs != check.get("referenced_git_blobs"):
        errors.append(f"{path}.required_candidate_blobs: must equal expected check blobs")
    execution = value.get("expected_execution")
    if not isinstance(execution, dict):
        errors.append(f"{path}.expected_execution: must be an object")
    else:
        _exact(execution, f"{path}.expected_execution", _EXPECTED_EXECUTION_FIELDS, errors)
        for field in _EXPECTED_EXECUTION_FIELDS:
            if field == "spawn_vector_sha256" and execution.get(field) is None:
                continue
            _sha(execution.get(field), f"{path}.expected_execution.{field}", errors)
        try:
            check_id = check["check_id"] if isinstance(check, dict) else ""
            if execution.get("execution_binding_sha256") != execution_binding_sha256(
                check_id, execution
            ):
                errors.append(f"{path}.expected_execution.execution_binding_sha256: mismatch")
        except (KeyError, TypeError, ValueError):
            pass
    _sha(value.get("requirement_sha256"), f"{path}.requirement_sha256", errors)
    try:
        content = {field: value[field] for field in _REQUIREMENT_FIELDS}
        recorded = content.pop("requirement_sha256")
        content["authority_surface_resolution_sha256"] = authority_digest
        if recorded != proof_document_sha256(content):
            errors.append(f"{path}.requirement_sha256: digest mismatch")
    except (KeyError, TypeError, ValueError):
        pass


def _expected_check(
    value: dict[str, Any],
    path: str,
    object_format: str | None,
    errors: list[str],
) -> None:
    _exact(value, path, _EXPECTED_CHECK_FIELDS, errors)
    _identifier(value.get("check_id"), f"{path}.check_id", errors)
    _identifier(value.get("role"), f"{path}.role", errors)
    argv = value.get("argv")
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 256
        or any(not isinstance(item, str) or not item or "\0" in item for item in argv)
    ):
        errors.append(f"{path}.argv: must contain 1..256 nonempty NUL-free strings")
    _relative_path(value.get("cwd"), f"{path}.cwd", errors, allow_dot=True)
    _unique_strings(value.get("selectors"), f"{path}.selectors", errors, 4096)
    _blobs(value.get("referenced_git_blobs"), f"{path}.referenced_git_blobs", object_format, errors)
    _sorted_unique_strings(value.get("input_ids"), f"{path}.input_ids", errors, 4096)
    environment = value.get("environment")
    if not isinstance(environment, dict):
        errors.append(f"{path}.environment: must be an object")
    else:
        _exact(environment, f"{path}.environment", {"inherit_names", "workspace_pythonpath"}, errors)
        _sorted_unique_strings(
            environment.get("inherit_names"),
            f"{path}.environment.inherit_names",
            errors,
            4096,
        )
        _unique_strings(
            environment.get("workspace_pythonpath"),
            f"{path}.environment.workspace_pythonpath",
            errors,
            4096,
        )
    _bounded_int(value.get("timeout_seconds"), f"{path}.timeout_seconds", errors, 86_400)
    _bounded_int(value.get("max_output_bytes"), f"{path}.max_output_bytes", errors, 104_857_600)
    _sorted_unique_strings(value.get("declared_outputs"), f"{path}.declared_outputs", errors, 4096)


def _admission(value: dict[str, Any], errors: list[str]) -> None:
    _exact(value, "$", _ADMISSION_FIELDS, errors)
    if value.get("contract_version") != PROOF_COVERAGE_ADMISSION_CONTRACT_VERSION:
        errors.append("$.contract_version: unsupported admission contract")
    _sha(value.get("policy_sha256"), "$.policy_sha256", errors)
    _sha(value.get("coverage_group_sha256"), "$.coverage_group_sha256", errors)
    raw_participants = value.get("participants")
    participants: list[dict[str, Any]] = []
    if not isinstance(raw_participants, list) or not 1 <= len(raw_participants) <= MAX_PARTICIPANTS:
        errors.append("$.participants: must contain 1..256 participants")
    else:
        for index, participant in enumerate(raw_participants):
            if not isinstance(participant, dict):
                errors.append(f"$.participants[{index}]: must be an object")
                continue
            _participant(participant, f"$.participants[{index}]", errors)
            participants.append(participant)
        digests = [item.get("participant_sha256") for item in participants]
        if digests != sorted(digests):
            errors.append("$.participants: must be sorted by participant digest")
    current = value.get("current_proof")
    if not isinstance(current, dict):
        errors.append("$.current_proof: must be an object")
        current = {}
    else:
        _current_proof(current, "$.current_proof", errors)
        try:
            expected_match = derive_current_proof_match_status(participants, current)
            if current.get("match_status") != expected_match:
                errors.append("$.current_proof.match_status: total-function mismatch")
        except (KeyError, TypeError, ValueError):
            pass
    raw_observations = value.get("role_observations")
    observations: list[dict[str, Any]] = []
    participant_by_digest = {
        item.get("participant_sha256"): item for item in participants
    }
    if not isinstance(raw_observations, list) or not 1 <= len(raw_observations) <= MAX_REQUIRED_ROLES:
        errors.append("$.role_observations: must contain 1..4096 observations")
    else:
        for index, observation in enumerate(raw_observations):
            if not isinstance(observation, dict):
                errors.append(f"$.role_observations[{index}]: must be an object")
                continue
            _observation(
                observation,
                f"$.role_observations[{index}]",
                participant_by_digest,
                current,
                errors,
            )
            observations.append(observation)
    reasons = value.get("state_reason_codes")
    _sorted_unique_strings(reasons, "$.state_reason_codes", errors, MAX_REASON_CODES)
    if isinstance(reasons, list):
        unknown = sorted(set(reasons) - set(REASON_TO_RANK))
        if unknown:
            errors.append("$.state_reason_codes: contains unknown reason codes")
        expected_current = _current_reason_codes(participants, current)
        current_domain = {
            "current_proof_indeterminate",
            "participant_current_proof_indeterminate",
            "participant_current_proof_changed",
            "current_proof_mismatch",
            "current_proof_unhealthy",
        }
        if set(reasons) & current_domain != expected_current:
            errors.append("$.state_reason_codes: current-proof source edges mismatch")
        expected_state = derive_admission_state(reasons)
        if value.get("admission_state") != expected_state:
            errors.append("$.admission_state: does not match reason precedence")
        if (not reasons) != (value.get("admission_state") == "reviewable"):
            errors.append("$.state_reason_codes: empty iff reviewable")
    _enum(
        value.get("admission_state"),
        {"invalid", "indeterminate", "stale", "blocked", "incomplete", "reviewable"},
        "$.admission_state",
        errors,
    )
    expected_readiness = "ready" if value.get("admission_state") == "reviewable" else "withheld"
    if value.get("review_readiness") != expected_readiness:
        errors.append("$.review_readiness: must follow admission state")
    promotion = value.get("promotion_withholding_codes")
    _sorted_unique_strings(promotion, "$.promotion_withholding_codes", errors, MAX_REASON_CODES)
    expected_promotion = _promotion_codes(participants)
    if promotion != expected_promotion:
        errors.append("$.promotion_withholding_codes: participant facts mismatch")
    candidate = value.get("admission_state") == "reviewable" and not expected_promotion
    expected_suitability = "candidate" if candidate else "withheld"
    if value.get("promotion_suitability") != expected_suitability:
        errors.append("$.promotion_suitability: must follow factual suitability")
    authorization = value.get("authorization_status")
    if not isinstance(authorization, dict):
        errors.append("$.authorization_status: must be an object")
    else:
        _exact(
            authorization,
            "$.authorization_status",
            {
                "independent_review",
                "human_gate",
                "anchoring_authorized",
                "reuse_authorized",
                "terminal_authority",
                "mandatory_evidence",
            },
            errors,
        )
        if authorization.get("independent_review") != "pending":
            errors.append("$.authorization_status.independent_review: must be pending")
        _enum(
            authorization.get("human_gate"),
            {"pending", "not_required"},
            "$.authorization_status.human_gate",
            errors,
        )
        for field in (
            "anchoring_authorized",
            "reuse_authorized",
            "terminal_authority",
            "mandatory_evidence",
        ):
            if authorization.get(field) is not False:
                errors.append(f"$.authorization_status.{field}: must equal false")
    if value.get("effects") != EFFECTS_ZERO:
        errors.append("$.effects: must be the effect-zero runtime matrix")
    _sha(value.get("admission_sha256"), "$.admission_sha256", errors)
    try:
        content = dict(value)
        recorded = content.pop("admission_sha256")
        if recorded != proof_document_sha256(content):
            errors.append("$.admission_sha256: digest mismatch")
    except (KeyError, TypeError, ValueError):
        pass


def _participant(value: dict[str, Any], path: str, errors: list[str]) -> None:
    _exact(value, path, _PARTICIPANT_FIELDS, errors)
    for field in (
        "participant_sha256",
        "participant_group_sha256",
        "spec_sha256",
        "workspace_binding_sha256",
        "proof_key_sha256",
        "verification_profile_sha256",
        "check_plan_sha256",
        "external_input_binding_sha256",
        "packet_sha256",
        "executor_contract_sha256",
        "aggregate_sha256",
        "bundle_sha256",
    ):
        _sha(value.get(field), f"{path}.{field}", errors)
    _enum(value.get("aggregate_verdict"), _VERDICTS, f"{path}.aggregate_verdict", errors)
    _enum(
        value.get("aggregate_output_commitment_status"),
        {"committed", "uncommitted"},
        f"{path}.aggregate_output_commitment_status",
        errors,
    )
    _enum(
        value.get("aggregate_reuse_disposition"),
        {"eligible", "fresh_only"},
        f"{path}.aggregate_reuse_disposition",
        errors,
    )
    if not isinstance(value.get("aggregate_anchoring_eligible"), bool):
        errors.append(f"{path}.aggregate_anchoring_eligible: must be a boolean")
    _enum(
        value.get("aggregate_positive_proof_handoff"),
        {"candidate", "withheld"},
        f"{path}.aggregate_positive_proof_handoff",
        errors,
    )
    _aggregate_current_proof(value.get("aggregate_current_proof"), f"{path}.aggregate_current_proof", errors)
    try:
        content = {field: value[field] for field in _PARTICIPANT_FIELDS}
        recorded = content.pop("participant_sha256")
        expected = proof_document_sha256(
            {"contract_version": "proof-coverage-participant/v1", **content}
        )
        if recorded != expected:
            errors.append(f"{path}.participant_sha256: digest mismatch")
    except (KeyError, TypeError, ValueError):
        pass


def _observation(
    value: dict[str, Any],
    path: str,
    participants: Mapping[Any, Mapping[str, Any]],
    current: Mapping[str, Any],
    errors: list[str],
) -> None:
    _exact(value, path, _OBSERVATION_FIELDS, errors)
    if value.get("contract_version") != PROOF_COVERAGE_OBSERVATION_CONTRACT_VERSION:
        errors.append(f"{path}.contract_version: unsupported observation contract")
    _identifier(value.get("role"), f"{path}.role", errors)
    kind = value.get("kind")
    _enum(kind, {"full_regression", "authority_canary"}, f"{path}.kind", errors)
    if kind == "full_regression":
        if value.get("canary_id") is not None:
            errors.append(f"{path}.canary_id: full regression requires null")
    else:
        _canary_identifier(value.get("canary_id"), f"{path}.canary_id", errors)
    _sha(value.get("requirement_sha256"), f"{path}.requirement_sha256", errors)
    matching = value.get("matching_checks")
    if not isinstance(matching, list) or len(matching) > MAX_CHECKS:
        errors.append(f"{path}.matching_checks: must be an array of at most 4096")
        matching = []
    else:
        for index, match in enumerate(matching):
            if not isinstance(match, dict):
                errors.append(f"{path}.matching_checks[{index}]: must be an object")
                continue
            _exact(match, f"{path}.matching_checks[{index}]", {"participant_sha256", "check_id"}, errors)
            _sha(match.get("participant_sha256"), f"{path}.matching_checks[{index}].participant_sha256", errors)
            _identifier(match.get("check_id"), f"{path}.matching_checks[{index}].check_id", errors)
        expected_matching = sorted(
            matching,
            key=lambda item: (str(item.get("participant_sha256")), str(item.get("check_id")))
            if isinstance(item, dict)
            else ("", ""),
        )
        if matching != expected_matching or len({json.dumps(item, sort_keys=True) for item in matching}) != len(matching):
            errors.append(f"{path}.matching_checks: must be sorted and unique")
    attempt = value.get("attempt_status")
    _enum(attempt, {"missing", "not_run", "executed"}, f"{path}.attempt_status", errors)
    selected = value.get("selected_participant_sha256")
    check_id = value.get("check_id")
    aggregate_fields = (
        "aggregate_verdict",
        "aggregate_reuse_disposition",
        "aggregate_anchoring_eligible",
        "aggregate_positive_proof_handoff",
        "output_commitment_status",
    )
    execution_fields = (
        "attempt_sha256",
        "result_sha256",
        "receipt_sha256",
        "c3_verdict",
    )
    if attempt == "missing":
        if matching:
            errors.append(f"{path}.matching_checks: missing requires empty")
        for field in ("selected_participant_sha256", "check_id", *execution_fields, *aggregate_fields):
            if value.get(field) is not None:
                errors.append(f"{path}.{field}: missing requires null")
    else:
        if not matching:
            errors.append(f"{path}.matching_checks: observed role requires non-empty")
        _sha(selected, f"{path}.selected_participant_sha256", errors)
        _identifier(check_id, f"{path}.check_id", errors)
        if matching and (selected, check_id) != (
            matching[0].get("participant_sha256"),
            matching[0].get("check_id"),
        ):
            errors.append(f"{path}: selected check must be the deterministic first match")
        participant = participants.get(selected)
        if participant is None:
            errors.append(f"{path}.selected_participant_sha256: participant not found")
        else:
            expected_aggregate = {
                "aggregate_verdict": participant.get("aggregate_verdict"),
                "aggregate_reuse_disposition": participant.get("aggregate_reuse_disposition"),
                "aggregate_anchoring_eligible": participant.get("aggregate_anchoring_eligible"),
                "aggregate_positive_proof_handoff": participant.get("aggregate_positive_proof_handoff"),
                "output_commitment_status": participant.get("aggregate_output_commitment_status"),
            }
            for field, expected in expected_aggregate.items():
                if value.get(field) != expected:
                    errors.append(f"{path}.{field}: must equal selected aggregate fact")
        if attempt == "not_run":
            for field in execution_fields:
                if value.get(field) is not None:
                    errors.append(f"{path}.{field}: not_run requires null")
        else:
            for field in ("attempt_sha256", "result_sha256", "receipt_sha256"):
                _sha(value.get(field), f"{path}.{field}", errors)
            _enum(value.get("c3_verdict"), _VERDICTS, f"{path}.c3_verdict", errors)
    for field, allowed in (
        ("plan_binding_status", {"not_observed", "matched", "mismatched"}),
        ("selector_audit_status", {"not_observed", "not_applicable", "matched", "mismatched"}),
        ("candidate_blob_status", {"not_observed", "matched", "missing", "oid_mismatch", "unsupported_type", "indeterminate"}),
        ("effect_status", {"not_observed", "not_applicable", "satisfied", "not_disproved", "unproved", "mismatched", "unsupported"}),
        ("freshness", {"not_observed", "current", "stale", "indeterminate"}),
    ):
        _enum(value.get(field), allowed, f"{path}.{field}", errors)
    blob_digest = value.get("candidate_blob_resolution_sha256")
    if attempt == "missing":
        if blob_digest is not None:
            errors.append(f"{path}.candidate_blob_resolution_sha256: missing requires null")
    else:
        _sha(blob_digest, f"{path}.candidate_blob_resolution_sha256", errors)
    if attempt == "missing":
        expected_statuses = {
            "plan_binding_status": "not_observed",
            "selector_audit_status": "not_applicable" if kind == "full_regression" else "not_observed",
            "candidate_blob_status": "not_observed",
            "effect_status": "not_applicable" if kind == "full_regression" else "not_observed",
            "freshness": "not_observed",
        }
    elif attempt == "not_run":
        expected_statuses = {
            "selector_audit_status": "not_applicable" if kind == "full_regression" else value.get("selector_audit_status"),
            "effect_status": "not_applicable" if kind == "full_regression" else "not_observed",
            "freshness": "not_observed",
        }
    else:
        expected_statuses = {
            "selector_audit_status": "not_applicable" if kind == "full_regression" else value.get("selector_audit_status"),
            "effect_status": "not_applicable" if kind == "full_regression" else value.get("effect_status"),
        }
        participant = participants.get(selected)
        if participant is not None:
            try:
                freshness = derive_role_freshness(
                    "executed", participant["aggregate_current_proof"], current
                )
                expected_statuses["freshness"] = freshness
            except (KeyError, TypeError, ValueError):
                pass
    for field, expected in expected_statuses.items():
        if value.get(field) != expected:
            errors.append(f"{path}.{field}: status-matrix mismatch")
    _sha(value.get("observation_sha256"), f"{path}.observation_sha256", errors)
    try:
        content = dict(value)
        recorded = content.pop("observation_sha256")
        if recorded != proof_document_sha256(content):
            errors.append(f"{path}.observation_sha256: digest mismatch")
    except (KeyError, TypeError, ValueError):
        pass


def _aggregate_current_proof(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    _exact(value, path, {"scope", "status", "proof_sha256"}, errors)
    scope = value.get("scope")
    status = value.get("status")
    _enum(scope, {"feature", "not_applicable"}, f"{path}.scope", errors)
    _enum(status, _AGGREGATE_CURRENT_STATUSES, f"{path}.status", errors)
    if status == "indeterminate":
        if value.get("proof_sha256") is not None:
            errors.append(f"{path}.proof_sha256: indeterminate requires null")
    else:
        _sha(value.get("proof_sha256"), f"{path}.proof_sha256", errors)
    if scope == "not_applicable" and status not in {"not_applicable", "changed", "indeterminate"}:
        errors.append(f"{path}.status: incompatible with not_applicable scope")
    if scope == "feature" and status == "not_applicable":
        errors.append(f"{path}.status: feature scope cannot be not_applicable")


def _current_proof(value: dict[str, Any], path: str, errors: list[str]) -> None:
    _exact(value, path, {"scope", "status", "proof_sha256", "match_status"}, errors)
    scope = value.get("scope")
    status = value.get("status")
    _enum(scope, {"feature", "not_applicable", "unknown"}, f"{path}.scope", errors)
    _enum(status, {"healthy", "unhealthy", "not_applicable", "indeterminate"}, f"{path}.status", errors)
    _enum(value.get("match_status"), {"matched", "mismatched", "indeterminate"}, f"{path}.match_status", errors)
    if scope == "unknown" or status == "indeterminate":
        if scope != "unknown" or status != "indeterminate" or value.get("proof_sha256") is not None:
            errors.append(f"{path}: unknown/indeterminate/null must be one exact tuple")
    else:
        _sha(value.get("proof_sha256"), f"{path}.proof_sha256", errors)
        if scope == "feature" and status not in {"healthy", "unhealthy"}:
            errors.append(f"{path}.status: feature requires healthy or unhealthy")
        if scope == "not_applicable" and status != "not_applicable":
            errors.append(f"{path}.status: not_applicable scope requires matching status")


def _current_reason_codes(
    participants: Sequence[Mapping[str, Any]],
    final: Mapping[str, Any],
) -> set[str]:
    reasons: set[str] = set()
    final_indeterminate = _final_indeterminate(final)
    if final_indeterminate:
        reasons.add("current_proof_indeterminate")
    if final.get("status") == "unhealthy":
        reasons.add("current_proof_unhealthy")
    final_tuple = _current_tuple(final)
    for participant in participants:
        current = participant.get("aggregate_current_proof", {})
        status = current.get("status")
        if status == "indeterminate":
            reasons.add("participant_current_proof_indeterminate")
        if status == "changed":
            reasons.add("participant_current_proof_changed")
        if not final_indeterminate and status != "indeterminate" and _current_tuple(current) != final_tuple:
            reasons.add("current_proof_mismatch")
    return reasons


def _promotion_codes(participants: Sequence[Mapping[str, Any]]) -> list[str]:
    reasons: set[str] = set()
    for participant in participants:
        if participant.get("aggregate_reuse_disposition") == "fresh_only":
            reasons.add("participant_fresh_only")
        if participant.get("aggregate_output_commitment_status") == "uncommitted":
            reasons.add("participant_output_uncommitted")
        if participant.get("aggregate_anchoring_eligible") is False:
            reasons.add("participant_anchoring_ineligible")
        if participant.get("aggregate_positive_proof_handoff") == "withheld":
            reasons.add("participant_handoff_withheld")
    return sorted(reasons)


def _final_indeterminate(value: Mapping[str, Any]) -> bool:
    return (
        value.get("scope") == "unknown"
        or value.get("status") == "indeterminate"
        or value.get("proof_sha256") is None
    )


def _current_tuple(value: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return value.get("scope"), value.get("status"), value.get("proof_sha256")


def _blobs(value: Any, path: str, object_format: str | None, errors: list[str]) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 256:
        errors.append(f"{path}: must contain 1..256 blob bindings")
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_path}: must be an object")
            continue
        _exact(item, item_path, {"path", "oid"}, errors)
        _relative_path(item.get("path"), f"{item_path}.path", errors)
        _oid(item.get("oid"), object_format, f"{item_path}.oid", errors)
        if isinstance(item.get("path"), str):
            if item["path"] in seen:
                errors.append(f"{item_path}.path: must be unique")
            seen.add(item["path"])
    expected = sorted(
        value,
        key=lambda item: (str(item.get("path")), str(item.get("oid")))
        if isinstance(item, dict)
        else ("", ""),
    )
    if value != expected:
        errors.append(f"{path}: must be sorted by path and oid")


def _schema(resource: str) -> dict[str, Any]:
    return json.loads(files("pcl.contracts").joinpath(resource).read_text(encoding="utf-8"))


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _document_cap(value: Mapping[str, Any], path: str, errors: list[str]) -> None:
    try:
        if len(canonical_proof_coverage_bytes(value)) > MAX_CANONICAL_DOCUMENT_BYTES:
            errors.append(f"{path}: canonical document exceeds 16777216 bytes")
    except (TypeError, ValueError):
        errors.append(f"{path}: must be finite canonical JSON data")


def _exact(value: Mapping[str, Any], path: str, expected: set[str], errors: list[str]) -> None:
    for field in sorted(expected - set(value)):
        errors.append(f"{path}.{field}: is required")
    for field in sorted(set(value) - expected):
        errors.append(f"{path}.{field}: additional property is not allowed")


def _identifier(value: Any, path: str, errors: list[str]) -> None:
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > 4096
        or _PUBLIC_ID.fullmatch(value) is None
    ):
        errors.append(f"{path}: must be a 1..4096 byte ASCII public identifier")


def _canary_identifier(value: Any, path: str, errors: list[str]) -> None:
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > 4079
        or _CANARY_ID.fullmatch(value) is None
    ):
        errors.append(f"{path}: must be a 1..4079 byte lowercase canary identifier")


def _sha(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        errors.append(f"{path}: must be sha256:<64 lowercase hex>")


def _oid(value: Any, object_format: Any, path: str, errors: list[str]) -> None:
    matcher = _OID.get(object_format) if isinstance(object_format, str) else None
    if matcher is None or not isinstance(value, str) or matcher.fullmatch(value) is None:
        errors.append(f"{path}: must be a full lowercase {object_format or 'Git'} OID")


def _enum(value: Any, allowed: set[str], path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or value not in allowed:
        errors.append(f"{path}: unsupported value")


def _relative_path(
    value: Any,
    path: str,
    errors: list[str],
    *,
    allow_dot: bool = False,
) -> None:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 4096:
        errors.append(f"{path}: must be a normalized relative POSIX path")
        return
    if value == ".":
        if allow_dot:
            return
        errors.append(f"{path}: '.' is not allowed")
        return
    pure = PurePosixPath(value)
    if (
        not value
        or "\0" in value
        or "\\" in value
        or value != unicodedata.normalize("NFC", value)
        or pure.is_absolute()
        or str(pure) != value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        errors.append(f"{path}: must be a normalized relative POSIX path")


def _unique_strings(value: Any, path: str, errors: list[str], maximum: int) -> None:
    if not isinstance(value, list) or len(value) > maximum:
        errors.append(f"{path}: must be an array of at most {maximum}")
        return
    if any(
        not isinstance(item, str)
        or not item
        or "\0" in item
        or len(item.encode("utf-8")) > 4096
        for item in value
    ):
        errors.append(f"{path}: must contain nonempty NUL-free strings")
        return
    if len(value) != len(set(value)):
        errors.append(f"{path}: values must be unique")


def _sorted_unique_strings(value: Any, path: str, errors: list[str], maximum: int) -> None:
    _unique_strings(value, path, errors, maximum)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        if value != sorted(value):
            errors.append(f"{path}: values must be sorted")


def _bounded_int(value: Any, path: str, errors: list[str], maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        errors.append(f"{path}: must be an integer from 1 through {maximum}")


__all__ = [
    "EFFECTS_ZERO",
    "MAX_CANONICAL_DOCUMENT_BYTES",
    "PROOF_COVERAGE_ADMISSION_CONTRACT_VERSION",
    "PROOF_COVERAGE_OBSERVATION_CONTRACT_VERSION",
    "PROOF_COVERAGE_POLICY_CONTRACT_VERSION",
    "PROMOTION_WITHHOLDING_CODES",
    "ProofCoverageValidationResult",
    "REASON_TO_RANK",
    "STATE_PRECEDENCE",
    "canary_item_sha256",
    "canonical_proof_coverage_bytes",
    "coverage_group_sha256",
    "derive_admission_state",
    "derive_current_proof_match_status",
    "derive_effect_status",
    "derive_role_freshness",
    "environment_binding_sha256",
    "execution_binding_sha256",
    "finalize_proof_coverage_admission",
    "finalize_proof_coverage_observation",
    "finalize_proof_coverage_participant",
    "finalize_proof_coverage_policy",
    "producer_sha256",
    "proof_coverage_admission_schema",
    "proof_coverage_policy_schema",
    "validate_proof_coverage_admission",
    "validate_proof_coverage_policy",
]
