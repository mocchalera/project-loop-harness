from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from .contracts.completion_policy import (
    COMPLETION_EVALUATION_CONTRACT_VERSION,
    canonical_completion_policy_json,
    load_completion_policy,
    validate_completion_policy,
)
from .db import connect
from .errors import InvalidInputError, PclError
from .evidence import EvidenceAddError
from .evidence_sets import inspect_evidence_set
from .guards import require_initialized
from .paths import ProjectPaths


class CompletionPolicyError(PclError):
    pass


def evaluate_completion_policy(
    paths: ProjectPaths,
    *,
    policy_file: str,
    evidence_set_id: str,
    test_case_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    policy = _load_policy(policy_file)
    own_connection = conn is None
    active_conn = connect(paths.db_path) if conn is None else conn
    try:
        evidence_set = inspect_evidence_set(active_conn, paths, evidence_set_id)
    finally:
        if own_connection:
            active_conn.close()
    if evidence_set["health"] != "ok" or evidence_set["artifact"] is None:
        raise _error(
            "completion_evidence_set_unhealthy",
            f"Evidence set {evidence_set_id} is not healthy enough for completion evaluation.",
            evidence_set_id=evidence_set_id,
            findings=evidence_set["findings"],
        )
    artifact = evidence_set["artifact"]
    if test_case_id is not None and artifact["target"] != {
        "type": "test_case",
        "id": test_case_id,
    }:
        raise _error(
            "completion_evidence_set_target_mismatch",
            f"Evidence set {evidence_set_id} does not target test_case:{test_case_id}.",
            evidence_set_id=evidence_set_id,
            expected={"type": "test_case", "id": test_case_id},
            actual=artifact["target"],
        )
    results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    if artifact["completeness"]["status"] != policy["required_evidence_set_status"]:
        findings.append(
            {
                "code": "evidence_set_incomplete",
                "evidence_set_status": artifact["completeness"]["status"],
                "required_status": policy["required_evidence_set_status"],
            }
        )
    reports = {item["kind"]: item for item in artifact["included_reports"]}
    report_cache: dict[str, tuple[bool, Any, str | None]] = {}
    for predicate in policy["predicates"]:
        report_kind = predicate["report_kind"]
        report = reports.get(report_kind)
        base = {
            "id": predicate["id"],
            "report_kind": report_kind,
            "json_path": predicate["json_path"],
            "operator": predicate["operator"],
        }
        if "expected" in predicate:
            base["expected"] = predicate["expected"]
        if report is None:
            result = {**base, "actual": None, "found": False, "passed": False}
            results.append(result)
            findings.append(
                {"code": "predicate_report_missing", "predicate_id": predicate["id"], "report_kind": report_kind}
            )
            continue
        if report_kind not in report_cache:
            report_cache[report_kind] = _load_bound_report(paths, artifact, report)
        report_ok, document, report_error = report_cache[report_kind]
        if not report_ok:
            result = {**base, "actual": None, "found": False, "passed": False}
            results.append(result)
            findings.append(
                {
                    "code": str(report_error),
                    "predicate_id": predicate["id"],
                    "report_kind": report_kind,
                }
            )
            continue
        found, actual = _resolve_json_path(document, predicate["json_path"])
        passed = _apply_operator(
            predicate["operator"],
            found=found,
            actual=actual,
            expected=predicate.get("expected"),
        )
        results.append({**base, "actual": actual if found else None, "found": found, "passed": passed})
        if not passed:
            findings.append(
                {
                    "code": "predicate_failed",
                    "predicate_id": predicate["id"],
                    "report_kind": report_kind,
                }
            )
    results.sort(key=lambda item: (item["id"], item["report_kind"], item["json_path"]))
    findings.sort(
        key=lambda item: (
            item["code"],
            str(item.get("predicate_id") or ""),
            str(item.get("report_kind") or ""),
        )
    )
    policy_sha256 = "sha256:" + hashlib.sha256(
        canonical_completion_policy_json(policy).encode("utf-8")
    ).hexdigest()
    evaluation = {
        "contract_version": COMPLETION_EVALUATION_CONTRACT_VERSION,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy_sha256,
        "evidence_set_id": evidence_set_id,
        "evidence_set_sha256": evidence_set["artifact_sha256"],
        "target": artifact["target"],
        "status": "passed" if not findings else "failed",
        "predicate_results": results,
        "findings": findings,
    }
    return {"ok": not findings, "changed": False, "evaluation": evaluation}


def require_completion_policy(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    policy_file: str,
    evidence_set_id: str,
    test_case_id: str,
) -> dict[str, Any]:
    result = evaluate_completion_policy(
        paths,
        policy_file=policy_file,
        evidence_set_id=evidence_set_id,
        test_case_id=test_case_id,
        conn=conn,
    )
    if not result["ok"]:
        raise EvidenceAddError(
            f"Completion policy rejected Evidence set {evidence_set_id} for Test {test_case_id}.",
            code="completion_policy_failed",
            details={"evaluation": result["evaluation"]},
        )
    return result["evaluation"]


def _load_policy(path_value: str) -> dict[str, Any]:
    try:
        value = load_completion_policy(path_value)
    except OSError as exc:
        raise InvalidInputError(
            f"Could not read completion policy: {path_value}",
            details={"path": path_value, "reason": str(exc)},
        ) from exc
    except json.JSONDecodeError as exc:
        raise _error(
            "completion_policy_invalid_json",
            f"Completion policy is not valid JSON: {path_value}",
            path=path_value,
            line=exc.lineno,
            column=exc.colno,
        ) from exc
    except ValueError as exc:
        raise _error(
            "completion_policy_invalid_json",
            f"Completion policy contains an invalid JSON value: {path_value}",
            path=path_value,
            reason=str(exc),
        ) from exc
    validation = validate_completion_policy(value)
    if not validation.ok:
        raise _error(
            "completion_policy_contract_invalid",
            f"Completion policy contract validation failed: {path_value}",
            path=path_value,
            errors=list(validation.errors),
        )
    return value


def _load_bound_report(
    paths: ProjectPaths,
    artifact: dict[str, Any],
    report: dict[str, Any],
) -> tuple[bool, Any, str | None]:
    project_root = paths.root.resolve()
    work_root = (project_root / artifact["work_root"]).resolve()
    try:
        work_root.relative_to(project_root)
    except ValueError:
        return False, None, "report_path_escape"
    report_path = (work_root / report["path"]).resolve()
    try:
        report_path.relative_to(work_root)
    except ValueError:
        return False, None, "report_path_escape"
    if not report_path.is_file():
        return False, None, "report_missing"
    try:
        content = report_path.read_bytes()
    except OSError:
        return False, None, "report_unreadable"
    actual_sha256 = "sha256:" + hashlib.sha256(content).hexdigest()
    if actual_sha256 != report["sha256"]:
        return False, None, "report_hash_mismatch"
    try:
        document = json.loads(
            content.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number {value} is not allowed")
            ),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return False, None, "report_invalid_json"
    return True, document, None


def _resolve_json_path(document: Any, path: str) -> tuple[bool, Any]:
    if path == "$":
        return True, document
    current = document
    for part in path[2:].split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _apply_operator(operator: str, *, found: bool, actual: Any, expected: Any) -> bool:
    if operator == "exists":
        return found
    if not found:
        return False
    if operator == "empty":
        return actual is None or (isinstance(actual, (str, list, dict)) and len(actual) == 0)
    if operator == "equals":
        return actual == expected and type(actual) is type(expected)
    if operator == "in":
        return any(actual == item and type(actual) is type(item) for item in expected)
    if operator in {"gte", "lte"}:
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False
        return actual >= expected if operator == "gte" else actual <= expected
    return False


def _error(code: str, message: str, **details: Any) -> CompletionPolicyError:
    return CompletionPolicyError(message=message, code=code, details=details)
