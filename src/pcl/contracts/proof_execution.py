from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
import re
from typing import Any

from .proof_workspace import proof_document_sha256


PROOF_EXECUTION_PACKET_CONTRACT_VERSION = "proof-execution-packet/v1"
PROOF_AUTHORITY_CHECKPOINT_CONTRACT_VERSION = "proof-authority-checkpoint/v1"
PROOF_STREAM_LOG_CONTRACT_VERSION = "proof-stream-log/v1"
PROOF_CHECK_EXECUTION_RECEIPT_CONTRACT_VERSION = "proof-check-execution-receipt/v1"
PROOF_CHECK_EXECUTION_RESULT_CONTRACT_VERSION = "proof-check-execution-result/v1"
PROOF_EXECUTION_RESULT_CONTRACT_VERSION = "proof-execution-result/v1"
PROOF_EXECUTION_BUNDLE_RECEIPT_CONTRACT_VERSION = "proof-execution-bundle-receipt/v1"

PROOF_EXECUTION_PACKET_SCHEMA_RESOURCE = "schemas/proof-execution-packet-v1.schema.json"
PROOF_AUTHORITY_CHECKPOINT_SCHEMA_RESOURCE = (
    "schemas/proof-authority-checkpoint-v1.schema.json"
)
PROOF_STREAM_LOG_SCHEMA_RESOURCE = "schemas/proof-stream-log-v1.schema.json"
PROOF_CHECK_EXECUTION_RECEIPT_SCHEMA_RESOURCE = (
    "schemas/proof-check-execution-receipt-v1.schema.json"
)
PROOF_CHECK_EXECUTION_RESULT_SCHEMA_RESOURCE = (
    "schemas/proof-check-execution-result-v1.schema.json"
)
PROOF_EXECUTION_RESULT_SCHEMA_RESOURCE = "schemas/proof-execution-result-v1.schema.json"
PROOF_EXECUTION_BUNDLE_RECEIPT_SCHEMA_RESOURCE = (
    "schemas/proof-execution-bundle-receipt-v1.schema.json"
)

PUBLIC_STREAM_DISCLOSURE_BYTES = 1_048_576
PUBLIC_STREAM_BASE64_MAX_LENGTH = 1_398_104
MAX_CHECKS = 256
MAX_CHECK_ID_LENGTH = 4096

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTRACT_DIGEST_FIELDS = {
    PROOF_EXECUTION_PACKET_CONTRACT_VERSION: "packet_sha256",
    PROOF_AUTHORITY_CHECKPOINT_CONTRACT_VERSION: "checkpoint_sha256",
    PROOF_STREAM_LOG_CONTRACT_VERSION: "log_sha256",
    PROOF_CHECK_EXECUTION_RECEIPT_CONTRACT_VERSION: "receipt_sha256",
    PROOF_CHECK_EXECUTION_RESULT_CONTRACT_VERSION: "result_sha256",
    PROOF_EXECUTION_RESULT_CONTRACT_VERSION: "aggregate_sha256",
    PROOF_EXECUTION_BUNDLE_RECEIPT_CONTRACT_VERSION: "bundle_sha256",
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
_UNCOMMITTED_REASONS = {
    "output_profile_cap_exceeded",
    "public_disclosure_ceiling_exceeded",
    "secret_shaped_environment",
    "secret_shape_match",
    "output_incomplete",
}


@dataclass(frozen=True)
class ProofExecutionValidationResult:
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


def proof_execution_packet_schema() -> dict[str, Any]:
    return _schema(PROOF_EXECUTION_PACKET_SCHEMA_RESOURCE)


def proof_authority_checkpoint_schema() -> dict[str, Any]:
    return _schema(PROOF_AUTHORITY_CHECKPOINT_SCHEMA_RESOURCE)


def proof_stream_log_schema() -> dict[str, Any]:
    return _schema(PROOF_STREAM_LOG_SCHEMA_RESOURCE)


def proof_check_execution_receipt_schema() -> dict[str, Any]:
    return _schema(PROOF_CHECK_EXECUTION_RECEIPT_SCHEMA_RESOURCE)


def proof_check_execution_result_schema() -> dict[str, Any]:
    return _schema(PROOF_CHECK_EXECUTION_RESULT_SCHEMA_RESOURCE)


def proof_execution_result_schema() -> dict[str, Any]:
    return _schema(PROOF_EXECUTION_RESULT_SCHEMA_RESOURCE)


def proof_execution_bundle_receipt_schema() -> dict[str, Any]:
    return _schema(PROOF_EXECUTION_BUNDLE_RECEIPT_SCHEMA_RESOURCE)


def finalize_proof_execution_document(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical JSON copy with its contract-specific root digest."""

    normalized = json.loads(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    contract = normalized.get("contract_version")
    digest_field = _CONTRACT_DIGEST_FIELDS.get(contract)
    if digest_field is None:
        raise ValueError(f"Unsupported proof execution contract: {contract!r}")
    normalized.pop(digest_field, None)
    normalized[digest_field] = proof_document_sha256(normalized)
    return normalized


def validate_proof_execution_document(value: Any) -> ProofExecutionValidationResult:
    if not isinstance(value, dict):
        return ProofExecutionValidationResult("unknown", ("$: must be an object",))
    contract = value.get("contract_version")
    errors: list[str] = []
    validator = {
        PROOF_EXECUTION_PACKET_CONTRACT_VERSION: _packet,
        PROOF_AUTHORITY_CHECKPOINT_CONTRACT_VERSION: _checkpoint,
        PROOF_STREAM_LOG_CONTRACT_VERSION: _stream,
        PROOF_CHECK_EXECUTION_RECEIPT_CONTRACT_VERSION: _receipt,
        PROOF_CHECK_EXECUTION_RESULT_CONTRACT_VERSION: _check_result,
        PROOF_EXECUTION_RESULT_CONTRACT_VERSION: _aggregate,
        PROOF_EXECUTION_BUNDLE_RECEIPT_CONTRACT_VERSION: _bundle,
    }.get(contract)
    if validator is None:
        return ProofExecutionValidationResult(
            str(contract or "unknown"),
            ("$.contract_version: unsupported proof execution contract",),
        )
    validator(value, errors)
    digest_field = _CONTRACT_DIGEST_FIELDS[str(contract)]
    _sha(value.get(digest_field), f"$.{digest_field}", errors)
    if isinstance(value.get(digest_field), str):
        content = dict(value)
        recorded = content.pop(digest_field)
        try:
            actual = proof_document_sha256(content)
        except (TypeError, ValueError):
            errors.append("$: is not canonical JSON data")
        else:
            if recorded != actual:
                errors.append(f"$.{digest_field}: does not match canonical content")
    return ProofExecutionValidationResult(str(contract), tuple(errors))


def _packet(value: dict[str, Any], errors: list[str]) -> None:
    _exact(
        value,
        "$",
        {
            "contract_version",
            "workspace_binding_sha256",
            "executor_contract_sha256",
            "ordered_check_ids",
            "initial_reuse_disposition",
            "packet_sha256",
        },
        errors,
    )
    _sha(value.get("workspace_binding_sha256"), "$.workspace_binding_sha256", errors)
    _sha(value.get("executor_contract_sha256"), "$.executor_contract_sha256", errors)
    _check_ids(value.get("ordered_check_ids"), "$.ordered_check_ids", errors, nonempty=True)
    _enum(
        value.get("initial_reuse_disposition"),
        {"eligible", "fresh_only"},
        "$.initial_reuse_disposition",
        errors,
    )


def _checkpoint(value: dict[str, Any], errors: list[str]) -> None:
    _exact(
        value,
        "$",
        {
            "contract_version",
            "packet_sha256",
            "phase",
            "check_id",
            "source_status",
            "base_status",
            "literal_reuse_allowed",
            "rederived_cross_checks",
            "clone_diff_cross_check",
            "checkpoint_sha256",
        },
        errors,
    )
    _sha(value.get("packet_sha256"), "$.packet_sha256", errors)
    phase = value.get("phase")
    _enum(phase, {"initial", "pre_spawn", "post_execution", "aggregate_final"}, "$.phase", errors)
    check_id = value.get("check_id")
    if phase in {"initial", "aggregate_final"}:
        if check_id is not None:
            errors.append("$.check_id: must be null for an aggregate checkpoint")
    else:
        _check_id(check_id, "$.check_id", errors)
    if value.get("source_status") != "matched":
        errors.append("$.source_status: must equal 'matched'")
    base = value.get("base_status")
    _enum(base, {"resolved", "base_unknown", "no_candidate_change"}, "$.base_status", errors)
    if not isinstance(value.get("literal_reuse_allowed"), bool):
        errors.append("$.literal_reuse_allowed: must be a boolean")
    checks = value.get("rederived_cross_checks")
    expected_checks = {
        "binding",
        "bootstrap_profile",
        "verification_profile",
        "check_plan",
        "external_inputs",
        "proof_key",
        "public_execution",
    }
    if not isinstance(checks, dict):
        errors.append("$.rederived_cross_checks: must be an object")
    else:
        _exact(checks, "$.rederived_cross_checks", expected_checks, errors)
        for field in sorted(expected_checks):
            if checks.get(field) is not True:
                errors.append(f"$.rederived_cross_checks.{field}: must equal True")
    clone = value.get("clone_diff_cross_check")
    if not isinstance(clone, dict):
        errors.append("$.clone_diff_cross_check: must be an object")
    else:
        _exact(clone, "$.clone_diff_cross_check", {"status", "diff_sha256"}, errors)
        status = clone.get("status")
        diff = clone.get("diff_sha256")
        if base == "base_unknown":
            if status != "not_applicable_base_unknown" or diff is not None:
                errors.append(
                    "$.clone_diff_cross_check: base_unknown requires not_applicable status and null digest"
                )
        else:
            if status != "matched":
                errors.append("$.clone_diff_cross_check.status: must equal 'matched'")
            _sha(diff, "$.clone_diff_cross_check.diff_sha256", errors)


def _stream(value: dict[str, Any], errors: list[str]) -> None:
    common = {
        "contract_version",
        "packet_sha256",
        "check_id",
        "stream",
        "commitment",
        "log_sha256",
    }
    commitment = value.get("commitment")
    if commitment == "committed":
        expected = common | {"content_byte_count", "content_base64", "content_sha256"}
    elif commitment == "uncommitted":
        expected = common | {"reason_codes"}
    else:
        expected = common
        errors.append("$.commitment: unsupported commitment")
    _exact(value, "$", expected, errors)
    _sha(value.get("packet_sha256"), "$.packet_sha256", errors)
    _check_id(value.get("check_id"), "$.check_id", errors)
    _enum(value.get("stream"), {"stdout", "stderr"}, "$.stream", errors)
    if commitment == "committed":
        count = value.get("content_byte_count")
        if type(count) is not int or count < 0 or count > PUBLIC_STREAM_DISCLOSURE_BYTES:
            errors.append("$.content_byte_count: must be an integer from 0 through 1048576")
        encoded = value.get("content_base64")
        if not isinstance(encoded, str) or len(encoded) > PUBLIC_STREAM_BASE64_MAX_LENGTH:
            errors.append("$.content_base64: invalid bounded base64")
        else:
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (ValueError, base64.binascii.Error):
                errors.append("$.content_base64: invalid padded RFC4648 base64")
            else:
                if type(count) is int and len(decoded) != count:
                    errors.append("$.content_base64: decoded length does not match count")
                expected_digest = "sha256:" + hashlib.sha256(decoded).hexdigest()
                if value.get("content_sha256") != expected_digest:
                    errors.append("$.content_sha256: does not match decoded content")
        _sha(value.get("content_sha256"), "$.content_sha256", errors)
    elif commitment == "uncommitted":
        _sorted_enums(
            value.get("reason_codes"),
            _UNCOMMITTED_REASONS,
            "$.reason_codes",
            errors,
            nonempty=True,
        )


def _receipt(value: dict[str, Any], errors: list[str]) -> None:
    _exact(
        value,
        "$",
        {
            "contract_version",
            "packet_sha256",
            "check_id",
            "authority_checkpoint_sha256s",
            "spawn",
            "process",
            "stdout_log_sha256",
            "stderr_log_sha256",
            "reseal",
            "proof_validity",
            "receipt_sha256",
        },
        errors,
    )
    _sha(value.get("packet_sha256"), "$.packet_sha256", errors)
    _check_id(value.get("check_id"), "$.check_id", errors)
    _sha_array(value.get("authority_checkpoint_sha256s"), "$.authority_checkpoint_sha256s", errors)
    spawn = value.get("spawn")
    if not isinstance(spawn, dict):
        errors.append("$.spawn: must be an object")
    else:
        _exact(spawn, "$.spawn", {"status", "error_kind"}, errors)
        status = spawn.get("status")
        _enum(status, {"not_attempted", "spawned", "failed"}, "$.spawn.status", errors)
        error_kind = spawn.get("error_kind")
        if status == "failed":
            _enum(error_kind, {"not_found", "permission_denied", "os_error"}, "$.spawn.error_kind", errors)
        elif error_kind is not None:
            errors.append("$.spawn.error_kind: must be null unless spawn failed")
    process = value.get("process")
    if not isinstance(process, dict):
        errors.append("$.process: must be an object")
    else:
        _exact(
            process,
            "$.process",
            {
                "controller_cause",
                "leader_kind",
                "leader_value",
                "term_sent",
                "kill_sent",
                "pipes_eof",
                "group_quiescent",
            },
            errors,
        )
        _enum(
            process.get("controller_cause"),
            {"not_started", "exit", "signal", "timeout", "cancellation", "descendant_cleanup", "uncertain"},
            "$.process.controller_cause",
            errors,
        )
        kind = process.get("leader_kind")
        _enum(kind, {"not_started", "exited", "signaled", "unknown"}, "$.process.leader_kind", errors)
        leader_value = process.get("leader_value")
        if kind in {"exited", "signaled"}:
            if type(leader_value) is not int or leader_value < 0:
                errors.append("$.process.leader_value: must be a non-negative integer")
        elif leader_value is not None:
            errors.append("$.process.leader_value: must be null without a known leader result")
        for field in ("term_sent", "kill_sent", "pipes_eof", "group_quiescent"):
            if not isinstance(process.get(field), bool):
                errors.append(f"$.process.{field}: must be a boolean")
    _sha(value.get("stdout_log_sha256"), "$.stdout_log_sha256", errors)
    _sha(value.get("stderr_log_sha256"), "$.stderr_log_sha256", errors)
    reseal = value.get("reseal")
    if not isinstance(reseal, dict):
        errors.append("$.reseal: must be an object")
    else:
        _exact(
            reseal,
            "$.reseal",
            {"status", "before_manifest_sha256", "after_manifest_sha256", "effect_classification"},
            errors,
        )
        status = reseal.get("status")
        _enum(status, {"not_run", "matched", "inconclusive"}, "$.reseal.status", errors)
        if status == "not_run":
            for field in ("before_manifest_sha256", "after_manifest_sha256", "effect_classification"):
                if reseal.get(field) is not None:
                    errors.append(f"$.reseal.{field}: must be null when not run")
        else:
            _sha(reseal.get("before_manifest_sha256"), "$.reseal.before_manifest_sha256", errors)
            if status == "matched":
                _sha(reseal.get("after_manifest_sha256"), "$.reseal.after_manifest_sha256", errors)
                _enum(
                    reseal.get("effect_classification"),
                    {"read_only", "declared_outputs", "mutates_inputs", "unknown"},
                    "$.reseal.effect_classification",
                    errors,
                )
    _enum(value.get("proof_validity"), {"valid", "invalid", "indeterminate"}, "$.proof_validity", errors)


def _check_result(value: dict[str, Any], errors: list[str]) -> None:
    _exact(
        value,
        "$",
        {
            "contract_version",
            "packet_sha256",
            "check_id",
            "receipt_sha256",
            "verdict",
            "reuse_disposition",
            "result_sha256",
        },
        errors,
    )
    for field in ("packet_sha256", "receipt_sha256"):
        _sha(value.get(field), f"$.{field}", errors)
    _check_id(value.get("check_id"), "$.check_id", errors)
    verdict = value.get("verdict")
    _enum(verdict, _VERDICTS, "$.verdict", errors)
    disposition = value.get("reuse_disposition")
    _enum(disposition, {"eligible", "fresh_only"}, "$.reuse_disposition", errors)
    if verdict != "passed" and disposition != "fresh_only":
        errors.append("$.reuse_disposition: non-passed results must be fresh_only")


def _aggregate(value: dict[str, Any], errors: list[str]) -> None:
    _exact(
        value,
        "$",
        {
            "contract_version",
            "packet_sha256",
            "ordered_result_sha256s",
            "not_run_check_ids",
            "final_authority_checkpoint_sha256",
            "verdict",
            "output_commitment_status",
            "current_proof",
            "anchoring_eligible",
            "positive_proof_handoff",
            "reuse_disposition",
            "reuse_authorized",
            "aggregate_sha256",
        },
        errors,
    )
    _sha(value.get("packet_sha256"), "$.packet_sha256", errors)
    _sha_array(value.get("ordered_result_sha256s"), "$.ordered_result_sha256s", errors)
    _check_ids(value.get("not_run_check_ids"), "$.not_run_check_ids", errors)
    final_authority = value.get("final_authority_checkpoint_sha256")
    if final_authority is not None:
        _sha(final_authority, "$.final_authority_checkpoint_sha256", errors)
    verdict = value.get("verdict")
    _enum(verdict, _VERDICTS, "$.verdict", errors)
    output_status = value.get("output_commitment_status")
    _enum(output_status, {"committed", "uncommitted"}, "$.output_commitment_status", errors)
    current = value.get("current_proof")
    current_candidate = False
    if not isinstance(current, dict):
        errors.append("$.current_proof: must be an object")
    else:
        _exact(current, "$.current_proof", {"scope", "status", "proof_sha256"}, errors)
        scope = current.get("scope")
        status = current.get("status")
        _enum(scope, {"feature", "not_applicable"}, "$.current_proof.scope", errors)
        _enum(
            status,
            {"healthy", "unhealthy", "not_applicable", "changed", "indeterminate"},
            "$.current_proof.status",
            errors,
        )
        digest = current.get("proof_sha256")
        if status == "indeterminate":
            if digest is not None:
                errors.append("$.current_proof.proof_sha256: indeterminate requires null")
        else:
            _sha(digest, "$.current_proof.proof_sha256", errors)
        if scope == "not_applicable" and status not in {
            "not_applicable",
            "changed",
            "indeterminate",
        }:
            errors.append(
                "$.current_proof.status: not_applicable scope requires a compatible status"
            )
        if scope == "feature" and status == "not_applicable":
            errors.append("$.current_proof.status: feature scope cannot be not_applicable")
        current_candidate = status in {"healthy", "not_applicable"}
    anchoring = value.get("anchoring_eligible")
    if not isinstance(anchoring, bool):
        errors.append("$.anchoring_eligible: must be a boolean")
    handoff = value.get("positive_proof_handoff")
    _enum(handoff, {"candidate", "withheld"}, "$.positive_proof_handoff", errors)
    if anchoring is True and handoff != "candidate":
        errors.append("$.positive_proof_handoff: anchoring true requires candidate")
    if anchoring is False and handoff != "withheld":
        errors.append("$.positive_proof_handoff: anchoring false requires withheld")
    suitable = (
        verdict == "passed"
        and not value.get("not_run_check_ids")
        and final_authority is not None
        and output_status == "committed"
        and current_candidate
    )
    if anchoring is not suitable:
        errors.append("$.anchoring_eligible: must equal the complete suitability predicate")
    disposition = value.get("reuse_disposition")
    _enum(disposition, {"eligible", "fresh_only"}, "$.reuse_disposition", errors)
    if (verdict != "passed" or output_status != "committed" or not current_candidate) and disposition != "fresh_only":
        errors.append("$.reuse_disposition: proof withholding must be fresh_only")
    if value.get("reuse_authorized") is not False:
        errors.append("$.reuse_authorized: must equal False")


def _bundle(value: dict[str, Any], errors: list[str]) -> None:
    _exact(
        value,
        "$",
        {"contract_version", "packet_sha256", "aggregate_sha256", "objects", "bundle_sha256"},
        errors,
    )
    _sha(value.get("packet_sha256"), "$.packet_sha256", errors)
    _sha(value.get("aggregate_sha256"), "$.aggregate_sha256", errors)
    objects = value.get("objects")
    if not isinstance(objects, list) or not objects:
        errors.append("$.objects: must be a non-empty array")
        return
    if len(objects) > (MAX_CHECKS * 6 + 4):
        errors.append("$.objects: exceeds the C3 object bound")
    seen: set[tuple[str, str]] = set()
    normalized: list[tuple[str, str]] = []
    for index, item in enumerate(objects):
        path = f"$.objects[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: must be an object")
            continue
        _exact(item, path, {"role", "sha256"}, errors)
        role = item.get("role")
        if not isinstance(role, str) or not role or len(role) > 128 or not role.isascii():
            errors.append(f"{path}.role: invalid role")
        _sha(item.get("sha256"), f"{path}.sha256", errors)
        pair = (str(role), str(item.get("sha256")))
        if pair in seen:
            errors.append(f"{path}: duplicate object")
        seen.add(pair)
        normalized.append(pair)
    if normalized != sorted(normalized):
        errors.append("$.objects: must be sorted by role and digest")


def _schema(resource: str) -> dict[str, Any]:
    return json.loads(files("pcl.contracts").joinpath(resource).read_text(encoding="utf-8"))


def _exact(
    value: Mapping[str, Any],
    path: str,
    expected: set[str],
    errors: list[str],
) -> None:
    for field in sorted(expected - set(value)):
        errors.append(f"{path}.{field}: is required")
    for field in sorted(set(value) - expected):
        errors.append(f"{path}.{field}: additional property is not allowed")


def _sha(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        errors.append(f"{path}: invalid sha256 digest")


def _check_id(value: Any, path: str, errors: list[str]) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_CHECK_ID_LENGTH
        or not value.isascii()
        or "\0" in value
    ):
        errors.append(f"{path}: invalid bounded ASCII check id")


def _check_ids(
    value: Any,
    path: str,
    errors: list[str],
    *,
    nonempty: bool = False,
) -> None:
    if not isinstance(value, list) or (nonempty and not value) or len(value) > MAX_CHECKS:
        errors.append(f"{path}: invalid bounded check-id array")
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        _check_id(item, f"{path}[{index}]", errors)
        if isinstance(item, str) and item in seen:
            errors.append(f"{path}[{index}]: duplicate check id")
        if isinstance(item, str):
            seen.add(item)


def _sha_array(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, list) or len(value) > MAX_CHECKS * 2 + 2:
        errors.append(f"{path}: invalid bounded digest array")
        return
    for index, item in enumerate(value):
        _sha(item, f"{path}[{index}]", errors)


def _enum(value: Any, allowed: set[str], path: str, errors: list[str]) -> None:
    if value not in allowed:
        errors.append(f"{path}: unsupported value")


def _sorted_enums(
    value: Any,
    allowed: set[str],
    path: str,
    errors: list[str],
    *,
    nonempty: bool = False,
) -> None:
    if not isinstance(value, list) or (nonempty and not value):
        errors.append(f"{path}: must be an array")
        return
    if value != sorted(set(value)):
        errors.append(f"{path}: values must be sorted and unique")
    for index, item in enumerate(value):
        _enum(item, allowed, f"{path}[{index}]", errors)
