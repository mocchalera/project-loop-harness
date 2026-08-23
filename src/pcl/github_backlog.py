"""Deterministic, read-only GitHub backlog projection.

Renders issue-ready Markdown/JSON from repo-verifiable anchors declared in a
committed mapping file, with optional read-only enrichment from local PCL
state. PCL state and accepted task/Evidence records remain authoritative;
GitHub Issues are a contributor-facing projection. This module never mutates
project state, never appends events, and never touches the network.

Fail-closed contract: missing anchors, duplicate mappings, unresolvable PCL
entity references, and stale-status contradictions are reported as
error-severity findings and the command exits non-zero. The renderer emits
stdout only. State that is simply unavailable (no local ``project.db``) is
labeled honestly instead of invented.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

from .db import connect_read_only
from .errors import InvalidInputError, PclError

PROJECTION_SCHEMA = "github-backlog-projection/v0"
ISSUE_MAP_SCHEMA = "github-issue-map/v0"
PROJECTION_POLICY = (
    "PCL state and accepted task/Evidence records are authoritative; GitHub Issues "
    "communicate current work and discussion. Closing a GitHub Issue alone must not "
    "close a PCL target or rewrite historical Evidence."
)

ISSUE_MAP_REQUIRED_ENTRY_KEYS = frozenset({"issue", "anchors", "acceptance_criteria_refs"})
ISSUE_MAP_OPTIONAL_ENTRY_KEYS = frozenset(
    {
        "title_hint",
        "pcl_entities",
    }
)
ANCHOR_KINDS = ("agent_task_ids", "repo_paths")
PCL_ID_PATTERNS = {
    "goals": re.compile(r"^G-\d+$"),
    "features": re.compile(r"^F-\d+$"),
    "tasks": re.compile(r"^T-\d+$"),
}

TERMINAL_STATUSES = {
    "goal": frozenset({"closed", "cancelled"}),
    "feature": frozenset({"done", "waived"}),
    "task": frozenset({"done", "cancelled", "waived"}),
}
EVIDENCE_SUPERSEDES_ROLE = "supersedes"
EVIDENCE_SUPERSEDES_TARGET = "evidence"

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_TASK_METADATA_RE = re.compile(
    r"(?im)^\s*-\s+\*\*(Status|Priority|Dependency):\*\*\s*(.+?)\s*$"
)
_TASK_REFERENCE_RE = re.compile(r"(?<!\d)(\d{4})(?:\s*[-–]\s*(\d{4}))?(?!\d)")
_RELEVANT_COMMIT_RE = re.compile(
    r"(?im)^\s*-\s+(?:Release commit|Implementation (?:commit|tree)):\s*`([0-9a-f]{7,40})`"
)

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
    unknown_root = set(payload) - {"schema", "repository", "issues"}
    if unknown_root:
        raise InvalidInputError(
            "Issue map root has unknown fields",
            details={"unknown": sorted(unknown_root)},
        )
    if payload.get("schema") != ISSUE_MAP_SCHEMA:
        raise InvalidInputError(
            f"Issue map schema must be {ISSUE_MAP_SCHEMA}",
            details={"found": payload.get("schema")},
        )
    for key in ("repository",):
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
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
            raise InvalidInputError("Issue map field issue must be a positive integer", details={})
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
            if kind == "agent_task_ids" and not all(
                re.fullmatch(r"\d{4}", ref) for ref in refs_list
            ):
                raise InvalidInputError(
                    "Mapping agent_task_ids must be four-digit task-record identifiers",
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
            "anchors": anchors,
            "acceptance_criteria_refs": _require_str_list(
                entry["acceptance_criteria_refs"], "acceptance_criteria_refs", number
            ),
        }
        if "title_hint" in entry:
            if not isinstance(entry["title_hint"], str) or not entry["title_hint"].strip():
                raise InvalidInputError(
                    "Issue map title_hint must be a non-empty string",
                    details={"issue": number},
                )
            normalized_entry["title_hint"] = entry["title_hint"]
        if "pcl_entities" in entry:
            entities = entry["pcl_entities"]
            if not isinstance(entities, dict):
                raise InvalidInputError(
                    "Issue map pcl_entities must be an object",
                    details={"issue": number},
                )
            pcl: dict[str, list[str]] = {}
            for kind in ("goals", "features", "tasks"):
                values = entities.get(kind, [])
                pcl[kind] = _require_str_list(values, f"pcl_entities.{kind}", number)
                if not all(PCL_ID_PATTERNS[kind].fullmatch(value) for value in pcl[kind]):
                    raise InvalidInputError(
                        f"Mapping pcl_entities.{kind} contains an invalid PCL ID",
                        details={"issue": number},
                    )
            unknown_entity_kinds = set(entities) - {"goals", "features", "tasks"}
            if unknown_entity_kinds:
                raise InvalidInputError(
                    "Issue map pcl_entities supports only goals, features, and tasks",
                    details={"issue": number, "unknown": sorted(unknown_entity_kinds)},
                )
            normalized_entry["pcl_entities"] = pcl
        normalized.append(normalized_entry)
    return {
        "schema": ISSUE_MAP_SCHEMA,
        "repository": payload["repository"],
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


def _repo_local_file(root: Path, ref: str) -> Path | None:
    candidate = Path(ref)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = root / candidate
    return resolved if resolved.is_file() else None


def _resolve_acceptance_references(
    root: Path, entry: dict[str, Any], findings: list[dict[str, Any]]
) -> list[str]:
    number = entry["issue"]
    refs = entry["acceptance_criteria_refs"]
    if not refs:
        findings.append(
            _finding(
                "acceptance_reference_missing",
                "error",
                f"#{number} has no repo-local acceptance reference",
                issue=number,
            )
        )
    for ref in refs:
        if _repo_local_file(root, ref) is None:
            findings.append(
                _finding(
                    "acceptance_reference_missing",
                    "error",
                    f"Repo-local acceptance reference for #{number} does not exist: {ref}",
                    issue=number,
                    detail={"ref": ref},
                )
            )
    return list(refs)


def _normalize_record_status(raw: str) -> tuple[str | None, str | None]:
    value = raw.strip().lower()
    if value.startswith("active"):
        return "active", "active"
    if value.startswith("done"):
        return "done", "completed"
    if value.startswith("completed"):
        return "completed", "completed"
    if value.startswith("cancelled"):
        return "cancelled", "completed"
    if value.startswith("waived"):
        return "waived", "completed"
    return None, None


def _dependency_ids(raw: str) -> list[str]:
    dependencies: list[str] = []
    for match in _TASK_REFERENCE_RE.finditer(raw):
        start = match.group(1)
        end = match.group(2)
        if end is None:
            dependencies.append(start)
            continue
        start_number = int(start)
        end_number = int(end)
        if end_number < start_number or end_number - start_number > 100:
            dependencies.extend([start, end])
            continue
        dependencies.extend(f"{number:04d}" for number in range(start_number, end_number + 1))
    return dependencies


def _completion_evidence(text: str) -> list[str]:
    lines = text.splitlines()
    in_section = False
    evidence: list[str] = []
    for line in lines:
        if line.strip().lower() == "## completion evidence":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.lstrip().startswith("-"):
            value = line.lstrip()[1:].strip()
            if value:
                evidence.append(value)
    return evidence


def _accepted_task_records(
    root: Path,
    entry: dict[str, Any],
    resolved_anchors: dict[str, list[dict[str, Any]]],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    number = entry["issue"]
    records: list[dict[str, Any]] = []
    for anchor in resolved_anchors["agent_task_ids"]:
        path_value = anchor["path"]
        if path_value is None:
            continue
        path = root / path_value
        text = path.read_text(encoding="utf-8")
        metadata = {key.lower(): value for key, value in _TASK_METADATA_RE.findall(text)}
        status, lifecycle = _normalize_record_status(metadata.get("status", ""))
        priority_match = re.search(r"\bP[0-3]\b", metadata.get("priority", ""))
        dependencies = _dependency_ids(metadata.get("dependency", ""))
        dependency_counts = Counter(dependencies)
        for dependency, count in sorted(dependency_counts.items()):
            if count > 1:
                findings.append(
                    _finding(
                        "dependency_reference_duplicate",
                        "error",
                        (
                            f"Accepted task record {anchor['ref']} for #{number} repeats "
                            f"dependency {dependency}"
                        ),
                        issue=number,
                        detail={"task_record_id": anchor["ref"], "dependency": dependency},
                    )
                )
            if dependency == anchor["ref"]:
                findings.append(
                    _finding(
                        "dependency_reference_self",
                        "error",
                        f"Accepted task record {anchor['ref']} for #{number} depends on itself",
                        issue=number,
                        detail={"task_record_id": anchor["ref"]},
                    )
                )
                continue
            matches = sorted((root / "agent-tasks").glob(f"{dependency}-*.md"))
            if len(matches) != 1:
                findings.append(
                    _finding(
                        "dependency_reference_missing",
                        "error",
                        (
                            f"Accepted task record {anchor['ref']} for #{number} references "
                            f"missing or ambiguous dependency {dependency}"
                        ),
                        issue=number,
                        detail={"task_record_id": anchor["ref"], "dependency": dependency},
                    )
                )
        records.append(
            {
                "id": anchor["ref"],
                "path": path_value,
                "status": status,
                "lifecycle": lifecycle,
                "priority": priority_match.group(0) if priority_match else None,
                "dependencies": sorted(dependency_counts),
                "completion_evidence": _completion_evidence(text),
                "relevant_commits": sorted(set(_RELEVANT_COMMIT_RE.findall(text))),
            }
        )
    return records


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
    entities = entry.get("pcl_entities", {"goals": [], "features": [], "tasks": []})
    goals: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
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

    for feature_id in entities.get("features", []):
        row = conn.execute(
            "SELECT id, name, surface, status, updated_at FROM features WHERE id = ?",
            (feature_id,),
        ).fetchone()
        if row is None:
            findings.append(
                _finding(
                    "pcl_entity_missing",
                    "error",
                    f"PCL feature referenced by #{number} does not exist: {feature_id}",
                    issue=number,
                    detail={"kind": "feature", "id": feature_id},
                )
            )
            continue
        features.append(
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "surface": str(row["surface"]),
                "status": str(row["status"]),
                "updated_at": str(row["updated_at"]),
            }
        )

    dependency_edges: set[tuple[str, str]] = set()
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
        for edge in conn.execute(
            """
            SELECT task_id, depends_on_task_id FROM task_dependencies
            WHERE task_id = ?
            ORDER BY task_id, depends_on_task_id
            """,
            (task_id,),
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
        "features": features,
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

    pcl_owners: dict[tuple[str, str], list[int]] = {}
    for entry in entries:
        for kind, ids in entry.get("pcl_entities", {}).items():
            for entity_id in ids:
                pcl_owners.setdefault((kind, entity_id), []).append(entry["issue"])
    for (kind, entity_id), owners in sorted(pcl_owners.items()):
        if len(owners) > 1:
            findings.append(
                _finding(
                    "duplicate_pcl_id",
                    "error",
                    (
                        f"PCL {kind[:-1]} {entity_id} is claimed by multiple issues: "
                        + ", ".join(f"#{owner}" for owner in sorted(owners))
                    ),
                    detail={"kind": kind[:-1], "id": entity_id, "issues": sorted(owners)},
                )
            )

    db_path = project_root / ".project-loop" / "project.db"
    db_available = db_path.is_file()
    conn: sqlite3.Connection | None = None
    if db_available:
        conn = connect_read_only(db_path)

    items: list[dict[str, Any]] = []
    try:
        for entry in entries:
            number = entry["issue"]
            anchors = _resolve_anchors(project_root, entry, findings)
            acceptance_refs = _resolve_acceptance_references(project_root, entry, findings)
            task_records = _accepted_task_records(project_root, entry, anchors, findings)
            declared = entry.get(
                "pcl_entities", {"goals": [], "features": [], "tasks": []}
            )
            pcl_block: dict[str, Any]
            declares_entities = any(declared.values())
            if conn is not None:
                pcl_block = _enrich_from_pcl_state(conn, entry, findings)
            else:
                pcl_block = {
                    "available": False,
                    "goals": [],
                    "features": [],
                    "tasks": [],
                    "pcl_task_dependencies": [],
                }
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

            pcl_statuses: list[dict[str, Any]] = []
            for kind in ("goal", "feature", "task"):
                for row in pcl_block[f"{kind}s"]:
                    pcl_statuses.append(
                        {
                            "source": "pcl",
                            "kind": kind,
                            "id": row["id"],
                            "status": row["status"],
                        }
                    )
            record_statuses = [
                {
                    "source": "accepted_task_record",
                    "kind": "task_record",
                    "id": record["id"],
                    "status": record["status"],
                }
                for record in task_records
                if record["status"] is not None
            ]
            status_details = pcl_statuses if pcl_statuses else record_statuses
            status_values = [detail["status"] for detail in status_details]
            item_status = (
                status_values[0]
                if status_values and len(set(status_values)) == 1
                else None
            )

            record_lifecycles = {
                record["lifecycle"]
                for record in task_records
                if record["lifecycle"] is not None
            }
            if len(record_lifecycles) == 1 and pcl_statuses:
                expected_lifecycle = next(iter(record_lifecycles))
                for detail in pcl_statuses:
                    terminal = detail["status"] in TERMINAL_STATUSES[detail["kind"]]
                    contradiction = (
                        expected_lifecycle == "active" and terminal
                    ) or (
                        expected_lifecycle == "completed" and not terminal
                    )
                    if contradiction:
                        findings.append(
                            _finding(
                                "status_contradiction",
                                "error",
                                (
                                    f"#{number} accepted task record lifecycle is "
                                    f"{expected_lifecycle}, but PCL {detail['kind']} "
                                    f"{detail['id']} is {detail['status']}"
                                ),
                                issue=number,
                                detail=detail,
                            )
                        )

            pcl_lifecycles = [
                (
                    "completed"
                    if detail["status"] in TERMINAL_STATUSES[detail["kind"]]
                    else "active"
                )
                for detail in pcl_statuses
            ]
            lifecycle_values = pcl_lifecycles or sorted(record_lifecycles)
            lifecycle = (
                lifecycle_values[0]
                if lifecycle_values and len(set(lifecycle_values)) == 1
                else None
            )

            pcl_priorities = [
                {
                    "source": "pcl",
                    "kind": "task",
                    "id": task["id"],
                    "priority": task["priority"],
                }
                for task in pcl_block["tasks"]
            ]
            record_priorities = [
                {
                    "source": "accepted_task_record",
                    "kind": "task_record",
                    "id": record["id"],
                    "priority": record["priority"],
                }
                for record in task_records
                if record["priority"] is not None
            ]
            priority_details = pcl_priorities or record_priorities
            priority_values = [detail["priority"] for detail in priority_details]
            priority = (
                priority_values[0]
                if priority_values and len(set(priority_values)) == 1
                else None
            )

            record_dependencies = [
                {"task_record_id": record["id"], "depends_on_task_record_id": dependency}
                for record in task_records
                for dependency in record["dependencies"]
            ]
            evidence = [
                {
                    "source": "pcl",
                    "target_id": task["id"],
                    "evidence": task["last_authoritative_evidence"],
                }
                for task in pcl_block["tasks"]
                if task["last_authoritative_evidence"] is not None
            ]
            evidence.extend(
                {
                    "source": "accepted_task_record",
                    "target_id": record["id"],
                    "reference": reference,
                }
                for record in task_records
                for reference in record["completion_evidence"]
            )
            relevant_commits = sorted(
                {
                    commit
                    for record in task_records
                    for commit in record["relevant_commits"]
                }
            )

            items.append(
                {
                    "issue": number,
                    "issue_url": f"https://github.com/{mapping['repository']}/issues/{number}",
                    "title_hint": entry.get("title_hint"),
                    "priority": priority,
                    "priorities": priority_details,
                    "lifecycle": lifecycle,
                    "status": item_status,
                    "statuses": status_details,
                    "acceptance_criteria_refs": acceptance_refs,
                    "anchors": anchors,
                    "dependencies": {
                        "pcl_task_dependencies": pcl_block["pcl_task_dependencies"],
                        "task_record_dependencies": record_dependencies,
                    },
                    "evidence": evidence,
                    "relevant_commit": (
                        relevant_commits[0] if len(relevant_commits) == 1 else None
                    ),
                    "relevant_commits": relevant_commits,
                    "accepted_task_records": task_records,
                    "pcl": {
                        "available": pcl_block["available"],
                        "declared": {
                            "goals": list(declared.get("goals", [])),
                            "features": list(declared.get("features", [])),
                            "tasks": list(declared.get("tasks", [])),
                        },
                        "goals": pcl_block["goals"],
                        "features": pcl_block["features"],
                        "tasks": pcl_block["tasks"],
                    },
                }
            )
    finally:
        if conn is not None:
            conn.close()

    items.sort(key=lambda item: item["issue"])
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
        "policy": PROJECTION_POLICY,
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
        priority = item["priority"] if item["priority"] is not None else "priority unavailable"
        lifecycle = (
            item["lifecycle"] if item["lifecycle"] is not None else "lifecycle unavailable"
        )
        lines.append(f"### #{item['issue']} [{priority}] ({lifecycle}){title_suffix}")
        lines.append("")
        lines.append(f"- Issue: {item['issue_url']}")
        if item["status"] is not None:
            status_text = f"`{item['status']}`"
        elif item["statuses"]:
            status_text = (
                "mixed (see individual PCL targets)"
                if item["pcl"]["available"] and any(
                    detail["source"] == "pcl" for detail in item["statuses"]
                )
                else "mixed (see accepted task records)"
            )
        else:
            status_text = "unavailable"
        lines.append(f"- Status: {status_text}")
        edges = item["dependencies"]["pcl_task_dependencies"]
        if edges:
            edge_text = ", ".join(
                f"`{edge['task_id']}` depends on `{edge['depends_on_task_id']}`" for edge in edges
            )
            lines.append(f"- Dependencies (PCL tasks): {edge_text}")
        record_edges = item["dependencies"]["task_record_dependencies"]
        if record_edges:
            edge_text = ", ".join(
                (
                    f"task record `{edge['task_record_id']}` depends on "
                    f"`{edge['depends_on_task_record_id']}`"
                )
                for edge in record_edges
            )
            lines.append(f"- Dependencies (accepted task records): {edge_text}")
        if not edges and not record_edges:
            lines.append("- Dependencies: unavailable")
        refs = item["acceptance_criteria_refs"]
        lines.append(
            "- Acceptance criteria: "
            + (", ".join(f"`{ref}`" for ref in refs) if refs else "see issue body")
        )
        for kind, rows in sorted(item["anchors"].items()):
            if not rows:
                continue
            rendered = ", ".join(
                f"`{row['path']}`" if row["path"] else f"`{row['ref']}` (missing)" for row in rows
            )
            lines.append(f"- Anchors ({kind}): {rendered}")
        declared_targets = [
            entity_id
            for kind in ("goals", "features", "tasks")
            for entity_id in item["pcl"]["declared"][kind]
        ]
        if declared_targets:
            lines.append(
                "- Declared PCL targets: "
                + ", ".join(f"`{entity_id}`" for entity_id in declared_targets)
            )
        if item["pcl"]["available"]:
            for goal in item["pcl"]["goals"]:
                lines.append(
                    f"- PCL goal `{goal['id']}`: {goal['status']} — {goal['title']} "
                    f"(updated {goal['updated_at']})"
                )
            for feature in item["pcl"]["features"]:
                lines.append(
                    f"- PCL feature `{feature['id']}`: {feature['status']} — "
                    f"{feature['name']} (updated {feature['updated_at']})"
                )
            for task in item["pcl"]["tasks"]:
                lines.append(
                    f"- PCL task `{task['id']}`: {task['status']} — {task['title']} "
                    f"(priority {task['priority']}, updated {task['updated_at']})"
                )
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
            lines.append("- PCL enrichment: unavailable; declared target IDs remain listed above")
        for record in item["accepted_task_records"]:
            status = record["status"] or "unavailable"
            priority = record["priority"] or "unavailable"
            lines.append(
                f"- Accepted task record `{record['id']}`: status {status}; priority {priority}"
            )
        if item["relevant_commit"] is not None:
            lines.append(f"- Relevant commit: `{item['relevant_commit']}`")
        elif item["relevant_commits"]:
            lines.append(
                "- Relevant commits: "
                + ", ".join(f"`{commit}`" for commit in item["relevant_commits"])
            )
        else:
            lines.append("- Relevant commit: unavailable")
        if not item["evidence"]:
            lines.append("- Evidence: unavailable")
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
        return 1

    print(content, end="")
    return 0
