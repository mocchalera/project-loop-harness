from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
from importlib.resources import files
import json
import math
from pathlib import Path
import re
from typing import Any


EXECUTION_BINDING_CONTRACT_VERSION = "execution-binding/v1"
PROGRESS_RECEIPT_CONTRACT_VERSION = "progress-receipt/v1"
SCHEMA_RESOURCE = "schemas/progress-receipt-v1.schema.json"

_RECEIPT_ID = re.compile(r"^pr-sha256:[0-9a-f]{64}$")
_EVIDENCE_ID = re.compile(r"^E-[0-9]{4,}$")
_TARGETS = {
    "goal": re.compile(r"^G-[0-9]{4,}$"),
    "task": re.compile(r"^T-[0-9]{4,}$"),
}
_STATUSES = {"started", "completed", "blocked"}
_RELATIONSHIPS = {"same_worktree", "linked_worktree", "non_git"}


@dataclass(frozen=True)
class ProgressReceiptValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": PROGRESS_RECEIPT_CONTRACT_VERSION,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def progress_receipt_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def load_progress_receipt(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_non_finite_json_number)


def canonical_progress_receipt_json(receipt: Mapping[str, Any]) -> str:
    return json.dumps(
        receipt,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def compute_progress_receipt_id(receipt: Mapping[str, Any]) -> str:
    content = dict(receipt)
    content.pop("receipt_id", None)
    digest = hashlib.sha256(
        canonical_progress_receipt_json(content).encode("utf-8")
    ).hexdigest()
    return f"pr-sha256:{digest}"


def finalize_progress_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(receipt))
    result["receipt_id"] = compute_progress_receipt_id(result)
    return result


def serialized_progress_receipt(receipt: Mapping[str, Any]) -> str:
    return (
        json.dumps(
            receipt,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def validate_progress_receipt(value: Any) -> ProgressReceiptValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ProgressReceiptValidationResult(("$: must be an object",))
    _non_finite(value, "$", errors)
    fields = {
        "contract_version",
        "receipt_id",
        "producer",
        "generated_at",
        "target",
        "milestone",
        "status",
        "execution_binding",
        "latest_valid_evidence",
        "residual_blockers",
    }
    _fields(value, "$", fields, fields, errors)
    _equal(
        value.get("contract_version"),
        PROGRESS_RECEIPT_CONTRACT_VERSION,
        "$.contract_version",
        errors,
    )
    _string(value.get("receipt_id"), "$.receipt_id", errors, pattern=_RECEIPT_ID)
    _producer(value.get("producer"), errors)
    _timestamp(value.get("generated_at"), "$.generated_at", errors)
    _target(value.get("target"), errors)
    _string(value.get("milestone"), "$.milestone", errors)
    status = value.get("status")
    if status not in _STATUSES:
        errors.append("$.status: must be one of blocked, completed, started")
    _execution_binding(value.get("execution_binding"), errors)
    _latest_evidence(value.get("latest_valid_evidence"), errors)
    blockers = value.get("residual_blockers")
    _string_array(blockers, "$.residual_blockers", errors)
    if isinstance(blockers, list) and len(set(blockers)) != len(blockers):
        errors.append("$.residual_blockers: items must be unique")
    if status == "blocked" and isinstance(blockers, list) and not blockers:
        errors.append("$.residual_blockers: blocked progress requires a blocker")

    receipt_id = value.get("receipt_id")
    if (
        isinstance(receipt_id, str)
        and _RECEIPT_ID.fullmatch(receipt_id)
        and not _has_non_finite(value)
        and receipt_id != compute_progress_receipt_id(value)
    ):
        errors.append("$.receipt_id: does not match canonical receipt content")
    return ProgressReceiptValidationResult(tuple(errors))


def _producer(value: Any, errors: list[str]) -> None:
    path = "$.producer"
    if not _object(value, path, errors):
        return
    _fields(value, path, {"name", "version"}, {"name", "version"}, errors)
    _equal(value.get("name"), "project-loop-harness", f"{path}.name", errors)
    _string(value.get("version"), f"{path}.version", errors)


def _target(value: Any, errors: list[str]) -> None:
    path = "$.target"
    if not _object(value, path, errors):
        return
    _fields(value, path, {"type", "id"}, {"type", "id"}, errors)
    target_type = value.get("type")
    if target_type not in _TARGETS:
        errors.append(f"{path}.type: must be one of goal, task")
    _string(
        value.get("id"),
        f"{path}.id",
        errors,
        pattern=_TARGETS.get(target_type),
    )


def _execution_binding(value: Any, errors: list[str]) -> None:
    path = "$.execution_binding"
    if not _object(value, path, errors):
        return
    fields = {
        "contract_version",
        "canonical_root",
        "execution_root",
        "git",
        "cockpit",
        "ci",
    }
    _fields(value, path, fields, fields, errors)
    _equal(
        value.get("contract_version"),
        EXECUTION_BINDING_CONTRACT_VERSION,
        f"{path}.contract_version",
        errors,
    )
    _absolute_path(value.get("canonical_root"), f"{path}.canonical_root", errors)
    _absolute_path(value.get("execution_root"), f"{path}.execution_root", errors)
    _git(value.get("git"), errors=errors)
    _cockpit(value.get("cockpit"), errors)
    _ci(value.get("ci"), errors)


def _git(value: Any, *, errors: list[str]) -> None:
    path = "$.execution_binding.git"
    if not _object(value, path, errors):
        return
    fields = {
        "available",
        "worktree_root",
        "common_dir",
        "head_revision",
        "branch",
        "detached",
        "relationship",
    }
    _fields(value, path, fields, fields, errors)
    available = value.get("available")
    if not isinstance(available, bool):
        errors.append(f"{path}.available: must be a boolean")
    relationship = value.get("relationship")
    if relationship not in _RELATIONSHIPS:
        errors.append(
            f"{path}.relationship: must be one of linked_worktree, non_git, same_worktree"
        )
    for field in ("worktree_root", "common_dir"):
        _optional_absolute_path(value.get(field), f"{path}.{field}", errors)
    _optional_string(value.get("head_revision"), f"{path}.head_revision", errors)
    _optional_string(value.get("branch"), f"{path}.branch", errors)
    detached = value.get("detached")
    if detached is not None and not isinstance(detached, bool):
        errors.append(f"{path}.detached: must be a boolean or null")
    if available is False:
        for field in (
            "worktree_root",
            "common_dir",
            "head_revision",
            "branch",
            "detached",
        ):
            if value.get(field) is not None:
                errors.append(f"{path}.{field}: must be null when Git is unavailable")
        if relationship != "non_git":
            errors.append(f"{path}.relationship: unavailable Git requires non_git")
    elif available is True:
        for field in ("worktree_root", "common_dir", "head_revision"):
            if not isinstance(value.get(field), str) or not value[field]:
                errors.append(f"{path}.{field}: available Git requires a string")
        if not isinstance(detached, bool):
            errors.append(f"{path}.detached: available Git requires a boolean")
        if detached is True and value.get("branch") is not None:
            errors.append(f"{path}.branch: detached Git requires null")
        if detached is False and not isinstance(value.get("branch"), str):
            errors.append(f"{path}.branch: attached Git requires a string")
        if relationship == "non_git":
            errors.append(f"{path}.relationship: available Git cannot be non_git")


def _cockpit(value: Any, errors: list[str]) -> None:
    path = "$.execution_binding.cockpit"
    if value is None:
        return
    if not _object(value, path, errors):
        return
    fields = {"task_id", "report_sequence", "report_ref"}
    _fields(value, path, fields, fields, errors)
    _string(value.get("task_id"), f"{path}.task_id", errors)
    sequence = value.get("report_sequence")
    if sequence is not None and (
        type(sequence) is not int or sequence < 0
    ):
        errors.append(f"{path}.report_sequence: must be a non-negative integer or null")
    _optional_string(value.get("report_ref"), f"{path}.report_ref", errors)


def _ci(value: Any, errors: list[str]) -> None:
    path = "$.execution_binding.ci"
    if value is None:
        return
    if not _object(value, path, errors):
        return
    fields = {"provider", "run_id", "run_url"}
    _fields(value, path, fields, fields, errors)
    _string(value.get("provider"), f"{path}.provider", errors)
    _string(value.get("run_id"), f"{path}.run_id", errors)
    _optional_string(value.get("run_url"), f"{path}.run_url", errors)


def _latest_evidence(value: Any, errors: list[str]) -> None:
    path = "$.latest_valid_evidence"
    if value is None:
        return
    if not _object(value, path, errors):
        return
    fields = {"evidence_id", "type", "created_at", "link_role"}
    _fields(value, path, fields, fields, errors)
    _string(value.get("evidence_id"), f"{path}.evidence_id", errors, pattern=_EVIDENCE_ID)
    _string(value.get("type"), f"{path}.type", errors)
    _timestamp(value.get("created_at"), f"{path}.created_at", errors)
    _string(value.get("link_role"), f"{path}.link_role", errors)


def _fields(
    value: dict[str, Any],
    path: str,
    required: set[str],
    allowed: set[str],
    errors: list[str],
) -> None:
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    for field in missing:
        errors.append(f"{path}.{field}: is required")
    for field in extra:
        errors.append(f"{path}.{field}: additional property is not allowed")


def _object(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
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
    elif pattern is not None and pattern.fullmatch(value) is None:
        errors.append(f"{path}: has invalid format")


def _optional_string(value: Any, path: str, errors: list[str]) -> None:
    if value is not None:
        _string(value, path, errors)


def _absolute_path(value: Any, path: str, errors: list[str]) -> None:
    _string(value, path, errors)
    if isinstance(value, str) and value and not Path(value).is_absolute():
        errors.append(f"{path}: must be an absolute path")


def _optional_absolute_path(value: Any, path: str, errors: list[str]) -> None:
    if value is not None:
        _absolute_path(value, path, errors)


def _string_array(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return
    for index, item in enumerate(value):
        _string(item, f"{path}[{index}]", errors)


def _timestamp(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: must be a non-empty timestamp")
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path}: must be a valid ISO-8601 timestamp")
        return
    if parsed.tzinfo is None:
        errors.append(f"{path}: timestamp must include an offset")


def _equal(value: Any, expected: Any, path: str, errors: list[str]) -> None:
    if value != expected:
        errors.append(f"{path}: must equal {expected!r}")


def _non_finite(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path}: non-finite numbers are not allowed")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _non_finite(item, f"{path}[{index}]", errors)
    elif isinstance(value, dict):
        for key, item in value.items():
            _non_finite(item, f"{path}.{key}", errors)


def _has_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, list):
        return any(_has_non_finite(item) for item in value)
    if isinstance(value, dict):
        return any(_has_non_finite(item) for item in value.values())
    return False


def _reject_non_finite_json_number(value: str) -> Any:
    raise ValueError(f"Non-finite JSON number is not allowed: {value}")
