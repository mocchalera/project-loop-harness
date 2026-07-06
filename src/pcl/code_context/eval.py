from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .diff import _inline_diff_source
from .impact import analyze_impact
from .search import search_code
from ..errors import InvalidInputError
from ..guards import require_initialized
from ..paths import ProjectPaths


RETRIEVAL_EVAL_VERSION = "retrieval-eval/v0"


RETRIEVAL_FIXTURE_VERSION = "retrieval-fixture/v0"


def evaluate_retrieval(paths: ProjectPaths, *, fixture_path: str) -> dict[str, Any]:
    require_initialized(paths)
    fixture = _load_fixture(paths, fixture_path)
    tasks = fixture.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise InvalidInputError(
            "Retrieval fixture must include a non-empty tasks array.",
            details={"fixture_path": fixture_path},
        )

    task_results: list[dict[str, Any]] = []
    true_positive_total = 0
    retrieved_total = 0
    expected_total = 0
    missing_critical_context: list[dict[str, str]] = []

    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise InvalidInputError(
                f"Retrieval fixture task {index} must be an object.",
                details={"fixture_path": fixture_path, "task_index": index},
            )
        task_id = str(task.get("id") or f"task-{index}")
        expected_files = _string_set(task.get("expected_files"))
        expected_tests = _string_set(task.get("expected_tests"))
        expected = expected_files | expected_tests
        critical = _string_set(task.get("critical_context")) or expected
        retrieval = _retrieval_result_for_fixture_task(paths, task)
        retrieved = retrieval["retrieved_paths"]
        true_positives = sorted(retrieved & expected)
        missing = sorted(critical - retrieved)
        for path in missing:
            missing_critical_context.append({"task_id": task_id, "path": path})
        true_positive_total += len(true_positives)
        retrieved_total += len(retrieved)
        expected_total += len(expected)
        task_result = {
            "id": task_id,
            "retrieval_source": retrieval["retrieval_source"],
            "retrieved_paths": sorted(retrieved),
            "expected_files": sorted(expected_files),
            "expected_tests": sorted(expected_tests),
            "true_positives": true_positives,
            "precision": _ratio(len(true_positives), len(retrieved)),
            "recall": _ratio(len(true_positives), len(expected)),
            "missing_critical_context": missing,
            "staleness_warnings": retrieval["staleness_warnings"],
            "staleness_affected_paths": retrieval["staleness_affected_paths"],
        }
        expected_misses = _expected_misses(task.get("expected_misses"))
        if expected_misses:
            task_result["expected_misses"] = expected_misses
        if retrieval.get("sensitive_omitted_count") is not None:
            task_result["sensitive_omitted_count"] = retrieval["sensitive_omitted_count"]
        if retrieval.get("excluded_changed_files"):
            task_result["excluded_changed_files"] = retrieval["excluded_changed_files"]
        if retrieval.get("retrieved_snapshot_consistency"):
            task_result["retrieved_snapshot_consistency"] = retrieval[
                "retrieved_snapshot_consistency"
            ]
        task_results.append(task_result)

    return {
        "ok": True,
        "evaluation": {
            "contract_version": RETRIEVAL_EVAL_VERSION,
            "fixture_path": str(_resolve_fixture_path(paths, fixture_path)),
            "task_count": len(task_results),
            "metrics": {
                "precision": _ratio(true_positive_total, retrieved_total),
                "recall": _ratio(true_positive_total, expected_total),
                "missing_critical_context": missing_critical_context,
            },
            "tasks": task_results,
        },
    }


def _retrieved_paths_for_fixture_task(paths: ProjectPaths, task: dict[str, Any]) -> set[str]:
    return _retrieval_result_for_fixture_task(paths, task)["retrieved_paths"]


def _retrieval_result_for_fixture_task(paths: ProjectPaths, task: dict[str, Any]) -> dict[str, Any]:
    if task.get("diff") is not None:
        impact = analyze_impact(paths, diff_source=_inline_diff_source(str(task["diff"])), write_receipt=False)[
            "impact"
        ]
        changed = {
            str(item["path"])
            for item in impact["changed_files"]
            if item.get("indexed")
        }
        likely = {str(item["path"]) for item in impact["likely_impacted"]}
        return {
            "retrieval_source": "diff",
            "retrieved_paths": changed | likely,
            "staleness_warnings": _string_list(impact.get("staleness_warnings")),
            "staleness_affected_paths": [],
            "sensitive_omitted_count": int(impact.get("sensitive_omitted_count") or 0),
            "excluded_changed_files": _object_list(impact.get("excluded_changed_files")),
        }
    query = str(task.get("query") or "").strip()
    if query:
        search = search_code(paths, query=query, limit=int(task.get("limit") or 50))["search"]
        results = _object_list(search.get("results"))
        staleness_summary = (
            search.get("staleness_warnings")
            if isinstance(search.get("staleness_warnings"), dict)
            else {}
        )
        affected_paths = _string_list(staleness_summary.get("affected_paths"))
        warnings = []
        if affected_paths:
            warnings.append(
                "Search returned paths whose snapshot is not fresh: "
                + ", ".join(affected_paths)
                + "."
            )
        git_head_warning = search.get("git_head_warning")
        if isinstance(git_head_warning, dict) and git_head_warning.get("message"):
            warnings.append(str(git_head_warning["message"]))
        return {
            "retrieval_source": "query",
            "retrieved_paths": {str(item["path"]) for item in results if item.get("path")},
            "staleness_warnings": warnings,
            "staleness_affected_paths": affected_paths,
            "sensitive_omitted_count": None,
            "retrieved_snapshot_consistency": {
                str(item["path"]): str(item["snapshot_consistency"])
                for item in results
                if item.get("path") and item.get("snapshot_consistency")
            },
        }
    raise InvalidInputError(
        "Retrieval fixture task must include diff or query.",
        details={"task": task.get("id")},
    )


def _load_fixture(paths: ProjectPaths, fixture_path: str) -> dict[str, Any]:
    path = _resolve_fixture_path(paths, fixture_path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InvalidInputError(
            f"Could not open retrieval fixture: {path}",
            details={"fixture_path": str(path)},
        ) from exc
    except JSONDecodeError as exc:
        raise InvalidInputError(
            f"Retrieval fixture must be valid JSON: {exc.msg}.",
            details={"fixture_path": str(path), "position": exc.pos},
        ) from exc
    if not isinstance(value, dict):
        raise InvalidInputError(
            "Retrieval fixture must be a JSON object.",
            details={"fixture_path": str(path)},
        )
    contract = value.get("contract_version")
    if contract not in {None, RETRIEVAL_FIXTURE_VERSION}:
        raise InvalidInputError(
            f"Unsupported retrieval fixture contract_version: {contract}",
            details={"expected": RETRIEVAL_FIXTURE_VERSION, "actual": contract},
        )
    return value


def _resolve_fixture_path(paths: ProjectPaths, fixture_path: str) -> Path:
    path = Path(fixture_path)
    if path.is_absolute():
        return path
    root_relative = paths.root / path
    if root_relative.exists():
        return root_relative
    return Path.cwd() / path


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str) and item.strip()}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _expected_misses(value: Any) -> list[dict[str, str]]:
    expected: list[dict[str, str]] = []
    for item in _object_list(value):
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        entry = {"path": path}
        reason = str(item.get("reason") or "").strip()
        if reason:
            entry["reason"] = reason
        expected.append(entry)
    return expected


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0 if numerator == 0 else 0.0
    return round(numerator / denominator, 4)
