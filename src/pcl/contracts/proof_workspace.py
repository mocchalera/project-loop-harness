from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping
import unicodedata


VERIFICATION_PROFILE_CONTRACT_VERSION = "verification-profile/v1"
PROOF_WORKSPACE_SPEC_CONTRACT_VERSION = "proof-workspace-spec/v1"
PROOF_WORKSPACE_BINDING_CONTRACT_VERSION = "proof-workspace-binding/v1"
PROOF_WORKSPACE_ISOLATION_CONTRACT_VERSION = "proof-workspace-isolation/v1"
PREPARED_CHECK_CONTRACT_VERSION = "prepared-check/v1"

VERIFICATION_PROFILE_SCHEMA_RESOURCE = "schemas/verification-profile-v1.schema.json"
PROOF_WORKSPACE_SPEC_SCHEMA_RESOURCE = "schemas/proof-workspace-spec-v1.schema.json"
PROOF_WORKSPACE_BINDING_SCHEMA_RESOURCE = "schemas/proof-workspace-binding-v1.schema.json"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_OID_BY_FORMAT = {
    "sha1": re.compile(r"^[0-9a-f]{40}$"),
    "sha256": re.compile(r"^[0-9a-f]{64}$"),
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PORTABLE_MODE = {"0644", "0755"}
_AVAILABILITY = {"fresh_only", "block"}
_PROFILE_FIELDS = {
    "contract_version",
    "profile_id",
    "execution_policy",
    "checks",
    "terminal_authority",
    "mandatory_evidence",
}
_POLICY_FIELDS = {
    "spawn_contract",
    "workspace_contract",
    "shell",
    "os_sandbox",
    "network_sandbox",
    "supported_platforms",
}
_CHECK_FIELDS = {
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
_ENVIRONMENT_FIELDS = {"inherit_names", "workspace_pythonpath"}
_SPEC_FIELDS = {
    "contract_version",
    "target",
    "candidate",
    "authority_surface_resolution_sha256",
    "bootstrap_profile_sha256",
    "verification_profile_sha256",
    "isolation_contract_version",
    "external_inputs",
    "terminal_authority",
    "mandatory_evidence",
}
_COMMON_INPUT_FIELDS = {
    "input_id",
    "type",
    "consumer_check_ids",
    "on_unavailable",
}
_FILE_INPUT_FIELDS = _COMMON_INPUT_FIELDS | {
    "destination",
    "sha256",
    "size",
    "mode",
}
_DIRECTORY_INPUT_FIELDS = _COMMON_INPUT_FIELDS | {
    "destination",
    "bundle_sha256",
}
_SUBMODULE_INPUT_FIELDS = _COMMON_INPUT_FIELDS | {
    "destination",
    "gitlink_oid",
    "commit_oid",
    "tree_oid",
    "object_format",
}
_GENERATED_INPUT_FIELDS = _COMMON_INPUT_FIELDS | {
    "destination",
    "material_kind",
    "sha256",
    "size",
    "mode",
    "base_expectation",
}
_LFS_INPUT_FIELDS = _COMMON_INPUT_FIELDS | {
    "destination",
    "material_kind",
    "pointer_blob_oid",
    "lfs_oid_sha256",
    "lfs_size",
    "sha256",
    "size",
    "mode",
}
_BINDING_FIELDS = {
    "contract_version",
    "spec_sha256",
    "repository",
    "authority",
    "verification_profile",
    "external_inputs",
    "checks",
    "proof_key",
    "reuse",
    "terminal_authority",
    "mandatory_evidence",
}


@dataclass(frozen=True)
class ProofWorkspaceValidationResult:
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


def verification_profile_schema() -> dict[str, Any]:
    return _schema(VERIFICATION_PROFILE_SCHEMA_RESOURCE)


def proof_workspace_spec_schema() -> dict[str, Any]:
    return _schema(PROOF_WORKSPACE_SPEC_SCHEMA_RESOURCE)


def proof_workspace_binding_schema() -> dict[str, Any]:
    return _schema(PROOF_WORKSPACE_BINDING_SCHEMA_RESOURCE)


def proof_document_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_verification_profile(value: Any) -> ProofWorkspaceValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return _result(VERIFICATION_PROFILE_CONTRACT_VERSION, ["$: must be an object"])
    _exact_fields(value, "$", _PROFILE_FIELDS, errors)
    if value.get("contract_version") != VERIFICATION_PROFILE_CONTRACT_VERSION:
        errors.append(
            "$.contract_version: must equal "
            f"{VERIFICATION_PROFILE_CONTRACT_VERSION!r}"
        )
    _identifier(value.get("profile_id"), "$.profile_id", errors)
    policy = value.get("execution_policy")
    if not isinstance(policy, dict):
        errors.append("$.execution_policy: must be an object")
    else:
        _exact_fields(policy, "$.execution_policy", _POLICY_FIELDS, errors)
        expected = {
            "spawn_contract": PREPARED_CHECK_CONTRACT_VERSION,
            "workspace_contract": PROOF_WORKSPACE_ISOLATION_CONTRACT_VERSION,
            "shell": False,
            "os_sandbox": False,
            "network_sandbox": False,
            "supported_platforms": ["darwin", "linux"],
        }
        for field, expected_value in expected.items():
            if policy.get(field) != expected_value:
                errors.append(
                    f"$.execution_policy.{field}: must equal {expected_value!r}"
                )
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("$.checks: must be a non-empty array")
    else:
        seen: set[str] = set()
        for index, check in enumerate(checks):
            path = f"$.checks[{index}]"
            if not isinstance(check, dict):
                errors.append(f"{path}: must be an object")
                continue
            _exact_fields(check, path, _CHECK_FIELDS, errors)
            check_id = check.get("check_id")
            _identifier(check_id, f"{path}.check_id", errors)
            if isinstance(check_id, str):
                if check_id in seen:
                    errors.append(f"{path}.check_id: must be unique")
                seen.add(check_id)
            _identifier(check.get("role"), f"{path}.role", errors)
            argv = check.get("argv")
            if (
                not isinstance(argv, list)
                or not argv
                or any(not isinstance(item, str) or not item or "\0" in item for item in argv)
            ):
                errors.append(f"{path}.argv: must contain non-empty NUL-free strings")
            _relative_path(check.get("cwd"), f"{path}.cwd", errors, allow_dot=True)
            _unique_strings(check.get("selectors"), f"{path}.selectors", errors)
            _referenced_blobs(
                check.get("referenced_git_blobs"),
                f"{path}.referenced_git_blobs",
                errors,
            )
            _sorted_unique_strings(check.get("input_ids"), f"{path}.input_ids", errors)
            environment = check.get("environment")
            if not isinstance(environment, dict):
                errors.append(f"{path}.environment: must be an object")
            else:
                _exact_fields(
                    environment,
                    f"{path}.environment",
                    _ENVIRONMENT_FIELDS,
                    errors,
                )
                names = environment.get("inherit_names")
                _sorted_unique_strings(names, f"{path}.environment.inherit_names", errors)
                if isinstance(names, list):
                    for name_index, name in enumerate(names):
                        if not isinstance(name, str) or _ENVIRONMENT_NAME.fullmatch(name) is None:
                            errors.append(
                                f"{path}.environment.inherit_names[{name_index}]: "
                                "invalid environment name"
                            )
                pythonpath = environment.get("workspace_pythonpath")
                _unique_strings(
                    pythonpath,
                    f"{path}.environment.workspace_pythonpath",
                    errors,
                )
                if isinstance(pythonpath, list):
                    for item_index, item in enumerate(pythonpath):
                        _relative_path(
                            item,
                            f"{path}.environment.workspace_pythonpath[{item_index}]",
                            errors,
                            allow_dot=True,
                        )
            _positive_bounded_int(
                check.get("timeout_seconds"),
                f"{path}.timeout_seconds",
                errors,
                maximum=86_400,
            )
            _positive_bounded_int(
                check.get("max_output_bytes"),
                f"{path}.max_output_bytes",
                errors,
                maximum=100 * 1024 * 1024,
            )
            outputs = check.get("declared_outputs")
            _sorted_unique_strings(outputs, f"{path}.declared_outputs", errors)
            if isinstance(outputs, list):
                for output_index, output in enumerate(outputs):
                    _relative_pattern(
                        output,
                        f"{path}.declared_outputs[{output_index}]",
                        errors,
                    )
    _false_literals(value, errors)
    return _result(VERIFICATION_PROFILE_CONTRACT_VERSION, errors)


def validate_proof_workspace_spec(value: Any) -> ProofWorkspaceValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return _result(PROOF_WORKSPACE_SPEC_CONTRACT_VERSION, ["$: must be an object"])
    _exact_fields(value, "$", _SPEC_FIELDS, errors)
    if value.get("contract_version") != PROOF_WORKSPACE_SPEC_CONTRACT_VERSION:
        errors.append(
            "$.contract_version: must equal "
            f"{PROOF_WORKSPACE_SPEC_CONTRACT_VERSION!r}"
        )
    target = value.get("target")
    if not isinstance(target, dict) or set(target) != {"type", "id"}:
        errors.append("$.target: must contain only type and id")
    else:
        if target.get("type") != "task":
            errors.append("$.target.type: must equal 'task'")
        if not isinstance(target.get("id"), str) or not target["id"]:
            errors.append("$.target.id: must be non-empty")
    candidate = value.get("candidate")
    if not isinstance(candidate, dict) or set(candidate) != {
        "object_format",
        "commit_oid",
        "tree_oid",
    }:
        errors.append("$.candidate: unsupported shape")
    else:
        object_format = candidate.get("object_format")
        matcher = _OID_BY_FORMAT.get(object_format)
        if matcher is None:
            errors.append("$.candidate.object_format: unsupported Git object format")
        else:
            for field in ("commit_oid", "tree_oid"):
                if not isinstance(candidate.get(field), str) or matcher.fullmatch(candidate[field]) is None:
                    errors.append(f"$.candidate.{field}: invalid full Git OID")
    for field in (
        "authority_surface_resolution_sha256",
        "bootstrap_profile_sha256",
        "verification_profile_sha256",
    ):
        _sha(value.get(field), f"$.{field}", errors)
    if value.get("isolation_contract_version") != PROOF_WORKSPACE_ISOLATION_CONTRACT_VERSION:
        errors.append(
            "$.isolation_contract_version: must equal "
            f"{PROOF_WORKSPACE_ISOLATION_CONTRACT_VERSION!r}"
        )
    external_inputs = value.get("external_inputs")
    if not isinstance(external_inputs, list):
        errors.append("$.external_inputs: must be an array")
    else:
        seen_ids: set[str] = set()
        seen_destinations: list[tuple[str, PurePosixPath]] = []
        for index, item in enumerate(external_inputs):
            path = f"$.external_inputs[{index}]"
            _external_input(item, path, errors)
            if not isinstance(item, dict):
                continue
            input_id = item.get("input_id")
            if isinstance(input_id, str):
                if input_id in seen_ids:
                    errors.append(f"{path}.input_id: must be unique")
                seen_ids.add(input_id)
            destination = item.get("destination")
            if isinstance(destination, str) and _is_relative_path(destination):
                candidate_path = PurePosixPath(destination)
                for prior_id, prior in seen_destinations:
                    if _paths_overlap(candidate_path, prior):
                        errors.append(
                            f"{path}.destination: overlaps external input {prior_id!r}"
                        )
                seen_destinations.append((str(input_id), candidate_path))
    _false_literals(value, errors)
    return _result(PROOF_WORKSPACE_SPEC_CONTRACT_VERSION, errors)


def validate_proof_workspace_binding(value: Any) -> ProofWorkspaceValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return _result(PROOF_WORKSPACE_BINDING_CONTRACT_VERSION, ["$: must be an object"])
    _exact_fields(value, "$", _BINDING_FIELDS, errors)
    if value.get("contract_version") != PROOF_WORKSPACE_BINDING_CONTRACT_VERSION:
        errors.append(
            "$.contract_version: must equal "
            f"{PROOF_WORKSPACE_BINDING_CONTRACT_VERSION!r}"
        )
    _sha(value.get("spec_sha256"), "$.spec_sha256", errors)
    repository = value.get("repository")
    if not isinstance(repository, dict):
        errors.append("$.repository: must be an object")
    else:
        expected_repository_fields = {
            "candidate",
            "git_tree_entries_sha256",
            "detached",
            "initially_clean",
            "git_common_dir_distinct",
            "alternates_absent",
            "origin_absent",
            "configuration_sealed",
        }
        _exact_fields(repository, "$.repository", expected_repository_fields, errors)
        _sha(repository.get("git_tree_entries_sha256"), "$.repository.git_tree_entries_sha256", errors)
        for field in expected_repository_fields - {"candidate", "git_tree_entries_sha256"}:
            if repository.get(field) is not True:
                errors.append(f"$.repository.{field}: must equal True")
        candidate = repository.get("candidate")
        if not isinstance(candidate, dict) or set(candidate) != {
            "object_format",
            "commit_oid",
            "tree_oid",
        }:
            errors.append("$.repository.candidate: unsupported shape")
        else:
            matcher = _OID_BY_FORMAT.get(candidate.get("object_format"))
            if matcher is None:
                errors.append("$.repository.candidate.object_format: unsupported format")
            else:
                for field in ("commit_oid", "tree_oid"):
                    if not isinstance(candidate.get(field), str) or matcher.fullmatch(
                        candidate[field]
                    ) is None:
                        errors.append(f"$.repository.candidate.{field}: invalid Git OID")
    authority = value.get("authority")
    if not isinstance(authority, dict):
        errors.append("$.authority: must be an object")
    else:
        _exact_fields(
            authority,
            "$.authority",
            {"resolution_sha256", "base_status", "actual_diff_sha256"},
            errors,
        )
        _sha(authority.get("resolution_sha256"), "$.authority.resolution_sha256", errors)
        _sha(authority.get("actual_diff_sha256"), "$.authority.actual_diff_sha256", errors)
        if authority.get("base_status") not in {
            "resolved",
            "base_unknown",
            "no_candidate_change",
        }:
            errors.append("$.authority.base_status: unsupported status")
    profile = value.get("verification_profile")
    if not isinstance(profile, dict):
        errors.append("$.verification_profile: must be an object")
    else:
        _exact_fields(profile, "$.verification_profile", {"profile_id", "sha256", "check_plan_sha256"}, errors)
        _sha(profile.get("sha256"), "$.verification_profile.sha256", errors)
        _sha(profile.get("check_plan_sha256"), "$.verification_profile.check_plan_sha256", errors)
    external = value.get("external_inputs")
    if not isinstance(external, dict):
        errors.append("$.external_inputs: must be an object")
    else:
        _exact_fields(external, "$.external_inputs", {"binding_sha256", "entries"}, errors)
        _sha(external.get("binding_sha256"), "$.external_inputs.binding_sha256", errors)
        if not isinstance(external.get("entries"), list):
            errors.append("$.external_inputs.entries: must be an array")
    checks = value.get("checks")
    if not isinstance(checks, list):
        errors.append("$.checks: must be an array")
    else:
        seen: set[str] = set()
        for index, check in enumerate(checks):
            path = f"$.checks[{index}]"
            if not isinstance(check, dict):
                errors.append(f"{path}: must be an object")
                continue
            expected = {
                "check_id",
                "plan_sha256",
                "tool_identity_sha256",
                "environment",
                "public_execution_sha256",
                "spawn_vector_sha256",
                "secret_derived_digests_public",
            }
            _exact_fields(check, path, expected, errors)
            check_id = check.get("check_id")
            _identifier(check_id, f"{path}.check_id", errors)
            if isinstance(check_id, str):
                if check_id in seen:
                    errors.append(f"{path}.check_id: must be unique")
                seen.add(check_id)
            for field in ("plan_sha256", "tool_identity_sha256", "public_execution_sha256"):
                _sha(check.get(field), f"{path}.{field}", errors)
            spawn = check.get("spawn_vector_sha256")
            if spawn is not None:
                _sha(spawn, f"{path}.spawn_vector_sha256", errors)
            if check.get("secret_derived_digests_public") is not False:
                errors.append(f"{path}.secret_derived_digests_public: must equal False")
            environment = check.get("environment")
            expected_environment_fields = {
                "inheritance",
                "inherited_names",
                "fixed_names",
                "public_values_sha256",
                "values_recorded",
                "secret_shaped_names",
                "secret_derived_digest_recorded",
            }
            if not isinstance(environment, dict):
                errors.append(f"{path}.environment: must be an object")
            else:
                _exact_fields(
                    environment,
                    f"{path}.environment",
                    expected_environment_fields,
                    errors,
                )
                if environment.get("inheritance") != "allowlist":
                    errors.append(f"{path}.environment.inheritance: must equal 'allowlist'")
                for field in ("inherited_names", "fixed_names", "secret_shaped_names"):
                    _sorted_unique_strings(
                        environment.get(field),
                        f"{path}.environment.{field}",
                        errors,
                    )
                _sha(
                    environment.get("public_values_sha256"),
                    f"{path}.environment.public_values_sha256",
                    errors,
                )
                if environment.get("values_recorded") is not False:
                    errors.append(f"{path}.environment.values_recorded: must equal False")
                if environment.get("secret_derived_digest_recorded") is not False:
                    errors.append(
                        f"{path}.environment.secret_derived_digest_recorded: must equal False"
                    )
    proof_key = value.get("proof_key")
    if not isinstance(proof_key, dict) or set(proof_key) != {"contract_version", "sha256"}:
        errors.append("$.proof_key: unsupported shape")
    else:
        if proof_key.get("contract_version") != "proof-key/v1":
            errors.append("$.proof_key.contract_version: must equal 'proof-key/v1'")
        _sha(proof_key.get("sha256"), "$.proof_key.sha256", errors)
    reuse = value.get("reuse")
    if not isinstance(reuse, dict):
        errors.append("$.reuse: must be an object")
    else:
        _exact_fields(
            reuse,
            "$.reuse",
            {
                "authority_effective",
                "disposition",
                "r2_reuse_eligible",
                "reuse_authorized",
                "reason_codes",
            },
            errors,
        )
        if reuse.get("disposition") not in {"eligible", "fresh_only"}:
            errors.append("$.reuse.disposition: unsupported disposition")
        if not isinstance(reuse.get("r2_reuse_eligible"), bool):
            errors.append("$.reuse.r2_reuse_eligible: must be a boolean")
        if reuse.get("reuse_authorized") is not False:
            errors.append("$.reuse.reuse_authorized: must equal False")
        _sorted_unique_strings(reuse.get("reason_codes"), "$.reuse.reason_codes", errors)
        effective = reuse.get("authority_effective")
        if not isinstance(effective, dict) or set(effective) != {
            "reuse_allowed",
            "risk_level",
            "human_gate_required",
        }:
            errors.append("$.reuse.authority_effective: unsupported shape")
        else:
            if not isinstance(effective.get("reuse_allowed"), bool):
                errors.append("$.reuse.authority_effective.reuse_allowed: must be a boolean")
            if effective.get("risk_level") not in {"R0", "R1", "R2", "R3", "R4"}:
                errors.append("$.reuse.authority_effective.risk_level: unsupported risk")
            if not isinstance(effective.get("human_gate_required"), bool):
                errors.append(
                    "$.reuse.authority_effective.human_gate_required: must be a boolean"
                )
        if reuse.get("r2_reuse_eligible") is not (reuse.get("disposition") == "eligible"):
            errors.append("$.reuse.r2_reuse_eligible: must match disposition")
    _false_literals(value, errors)
    return _result(PROOF_WORKSPACE_BINDING_CONTRACT_VERSION, errors)


def _external_input(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    input_type = value.get("type")
    material_kind = value.get("material_kind")
    expected = {
        "file": _FILE_INPUT_FIELDS,
        "directory_bundle": _DIRECTORY_INPUT_FIELDS,
        "submodule": _SUBMODULE_INPUT_FIELDS,
        "opaque": _COMMON_INPUT_FIELDS,
    }.get(input_type)
    if input_type == "materialized_file":
        expected = _LFS_INPUT_FIELDS if material_kind == "git_lfs" else _GENERATED_INPUT_FIELDS
    if expected is None:
        errors.append(f"{path}.type: unsupported external input type")
        return
    _exact_fields(value, path, expected, errors)
    _identifier(value.get("input_id"), f"{path}.input_id", errors)
    _sorted_unique_strings(
        value.get("consumer_check_ids"),
        f"{path}.consumer_check_ids",
        errors,
        require_nonempty=True,
    )
    if value.get("on_unavailable") not in _AVAILABILITY:
        errors.append(f"{path}.on_unavailable: unsupported availability policy")
    if "destination" in expected:
        _relative_path(value.get("destination"), f"{path}.destination", errors)
    if input_type == "file" or input_type == "materialized_file":
        _sha(value.get("sha256"), f"{path}.sha256", errors)
        _nonnegative_int(value.get("size"), f"{path}.size", errors)
        if value.get("mode") not in _PORTABLE_MODE:
            errors.append(f"{path}.mode: unsupported portable mode")
    if input_type == "directory_bundle":
        _sha(value.get("bundle_sha256"), f"{path}.bundle_sha256", errors)
    if input_type == "submodule":
        object_format = value.get("object_format")
        matcher = _OID_BY_FORMAT.get(object_format)
        if matcher is None:
            errors.append(f"{path}.object_format: unsupported Git object format")
        else:
            for field in ("gitlink_oid", "commit_oid", "tree_oid"):
                if not isinstance(value.get(field), str) or matcher.fullmatch(value[field]) is None:
                    errors.append(f"{path}.{field}: invalid full Git OID")
        if value.get("gitlink_oid") != value.get("commit_oid"):
            errors.append(f"{path}.gitlink_oid: must equal commit_oid")
    if input_type == "materialized_file":
        if material_kind not in {"git_lfs", "generated"}:
            errors.append(f"{path}.material_kind: unsupported material kind")
        if material_kind == "git_lfs":
            for field in ("pointer_blob_oid",):
                oid = value.get(field)
                if not isinstance(oid, str) or not any(
                    matcher.fullmatch(oid) for matcher in _OID_BY_FORMAT.values()
                ):
                    errors.append(f"{path}.{field}: invalid Git blob OID")
            _sha(value.get("lfs_oid_sha256"), f"{path}.lfs_oid_sha256", errors)
            _nonnegative_int(value.get("lfs_size"), f"{path}.lfs_size", errors)
            if value.get("lfs_oid_sha256") != value.get("sha256"):
                errors.append(f"{path}.lfs_oid_sha256: must equal sha256")
            if value.get("lfs_size") != value.get("size"):
                errors.append(f"{path}.lfs_size: must equal size")
        elif material_kind == "generated":
            expectation = value.get("base_expectation")
            if not isinstance(expectation, dict) or expectation.get("kind") not in {
                "absent",
                "placeholder",
            }:
                errors.append(f"{path}.base_expectation: unsupported expectation")
            elif expectation["kind"] == "absent":
                _exact_fields(expectation, f"{path}.base_expectation", {"kind"}, errors)
            else:
                _exact_fields(
                    expectation,
                    f"{path}.base_expectation",
                    {"kind", "blob_oid", "mode"},
                    errors,
                )
                oid = expectation.get("blob_oid")
                if not isinstance(oid, str) or not any(
                    matcher.fullmatch(oid) for matcher in _OID_BY_FORMAT.values()
                ):
                    errors.append(f"{path}.base_expectation.blob_oid: invalid Git blob OID")
                if expectation.get("mode") not in _PORTABLE_MODE:
                    errors.append(f"{path}.base_expectation.mode: unsupported mode")


def _schema(resource: str) -> dict[str, Any]:
    return json.loads(files("pcl.contracts").joinpath(resource).read_text(encoding="utf-8"))


def _result(contract_type: str, errors: list[str]) -> ProofWorkspaceValidationResult:
    return ProofWorkspaceValidationResult(contract_type, tuple(errors))


def _exact_fields(
    value: Mapping[str, Any],
    path: str,
    expected: set[str],
    errors: list[str],
) -> None:
    for field in sorted(expected - set(value)):
        errors.append(f"{path}.{field}: is required")
    for field in sorted(set(value) - expected):
        errors.append(f"{path}.{field}: additional property is not allowed")


def _false_literals(value: Mapping[str, Any], errors: list[str]) -> None:
    if value.get("terminal_authority") is not False:
        errors.append("$.terminal_authority: must equal False")
    if value.get("mandatory_evidence") is not False:
        errors.append("$.mandatory_evidence: must equal False")


def _identifier(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        errors.append(f"{path}: invalid identifier")


def _sha(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        errors.append(f"{path}: invalid sha256 digest")


def _relative_path(
    value: Any,
    path: str,
    errors: list[str],
    *,
    allow_dot: bool = False,
) -> None:
    if not isinstance(value, str) or not _is_relative_path(value, allow_dot=allow_dot):
        errors.append(f"{path}: must be a normalized relative POSIX path")


def _relative_pattern(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        errors.append(f"{path}: must be a relative POSIX pattern")
        return
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        errors.append(f"{path}: must not escape the workspace")


def _is_relative_path(value: str, *, allow_dot: bool = False) -> bool:
    if value == ".":
        return allow_dot
    if not value or "\0" in value or "\\" in value or value != unicodedata.normalize("NFC", value):
        return False
    pure = PurePosixPath(value)
    return (
        not pure.is_absolute()
        and bool(pure.parts)
        and all(part not in {"", ".", ".."} for part in pure.parts)
        and str(pure) == value
    )


def _paths_overlap(left: PurePosixPath, right: PurePosixPath) -> bool:
    left_parts = left.parts
    right_parts = right.parts
    shared = min(len(left_parts), len(right_parts))
    return left_parts[:shared] == right_parts[:shared]


def _unique_strings(
    value: Any,
    path: str,
    errors: list[str],
    *,
    require_nonempty: bool = False,
) -> None:
    if not isinstance(value, list) or (require_nonempty and not value):
        errors.append(f"{path}: must be an array")
        return
    if any(not isinstance(item, str) or not item for item in value):
        errors.append(f"{path}: must contain non-empty strings")
        return
    if len(value) != len(set(value)):
        errors.append(f"{path}: values must be unique")


def _sorted_unique_strings(
    value: Any,
    path: str,
    errors: list[str],
    *,
    require_nonempty: bool = False,
) -> None:
    _unique_strings(value, path, errors, require_nonempty=require_nonempty)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        if value != sorted(value):
            errors.append(f"{path}: values must be sorted")


def _referenced_blobs(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict) or set(item) != {"path", "oid"}:
            errors.append(f"{item_path}: must contain only path and oid")
            continue
        _relative_path(item.get("path"), f"{item_path}.path", errors)
        oid = item.get("oid")
        if not isinstance(oid, str) or not any(
            matcher.fullmatch(oid) for matcher in _OID_BY_FORMAT.values()
        ):
            errors.append(f"{item_path}.oid: invalid Git OID")
        key = f"{item.get('path')}:{oid}"
        if key in seen:
            errors.append(f"{item_path}: must be unique")
        seen.add(key)
    if isinstance(value, list) and value != sorted(
        value,
        key=lambda item: (str(item.get("path")), str(item.get("oid")))
        if isinstance(item, dict)
        else ("", ""),
    ):
        errors.append(f"{path}: values must be sorted")


def _positive_bounded_int(value: Any, path: str, errors: list[str], *, maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > maximum:
        errors.append(f"{path}: must be an integer from 1 through {maximum}")


def _nonnegative_int(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(f"{path}: must be a non-negative integer")
