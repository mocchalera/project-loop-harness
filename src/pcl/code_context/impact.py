from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .diff import PROVIDED_DIFF_SOURCE, LoadedDiff, _load_diff, _parse_changed_files
from .receipts import _record_context_receipt
from .scan import (
    _code_index_exclude_patterns,
    _configured_ignore_reason,
    _default_ignore_reason,
    _sensitive_ignore_reason,
    _sensitive_index_settings,
)
from .store import (
    IndexSnapshot,
    _load_required_snapshot,
    _staleness_warnings_for_snapshot,
    _summary_sensitive_omitted_count,
)
from .symbols import _file_mentions, _symbol_names
from .test_hints import _is_test_path, _stem_key, _test_path_matches_changed_path
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
    base_ref: str | None = None,
    staged: bool = False,
    unstaged: bool = False,
    include_untracked: bool = False,
    all_changes: bool = False,
    write_receipt: bool = True,
) -> dict[str, Any]:
    require_initialized(paths)
    snapshot = _load_required_snapshot(paths)
    loaded_diff = _load_diff(
        paths,
        diff_source,
        base_ref=base_ref,
        staged=staged,
        unstaged=unstaged,
        include_untracked=include_untracked,
        all_changes=all_changes,
    )
    changed_files = _parse_changed_files(loaded_diff.text)
    untracked_paths = set(loaded_diff.untracked_paths)

    staleness_warnings = _staleness_warnings_for_snapshot(paths, snapshot)
    sensitive_omitted_count = _summary_sensitive_omitted_count(snapshot.summary)
    if not changed_files:
        return {
            "ok": True,
            "impact": _empty_impact_payload(
                snapshot=snapshot,
                loaded_diff=loaded_diff,
                sensitive_omitted_count=sensitive_omitted_count,
                staleness_warnings=staleness_warnings,
            ),
        }

    indexable_changed_files, excluded_changed_files = _split_indexable_changed_files(paths, changed_files)
    changed = _changed_file_entries(paths, snapshot, indexable_changed_files, untracked_paths=untracked_paths)
    omitted = _omitted_changed_entries(
        paths,
        snapshot,
        indexable_changed_files,
        included_untracked_paths=untracked_paths,
    )
    likely_impacted, candidate_omissions = _likely_impacted_entries(paths, snapshot, indexable_changed_files)
    omitted.extend(candidate_omissions)
    verification_suggestion_items = _verification_suggestion_items_for_indexable_changes(
        changed,
        likely_impacted,
        staleness_warnings,
    )
    impact = {
        "contract_version": IMPACT_CONTRACT_VERSION,
        "diff_source": loaded_diff.diff_source,
        "diff_provenance": loaded_diff.provenance,
        "index_run": _index_run_payload(snapshot),
        "changed_files": changed,
        "excluded_changed_files": excluded_changed_files,
        "likely_impacted": likely_impacted,
        "verification_suggestions": [
            item["command"] for item in verification_suggestion_items
        ],
        "omitted": omitted,
        "sensitive_omitted_count": sensitive_omitted_count,
        "staleness_warnings": staleness_warnings,
        "receipt_path": None,
    }
    _add_untracked_inclusion_metadata(impact, loaded_diff)
    if loaded_diff.base_ref is not None:
        impact["base_ref"] = loaded_diff.base_ref
    if write_receipt:
        receipt_impact = {
            **impact,
            "_verification_suggestion_items": verification_suggestion_items,
        }
        evidence_id, receipt_path = _record_context_receipt(paths, snapshot, receipt_impact)
        impact["evidence_id"] = evidence_id
        impact["receipt_path"] = receipt_path
    return {"ok": True, "impact": impact}


def _index_run_payload(snapshot: IndexSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.run["id"],
        "git_head": snapshot.run.get("git_head"),
        "created_at": snapshot.run["created_at"],
        "index_version": snapshot.run["index_version"],
        "sensitive_include_override_used": bool(snapshot.summary.get("sensitive_include_override_used")),
    }


def _empty_impact_payload(
    *,
    snapshot: IndexSnapshot,
    loaded_diff: LoadedDiff,
    sensitive_omitted_count: int,
    staleness_warnings: list[str],
) -> dict[str, Any]:
    guidance = _empty_diff_guidance(loaded_diff)
    impact = {
        "contract_version": IMPACT_CONTRACT_VERSION,
        "diff_source": loaded_diff.diff_source,
        "diff_provenance": loaded_diff.provenance,
        "index_run": _index_run_payload(snapshot),
        "changed_files": [],
        "excluded_changed_files": [],
        "likely_impacted": [],
        "verification_suggestions": [],
        "omitted": [],
        "sensitive_omitted_count": sensitive_omitted_count,
        "staleness_warnings": staleness_warnings,
        "receipt_path": None,
        "empty_diff_guidance": guidance,
    }
    _add_untracked_inclusion_metadata(impact, loaded_diff)
    if loaded_diff.base_ref is not None:
        impact["base_ref"] = loaded_diff.base_ref
    return impact


def _split_indexable_changed_files(
    paths: ProjectPaths,
    changed_files: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    indexable: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    for item in changed_files:
        path = item["path"]
        reason = _changed_file_exclusion_reason(paths, path)
        if reason:
            excluded.append({"path": path, "status": item["status"], "reason": reason})
        else:
            indexable.append(item)
    return indexable, excluded


def _changed_file_exclusion_reason(paths: ProjectPaths, path: str) -> str | None:
    sensitive_reason = _sensitive_ignore_reason(path, _sensitive_index_settings(paths.root))
    if sensitive_reason:
        return sensitive_reason
    default_reason = _default_ignore_reason(path)
    if default_reason:
        return default_reason
    configured_reason = _configured_ignore_reason(path, _code_index_exclude_patterns(paths.root))
    if configured_reason:
        return configured_reason
    return None


def _verification_suggestions_for_indexable_changes(
    changed_files: list[dict[str, Any]],
    likely_impacted: list[dict[str, Any]],
    staleness_warnings: list[str],
) -> list[str]:
    return [
        item["command"]
        for item in _verification_suggestion_items_for_indexable_changes(
            changed_files,
            likely_impacted,
            staleness_warnings,
        )
    ]


def _verification_suggestion_items_for_indexable_changes(
    changed_files: list[dict[str, Any]],
    likely_impacted: list[dict[str, Any]],
    staleness_warnings: list[str],
) -> list[dict[str, str]]:
    if changed_files or likely_impacted:
        return _verification_suggestion_items(changed_files, likely_impacted, staleness_warnings)
    if staleness_warnings:
        return [
            {
                "command": (
                    "Run `pcl index build --json` to refresh the code index before relying on impact output."
                ),
                "reason": "staleness_warnings",
            }
        ]
    return []


def _empty_diff_guidance(loaded_diff: LoadedDiff) -> dict[str, Any]:
    diff_source = loaded_diff.diff_source
    next_steps = [
        "No context receipt was written because the stated diff has no changed files.",
    ]
    if diff_source.startswith("staged-vs-"):
        next_steps.append("Stage changes with `git add` before using `--staged`, or use the default mode.")
    elif diff_source == "worktree-vs-index":
        next_steps.append("Use `--staged` for staged changes, or edit files before using `--unstaged`.")
    elif diff_source == PROVIDED_DIFF_SOURCE:
        next_steps.append("Check that the provided diff contains changed file paths.")
    else:
        next_steps.append(
            "If HEAD equals the working tree, compare against a branch with "
            "`pcl impact --diff --base <default-branch> --json`."
        )
    if loaded_diff.untracked_excluded_count:
        next_steps.append("Untracked files are present; add `--include-untracked` to include them.")
    elif loaded_diff.untracked_included:
        next_steps.append("No tracked or untracked files matched this diff mode.")
    elif diff_source != PROVIDED_DIFF_SOURCE:
        next_steps.append(
            "If the expected change is untracked, add it to Git or provide an explicit diff with "
            "`pcl impact --diff - --json`."
        )
    return {
        "message": f"There is nothing to analyze for diff_source {diff_source}.",
        "next_steps": next_steps,
    }


def _changed_file_entries(
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    changed_files: list[dict[str, str]],
    *,
    untracked_paths: set[str] | None = None,
) -> list[dict[str, Any]]:
    files_by_path = _safe_snapshot_files_by_path(paths.root, snapshot)
    sensitive_settings = _sensitive_index_settings(paths.root)
    untracked_paths = untracked_paths or set()
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
        if path in untracked_paths:
            reason = "untracked file included as added file"
        entry = {
            "path": path,
            "status": item["status"],
            "indexed": row is not None,
            "language": row.get("language") if row else None,
            "reason": reason,
        }
        if path in untracked_paths:
            entry["untracked"] = True
        entries.append(entry)
    return entries


def _omitted_changed_entries(
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    changed_files: list[dict[str, str]],
    *,
    included_untracked_paths: set[str] | None = None,
) -> list[dict[str, Any]]:
    files_by_path = _safe_snapshot_files_by_path(paths.root, snapshot)
    ignored_by_path = snapshot.ignored_by_path
    sensitive_settings = _sensitive_index_settings(paths.root)
    included_untracked_paths = included_untracked_paths or set()
    omitted: list[dict[str, Any]] = []
    for item in changed_files:
        path = item["path"]
        if path in files_by_path:
            continue
        if path in included_untracked_paths:
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


def _add_untracked_inclusion_metadata(impact: dict[str, Any], loaded_diff: LoadedDiff) -> None:
    if not loaded_diff.untracked_included:
        return
    paths = list(loaded_diff.untracked_paths)
    impact["untracked_included_count"] = len(paths)
    impact["untracked_included_paths"] = paths


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
    return [
        item["command"]
        for item in _verification_suggestion_items(
            changed_files,
            likely_impacted,
            staleness_warnings,
        )
    ]


def _verification_suggestion_items(
    changed_files: list[dict[str, Any]],
    likely_impacted: list[dict[str, Any]],
    staleness_warnings: list[str],
) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    changed_python_tests = sorted(
        {
            str(item["path"])
            for item in changed_files
            if str(item.get("path", "")).endswith(".py")
            and _is_test_path(str(item.get("path", "")))
        }
    )
    if changed_python_tests:
        suggestions.append(
            {
                "command": "python3 -m pytest " + " ".join(changed_python_tests),
                "reason": "changed_file:test",
            }
        )

    python_test_candidates = [
        item
        for item in likely_impacted
        if str(item.get("path", "")).endswith(".py") and _is_test_path(str(item.get("path", "")))
    ]
    if python_test_candidates:
        unique_tests = sorted({str(item["path"]) for item in python_test_candidates})
        if len(unique_tests) <= TARGETED_TEST_SUGGESTION_LIMIT:
            suggestions.append(
                {
                    "command": "python3 -m pytest " + " ".join(unique_tests),
                    "reason": _verification_suggestion_reason(python_test_candidates),
                }
            )
        else:
            suggestions.append(
                {
                    "command": "python3 -m pytest",
                    "reason": "test_hint:candidate_test_limit_exceeded",
                }
            )
            suggestions.append(
                {
                    "command": (
                        f"Review {len(unique_tests)} candidate test files in likely_impacted "
                        "before narrowing verification."
                    ),
                    "reason": "likely_impacted:candidate_test_limit_exceeded",
                }
            )
    elif not suggestions:
        suggestions.append(
            {
                "command": (
                    "Review changed files and likely impacted candidate context before choosing verification."
                ),
                "reason": "candidate_context:review_required",
            }
        )
    if staleness_warnings:
        suggestions.append(
            {
                "command": (
                    "Run `pcl index build --json` to refresh the code index before relying on impact output."
                ),
                "reason": "staleness_warnings",
            }
        )
    return suggestions


def _verification_suggestion_reason(candidates: list[dict[str, Any]]) -> str:
    reasons = sorted(
        {
            str(item.get("reason") or "").strip()
            for item in candidates
            if str(item.get("reason") or "").strip()
        }
    )
    if len(reasons) == 1:
        return reasons[0]
    if reasons and all(reason.startswith("test_hint:") for reason in reasons):
        return "test_hint:multiple"
    if reasons:
        return "likely_impacted:multiple"
    return "likely_impacted:candidate_test"


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
