from __future__ import annotations

import hashlib
from importlib.resources import files
import json
from pathlib import Path
from typing import Any

from .contracts.route_recommendation import (
    canonical_route_recommendation_json,
    validate_route_recommendation,
)
from .errors import InvalidInputError, PclError
from .paths import ProjectPaths
from .routing import recommend_route


ADAPTIVE_POLICY_CONTRACT_VERSION = "adaptive-policy/v1"
POLICY_RESOLUTION_CONTRACT_VERSION = "adaptive-policy-resolution/v1"
DEFAULT_POLICY_RESOURCE = "policies/adaptive-policy-v1-default.json"
POLICY_RESOLUTION_SCHEMA_RESOURCE = "schemas/adaptive-policy-resolution-v1.schema.json"

AXES = {
    "planning_depth",
    "verification_depth",
    "execution_chunk_size",
    "checkpoint_frequency",
    "context_budget_bytes",
    "tool_call_budget",
    "wall_time_budget_seconds",
    "escalation_budget",
}
_POLICY_FIELDS = {
    "contract_version",
    "policy_version",
    "defaults",
    "profile_rules",
    "rules",
    "risk_floors",
}
_PROFILES = {"direct", "discover", "assure"}
_RISKS = {"R0", "R1", "R2", "R3", "R4"}
_PLANNING = {"none", "light", "full"}
_VERIFICATION = {"basic", "standard", "independent", "human"}
_CHUNKS = {"large", "medium", "small"}
_CHECKPOINTS = {"low", "medium", "high"}
_VERIFICATION_RANK = {"basic": 0, "standard": 1, "independent": 2, "human": 3}
_CHUNK_RANK = {"large": 0, "medium": 1, "small": 2}
_CHECKPOINT_RANK = {"low": 0, "medium": 1, "high": 2}


class AdaptivePolicyError(PclError):
    pass


def default_policy() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(DEFAULT_POLICY_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def policy_resolution_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(POLICY_RESOLUTION_SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def load_policy(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        value = default_policy()
    else:
        try:
            with Path(path).open(encoding="utf-8") as handle:
                value = json.load(handle, parse_constant=_reject_non_finite)
        except OSError as exc:
            raise InvalidInputError(
                f"Could not read adaptive policy: {path}",
                details={"path": str(path), "reason": str(exc)},
            ) from exc
        except json.JSONDecodeError as exc:
            raise InvalidInputError(
                f"Adaptive policy is not valid JSON: {path}",
                details={"path": str(path), "line": exc.lineno, "column": exc.colno},
            ) from exc
        except ValueError as exc:
            raise InvalidInputError(
                f"Adaptive policy contains an invalid JSON value: {path}",
                details={"path": str(path), "reason": str(exc)},
            ) from exc
    errors = validate_policy(value)
    if errors:
        raise _error(
            "adaptive_policy_invalid",
            "Adaptive policy validation failed.",
            errors=errors,
            path=None if path is None else str(path),
        )
    return value


def validate_policy(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["$: must be an object"]
    _exact_fields(value, "$", _POLICY_FIELDS, errors)
    if value.get("contract_version") != ADAPTIVE_POLICY_CONTRACT_VERSION:
        errors.append(
            f"$.contract_version: must equal {ADAPTIVE_POLICY_CONTRACT_VERSION!r}"
        )
    _nonempty_string(value.get("policy_version"), "$.policy_version", errors)
    defaults = value.get("defaults")
    if isinstance(defaults, dict):
        _exact_fields(defaults, "$.defaults", AXES, errors)
        _validate_axes(defaults, "$.defaults", errors)
    else:
        errors.append("$.defaults: must be an object")
    profiles = value.get("profile_rules")
    if isinstance(profiles, dict):
        _exact_fields(profiles, "$.profile_rules", _PROFILES, errors)
        for profile in sorted(_PROFILES):
            _partial_axes(profiles.get(profile), f"$.profile_rules.{profile}", errors)
    else:
        errors.append("$.profile_rules: must be an object")
    floors = value.get("risk_floors")
    if isinstance(floors, dict):
        _exact_fields(floors, "$.risk_floors", _RISKS, errors)
        for risk in sorted(_RISKS):
            _partial_axes(floors.get(risk), f"$.risk_floors.{risk}", errors)
        _validate_non_overridable_floors(floors, errors)
    else:
        errors.append("$.risk_floors: must be an object")
    rules = value.get("rules")
    if not isinstance(rules, list):
        errors.append("$.rules: must be an array")
    else:
        seen: set[str] = set()
        for index, rule in enumerate(rules):
            path = f"$.rules[{index}]"
            if not isinstance(rule, dict):
                errors.append(f"{path}: must be an object")
                continue
            _exact_fields(rule, path, {"id", "when", "set"}, errors)
            rule_id = rule.get("id")
            _nonempty_string(rule_id, f"{path}.id", errors)
            if isinstance(rule_id, str):
                if rule_id in seen:
                    errors.append(f"{path}.id: must be unique")
                seen.add(rule_id)
            _validate_when(rule.get("when"), f"{path}.when", errors)
            _partial_axes(rule.get("set"), f"{path}.set", errors, require_nonempty=True)
    return errors


def resolve_policy(
    recommendation: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recommendation_validation = validate_route_recommendation(recommendation)
    if not recommendation_validation.ok:
        raise _error(
            "adaptive_policy_route_invalid",
            "Route recommendation is invalid.",
            errors=list(recommendation_validation.errors),
        )
    policy = default_policy() if policy is None else policy
    policy_errors = validate_policy(policy)
    if policy_errors:
        raise _error(
            "adaptive_policy_invalid",
            "Adaptive policy validation failed.",
            errors=policy_errors,
        )
    axes = dict(policy["defaults"])
    sources = {axis: "defaults" for axis in AXES}
    profile = str(recommendation["profile"])
    risk = str(recommendation["risk_level"])
    for axis, value in policy["profile_rules"][profile].items():
        axes[axis] = value
        sources[axis] = f"profile:{profile}"
    matches = [rule for rule in policy["rules"] if _matches(rule["when"], recommendation)]
    _reject_rule_conflicts(matches)
    for rule in matches:
        for axis, value in rule["set"].items():
            axes[axis] = value
            sources[axis] = f"rule:{rule['id']}"
    for axis, value in policy["risk_floors"][risk].items():
        axes[axis] = value
        sources[axis] = f"risk_floor:{risk}"
    policy_sha = "sha256:" + hashlib.sha256(_canonical_json(policy).encode("utf-8")).hexdigest()
    recommendation_digest = "sha256:" + hashlib.sha256(
        canonical_route_recommendation_json(recommendation).encode("utf-8")
    ).hexdigest()
    return {
        "contract_version": POLICY_RESOLUTION_CONTRACT_VERSION,
        "policy_version": policy["policy_version"],
        "policy_sha256": policy_sha,
        "target": recommendation["target"],
        "recommendation_digest": recommendation_digest,
        "profile": profile,
        "risk_level": risk,
        "axes": {axis: axes[axis] for axis in sorted(AXES)},
        "sources": {axis: sources[axis] for axis in sorted(AXES)},
        "matched_rule_ids": sorted(str(rule["id"]) for rule in matches),
        "reason_codes": list(recommendation["reason_codes"]),
    }


def resolve_policy_for_target(
    paths: ProjectPaths,
    *,
    target_ref: str,
    brief_file: str | None = None,
    changed_paths: list[str] | None = None,
    policy_file: str | None = None,
) -> dict[str, Any]:
    recommendation = recommend_route(
        paths,
        target_ref=target_ref,
        brief_file=brief_file,
        changed_paths=changed_paths,
        record=False,
    )["recommendation"]
    policy = load_policy(policy_file)
    return {
        "ok": True,
        "resolution": resolve_policy(recommendation, policy=policy),
        "recommendation": recommendation,
    }


def render_policy_explanation(resolution: dict[str, Any]) -> str:
    lines = [
        f"Policy {resolution['policy_version']} ({resolution['policy_sha256']})",
        f"Route: {resolution['profile']} risk={resolution['risk_level']}",
        "Resolved axes:",
    ]
    for axis, value in resolution["axes"].items():
        lines.append(f"- {axis}: {value} ({resolution['sources'][axis]})")
    if resolution["matched_rule_ids"]:
        lines.append("Matched rules: " + ", ".join(resolution["matched_rule_ids"]))
    lines.append("Reasons: " + ", ".join(resolution["reason_codes"]))
    return "\n".join(lines) + "\n"


def _validate_axes(value: dict[str, Any], path: str, errors: list[str]) -> None:
    for axis in sorted(AXES):
        _validate_axis(axis, value.get(axis), f"{path}.{axis}", errors)


def _partial_axes(
    value: Any,
    path: str,
    errors: list[str],
    *,
    require_nonempty: bool = False,
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    unknown = set(value) - AXES
    for field in sorted(unknown):
        errors.append(f"{path}.{field}: unknown policy axis")
    if require_nonempty and not value:
        errors.append(f"{path}: must set at least one axis")
    for axis, item in value.items():
        if axis in AXES:
            _validate_axis(axis, item, f"{path}.{axis}", errors)


def _validate_axis(axis: str, value: Any, path: str, errors: list[str]) -> None:
    enums = {
        "planning_depth": _PLANNING,
        "verification_depth": _VERIFICATION,
        "execution_chunk_size": _CHUNKS,
        "checkpoint_frequency": _CHECKPOINTS,
    }
    if axis in enums:
        if value not in enums[axis]:
            errors.append(f"{path}: unsupported value")
        return
    if axis in {"tool_call_budget", "wall_time_budget_seconds"} and value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(f"{path}: must be a non-negative integer or allowed null")


def _validate_when(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    allowed = {"profiles", "risk_levels", "reason_codes_any"}
    for key in sorted(set(value) - allowed):
        errors.append(f"{path}.{key}: unknown condition")
    if not value:
        errors.append(f"{path}: must contain at least one condition")
    _enum_list(value.get("profiles"), f"{path}.profiles", _PROFILES, errors, optional=True)
    _enum_list(value.get("risk_levels"), f"{path}.risk_levels", _RISKS, errors, optional=True)
    reasons = value.get("reason_codes_any")
    if reasons is not None and (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(item, str) or not item for item in reasons)
    ):
        errors.append(f"{path}.reason_codes_any: must be a non-empty string array")


def _enum_list(
    value: Any,
    path: str,
    allowed: set[str],
    errors: list[str],
    *,
    optional: bool,
) -> None:
    if value is None and optional:
        return
    if not isinstance(value, list) or not value or any(item not in allowed for item in value):
        errors.append(f"{path}: contains unsupported values")


def _validate_non_overridable_floors(floors: dict[str, Any], errors: list[str]) -> None:
    minimums = {
        "R2": {"verification_depth": ("independent", _VERIFICATION_RANK)},
        "R3": {
            "verification_depth": ("independent", _VERIFICATION_RANK),
            "execution_chunk_size": ("small", _CHUNK_RANK),
            "checkpoint_frequency": ("high", _CHECKPOINT_RANK),
        },
        "R4": {
            "verification_depth": ("human", _VERIFICATION_RANK),
            "execution_chunk_size": ("small", _CHUNK_RANK),
            "checkpoint_frequency": ("high", _CHECKPOINT_RANK),
        },
    }
    for risk, axes in minimums.items():
        floor = floors.get(risk)
        if not isinstance(floor, dict):
            continue
        for axis, (minimum, ranking) in axes.items():
            actual = floor.get(axis)
            if actual not in ranking or ranking[actual] < ranking[minimum]:
                errors.append(
                    f"$.risk_floors.{risk}.{axis}: must not be weaker than {minimum}"
                )


def _matches(when: dict[str, Any], recommendation: dict[str, Any]) -> bool:
    profiles = when.get("profiles")
    if profiles is not None and recommendation["profile"] not in profiles:
        return False
    risks = when.get("risk_levels")
    if risks is not None and recommendation["risk_level"] not in risks:
        return False
    reason_codes = when.get("reason_codes_any")
    if reason_codes is not None and not set(reason_codes) & set(recommendation["reason_codes"]):
        return False
    return True


def _reject_rule_conflicts(rules: list[dict[str, Any]]) -> None:
    by_axis: dict[str, dict[Any, list[str]]] = {}
    for rule in rules:
        for axis, value in rule["set"].items():
            by_axis.setdefault(axis, {}).setdefault(_hashable(value), []).append(str(rule["id"]))
    conflicts = {
        axis: sorted(rule_id for ids in values.values() for rule_id in ids)
        for axis, values in by_axis.items()
        if len(values) > 1
    }
    if conflicts:
        raise _error(
            "adaptive_policy_rule_conflict",
            "Matched project rules set conflicting values at the same precedence.",
            conflicts=conflicts,
        )


def _exact_fields(value: dict[str, Any], path: str, expected: set[str], errors: list[str]) -> None:
    for field in sorted(expected - set(value)):
        errors.append(f"{path}.{field}: is required")
    for field in sorted(set(value) - expected):
        errors.append(f"{path}.{field}: unknown field")


def _nonempty_string(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: must be a non-empty string")


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _hashable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return _canonical_json(value)


def _reject_non_finite(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value} is not allowed")


def _error(code: str, message: str, **details: Any) -> AdaptivePolicyError:
    return AdaptivePolicyError(message=message, code=code, details=details)
