from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .diff import _load_diff, _parse_changed_files
from .receipts import _record_context_receipt
from .scan import _sensitive_ignore_reason, _sensitive_index_settings
from .store import (
    IndexSnapshot,
    _load_required_snapshot,
    _staleness_warnings_for_snapshot,
    _summary_sensitive_omitted_count,
)
from .symbols import _file_mentions, _symbol_names
from .test_hints import _is_test_path, _stem_key, _test_path_matches_changed_path
from ..errors import InvalidInputError
from ..guards import require_initialized
from ..paths import ProjectPaths


IMPACT_CONTRACT_VERSION = "impact/v0"


LIKELY_IMPACTED_LIMIT = 20


TARGETED_TEST_SUGGESTION_LIMIT = 6


LEXICAL_SYMBOL_MAX_DOCUMENT_FRACTION = 0.05


LEXICAL_SYMBOL_MIN_DOCUMENT_LIMIT = 10


def analyze_impact(
    paths: ProjectPaths,
    *,
    diff_source: str,
    write_receipt: bool = True,
) -> dict[str, Any]:
    require_initialized(paths)
    snapshot = _load_required_snapshot(paths)
    diff_text, source_label = _load_diff(paths, diff_source)
    changed_files = _parse_changed_files(diff_text)
    if not changed_files:
        raise InvalidInputError(
            "Diff did not contain any changed files.",
            details={"diff_source": source_label},
        )

    staleness_warnings = _staleness_warnings_for_snapshot(paths, snapshot)
    changed = _changed_file_entries(paths, snapshot, changed_files)
    omitted = _omitted_changed_entries(paths, snapshot, changed_files)
    likely_impacted, candidate_omissions = _likely_impacted_entries(paths, snapshot, changed_files)
    omitted.extend(candidate_omissions)
    verification_suggestions = _verification_suggestions(changed, likely_impacted, staleness_warnings)
    sensitive_omitted_count = _summary_sensitive_omitted_count(snapshot.summary)
    impact = {
        "contract_version": IMPACT_CONTRACT_VERSION,
        "diff_source": source_label,
        "index_run": {
            "id": snapshot.run["id"],
            "git_head": snapshot.run.get("git_head"),
            "created_at": snapshot.run["created_at"],
            "index_version": snapshot.run["index_version"],
        },
        "changed_files": changed,
        "likely_impacted": likely_impacted,
        "verification_suggestions": verification_suggestions,
        "omitted": omitted,
        "sensitive_omitted_count": sensitive_omitted_count,
        "staleness_warnings": staleness_warnings,
        "receipt_path": None,
    }
    if write_receipt:
        evidence_id, receipt_path = _record_context_receipt(paths, snapshot, impact)
        impact["evidence_id"] = evidence_id
        impact["receipt_path"] = receipt_path
    return {"ok": True, "impact": impact}


def _changed_file_entries(
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    changed_files: list[dict[str, str]],
) -> list[dict[str, Any]]:
    files_by_path = _safe_snapshot_files_by_path(paths.root, snapshot)
    sensitive_settings = _sensitive_index_settings(paths.root)
    entries: list[dict[str, Any]] = []
    for item in changed_files:
        path = item["path"]
        row = files_by_path.get(path)
        sensitive_reason = _sensitive_ignore_reason(path, sensitive_settings)
        if sensitive_reason:
            row = None
        reason = (
            "changed file is present in the latest index"
            if row
            else "changed file is not present in the latest index"
        )
        if sensitive_reason:
            reason = f"changed file is sensitive-excluded: {sensitive_reason}"
        entries.append(
            {
                "path": path,
                "status": item["status"],
                "indexed": row is not None,
                "language": row.get("language") if row else None,
                "reason": reason,
            }
        )
    return entries


def _omitted_changed_entries(
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    changed_files: list[dict[str, str]],
) -> list[dict[str, Any]]:
    files_by_path = _safe_snapshot_files_by_path(paths.root, snapshot)
    ignored_by_path = snapshot.ignored_by_path
    sensitive_settings = _sensitive_index_settings(paths.root)
    omitted: list[dict[str, Any]] = []
    for item in changed_files:
        path = item["path"]
        if path in files_by_path:
            continue
        sensitive_reason = _sensitive_ignore_reason(path, sensitive_settings)
        ignored = ignored_by_path.get(path)
        if sensitive_reason:
            reason = sensitive_reason
        elif ignored and ignored.get("ignored_reason"):
            reason = str(ignored["ignored_reason"])
        else:
            reason = "not present in latest index"
        omitted.append({"path": path, "reason": reason})
    return omitted


def _likely_impacted_entries(
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    changed_files: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changed_paths = {item["path"] for item in changed_files}
    files_by_path = _safe_snapshot_files_by_path(paths.root, snapshot)
    snapshot_files = _safe_snapshot_files(paths.root, snapshot)
    candidates: dict[str, dict[str, Any]] = {}
    omitted: list[dict[str, Any]] = []
    omitted_symbol_keys: set[tuple[str, str]] = set()

    def add_candidate(path: str, *, reason: str, confidence: float, source_path: str) -> None:
        if path in changed_paths or path not in files_by_path:
            return
        existing = candidates.get(path)
        entry = {
            "path": path,
            "reason": reason,
            "confidence": confidence,
            "source_path": source_path,
            "language": files_by_path[path].get("language"),
        }
        if existing is None or confidence > float(existing["confidence"]):
            candidates[path] = entry

    for changed_path in sorted(changed_paths):
        changed_row = files_by_path.get(changed_path)
        if changed_row is None:
            continue
        test_hint = changed_row.get("test_hint") if isinstance(changed_row.get("test_hint"), dict) else {}
        for candidate in test_hint.get("candidate_tests", []):
            if not isinstance(candidate, dict):
                continue
            candidate_path = str(candidate.get("path") or "")
            if candidate_path:
                add_candidate(
                    candidate_path,
                    reason=f"test_hint:{candidate.get('reason') or 'candidate_test'}",
                    confidence=float(candidate.get("confidence") or 0.7),
                    source_path=changed_path,
                )
        for row in snapshot_files:
            row_path = str(row["path"])
            if not _is_test_path(row_path):
                continue
            if _test_path_matches_changed_path(row_path, changed_path):
                add_candidate(
                    row_path,
                    reason="test_hint:path_token_match",
                    confidence=0.9,
                    source_path=changed_path,
                )
        for row in snapshot_files:
            row_path = str(row["path"])
            if row_path in changed_paths:
                continue
            row_hint = row.get("test_hint") if isinstance(row.get("test_hint"), dict) else {}
            for candidate in row_hint.get("candidate_tests", []):
                if isinstance(candidate, dict) and candidate.get("path") == changed_path:
                    add_candidate(
                        row_path,
                        reason="reverse_test_hint:changed test maps to this source file",
                        confidence=0.75,
                        source_path=changed_path,
                    )
            if _stem_key(row_path) == _stem_key(changed_path):
                add_candidate(
                    row_path,
                    reason="filename_stem_match",
                    confidence=0.55,
                    source_path=changed_path,
                )
        for symbol_name in _symbol_names(changed_row)[:8]:
            document_frequency = _document_frequency(paths.root, snapshot, symbol_name)
            if _symbol_is_too_common(document_frequency, len(snapshot_files)):
                key = (changed_path, symbol_name)
                if key not in omitted_symbol_keys:
                    omitted.append(
                        {
                            "omitted_type": "lexical_symbol_reference",
                            "source_path": changed_path,
                            "symbol": symbol_name,
                            "reason": (
                                "dropped common lexical symbol: "
                                f"{document_frequency} indexed files mention it; "
                                f"threshold is {_lexical_symbol_document_limit(len(snapshot.files))}"
                            ),
                        }
                    )
                    omitted_symbol_keys.add(key)
                continue
            for row in snapshot_files:
                row_path = str(row["path"])
                if row_path in changed_paths or row_path in candidates:
                    continue
                if _file_mentions(paths.root / row_path, symbol_name):
                    add_candidate(
                        row_path,
                        reason=f"lexical_symbol_reference:{symbol_name}",
                        confidence=0.5,
                        source_path=changed_path,
                    )
    ranked = sorted(
        candidates.values(),
        key=lambda item: (-float(item["confidence"]), str(item["reason"]), str(item["path"])),
    )
    included = ranked[:LIKELY_IMPACTED_LIMIT]
    for item in ranked[LIKELY_IMPACTED_LIMIT:]:
        omitted.append(
            {
                "omitted_type": "likely_impacted_candidate",
                "path": item["path"],
                "source_path": item["source_path"],
                "confidence": item["confidence"],
                "reason": f"likely_impacted cap exceeded; top {LIKELY_IMPACTED_LIMIT} candidates included",
            }
        )
    return included, omitted


def _verification_suggestions(
    changed_files: list[dict[str, Any]],
    likely_impacted: list[dict[str, Any]],
    staleness_warnings: list[str],
) -> list[str]:
    suggestions: list[str] = []
    changed_python_tests = sorted(
        {
            str(item["path"])
            for item in changed_files
            if str(item.get("path", "")).endswith(".py")
            and _is_test_path(str(item.get("path", "")))
        }
    )
    if changed_python_tests:
        suggestions.append("python3 -m pytest " + " ".join(changed_python_tests))

    python_tests = [
        str(item["path"])
        for item in likely_impacted
        if str(item.get("path", "")).endswith(".py") and _is_test_path(str(item.get("path", "")))
    ]
    if python_tests:
        unique_tests = sorted(set(python_tests))
        if len(unique_tests) <= TARGETED_TEST_SUGGESTION_LIMIT:
            suggestions.append("python3 -m pytest " + " ".join(unique_tests))
        else:
            suggestions.append("python3 -m pytest")
            suggestions.append(
                f"Review {len(unique_tests)} candidate test files in likely_impacted before narrowing verification."
            )
    elif not suggestions:
        suggestions.append("Review changed files and likely impacted candidate context before choosing verification.")
    if staleness_warnings:
        suggestions.append("Run `pcl index build --json` to refresh the code index before relying on impact output.")
    return suggestions


def _safe_snapshot_files(root: Path, snapshot: IndexSnapshot) -> list[dict[str, Any]]:
    settings = _sensitive_index_settings(root)
    return [
        item
        for item in snapshot.files
        if not _sensitive_ignore_reason(str(item["path"]), settings)
    ]


def _safe_snapshot_files_by_path(root: Path, snapshot: IndexSnapshot) -> dict[str, dict[str, Any]]:
    return {str(item["path"]): item for item in _safe_snapshot_files(root, snapshot)}


def _document_frequency(root: Path, snapshot: IndexSnapshot, value: str) -> int:
    count = 0
    for row in _safe_snapshot_files(root, snapshot):
        if _file_mentions(root / str(row["path"]), value):
            count += 1
    return count


def _symbol_is_too_common(document_frequency: int, file_count: int) -> bool:
    return document_frequency > _lexical_symbol_document_limit(file_count)


def _lexical_symbol_document_limit(file_count: int) -> int:
    fraction_limit = math.ceil(file_count * LEXICAL_SYMBOL_MAX_DOCUMENT_FRACTION)
    return max(LEXICAL_SYMBOL_MIN_DOCUMENT_LIMIT, fraction_limit)
