from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
import json
from pathlib import Path
import re
from typing import Any


COMPLETION_POLICY_CONTRACT_VERSION = "completion-policy/v1"
COMPLETION_EVALUATION_CONTRACT_VERSION = "completion-evaluation/v1"
SCHEMA_RESOURCE = "schemas/completion-policy-v1.schema.json"

_POLICY_FIELDS = {
    "contract_version",
    "policy_id",
    "required_evidence_set_status",
    "predicates",
}
_PREDICATE_BASE = {"id", "report_kind", "json_path", "operator"}
_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_JSON_PATH = re.compile(r"^\$(?:\.[A-Za-z0-9_-]+)*$")
_OPERATORS = {"empty", "equals", "exists", "gte", "in", "lte"}


@dataclass(frozen=True)
class CompletionPolicyValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": COMPLETION_POLICY_CONTRACT_VERSION,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def completion_policy_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def load_completion_policy(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_non_finite)


def canonical_completion_policy_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def validate_completion_policy(value: Any) -> CompletionPolicyValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return CompletionPolicyValidationResult(("$: must be an object",))
    _fields(value, "$", _POLICY_FIELDS, errors)
    if value.get("contract_version") != COMPLETION_POLICY_CONTRACT_VERSION:
        errors.append(
            f"$.contract_version: must equal {COMPLETION_POLICY_CONTRACT_VERSION!r}"
        )
    _pattern(value.get("policy_id"), "$.policy_id", _ID, errors)
    if value.get("required_evidence_set_status") != "complete":
        errors.append("$.required_evidence_set_status: must equal 'complete'")
    predicates = value.get("predicates")
    if not isinstance(predicates, list) or not predicates:
        errors.append("$.predicates: must be a non-empty array")
        return CompletionPolicyValidationResult(tuple(errors))
    keys: list[tuple[str, str, str]] = []
    for index, item in enumerate(predicates):
        path = f"$.predicates[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: must be an object")
            continue
        operator = item.get("operator")
        expected_fields = _PREDICATE_BASE | ({"expected"} if operator in {"equals", "gte", "in", "lte"} else set())
        _fields(item, path, expected_fields, errors)
        _pattern(item.get("id"), f"{path}.id", _ID, errors)
        _pattern(item.get("report_kind"), f"{path}.report_kind", _ID, errors)
        _pattern(item.get("json_path"), f"{path}.json_path", _JSON_PATH, errors)
        if operator not in _OPERATORS:
            errors.append(f"{path}.operator: unsupported operator")
        expected = item.get("expected")
        if operator == "in" and (not isinstance(expected, list) or not expected):
            errors.append(f"{path}.expected: in requires a non-empty array")
        if operator in {"gte", "lte"} and (
            not isinstance(expected, (int, float)) or isinstance(expected, bool)
        ):
            errors.append(f"{path}.expected: numeric comparison requires a number")
        if operator == "equals" and isinstance(expected, (dict, list)):
            errors.append(f"{path}.expected: equals requires a scalar or null")
        keys.append(
            (
                str(item.get("id") or ""),
                str(item.get("report_kind") or ""),
                str(item.get("json_path") or ""),
            )
        )
    if keys != sorted(set(keys)):
        errors.append("$.predicates: must be unique and sorted by id, report_kind, json_path")
    return CompletionPolicyValidationResult(tuple(errors))


def _fields(value: Mapping[str, Any], path: str, expected: set[str], errors: list[str]) -> None:
    for field in sorted(expected - set(value)):
        errors.append(f"{path}.{field}: is required")
    for field in sorted(set(value) - expected):
        errors.append(f"{path}.{field}: additional property is not allowed")


def _pattern(value: Any, path: str, pattern: re.Pattern[str], errors: list[str]) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        errors.append(f"{path}: has invalid format")


def _reject_non_finite(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value} is not allowed")
