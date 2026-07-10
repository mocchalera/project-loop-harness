from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import time
from typing import Any

from . import __version__
from .db import connect, connect_mutation, table_exists
from .errors import DataStoreError, EXIT_USAGE, InvalidInputError, PclError, ProjectNotInitializedError
from .events import append_event
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .test_faults import crash_if_requested
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
EVIDENCE_LINK_SUPPORTING_ROLE = "supporting"
EVIDENCE_LINK_TASK_TARGET = "task"
EXECUTION_PROVENANCE_CONTRACT_VERSION = "execution-provenance/v1"
EXECUTION_PROVENANCE_EVIDENCE_TYPE = "execution_provenance"
EXECUTION_PROVENANCE_LINK_ROLE = "execution_provenance"
LEGACY_INLINE_EVIDENCE_WARNING = {
    "code": "legacy_inline_evidence",
    "message": "--evidence is deprecated for terminal proof; use --evidence-id with hash-pinned Evidence.",
}


class EvidenceAddError(PclError):
    def __init__(self, message: str, *, code: str, details: dict[str, Any]) -> None:
        super().__init__(
            message=message,
            code=code,
            exit_code=EXIT_USAGE,
            details=details,
        )


class SkillProvenanceError(PclError):
    def __init__(self, message: str, *, code: str, details: dict[str, Any]) -> None:
        super().__init__(message=message, code=code, exit_code=EXIT_USAGE, details=details)


def inspect_skill_files(paths: ProjectPaths, skill_paths: list[str]) -> list[dict[str, str]]:
    """Validate and hash Skill files without mutating project state."""
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    root = paths.root.resolve()
    for value in skill_paths:
        display = str(Path(value).expanduser().resolve(strict=False))
        descriptor = _redacted_skill_descriptor(paths, Path(display))
        if display in seen:
            raise SkillProvenanceError(
                f"Duplicate Skill path: {descriptor['path_basename']}", code="skill_path_duplicate",
                details=descriptor,
            )
        seen.add(display)
        path = Path(display)
        try:
            before = path.stat()
            if not stat.S_ISREG(before.st_mode):
                raise SkillProvenanceError(
                    f"Skill path is not a regular file: {descriptor['path_basename']}",
                    code="skill_path_not_file", details=descriptor,
                )
            if before.st_mode & 0o444 == 0:
                raise SkillProvenanceError(
                    f"Skill file is not readable: {descriptor['path_basename']}",
                    code="skill_path_unreadable",
                    details={**descriptor, "reason": "no_readable_permission_bits"},
                )
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                content = stream.read()
                after = os.fstat(stream.fileno())
            current = path.stat()
        except SkillProvenanceError:
            raise
        except FileNotFoundError as exc:
            raise SkillProvenanceError(
                f"Skill file does not exist: {descriptor['path_basename']}", code="skill_path_missing",
                details=descriptor,
            ) from exc
        except OSError as exc:
            raise SkillProvenanceError(
                f"Skill file is not readable: {descriptor['path_basename']}", code="skill_path_unreadable",
                details={**descriptor, "reason": "os_error", "errno": exc.errno},
            ) from exc
        def identity(stat_value: os.stat_result) -> tuple[int, int, int, int, int]:
            return (
                stat_value.st_dev,
                stat_value.st_ino,
                stat_value.st_size,
                stat_value.st_mtime_ns,
                stat_value.st_ctime_ns,
            )

        if (
            identity(before) != identity(opened)
            or identity(opened) != identity(after)
            or identity(after) != identity(current)
        ):
            raise SkillProvenanceError(
                f"Skill file changed while it was being read: {descriptor['path_basename']}",
                code="skill_changed_during_read", details=descriptor,
            )
        entries.append({
            "name": _skill_name(path, content),
            "path": display,
            "path_scope": "inside_project" if path.is_relative_to(root) else "outside_project",
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    return entries


def public_skill_entries(skills: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "name": skill["name"],
            "path_basename": Path(skill["path"]).name,
            "path_scope": skill["path_scope"],
            "sha256": skill["sha256"],
        }
        for skill in skills
    ]


def preflight_provenance_destination(paths: ProjectPaths) -> None:
    """Reject known canonical destination collisions before start mutates lifecycle state."""
    directory = paths.evidence_dir / "execution-provenance"
    if os.path.lexists(directory):
        _require_real_canonical_directory(directory, create=False)
    else:
        parent_error = _real_canonical_parent_error(directory.parent)
        if parent_error is not None:
            raise OSError(parent_error)
        return
    conn = connect(paths.db_path)
    try:
        rows = conn.execute("SELECT id FROM evidence WHERE id LIKE 'E-%'").fetchall()
    finally:
        conn.close()
    highest = 0
    for row in rows:
        match = re.fullmatch(r"E-(\d+)", str(row["id"]))
        if match:
            highest = max(highest, int(match.group(1)))
    provenance_id = f"E-{highest + 2:04d}"
    final_path = directory / f"{provenance_id}.json"
    if os.path.lexists(final_path):
        os.lstat(final_path)
        raise OSError(f"provenance artifact already exists: {final_path.name}")


def execution_provenance_document(
    *, skills: list[dict[str, str]], repository_revision: str | None, task_id: str,
) -> dict[str, Any]:
    return {
        "contract_version": EXECUTION_PROVENANCE_CONTRACT_VERSION,
        "producer": {"name": "project-loop-harness", "version": __version__},
        "skills": skills,
        "repository_revision": repository_revision,
        "target": {"type": "task", "id": task_id},
    }


def canonical_provenance_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_provenance_artifact(paths: ProjectPaths, *, evidence_id: str, content: bytes) -> tuple[Path, str]:
    directory = paths.evidence_dir / "execution-provenance"
    _require_real_canonical_directory(directory, create=True)
    final_path = directory / f"{evidence_id}.json"
    if os.path.lexists(final_path):
        os.lstat(final_path)
        raise OSError(f"provenance artifact already exists: {final_path.name}")
    fd, tmp_value = tempfile.mkstemp(prefix=f".{evidence_id}.", suffix=".tmp", dir=directory)
    tmp_path = Path(tmp_value)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if tmp_path.read_bytes() != content:
            raise OSError("temporary provenance artifact verification failed")
        os.replace(tmp_path, final_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return final_path, hashlib.sha256(content).hexdigest()


def assess_execution_provenance(paths: ProjectPaths, *, evidence_id: str) -> dict[str, Any]:
    """Verify event anchor, Evidence row and artifact before following Skill paths."""
    conn = connect(paths.db_path)
    try:
        row = conn.execute("SELECT type, path FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        event_rows = conn.execute(
            "SELECT entity_type, entity_id, payload_json FROM events WHERE event_type = 'work_started' ORDER BY rowid DESC"
        ).fetchall()
        links = conn.execute(
            "SELECT target_type, target_id, link_role FROM evidence_links WHERE evidence_id = ? ORDER BY created_at",
            (evidence_id,),
        ).fetchall()
    finally:
        conn.close()
    anchor = None
    matched_event = None
    for event_row in event_rows:
        try:
            candidate = json.loads(str(event_row["payload_json"])).get("execution_provenance")
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("evidence_id") == evidence_id:
            anchor = candidate
            matched_event = event_row
            break
    base = {"contract_version": EXECUTION_PROVENANCE_CONTRACT_VERSION, "artifact_health": "ok", "skills": []}
    if anchor is None or not isinstance(anchor.get("artifact_sha256"), str):
        return {**base, "artifact_health": "anchor_missing", "reason": "Matching work_started event hash anchor is absent."}
    event_target = anchor.get("target")
    if (
        not isinstance(event_target, dict)
        or event_target.get("type") != "task"
        or not isinstance(event_target.get("id"), str)
        or matched_event is None
        or str(matched_event["entity_type"]) != "task"
        or str(matched_event["entity_id"]) != event_target["id"]
    ):
        return {**base, "artifact_health": "anchor_target_mismatch", "reason": "Event entity and provenance anchor target do not match."}
    if row is None:
        return {**base, "artifact_health": "evidence_missing", "reason": "Anchored Evidence row is absent."}
    if str(row["type"]) != EXECUTION_PROVENANCE_EVIDENCE_TYPE:
        return {**base, "artifact_health": "wrong_evidence_type", "reason": "Anchored Evidence has the wrong type."}
    matching_links = [
        link for link in links
        if str(link["link_role"]) == EXECUTION_PROVENANCE_LINK_ROLE
    ]
    if len(matching_links) != 1 or (
        str(matching_links[0]["target_type"]) != "task"
        or str(matching_links[0]["target_id"]) != event_target["id"]
    ):
        return {**base, "artifact_health": "task_link_mismatch", "reason": "Task provenance link does not match the event anchor target."}
    recorded_path = str(row["path"] or "")
    artifact = _absolute_local_path(paths, recorded_path)
    expected_dir = paths.evidence_dir / "execution-provenance"
    directory_error = _real_canonical_directory_error(expected_dir)
    if directory_error is not None:
        return {**base, "artifact_health": "artifact_directory_invalid", "reason": directory_error}
    if artifact is None or artifact.parent != expected_dir or artifact.name != f"{evidence_id}.json":
        return {**base, "artifact_health": "wrong_evidence_path", "reason": "Evidence path is not the canonical provenance path."}
    try:
        artifact_lstat = os.lstat(artifact)
    except FileNotFoundError:
        return {**base, "artifact_health": "artifact_missing", "reason": "Canonical provenance artifact is absent."}
    except OSError as exc:
        return {**base, "artifact_health": "artifact_unreadable", "reason": str(exc)}
    if stat.S_ISLNK(artifact_lstat.st_mode):
        return {**base, "artifact_health": "artifact_symlink", "reason": "Canonical provenance artifact is a symbolic link."}
    if not stat.S_ISREG(artifact_lstat.st_mode):
        return {**base, "artifact_health": "artifact_not_regular", "reason": "Canonical provenance artifact is not a regular file."}
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(artifact, flags)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or _file_identity(artifact_lstat) != _file_identity(opened):
                return {**base, "artifact_health": "artifact_changed", "reason": "Canonical provenance artifact changed before read."}
            raw = stream.read()
            after = os.fstat(stream.fileno())
        current = os.lstat(artifact)
    except FileNotFoundError:
        return {**base, "artifact_health": "artifact_missing", "reason": "Canonical provenance artifact is absent."}
    except OSError as exc:
        return {**base, "artifact_health": "artifact_unreadable", "reason": f"Could not safely read canonical provenance artifact (errno={exc.errno})."}
    if (
        _file_identity(opened) != _file_identity(after)
        or _file_identity(after) != _file_identity(current)
    ):
        return {**base, "artifact_health": "artifact_changed", "reason": "Canonical provenance artifact changed during read."}
    actual = hashlib.sha256(raw).hexdigest()
    if actual != anchor["artifact_sha256"]:
        return {**base, "artifact_health": "artifact_hash_mismatch", "artifact_sha256": actual, "recorded_artifact_sha256": anchor["artifact_sha256"], "reason": "Artifact bytes do not match the immutable event anchor."}
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {**base, "artifact_health": "artifact_invalid", "reason": str(exc)}
    if not isinstance(document, dict) or document.get("contract_version") != EXECUTION_PROVENANCE_CONTRACT_VERSION or not isinstance(document.get("skills"), list):
        return {**base, "artifact_health": "artifact_invalid", "reason": "Artifact contract is invalid."}
    if document.get("target") != event_target:
        return {**base, "artifact_health": "artifact_target_mismatch", "reason": "Verified artifact target does not match the event anchor target."}
    assessed = []
    for skill in document["skills"]:
        if not isinstance(skill, dict) or not isinstance(skill.get("path"), str) or not isinstance(skill.get("sha256"), str):
            return {**base, "artifact_health": "artifact_invalid", "reason": "Artifact Skill entry is invalid."}
        item = dict(skill)
        try:
            current_path = Path(skill["path"])
            if current_path.stat().st_mode & 0o444 == 0:
                raise PermissionError("Skill file has no readable permission bits.")
            current = hashlib.sha256(current_path.read_bytes()).hexdigest()
            item["current_sha256"] = current
            item["health"] = "ok" if current == skill["sha256"] else "drifted"
            item["reason"] = "Current bytes match the recorded hash." if item["health"] == "ok" else "Current bytes differ from the recorded hash."
        except FileNotFoundError:
            item.update({"current_sha256": None, "health": "missing", "reason": "Recorded Skill path is missing."})
        except OSError as exc:
            item.update({"current_sha256": None, "health": "unreadable", "reason": str(exc)})
        assessed.append(item)
    return {**base, "artifact_sha256": actual, "payload": document, "skills": assessed}


def provenance_presentation(paths: ProjectPaths, *, evidence_id: str) -> dict[str, Any]:
    assessment = assess_execution_provenance(paths, evidence_id=evidence_id)
    return {
        "evidence_id": evidence_id,
        "artifact_health": assessment["artifact_health"],
        "skills": [
            {
                "name": item.get("name"),
                "path_scope": item.get("path_scope"),
                "recorded_sha256": str(item.get("sha256", ""))[:12],
                "health": item.get("health"),
            }
            for item in assessment.get("skills", [])
        ],
    }


def linked_task_provenance(paths: ProjectPaths, *, task_id: str) -> dict[str, Any] | None:
    conn = connect(paths.db_path)
    try:
        evidence_id = newest_linked_evidence_id(
            conn, target_type="task", target_id=task_id,
            link_role=EXECUTION_PROVENANCE_LINK_ROLE,
        )
    finally:
        conn.close()
    return None if evidence_id is None else provenance_presentation(paths, evidence_id=evidence_id)


def _skill_name(path: Path, content: bytes) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return path.parent.name
    if text.startswith("---\n") or text.startswith("---\r\n"):
        for line in text.splitlines()[1:]:
            if line.strip() == "---":
                break
            if line.startswith("name:"):
                value = line.split(":", 1)[1].strip().strip("'\"")
                if value and all(ch.isalnum() or ch in "-_." for ch in value):
                    return value
    return path.parent.name


def _redacted_skill_descriptor(paths: ProjectPaths, path: Path) -> dict[str, str]:
    return {
        "path_basename": path.name,
        "path_scope": "inside_project" if path.is_relative_to(paths.root.resolve()) else "outside_project",
    }


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _real_canonical_directory_error(directory: Path) -> str | None:
    try:
        value = os.lstat(directory)
    except FileNotFoundError:
        return "Canonical provenance directory is missing."
    except OSError as exc:
        return f"Canonical provenance directory cannot be inspected (errno={exc.errno})."
    if stat.S_ISLNK(value.st_mode):
        return "Canonical provenance directory is a symbolic link."
    if not stat.S_ISDIR(value.st_mode):
        return "Canonical provenance directory is not a directory."
    if directory.resolve() != directory.absolute():
        return "Canonical provenance directory is redirected through a symbolic-link parent."
    return None


def _require_real_canonical_directory(directory: Path, *, create: bool) -> None:
    if create and not os.path.lexists(directory):
        parent_error = _real_canonical_parent_error(directory.parent)
        if parent_error is not None:
            raise OSError(parent_error)
        directory.mkdir(parents=True, exist_ok=False)
    error = _real_canonical_directory_error(directory)
    if error is not None:
        raise OSError(error)


def _real_canonical_parent_error(parent: Path) -> str | None:
    try:
        value = os.lstat(parent)
    except FileNotFoundError:
        return "Canonical provenance parent directory is missing."
    except OSError as exc:
        return f"Canonical provenance parent directory cannot be inspected (errno={exc.errno})."
    if stat.S_ISLNK(value.st_mode):
        return "Canonical provenance parent directory is a symbolic link."
    if not stat.S_ISDIR(value.st_mode):
        return "Canonical provenance parent path is not a directory."
    if parent.resolve() != parent.absolute():
        return "Canonical provenance parent directory is redirected through a symbolic-link ancestor."
    return None


def require_healthy_terminal_evidence(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    evidence_id: str,
    error_code: str,
    allowed_types: set[str] | None = None,
) -> sqlite3.Row:
    evidence_id = str(evidence_id or "").strip()
    row = conn.execute(
        "SELECT id, type, path, command, summary, created_at FROM evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if row is None:
        raise EvidenceAddError(
            f"Evidence does not exist: {evidence_id}",
            code=error_code,
            details={"evidence_id": evidence_id, "reason": "missing_evidence"},
        )
    evidence_type = str(row["type"])
    if allowed_types is not None and evidence_type not in allowed_types:
        raise EvidenceAddError(
            f"Evidence {evidence_id} has unsupported type {evidence_type} for this terminal transition.",
            code=error_code,
            details={"evidence_id": evidence_id, "evidence_type": evidence_type, "reason": "wrong_evidence_type"},
        )
    if evidence_type in ADHOC_EVIDENCE_TYPES:
        assessment = assess_adhoc_evidence(
            paths,
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            manifest_path_value=str(row["path"] or ""),
            validate_optional_fields=True,
        )
        if assessment["health"] != "ok":
            raise EvidenceAddError(
                f"Evidence {evidence_id} is not healthy enough for terminal proof.",
                code=error_code,
                details={"evidence_id": evidence_id, "reason": "artifact_unhealthy", "assessment": assessment},
            )
    return row


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

    conn = connect_mutation(paths)
    manifest_path: Path | None = None
    tmp_path: Path | None = None
    final_copy_dir: Path | None = None
    copy_metrics: dict[str, int] = {}
    try:
        transaction_started_at = time.perf_counter()
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        now = utc_now_iso()
        if copy_files:
            final_copy_dir, copy_metrics = _copy_adhoc_members(
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
        crash_if_requested("before_evidence_temp_write")
        tmp_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        crash_if_requested("after_evidence_temp_write_before_rename")
        tmp_path.replace(manifest_path)
        crash_if_requested("after_evidence_rename_before_commit")
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
            insert_evidence_link(
                conn,
                evidence_id=evidence_id,
                target_type=EVIDENCE_LINK_TASK_TARGET,
                target_id=linked_task_id,
                link_role=EVIDENCE_LINK_SUPPORTING_ROLE,
                created_at=now,
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
        if copy_files:
            event_payload.update(copy_metrics)
            event_payload["write_transaction_pre_event_duration_ms"] = _duration_ms(transaction_started_at)
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
        if not table_exists(conn, "evidence_links"):
            migrate_command = f"pcl migrate --root {paths.root}"
            raise EvidenceAddError(
                "Evidence task links require schema migration 007_evidence_links. "
                f"Run `{migrate_command}`.",
                code="evidence_links_requires_migration",
                details={
                    "task_id": task_id,
                    "required_schema_version": 7,
                    "migration": "007_evidence_links",
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


def insert_evidence_link(
    conn: sqlite3.Connection,
    *,
    evidence_id: str,
    target_type: str,
    target_id: str,
    link_role: str,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (evidence_id, target_type, target_id, link_role, created_at),
    )


def newest_linked_evidence_id(
    conn: sqlite3.Connection,
    *,
    target_type: str,
    target_id: str,
    link_role: str,
) -> str | None:
    if not table_exists(conn, "evidence_links"):
        return None
    row = conn.execute(
        """
        SELECT evidence_id
        FROM evidence_links
        WHERE target_type = ?
          AND target_id = ?
          AND link_role = ?
        ORDER BY created_at DESC, evidence_id DESC
        LIMIT 1
        """,
        (target_type, target_id, link_role),
    ).fetchone()
    return None if row is None else str(row["evidence_id"])


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
        else:
            try:
                actual_source_sha256 = _sha256_file(absolute_source_path)
            except OSError:
                findings.append(
                    {
                        "code": "source_drifted",
                        "path": member_path,
                        "detail": "missing",
                    }
                )
            else:
                if actual_source_sha256 != expected_sha256:
                    findings.append(
                        {
                            "code": "source_drifted",
                            "path": member_path,
                            "detail": "hash_mismatch",
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
) -> tuple[Path, dict[str, int]]:
    started_at = time.perf_counter()
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
    return final_dir, {
        "copy_duration_ms": _duration_ms(started_at),
        "copied_total_bytes": sum(int(member["size_bytes"]) for member in members),
    }


def _duration_ms(started_at: float) -> int:
    return max(0, int(round((time.perf_counter() - started_at) * 1000)))


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
