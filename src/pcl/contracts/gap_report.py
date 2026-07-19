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


GAP_REPORT_CONTRACT_VERSION = "gap-report/v1"
SCHEMA_RESOURCE = "schemas/gap-report-v1.schema.json"

GAP_CLASSES = {
    "context",
    "capability",
    "domain_ownership",
    "authority",
    "proof",
    "feedback_delivery",
    "worker_limitation",
}
DURABLE_OWNERS = {
    "agents_md",
    "skill",
    "types",
    "api",
    "tests",
    "runbook",
    "project_docs",
    "tool_error_message",
}

_FIELDS = {
    "contract_version",
    "producer",
    "generated_at",
    "target",
    "related",
    "earliest_failed_handoff",
    "gap_class",
    "candidate_lessons",
}
_REQUIRED = _FIELDS - {"related"}
_TARGETS = {
    "goal": re.compile(r"^G-[0-9]{4,}$"),
    "task": re.compile(r"^T-[0-9]{4,}$"),
    "feature": re.compile(r"^F-[0-9]{4,}$"),
    "defect": re.compile(r"^D-[0-9]{4,}$"),
    "workflow_run": re.compile(r"^WR-[0-9]{4,}$"),
    "agent_job": re.compile(r"^J-[0-9]{4,}$"),
}
_EVIDENCE_REF = re.compile(r"^evidence:E-[0-9]{4,}$")
_PACKET_ID = re.compile(r"^cp-sha256:[0-9a-f]{64}$")
_WORKFLOW_RUN_ID = re.compile(r"^WR-[0-9]{4,}$")
_LESSON_ID = re.compile(r"^lesson-[a-z0-9][a-z0-9._-]*$")
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
)


@dataclass(frozen=True)
class GapReportValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": GAP_REPORT_CONTRACT_VERSION,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def gap_report_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def load_gap_report(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_non_finite)


def canonical_gap_report_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        report,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def serialized_gap_report(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def gap_report_sha256(report: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_gap_report_json(report).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def gap_lesson_sha256(lesson: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            lesson,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def validate_gap_report(value: Any) -> GapReportValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return GapReportValidationResult(("$: must be an object",))
    _non_finite(value, "$", errors)
    _fields(value, "$", _REQUIRED, _FIELDS, errors)
    _equal(value.get("contract_version"), GAP_REPORT_CONTRACT_VERSION, "$.contract_version", errors)
    _producer(value.get("producer"), errors)
    _timestamp(value.get("generated_at"), "$.generated_at", errors)
    _target(value.get("target"), errors)
    if "related" in value:
        _related(value.get("related"), errors)
    _handoff(value.get("earliest_failed_handoff"), errors)
    _enum(value.get("gap_class"), GAP_CLASSES, "$.gap_class", errors)
    _lessons(value.get("candidate_lessons"), errors)
    return GapReportValidationResult(tuple(errors))


def _producer(value: Any, errors: list[str]) -> None:
    path = "$.producer"
    if not _object(value, path, errors):
        return
    _fields(value, path, {"name", "version"}, {"name", "version"}, errors)
    _string(value.get("name"), f"{path}.name", errors)
    _string(value.get("version"), f"{path}.version", errors)


def _target(value: Any, errors: list[str]) -> None:
    path = "$.target"
    if not _object(value, path, errors):
        return
    _fields(value, path, {"type", "id"}, {"type", "id"}, errors)
    target_type = value.get("type")
    _enum(target_type, set(_TARGETS), f"{path}.type", errors)
    pattern = _TARGETS.get(target_type) if isinstance(target_type, str) else None
    _string(value.get("id"), f"{path}.id", errors, pattern=pattern)


def _related(value: Any, errors: list[str]) -> None:
    path = "$.related"
    if not _object(value, path, errors):
        return
    allowed = {"packet_id", "evidence_refs", "workflow_run"}
    _fields(value, path, set(), allowed, errors)
    packet_id = value.get("packet_id")
    if packet_id is not None:
        _string(packet_id, f"{path}.packet_id", errors, pattern=_PACKET_ID)
    evidence_refs = value.get("evidence_refs")
    if evidence_refs is not None:
        _reference_array(evidence_refs, f"{path}.evidence_refs", errors)
    workflow_run = value.get("workflow_run")
    if workflow_run is not None:
        _string(workflow_run, f"{path}.workflow_run", errors, pattern=_WORKFLOW_RUN_ID)


def _handoff(value: Any, errors: list[str]) -> None:
    path = "$.earliest_failed_handoff"
    if not _object(value, path, errors):
        return
    _fields(value, path, {"stage", "description"}, {"stage", "description"}, errors)
    _string(value.get("stage"), f"{path}.stage", errors)
    _string(value.get("description"), f"{path}.description", errors)


def _lessons(value: Any, errors: list[str]) -> None:
    path = "$.candidate_lessons"
    if not _array(value, path, errors):
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not _object(item, item_path, errors):
            continue
        allowed = {"lesson_id", "lesson", "durable_owner", "evidence_refs"}
        _fields(item, item_path, allowed, allowed, errors)
        lesson_id = item.get("lesson_id")
        _string(lesson_id, f"{item_path}.lesson_id", errors, pattern=_LESSON_ID)
        if isinstance(lesson_id, str):
            if lesson_id in seen:
                errors.append(f"{item_path}.lesson_id: must be unique")
            seen.add(lesson_id)
        _string(item.get("lesson"), f"{item_path}.lesson", errors)
        _enum(item.get("durable_owner"), DURABLE_OWNERS, f"{item_path}.durable_owner", errors)
        _reference_array(item.get("evidence_refs"), f"{item_path}.evidence_refs", errors)


def _reference_array(value: Any, path: str, errors: list[str]) -> None:
    if not _array(value, path, errors):
        return
    for index, item in enumerate(value):
        _string(item, f"{path}[{index}]", errors, pattern=_EVIDENCE_REF)


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


def _string(
    value: Any,
    path: str,
    errors: list[str],
    *,
    pattern: re.Pattern[str] | None = None,
) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: must be a non-empty string")
        return
    if pattern is not None and pattern.fullmatch(value) is None:
        errors.append(f"{path}: has invalid format")


def _enum(value: Any, allowed: set[str], path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or value not in allowed:
        errors.append(f"{path}: must be one of {', '.join(sorted(allowed))}")


def _equal(value: Any, expected: Any, path: str, errors: list[str]) -> None:
    if value != expected:
        errors.append(f"{path}: must equal {expected!r}")


def _timestamp(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        errors.append(f"{path}: must be an RFC 3339 UTC timestamp at second precision ending in Z")
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
    raise ValueError(f"Non-finite JSON number is not allowed: {value}")
