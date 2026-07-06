from __future__ import annotations

import hashlib
import json
from json import JSONDecodeError
from pathlib import Path
import sqlite3
from typing import Any

from .diff import _git_head, _inline_diff_source
from .impact import analyze_impact
from .receipts import (
    CONTEXT_RECEIPT_EVIDENCE_TYPE,
    CONTEXT_RECEIPT_VERSION,
    resolve_context_receipt_path,
)
from .scan import (
    DEFAULT_CODE_INDEX_EXCLUDES,
    INDEX_VERSION,
    _parse_inline_yaml_list,
    _strip_yaml_string,
)
from .store import (
    INDEX_DETAIL_RELATIVE_PATH,
    IndexSnapshot,
    _ensure_index_schema,
    _latest_snapshot,
)
from .search import search_code
from .. import __version__
from ..db import connect
from ..errors import EXIT_USAGE, DataStoreError, InvalidInputError, PclError
from ..events import append_event
from ..guards import require_initialized
from ..ids import next_prefixed_id
from ..paths import ProjectPaths
from ..token_estimation import TOKEN_ESTIMATOR
from ..timeutil import utc_now_iso


RETRIEVAL_EVAL_VERSION = "retrieval-eval/v0"


RETRIEVAL_FIXTURE_VERSION = "retrieval-fixture/v0"


RETRIEVAL_BASELINE_EVIDENCE_TYPE = "retrieval_eval_baseline"


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

    token_estimate_by_path = _token_estimate_by_path(paths)
    task_results: list[dict[str, Any]] = []
    true_positive_total = 0
    retrieved_total = 0
    expected_total = 0
    token_cost_estimate_total = 0
    token_cost_unestimated_paths: set[str] = set()
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
        false_positive_count = len(retrieved) - len(true_positives)
        missing = sorted(critical - retrieved)
        token_cost = _token_cost_for_paths(
            retrieved,
            token_estimate_by_path=token_estimate_by_path,
        )
        for path in missing:
            missing_critical_context.append({"task_id": task_id, "path": path})
        true_positive_total += len(true_positives)
        retrieved_total += len(retrieved)
        expected_total += len(expected)
        token_cost_estimate_total += token_cost["token_cost_estimate"]
        token_cost_unestimated_paths.update(token_cost["token_cost_unestimated_paths"])
        task_result = {
            "id": task_id,
            "retrieval_source": retrieval["retrieval_source"],
            "retrieved_paths": sorted(retrieved),
            "expected_files": sorted(expected_files),
            "expected_tests": sorted(expected_tests),
            "true_positives": true_positives,
            "precision": _ratio(len(true_positives), len(retrieved)),
            "recall": _ratio(len(true_positives), len(expected)),
            "false_positive_rate": _nullable_ratio(false_positive_count, len(retrieved)),
            "token_cost_estimate": token_cost["token_cost_estimate"],
            "token_cost_estimator": TOKEN_ESTIMATOR,
            "token_cost_basis": "index_detail_token_estimate",
            "token_cost_unestimated_paths": token_cost["token_cost_unestimated_paths"],
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
                "false_positive_rate": _nullable_ratio(
                    retrieved_total - true_positive_total,
                    retrieved_total,
                ),
                "token_cost_estimate": token_cost_estimate_total,
                "token_cost_estimator": TOKEN_ESTIMATOR,
                "token_cost_basis": "index_detail_token_estimate",
                "token_cost_unestimated_paths": sorted(token_cost_unestimated_paths),
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

    conn = connect(paths.db_path)
    try:
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="eval_fixture_proposed",
            entity_type="retrieval_fixture",
            entity_id=relative_output_path,
            payload={
                "receipt_evidence_id": evidence_id,
                "output_path": relative_output_path,
            },
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise DataStoreError(
            f"Could not append proposed retrieval fixture event: {exc}",
            details={
                "receipt_evidence_id": evidence_id,
                "output_path": relative_output_path,
            },
        ) from exc
    finally:
        conn.close()

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


def record_retrieval_baseline(paths: ProjectPaths, *, fixture_path: str) -> dict[str, Any]:
    require_initialized(paths)
    provenance = _baseline_provenance(paths, fixture_path=fixture_path)
    evaluation = evaluate_retrieval(paths, fixture_path=fixture_path)["evaluation"]
    baseline_dir = paths.evidence_dir / "retrieval-eval"
    conn = connect(paths.db_path)
    artifact_path: Path | None = None
    tmp_path: Path | None = None
    try:
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        created_at = utc_now_iso()
        artifact_path = baseline_dir / f"{evidence_id.lower()}-retrieval-eval-baseline.json"
        relative_artifact_path = _relative_to_root(paths, artifact_path)
        payload = {
            "ok": True,
            "baseline": {
                "evidence_id": evidence_id,
                "evidence_path": relative_artifact_path,
                "created_at": created_at,
                "baseline_provenance": provenance,
            },
            "evaluation": evaluation,
        }
        baseline_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = artifact_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(artifact_path)
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                RETRIEVAL_BASELINE_EVIDENCE_TYPE,
                relative_artifact_path,
                f"pcl eval retrieval --fixture {fixture_path} --record-baseline",
                "Retrieval eval baseline.",
                created_at,
            ),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="retrieval_eval_baseline_recorded",
            entity_type="evidence",
            entity_id=evidence_id,
            payload={
                "contract_version": RETRIEVAL_EVAL_VERSION,
                "evidence_path": relative_artifact_path,
                "fixture_path": provenance["fixture_path"],
                "fixture_content_hash": provenance["fixture_content_hash"],
                "index_run_id": provenance["index_run_id"],
                "index_detail_hash": provenance["index_detail_hash"],
                "task_count": evaluation["task_count"],
            },
        )
        conn.commit()
        return payload
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
        if artifact_path and artifact_path.exists():
            artifact_path.unlink()
        raise DataStoreError(
            f"Could not record retrieval eval baseline: {exc}",
            details={"contract_version": RETRIEVAL_EVAL_VERSION},
        ) from exc
    finally:
        conn.close()


def compare_retrieval_baseline(paths: ProjectPaths, *, fixture_path: str) -> dict[str, Any]:
    require_initialized(paths)
    current_provenance = _baseline_provenance(paths, fixture_path=fixture_path)
    current_evaluation = evaluate_retrieval(paths, fixture_path=fixture_path)["evaluation"]
    baseline = _latest_comparable_baseline(
        paths,
        fixture_content_hash=current_provenance["fixture_content_hash"],
    )
    baseline_evaluation = baseline["payload"]["evaluation"]
    current_metrics = _comparison_metrics(current_evaluation)
    baseline_metrics = _comparison_metrics(baseline_evaluation)
    return {
        "ok": True,
        "comparison": {
            "contract_version": RETRIEVAL_EVAL_VERSION,
            "fixture_content_hash": current_provenance["fixture_content_hash"],
            "current_provenance": current_provenance,
            "baseline_provenance": baseline["baseline_provenance"],
            "baseline_evidence": {
                "evidence_id": baseline["evidence_id"],
                "evidence_path": baseline["evidence_path"],
                "created_at": baseline["created_at"],
            },
            "metrics": {
                "current": current_metrics,
                "baseline": baseline_metrics,
                "delta": _metric_delta(current=current_metrics, baseline=baseline_metrics),
            },
        },
    }


def _baseline_provenance(paths: ProjectPaths, *, fixture_path: str) -> dict[str, Any]:
    resolved_fixture_path = _resolve_fixture_path(paths, fixture_path)
    fixture_content_hash = _sha256_file_bytes(
        resolved_fixture_path,
        error_code="eval_baseline_fixture_unreadable",
        detail_key="fixture_path",
    )
    snapshot = _latest_index_snapshot_for_baseline(paths)
    git_head = _git_head(paths.root)
    if not git_head:
        raise RetrievalFixtureError(
            "Cannot record or compare a retrieval eval baseline outside a Git repository.",
            code="eval_baseline_missing_git_head",
            details={"root": str(paths.root)},
        )
    index_detail_hash = _index_detail_hash(paths)
    return {
        "fixture_path": _relative_to_root(paths, resolved_fixture_path),
        "fixture_content_hash": fixture_content_hash,
        "git_head": git_head,
        "index_run_id": str(snapshot.run["id"]),
        "index_detail_hash": index_detail_hash,
        "code_context_config_hash": _code_context_config_hash(paths),
        "pcl_version": __version__,
        "eval_contract_version": RETRIEVAL_EVAL_VERSION,
    }


def _latest_index_snapshot_for_baseline(paths: ProjectPaths) -> IndexSnapshot:
    conn = connect(paths.db_path)
    try:
        _ensure_index_schema(conn)
        snapshot = _latest_snapshot(conn)
    finally:
        conn.close()
    if snapshot is None:
        raise RetrievalFixtureError(
            "Cannot record or compare a retrieval eval baseline before an index run exists. "
            "Run `pcl index build --json` first.",
            code="eval_baseline_missing_index_run",
            details={"index_version": INDEX_VERSION},
        )
    return snapshot


def _index_detail_hash(paths: ProjectPaths) -> str:
    detail_path = paths.root / INDEX_DETAIL_RELATIVE_PATH
    return _sha256_file_bytes(
        detail_path,
        error_code="eval_baseline_missing_index_detail",
        detail_key="index_detail_path",
    )


def _sha256_file_bytes(path: Path, *, error_code: str, detail_key: str) -> str:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise RetrievalFixtureError(
            f"Could not read required baseline provenance input: {path}.",
            code=error_code,
            details={detail_key: str(path)},
        ) from exc
    return hashlib.sha256(content).hexdigest()


def _code_context_config_hash(paths: ProjectPaths) -> str:
    config = _effective_code_index_config(paths)
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _effective_code_index_config(paths: ProjectPaths) -> dict[str, list[str]]:
    config_path = paths.root / "pcl.yaml"
    if not config_path.exists():
        raw_config: dict[str, list[str]] = {}
    else:
        try:
            raw_config = _code_index_config_from_lines(
                config_path.read_text(encoding="utf-8").splitlines()
            )
        except OSError as exc:
            raise RetrievalFixtureError(
                f"Could not read code_context config provenance input: {config_path}.",
                code="eval_baseline_config_unreadable",
                details={"config_path": str(config_path)},
            ) from exc
    return {
        "exclude": raw_config.get("exclude", list(DEFAULT_CODE_INDEX_EXCLUDES)),
        "sensitive_exclude": raw_config.get("sensitive_exclude", []),
        "sensitive_include_override": raw_config.get("sensitive_include_override", []),
    }


def _code_index_config_from_lines(lines: list[str]) -> dict[str, list[str]]:
    values_by_key: dict[str, list[str]] = {}
    in_section = False
    in_list_key: str | None = None
    section_indent = 0
    list_indent = 0
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if indent == 0 and stripped.startswith("code_index:"):
            in_section = True
            in_list_key = None
            section_indent = indent
            continue
        if in_section and indent <= section_indent and not stripped.startswith("-"):
            break
        if not in_section:
            continue
        if ":" in stripped and not stripped.startswith("-"):
            key, raw_value = stripped.split(":", 1)
            key = key.strip()
            in_list_key = key
            list_indent = indent
            raw_value = raw_value.strip()
            values_by_key.setdefault(key, [])
            if raw_value:
                inline = _parse_inline_yaml_list(raw_value)
                if inline is not None:
                    values_by_key[key] = inline
                    in_list_key = None
                else:
                    value = _strip_yaml_string(raw_value)
                    values_by_key[key] = [value] if value else []
                    in_list_key = None
            continue
        if in_list_key and stripped.startswith("-") and indent > list_indent:
            value = _strip_yaml_string(stripped[1:].strip())
            if value:
                values_by_key[in_list_key].append(value)
    return {
        key: _unique_nonempty_list(value)
        for key, value in values_by_key.items()
        if key in {"exclude", "sensitive_exclude", "sensitive_include_override"}
    }


def _unique_nonempty_list(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _latest_comparable_baseline(
    paths: ProjectPaths,
    *,
    fixture_content_hash: str,
) -> dict[str, Any]:
    rows = _baseline_evidence_rows(paths)
    nearest: dict[str, Any] | None = None
    for row in rows:
        baseline = _load_baseline_from_row(paths, row)
        if nearest is None:
            nearest = baseline
        if baseline["baseline_provenance"]["fixture_content_hash"] == fixture_content_hash:
            return baseline
    if nearest is None:
        raise RetrievalFixtureError(
            "No retrieval eval baseline exists for the current fixture hash.",
            code="eval_baseline_not_comparable",
            details={
                "reason": "no_baseline",
                "current_fixture_content_hash": fixture_content_hash,
            },
        )
    nearest_hash = nearest["baseline_provenance"]["fixture_content_hash"]
    raise RetrievalFixtureError(
        "No comparable retrieval eval baseline found; nearest baseline fixture_content_hash "
        f"mismatch: current={fixture_content_hash}, baseline={nearest_hash}.",
        code="eval_baseline_not_comparable",
        details={
            "reason": "fixture_content_hash_mismatch",
            "current_fixture_content_hash": fixture_content_hash,
            "nearest_baseline": {
                "evidence_id": nearest["evidence_id"],
                "evidence_path": nearest["evidence_path"],
                "fixture_content_hash": nearest_hash,
            },
        },
    )


def _baseline_evidence_rows(paths: ProjectPaths) -> list[sqlite3.Row]:
    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, path, created_at
            FROM evidence
            WHERE type = ?
            ORDER BY created_at DESC, id DESC
            """,
            (RETRIEVAL_BASELINE_EVIDENCE_TYPE,),
        ).fetchall()
    finally:
        conn.close()
    return rows


def _load_baseline_from_row(paths: ProjectPaths, row: sqlite3.Row) -> dict[str, Any]:
    evidence_path = str(row["path"] or "")
    artifact_path = paths.root / evidence_path
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        raise DataStoreError(
            f"Could not read retrieval eval baseline artifact: {evidence_path}",
            details={"evidence_id": str(row["id"]), "evidence_path": evidence_path},
        ) from exc
    if not isinstance(payload, dict):
        raise DataStoreError(
            f"Retrieval eval baseline artifact is not a JSON object: {evidence_path}",
            details={"evidence_id": str(row["id"]), "evidence_path": evidence_path},
        )
    baseline = payload.get("baseline")
    evaluation = payload.get("evaluation")
    if not isinstance(baseline, dict) or not isinstance(evaluation, dict):
        raise DataStoreError(
            f"Retrieval eval baseline artifact is missing baseline or evaluation: {evidence_path}",
            details={"evidence_id": str(row["id"]), "evidence_path": evidence_path},
        )
    provenance = baseline.get("baseline_provenance")
    if not isinstance(provenance, dict):
        raise DataStoreError(
            f"Retrieval eval baseline artifact is missing provenance: {evidence_path}",
            details={"evidence_id": str(row["id"]), "evidence_path": evidence_path},
        )
    missing = [field for field in _BASELINE_PROVENANCE_FIELDS if not provenance.get(field)]
    if missing:
        raise DataStoreError(
            f"Retrieval eval baseline artifact has incomplete provenance: {evidence_path}",
            details={
                "evidence_id": str(row["id"]),
                "evidence_path": evidence_path,
                "missing_fields": missing,
            },
        )
    return {
        "evidence_id": str(row["id"]),
        "evidence_path": evidence_path,
        "created_at": str(row["created_at"]),
        "baseline_provenance": provenance,
        "payload": payload,
    }


_BASELINE_PROVENANCE_FIELDS = (
    "fixture_path",
    "fixture_content_hash",
    "git_head",
    "index_run_id",
    "index_detail_hash",
    "code_context_config_hash",
    "pcl_version",
    "eval_contract_version",
)


def _comparison_metrics(evaluation: dict[str, Any]) -> dict[str, int | float | None]:
    metrics = evaluation.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    missing_critical_context = metrics.get("missing_critical_context")
    missing_count = len(missing_critical_context) if isinstance(missing_critical_context, list) else 0
    return {
        "precision": _number_or_none(metrics.get("precision")),
        "recall": _number_or_none(metrics.get("recall")),
        "missing_critical_context_count": missing_count,
        "false_positive_rate": _number_or_none(metrics.get("false_positive_rate")),
        "token_cost_estimate": _int_or_none(metrics.get("token_cost_estimate")),
    }


def _metric_delta(
    *,
    current: dict[str, int | float | None],
    baseline: dict[str, int | float | None],
) -> dict[str, int | float | None]:
    return {
        key: _delta_value(current.get(key), baseline.get(key))
        for key in [
            "precision",
            "recall",
            "missing_critical_context_count",
            "false_positive_rate",
            "token_cost_estimate",
        ]
    }


def _delta_value(
    current: int | float | None,
    baseline: int | float | None,
) -> int | float | None:
    if current is None or baseline is None:
        return None
    if isinstance(current, int) and isinstance(baseline, int):
        return current - baseline
    return round(float(current) - float(baseline), 4)


def _number_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


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


def _nullable_ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _token_cost_for_paths(
    paths: set[str],
    *,
    token_estimate_by_path: dict[str, int],
) -> dict[str, Any]:
    token_cost_estimate = 0
    token_cost_unestimated_paths: list[str] = []
    for path in sorted(paths):
        token_estimate = token_estimate_by_path.get(path)
        if token_estimate is None:
            token_cost_unestimated_paths.append(path)
            continue
        token_cost_estimate += token_estimate
    return {
        "token_cost_estimate": token_cost_estimate,
        "token_cost_unestimated_paths": token_cost_unestimated_paths,
    }


def _token_estimate_by_path(paths: ProjectPaths) -> dict[str, int]:
    detail_path = paths.root / INDEX_DETAIL_RELATIVE_PATH
    try:
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError):
        return {}
    if not isinstance(detail, dict):
        return {}
    files = detail.get("files")
    if not isinstance(files, list):
        return {}
    token_estimate_by_path: dict[str, int] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        token_estimate = item.get("token_estimate")
        if path and isinstance(token_estimate, int) and not isinstance(token_estimate, bool):
            token_estimate_by_path[path] = token_estimate
    return token_estimate_by_path


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
