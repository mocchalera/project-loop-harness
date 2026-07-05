from __future__ import annotations

import ast
from dataclasses import dataclass, field
import fnmatch
import hashlib
import json
from json import JSONDecodeError
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from typing import Any

from .db import connect, table_exists
from .errors import DataStoreError, InvalidInputError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso


INDEX_VERSION = "code-index/v0"
SYMBOL_SUMMARY_VERSION = "symbol-summary/v0"
TEST_HINT_VERSION = "test-hint/v0"
CODE_SEARCH_VERSION = "code-search/v0"
IMPACT_CONTRACT_VERSION = "impact/v0"
CONTEXT_RECEIPT_VERSION = "context-receipt/v0"
RETRIEVAL_EVAL_VERSION = "retrieval-eval/v0"
RETRIEVAL_FIXTURE_VERSION = "retrieval-fixture/v0"
GIT_DIFF_SENTINEL = "__git__"
LARGE_FILE_BYTES = 1_000_000
SEARCH_SNIPPET_CHARS = 220
LIKELY_IMPACTED_LIMIT = 20
TARGETED_TEST_SUGGESTION_LIMIT = 6
LEXICAL_SYMBOL_MAX_DOCUMENT_FRACTION = 0.05
LEXICAL_SYMBOL_MIN_DOCUMENT_LIMIT = 10

DEFAULT_CODE_INDEX_EXCLUDES = (
    ".claude/",
    ".agents/",
    ".codex/",
)

DEFAULT_SENSITIVE_EXCLUDES = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "credentials*.json",
    ".npmrc",
    ".pypirc",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    ".netrc",
    ".aws/",
    "secrets/",
)

DEFAULT_IGNORED_NAMES = {
    ".git": "default_ignore:.git",
    ".project-loop": "default_ignore:.project-loop",
    ".pytest_cache": "default_ignore:.pytest_cache",
    ".ruff_cache": "default_ignore:.ruff_cache",
    ".venv": "default_ignore:.venv",
    "__pycache__": "default_ignore:__pycache__",
    "dist": "default_ignore:dist",
    "node_modules": "default_ignore:node_modules",
}

LANGUAGE_BY_SUFFIX = {
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".markdown": "markdown",
    ".mjs": "javascript",
    ".py": "python",
    ".rst": "text",
    ".sh": "shell",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}

PYTHON_DEF_RE = re.compile(r"^\s*(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PYTHON_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b")
JS_FUNCTION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("
)
JS_CLASS_RE = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b"
)
JS_EXPORT_BINDING_RE = re.compile(r"^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")
JS_EXPORT_LIST_RE = re.compile(r"^\s*export\s+\{([^}]+)\}")
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
ID_NUMBER_RE = re.compile(r"^[A-Z]+-(\d+)$")


@dataclass
class IgnoredEntry:
    path: str
    ignored_reason: str
    size_bytes: int | None = None
    hash_skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "ignored_reason": self.ignored_reason,
        }
        if self.size_bytes is not None:
            payload["size_bytes"] = self.size_bytes
        if self.hash_skipped_reason:
            payload["sha256"] = None
            payload["hash_skipped_reason"] = self.hash_skipped_reason
        return payload


@dataclass
class IndexedFile:
    path: str
    absolute_path: Path
    language: str
    size_bytes: int
    mtime: int
    sha256: str | None
    line_count: int
    symbol_summary: dict[str, Any]
    test_hint: dict[str, Any]
    text: str = field(repr=False, default="")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "size_bytes": self.size_bytes,
            "mtime": self.mtime,
            "sha256": self.sha256,
            "line_count": self.line_count,
            "symbol_summary": self.symbol_summary,
            "test_hint": self.test_hint,
        }


@dataclass
class ScanResult:
    files: list[IndexedFile]
    ignored: list[IgnoredEntry]
    git_head: str | None
    sensitive_include_override: tuple[str, ...] = ()

    @property
    def indexed_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)

    @property
    def language_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.files:
            counts[item.language] = counts.get(item.language, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def sensitive_omitted_count(self) -> int:
        return sum(1 for item in self.ignored if item.ignored_reason.startswith("sensitive:"))


@dataclass(frozen=True)
class SensitiveIndexSettings:
    additional_patterns: tuple[str, ...] = ()
    agent_may_not_modify_patterns: tuple[str, ...] = ()
    include_override_patterns: tuple[str, ...] = ()


@dataclass
class IndexSnapshot:
    run: dict[str, Any]
    files: list[dict[str, Any]]
    summary: dict[str, Any]

    @property
    def files_by_path(self) -> dict[str, dict[str, Any]]:
        return {str(item["path"]): item for item in self.files}

    @property
    def ignored_by_path(self) -> dict[str, dict[str, Any]]:
        ignored = self.summary.get("ignored", [])
        if not isinstance(ignored, list):
            return {}
        return {
            str(item.get("path")): item
            for item in ignored
            if isinstance(item, dict) and item.get("path")
        }


def build_code_index(paths: ProjectPaths) -> dict[str, Any]:
    require_initialized(paths)
    scan = _scan_working_tree(paths.root, include_text=True, warn_on_sensitive_override=True)
    _attach_test_hints(scan.files)
    summary = _index_summary(scan)

    conn = connect(paths.db_path)
    try:
        _ensure_index_schema(conn)
        run_id = next_prefixed_id(conn, "code_index_runs", "CI")
        created_at = utc_now_iso()
        conn.execute(
            """
            INSERT INTO code_index_runs(
              id, root_path, created_at, git_head, file_count, indexed_bytes,
              ignored_count, index_version, status, summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                str(paths.root),
                created_at,
                scan.git_head,
                len(scan.files),
                scan.indexed_bytes,
                len(scan.ignored),
                INDEX_VERSION,
                "built",
                json.dumps(summary, ensure_ascii=False, sort_keys=True),
            ),
        )
        next_file_number = _next_numeric_suffix(conn, "code_index_files", "CIF")
        for offset, item in enumerate(scan.files):
            file_id = f"CIF-{next_file_number + offset:04d}"
            conn.execute(
                """
                INSERT INTO code_index_files(
                  id, index_run_id, path, language, size_bytes, mtime, sha256,
                  line_count, symbol_summary_json, test_hint_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    run_id,
                    item.path,
                    item.language,
                    item.size_bytes,
                    item.mtime,
                    item.sha256,
                    item.line_count,
                    json.dumps(item.symbol_summary, ensure_ascii=False, sort_keys=True),
                    json.dumps(item.test_hint, ensure_ascii=False, sort_keys=True),
                ),
            )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="code_index_built",
            entity_type="code_index_run",
            entity_id=run_id,
            payload={
                "index_version": INDEX_VERSION,
                "root_path": str(paths.root),
                "git_head": scan.git_head,
                "file_count": len(scan.files),
                "indexed_bytes": scan.indexed_bytes,
                "ignored_count": len(scan.ignored),
                "sensitive_omitted_count": scan.sensitive_omitted_count,
            },
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise DataStoreError(
            f"Could not store code index: {exc}",
            details={"index_version": INDEX_VERSION},
        ) from exc
    finally:
        conn.close()

    return {
        "ok": True,
        "index": _build_index_payload(paths=paths, scan=scan, summary=summary),
    }


def code_index_status(paths: ProjectPaths) -> dict[str, Any]:
    require_initialized(paths)
    conn = connect(paths.db_path)
    try:
        _ensure_index_schema(conn)
        snapshot = _latest_snapshot(conn)
    finally:
        conn.close()

    if snapshot is None:
        return {
            "ok": True,
            "index": {
                "contract_version": INDEX_VERSION,
                "stale": True,
                "file_count": 0,
                "ignored_count": 0,
                "sensitive_omitted_count": 0,
                "last_run": None,
                "current_git_head": _git_head(paths.root),
                "staleness_warnings": ["No code index run has been recorded."],
            },
        }

    warnings = _staleness_warnings_for_snapshot(paths, snapshot)
    return {
        "ok": True,
        "index": {
            "contract_version": INDEX_VERSION,
            "stale": bool(warnings),
            "file_count": int(snapshot.run["file_count"]),
            "ignored_count": int(snapshot.run["ignored_count"]),
            "sensitive_omitted_count": _summary_sensitive_omitted_count(snapshot.summary),
            "indexed_bytes": int(snapshot.run["indexed_bytes"]),
            "last_run": snapshot.run,
            "current_git_head": _git_head(paths.root),
            "staleness_warnings": warnings,
        },
    }


def search_code(paths: ProjectPaths, *, query: str, limit: int = 50) -> dict[str, Any]:
    require_initialized(paths)
    terms = [_search_normalized(term) for term in query.split() if term.strip()]
    if not terms:
        raise InvalidInputError("Search query must not be empty.", details={"query": query})
    if limit < 1:
        raise InvalidInputError("--limit must be a positive integer.", details={"limit": limit})

    snapshot = _load_required_snapshot(paths)
    sensitive_settings = _sensitive_index_settings(paths.root)
    ranked_results: list[tuple[tuple[int, str], dict[str, Any]]] = []
    for item in snapshot.files:
        path = str(item["path"])
        if _sensitive_ignore_reason(path, sensitive_settings):
            continue
        absolute_path = paths.root / path
        try:
            lines = absolute_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        text = _search_normalized("\n".join(lines))
        if not all(term in text for term in terms):
            continue
        score, reason_parts = _search_score(path=path, lines=lines, terms=terms)
        result_lines, snippet = _search_result_lines(lines, terms)
        ranked_results.append(
            (
                (-score, path),
                {
                    "path": path,
                    "lines": result_lines,
                    "snippet": snippet,
                    "reason": "; ".join(reason_parts),
                },
            )
        )
    results = [item for _, item in sorted(ranked_results, key=lambda item: item[0])[:limit]]
    return _search_payload(query=query, limit=limit, results=results)


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
        retrieved = _retrieved_paths_for_fixture_task(paths, task)
        true_positives = sorted(retrieved & expected)
        missing = sorted(critical - retrieved)
        for path in missing:
            missing_critical_context.append({"task_id": task_id, "path": path})
        true_positive_total += len(true_positives)
        retrieved_total += len(retrieved)
        expected_total += len(expected)
        task_results.append(
            {
                "id": task_id,
                "retrieved_paths": sorted(retrieved),
                "expected_files": sorted(expected_files),
                "expected_tests": sorted(expected_tests),
                "true_positives": true_positives,
                "precision": _ratio(len(true_positives), len(retrieved)),
                "recall": _ratio(len(true_positives), len(expected)),
                "missing_critical_context": missing,
            }
        )

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


def _scan_working_tree(
    root: Path,
    *,
    include_text: bool,
    warn_on_sensitive_override: bool = False,
) -> ScanResult:
    root = root.resolve()
    configured_excludes = _code_index_exclude_patterns(root)
    sensitive_settings = _sensitive_index_settings(root)
    if warn_on_sensitive_override and sensitive_settings.include_override_patterns:
        print(_sensitive_override_warning(sensitive_settings.include_override_patterns), file=sys.stderr)
    ignored: list[IgnoredEntry] = []
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current_dir = Path(dirpath)
        dirnames.sort()
        filenames.sort()
        kept_dirnames: list[str] = []
        for dirname in dirnames:
            child = current_dir / dirname
            rel = _relative_path(root, child)
            sensitive_reason = _sensitive_ignore_reason(f"{rel}/", sensitive_settings)
            if sensitive_reason:
                ignored.append(IgnoredEntry(path=f"{rel}/", ignored_reason=sensitive_reason))
                continue
            reason = DEFAULT_IGNORED_NAMES.get(dirname)
            if reason:
                ignored.append(IgnoredEntry(path=f"{rel}/", ignored_reason=reason))
                continue
            configured_reason = _configured_ignore_reason(f"{rel}/", configured_excludes)
            if configured_reason:
                ignored.append(IgnoredEntry(path=f"{rel}/", ignored_reason=configured_reason))
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames
        for filename in filenames:
            path = current_dir / filename
            rel = _relative_path(root, path)
            sensitive_reason = _sensitive_ignore_reason(rel, sensitive_settings)
            if sensitive_reason:
                ignored.append(IgnoredEntry(path=rel, ignored_reason=sensitive_reason))
                continue
            default_reason = _default_ignore_reason(rel)
            if default_reason:
                ignored.append(IgnoredEntry(path=rel, ignored_reason=default_reason))
                continue
            configured_reason = _configured_ignore_reason(rel, configured_excludes)
            if configured_reason:
                ignored.append(IgnoredEntry(path=rel, ignored_reason=configured_reason))
                continue
            candidates.append(path)

    gitignored = _gitignored_paths(root, [_relative_path(root, path) for path in candidates])
    files: list[IndexedFile] = []
    for path in candidates:
        rel = _relative_path(root, path)
        if rel in gitignored:
            ignored.append(IgnoredEntry(path=rel, ignored_reason=gitignored[rel]))
            continue
        try:
            stat = path.stat()
        except OSError as exc:
            ignored.append(IgnoredEntry(path=rel, ignored_reason=f"unreadable:{exc.__class__.__name__}"))
            continue
        if not path.is_file():
            continue
        size = int(stat.st_size)
        if size > LARGE_FILE_BYTES:
            ignored.append(
                IgnoredEntry(
                    path=rel,
                    ignored_reason="large_file",
                    size_bytes=size,
                    hash_skipped_reason=f"size>{LARGE_FILE_BYTES}",
                )
            )
            continue
        try:
            sample = path.read_bytes()[:8192]
        except OSError as exc:
            ignored.append(IgnoredEntry(path=rel, ignored_reason=f"unreadable:{exc.__class__.__name__}"))
            continue
        if _looks_binary(sample):
            ignored.append(
                IgnoredEntry(
                    path=rel,
                    ignored_reason="binary_file",
                    size_bytes=size,
                    hash_skipped_reason="binary_file",
                )
            )
            continue
        text = ""
        if include_text:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                ignored.append(
                    IgnoredEntry(
                        path=rel,
                        ignored_reason=f"text_decode_failed:{exc.__class__.__name__}",
                        size_bytes=size,
                        hash_skipped_reason="text_decode_failed",
                    )
                )
                continue
        files.append(
            IndexedFile(
                path=rel,
                absolute_path=path,
                language=_detect_language(path),
                size_bytes=size,
                mtime=int(stat.st_mtime_ns),
                sha256=_sha256_file(path) if include_text else None,
                line_count=_line_count(text) if include_text else 0,
                symbol_summary=_symbol_summary(rel, text) if include_text else _empty_symbol_summary(),
                test_hint=_empty_test_hint(rel),
                text=text,
            )
        )
    files.sort(key=lambda item: item.path)
    ignored.sort(key=lambda item: item.path)
    return ScanResult(
        files=files,
        ignored=ignored,
        git_head=_git_head(root),
        sensitive_include_override=sensitive_settings.include_override_patterns,
    )


def _attach_test_hints(files: list[IndexedFile]) -> None:
    for item in files:
        item.test_hint = _test_hint_for_file(item, files)


def _index_summary(scan: ScanResult) -> dict[str, Any]:
    return {
        "contract_version": INDEX_VERSION,
        "sensitive_omitted_count": scan.sensitive_omitted_count,
        "sensitive_include_override": list(scan.sensitive_include_override),
        "sensitive_include_override_used": bool(scan.sensitive_include_override),
        "ignored": [item.to_dict() for item in scan.ignored],
        "hash_skipped": [
            item.to_dict()
            for item in scan.ignored
            if item.hash_skipped_reason in {"binary_file", f"size>{LARGE_FILE_BYTES}", "text_decode_failed"}
        ],
        "language_counts": scan.language_counts,
    }


def _build_index_payload(*, paths: ProjectPaths, scan: ScanResult, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": INDEX_VERSION,
        "root_path": str(paths.root),
        "git_head": scan.git_head,
        "file_count": len(scan.files),
        "indexed_bytes": scan.indexed_bytes,
        "ignored_count": len(scan.ignored),
        "sensitive_omitted_count": summary["sensitive_omitted_count"],
        "language_counts": scan.language_counts,
        "files": [item.to_public_dict() for item in scan.files],
        "ignored": summary["ignored"],
        "hash_skipped": summary["hash_skipped"],
        "event_appended": True,
    }


def _ensure_index_schema(conn: sqlite3.Connection) -> None:
    missing = [
        table_name
        for table_name in ["code_index_runs", "code_index_files"]
        if not table_exists(conn, table_name)
    ]
    if missing:
        raise InvalidInputError(
            "Code index schema is not available. Run `pcl migrate`.",
            details={"missing_tables": missing},
        )


def _latest_snapshot(conn: sqlite3.Connection) -> IndexSnapshot | None:
    run = conn.execute(
        """
        SELECT id, root_path, created_at, git_head, file_count, indexed_bytes,
               ignored_count, index_version, status, summary_json
        FROM code_index_runs
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if run is None:
        return None
    run_dict = dict(run)
    summary = _json_object(run_dict.pop("summary_json"))
    rows = conn.execute(
        """
        SELECT id, index_run_id, path, language, size_bytes, mtime, sha256,
               line_count, symbol_summary_json, test_hint_json
        FROM code_index_files
        WHERE index_run_id = ?
        ORDER BY path
        """,
        (run_dict["id"],),
    ).fetchall()
    files: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["symbol_summary"] = _json_object(item.pop("symbol_summary_json"))
        item["test_hint"] = _json_object(item.pop("test_hint_json"))
        files.append(item)
    return IndexSnapshot(run=run_dict, files=files, summary=summary)


def _load_required_snapshot(paths: ProjectPaths) -> IndexSnapshot:
    conn = connect(paths.db_path)
    try:
        _ensure_index_schema(conn)
        snapshot = _latest_snapshot(conn)
    finally:
        conn.close()
    if snapshot is None:
        raise InvalidInputError(
            "No code index run exists. Run `pcl index build --json`.",
            details={"index_version": INDEX_VERSION},
        )
    return snapshot


def _staleness_warnings_for_snapshot(paths: ProjectPaths, snapshot: IndexSnapshot) -> list[str]:
    current = _scan_working_tree(paths.root, include_text=False)
    current_by_path = {item.path: item for item in current.files}
    previous_by_path = snapshot.files_by_path
    warnings: list[str] = []
    previous_git_head = snapshot.run.get("git_head")
    if previous_git_head and current.git_head and previous_git_head != current.git_head:
        warnings.append(
            f"Git HEAD differs from index snapshot: index={previous_git_head}, current={current.git_head}."
        )
    deleted = sorted(set(previous_by_path) - set(current_by_path))
    added = sorted(set(current_by_path) - set(previous_by_path))
    changed = sorted(
        path
        for path in set(previous_by_path) & set(current_by_path)
        if int(previous_by_path[path]["size_bytes"]) != current_by_path[path].size_bytes
        or int(previous_by_path[path]["mtime"]) != current_by_path[path].mtime
    )
    if deleted:
        warnings.append(_counted_path_warning("Indexed files are missing", deleted))
    if added:
        warnings.append(_counted_path_warning("New files are not in the index", added))
    if changed:
        warnings.append(_counted_path_warning("Indexed file metadata changed", changed))
    if len(current.ignored) != int(snapshot.run["ignored_count"]):
        warnings.append(
            "Ignored path count differs from index snapshot: "
            f"index={snapshot.run['ignored_count']}, current={len(current.ignored)}."
        )
    return warnings


def _counted_path_warning(prefix: str, paths: list[str], *, limit: int = 5) -> str:
    visible = ", ".join(paths[:limit])
    if len(paths) > limit:
        visible += f", ... (+{len(paths) - limit} more)"
    return f"{prefix}: {visible}."


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


def _record_context_receipt(
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    impact: dict[str, Any],
) -> tuple[str, str]:
    receipt_dir = paths.context_receipts_dir
    receipt_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(paths.db_path)
    receipt_path: Path | None = None
    tmp_path: Path | None = None
    try:
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        receipt_name = f"{evidence_id.lower()}-impact-v0.json"
        receipt_path = receipt_dir / receipt_name
        relative_receipt_path = _relative_path(paths.root, receipt_path)
        receipt = _receipt_payload(
            paths=paths,
            snapshot=snapshot,
            impact=impact,
            evidence_id=evidence_id,
            receipt_path=relative_receipt_path,
        )
        tmp_path = receipt_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(receipt_path)
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                "context_receipt",
                relative_receipt_path,
                "pcl impact --diff",
                "Impact candidate context receipt.",
                utc_now_iso(),
            ),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="context_receipt_recorded",
            entity_type="evidence",
            entity_id=evidence_id,
            payload={
                "contract_version": CONTEXT_RECEIPT_VERSION,
                "impact_contract_version": IMPACT_CONTRACT_VERSION,
                "receipt_path": relative_receipt_path,
                "index_run_id": snapshot.run["id"],
                "changed_file_count": len(impact["changed_files"]),
                "included_candidate_context_count": len(receipt["included_candidate_context"]),
                "omitted_count": len(receipt["omitted"]),
            },
        )
        conn.commit()
        return evidence_id, relative_receipt_path
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
        if receipt_path and receipt_path.exists():
            receipt_path.unlink()
        raise DataStoreError(
            f"Could not record context receipt: {exc}",
            details={"contract_version": CONTEXT_RECEIPT_VERSION},
        ) from exc
    finally:
        conn.close()


def _receipt_payload(
    *,
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    impact: dict[str, Any],
    evidence_id: str,
    receipt_path: str,
) -> dict[str, Any]:
    return {
        "contract_version": CONTEXT_RECEIPT_VERSION,
        "created_at": utc_now_iso(),
        "evidence_id": evidence_id,
        "receipt_path": receipt_path,
        "root_path": str(paths.root),
        "source_command": "pcl impact --diff",
        "index_run": impact["index_run"],
        "included_candidate_context": _included_candidate_context(snapshot, impact),
        "omitted": impact["omitted"],
        "sensitive_omitted_count": impact["sensitive_omitted_count"],
        "staleness_warnings": impact["staleness_warnings"],
        "verification_suggestions": impact["verification_suggestions"],
    }


def _included_candidate_context(
    snapshot: IndexSnapshot,
    impact: dict[str, Any],
) -> list[dict[str, Any]]:
    files_by_path = snapshot.files_by_path
    included: list[dict[str, Any]] = []
    for item in impact["changed_files"]:
        if not item["indexed"]:
            continue
        row = files_by_path[str(item["path"])]
        included.append(
            {
                "path": item["path"],
                "role": "changed_file",
                "reason": item["reason"],
                "confidence": 1.0,
                "language": row["language"],
                "sha256": row["sha256"],
            }
        )
    for item in impact["likely_impacted"]:
        row = files_by_path[str(item["path"])]
        included.append(
            {
                "path": item["path"],
                "role": "likely_impacted",
                "reason": item["reason"],
                "confidence": item["confidence"],
                "language": row["language"],
                "sha256": row["sha256"],
            }
        )
    return included


def _retrieved_paths_for_fixture_task(paths: ProjectPaths, task: dict[str, Any]) -> set[str]:
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
        return changed | likely
    query = str(task.get("query") or "").strip()
    if query:
        search = search_code(paths, query=query, limit=int(task.get("limit") or 50))["search"]
        return {str(item["path"]) for item in search["results"]}
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


def _load_diff(paths: ProjectPaths, diff_source: str) -> tuple[str, str]:
    if diff_source.startswith("inline:"):
        return diff_source.removeprefix("inline:"), "fixture:inline"
    if diff_source == GIT_DIFF_SENTINEL:
        return _git_diff(paths.root), "git:diff"
    if diff_source == "-":
        return sys.stdin.read(), "stdin"
    path = Path(diff_source)
    if not path.is_absolute():
        path = paths.root / path
    try:
        return path.read_text(encoding="utf-8"), str(path)
    except OSError as exc:
        raise InvalidInputError(
            f"Could not open diff source: {path}",
            details={"diff_source": str(path)},
        ) from exc


def _inline_diff_source(diff_text: str) -> str:
    return "inline:" + diff_text


def _git_diff(root: Path) -> str:
    commands = [
        ["git", "-C", str(root), "diff", "--name-status", "HEAD", "--"],
        ["git", "-C", str(root), "diff", "--name-status", "--"],
    ]
    for command in commands:
        completed = subprocess.run(command, capture_output=True, check=False, text=True)
        if completed.returncode == 0:
            return completed.stdout
    raise InvalidInputError(
        "Could not obtain git diff for this project. Pass --diff <path> with a synthetic diff file.",
        details={"root": str(root)},
    )


def _parse_changed_files(diff_text: str) -> list[dict[str, str]]:
    by_path: dict[str, str] = {}
    current_old_path = ""
    current_new_path = ""
    pending_source_path = ""
    in_hunk = False
    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("diff --git "):
            parts = stripped.split()
            if len(parts) >= 4:
                current_old_path = _normalize_diff_path(parts[2])
                current_new_path = _normalize_diff_path(parts[3])
                pending_source_path = ""
                in_hunk = False
                path = current_new_path or current_old_path
                if path:
                    by_path.setdefault(path, "M")
            continue
        if stripped.startswith("@@"):
            in_hunk = True
            continue
        if stripped.startswith("rename from "):
            pending_source_path = _normalize_diff_path(stripped.removeprefix("rename from ").strip())
            continue
        if stripped.startswith("rename to "):
            path = _normalize_diff_path(stripped.removeprefix("rename to ").strip())
            if path:
                by_path[path] = "R"
            elif pending_source_path:
                by_path[pending_source_path] = "R"
            pending_source_path = ""
            continue
        if stripped.startswith("copy from "):
            pending_source_path = _normalize_diff_path(stripped.removeprefix("copy from ").strip())
            continue
        if stripped.startswith("copy to "):
            path = _normalize_diff_path(stripped.removeprefix("copy to ").strip())
            if path:
                by_path[path] = "C"
            elif pending_source_path:
                by_path[pending_source_path] = "C"
            pending_source_path = ""
            continue
        if stripped.startswith("new file mode"):
            path = current_new_path or current_old_path
            if path:
                by_path[path] = "A"
            continue
        if stripped.startswith("deleted file mode"):
            path = current_old_path or current_new_path
            if path:
                by_path[path] = "D"
            continue
        if not in_hunk and stripped.startswith("--- "):
            path = _normalize_diff_path(stripped[4:].strip())
            if path:
                by_path.setdefault(path, "M")
                current_old_path = path
            continue
        if not in_hunk and stripped.startswith("+++ "):
            path = _normalize_diff_path(stripped[4:].strip())
            if path:
                by_path[path] = by_path.get(path, "M")
                current_new_path = path
            elif current_old_path:
                by_path[current_old_path] = "D"
            continue
        status_match = re.match(r"^([ACDMRTUXB])\d*\s+(.+)$", stripped)
        if status_match:
            status = status_match.group(1)
            fields = status_match.group(2).split()
            path = _normalize_diff_path(fields[-1]) if fields else ""
            if path:
                by_path[path] = status
            continue
    return [{"path": path, "status": by_path[path]} for path in sorted(by_path)]


def _normalize_diff_path(value: str) -> str:
    path = value.strip().strip('"')
    if path == "/dev/null":
        return ""
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def _git_head(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _gitignored_paths(root: Path, relative_paths: list[str]) -> dict[str, str]:
    if not relative_paths:
        return {}
    input_text = "\0".join(relative_paths) + "\0"
    completed = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--verbose", "-z", "--stdin"],
        capture_output=True,
        check=False,
        input=input_text,
        text=True,
    )
    if completed.returncode in {0, 1}:
        return _parse_git_check_ignore_output(completed.stdout)
    return _fallback_gitignore_matches(root, relative_paths)


def _parse_git_check_ignore_output(output: str) -> dict[str, str]:
    ignored: dict[str, str] = {}
    parts = [part for part in output.split("\0") if part]
    for index in range(0, len(parts) - 3, 4):
        source, line_number, pattern, path = parts[index : index + 4]
        ignored[path] = f"gitignore:{source}:{line_number}:{pattern}"
    return ignored


def _fallback_gitignore_matches(root: Path, relative_paths: list[str]) -> dict[str, str]:
    patterns = _root_gitignore_patterns(root)
    ignored: dict[str, str] = {}
    for path in relative_paths:
        for pattern in patterns:
            if _gitignore_pattern_matches(pattern, path):
                ignored[path] = f"gitignore:{pattern}"
                break
    return ignored


def _root_gitignore_patterns(root: Path) -> list[str]:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return []
    patterns: list[str] = []
    for raw_line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        patterns.append(line)
    return patterns


def _gitignore_pattern_matches(pattern: str, path: str) -> bool:
    normalized = pattern.strip("/")
    if not normalized:
        return False
    if pattern.endswith("/"):
        return path == normalized or path.startswith(normalized + "/")
    if "/" not in normalized:
        return any(part == normalized or fnmatch.fnmatch(part, normalized) for part in path.split("/"))
    return fnmatch.fnmatch(path, normalized)


def _default_ignore_reason(relative_path: str) -> str | None:
    for part in relative_path.split("/"):
        reason = DEFAULT_IGNORED_NAMES.get(part)
        if reason:
            return reason
    return None


def _code_index_exclude_patterns(root: Path) -> list[tuple[str, str]]:
    configured = _configured_yaml_list(root, "code_index", "exclude")
    if configured is None:
        return [
            (pattern, f"default_code_index_exclude:{pattern}")
            for pattern in DEFAULT_CODE_INDEX_EXCLUDES
        ]
    return [(pattern, f"code_index.exclude:{pattern}") for pattern in configured]


def _sensitive_index_settings(root: Path) -> SensitiveIndexSettings:
    additional = _configured_yaml_list(root, "code_index", "sensitive_exclude") or []
    agent_may_not_modify = _configured_yaml_list(root, "permissions", "agent_may_not_modify") or []
    include_override = _configured_yaml_list(root, "code_index", "sensitive_include_override") or []
    return SensitiveIndexSettings(
        additional_patterns=tuple(additional),
        agent_may_not_modify_patterns=tuple(agent_may_not_modify),
        include_override_patterns=tuple(include_override),
    )


def _sensitive_ignore_reason(relative_path: str, settings: SensitiveIndexSettings) -> str | None:
    if _matches_any_pattern(relative_path, settings.include_override_patterns):
        return None
    if _matches_any_pattern(relative_path, settings.agent_may_not_modify_patterns):
        return "sensitive:agent_may_not_modify"
    for pattern in (*DEFAULT_SENSITIVE_EXCLUDES, *settings.additional_patterns):
        if _path_pattern_matches(pattern, relative_path):
            return f"sensitive:{pattern}"
    return None


def _sensitive_override_warning(patterns: tuple[str, ...]) -> str:
    joined = ", ".join(patterns)
    return (
        "WARNING: code_index.sensitive_include_override is configured; "
        f"sensitive paths matching these patterns may be indexed: {joined}"
    )


def _safe_snapshot_files(root: Path, snapshot: IndexSnapshot) -> list[dict[str, Any]]:
    settings = _sensitive_index_settings(root)
    return [
        item
        for item in snapshot.files
        if not _sensitive_ignore_reason(str(item["path"]), settings)
    ]


def _safe_snapshot_files_by_path(root: Path, snapshot: IndexSnapshot) -> dict[str, dict[str, Any]]:
    return {str(item["path"]): item for item in _safe_snapshot_files(root, snapshot)}


def _summary_sensitive_omitted_count(summary: dict[str, Any]) -> int:
    value = summary.get("sensitive_omitted_count")
    if isinstance(value, int):
        return value
    ignored = summary.get("ignored", [])
    if not isinstance(ignored, list):
        return 0
    return sum(
        1
        for item in ignored
        if isinstance(item, dict)
        and str(item.get("ignored_reason", "")).startswith("sensitive:")
    )


def _configured_yaml_list(root: Path, section: str, key: str) -> list[str] | None:
    config_path = root / "pcl.yaml"
    if not config_path.exists():
        return None
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    in_section = False
    in_list = False
    section_indent = 0
    list_indent = 0
    values: list[str] = []
    saw_key = False
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if indent == 0 and stripped.startswith(f"{section}:"):
            in_section = True
            in_list = False
            section_indent = indent
            continue
        if in_section and indent <= section_indent and not stripped.startswith("-"):
            break
        if not in_section:
            continue
        if stripped.startswith(f"{key}:"):
            saw_key = True
            in_list = True
            list_indent = indent
            raw_value = stripped.split(":", 1)[1].strip()
            if raw_value:
                inline = _parse_inline_yaml_list(raw_value)
                if inline is not None:
                    values.extend(inline)
                    in_list = False
                else:
                    value = _strip_yaml_string(raw_value)
                    if value:
                        values.append(value)
            continue
        if in_list:
            if indent <= list_indent and not stripped.startswith("-"):
                in_list = False
                continue
            if stripped.startswith("-"):
                value = _strip_yaml_string(stripped[1:].strip())
                if value:
                    values.append(value)
    if not saw_key:
        return None
    return _unique_nonempty(values)


def _parse_inline_yaml_list(value: str) -> list[str] | None:
    stripped = value.strip()
    if stripped == "[]":
        return []
    if not stripped.startswith("[") or not stripped.endswith("]"):
        return None
    inner = stripped[1:-1].strip()
    if not inner:
        return []
    return [_strip_yaml_string(part.strip()) for part in inner.split(",") if _strip_yaml_string(part.strip())]


def _strip_yaml_string(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _unique_nonempty(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _configured_ignore_reason(relative_path: str, patterns: list[tuple[str, str]]) -> str | None:
    for pattern, reason in patterns:
        if _path_pattern_matches(pattern, relative_path):
            return reason
    return None


def _matches_any_pattern(relative_path: str, patterns: tuple[str, ...]) -> bool:
    return any(_path_pattern_matches(pattern, relative_path) for pattern in patterns)


def _path_pattern_matches(pattern: str, relative_path: str) -> bool:
    normalized_path = relative_path.strip("/")
    normalized_pattern = pattern.strip()
    if not normalized_path or not normalized_pattern:
        return False
    pattern_without_slashes = normalized_pattern.strip("/")
    if not pattern_without_slashes:
        return False
    if normalized_pattern.endswith("/"):
        return normalized_path == pattern_without_slashes or normalized_path.startswith(
            pattern_without_slashes + "/"
        )
    if "/" not in pattern_without_slashes:
        return any(
            fnmatch.fnmatch(part, pattern_without_slashes)
            for part in normalized_path.split("/")
        )
    return fnmatch.fnmatch(normalized_path, pattern_without_slashes)


def _detect_language(path: Path) -> str:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "text")


def _looks_binary(sample: bytes) -> bool:
    if b"\0" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _symbol_summary(path: str, text: str) -> dict[str, Any]:
    language = _detect_language(Path(path))
    if language == "python":
        symbols = _python_symbols(text)
    elif language in {"javascript", "typescript"}:
        symbols = _javascript_symbols(text)
    elif language == "markdown":
        symbols = _markdown_symbols(text)
    else:
        symbols = []
    return {"contract_version": SYMBOL_SUMMARY_VERSION, "symbols": symbols}


def _empty_symbol_summary() -> dict[str, Any]:
    return {"contract_version": SYMBOL_SUMMARY_VERSION, "symbols": []}


def _python_symbols(text: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        function_match = PYTHON_DEF_RE.match(line)
        if function_match:
            symbols.append(
                {
                    "type": "function",
                    "name": function_match.group(1),
                    "line": line_number,
                    "reason": "python_def",
                }
            )
            continue
        class_match = PYTHON_CLASS_RE.match(line)
        if class_match:
            symbols.append(
                {
                    "type": "class",
                    "name": class_match.group(1),
                    "line": line_number,
                    "reason": "python_class",
                }
            )
    return symbols


def _javascript_symbols(text: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for symbol_type, pattern, reason in [
            ("function", JS_FUNCTION_RE, "js_function"),
            ("class", JS_CLASS_RE, "js_class"),
            ("export", JS_EXPORT_BINDING_RE, "js_export_binding"),
        ]:
            match = pattern.match(line)
            if match:
                symbols.append(
                    {
                        "type": symbol_type,
                        "name": match.group(1),
                        "line": line_number,
                        "reason": reason,
                    }
                )
                break
        export_list = JS_EXPORT_LIST_RE.match(line)
        if export_list:
            for raw_name in export_list.group(1).split(","):
                name = raw_name.strip().split(" as ", 1)[0].strip()
                if name:
                    symbols.append(
                        {
                            "type": "export",
                            "name": name,
                            "line": line_number,
                            "reason": "js_export_list",
                        }
                    )
    return symbols


def _markdown_symbols(text: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = MD_HEADING_RE.match(line)
        if match:
            symbols.append(
                {
                    "type": "heading",
                    "name": match.group(2).strip(),
                    "level": len(match.group(1)),
                    "line": line_number,
                    "reason": "markdown_heading",
                }
            )
    return symbols


def _empty_test_hint(path: str) -> dict[str, Any]:
    return {
        "contract_version": TEST_HINT_VERSION,
        "is_test": _is_test_path(path),
        "candidate_tests": [],
    }


def _test_hint_for_file(item: IndexedFile, files: list[IndexedFile]) -> dict[str, Any]:
    hint = _empty_test_hint(item.path)
    if hint["is_test"]:
        return hint
    candidates: dict[str, dict[str, Any]] = {}
    source_stem = _stem_key(item.path)
    for possible_test in files:
        if not _is_test_path(possible_test.path):
            continue
        reasons: list[str] = []
        confidence = 0.0
        if _stem_key(possible_test.path) == source_stem:
            reasons.append("filename_match")
            confidence = max(confidence, 0.72)
        if item.language == "python":
            import_reasons = _python_test_import_reasons(possible_test.text, possible_test.path, item)
            if import_reasons:
                reasons.extend(import_reasons)
                confidence = max(confidence, 0.88 if "python_import" in import_reasons else 0.76)
        if reasons:
            candidates[possible_test.path] = {
                "path": possible_test.path,
                "reason": "+".join(sorted(reasons)),
                "confidence": confidence,
            }
    hint["candidate_tests"] = [candidates[path] for path in sorted(candidates)]
    return hint


def _python_test_import_reasons(test_text: str, test_path: str, source: IndexedFile) -> list[str]:
    module = _python_module_name(source.path)
    if not module:
        return []
    imported = _python_imported_modules(test_text)
    reasons: list[str] = []
    if any(imported_module == module or imported_module.startswith(module + ".") for imported_module in imported):
        reasons.append("python_import")
    if (
        "python_import" not in reasons
        and module.startswith("pcl.")
        and "pcl.cli" in imported
        and _test_path_matches_source_surface(test_path, source)
    ):
        reasons.append("python_import:pcl_cli_surface")
    return reasons


def _python_imported_modules(test_text: str) -> set[str]:
    try:
        tree = ast.parse(test_text)
    except SyntaxError:
        return set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
                for alias in node.names:
                    imported.add(f"{node.module}.{alias.name}")
            else:
                for alias in node.names:
                    imported.add(alias.name)
    return imported


def _test_path_matches_source_surface(test_path: str, source: IndexedFile) -> bool:
    test_tokens = _identifier_tokens(Path(test_path).stem)
    source_tokens = _identifier_tokens(Path(source.path).stem)
    for symbol_name in _symbol_names(source.to_public_dict()):
        source_tokens.update(_identifier_tokens(symbol_name))
    source_tokens.discard("test")
    test_tokens.discard("test")
    return bool(test_tokens & source_tokens)


def _test_path_matches_changed_path(test_path: str, changed_path: str) -> bool:
    if not _is_test_path(test_path):
        return False
    test_tokens = _identifier_tokens(Path(test_path).stem)
    changed_tokens: set[str] = set()
    for part in Path(changed_path).parts:
        changed_tokens.update(_identifier_tokens(Path(part).stem))
    for noisy in {"src", "pcl", "test", "tests", "py"}:
        test_tokens.discard(noisy)
        changed_tokens.discard(noisy)
    return bool(test_tokens and changed_tokens and test_tokens & changed_tokens)


def _python_module_name(path: str) -> str:
    if not path.endswith(".py"):
        return ""
    without_suffix = path[:-3]
    if without_suffix.startswith("src/"):
        without_suffix = without_suffix[4:]
    if without_suffix.endswith("/__init__"):
        without_suffix = without_suffix[: -len("/__init__")]
    return without_suffix.replace("/", ".")


def _is_test_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return (
        "tests" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def _stem_key(path: str) -> str:
    name = Path(path).name
    for suffix in [".test", ".spec"]:
        if suffix in name:
            name = name.split(suffix, 1)[0]
    stem = Path(name).stem
    if stem.startswith("test_"):
        stem = stem[5:]
    if stem.endswith("_test"):
        stem = stem[:-5]
    return stem


def _identifier_tokens(value: str) -> set[str]:
    tokens = {
        token.casefold()
        for token in re.split(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])", value)
        if token
    }
    expanded: set[str] = set(tokens)
    if "renderer" in expanded:
        expanded.add("dashboard")
        expanded.add("render")
    return expanded


def _symbol_names(row: dict[str, Any]) -> list[str]:
    summary = row.get("symbol_summary") if isinstance(row.get("symbol_summary"), dict) else {}
    symbols = summary.get("symbols") if isinstance(summary.get("symbols"), list) else []
    names: list[str] = []
    for symbol in symbols:
        if isinstance(symbol, dict):
            name = str(symbol.get("name") or "")
            if len(name) >= 3 and name not in names:
                names.append(name)
    return names


def _file_mentions(path: Path, symbol_name: str) -> bool:
    try:
        return symbol_name in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


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


def _search_score(*, path: str, lines: list[str], terms: list[str]) -> tuple[int, list[str]]:
    score = 0
    reason_parts = ["file contains all query terms"]
    best_line_score = 0
    has_all_terms_on_line = False
    has_definition_hit = False
    for line in lines:
        line_score = _line_search_score(line, terms)
        best_line_score = max(best_line_score, line_score)
        folded = line.casefold()
        if all(term in folded for term in terms):
            has_all_terms_on_line = True
        if (
            not _is_test_path(path)
            and _is_definition_like_line(line)
            and any(term in _search_normalized(line) for term in terms)
        ):
            has_definition_hit = True
    score += best_line_score
    if has_all_terms_on_line:
        score += 25
        reason_parts.append("one line contains all query terms")
    if has_definition_hit:
        score += 60
        reason_parts.append("definition-like hit")
    if path.startswith("src/"):
        score += 18
        reason_parts.append("source file")
    elif path.endswith(".py") and _is_test_path(path):
        score += 14
        reason_parts.append("test file")
    elif path.startswith("docs/") or path.startswith("agent-tasks/") or path.endswith(".md"):
        score -= 6
        reason_parts.append("prose file")
    score += sum(_search_normalized(Path(path).stem).count(term) for term in terms) * 4
    return score, reason_parts


def _search_result_lines(lines: list[str], terms: list[str]) -> tuple[list[int], str]:
    scored: list[tuple[int, int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        score = _line_search_score(line, terms)
        if score > 0:
            scored.append((-score, line_number, line))
    if not scored:
        return [], ""
    best = sorted(scored)[:3]
    line_numbers = sorted(line_number for _, line_number, _ in best)
    return line_numbers, _snippet(best[0][2])


def _line_search_score(line: str, terms: list[str]) -> int:
    normalized = _search_normalized(line)
    score = 0
    matched_terms = 0
    for term in terms:
        count = normalized.count(term)
        if count:
            matched_terms += 1
            score += min(count, 2) * 6
    if matched_terms == len(terms):
        score += 30
    if _is_definition_like_line(line):
        score += 20
    return score


def _search_normalized(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").casefold()


def _is_definition_like_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if PYTHON_DEF_RE.match(stripped) or PYTHON_CLASS_RE.match(stripped):
        return True
    if JS_FUNCTION_RE.match(stripped) or JS_CLASS_RE.match(stripped) or JS_EXPORT_BINDING_RE.match(stripped):
        return True
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", stripped))


def _search_payload(*, query: str, limit: int, results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "search": {
            "contract_version": CODE_SEARCH_VERSION,
            "query": query,
            "limit": limit,
            "result_count": len(results),
            "results": results,
        },
    }


def _snippet(line: str) -> str:
    text = line.strip()
    if len(text) <= SEARCH_SNIPPET_CHARS:
        return text
    return text[: SEARCH_SNIPPET_CHARS - 1].rstrip() + "…"


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _next_numeric_suffix(conn: sqlite3.Connection, table: str, prefix: str) -> int:
    rows = conn.execute(f"SELECT id FROM {table} WHERE id LIKE ?", (f"{prefix}-%",)).fetchall()
    max_number = 0
    for row in rows:
        match = ID_NUMBER_RE.match(str(row["id"]))
        if match:
            max_number = max(max_number, int(match.group(1)))
    return max_number + 1


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str) and item.strip()}


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0 if numerator == 0 else 0.0
    return round(numerator / denominator, 4)
