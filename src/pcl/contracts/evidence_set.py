from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any


EVIDENCE_SET_CONTRACT_VERSION = "evidence-set/v1"
REPORT_MANIFEST_CONTRACT_VERSION = "evidence-report-manifest/v1"
SCHEMA_RESOURCE = "schemas/evidence-set-v1.schema.json"

_FIELDS = {
    "contract_version",
    "target",
    "work_root",
    "report_manifest",
    "required_report_kinds",
    "included_reports",
    "excluded_reports",
    "completeness",
}
_TARGETS = {
    "goal": re.compile(r"^G-[0-9]{4,}$"),
    "task": re.compile(r"^T-[0-9]{4,}$"),
    "feature": re.compile(r"^F-[0-9]{4,}$"),
    "story": re.compile(r"^US-[0-9]{4,}$"),
    "defect": re.compile(r"^D-[0-9]{4,}$"),
    "workflow_run": re.compile(r"^WR-[0-9]{4,}$"),
    "test_case": re.compile(r"^TC-[0-9]{4,}$"),
}
_EVIDENCE_ID = re.compile(r"^E-[0-9]{4,}$")
_KIND = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_ROLE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_STATUSES = {"pass", "fail", "warning", "unknown"}
_FINDING_CODES = {
    "required_report_excluded",
    "required_report_missing",
    "required_report_not_passing",
}


@dataclass(frozen=True)
class EvidenceSetValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": EVIDENCE_SET_CONTRACT_VERSION,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def evidence_set_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def load_evidence_set(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_non_finite)


def canonical_evidence_set_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def serialized_evidence_set(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def validate_evidence_set(value: Any) -> EvidenceSetValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return EvidenceSetValidationResult(("$: must be an object",))
    _fields(value, "$", _FIELDS, errors)
    if value.get("contract_version") != EVIDENCE_SET_CONTRACT_VERSION:
        errors.append(
            f"$.contract_version: must equal {EVIDENCE_SET_CONTRACT_VERSION!r}"
        )
    _target(value.get("target"), errors)
    _relative_path(value.get("work_root"), "$.work_root", errors)
    _manifest(value.get("report_manifest"), errors)
    required = _kind_array(value.get("required_report_kinds"), "$.required_report_kinds", errors)
    included = _reports(value.get("included_reports"), "$.included_reports", errors, included=True)
    excluded = _reports(value.get("excluded_reports"), "$.excluded_reports", errors, included=False)
    included_kinds = {item["kind"] for item in included if isinstance(item.get("kind"), str)}
    excluded_kinds = {item["kind"] for item in excluded if isinstance(item.get("kind"), str)}
    overlap = sorted(included_kinds & excluded_kinds)
    if overlap:
        errors.append(f"$: report kinds cannot be both included and excluded: {', '.join(overlap)}")
    _completeness(value.get("completeness"), required, included, excluded, errors)
    return EvidenceSetValidationResult(tuple(errors))


def _target(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("$.target: must be an object")
        return
    _fields(value, "$.target", {"type", "id"}, errors)
    target_type = value.get("type")
    if target_type not in _TARGETS:
        errors.append("$.target.type: unsupported target type")
    _pattern(value.get("id"), "$.target.id", _TARGETS.get(target_type), errors)


def _manifest(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("$.report_manifest: must be an object")
        return
    _fields(value, "$.report_manifest", {"path", "sha256"}, errors)
    _relative_path(value.get("path"), "$.report_manifest.path", errors)
    _pattern(value.get("sha256"), "$.report_manifest.sha256", _SHA256, errors)


def _kind_array(value: Any, path: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return []
    kinds: list[str] = []
    for index, item in enumerate(value):
        _pattern(item, f"{path}[{index}]", _KIND, errors)
        if isinstance(item, str):
            kinds.append(item)
    if kinds != sorted(set(kinds)):
        errors.append(f"{path}: must be unique and sorted")
    return kinds


def _reports(
    value: Any,
    path: str,
    errors: list[str],
    *,
    included: bool,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return []
    result: list[dict[str, Any]] = []
    expected_fields = (
        {"kind", "path", "status", "sha256", "size_bytes", "evidence_id", "role"}
        if included
        else {"kind", "path", "status", "sha256", "size_bytes", "required", "reason"}
    )
    keys: list[tuple[str, str]] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_path}: must be an object")
            continue
        _fields(item, item_path, expected_fields, errors)
        _pattern(item.get("kind"), f"{item_path}.kind", _KIND, errors)
        _relative_path(item.get("path"), f"{item_path}.path", errors)
        if item.get("status") not in _STATUSES:
            errors.append(f"{item_path}.status: must be one of fail, pass, unknown, warning")
        _pattern(item.get("sha256"), f"{item_path}.sha256", _SHA256, errors)
        size = item.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            errors.append(f"{item_path}.size_bytes: must be a non-negative integer")
        if included:
            _pattern(item.get("evidence_id"), f"{item_path}.evidence_id", _EVIDENCE_ID, errors)
            _pattern(item.get("role"), f"{item_path}.role", _ROLE, errors)
            key = (str(item.get("kind") or ""), str(item.get("role") or ""))
        else:
            if not isinstance(item.get("required"), bool):
                errors.append(f"{item_path}.required: must be a boolean")
            if item.get("reason") != "not_selected":
                errors.append(f"{item_path}.reason: must equal 'not_selected'")
            key = (str(item.get("kind") or ""), "")
        keys.append(key)
        result.append(item)
    if keys != sorted(set(keys)):
        errors.append(f"{path}: must have unique, sorted kind/role entries")
    return result


def _completeness(
    value: Any,
    required: list[str],
    included: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append("$.completeness: must be an object")
        return
    _fields(value, "$.completeness", {"status", "findings"}, errors)
    status = value.get("status")
    if status not in {"complete", "incomplete"}:
        errors.append("$.completeness.status: must be complete or incomplete")
    findings = value.get("findings")
    if not isinstance(findings, list):
        errors.append("$.completeness.findings: must be an array")
        return
    keys: list[tuple[str, str, str]] = []
    for index, item in enumerate(findings):
        path = f"$.completeness.findings[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: must be an object")
            continue
        _fields(item, path, {"code", "kind", "path", "severity"}, errors)
        if item.get("code") not in _FINDING_CODES:
            errors.append(f"{path}.code: unsupported finding code")
        _pattern(item.get("kind"), f"{path}.kind", _KIND, errors)
        report_path = item.get("path")
        if report_path is not None:
            _relative_path(report_path, f"{path}.path", errors)
        if item.get("severity") != "error":
            errors.append(f"{path}.severity: must equal 'error'")
        keys.append((str(item.get("code") or ""), str(item.get("kind") or ""), str(report_path or "")))
    if keys != sorted(set(keys)):
        errors.append("$.completeness.findings: must be unique and sorted")
    if status == "complete" and findings:
        errors.append("$.completeness: complete status requires no findings")
    if status == "incomplete" and not findings:
        errors.append("$.completeness: incomplete status requires findings")
    included_by_kind = {
        str(item.get("kind")): item
        for item in included
        if isinstance(item.get("kind"), str)
    }
    excluded_by_kind = {
        str(item.get("kind")): item
        for item in excluded
        if isinstance(item.get("kind"), str)
    }
    expected_findings: list[dict[str, Any]] = []
    for kind in required:
        if kind in included_by_kind:
            report = included_by_kind[kind]
            if report.get("status") == "pass":
                continue
            code = "required_report_not_passing"
            report_path = report.get("path")
        elif kind in excluded_by_kind:
            code = "required_report_excluded"
            report_path = excluded_by_kind[kind].get("path")
        else:
            code = "required_report_missing"
            report_path = None
        expected_findings.append(
            {"code": code, "kind": kind, "path": report_path, "severity": "error"}
        )
    expected_findings.sort(
        key=lambda item: (item["code"], item["kind"], str(item["path"] or ""))
    )
    if findings != expected_findings:
        errors.append("$.completeness.findings: must exactly match required report state")
    expected_status = "complete" if not expected_findings else "incomplete"
    if status in {"complete", "incomplete"} and status != expected_status:
        errors.append(f"$.completeness.status: must equal {expected_status!r} for these findings")


def _fields(value: Mapping[str, Any], path: str, expected: set[str], errors: list[str]) -> None:
    for field in sorted(expected - set(value)):
        errors.append(f"{path}.{field}: is required")
    for field in sorted(set(value) - expected):
        errors.append(f"{path}.{field}: additional property is not allowed")


def _relative_path(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: must be a non-empty relative POSIX path")
        return
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != value:
        errors.append(f"{path}: must be a normalized relative POSIX path without '..'")


def _pattern(
    value: Any,
    path: str,
    pattern: re.Pattern[str] | None,
    errors: list[str],
) -> None:
    if not isinstance(value, str) or pattern is None or pattern.fullmatch(value) is None:
        errors.append(f"{path}: has invalid format")


def _reject_non_finite(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value} is not allowed")
