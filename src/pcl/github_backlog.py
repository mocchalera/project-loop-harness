"""Deterministic, read-only GitHub backlog projection.

Renders issue-ready Markdown/JSON from repo-verifiable anchors declared in a
committed mapping file, with optional read-only enrichment from local PCL
state. PCL state and accepted task/Evidence records remain authoritative;
GitHub Issues are a contributor-facing projection. This module never mutates
project state, never appends events, and never touches the network.

Fail-closed contract: missing anchors, duplicate mappings, unresolvable PCL
entity references, and stale-status contradictions are reported as
error-severity findings, the command exits non-zero, and no artifact is
written. State that is simply unavailable (no local ``project.db``) is
labeled honestly instead of invented.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import sqlite3
import sys
from typing import Any

from .db import connect
from .errors import InvalidInputError, PclError

PROJECTION_SCHEMA = "github-backlog-projection/v0"
ISSUE_MAP_SCHEMA = "github-issue-map/v0"

ISSUE_MAP_REQUIRED_ENTRY_KEYS = frozenset(
    {"issue", "priority", "lifecycle", "depends_on", "anchors"}
)
ISSUE_MAP_OPTIONAL_ENTRY_KEYS = frozenset(
    {
        "title_hint",
        "owner_boundary",
        "acceptance_criteria_refs",
        "pcl_entities",
    }
)
ANCHOR_KINDS = ("agent_task_ids", "repo_paths")
LIFECYCLES = ("active", "completed")
PRIORITIES = ("P0", "P1", "P2", "P3")

CONTRADICTING_TASK_STATUSES = frozenset({"cancelled", "waived", "closed"})
EVIDENCE_SUPERSEDES_ROLE = "supersedes"
EVIDENCE_SUPERSEDES_TARGET = "evidence"

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_PRIORITY_ORDER = {name: rank for rank, name in enumerate(PRIORITIES)}

_REFRESH_COMMAND = (
    "PYTHONPATH=src python scripts/render_github_backlog.py "
    "--root . --format markdown"
)


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    issue: int | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if issue is not None:
        finding["issue"] = issue
    if detail:
        finding["detail"] = detail
    return finding


def _require_str_list(value: Any, field: str, issue: int | None) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InvalidInputError(
            f"Mapping field {field} must be a list of strings",
            details={"issue": issue, "field": field},
        )
    return list(value)


def load_issue_map(path: Path | str) -> dict[str, Any]:
    """Load and structurally validate the committed GitHub issue map."""
    map_path = Path(path)
    try:
        raw = map_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidInputError(
            f"Could not read issue map: {map_path}", details={"error": str(exc)}
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidInputError(
            f"Issue map is not valid JSON: {map_path}", details={"error": str(exc)}
        ) from exc
    if not isinstance(payload, dict):
        raise InvalidInputError("Issue map root must be an object", details={})
    if payload.get("schema") != ISSUE_MAP_SCHEMA:
        raise InvalidInputError(
            f"Issue map schema must be {ISSUE_MAP_SCHEMA}",
            details={"found": payload.get("schema")},
        )
    for key in ("repository", "policy"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise InvalidInputError(
                f"Issue map field {key} must be a non-empty string", details={}
            )
    issues = payload.get("issues")
    if not isinstance(issues, list) or not issues:
        raise InvalidInputError("Issue map field issues must be a non-empty list", details={})
    normalized: list[dict[str, Any]] = []
    for entry in issues:
        if not isinstance(entry, dict):
            raise InvalidInputError("Each issue map entry must be an object", details={})
        unknown = set(entry) - ISSUE_MAP_REQUIRED_ENTRY_KEYS - ISSUE_MAP_OPTIONAL_ENTRY_KEYS
        if unknown:
            raise InvalidInputError(
                "Issue map entry has unknown fields (typo?)",
                details={"unknown": sorted(unknown)},
            )
        missing = ISSUE_MAP_REQUIRED_ENTRY_KEYS - set(entry)
        if missing:
            raise InvalidInputError(
                "Issue map entry is missing required fields",
                details={"missing": sorted(missing)},
            )
        number = entry["issue"]
        if not isinstance(number, int) or isinstance(number, bool):
            raise InvalidInputError("Issue map field issue must be an integer", details={})
        if entry["priority"] not in PRIORITIES:
            raise InvalidInputError(
                f"Issue map priority must be one of {', '.join(PRIORITIES)}",
                details={"issue": number, "found": entry["priority"]},
            )
        if entry["lifecycle"] not in LIFECYCLES:
            raise InvalidInputError(
                f"Issue map lifecycle must be one of {', '.join(LIFECYCLES)}",
                details={"issue": number, "found": entry["lifecycle"]},
            )
        depends_on = _require_str_list(entry["depends_on"], "depends_on", number)
        if not all(dep.isdigit() for dep in depends_on):
            raise InvalidInputError(
                "Issue map depends_on entries must be numeric issue numbers as strings",
                details={"issue": number},
            )
        anchors_field = entry["anchors"]
        if not isinstance(anchors_field, dict) or not anchors_field:
            raise InvalidInputError(
                "Issue map anchors must be a non-empty object",
                details={"issue": number},
            )
        unknown_kinds = set(anchors_field) - set(ANCHOR_KINDS)
        if unknown_kinds:
            raise InvalidInputError(
                f"Issue map anchor kinds must be among {', '.join(ANCHOR_KINDS)}",
                details={"issue": number, "unknown": sorted(unknown_kinds)},
            )
        anchors: dict[str, list[str]] = {}
        total_refs = 0
        for kind in ANCHOR_KINDS:
            refs_list = _require_str_list(
                anchors_field.get(kind, []), f"anchors.{kind}", number
            )
            if not all(ref.strip() for ref in refs_list):
                raise InvalidInputError(
                    f"Issue map anchor list {kind} contains empty references",
                    details={"issue": number},
                )
            total_refs += len(refs_list)
            anchors[kind] = refs_list
        if total_refs == 0:
            raise InvalidInputError(
                "Issue map entry must declare at least one anchor",
                details={"issue": number},
            )
        normalized_entry: dict[str, Any] = {
            "issue": number,
            "priority": entry["priority"],
            "lifecycle": entry["lifecycle"],
            "depends_on": [int(dep) for dep in depends_on],
            "anchors": anchors,
        }
        if "title_hint" in entry:
            normalized_entry["title_hint"] = str(entry["title_hint"])
        if "owner_boundary" in entry:
            normalized_entry["owner_boundary"] = str(entry["owner_boundary"])
        if "acceptance_criteria_refs" in entry:
            normalized_entry["acceptance_criteria_refs"] = _require_str_list(
                entry["acceptance_criteria_refs"], "acceptance_criteria_refs", number
            )
        if "pcl_entities" in entry:
            entities = entry["pcl_entities"]
            if not isinstance(entities, dict):
                raise InvalidInputError(
                    "Issue map pcl_entities must be an object",
                    details={"issue": number},
                )
            pcl: dict[str, list[str]] = {}
            for kind in ("goals", "tasks"):
                values = entities.get(kind, [])
                pcl[kind] = _require_str_list(values, f"pcl_entities.{kind}", number)
            unknown_entity_kinds = set(entities) - {"goals", "tasks"}
            if unknown_entity_kinds:
                raise InvalidInputError(
                    "Issue map pcl_entities supports only goals and tasks",
                    details={"issue": number, "unknown": sorted(unknown_entity_kinds)},
                )
            normalized_entry["pcl_entities"] = pcl
        normalized.append(normalized_entry)
    return {
        "schema": ISSUE_MAP_SCHEMA,
        "repository": payload["repository"],
        "policy": payload["policy"],
        "issues": normalized,
    }


def _resolve_anchors(
    root: Path, entry: dict[str, Any], findings: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    resolved: dict[str, list[dict[str, Any]]] = {}
    number = entry["issue"]
    agent_task_refs = entry["anchors"].get("agent_task_ids", [])
    repo_path_refs = entry["anchors"].get("repo_paths", [])
    task_rows: list[dict[str, Any]] = []
    if agent_task_refs:
        tasks_dir = root / "agent-tasks"
        for ref in agent_task_refs:
            matches = sorted(tasks_dir.glob(f"{ref}-*.md"))
            if len(matches) == 0:
                findings.append(
                    _finding(
                        "anchor_missing",
                        "error",
                        f"agent-tasks spec for #{number} does not exist: {ref}",
                        issue=number,
                        detail={"kind": "agent_task_ids", "ref": ref},
                    )
                )
                task_rows.append({"ref": ref, "path": None})
            elif len(matches) > 1:
                findings.append(
                    _finding(
                        "anchor_ambiguous",
                        "error",
                        f"agent-tasks spec reference for #{number} matches multiple files: {ref}",
                        issue=number,
                        detail={
                            "kind": "agent_task_ids",
                            "ref": ref,
                            "matches": [str(m.relative_to(root)) for m in matches],
                        },
                    )
                )
                task_rows.append({"ref": ref, "path": None})
            else:
                task_rows.append({"ref": ref, "path": matches[0].relative_to(root).as_posix()})
    doc_rows: list[dict[str, Any]] = []
    for ref in repo_path_refs:
        candidate = Path(ref)
        if candidate.is_absolute() or ".." in candidate.parts:
            findings.append(
                _finding(
                    "invalid_anchor_path",
                    "error",
                    f"repo path anchor for #{number} must be a relative path inside the repository: {ref}",
                    issue=number,
                    detail={"kind": "repo_paths", "ref": ref},
                )
            )
            doc_rows.append({"ref": ref, "path": None})
            continue
        if (root / candidate).is_file():
            doc_rows.append({"ref": ref, "path": candidate.as_posix()})
        else:
            findings.append(
                _finding(
                    "anchor_missing",
                    "error",
                    f"repo path anchor for #{number} does not exist: {ref}",
                    issue=number,
                    detail={"kind": "repo_paths", "ref": ref},
                )
            )
            doc_rows.append({"ref": ref, "path": None})
    resolved["agent_task_ids"] = task_rows
    resolved["repo_paths"] = doc_rows
    return resolved


def _task_evidence(
    conn: sqlite3.Connection, task_id: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT e.id, e.type, e.path, e.summary, e.created_at
        FROM evidence_links el
        JOIN evidence e ON e.id = el.evidence_id
        WHERE el.target_type = 'task' AND el.target_id = ?
        ORDER BY e.created_at, e.id
        """,
        (task_id,),
    ).fetchall()
    superseded_by: dict[str, str] = {}
    for row in rows:
        replacement = conn.execute(
            """
            SELECT evidence_id FROM evidence_links
            WHERE target_type = ? AND target_id = ? AND link_role = ?
            LIMIT 1
            """,
            (EVIDENCE_SUPERSEDES_TARGET, row["id"], EVIDENCE_SUPERSEDES_ROLE),
        ).fetchone()
        if replacement is not None:
            superseded_by[str(row["id"])] = str(replacement["evidence_id"])

    def _row_dict(row: sqlite3.Row, *, superseded_by_value: str | None) -> dict[str, Any]:
        payload = {
            "id": str(row["id"]),
            "type": str(row["type"]),
            "path": None if row["path"] is None else str(row["path"]),
            "summary": None if row["summary"] is None else str(row["summary"]),
            "created_at": str(row["created_at"]),
        }
        if superseded_by_value is not None:
            payload["superseded_by"] = superseded_by_value
        return payload

    authoritative: dict[str, Any] | None = None
    superseded: list[dict[str, Any]] = []
    for row in rows:
        evidence_id = str(row["id"])
        if evidence_id in superseded_by:
            superseded.append(_row_dict(row, superseded_by_value=superseded_by[evidence_id]))
        else:
            candidate = _row_dict(row, superseded_by_value=None)
            if (
                authoritative is None
                or (candidate["created_at"], candidate["id"])
                > (authoritative["created_at"], authoritative["id"])
            ):
                authoritative = candidate
    return authoritative, superseded


def _enrich_from_pcl_state(
    conn: sqlite3.Connection,
    entry: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    number = entry["issue"]
    entities = entry.get("pcl_entities", {"goals": [], "tasks": []})
    goals: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []

    for goal_id in entities.get("goals", []):
        row = conn.execute(
            "SELECT id, title, status, updated_at FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if row is None:
            findings.append(
                _finding(
                    "pcl_entity_missing",
                    "error",
                    f"PCL goal referenced by #{number} does not exist: {goal_id}",
                    issue=number,
                    detail={"kind": "goal", "id": goal_id},
                )
            )
            continue
        goals.append(
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "updated_at": str(row["updated_at"]),
            }
        )

    dependency_edges: set[tuple[str, str]] = set()
    referenced_task_ids: list[str] = []
    for task_id in entities.get("tasks", []):
        row = conn.execute(
            """
            SELECT id, title, status, priority, owner, updated_at
            FROM tasks WHERE id = ?
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            findings.append(
                _finding(
                    "pcl_entity_missing",
                    "error",
                    f"PCL task referenced by #{number} does not exist: {task_id}",
                    issue=number,
                    detail={"kind": "task", "id": task_id},
                )
            )
            continue
        referenced_task_ids.append(task_id)
        for edge in conn.execute(
            """
            SELECT task_id, depends_on_task_id FROM task_dependencies
            WHERE task_id = ? OR depends_on_task_id = ?
            ORDER BY task_id, depends_on_task_id
            """,
            (task_id, task_id),
        ):
            dependency_edges.add((str(edge["task_id"]), str(edge["depends_on_task_id"])))
        last_evidence, superseded = _task_evidence(conn, task_id)
        for stale_row in superseded:
            findings.append(
                _finding(
                    "evidence_superseded",
                    "info",
                    (
                        f"Evidence {stale_row['id']} for task {task_id} "
                        f"(#{number}) was superseded by {stale_row['superseded_by']}"
                    ),
                    issue=number,
                    detail={"evidence_id": stale_row["id"], "task_id": task_id},
                )
            )
        tasks.append(
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "priority": int(row["priority"]),
                "owner": None if row["owner"] is None else str(row["owner"]),
                "updated_at": str(row["updated_at"]),
                "last_authoritative_evidence": last_evidence,
                "superseded_evidence": superseded,
            }
        )

    dependencies = [
        {"task_id": task_id, "depends_on_task_id": depends_on}
        for task_id, depends_on in sorted(dependency_edges)
    ]
    return {
        "available": True,
        "goals": goals,
        "tasks": tasks,
        "pcl_task_dependencies": dependencies,
    }


def build_projection(root: Path | str, mapping: dict[str, Any]) -> dict[str, Any]:
    """Build the projection payload from a loaded mapping. Read-only."""
    project_root = Path(root).resolve()
    findings: list[dict[str, Any]] = []
    entries = mapping["issues"]

    numbers = Counter(entry["issue"] for entry in entries)
    for duplicated_number, count in sorted(numbers.items()):
        if count > 1:
            findings.append(
                _finding(
                    "duplicate_issue_number",
                    "error",
                    f"GitHub issue #{duplicated_number} is mapped {count} times",
                    issue=duplicated_number,
                )
            )

    anchor_owners: dict[tuple[str, str], list[int]] = {}
    for entry in entries:
        for kind, refs in entry["anchors"].items():
            for ref in refs:
                anchor_owners.setdefault((kind, ref), []).append(entry["issue"])
    for (kind, ref), owners in sorted(anchor_owners.items()):
        if len(owners) > 1:
            findings.append(
                _finding(
                    "duplicate_anchor",
                    "error",
                    (
                        f"Anchor {kind}:{ref} is claimed by multiple issues: "
                        + ", ".join(f"#{n}" for n in sorted(owners))
                    ),
                    detail={"kind": kind, "ref": ref, "issues": sorted(owners)},
                )
            )

    db_path = project_root / ".project-loop" / "project.db"
    db_available = db_path.is_file()
    conn: sqlite3.Connection | None = None
    if db_available:
        conn = connect(db_path)

    items: list[dict[str, Any]] = []
    try:
        for entry in entries:
            number = entry["issue"]
            anchors = _resolve_anchors(project_root, entry, findings)
            pcl_block: dict[str, Any]
            declares_entities = bool(entry.get("pcl_entities"))
            if conn is not None:
                pcl_block = _enrich_from_pcl_state(conn, entry, findings)
            else:
                pcl_block = {"available": False, "goals": [], "tasks": [], "pcl_task_dependencies": []}
                if declares_entities:
                    findings.append(
                        _finding(
                            "state_unavailable",
                            "warning",
                            (
                                f"#{number} declares PCL entity references but no local "
                                "PCL state exists at this root; statuses are omitted, "
                                "not invented"
                            ),
                            issue=number,
                        )
                    )

            resolved_statuses: list[str] = []
            resolved_statuses.extend(goal["status"] for goal in pcl_block["goals"])
            resolved_statuses.extend(task["status"] for task in pcl_block["tasks"])
            item_status: str | None = None
            if resolved_statuses and len(set(resolved_statuses)) == 1:
                item_status = resolved_statuses[0]

            if entry["lifecycle"] == "active":
                for status in sorted(set(resolved_statuses)):
                    if status in CONTRADICTING_TASK_STATUSES:
                        findings.append(
                            _finding(
                                "status_contradiction",
                                "error",
                                (
                                    f"#{number} is mapped as active but its PCL state "
                                    f"is terminal ({status}); refresh the mapping or "
                                    "the PCL state before publishing"
                                ),
                                issue=number,
                            )
                        )

            items.append(
                {
                    "issue": number,
                    "issue_url": f"https://github.com/{mapping['repository']}/issues/{number}",
                    "title_hint": entry.get("title_hint"),
                    "priority": entry["priority"],
                    "lifecycle": entry["lifecycle"],
                    "depends_on": list(entry["depends_on"]),
                    "status": item_status,
                    "statuses": sorted(resolved_statuses),
                    "owner_boundary": entry.get("owner_boundary"),
                    "acceptance_criteria_refs": list(entry.get("acceptance_criteria_refs", [])),
                    "anchors": anchors,
                    "dependencies": {
                        "declared": list(entry["depends_on"]),
                        "pcl_task_dependencies": pcl_block["pcl_task_dependencies"],
                    },
                    "pcl": {
                        "available": pcl_block["available"],
                        "goals": pcl_block["goals"],
                        "tasks": pcl_block["tasks"],
                    },
                }
            )
    finally:
        if conn is not None:
            conn.close()

    items.sort(key=lambda item: (_PRIORITY_ORDER[item["priority"]], item["issue"]))
    findings.sort(
        key=lambda finding: (
            _SEVERITY_ORDER[finding["severity"]],
            finding["code"],
            finding.get("issue") is None,
            finding.get("issue") or 0,
            finding["message"],
        )
    )
    has_errors = any(finding["severity"] == "error" for finding in findings)
    return {
        "schema": PROJECTION_SCHEMA,
        "repository": mapping["repository"],
        "policy": mapping["policy"],
        "source_of_truth": "PCL state (.project-loop) and accepted task/Evidence records",
        "refresh_command": _REFRESH_COMMAND,
        "pcl_state_available": db_available,
        "items": items,
        "findings": findings,
        "ok": not has_errors,
    }


def render_markdown(projection: dict[str, Any]) -> str:
    """Render the deterministic Markdown form of a projection payload."""
    lines: list[str] = []
    lines.append("# Backlog projection from PCL state")
    lines.append("")
    lines.append(f"Source of truth: {projection['source_of_truth']}.")
    lines.append(projection["policy"])
    lines.append("")
    lines.append(f"Refresh command: `{projection['refresh_command']}`")
    lines.append("")
    lines.append(f"- Schema: `{projection['schema']}`")
    lines.append(f"- Repository: `{projection['repository']}`")
    lines.append(
        "- Local PCL state enrichment: "
        + ("available at render time" if projection["pcl_state_available"] else "not present; statuses omitted")
    )
    lines.append("")
    lines.append("## Items")
    lines.append("")
    if not projection["items"]:
        lines.append("(no items)")
        lines.append("")
    for item in projection["items"]:
        title_suffix = f" — {item['title_hint']}" if item.get("title_hint") else ""
        lines.append(f"### #{item['issue']} [{item['priority']}] ({item['lifecycle']}){title_suffix}")
        lines.append("")
        lines.append(f"- Issue: {item['issue_url']}")
        status_text = (
            f"`{item['status']}`"
            if item["status"] is not None
            else "unavailable (no local PCL state at render time)"
        )
        lines.append(f"- Status: {status_text}")
        declared = ", ".join(f"#{dep}" for dep in item["dependencies"]["declared"]) or "none"
        lines.append(f"- Dependencies (declared): {declared}")
        edges = item["dependencies"]["pcl_task_dependencies"]
        if edges:
            edge_text = ", ".join(
                f"`{edge['task_id']}` depends on `{edge['depends_on_task_id']}`" for edge in edges
            )
            lines.append(f"- Dependencies (PCL tasks): {edge_text}")
        refs = item["acceptance_criteria_refs"]
        lines.append(
            "- Acceptance criteria: "
            + (", ".join(f"`{ref}`" for ref in refs) if refs else "see issue body")
        )
        boundary = item.get("owner_boundary")
        if boundary:
            lines.append(f"- Owner boundary: {boundary}")
        for kind, rows in sorted(item["anchors"].items()):
            if not rows:
                continue
            rendered = ", ".join(
                f"`{row['path']}`" if row["path"] else f"`{row['ref']}` (missing)" for row in rows
            )
            lines.append(f"- Anchors ({kind}): {rendered}")
        if item["pcl"]["available"]:
            for goal in item["pcl"]["goals"]:
                lines.append(
                    f"- PCL goal `{goal['id']}`: {goal['status']} — {goal['title']} "
                    f"(updated {goal['updated_at']})"
                )
            for task in item["pcl"]["tasks"]:
                evidence = task["last_authoritative_evidence"]
                if evidence is not None:
                    summary = f": {evidence['summary']}" if evidence.get("summary") else ""
                    lines.append(
                        f"- Last authoritative Evidence for `{task['id']}`: "
                        f"`{evidence['id']}` ({evidence['type']}, {evidence['created_at']}"
                        f"{summary})"
                    )
                else:
                    lines.append(f"- Last authoritative Evidence for `{task['id']}`: none")
                for stale_row in task["superseded_evidence"]:
                    lines.append(
                        f"  - Superseded Evidence `{stale_row['id']}` "
                        f"(superseded by `{stale_row['superseded_by']}`)"
                    )
        else:
            lines.append("- PCL state: not available on this machine; live status lives in `.project-loop/`")
        lines.append("")
    lines.append("## Findings")
    lines.append("")
    if not projection["findings"]:
        lines.append("none")
        lines.append("")
    for finding in projection["findings"]:
        issue_part = f" #{finding['issue']}" if "issue" in finding else ""
        lines.append(f"- [{finding['severity'].upper()}] {finding['code']}{issue_part}: {finding['message']}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render_github_backlog",
        description=(
            "Render the deterministic, read-only GitHub backlog projection "
            "from the committed issue map plus optional local PCL state."
        ),
    )
    parser.add_argument("--root", default=".", help="Repository/project root to read anchors and PCL state from.")
    parser.add_argument("--map", required=True, help="Path to the committed github-issue-map.json file.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out", default=None, help="Write the artifact to this path instead of stdout. Refuses to write when findings fail closed.")
    args = parser.parse_args(argv)

    try:
        mapping = load_issue_map(args.map)
        projection = build_projection(args.root, mapping)
    except PclError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code

    map_bytes = Path(args.map).read_bytes()
    projection["mapping_sha256"] = hashlib.sha256(map_bytes).hexdigest()

    if args.format == "json":
        content = json.dumps(projection, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    else:
        content = render_markdown(projection)

    error_findings = [f for f in projection["findings"] if f["severity"] == "error"]
    if error_findings:
        print(json.dumps(projection, ensure_ascii=False, sort_keys=True, indent=2))
        for finding in error_findings:
            print(f"ERROR: {finding['code']}: {finding['message']}", file=sys.stderr)
        if args.out is not None:
            print(
                "ERROR: fail-closed; refusing to write review artifact while "
                "error findings exist",
                file=sys.stderr,
            )
        return 1

    if args.out is not None:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0
