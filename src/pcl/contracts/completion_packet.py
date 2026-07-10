from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


COMPLETION_PACKET_CONTRACT_VERSION = "completion-packet/v1"
SCHEMA_RESOURCE = "schemas/completion-packet-v1.schema.json"

_TOP_LEVEL_FIELDS = {
    "contract_version",
    "packet_id",
    "producer",
    "generated_at",
    "outcome",
    "target",
    "repository",
    "changes",
    "checks",
    "claims",
    "unverified_claims",
    "risks",
    "human_decisions",
    "next_action",
    "verifier_provenance",
}
_REQUIRED_TOP_LEVEL_FIELDS = _TOP_LEVEL_FIELDS - {"verifier_provenance"}
_OUTCOMES = {
    "COMPLETED_VERIFIED",
    "COMPLETED_WITH_RISK",
    "INCOMPLETE_VALIDATION",
    "INCOMPLETE_BUDGET_EXHAUSTED",
    "INCOMPLETE_HUMAN_DECISION_REQUIRED",
    "NO_CHANGES",
}
_COMPLETED_OUTCOMES = {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"}
_CHECK_STATUSES = {"passed", "failed", "skipped", "not_run", "timed_out"}
_CHANGE_TYPES = {"added", "modified", "deleted", "renamed", "untracked"}
_PROOF_LEVELS = {"L0", "L1", "L2", "L3", "L4"}
_RISK_LEVELS = {"low", "medium", "high", "critical"}
_TARGET_PATTERNS = {
    "goal": re.compile(r"^G-[0-9]{4,}$"),
    "task": re.compile(r"^T-[0-9]{4,}$"),
}
_EVIDENCE_REF = re.compile(r"^evidence:E-[0-9]{4,}$")
_PACKET_ID = re.compile(r"^cp-sha256:[0-9a-f]{64}$")
_DIFF_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
)


@dataclass(frozen=True)
class CompletionPacketValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": COMPLETION_PACKET_CONTRACT_VERSION,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def completion_packet_schema() -> dict[str, Any]:
    """Read the authoritative packaged JSON Schema through importlib.resources."""

    resource = files("pcl.contracts").joinpath(SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def canonical_json(packet: Mapping[str, Any]) -> str:
    """Serialize a packet as canonical UTF-8 JSON with stable key ordering."""

    return json.dumps(
        packet,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def compute_packet_id(packet: Mapping[str, Any]) -> str:
    """Return the content-derived ID, excluding the circular packet_id field."""

    content = dict(packet)
    content.pop("packet_id", None)
    digest = hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()
    return f"cp-sha256:{digest}"


def with_computed_packet_id(packet: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(packet))
    result["packet_id"] = compute_packet_id(result)
    return result


def load_completion_packet(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_non_finite_json_number)


def calculate_proof_level(evidence_classes: Iterable[str]) -> str:
    """Calculate deterministic claim proof from factual evidence classes.

    Unknown classes fail closed. A model review, with or without an artifact
    reference, can never raise a claim above L1.
    """

    classes = frozenset(evidence_classes)
    if "production_observation" in classes:
        return "L4"
    if "independent_reproduction" in classes:
        return "L3"
    if "executed_check" in classes:
        return "L2"
    if classes & {"artifact_ref", "model_review"}:
        return "L1"
    return "L0"


def validate_completion_packet(packet: Any) -> CompletionPacketValidationResult:
    errors: list[str] = []
    if not isinstance(packet, dict):
        return CompletionPacketValidationResult(("$: must be an object",))

    non_finite_errors: list[str] = []
    _collect_non_finite_json_numbers(packet, path="$", errors=non_finite_errors)
    errors.extend(non_finite_errors)

    _check_object_fields(
        packet,
        path="$",
        required=_REQUIRED_TOP_LEVEL_FIELDS,
        allowed=_TOP_LEVEL_FIELDS,
        errors=errors,
    )
    _expect_equal(packet.get("contract_version"), COMPLETION_PACKET_CONTRACT_VERSION, "$.contract_version", errors)
    _validate_string(packet.get("packet_id"), "$.packet_id", errors, pattern=_PACKET_ID)
    _validate_timestamp(packet.get("generated_at"), "$.generated_at", errors)
    _expect_enum(packet.get("outcome"), _OUTCOMES, "$.outcome", errors)

    _validate_producer(packet.get("producer"), errors)
    _validate_target(packet.get("target"), errors)
    _validate_repository(packet.get("repository"), errors)
    _validate_changes(packet.get("changes"), errors)
    _validate_checks(packet.get("checks"), errors)
    _validate_claims(packet.get("claims"), errors)
    _validate_unverified_claims(packet.get("unverified_claims"), errors)
    _validate_risks(packet.get("risks"), errors)
    _validate_string_array(packet.get("human_decisions"), "$.human_decisions", errors)
    _validate_next_action(packet.get("next_action"), errors)
    _validate_verifier_provenance(packet.get("verifier_provenance"), errors)

    packet_id = packet.get("packet_id")
    if (
        isinstance(packet_id, str)
        and _PACKET_ID.fullmatch(packet_id)
        and not non_finite_errors
    ):
        expected_id = compute_packet_id(packet)
        if packet_id != expected_id:
            errors.append("$.packet_id: does not match the canonical packet content hash")

    _validate_semantics(packet, errors)
    return CompletionPacketValidationResult(tuple(errors))


def _validate_producer(value: Any, errors: list[str]) -> None:
    if not _is_object(value, "$.producer", errors):
        return
    _check_object_fields(value, path="$.producer", required={"name", "version"}, allowed={"name", "version"}, errors=errors)
    _expect_equal(value.get("name"), "project-loop-harness", "$.producer.name", errors)
    _validate_string(value.get("version"), "$.producer.version", errors)


def _validate_target(value: Any, errors: list[str]) -> None:
    if not _is_object(value, "$.target", errors):
        return
    allowed = {"type", "id", "intent", "work_brief_ref"}
    _check_object_fields(value, path="$.target", required={"type", "id", "intent"}, allowed=allowed, errors=errors)
    target_type = value.get("type")
    _expect_enum(target_type, set(_TARGET_PATTERNS), "$.target.type", errors)
    pattern = _TARGET_PATTERNS.get(target_type)
    _validate_string(value.get("id"), "$.target.id", errors, pattern=pattern)
    _validate_string(value.get("intent"), "$.target.intent", errors)
    _validate_optional_ref(value.get("work_brief_ref"), "$.target.work_brief_ref", errors)


def _validate_repository(value: Any, errors: list[str]) -> None:
    if not _is_object(value, "$.repository", errors):
        return
    allowed = {"base_revision", "head_revision", "diff_sha256", "dirty"}
    _check_object_fields(value, path="$.repository", required=allowed, allowed=allowed, errors=errors)
    _validate_string(value.get("base_revision"), "$.repository.base_revision", errors)
    _validate_string(value.get("head_revision"), "$.repository.head_revision", errors)
    _validate_string(value.get("diff_sha256"), "$.repository.diff_sha256", errors, pattern=_DIFF_HASH)
    _validate_bool(value.get("dirty"), "$.repository.dirty", errors)


def _validate_changes(value: Any, errors: list[str]) -> None:
    if not _is_array(value, "$.changes", errors):
        return
    for index, change in enumerate(value):
        path = f"$.changes[{index}]"
        if not _is_object(change, path, errors):
            continue
        allowed = {"path", "change_type", "previous_path"}
        _check_object_fields(change, path=path, required={"path", "change_type"}, allowed=allowed, errors=errors)
        _validate_string(change.get("path"), f"{path}.path", errors)
        _expect_enum(change.get("change_type"), _CHANGE_TYPES, f"{path}.change_type", errors)
        previous_path = change.get("previous_path")
        if previous_path is not None:
            _validate_string(previous_path, f"{path}.previous_path", errors)
        if change.get("change_type") == "renamed" and not previous_path:
            errors.append(f"{path}.previous_path: is required for a renamed change")


def _validate_checks(value: Any, errors: list[str]) -> None:
    if not _is_array(value, "$.checks", errors):
        return
    for index, check in enumerate(value):
        path = f"$.checks[{index}]"
        if not _is_object(check, path, errors):
            continue
        allowed = {"id", "command", "status", "exit_code", "artifact_ref", "reproducible", "reason"}
        required = {"id", "command", "status", "exit_code", "artifact_ref", "reproducible", "reason"}
        _check_object_fields(check, path=path, required=required, allowed=allowed, errors=errors)
        _validate_string(check.get("id"), f"{path}.id", errors, pattern=re.compile(r"^CHK-[0-9]{4,}$"))
        _validate_string(check.get("command"), f"{path}.command", errors)
        status = check.get("status")
        _expect_enum(status, _CHECK_STATUSES, f"{path}.status", errors)
        exit_code = check.get("exit_code")
        if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
            errors.append(f"{path}.exit_code: must be an integer or null")
        _validate_optional_ref(check.get("artifact_ref"), f"{path}.artifact_ref", errors)
        _validate_bool(check.get("reproducible"), f"{path}.reproducible", errors)
        reason = check.get("reason")
        if reason is not None:
            _validate_string(reason, f"{path}.reason", errors)
        if status == "passed" and exit_code != 0:
            errors.append(f"{path}: passed status requires exit_code 0")
        if status in {"skipped", "not_run", "timed_out"} and not reason:
            errors.append(f"{path}.reason: is required when status is {status}")


def _validate_claims(value: Any, errors: list[str]) -> None:
    if not _is_array(value, "$.claims", errors):
        return
    for index, claim in enumerate(value):
        path = f"$.claims[{index}]"
        if not _is_object(claim, path, errors):
            continue
        allowed = {"id", "text", "critical", "proof_level", "evidence_refs"}
        _check_object_fields(claim, path=path, required=allowed, allowed=allowed, errors=errors)
        _validate_string(claim.get("id"), f"{path}.id", errors, pattern=re.compile(r"^CL-[0-9]{4,}$"))
        _validate_string(claim.get("text"), f"{path}.text", errors)
        _validate_bool(claim.get("critical"), f"{path}.critical", errors)
        proof_level = claim.get("proof_level")
        _expect_enum(proof_level, _PROOF_LEVELS, f"{path}.proof_level", errors)
        _validate_ref_array(claim.get("evidence_refs"), f"{path}.evidence_refs", errors)
        if proof_level == "L0" and claim.get("evidence_refs"):
            errors.append(f"{path}.evidence_refs: L0 claims must not cite evidence")
        if proof_level in {"L1", "L2", "L3", "L4"} and not claim.get("evidence_refs"):
            errors.append(f"{path}.evidence_refs: {proof_level} claims require evidence refs")


def _validate_unverified_claims(value: Any, errors: list[str]) -> None:
    if not _is_array(value, "$.unverified_claims", errors):
        return
    for index, claim in enumerate(value):
        path = f"$.unverified_claims[{index}]"
        if not _is_object(claim, path, errors):
            continue
        allowed = {"text", "reason", "critical"}
        _check_object_fields(claim, path=path, required=allowed, allowed=allowed, errors=errors)
        _validate_string(claim.get("text"), f"{path}.text", errors)
        _validate_string(claim.get("reason"), f"{path}.reason", errors)
        _validate_bool(claim.get("critical"), f"{path}.critical", errors)


def _validate_risks(value: Any, errors: list[str]) -> None:
    if not _is_array(value, "$.risks", errors):
        return
    for index, risk in enumerate(value):
        path = f"$.risks[{index}]"
        if not _is_object(risk, path, errors):
            continue
        allowed = {"severity", "text", "mitigation"}
        _check_object_fields(risk, path=path, required=allowed, allowed=allowed, errors=errors)
        _expect_enum(risk.get("severity"), _RISK_LEVELS, f"{path}.severity", errors)
        _validate_string(risk.get("text"), f"{path}.text", errors)
        mitigation = risk.get("mitigation")
        if mitigation is not None:
            _validate_string(mitigation, f"{path}.mitigation", errors)


def _validate_next_action(value: Any, errors: list[str]) -> None:
    if value is None:
        return
    if not _is_object(value, "$.next_action", errors):
        return
    allowed = {"text", "command"}
    _check_object_fields(value, path="$.next_action", required=allowed, allowed=allowed, errors=errors)
    _validate_string(value.get("text"), "$.next_action.text", errors)
    command = value.get("command")
    if command is not None:
        _validate_string(command, "$.next_action.command", errors)


def _validate_verifier_provenance(value: Any, errors: list[str]) -> None:
    if value is None:
        return
    path = "$.verifier_provenance"
    if not _is_object(value, path, errors):
        return
    allowed = {"kind", "name", "version", "evidence_ref"}
    required = {"kind", "name", "version", "evidence_ref"}
    _check_object_fields(value, path=path, required=required, allowed=allowed, errors=errors)
    _expect_enum(value.get("kind"), {"human", "tool", "model"}, f"{path}.kind", errors)
    _validate_string(value.get("name"), f"{path}.name", errors)
    _validate_string(value.get("version"), f"{path}.version", errors)
    _validate_optional_ref(value.get("evidence_ref"), f"{path}.evidence_ref", errors)


def _validate_semantics(packet: dict[str, Any], errors: list[str]) -> None:
    outcome = packet.get("outcome")
    claims = packet.get("claims") if isinstance(packet.get("claims"), list) else []
    unverified = packet.get("unverified_claims") if isinstance(packet.get("unverified_claims"), list) else []
    risks = packet.get("risks") if isinstance(packet.get("risks"), list) else []
    changes = packet.get("changes") if isinstance(packet.get("changes"), list) else []

    if outcome in _COMPLETED_OUTCOMES:
        for index, claim in enumerate(claims):
            if isinstance(claim, dict) and claim.get("critical") and claim.get("proof_level") in {"L0", "L1"}:
                errors.append(
                    f"$.claims[{index}].proof_level: completed outcomes require critical claims at L2 or above"
                )
        if any(isinstance(claim, dict) and claim.get("critical") for claim in unverified):
            errors.append("$.unverified_claims: completed outcomes cannot contain critical unverified claims")
    if outcome == "COMPLETED_VERIFIED" and risks:
        errors.append("$.risks: COMPLETED_VERIFIED requires an empty risks list")
    if outcome == "COMPLETED_WITH_RISK" and not risks:
        errors.append("$.risks: COMPLETED_WITH_RISK requires at least one risk")
    if outcome == "NO_CHANGES" and changes:
        errors.append("$.changes: NO_CHANGES requires an empty changes list")
    if outcome == "INCOMPLETE_BUDGET_EXHAUSTED" and packet.get("next_action") is None:
        errors.append("$.next_action: INCOMPLETE_BUDGET_EXHAUSTED requires a next action")


def _check_object_fields(
    value: dict[str, Any],
    *,
    path: str,
    required: set[str],
    allowed: set[str],
    errors: list[str],
) -> None:
    for key in sorted(required - value.keys()):
        errors.append(f"{path}.{key}: is required")
    for key in sorted(value.keys() - allowed):
        errors.append(f"{path}.{key}: additional property is not allowed")


def _is_object(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return False
    return True


def _is_array(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return False
    return True


def _validate_string(value: Any, path: str, errors: list[str], *, pattern: re.Pattern[str] | None = None) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: must be a non-empty string")
    elif pattern is not None and not pattern.fullmatch(value):
        errors.append(f"{path}: has invalid canonical format")


def _validate_bool(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, bool):
        errors.append(f"{path}: must be a boolean")


def _expect_equal(value: Any, expected: Any, path: str, errors: list[str]) -> None:
    if value != expected:
        errors.append(f"{path}: must equal {expected!r}")


def _expect_enum(value: Any, allowed: set[str], path: str, errors: list[str]) -> None:
    if value not in allowed:
        errors.append(f"{path}: must be one of {', '.join(sorted(allowed))}")


def _validate_optional_ref(value: Any, path: str, errors: list[str]) -> None:
    if value is not None:
        _validate_string(value, path, errors, pattern=_EVIDENCE_REF)


def _validate_ref_array(value: Any, path: str, errors: list[str]) -> None:
    if not _is_array(value, path, errors):
        return
    for index, item in enumerate(value):
        _validate_string(item, f"{path}[{index}]", errors, pattern=_EVIDENCE_REF)


def _validate_string_array(value: Any, path: str, errors: list[str]) -> None:
    if not _is_array(value, path, errors):
        return
    for index, item in enumerate(value):
        _validate_string(item, f"{path}[{index}]", errors)


def _validate_timestamp(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: must be a non-empty string")
        return
    if not _TIMESTAMP.fullmatch(value):
        errors.append(f"{path}: has invalid canonical format")
        return
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errors.append(
            f"{path}: must be a real RFC 3339 UTC date-time at whole-second precision"
        )


def _reject_non_finite_json_number(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value} is not allowed")


def _collect_non_finite_json_numbers(
    value: Any,
    *,
    path: str,
    errors: list[str],
) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path}: non-finite JSON number is not allowed")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_non_finite_json_numbers(item, path=f"{path}.{key}", errors=errors)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _collect_non_finite_json_numbers(item, path=f"{path}[{index}]", errors=errors)
