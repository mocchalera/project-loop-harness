from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
import json
from pathlib import Path
import re
from typing import Any

from .route_recommendation import validate_route_recommendation


ROUTE_OVERRIDE_CONTRACT_VERSION = "route-override/v1"
SCHEMA_RESOURCE = "schemas/route-override-v1.schema.json"

_FIELDS = {
    "contract_version",
    "override_digest",
    "target",
    "actor",
    "reason",
    "requested_profile",
    "original_recommendation_ref",
    "original_recommendation_sha256",
    "original_resolution_ref",
    "original_resolution_sha256",
    "effective_recommendation",
    "effective_recommendation_sha256",
    "effective_resolution",
    "effective_resolution_sha256",
}
_PROFILES = {"direct", "discover", "assure"}
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVIDENCE_REF = re.compile(r"^evidence:E-[0-9]{4,}$")


@dataclass(frozen=True)
class RouteOverrideValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": ROUTE_OVERRIDE_CONTRACT_VERSION,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def route_override_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def canonical_route_override_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def serialized_route_override(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def load_route_override(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_non_finite)


def validate_route_override(value: Any) -> RouteOverrideValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return RouteOverrideValidationResult(("$: must be an object",))
    for field in sorted(_FIELDS - set(value)):
        errors.append(f"$.{field}: is required")
    for field in sorted(set(value) - _FIELDS):
        errors.append(f"$.{field}: additional property is not allowed")
    if value.get("contract_version") != ROUTE_OVERRIDE_CONTRACT_VERSION:
        errors.append(
            f"$.contract_version: must equal {ROUTE_OVERRIDE_CONTRACT_VERSION!r}"
        )
    _pattern(value.get("override_digest"), "$.override_digest", _SHA256, errors)
    target = value.get("target")
    if not isinstance(target, dict) or set(target) != {"type", "id"}:
        errors.append("$.target: must contain only type and id")
    _nonempty(value.get("actor"), "$.actor", errors)
    _nonempty(value.get("reason"), "$.reason", errors)
    if value.get("requested_profile") not in _PROFILES:
        errors.append("$.requested_profile: unsupported profile")
    for field in ("original_recommendation_ref", "original_resolution_ref"):
        _pattern(value.get(field), f"$.{field}", _EVIDENCE_REF, errors)
    for field in (
        "original_recommendation_sha256",
        "original_resolution_sha256",
        "effective_recommendation_sha256",
        "effective_resolution_sha256",
    ):
        _pattern(value.get(field), f"$.{field}", _SHA256, errors)
    effective_recommendation = value.get("effective_recommendation")
    route_validation = validate_route_recommendation(effective_recommendation)
    errors.extend(f"$.effective_recommendation{error[1:]}" for error in route_validation.errors)
    effective_resolution = value.get("effective_resolution")
    if not isinstance(effective_resolution, dict):
        errors.append("$.effective_resolution: must be an object")
    elif target != effective_resolution.get("target"):
        errors.append("$.effective_resolution.target: must match $.target")
    if isinstance(effective_recommendation, dict) and target != effective_recommendation.get("target"):
        errors.append("$.effective_recommendation.target: must match $.target")
    return RouteOverrideValidationResult(tuple(errors))


def _nonempty(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: must be a non-empty string")


def _pattern(value: Any, path: str, pattern: re.Pattern[str], errors: list[str]) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        errors.append(f"{path}: has invalid format")


def _reject_non_finite(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value} is not allowed")
