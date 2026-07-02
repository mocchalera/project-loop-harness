from __future__ import annotations

from typing import Any


RUBRIC_V1_CONTRACT_VERSION = "rubric/v1"

_TOP_LEVEL_KEYS = {
    "contract_version",
    "acceptance_criteria",
    "regression_risk",
    "test_evidence",
    "security_ux_checks",
    "confidence_score",
    "evidence_completeness",
}

_MET_VALUES = {"yes", "no", "unknown"}
_RISK_LEVELS = {"low", "medium", "high"}
_SECURITY_UX_RESULTS = {"pass", "fail", "n/a"}
_EVIDENCE_COMPLETENESS_VALUES = {"complete", "partial", "missing"}


def claims_rubric_v1(obj: object) -> bool:
    return isinstance(obj, dict) and obj.get("contract_version") == RUBRIC_V1_CONTRACT_VERSION


def rubric_contract_version(obj: object) -> str | None:
    return RUBRIC_V1_CONTRACT_VERSION if claims_rubric_v1(obj) else None


def validate_rubric(obj: object) -> list[str]:
    problems: list[str] = []
    if not isinstance(obj, dict):
        return ["rubric must be a JSON object."]

    for key in sorted(set(obj) - _TOP_LEVEL_KEYS):
        problems.append(f"unknown top-level key: {key}.")

    _validate_contract_version(obj, problems)
    _validate_acceptance_criteria(obj, problems)
    _validate_regression_risk(obj, problems)
    _validate_test_evidence(obj, problems)
    _validate_security_ux_checks(obj, problems)
    _validate_confidence_score(obj, problems)
    _validate_evidence_completeness(obj, problems)
    return problems


def evidence_ids_in_rubric(obj: object) -> list[str]:
    if not isinstance(obj, dict):
        return []
    evidence_ids: list[str] = []
    for section_name in ("acceptance_criteria", "test_evidence"):
        section = obj.get(section_name)
        if not isinstance(section, list):
            continue
        for item in section:
            if not isinstance(item, dict):
                continue
            evidence_id = item.get("evidence_id")
            if isinstance(evidence_id, str) and evidence_id.strip():
                evidence_ids.append(evidence_id.strip())
    seen: set[str] = set()
    unique: list[str] = []
    for evidence_id in evidence_ids:
        if evidence_id not in seen:
            seen.add(evidence_id)
            unique.append(evidence_id)
    return unique


def _validate_contract_version(obj: dict[str, Any], problems: list[str]) -> None:
    if "contract_version" not in obj:
        problems.append("contract_version is required.")
        return
    if obj["contract_version"] != RUBRIC_V1_CONTRACT_VERSION:
        problems.append("contract_version must be 'rubric/v1'.")


def _validate_acceptance_criteria(obj: dict[str, Any], problems: list[str]) -> None:
    value = obj.get("acceptance_criteria")
    if "acceptance_criteria" not in obj:
        problems.append("acceptance_criteria is required.")
        return
    if not isinstance(value, list):
        problems.append("acceptance_criteria must be a list.")
        return
    if not value:
        problems.append("acceptance_criteria must contain at least one item.")
        return
    for index, item in enumerate(value):
        path = f"acceptance_criteria[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{path} must be an object.")
            continue
        _validate_required_non_empty_string(item, "criterion", path, problems)
        _validate_enum(item, "met", path, _MET_VALUES, problems)
        _validate_nullable_evidence_id(item, "evidence_id", path, problems)


def _validate_regression_risk(obj: dict[str, Any], problems: list[str]) -> None:
    value = obj.get("regression_risk")
    if "regression_risk" not in obj:
        problems.append("regression_risk is required.")
        return
    if not isinstance(value, dict):
        problems.append("regression_risk must be an object.")
        return
    _validate_enum(value, "level", "regression_risk", _RISK_LEVELS, problems)
    _validate_nullable_string(value, "notes", "regression_risk", problems)


def _validate_test_evidence(obj: dict[str, Any], problems: list[str]) -> None:
    value = obj.get("test_evidence")
    if "test_evidence" not in obj:
        problems.append("test_evidence is required.")
        return
    if not isinstance(value, list):
        problems.append("test_evidence must be a list.")
        return
    for index, item in enumerate(value):
        path = f"test_evidence[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{path} must be an object.")
            continue
        _validate_nullable_evidence_id(item, "evidence_id", path, problems)
        _validate_nullable_string(item, "command", path, problems)
        _validate_nullable_string(item, "summary", path, problems)


def _validate_security_ux_checks(obj: dict[str, Any], problems: list[str]) -> None:
    value = obj.get("security_ux_checks")
    if "security_ux_checks" not in obj:
        problems.append("security_ux_checks is required.")
        return
    if not isinstance(value, list):
        problems.append("security_ux_checks must be a list.")
        return
    for index, item in enumerate(value):
        path = f"security_ux_checks[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{path} must be an object.")
            continue
        _validate_required_non_empty_string(item, "check", path, problems)
        _validate_enum(item, "result", path, _SECURITY_UX_RESULTS, problems)
        _validate_nullable_string(item, "notes", path, problems)


def _validate_confidence_score(obj: dict[str, Any], problems: list[str]) -> None:
    if "confidence_score" not in obj:
        problems.append("confidence_score is required.")
        return
    value = obj["confidence_score"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append("confidence_score must be a number between 0.0 and 1.0.")
        return
    if not 0.0 <= float(value) <= 1.0:
        problems.append("confidence_score must be between 0.0 and 1.0 inclusive.")


def _validate_evidence_completeness(obj: dict[str, Any], problems: list[str]) -> None:
    _validate_enum(obj, "evidence_completeness", "", _EVIDENCE_COMPLETENESS_VALUES, problems)


def _validate_required_non_empty_string(
    item: dict[str, Any],
    key: str,
    path: str,
    problems: list[str],
) -> None:
    if key not in item:
        problems.append(f"{_field_path(path, key)} is required.")
        return
    value = item[key]
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{_field_path(path, key)} must be a non-empty string.")


def _validate_nullable_string(
    item: dict[str, Any],
    key: str,
    path: str,
    problems: list[str],
) -> None:
    if key not in item:
        problems.append(f"{_field_path(path, key)} is required.")
        return
    value = item[key]
    if value is not None and not isinstance(value, str):
        problems.append(f"{_field_path(path, key)} must be a string or null.")


def _validate_nullable_evidence_id(
    item: dict[str, Any],
    key: str,
    path: str,
    problems: list[str],
) -> None:
    if key not in item:
        problems.append(f"{_field_path(path, key)} is required.")
        return
    value = item[key]
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{_field_path(path, key)} must be a non-empty string or null.")


def _validate_enum(
    item: dict[str, Any],
    key: str,
    path: str,
    allowed: set[str],
    problems: list[str],
) -> None:
    if key not in item:
        problems.append(f"{_field_path(path, key)} is required.")
        return
    value = item[key]
    if not isinstance(value, str) or value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        problems.append(f"{_field_path(path, key)} must be one of: {allowed_values}.")


def _field_path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key
