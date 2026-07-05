from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .scan import _sensitive_ignore_reason, _sensitive_index_settings
from .store import (
    IndexSnapshot,
    _git_head_snapshot_warning,
    _load_required_snapshot,
    _search_staleness_summary,
    _snapshot_consistency_for_path,
)
from .symbols import JS_CLASS_RE, JS_EXPORT_BINDING_RE, JS_FUNCTION_RE, PYTHON_CLASS_RE, PYTHON_DEF_RE
from .test_hints import _is_test_path
from ..errors import InvalidInputError
from ..guards import require_initialized
from ..paths import ProjectPaths


CODE_SEARCH_VERSION = "code-search/v0"


SEARCH_SNIPPET_CHARS = 220


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
    for item in _searchable_snapshot_items(snapshot):
        path = str(item["path"])
        if _sensitive_ignore_reason(path, sensitive_settings):
            continue
        absolute_path = paths.root / path
        searched_index_metadata = False
        try:
            lines = absolute_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            lines = _indexed_metadata_lines(item)
            searched_index_metadata = True
        if not lines:
            continue
        text = _search_normalized("\n".join(lines))
        if not all(term in text for term in terms):
            continue
        score, reason_parts = _search_score(path=path, lines=lines, terms=terms)
        if searched_index_metadata:
            score -= 12
            reason_parts = ["index metadata contains all query terms"]
            if not absolute_path.exists():
                reason_parts.append("file missing from working tree")
            result_lines = []
            snippet = _snippet(" | ".join(lines))
        else:
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
    for result in results:
        result.update(_snapshot_consistency_for_path(paths, snapshot, str(result["path"])))
    return _search_payload(
        paths=paths,
        snapshot=snapshot,
        query=query,
        limit=limit,
        results=results,
    )


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


def _search_payload(
    *,
    paths: ProjectPaths,
    snapshot: IndexSnapshot,
    query: str,
    limit: int,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "ok": True,
        "search": {
            "contract_version": CODE_SEARCH_VERSION,
            "query": query,
            "limit": limit,
            "result_count": len(results),
            "results": results,
            "staleness_warnings": _search_staleness_summary(results),
            "git_head_warning": _git_head_snapshot_warning(paths, snapshot),
        },
    }


def _snippet(line: str) -> str:
    text = line.strip()
    if len(text) <= SEARCH_SNIPPET_CHARS:
        return text
    return text[: SEARCH_SNIPPET_CHARS - 1].rstrip() + "…"


def _searchable_snapshot_items(snapshot: IndexSnapshot) -> list[dict[str, Any]]:
    items = [dict(item) for item in snapshot.files]
    indexed_paths = {str(item["path"]) for item in items}
    for path, item in sorted(snapshot.hash_skipped_by_path.items()):
        if path not in indexed_paths:
            items.append(
                {
                    "path": path,
                    "language": None,
                    "sha256": None,
                    "hash_skipped_reason": item.get("hash_skipped_reason") or item.get("ignored_reason"),
                    "symbol_summary": {"symbols": []},
                    "test_hint": {},
                }
            )
    return sorted(items, key=lambda item: str(item["path"]))


def _indexed_metadata_lines(item: dict[str, Any]) -> list[str]:
    path = str(item.get("path") or "")
    lines = [path]
    symbol_summary = item.get("symbol_summary")
    if isinstance(symbol_summary, dict):
        symbols = symbol_summary.get("symbols")
        if isinstance(symbols, list):
            names = [
                str(symbol.get("name"))
                for symbol in symbols
                if isinstance(symbol, dict) and symbol.get("name")
            ]
            if names:
                lines.append("symbols: " + " ".join(names))
    hash_skipped_reason = item.get("hash_skipped_reason")
    if hash_skipped_reason:
        lines.append("hash_skipped_reason: " + str(hash_skipped_reason))
    return lines
