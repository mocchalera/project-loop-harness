from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any

from .db import connect
from .errors import DataStoreError, EXIT_USAGE, InvalidInputError, PclError, ProjectNotInitializedError
from .events import append_event
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso


ADHOC_EVIDENCE_CONTRACT_VERSION = "adhoc-evidence/v0"
ADHOC_ARTIFACT_TYPE = "adhoc_artifact"
ADHOC_BUNDLE_TYPE = "adhoc_bundle"
ADHOC_EVIDENCE_TYPES = {ADHOC_ARTIFACT_TYPE, ADHOC_BUNDLE_TYPE}
ADHOC_ERROR_FINDING_CODES = {
    "manifest_not_local",
    "manifest_missing",
    "manifest_not_file",
    "manifest_corrupt",
    "contract_version_unsupported",
    "evidence_id_mismatch",
    "evidence_type_mismatch",
    "members_invalid",
    "member_entry_invalid",
    "sensitive_path_warning_count_invalid",
}
ADHOC_WARNING_FINDING_CODES = {
    "member_missing",
    "member_hash_mismatch",
    "member_outside_project_root",
    "copy_missing",
    "copy_hash_mismatch",
    "source_drifted",
}
ADHOC_PATH_SCOPES = {"in_project", "outside_project"}
ADHOC_COPY_STORAGE_MODE = "copied"
DEFAULT_EVIDENCE_COPY_MAX_MEMBER_BYTES = 10_000_000
EVIDENCE_TASK_LINK_REQUIRED_SCHEMA_VERSION = 6
EVIDENCE_TASK_LINK_MIGRATION_ID = "006_evidence_task_link"


class EvidenceAddError(PclError):
    def __init__(self, message: str, *, code: str, details: dict[str, Any]) -> None:
        super().__init__(
            message=message,
            code=code,
            exit_code=EXIT_USAGE,
            details=details,
        )


def record_inline_evidence(
    conn: sqlite3.Connection,
    *,
    evidence_type: str,
    summary: str,
    context: str,
    command: str | None = None,
) -> str:
    evidence_id = next_prefixed_id(conn, "evidence", "E")
    conn.execute(
        """
        INSERT INTO evidence(id, type, path, command, summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (evidence_id, evidence_type, f"inline:{context}", command, summary, utc_now_iso()),
    )
    return evidence_id


def record_adhoc_evidence(
    paths: ProjectPaths,
    *,
    files: list[str],
    summary: str,
    command: str | None = None,
    allow_sensitive_evidence: bool = False,
    copy_files: bool = False,
    task_id: str | None = None,
) -> dict[str, Any]:
    if not paths.loop_dir.exists() or not paths.db_path.exists():
        raise ProjectNotInitializedError(root=str(paths.root))
    if not files:
        raise InvalidInputError("--file is required.", details={"field": "file"})
    summary = summary.strip()
    if not summary:
        raise InvalidInputError("--summary must not be empty.", details={"field": "summary"})

    command = _clean_optional(command)
    linked_task_id = _validate_linked_task(paths, task_id)
    members, source_paths, warnings, sensitive_path_warning_count = _adhoc_members(
        paths,
        files,
        allow_sensitive_evidence=allow_sensitive_evidence,
        copy_files=copy_files,
    )
    if copy_files:
        warnings.extend(_copy_size_warnings_or_raise(paths, members))
    evidence_type = ADHOC_ARTIFACT_TYPE if len(members) == 1 else ADHOC_BUNDLE_TYPE
    include_sensitive_count = allow_sensitive_evidence or sensitive_path_warning_count > 0

    conn = connect(paths.db_path)
    manifest_path: Path | None = None
    tmp_path: Path | None = None
    final_copy_dir: Path | None = None
    try:
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        now = utc_now_iso()
        if copy_files:
            final_copy_dir = _copy_adhoc_members(
                paths,
                evidence_id=evidence_id,
                members=members,
                source_paths=source_paths,
            )
        manifest_dir = paths.evidence_dir / "adhoc"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"{evidence_id.lower()}-adhoc-v0.json"
        relative_manifest_path = _relative_path(paths.root, manifest_path)
        manifest = {
            "contract_version": ADHOC_EVIDENCE_CONTRACT_VERSION,
            "evidence_id": evidence_id,
            "evidence_type": evidence_type,
            "created_at": now,
            "members": members,
        }
        if include_sensitive_count:
            manifest["sensitive_path_warning_count"] = sensitive_path_warning_count
        tmp_path = manifest_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(manifest_path)
        if linked_task_id:
            conn.execute(
                """
                INSERT INTO evidence(id, type, path, command, summary, created_at, linked_task_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    evidence_type,
                    relative_manifest_path,
                    command,
                    summary,
                    now,
                    linked_task_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO evidence(id, type, path, command, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (evidence_id, evidence_type, relative_manifest_path, command, summary, now),
            )
        event_payload = {
            "contract_version": ADHOC_EVIDENCE_CONTRACT_VERSION,
            "evidence_type": evidence_type,
            "manifest_path": relative_manifest_path,
            "member_count": len(members),
            "members": members,
            "command": command,
        }
        if linked_task_id:
            event_payload["linked_task_id"] = linked_task_id
        if include_sensitive_count:
            event_payload["sensitive_path_warning_count"] = sensitive_path_warning_count
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="adhoc_evidence_recorded",
            entity_type="evidence",
            entity_id=evidence_id,
            payload=event_payload,
        )
        conn.commit()
        result = {
            "ok": True,
            "evidence": {
                "id": evidence_id,
                "type": evidence_type,
                "manifest_path": relative_manifest_path,
                "summary": summary,
                "command": command,
                "created_at": now,
                "members": members,
            },
        }
        if linked_task_id:
            result["evidence"]["linked_task_id"] = linked_task_id
        if include_sensitive_count:
            result["evidence"]["sensitive_path_warning_count"] = sensitive_path_warning_count
        if warnings:
            result["warnings"] = warnings
        return result
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
        if manifest_path and manifest_path.exists():
            manifest_path.unlink()
        if final_copy_dir and final_copy_dir.exists():
            shutil.rmtree(final_copy_dir, ignore_errors=True)
        raise DataStoreError(f"Could not record adhoc evidence: {exc}") from exc
    finally:
        conn.close()


def _validate_linked_task(paths: ProjectPaths, task_id: str | None) -> str | None:
    task_id = _clean_optional(task_id)
    if task_id is None:
        return None
    if not all(ch.isalnum() or ch in {"_", "-"} for ch in task_id):
        raise EvidenceAddError(
            f"Invalid task id for evidence link: {task_id}",
            code="evidence_add_invalid_task",
            details={"field": "task", "task_id": task_id},
        )
    conn = connect(paths.db_path)
    try:
        if not _table_has_column(conn, "evidence", "linked_task_id"):
            migrate_command = f"pcl migrate --root {paths.root}"
            raise EvidenceAddError(
                "Evidence task links require schema migration "
                f"{EVIDENCE_TASK_LINK_MIGRATION_ID}. Run `{migrate_command}`.",
                code="evidence_task_link_requires_migration",
                details={
                    "task_id": task_id,
                    "required_schema_version": EVIDENCE_TASK_LINK_REQUIRED_SCHEMA_VERSION,
                    "migration": EVIDENCE_TASK_LINK_MIGRATION_ID,
                    "command": migrate_command,
                },
            )
        row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise EvidenceAddError(
            f"Task does not exist: {task_id}",
            code="evidence_add_unknown_task",
            details={"task_id": task_id},
        )
    return task_id


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def assess_adhoc_evidence(
    paths: ProjectPaths,
    *,
    evidence_id: str,
    evidence_type: str,
    manifest_path_value: str,
    validate_optional_fields: bool = False,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    normalized_manifest_path = str(manifest_path_value or "").strip()
    manifest_path = _absolute_local_path(paths, normalized_manifest_path)
    if manifest_path is None:
        findings.append(
            {
                "code": "manifest_not_local",
                "path": normalized_manifest_path,
            }
        )
        return _adhoc_assessment(findings)
    if not manifest_path.exists():
        findings.append(
            {
                "code": "manifest_missing",
                "path": normalized_manifest_path,
            }
        )
        return _adhoc_assessment(findings)
    if not manifest_path.is_file():
        findings.append(
            {
                "code": "manifest_not_file",
                "path": normalized_manifest_path,
            }
        )
        return _adhoc_assessment(findings)

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        findings.append(
            {
                "code": "manifest_corrupt",
                "path": normalized_manifest_path,
                "detail": str(exc),
            }
        )
        return _adhoc_assessment(findings)
    if not isinstance(payload, dict):
        findings.append(
            {
                "code": "manifest_corrupt",
                "detail": "root must be an object",
            }
        )
        return _adhoc_assessment(findings)
    contract_version = payload.get("contract_version")
    if contract_version != ADHOC_EVIDENCE_CONTRACT_VERSION:
        findings.append(
            {
                "code": "contract_version_unsupported",
                "detail": repr(contract_version),
            }
        )
        return _adhoc_assessment(findings)
    manifest_evidence_id = payload.get("evidence_id")
    if manifest_evidence_id != evidence_id:
        findings.append(
            {
                "code": "evidence_id_mismatch",
                "detail": repr(manifest_evidence_id),
            }
        )
        return _adhoc_assessment(findings)
    manifest_evidence_type = payload.get("evidence_type")
    if manifest_evidence_type != evidence_type:
        findings.append(
            {
                "code": "evidence_type_mismatch",
                "detail": repr(manifest_evidence_type),
            }
        )
        return _adhoc_assessment(findings)
    members = payload.get("members")
    if not isinstance(members, list) or not members:
        findings.append({"code": "members_invalid"})
        return _adhoc_assessment(findings)
    if validate_optional_fields:
        sensitive_count = payload.get("sensitive_path_warning_count")
        if sensitive_count is not None and (type(sensitive_count) is not int or sensitive_count < 0):
            findings.append(
                {
                    "code": "sensitive_path_warning_count_invalid",
                    "detail": repr(sensitive_count),
                }
            )

    findings.extend(_assess_adhoc_members(paths, members, validate_optional_fields=validate_optional_fields))
    return _adhoc_assessment(findings)


def _assess_adhoc_members(
    paths: ProjectPaths,
    members: list[Any],
    *,
    validate_optional_fields: bool = False,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, member in enumerate(members, start=1):
        if not isinstance(member, dict):
            findings.append(
                {
                    "code": "member_entry_invalid",
                    "index": index,
                    "detail": "must_be_object",
                }
            )
            continue
        member_path = member.get("path")
        size_bytes = member.get("size_bytes")
        expected_sha256 = member.get("sha256")
        if not isinstance(member_path, str) or not member_path.strip():
            findings.append(
                {
                    "code": "member_entry_invalid",
                    "index": index,
                    "detail": "path_invalid",
                }
            )
            continue
        member_path = member_path.strip()
        if Path(member_path).is_absolute():
            findings.append(
                {
                    "code": "member_entry_invalid",
                    "path": member_path,
                    "detail": "path_absolute",
                }
            )
            continue
        if member_path in seen_paths:
            findings.append(
                {
                    "code": "member_entry_invalid",
                    "path": member_path,
                    "detail": "path_duplicated",
                }
            )
            continue
        seen_paths.add(member_path)
        if validate_optional_fields:
            path_scope = member.get("path_scope")
            if path_scope is not None and path_scope not in ADHOC_PATH_SCOPES:
                findings.append(
                    {
                        "code": "member_entry_invalid",
                        "path": member_path,
                        "detail": "path_scope_invalid",
                    }
                )
                continue
            sensitive_pattern = member.get("sensitive_pattern")
            if sensitive_pattern is not None and not isinstance(sensitive_pattern, str):
                findings.append(
                    {
                        "code": "member_entry_invalid",
                        "path": member_path,
                        "detail": "sensitive_pattern_invalid",
                    }
                )
                continue
        if member_path.startswith("../"):
            findings.append(
                {
                    "code": "member_outside_project_root",
                    "path": member_path,
                }
            )
        if not isinstance(size_bytes, int) or size_bytes < 0:
            findings.append(
                {
                    "code": "member_entry_invalid",
                    "path": member_path,
                    "detail": "size_bytes_invalid",
                }
            )
            continue
        if not isinstance(expected_sha256, str) or not _is_sha256_hex(expected_sha256):
            findings.append(
                {
                    "code": "member_entry_invalid",
                    "path": member_path,
                    "detail": "sha256_invalid",
                }
            )
            continue

        storage_mode = member.get("storage_mode")
        stored_path = member.get("stored_path")
        if storage_mode is None and stored_path is None:
            findings.extend(_assess_reference_member(paths, member_path, expected_sha256))
            continue
        if storage_mode != ADHOC_COPY_STORAGE_MODE:
            findings.append(
                {
                    "code": "member_entry_invalid",
                    "path": member_path,
                    "detail": "storage_mode_invalid",
                }
            )
            continue
        if not isinstance(stored_path, str) or not stored_path.strip() or Path(stored_path).is_absolute():
            findings.append(
                {
                    "code": "member_entry_invalid",
                    "path": member_path,
                    "detail": "stored_path_invalid",
                }
            )
            continue
        stored_path = stored_path.strip()
        if _is_virtual_or_external_path(stored_path):
            findings.append(
                {
                    "code": "member_entry_invalid",
                    "path": member_path,
                    "detail": "stored_path_invalid",
                }
            )
            continue
        findings.extend(
            _assess_copied_member(
                paths,
                member_path=member_path,
                stored_path=stored_path,
                size_bytes=size_bytes,
                expected_sha256=expected_sha256,
            )
        )
    return findings


def _assess_reference_member(paths: ProjectPaths, member_path: str, expected_sha256: str) -> list[dict[str, Any]]:
    absolute_member_path = (paths.root / member_path).resolve()
    if not absolute_member_path.exists() or not absolute_member_path.is_file():
        return [
            {
                "code": "member_missing",
                "path": member_path,
            }
        ]
    try:
        actual_sha256 = _sha256_file(absolute_member_path)
    except OSError:
        return [
            {
                "code": "member_missing",
                "path": member_path,
            }
        ]
    if actual_sha256 != expected_sha256:
        return [
            {
                "code": "member_hash_mismatch",
                "path": member_path,
            }
        ]
    return []


def _assess_copied_member(
    paths: ProjectPaths,
    *,
    member_path: str,
    stored_path: str,
    size_bytes: int,
    expected_sha256: str,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    absolute_copy_path = (paths.root / stored_path).resolve()
    if not absolute_copy_path.exists() or not absolute_copy_path.is_file():
        findings.append(
            {
                "code": "copy_missing",
                "path": stored_path,
                "source_path": member_path,
            }
        )
    else:
        try:
            actual_copy_sha256 = _sha256_file(absolute_copy_path)
        except OSError:
            findings.append(
                {
                    "code": "copy_missing",
                    "path": stored_path,
                    "source_path": member_path,
                }
            )
        else:
            if actual_copy_sha256 != expected_sha256:
                findings.append(
                    {
                        "code": "copy_hash_mismatch",
                        "path": stored_path,
                        "source_path": member_path,
                    }
                )

    absolute_source_path = (paths.root / member_path).resolve()
    try:
        source_stat = absolute_source_path.stat()
    except OSError:
        findings.append(
            {
                "code": "source_drifted",
                "path": member_path,
                "detail": "missing",
            }
        )
    else:
        if not absolute_source_path.is_file():
            findings.append(
                {
                    "code": "source_drifted",
                    "path": member_path,
                    "detail": "missing",
                }
            )
        elif source_stat.st_size != size_bytes:
            findings.append(
                {
                    "code": "source_drifted",
                    "path": member_path,
                    "detail": "size_mismatch",
                }
            )
    return findings


def _adhoc_assessment(findings: list[dict[str, Any]]) -> dict[str, Any]:
    if any(str(finding.get("code")) in ADHOC_ERROR_FINDING_CODES for finding in findings):
        health = "error"
    elif any(str(finding.get("code")) in ADHOC_WARNING_FINDING_CODES for finding in findings):
        health = "warning"
    else:
        health = "ok"
    return {
        "health": health,
        "findings": findings,
    }


def _adhoc_members(
    paths: ProjectPaths,
    files: list[str],
    *,
    allow_sensitive_evidence: bool,
    copy_files: bool,
) -> tuple[list[dict[str, Any]], list[Path], list[str], int]:
    members: list[dict[str, Any]] = []
    source_paths: list[Path] = []
    seen: dict[Path, str] = {}
    for raw_path in files:
        path_text = str(raw_path).strip()
        if not path_text:
            raise EvidenceAddError(
                "Evidence file path must not be empty.",
                code="evidence_add_missing_file",
                details={"path": raw_path},
            )
        path = Path(path_text)
        absolute_path = path if path.is_absolute() else paths.root / path
        if not absolute_path.exists():
            raise EvidenceAddError(
                f"Evidence file does not exist: {path_text}",
                code="evidence_add_missing_file",
                details={"path": path_text},
            )
        try:
            resolved = absolute_path.resolve()
        except OSError as exc:
            raise EvidenceAddError(
                f"Evidence file is unreadable: {path_text}",
                code="evidence_add_unreadable_file",
                details={"path": path_text, "reason": str(exc)},
            ) from exc
        if resolved in seen:
            raise EvidenceAddError(
                f"Duplicate evidence file path: {path_text}",
                code="evidence_add_duplicate_path",
                details={"path": path_text, "first_path": seen[resolved]},
            )
        seen[resolved] = path_text
        if not resolved.is_file():
            raise EvidenceAddError(
                f"Evidence file is not a readable file: {path_text}",
                code="evidence_add_unreadable_file",
                details={"path": path_text},
            )
        try:
            stat = resolved.stat()
            sha256 = _sha256_file(resolved)
        except OSError as exc:
            raise EvidenceAddError(
                f"Evidence file is unreadable: {path_text}",
                code="evidence_add_unreadable_file",
                details={"path": path_text, "reason": str(exc)},
            ) from exc
        members.append(
            {
                "path": _relative_path(paths.root, resolved),
                "path_scope": _path_scope(paths.root, resolved),
                "size_bytes": stat.st_size,
                "sha256": sha256,
            }
        )
        source_paths.append(resolved)

    sensitive_matches = _sensitive_path_matches(paths.root, members)
    if sensitive_matches and not allow_sensitive_evidence:
        raise EvidenceAddError(
            "Evidence file path matches a sensitive filename pattern. "
            "PLH checks path shapes only and does not scan file contents; "
            "pass --allow-sensitive-evidence to record this explicit caller decision.",
            code="evidence_add_sensitive_path",
            details={
                "matches": sensitive_matches,
                "allow_flag": "--allow-sensitive-evidence",
                "content_scanning": False,
            },
        )

    warnings: list[str] = []
    sensitive_count = 0
    if sensitive_matches:
        sensitive_by_path = {match["path"]: match["pattern"] for match in sensitive_matches}
        for member in members:
            pattern = sensitive_by_path.get(str(member["path"]))
            if pattern:
                member["sensitive_pattern"] = pattern
                sensitive_count += 1
                warnings.append(_sensitive_path_warning(str(member["path"]), pattern, copy_files=copy_files))

    outside_paths = [str(member["path"]) for member in members if member.get("path_scope") == "outside_project"]
    if outside_paths and _configured_allow_outside_root(paths.root) is False:
        raise EvidenceAddError(
            "Evidence file path is outside the project root.",
            code="evidence_add_outside_root",
            details={
                "paths": outside_paths,
                "config": "evidence.allow_outside_root",
            },
        )
    warnings.extend(_outside_project_warning(path) for path in outside_paths)
    return members, source_paths, warnings, sensitive_count


def _copy_size_warnings_or_raise(paths: ProjectPaths, members: list[dict[str, Any]]) -> list[str]:
    copy_max_member_bytes = _configured_copy_max_member_bytes(paths.root)
    warnings: list[str] = []
    for member in members:
        size_bytes = int(member["size_bytes"])
        member_path = str(member["path"])
        if size_bytes > copy_max_member_bytes:
            raise EvidenceAddError(
                f"Evidence member is too large to copy: {member_path}",
                code="evidence_copy_member_too_large",
                details={
                    "path": member_path,
                    "size_bytes": size_bytes,
                    "copy_max_member_bytes": copy_max_member_bytes,
                    "config": "evidence.copy_max_member_bytes",
                },
            )
        if size_bytes * 2 > copy_max_member_bytes:
            warnings.append(
                "large_evidence_member: "
                f"{member_path} is {size_bytes} bytes, over half the configured copy cap "
                f"({copy_max_member_bytes} bytes)"
            )
    return warnings


def _copy_adhoc_members(
    paths: ProjectPaths,
    *,
    evidence_id: str,
    members: list[dict[str, Any]],
    source_paths: list[Path],
) -> Path:
    final_dir = paths.evidence_dir / "adhoc-files" / evidence_id.lower()
    tmp_parent = paths.loop_dir / "tmp"
    try:
        tmp_parent.mkdir(parents=True, exist_ok=True)
        stage_dir = Path(tempfile.mkdtemp(prefix=f"{evidence_id.lower()}-adhoc-files-", dir=tmp_parent))
    except OSError as exc:
        raise DataStoreError(f"Could not stage adhoc evidence copies: {exc}") from exc

    stored_paths: list[str] = []
    try:
        for index, (member, source_path) in enumerate(zip(members, source_paths, strict=True), start=1):
            target_name = f"{index:02d}-{source_path.name}"
            staged_path = stage_dir / target_name
            try:
                shutil.copyfile(source_path, staged_path)
                actual_sha256 = _sha256_file(staged_path)
            except OSError as exc:
                raise EvidenceAddError(
                    f"Could not copy evidence member: {member['path']}",
                    code="evidence_copy_failed",
                    details={"path": member["path"], "reason": str(exc)},
                ) from exc
            if actual_sha256 != member["sha256"]:
                raise EvidenceAddError(
                    f"Evidence member changed while being copied: {member['path']}",
                    code="evidence_copy_hash_mismatch",
                    details={
                        "path": member["path"],
                        "expected_sha256": member["sha256"],
                        "actual_sha256": actual_sha256,
                    },
                )
            stored_paths.append(_relative_path(paths.root, final_dir / target_name))
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        if final_dir.exists():
            raise DataStoreError(f"Could not store adhoc evidence copies: destination exists at {final_dir}")
        stage_dir.replace(final_dir)
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise

    for member, stored_path in zip(members, stored_paths, strict=True):
        member["storage_mode"] = ADHOC_COPY_STORAGE_MODE
        member["stored_path"] = stored_path
    return final_dir


def _sensitive_path_matches(root: Path, members: list[dict[str, Any]]) -> list[dict[str, str]]:
    from .code_context import DEFAULT_SENSITIVE_EXCLUDES, _configured_yaml_list, _path_pattern_matches

    patterns = (*DEFAULT_SENSITIVE_EXCLUDES, *(_configured_yaml_list(root, "evidence", "sensitive_exclude") or []))
    matches: list[dict[str, str]] = []
    for member in members:
        member_path = str(member["path"])
        basename = Path(member_path).name
        for pattern in patterns:
            if _path_pattern_matches(pattern, member_path) or _path_pattern_matches(pattern, basename):
                matches.append({"path": member_path, "pattern": pattern})
                break
    return matches


def _configured_allow_outside_root(root: Path) -> bool:
    configured = _configured_yaml_scalar(root, "evidence", "allow_outside_root")
    if configured is None:
        return True
    normalized = configured.strip().strip("\"'").lower()
    if normalized == "false":
        return False
    if normalized == "true":
        return True
    return True


def _configured_copy_max_member_bytes(root: Path) -> int:
    configured = _configured_yaml_scalar(root, "evidence", "copy_max_member_bytes")
    if configured is None:
        return DEFAULT_EVIDENCE_COPY_MAX_MEMBER_BYTES
    normalized = configured.strip().strip("\"'")
    try:
        value = int(normalized)
    except ValueError:
        return DEFAULT_EVIDENCE_COPY_MAX_MEMBER_BYTES
    if value <= 0:
        return DEFAULT_EVIDENCE_COPY_MAX_MEMBER_BYTES
    return value


def _configured_yaml_scalar(root: Path, section: str, key: str) -> str | None:
    config_path = root / "pcl.yaml"
    if not config_path.exists():
        return None
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    in_section = False
    section_indent = 0
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if indent == 0 and stripped.startswith(f"{section}:"):
            in_section = True
            section_indent = indent
            continue
        if in_section and indent <= section_indent:
            break
        if not in_section:
            continue
        if stripped.startswith(f"{key}:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _path_scope(root: Path, path: Path) -> str:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return "outside_project"
    return "in_project"


def _outside_project_warning(path: str) -> str:
    return f"evidence member outside project root: {path}"


def _sensitive_path_warning(path: str, pattern: str, *, copy_files: bool) -> str:
    warning = (
        "evidence member matches sensitive filename pattern: "
        f"{path} (pattern: {pattern}); PLH checks path shapes only and does not scan file contents"
    )
    if copy_files:
        warning += "; copying amplifies exposure because the file will also live under .project-loop/evidence"
    return warning


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        try:
            return os.path.relpath(resolved_path, resolved_root).replace(os.sep, "/")
        except ValueError:
            return resolved_path.as_posix()


def _absolute_local_path(paths: ProjectPaths, path_value: str) -> Path | None:
    normalized = path_value.strip()
    if not normalized or _is_virtual_or_external_path(normalized):
        return None
    path = Path(normalized)
    return path if path.is_absolute() else paths.root / path


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_virtual_or_external_path(value: str) -> bool:
    if value.startswith("inline:"):
        return True
    if ":" not in value:
        return False
    scheme = value.split(":", 1)[0]
    return bool(scheme) and scheme[0].isalpha() and all(
        char.isalnum() or char in {"+", "-", "."} for char in scheme
    )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None
