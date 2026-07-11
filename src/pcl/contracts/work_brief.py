from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
from importlib.resources import files
import json
import math
from pathlib import Path
import re
from typing import Any


WORK_BRIEF_CONTRACT_VERSION = "work-brief/v1"
SCHEMA_RESOURCE = "schemas/work-brief-v1.schema.json"

_FIELDS = {
    "contract_version",
    "brief_id",
    "revision",
    "target",
    "intent",
    "acceptance_criteria",
    "constraints",
    "non_goals",
    "assumptions",
    "route_recommendation_evidence_id",
    "created_at",
    "created_by",
}
_REQUIRED = _FIELDS - {"route_recommendation_evidence_id"}
_BRIEF_ID = re.compile(r"^WB-[0-9]{4,}$")
_EVIDENCE_ID = re.compile(r"^E-[0-9]{4,}$")
_TARGETS = {
    "goal": re.compile(r"^G-[0-9]{4,}$"),
    "task": re.compile(r"^T-[0-9]{4,}$"),
    "feature": re.compile(r"^F-[0-9]{4,}$"),
    "story": re.compile(r"^US-[0-9]{4,}$"),
    "defect": re.compile(r"^D-[0-9]{4,}$"),
    "workflow_run": re.compile(r"^WR-[0-9]{4,}$"),
}
_CONSTRAINT_STRENGTHS = {"invariant", "inherited_default", "local"}
_ASSUMPTION_STATUSES = {"unverified", "supported", "contradicted", "retired"}


@dataclass(frozen=True)
class WorkBriefValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": WORK_BRIEF_CONTRACT_VERSION,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def work_brief_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def load_work_brief(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_non_finite)


def canonical_work_brief_json(brief: Mapping[str, Any]) -> str:
    return json.dumps(
        brief,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def work_brief_sha256(brief: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_work_brief_json(brief).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def serialized_work_brief(brief: Mapping[str, Any]) -> str:
    return json.dumps(brief, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def validate_work_brief(value: Any) -> WorkBriefValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return WorkBriefValidationResult(("$: must be an object",))
    _non_finite(value, "$", errors)
    _fields(value, "$", _REQUIRED, _FIELDS, errors)
    _equal(value.get("contract_version"), WORK_BRIEF_CONTRACT_VERSION, "$.contract_version", errors)
    _string(value.get("brief_id"), "$.brief_id", errors, pattern=_BRIEF_ID)
    revision = value.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        errors.append("$.revision: must be an integer greater than or equal to 1")
    _target(value.get("target"), errors)
    _intent(value.get("intent"), errors)
    _acceptance(value.get("acceptance_criteria"), errors)
    _constraints(value.get("constraints"), errors)
    _string_array(value.get("non_goals"), "$.non_goals", errors)
    _assumptions(value.get("assumptions"), errors)
    route_ref = value.get("route_recommendation_evidence_id")
    if route_ref is not None:
        _string(route_ref, "$.route_recommendation_evidence_id", errors, pattern=_EVIDENCE_ID)
    _timestamp(value.get("created_at"), "$.created_at", errors)
    _string(value.get("created_by"), "$.created_by", errors)
    return WorkBriefValidationResult(tuple(errors))


def _target(value: Any, errors: list[str]) -> None:
    if not _object(value, "$.target", errors):
        return
    _fields(value, "$.target", {"type", "id"}, {"type", "id"}, errors)
    target_type = value.get("type")
    if target_type not in _TARGETS:
        errors.append("$.target.type: must be one of defect, feature, goal, story, task, workflow_run")
    _string(value.get("id"), "$.target.id", errors, pattern=_TARGETS.get(target_type))


def _intent(value: Any, errors: list[str]) -> None:
    if not _object(value, "$.intent", errors):
        return
    allowed = {"problem", "desired_outcome", "target_user"}
    _fields(value, "$.intent", {"problem", "desired_outcome"}, allowed, errors)
    _string(value.get("problem"), "$.intent.problem", errors)
    _string(value.get("desired_outcome"), "$.intent.desired_outcome", errors)
    target_user = value.get("target_user")
    if target_user is not None:
        _string(target_user, "$.intent.target_user", errors)


def _acceptance(value: Any, errors: list[str]) -> None:
    if not _array(value, "$.acceptance_criteria", errors):
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        path = f"$.acceptance_criteria[{index}]"
        if not _object(item, path, errors):
            continue
        allowed = {"id", "text", "critical", "evidence_refs"}
        _fields(item, path, allowed, allowed, errors)
        item_id = item.get("id")
        _string(item_id, f"{path}.id", errors)
        if isinstance(item_id, str):
            if item_id in seen:
                errors.append(f"{path}.id: must be unique")
            seen.add(item_id)
        _string(item.get("text"), f"{path}.text", errors)
        if not isinstance(item.get("critical"), bool):
            errors.append(f"{path}.critical: must be a boolean")
        _evidence_refs(item.get("evidence_refs"), f"{path}.evidence_refs", errors)


def _constraints(value: Any, errors: list[str]) -> None:
    if not _array(value, "$.constraints", errors):
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        path = f"$.constraints[{index}]"
        if not _object(item, path, errors):
            continue
        allowed = {"id", "text", "strength", "source_evidence_refs"}
        _fields(item, path, allowed, allowed, errors)
        item_id = item.get("id")
        _string(item_id, f"{path}.id", errors)
        if isinstance(item_id, str):
            if item_id in seen:
                errors.append(f"{path}.id: must be unique")
            seen.add(item_id)
        _string(item.get("text"), f"{path}.text", errors)
        if item.get("strength") not in _CONSTRAINT_STRENGTHS:
            errors.append(f"{path}.strength: must be one of inherited_default, invariant, local")
        _evidence_refs(item.get("source_evidence_refs"), f"{path}.source_evidence_refs", errors)


def _assumptions(value: Any, errors: list[str]) -> None:
    if not _array(value, "$.assumptions", errors):
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        path = f"$.assumptions[{index}]"
        if not _object(item, path, errors):
            continue
        allowed = {"id", "text", "status", "evidence_refs"}
        _fields(item, path, allowed, allowed, errors)
        item_id = item.get("id")
        _string(item_id, f"{path}.id", errors)
        if isinstance(item_id, str):
            if item_id in seen:
                errors.append(f"{path}.id: must be unique")
            seen.add(item_id)
        _string(item.get("text"), f"{path}.text", errors)
        if item.get("status") not in _ASSUMPTION_STATUSES:
            errors.append(f"{path}.status: must be one of contradicted, retired, supported, unverified")
        _evidence_refs(item.get("evidence_refs"), f"{path}.evidence_refs", errors)


def _evidence_refs(value: Any, path: str, errors: list[str]) -> None:
    if not _array(value, path, errors):
        return
    for index, item in enumerate(value):
        _string(item, f"{path}[{index}]", errors, pattern=_EVIDENCE_ID)


def _fields(
    value: Mapping[str, Any],
    path: str,
    required: set[str],
    allowed: set[str],
    errors: list[str],
) -> None:
    for field in sorted(required - set(value)):
        errors.append(f"{path}.{field}: is required")
    for field in sorted(set(value) - allowed):
        errors.append(f"{path}.{field}: additional property is not allowed")


def _object(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return False
    return True


def _array(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return False
    return True


def _string(value: Any, path: str, errors: list[str], *, pattern: re.Pattern[str] | None = None) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: must be a non-empty string")
        return
    if pattern is not None and pattern.fullmatch(value) is None:
        errors.append(f"{path}: has invalid format")


def _string_array(value: Any, path: str, errors: list[str]) -> None:
    if not _array(value, path, errors):
        return
    for index, item in enumerate(value):
        _string(item, f"{path}[{index}]", errors)


def _equal(value: Any, expected: Any, path: str, errors: list[str]) -> None:
    if value != expected:
        errors.append(f"{path}: must equal {expected!r}")


def _timestamp(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        errors.append(f"{path}: must be an RFC 3339 UTC date-time ending in Z")
        return
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        errors.append(f"{path}: must be a real RFC 3339 UTC date-time")


def _non_finite(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path}: non-finite JSON numbers are not allowed")
    elif isinstance(value, dict):
        for key, child in value.items():
            _non_finite(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _non_finite(child, f"{path}[{index}]", errors)


def _reject_non_finite(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value} is not allowed")
