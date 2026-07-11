from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
import json
from pathlib import Path
import re
from typing import Any


ROUTE_RECOMMENDATION_CONTRACT_VERSION = "route-recommendation/v1"
ROUTE_POLICY_VERSION = "adaptive-entry-route/v1"
SCHEMA_RESOURCE = "schemas/route-recommendation-v1.schema.json"

_FIELDS = {
    "contract_version",
    "policy_version",
    "target",
    "input_digest",
    "profile",
    "risk_level",
    "signals",
    "reason_codes",
    "work_brief_ref",
    "work_brief_sha256",
}
_TARGET_TYPES = {"goal", "task", "feature", "story", "defect", "workflow_run"}
_PROFILES = {"direct", "discover", "assure"}
_RISK_LEVELS = {"R0", "R1", "R2", "R3", "R4"}
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVIDENCE_REF = re.compile(r"^evidence:E-[0-9]{4,}$")
_REASON = re.compile(r"^[a-z0-9_.-]+$")


@dataclass(frozen=True)
class RouteRecommendationValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": ROUTE_RECOMMENDATION_CONTRACT_VERSION,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def route_recommendation_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def canonical_route_recommendation_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def load_route_recommendation(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(
            handle,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number {value} is not allowed")
            ),
        )


def serialized_route_recommendation(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def validate_route_recommendation(value: Any) -> RouteRecommendationValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return RouteRecommendationValidationResult(("$: must be an object",))
    for field in sorted(_FIELDS - set(value)):
        errors.append(f"$.{field}: is required")
    for field in sorted(set(value) - _FIELDS):
        errors.append(f"$.{field}: additional property is not allowed")
    if value.get("contract_version") != ROUTE_RECOMMENDATION_CONTRACT_VERSION:
        errors.append(
            f"$.contract_version: must equal {ROUTE_RECOMMENDATION_CONTRACT_VERSION!r}"
        )
    _string(value.get("policy_version"), "$.policy_version", errors)
    target = value.get("target")
    if not isinstance(target, dict):
        errors.append("$.target: must be an object")
    else:
        if set(target) != {"type", "id"}:
            errors.append("$.target: must contain only type and id")
        if target.get("type") not in _TARGET_TYPES:
            errors.append("$.target.type: unsupported target type")
        _string(target.get("id"), "$.target.id", errors)
    _pattern(value.get("input_digest"), "$.input_digest", _SHA256, errors)
    if value.get("profile") not in _PROFILES:
        errors.append("$.profile: must be one of assure, direct, discover")
    if value.get("risk_level") not in _RISK_LEVELS:
        errors.append("$.risk_level: must be one of R0, R1, R2, R3, R4")
    if not isinstance(value.get("signals"), dict):
        errors.append("$.signals: must be an object")
    reasons = value.get("reason_codes")
    if not isinstance(reasons, list) or not reasons:
        errors.append("$.reason_codes: must be a non-empty array")
    else:
        if reasons != sorted(set(reasons)):
            errors.append("$.reason_codes: must be unique and sorted")
        for index, reason in enumerate(reasons):
            _pattern(reason, f"$.reason_codes[{index}]", _REASON, errors)
    brief_ref = value.get("work_brief_ref")
    if brief_ref is not None:
        _pattern(brief_ref, "$.work_brief_ref", _EVIDENCE_REF, errors)
    brief_sha = value.get("work_brief_sha256")
    if brief_sha is not None:
        _pattern(brief_sha, "$.work_brief_sha256", _SHA256, errors)
    if (brief_ref is None) != (brief_sha is None):
        errors.append("$: work_brief_ref and work_brief_sha256 must both be null or both be set")
    return RouteRecommendationValidationResult(tuple(errors))


def _string(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: must be a non-empty string")


def _pattern(value: Any, path: str, pattern: re.Pattern[str], errors: list[str]) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        errors.append(f"{path}: has invalid format")
