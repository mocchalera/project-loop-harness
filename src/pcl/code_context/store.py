from __future__ import annotations

from dataclasses import dataclass
import json
from json import JSONDecodeError
import re
import sqlite3
from typing import Any

from .diff import _git_head
from .scan import INDEX_VERSION, LARGE_FILE_BYTES, ScanResult
from .scan import _scan_working_tree
from .test_hints import _attach_test_hints
from ..db import connect, table_exists
from ..errors import DataStoreError, InvalidInputError
from ..events import append_event
from ..guards import require_initialized
from ..ids import next_prefixed_id
from ..paths import ProjectPaths
from ..timeutil import utc_now_iso


ID_NUMBER_RE = re.compile(r"^[A-Z]+-(\d+)$")


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


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _next_numeric_suffix(conn: sqlite3.Connection, table: str, prefix: str) -> int:
    rows = conn.execute(f"SELECT id FROM {table} WHERE id LIKE ?", (f"{prefix}-%",)).fetchall()
    max_number = 0
    for row in rows:
        match = ID_NUMBER_RE.match(str(row["id"]))
        if match:
            max_number = max(max_number, int(match.group(1)))
    return max_number + 1
