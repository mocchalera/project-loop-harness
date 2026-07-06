from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from .receipts import (
    CONTEXT_RECEIPT_EVIDENCE_TYPE,
    CONTEXT_RECEIPT_VERSION,
    resolve_context_receipt_path,
)
from .diff import _inline_diff_source
from .impact import analyze_impact
from .search import search_code
from ..db import connect
from ..errors import EXIT_USAGE, DataStoreError, InvalidInputError, PclError
from ..guards import require_initialized
from ..paths import ProjectPaths
from ..timeutil import utc_now_iso


RETRIEVAL_EVAL_VERSION = "retrieval-eval/v0"


RETRIEVAL_FIXTURE_VERSION = "retrieval-fixture/v0"


class RetrievalFixtureError(PclError):
    def __init__(self, message: str, *, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code=code,
            exit_code=EXIT_USAGE,
            details=details or {},
        )


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


def propose_retrieval_fixture(
    paths: ProjectPaths,
    *,
    receipt_evidence_id: str,
    force: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    evidence_id = receipt_evidence_id.strip()
    row = _load_receipt_evidence_row(paths, evidence_id)
    receipt = _load_context_receipt_payload(paths, row)
    output_path = _proposed_fixture_path(paths, evidence_id)
    relative_output_path = _relative_to_root(paths, output_path)
    if output_path.exists() and not force:
        raise RetrievalFixtureError(
            f"Proposed retrieval fixture already exists: {relative_output_path}. "
            "Use --force to overwrite it after confirming no human labels will be lost.",
            code="eval_fixture_candidate_exists",
            details={
                "receipt_evidence_id": evidence_id,
                "output_path": relative_output_path,
            },
        )

    candidate = _candidate_fixture_from_receipt(evidence_id=evidence_id, receipt=receipt)
    serialized = json.dumps(candidate, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(serialized, encoding="utf-8")
        tmp_path.replace(output_path)
        _append_jsonl_only_event(
            paths,
            event_type="eval_fixture_proposed",
            entity_type="retrieval_fixture",
            entity_id=relative_output_path,
            payload={
                "receipt_evidence_id": evidence_id,
                "output_path": relative_output_path,
            },
        )
    except OSError as exc:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise DataStoreError(
            f"Could not write proposed retrieval fixture: {exc}",
            details={
                "receipt_evidence_id": evidence_id,
                "output_path": relative_output_path,
            },
        ) from exc

    return {
        "ok": True,
        "fixture": {
            "contract_version": RETRIEVAL_FIXTURE_VERSION,
            "path": relative_output_path,
            "receipt_evidence_id": evidence_id,
            "labels_status": "unlabeled",
            "task_count": 1,
            "force": force,
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
    _reject_unlabeled_tasks(value, fixture_path=str(path))
    return value


def _reject_unlabeled_tasks(fixture: dict[str, Any], *, fixture_path: str) -> None:
    tasks = fixture.get("tasks")
    if not isinstance(tasks, list):
        return
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            continue
        if task.get("labels_status") == "unlabeled":
            raise RetrievalFixtureError(
                "Retrieval fixture contains unlabeled proposed task "
                f"{task.get('id') or f'task-{index}'}. Label expected_files, "
                "expected_tests, and critical_context, then move the fixture into "
                "tests/fixtures/ before running eval.",
                code="eval_retrieval_unlabeled_fixture",
                details={
                    "fixture_path": fixture_path,
                    "task_index": index,
                    "task_id": task.get("id"),
                    "labels_status": "unlabeled",
                    "next_action": "Label the candidate and move it into tests/fixtures/.",
                },
            )


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


def _load_receipt_evidence_row(paths: ProjectPaths, evidence_id: str) -> sqlite3.Row:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, type, path, created_at
            FROM evidence
            WHERE id = ?
            """,
            (evidence_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise RetrievalFixtureError(
            f"Evidence id not found: {evidence_id}.",
            code="eval_fixture_unknown_evidence",
            details={"receipt_evidence_id": evidence_id},
        )
    evidence_type = str(row["type"])
    if evidence_type != CONTEXT_RECEIPT_EVIDENCE_TYPE:
        raise RetrievalFixtureError(
            f"Evidence {evidence_id} is type {evidence_type}, not context_receipt.",
            code="eval_fixture_evidence_wrong_type",
            details={
                "receipt_evidence_id": evidence_id,
                "evidence_type": evidence_type,
                "expected_type": CONTEXT_RECEIPT_EVIDENCE_TYPE,
            },
        )
    return row


def _load_context_receipt_payload(paths: ProjectPaths, row: sqlite3.Row) -> dict[str, Any]:
    receipt_path_value = str(row["path"] or "")
    receipt_path = resolve_context_receipt_path(paths, receipt_path_value)
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        raise RetrievalFixtureError(
            f"Context receipt artifact is unreadable for evidence {row['id']}: {receipt_path_value}.",
            code="eval_fixture_unreadable_receipt",
            details={
                "receipt_evidence_id": str(row["id"]),
                "receipt_path": receipt_path_value,
            },
        ) from exc
    if not isinstance(payload, dict):
        raise RetrievalFixtureError(
            f"Context receipt artifact is not a JSON object for evidence {row['id']}: {receipt_path_value}.",
            code="eval_fixture_unreadable_receipt",
            details={
                "receipt_evidence_id": str(row["id"]),
                "receipt_path": receipt_path_value,
            },
        )
    if payload.get("contract_version") != CONTEXT_RECEIPT_VERSION:
        raise RetrievalFixtureError(
            f"Context receipt artifact has an unsupported contract for evidence {row['id']}: {receipt_path_value}.",
            code="eval_fixture_unreadable_receipt",
            details={
                "receipt_evidence_id": str(row["id"]),
                "receipt_path": receipt_path_value,
                "contract_version": payload.get("contract_version"),
            },
        )
    return payload


def _candidate_fixture_from_receipt(*, evidence_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": RETRIEVAL_FIXTURE_VERSION,
        "tasks": [
            {
                "id": f"{evidence_id.lower()}-retrieval",
                "diff": _synthetic_diff_from_receipt(receipt),
                "diff_synthesized_from_receipt": True,
                "expected_files": [],
                "expected_tests": [],
                "critical_context": [],
                "labels_status": "unlabeled",
                "source_receipt": _source_receipt_payload(evidence_id=evidence_id, receipt=receipt),
            }
        ],
    }


def _source_receipt_payload(*, evidence_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    source = {
        "evidence_id": evidence_id,
        "created_at": str(receipt.get("created_at") or ""),
        "diff_source": str(receipt.get("diff_source") or ""),
        "retrieved_candidate_paths": _retrieved_candidate_paths(receipt),
    }
    base_ref = receipt.get("base_ref")
    if isinstance(base_ref, str) and base_ref.strip():
        source["base_ref"] = base_ref
    return source


def _synthetic_diff_from_receipt(receipt: dict[str, Any]) -> str:
    paths = _changed_file_paths(receipt)
    sections: list[str] = []
    for path in paths:
        sections.extend(
            [
                f"diff --git a/{path} b/{path}",
                f"--- a/{path}",
                f"+++ b/{path}",
                "@@ -1 +1 @@",
                "-synthetic receipt fixture placeholder before",
                "+synthetic receipt fixture placeholder after",
            ]
        )
    return "\n".join(sections)


def _changed_file_paths(receipt: dict[str, Any]) -> list[str]:
    changed_files = receipt.get("changed_files")
    if not isinstance(changed_files, list):
        return []
    paths: list[str] = []
    seen: set[str] = set()
    for item in changed_files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _retrieved_candidate_paths(receipt: dict[str, Any]) -> list[str]:
    included = receipt.get("included_candidate_context")
    if not isinstance(included, list):
        return []
    paths: list[str] = []
    seen: set[str] = set()
    for item in included:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _proposed_fixture_path(paths: ProjectPaths, evidence_id: str) -> Path:
    return paths.root / "fixtures" / "proposed" / f"{evidence_id.lower()}-retrieval.json"


def _relative_to_root(paths: ProjectPaths, path: Path) -> str:
    try:
        return path.relative_to(paths.root).as_posix()
    except ValueError:
        return str(path)


def _append_jsonl_only_event(
    paths: ProjectPaths,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str | None,
    payload: dict[str, Any],
) -> None:
    record = {
        "id": f"EV-{uuid.uuid4().hex[:12].upper()}",
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload,
        "created_at": utc_now_iso(),
    }
    paths.events_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
