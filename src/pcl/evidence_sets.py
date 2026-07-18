from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
from typing import Any

from .contracts.evidence_set import (
    EVIDENCE_SET_CONTRACT_VERSION,
    REPORT_MANIFEST_CONTRACT_VERSION,
    canonical_evidence_set_json,
    load_evidence_set,
    serialized_evidence_set,
    validate_evidence_set,
)
from .db import connect, connect_mutation, table_exists
from .errors import DataStoreError, InvalidInputError, PclError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .strict_evidence import strict_read_canonical_file
from .timeutil import utc_now_iso
from .work_briefs import parse_target_ref


EVIDENCE_SET_EVIDENCE_TYPE = "evidence_set"
EVIDENCE_SET_LINK_ROLE = "evidence_set"

_TARGET_TABLES = {
    "goal": "goals",
    "task": "tasks",
    "feature": "features",
    "story": "user_stories",
    "defect": "defects",
    "workflow_run": "workflow_runs",
    "test_case": "test_cases",
}
_KIND = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_ROLE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_EVIDENCE_ID = re.compile(r"^E-[0-9]{4,}$")
_REPORT_STATUSES = {"pass", "fail", "warning", "unknown"}


class EvidenceSetError(PclError):
    pass


def plan_evidence_set(
    paths: ProjectPaths,
    *,
    target_ref: str,
    work_root: str,
    manifest_file: str,
    required_kinds: list[str] | None = None,
    included_refs: list[str] | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    target = parse_target_ref(target_ref)
    required = _required_kinds(required_kinds or [])
    selections = _included_selections(included_refs or [])
    work_path, work_root_value = _work_root(paths, work_root)
    manifest_path, manifest_value = _manifest_path(paths, work_path, manifest_file)
    reports = _load_report_manifest(work_path, manifest_path)
    conn = connect(paths.db_path)
    try:
        _validate_target(conn, target)
        _validate_selected_evidence(conn, selections)
    finally:
        conn.close()
    artifact = _build_artifact(
        work_root_value=work_root_value,
        manifest_path=manifest_path.relative_to(work_path).as_posix(),
        manifest_sha256=_file_sha256(manifest_path),
        target=target,
        required=required,
        reports=reports,
        selections=selections,
    )
    validation = validate_evidence_set(artifact)
    if not validation.ok:
        raise DataStoreError(
            "Generated Evidence set failed contract validation.",
            details={"errors": list(validation.errors)},
        )
    warnings = [
        {
            "code": "evidence_set_report_excluded",
            "kind": item["kind"],
            "path": item["path"],
            "required": item["required"],
            "status": item["status"],
        }
        for item in artifact["excluded_reports"]
    ]
    return {
        "ok": True,
        "changed": False,
        "plan": artifact,
        "warnings": warnings,
        "source": {
            "work_root": work_root_value,
            "manifest": manifest_value,
        },
    }


def record_evidence_set(
    paths: ProjectPaths,
    *,
    target_ref: str,
    work_root: str,
    manifest_file: str,
    required_kinds: list[str] | None,
    included_refs: list[str] | None,
    summary: str,
) -> dict[str, Any]:
    summary = _required_text(summary, "summary")
    preview = plan_evidence_set(
        paths,
        target_ref=target_ref,
        work_root=work_root,
        manifest_file=manifest_file,
        required_kinds=required_kinds,
        included_refs=included_refs,
    )
    artifact = preview["plan"]
    target = artifact["target"]
    conn = connect_mutation(paths)
    final_path: Path | None = None
    temp_path: Path | None = None
    try:
        if not table_exists(conn, "evidence_links"):
            raise _error(
                "evidence_set_links_required",
                "Evidence sets require schema 7 evidence_links support.",
            )
        _validate_target(conn, target)
        _validate_selected_evidence(
            conn,
            [
                {
                    "kind": item["kind"],
                    "evidence_id": item["evidence_id"],
                    "role": item["role"],
                }
                for item in artifact["included_reports"]
            ],
        )
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        artifact_dir = paths.evidence_dir / "evidence-sets"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        final_path = artifact_dir / f"{evidence_id.lower()}-evidence-set-v1.json"
        temp_path = final_path.with_suffix(".json.tmp")
        temp_path.write_text(serialized_evidence_set(artifact), encoding="utf-8")
        temp_path.replace(final_path)
        relative_path = final_path.relative_to(paths.root).as_posix()
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (evidence_id, EVIDENCE_SET_EVIDENCE_TYPE, relative_path, summary, now),
        )
        conn.execute(
            """
            INSERT INTO evidence_links(
              evidence_id, target_type, target_id, link_role, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (evidence_id, target["type"], target["id"], EVIDENCE_SET_LINK_ROLE, now),
        )
        artifact_sha256 = _artifact_sha256(artifact)
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="evidence_set_recorded",
            entity_type="evidence",
            entity_id=evidence_id,
            payload={
                "contract_version": EVIDENCE_SET_CONTRACT_VERSION,
                "evidence_id": evidence_id,
                "target": target,
                "path": relative_path,
                "artifact_sha256": artifact_sha256,
                "completeness_status": artifact["completeness"]["status"],
                "included_report_count": len(artifact["included_reports"]),
                "excluded_report_count": len(artifact["excluded_reports"]),
                "summary": summary,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "changed": True,
            "event_id": event_id,
            "warnings": preview["warnings"],
            "evidence": {
                "id": evidence_id,
                "type": EVIDENCE_SET_EVIDENCE_TYPE,
                "path": relative_path,
                "summary": summary,
                "target": target,
                "artifact_sha256": artifact_sha256,
                "completeness_status": artifact["completeness"]["status"],
            },
        }
    except PclError:
        conn.rollback()
        _remove_uncommitted_file(conn, temp_path, final_path)
        raise
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        _remove_uncommitted_file(conn, temp_path, final_path)
        raise DataStoreError(
            f"Could not record Evidence set: {exc}",
            details={"target": target},
        ) from exc
    finally:
        conn.close()


def show_evidence_set(paths: ProjectPaths, *, evidence_id: str) -> dict[str, Any]:
    require_initialized(paths)
    conn = connect(paths.db_path)
    try:
        return {"ok": True, "evidence_set": inspect_evidence_set(conn, paths, evidence_id)}
    finally:
        conn.close()


def inspect_evidence_set(
    conn: sqlite3.Connection,
    paths: ProjectPaths,
    evidence_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, type, path, summary, created_at FROM evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if row is None or str(row["type"]) != EVIDENCE_SET_EVIDENCE_TYPE:
        raise _error(
            "evidence_set_unknown_evidence",
            f"Evidence set does not exist: {evidence_id}",
            evidence_id=evidence_id,
        )
    links = conn.execute(
        """
        SELECT target_type, target_id, link_role
        FROM evidence_links
        WHERE evidence_id = ?
        ORDER BY target_type, target_id, link_role
        """,
        (evidence_id,),
    ).fetchall()
    findings: list[dict[str, Any]] = []
    matching_links = [row for row in links if str(row["link_role"]) == EVIDENCE_SET_LINK_ROLE]
    if len(matching_links) != 1:
        findings.append(
            {"code": "target_link_count", "expected": 1, "actual": len(matching_links)}
        )
        linked_target = {"type": "", "id": ""}
    else:
        linked_target = {
            "type": str(matching_links[0]["target_type"]),
            "id": str(matching_links[0]["target_id"]),
        }
    path = paths.root / str(row["path"])
    artifact: dict[str, Any] | None = None
    try:
        value = load_evidence_set(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        findings.append({"code": "artifact_unreadable", "reason": str(exc)})
    else:
        validation = validate_evidence_set(value)
        if not validation.ok:
            findings.append({"code": "contract_invalid", "errors": list(validation.errors)})
        elif isinstance(value, dict):
            artifact = value
            if value["target"] != linked_target:
                findings.append(
                    {"code": "target_mismatch", "artifact": value["target"], "link": linked_target}
                )
    return {
        "evidence_id": evidence_id,
        "path": str(row["path"]),
        "summary": str(row["summary"]),
        "created_at": str(row["created_at"]),
        "target": linked_target,
        "artifact_sha256": None if artifact is None else _artifact_sha256(artifact),
        "health": "ok" if not findings else "warning",
        "findings": findings,
        "artifact": artifact,
    }


def resolve_strict_evidence_set(
    paths: ProjectPaths,
    *,
    evidence_id: str,
) -> dict[str, Any]:
    """Resolve one event-anchored Evidence Set artifact without mutation."""
    require_initialized(paths)
    evidence_id = str(evidence_id or "").strip()
    conn = connect(paths.db_path)
    try:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT id, type, path, summary FROM evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        event_rows = conn.execute(
            """
            SELECT id, sequence, payload_json
            FROM events
            WHERE event_type = 'evidence_set_recorded'
              AND entity_type = 'evidence'
              AND entity_id = ?
            ORDER BY sequence, id
            """,
            (evidence_id,),
        ).fetchall()
    finally:
        conn.close()

    if not event_rows:
        return _strict_evidence_set_result(
            evidence_id,
            findings=[
                {"code": "strict_event_anchor_missing", "evidence_kind": "evidence_set"}
            ],
        )
    if len(event_rows) != 1:
        return _strict_evidence_set_result(
            evidence_id,
            findings=[
                {
                    "code": "strict_event_anchor_ambiguous",
                    "evidence_kind": "evidence_set",
                    "actual": len(event_rows),
                }
            ],
        )
    event_row = event_rows[0]
    event_anchor = {
        "id": str(event_row["id"]),
        "sequence": int(event_row["sequence"]),
        "event_type": "evidence_set_recorded",
    }
    try:
        anchor = json.loads(str(event_row["payload_json"]))
    except json.JSONDecodeError:
        return _strict_evidence_set_result(
            evidence_id,
            event_anchor=event_anchor,
            findings=[
                {"code": "strict_event_anchor_invalid", "evidence_kind": "evidence_set"}
            ],
        )
    if not isinstance(anchor, dict):
        return _strict_evidence_set_result(
            evidence_id,
            event_anchor=event_anchor,
            findings=[
                {"code": "strict_event_anchor_invalid", "evidence_kind": "evidence_set"}
            ],
        )
    if row is None or str(row["type"]) != EVIDENCE_SET_EVIDENCE_TYPE:
        return _strict_evidence_set_result(
            evidence_id,
            event_anchor=event_anchor,
            findings=[
                {"code": "strict_evidence_row_invalid", "evidence_kind": "evidence_set"}
            ],
        )

    expected_path = (
        f".project-loop/evidence/evidence-sets/{evidence_id.lower()}-evidence-set-v1.json"
    )
    if str(row["path"] or "") != expected_path or anchor.get("path") != expected_path:
        return _strict_evidence_set_result(
            evidence_id,
            event_anchor=event_anchor,
            findings=[{"code": "strict_evidence_set_path_invalid"}],
        )

    artifact_path = paths.root / expected_path
    artifact_read = strict_read_canonical_file(
        artifact_path,
        expected_parent=paths.evidence_dir / "evidence-sets",
    )
    if not artifact_read.ok:
        return _strict_evidence_set_result(
            evidence_id,
            event_anchor=event_anchor,
            findings=[_strict_evidence_set_file_finding(artifact_read.status)],
        )
    assert artifact_read.content is not None
    try:
        artifact = json.loads(artifact_read.content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _strict_evidence_set_result(
            evidence_id,
            event_anchor=event_anchor,
            artifact_bytes=artifact_read.content,
            findings=[{"code": "strict_evidence_set_invalid_json"}],
        )
    if not isinstance(artifact, dict):
        return _strict_evidence_set_result(
            evidence_id,
            event_anchor=event_anchor,
            artifact_bytes=artifact_read.content,
            findings=[{"code": "strict_evidence_set_contract_invalid"}],
        )
    validation = validate_evidence_set(artifact)
    if not validation.ok:
        return _strict_evidence_set_result(
            evidence_id,
            event_anchor=event_anchor,
            artifact=artifact,
            artifact_bytes=artifact_read.content,
            findings=[
                {
                    "code": "strict_evidence_set_contract_invalid",
                    "errors": list(validation.errors),
                }
            ],
        )

    artifact_sha256 = _artifact_sha256(artifact)
    if (
        anchor.get("contract_version") != EVIDENCE_SET_CONTRACT_VERSION
        or anchor.get("evidence_id") != evidence_id
        or anchor.get("target") != artifact["target"]
        or anchor.get("completeness_status") != artifact["completeness"]["status"]
        or type(anchor.get("included_report_count")) is not int
        or anchor["included_report_count"] != len(artifact["included_reports"])
        or type(anchor.get("excluded_report_count")) is not int
        or anchor["excluded_report_count"] != len(artifact["excluded_reports"])
        or anchor.get("summary") != str(row["summary"])
        or not isinstance(anchor.get("artifact_sha256"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", anchor["artifact_sha256"]) is None
    ):
        return _strict_evidence_set_result(
            evidence_id,
            event_anchor=event_anchor,
            artifact=artifact,
            artifact_bytes=artifact_read.content,
            artifact_sha256=artifact_sha256,
            findings=[{"code": "strict_evidence_set_event_mismatch"}],
        )
    if artifact_sha256 != anchor["artifact_sha256"]:
        return _strict_evidence_set_result(
            evidence_id,
            event_anchor=event_anchor,
            artifact=artifact,
            artifact_bytes=artifact_read.content,
            artifact_sha256=artifact_sha256,
            findings=[{"code": "strict_evidence_set_hash_mismatch"}],
        )
    return _strict_evidence_set_result(
        evidence_id,
        event_anchor=event_anchor,
        artifact=artifact,
        artifact_bytes=artifact_read.content,
        artifact_sha256=artifact_sha256,
        findings=[],
    )


def _strict_evidence_set_result(
    evidence_id: str,
    *,
    findings: list[dict[str, Any]],
    event_anchor: dict[str, Any] | None = None,
    artifact: dict[str, Any] | None = None,
    artifact_bytes: bytes | None = None,
    artifact_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": "strict-evidence-set-resolution/v1",
        "evidence_id": evidence_id,
        "ok": not findings,
        "health": "ok" if not findings else "invalid",
        "event_anchor": event_anchor,
        "findings": findings,
        "artifact": artifact,
        "artifact_bytes": artifact_bytes,
        "artifact_sha256": artifact_sha256,
    }


def _strict_evidence_set_file_finding(status: str) -> dict[str, Any]:
    if status.startswith("directory_"):
        code = "strict_evidence_set_directory_invalid"
    else:
        code = f"strict_evidence_set_{status}"
    return {"code": code}


def _build_artifact(
    *,
    work_root_value: str,
    manifest_path: str,
    manifest_sha256: str,
    target: dict[str, str],
    required: list[str],
    reports: list[dict[str, Any]],
    selections: list[dict[str, str]],
) -> dict[str, Any]:
    by_kind = {item["kind"]: item for item in reports}
    selected = {item["kind"]: item for item in selections}
    unknown = sorted(set(selected) - set(by_kind))
    if unknown:
        raise _error(
            "evidence_set_unknown_report_kind",
            "Included Evidence references report kinds absent from the manifest.",
            kinds=unknown,
        )
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for report in reports:
        selection = selected.get(report["kind"])
        if selection is None:
            excluded.append(
                {
                    **report,
                    "required": report["kind"] in required,
                    "reason": "not_selected",
                }
            )
        else:
            included.append(
                {
                    **report,
                    "evidence_id": selection["evidence_id"],
                    "role": selection["role"],
                }
            )
    included.sort(key=lambda item: (item["kind"], item["role"], item["evidence_id"]))
    excluded.sort(key=lambda item: item["kind"])
    included_by_kind = {item["kind"]: item for item in included}
    findings: list[dict[str, Any]] = []
    for kind in required:
        report = by_kind.get(kind)
        included_report = included_by_kind.get(kind)
        if report is None:
            code = "required_report_missing"
            report_path: str | None = None
        elif included_report is None:
            code = "required_report_excluded"
            report_path = report["path"]
        elif included_report["status"] != "pass":
            code = "required_report_not_passing"
            report_path = included_report["path"]
        else:
            continue
        findings.append(
            {"code": code, "kind": kind, "path": report_path, "severity": "error"}
        )
    findings.sort(key=lambda item: (item["code"], item["kind"], item["path"] or ""))
    return {
        "contract_version": EVIDENCE_SET_CONTRACT_VERSION,
        "target": target,
        "work_root": work_root_value,
        "report_manifest": {"path": manifest_path, "sha256": manifest_sha256},
        "required_report_kinds": required,
        "included_reports": included,
        "excluded_reports": excluded,
        "completeness": {
            "status": "complete" if not findings else "incomplete",
            "findings": findings,
        },
    }


def _load_report_manifest(work_root: Path, manifest_path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _error(
            "evidence_set_manifest_invalid_json",
            f"Evidence report manifest is not valid JSON: {manifest_path}",
            path=str(manifest_path),
            line=exc.lineno,
            column=exc.colno,
        ) from exc
    except OSError as exc:
        raise InvalidInputError(
            f"Could not read Evidence report manifest: {manifest_path}",
            details={"path": str(manifest_path), "reason": str(exc)},
        ) from exc
    if not isinstance(value, dict) or set(value) != {"contract_version", "reports"}:
        raise _error(
            "evidence_set_manifest_invalid",
            "Evidence report manifest must contain only contract_version and reports.",
        )
    if value.get("contract_version") != REPORT_MANIFEST_CONTRACT_VERSION:
        raise _error(
            "evidence_set_manifest_invalid",
            f"Evidence report manifest contract_version must be {REPORT_MANIFEST_CONTRACT_VERSION!r}.",
        )
    raw_reports = value.get("reports")
    if not isinstance(raw_reports, list):
        raise _error("evidence_set_manifest_invalid", "Evidence report manifest reports must be an array.")
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_reports):
        if not isinstance(item, dict) or set(item) != {"kind", "path", "status"}:
            raise _error(
                "evidence_set_manifest_invalid",
                f"Evidence report manifest item {index} must contain only kind, path, and status.",
            )
        kind = item.get("kind")
        path_value = item.get("path")
        status = item.get("status")
        if not isinstance(kind, str) or _KIND.fullmatch(kind) is None:
            raise _error(
                "evidence_set_manifest_invalid",
                f"Evidence report manifest item {index} has invalid kind.",
            )
        if kind in seen:
            raise _error(
                "evidence_set_manifest_duplicate_kind",
                f"Evidence report manifest repeats kind: {kind}",
                kind=kind,
            )
        seen.add(kind)
        report_path = _safe_report_path(work_root, path_value, label=f"report item {index}")
        if status not in _REPORT_STATUSES:
            raise _error(
                "evidence_set_manifest_invalid",
                f"Evidence report manifest item {index} has unsupported status.",
            )
        reports.append(
            {
                "kind": kind,
                "path": str(path_value),
                "status": status,
                "sha256": _file_sha256(report_path),
                "size_bytes": report_path.stat().st_size,
            }
        )
    return sorted(reports, key=lambda item: item["kind"])


def _work_root(paths: ProjectPaths, value: str) -> tuple[Path, str]:
    normalized = _required_text(value, "work_root")
    lexical = Path(normalized)
    candidate = lexical if lexical.is_absolute() else paths.root / lexical
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise _error(
            "evidence_set_work_root_missing",
            f"Evidence set work root does not exist: {normalized}",
            path=normalized,
        ) from exc
    project_root = paths.root.resolve()
    _require_within(resolved, project_root, code="evidence_set_work_root_outside_project")
    if not resolved.is_dir():
        raise _error(
            "evidence_set_work_root_not_directory",
            f"Evidence set work root is not a directory: {normalized}",
            path=normalized,
        )
    return resolved, resolved.relative_to(project_root).as_posix()


def _manifest_path(
    paths: ProjectPaths,
    work_root: Path,
    value: str,
) -> tuple[Path, str]:
    normalized = _required_text(value, "manifest")
    lexical = Path(normalized)
    candidate = lexical if lexical.is_absolute() else paths.root / lexical
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise _error(
            "evidence_set_manifest_missing",
            f"Evidence report manifest does not exist: {normalized}",
            path=normalized,
        ) from exc
    _require_within(resolved, work_root, code="evidence_set_manifest_outside_work_root")
    if not resolved.is_file():
        raise _error(
            "evidence_set_manifest_not_file",
            f"Evidence report manifest is not a file: {normalized}",
            path=normalized,
        )
    return resolved, resolved.relative_to(paths.root.resolve()).as_posix()


def _safe_report_path(work_root: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise _error(
            "evidence_set_report_path_invalid",
            f"Evidence {label} path must be a non-empty relative path.",
        )
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
        raise _error(
            "evidence_set_report_path_invalid",
            f"Evidence {label} path must be normalized, relative, and contain no '..': {value}",
            path=value,
        )
    candidate = work_root / Path(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise _error(
            "evidence_set_report_missing",
            f"Evidence report does not exist: {value}",
            path=value,
        ) from exc
    _require_within(resolved, work_root, code="evidence_set_report_outside_work_root")
    if not resolved.is_file():
        raise _error(
            "evidence_set_report_not_file",
            f"Evidence report is not a file: {value}",
            path=value,
        )
    return resolved


def _included_selections(values: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen_kinds: set[str] = set()
    seen_kind_roles: set[tuple[str, str]] = set()
    for value in values:
        if "=" not in value or ":" not in value.rsplit("=", 1)[1]:
            raise _error(
                "evidence_set_include_invalid",
                "--include must use KIND=E-XXXX:ROLE.",
                value=value,
            )
        kind, evidence_and_role = value.split("=", 1)
        evidence_id, role = evidence_and_role.rsplit(":", 1)
        if _KIND.fullmatch(kind) is None or _EVIDENCE_ID.fullmatch(evidence_id) is None or _ROLE.fullmatch(role) is None:
            raise _error(
                "evidence_set_include_invalid",
                "--include must use KIND=E-XXXX:ROLE with normalized kind and role.",
                value=value,
            )
        key = (kind, role)
        if kind in seen_kinds or key in seen_kind_roles:
            raise _error(
                "evidence_set_duplicate_selection",
                f"Evidence set includes duplicate report kind or role mapping: {value}",
                kind=kind,
                role=role,
            )
        seen_kinds.add(kind)
        seen_kind_roles.add(key)
        result.append({"kind": kind, "evidence_id": evidence_id, "role": role})
    return sorted(result, key=lambda item: (item["kind"], item["role"], item["evidence_id"]))


def _required_kinds(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        if _KIND.fullmatch(value) is None:
            raise _error(
                "evidence_set_required_kind_invalid",
                f"Required report kind has invalid format: {value}",
                kind=value,
            )
        normalized.append(value)
    if len(normalized) != len(set(normalized)):
        raise _error(
            "evidence_set_duplicate_required_kind",
            "Required report kinds must be unique.",
            kinds=normalized,
        )
    return sorted(normalized)


def _validate_selected_evidence(
    conn: sqlite3.Connection,
    selections: list[dict[str, str]],
) -> None:
    evidence_ids = sorted({item["evidence_id"] for item in selections})
    if not evidence_ids:
        return
    placeholders = ", ".join("?" for _ in evidence_ids)
    rows = conn.execute(
        f"SELECT id FROM evidence WHERE id IN ({placeholders}) ORDER BY id",
        tuple(evidence_ids),
    ).fetchall()
    found = {str(row["id"]) for row in rows}
    missing = sorted(set(evidence_ids) - found)
    if missing:
        raise _error(
            "evidence_set_unknown_evidence",
            "Evidence set references unknown Evidence IDs.",
            evidence_ids=missing,
        )


def _validate_target(conn: sqlite3.Connection, target: dict[str, str]) -> None:
    table = _TARGET_TABLES.get(target["type"])
    if table is None:
        raise _error(
            "evidence_set_unknown_target_type",
            f"Unsupported Evidence set target type: {target['type']}",
            target=target,
        )
    if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (target["id"],)).fetchone() is None:
        raise _error(
            "evidence_set_unknown_target",
            f"Evidence set target does not exist: {target['type']}:{target['id']}",
            target=target,
        )


def _require_within(path: Path, root: Path, *, code: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise _error(
            code,
            f"Evidence set path escapes its allowed root: {path}",
            path=str(path),
            allowed_root=str(root),
        ) from exc


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_sha256(value: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_evidence_set_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _required_text(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise InvalidInputError(f"{field} must not be empty.", details={"field": field})
    return normalized


def _remove_uncommitted_file(
    conn: sqlite3.Connection,
    temp_path: Path | None,
    final_path: Path | None,
) -> None:
    if getattr(conn, "_authoritative_commit_completed", False):
        return
    for path in (temp_path, final_path):
        if path is not None and path.exists():
            path.unlink()


def _error(code: str, message: str, **details: Any) -> EvidenceSetError:
    return EvidenceSetError(message=message, code=code, details=details)
