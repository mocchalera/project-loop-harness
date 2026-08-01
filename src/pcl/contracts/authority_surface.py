from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re
from typing import Any

from ._profile_contract import load_strict_json


AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION = "authority-surface-resolution/v1"
AUTHORITY_CATALOG_CONTRACT_VERSION = "authority-impact-catalog/v1"
AUTHORITY_CANARY_CONTRACT_VERSION = "authority-canary-contract/v1"
BOOTSTRAP_AUTHORITY_PROFILE_CONTRACT_VERSION = "bootstrap-authority-profile/v0"

AUTHORITY_SURFACE_RESOLUTION_SCHEMA_RESOURCE = (
    "schemas/authority-surface-resolution-v1.schema.json"
)
BOOTSTRAP_AUTHORITY_PROFILE_SCHEMA_RESOURCE = (
    "schemas/bootstrap-authority-profile-v0.schema.json"
)

RISK_LEVELS = ("R0", "R1", "R2", "R3", "R4")
VERIFICATION_DEPTHS = ("basic", "standard", "independent", "human")
_RISK_RANK = {value: index for index, value in enumerate(RISK_LEVELS)}
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_OID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_CATALOG_FIELDS = {"contract_version", "catalog_id", "rules"}
_CATALOG_RULE_FIELDS = {"id", "minimum_risk", "patterns", "path_class"}
_CANARY_FIELDS = {"contract_version", "items"}
_CANARY_ITEM_FIELDS = {
    "id",
    "authority_claim_ids",
    "command",
    "selectors",
    "required_outcome",
    "referenced_blob_oids",
    "effect_expectations",
    "supported_platform_conditions",
}
_PROFILE_FIELDS = {
    "contract_version",
    "profile_id",
    "resolver_contract_version",
    "authority_catalog",
    "canary_contract",
    "verification_boundary",
}
_RESOLUTION_FIELDS = {
    "contract_version",
    "target",
    "base",
    "candidate",
    "actual_diff",
    "inputs",
    "catalog",
    "canary",
    "resolver",
    "bootstrap_profile",
    "effective",
    "terminal_authority",
    "mandatory_evidence",
}


@dataclass(frozen=True)
class AuthorityContractValidationResult:
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


def authority_surface_resolution_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(AUTHORITY_SURFACE_RESOLUTION_SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def bootstrap_authority_profile_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(BOOTSTRAP_AUTHORITY_PROFILE_SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def authority_document_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def load_bootstrap_authority_profile(path: str | Path) -> dict[str, Any]:
    value = load_strict_json(path)
    validation = validate_bootstrap_authority_profile(value)
    if not validation.ok:
        raise ValueError("; ".join(validation.errors))
    return value


def validate_authority_catalog(
    value: Any,
    *,
    path: str = "$",
) -> AuthorityContractValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return AuthorityContractValidationResult(
            AUTHORITY_CATALOG_CONTRACT_VERSION,
            (f"{path}: must be an object",),
        )
    _exact_fields(value, path, _CATALOG_FIELDS, errors)
    if value.get("contract_version") != AUTHORITY_CATALOG_CONTRACT_VERSION:
        errors.append(
            f"{path}.contract_version: must equal {AUTHORITY_CATALOG_CONTRACT_VERSION!r}"
        )
    _identifier(value.get("catalog_id"), f"{path}.catalog_id", errors)
    rules = value.get("rules")
    if not isinstance(rules, list):
        errors.append(f"{path}.rules: must be an array")
    else:
        seen: set[str] = set()
        for index, rule in enumerate(rules):
            rule_path = f"{path}.rules[{index}]"
            if not isinstance(rule, dict):
                errors.append(f"{rule_path}: must be an object")
                continue
            allowed = set(_CATALOG_RULE_FIELDS)
            if "path_class" not in rule:
                allowed.remove("path_class")
            _exact_fields(rule, rule_path, allowed, errors)
            rule_id = rule.get("id")
            _identifier(rule_id, f"{rule_path}.id", errors)
            if isinstance(rule_id, str):
                if rule_id in seen:
                    errors.append(f"{rule_path}.id: must be unique")
                seen.add(rule_id)
            if rule.get("minimum_risk") not in RISK_LEVELS:
                errors.append(f"{rule_path}.minimum_risk: unsupported risk level")
            _sorted_unique_strings(
                rule.get("patterns"),
                f"{rule_path}.patterns",
                errors,
                require_nonempty=True,
            )
            if rule.get("path_class", "any") not in {"any", "non_executable"}:
                errors.append(f"{rule_path}.path_class: unsupported path class")
    return AuthorityContractValidationResult(
        AUTHORITY_CATALOG_CONTRACT_VERSION,
        tuple(errors),
    )


def validate_authority_canary(
    value: Any,
    *,
    path: str = "$",
) -> AuthorityContractValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return AuthorityContractValidationResult(
            AUTHORITY_CANARY_CONTRACT_VERSION,
            (f"{path}: must be an object",),
        )
    _exact_fields(value, path, _CANARY_FIELDS, errors)
    if value.get("contract_version") != AUTHORITY_CANARY_CONTRACT_VERSION:
        errors.append(
            f"{path}.contract_version: must equal {AUTHORITY_CANARY_CONTRACT_VERSION!r}"
        )
    items = value.get("items")
    if not isinstance(items, list):
        errors.append(f"{path}.items: must be an array")
    else:
        seen: set[str] = set()
        for index, item in enumerate(items):
            item_path = f"{path}.items[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{item_path}: must be an object")
                continue
            _exact_fields(item, item_path, _CANARY_ITEM_FIELDS, errors)
            item_id = item.get("id")
            _identifier(item_id, f"{item_path}.id", errors)
            if isinstance(item_id, str):
                if item_id in seen:
                    errors.append(f"{item_path}.id: must be unique")
                seen.add(item_id)
            for field in (
                "authority_claim_ids",
                "command",
                "selectors",
                "effect_expectations",
                "supported_platform_conditions",
            ):
                _sorted_unique_strings(
                    item.get(field),
                    f"{item_path}.{field}",
                    errors,
                    require_nonempty=True,
                    require_sorted=field != "command",
                )
            blobs = item.get("referenced_blob_oids")
            _sorted_unique_strings(
                blobs,
                f"{item_path}.referenced_blob_oids",
                errors,
                require_nonempty=False,
            )
            if isinstance(blobs, list):
                for blob_index, oid in enumerate(blobs):
                    if not isinstance(oid, str) or _OID.fullmatch(oid) is None:
                        errors.append(
                            f"{item_path}.referenced_blob_oids[{blob_index}]: invalid Git OID"
                        )
            if item.get("required_outcome") != "pass":
                errors.append(f"{item_path}.required_outcome: must equal 'pass'")
    return AuthorityContractValidationResult(
        AUTHORITY_CANARY_CONTRACT_VERSION,
        tuple(errors),
    )


def validate_bootstrap_authority_profile(value: Any) -> AuthorityContractValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return AuthorityContractValidationResult(
            BOOTSTRAP_AUTHORITY_PROFILE_CONTRACT_VERSION,
            ("$: must be an object",),
        )
    _exact_fields(value, "$", _PROFILE_FIELDS, errors)
    if value.get("contract_version") != BOOTSTRAP_AUTHORITY_PROFILE_CONTRACT_VERSION:
        errors.append(
            "$.contract_version: must equal "
            f"{BOOTSTRAP_AUTHORITY_PROFILE_CONTRACT_VERSION!r}"
        )
    _identifier(value.get("profile_id"), "$.profile_id", errors)
    if value.get("resolver_contract_version") != AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION:
        errors.append(
            "$.resolver_contract_version: must equal "
            f"{AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION!r}"
        )
    errors.extend(
        validate_authority_catalog(value.get("authority_catalog"), path="$.authority_catalog").errors
    )
    errors.extend(
        validate_authority_canary(value.get("canary_contract"), path="$.canary_contract").errors
    )
    boundary = value.get("verification_boundary")
    expected_boundary = {
        "exact_candidate_full_regression_required": True,
        "fixed_hash_independent_review_required": True,
        "self_certification_allowed": False,
    }
    if not isinstance(boundary, dict):
        errors.append("$.verification_boundary: must be an object")
    else:
        _exact_fields(boundary, "$.verification_boundary", set(expected_boundary), errors)
        for field, expected in expected_boundary.items():
            if boundary.get(field) is not expected:
                errors.append(f"$.verification_boundary.{field}: must equal {expected!r}")
    return AuthorityContractValidationResult(
        BOOTSTRAP_AUTHORITY_PROFILE_CONTRACT_VERSION,
        tuple(errors),
    )


def validate_authority_surface_resolution(value: Any) -> AuthorityContractValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return AuthorityContractValidationResult(
            AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION,
            ("$: must be an object",),
        )
    _exact_fields(value, "$", _RESOLUTION_FIELDS, errors)
    if value.get("contract_version") != AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION:
        errors.append(
            "$.contract_version: must equal "
            f"{AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION!r}"
        )
    _target(value.get("target"), "$.target", errors)
    _candidate(value.get("candidate"), "$.candidate", errors)
    _base(value.get("base"), "$.base", errors)
    _hash_container(value.get("actual_diff"), "$.actual_diff", errors, keys={"sha256"})
    _hash_container(
        value.get("catalog"),
        "$.catalog",
        errors,
        keys={
            "packaged_minimum_sha256",
            "base_sha256",
            "candidate_sha256",
            "union_sha256",
            "diff_sha256",
        },
    )
    _hash_container(
        value.get("canary"),
        "$.canary",
        errors,
        keys={
            "packaged_minimum_sha256",
            "base_sha256",
            "candidate_sha256",
            "union_sha256",
            "diff_sha256",
        },
    )
    resolver = value.get("resolver")
    if not isinstance(resolver, dict):
        errors.append("$.resolver: must be an object")
    else:
        _sha(resolver.get("sha256"), "$.resolver.sha256", errors)
        if resolver.get("source") not in {
            "trusted_base",
            "pinned_installed",
            "external_bootstrap",
        }:
            errors.append("$.resolver.source: must be a trusted resolver source")
        if resolver.get("candidate_controlled") is not False:
            errors.append("$.resolver.candidate_controlled: must equal False")
    profile = value.get("bootstrap_profile")
    if not isinstance(profile, dict):
        errors.append("$.bootstrap_profile: must be an object")
    else:
        _sha(profile.get("sha256"), "$.bootstrap_profile.sha256", errors)
        if profile.get("self_certification_allowed") is not False:
            errors.append("$.bootstrap_profile.self_certification_allowed: must equal False")
        if profile.get("approval_claimed") is not False:
            errors.append("$.bootstrap_profile.approval_claimed: must equal False")
    effective = value.get("effective")
    if not isinstance(effective, dict):
        errors.append("$.effective: must be an object")
    else:
        if effective.get("risk_level") not in RISK_LEVELS:
            errors.append("$.effective.risk_level: unsupported risk level")
        if effective.get("verification_depth") not in VERIFICATION_DEPTHS:
            errors.append("$.effective.verification_depth: unsupported verification depth")
        if not isinstance(effective.get("human_gate_required"), bool):
            errors.append("$.effective.human_gate_required: must be a boolean")
        if not isinstance(effective.get("reuse_allowed"), bool):
            errors.append("$.effective.reuse_allowed: must be a boolean")
    if value.get("terminal_authority") is not False:
        errors.append("$.terminal_authority: must equal False")
    if value.get("mandatory_evidence") is not False:
        errors.append("$.mandatory_evidence: must equal False")
    return AuthorityContractValidationResult(
        AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION,
        tuple(errors),
    )


def merge_authority_catalogs(*catalogs: Mapping[str, Any]) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    for catalog in catalogs:
        validation = validate_authority_catalog(catalog)
        if not validation.ok:
            raise ValueError("; ".join(validation.errors))
        for raw_rule in catalog["rules"]:
            rule = dict(raw_rule)
            rule.setdefault("path_class", "any")
            rule_id = str(rule["id"])
            current = by_id.get(rule_id)
            if current is None:
                by_id[rule_id] = rule
                continue
            current["minimum_risk"] = max(
                (str(current["minimum_risk"]), str(rule["minimum_risk"])),
                key=_RISK_RANK.__getitem__,
            )
            current["patterns"] = sorted(
                set(str(item) for item in current["patterns"])
                | set(str(item) for item in rule["patterns"])
            )
            if rule["path_class"] == "any":
                current["path_class"] = "any"
    merged_rules = []
    for rule_id in sorted(by_id):
        rule = by_id[rule_id]
        if rule.get("path_class") == "any":
            rule.pop("path_class", None)
        merged_rules.append(rule)
    return {
        "contract_version": AUTHORITY_CATALOG_CONTRACT_VERSION,
        "catalog_id": "effective-union",
        "rules": merged_rules,
    }


def merge_authority_canaries(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    for value in (base, candidate):
        validation = validate_authority_canary(value)
        if not validation.ok:
            raise ValueError("; ".join(validation.errors))
    by_id = {str(item["id"]): dict(item) for item in base["items"]}
    for raw_item in candidate["items"]:
        item = dict(raw_item)
        item_id = str(item["id"])
        current = by_id.get(item_id)
        if current is None:
            by_id[item_id] = item
            continue
        for field in ("command", "required_outcome", "supported_platform_conditions"):
            if item[field] != current[field]:
                raise ValueError(f"canary {item_id!r} conflicts at {field}")
        for field in (
            "authority_claim_ids",
            "selectors",
            "referenced_blob_oids",
            "effect_expectations",
        ):
            current_values = set(str(value) for value in current[field])
            candidate_values = set(str(value) for value in item[field])
            if not candidate_values.issuperset(current_values):
                raise ValueError(f"canary {item_id!r} narrows {field}")
            current[field] = sorted(current_values | candidate_values)
    return {
        "contract_version": AUTHORITY_CANARY_CONTRACT_VERSION,
        "items": [by_id[item_id] for item_id in sorted(by_id)],
    }


def authority_document_diff(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "base_sha256": authority_document_sha256(base),
        "candidate_sha256": authority_document_sha256(candidate),
        "changed": base != candidate,
    }


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


def _identifier(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        errors.append(f"{path}: must be a lowercase identifier")


def _sorted_unique_strings(
    value: Any,
    path: str,
    errors: list[str],
    *,
    require_nonempty: bool,
    require_sorted: bool = True,
) -> None:
    if not isinstance(value, list) or (require_nonempty and not value):
        errors.append(f"{path}: must be {'a non-empty' if require_nonempty else 'an'} array")
        return
    if any(not isinstance(item, str) or not item for item in value):
        errors.append(f"{path}: must contain non-empty strings")
        return
    if len(value) != len(set(value)):
        errors.append(f"{path}: values must be unique")
    if require_sorted and value != sorted(value):
        errors.append(f"{path}: values must be sorted")


def _target(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict) or set(value) != {"type", "id"}:
        errors.append(f"{path}: must contain only type and id")
        return
    if value.get("type") != "task":
        errors.append(f"{path}.type: C1 supports task targets only")
    if not isinstance(value.get("id"), str) or not value["id"]:
        errors.append(f"{path}.id: must be a non-empty string")


def _candidate(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict) or set(value) != {"commit_oid", "tree_oid"}:
        errors.append(f"{path}: must contain commit_oid and tree_oid")
        return
    for field in ("commit_oid", "tree_oid"):
        if not isinstance(value.get(field), str) or _OID.fullmatch(value[field]) is None:
            errors.append(f"{path}.{field}: invalid full Git OID")


def _base(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    if value.get("status") not in {"resolved", "base_unknown", "no_candidate_change"}:
        errors.append(f"{path}.status: unsupported status")
    commit = value.get("commit_oid")
    if commit is not None and (not isinstance(commit, str) or _OID.fullmatch(commit) is None):
        errors.append(f"{path}.commit_oid: invalid full Git OID")
    if not isinstance(value.get("reuse_allowed"), bool):
        errors.append(f"{path}.reuse_allowed: must be a boolean")


def _hash_container(
    value: Any,
    path: str,
    errors: list[str],
    *,
    keys: set[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    for key in sorted(keys):
        _sha(value.get(key), f"{path}.{key}", errors)


def _sha(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        errors.append(f"{path}: invalid sha256 digest")
