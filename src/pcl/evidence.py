from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
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
) -> dict[str, Any]:
    if not paths.loop_dir.exists() or not paths.db_path.exists():
        raise ProjectNotInitializedError(root=str(paths.root))
    if not files:
        raise InvalidInputError("--file is required.", details={"field": "file"})
    summary = summary.strip()
    if not summary:
        raise InvalidInputError("--summary must not be empty.", details={"field": "summary"})

    command = _clean_optional(command)
    members = _adhoc_members(paths, files)
    evidence_type = ADHOC_ARTIFACT_TYPE if len(members) == 1 else ADHOC_BUNDLE_TYPE

    conn = connect(paths.db_path)
    manifest_path: Path | None = None
    tmp_path: Path | None = None
    try:
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        now = utc_now_iso()
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
        tmp_path = manifest_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(manifest_path)
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (evidence_id, evidence_type, relative_manifest_path, command, summary, now),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="adhoc_evidence_recorded",
            entity_type="evidence",
            entity_id=evidence_id,
            payload={
                "contract_version": ADHOC_EVIDENCE_CONTRACT_VERSION,
                "evidence_type": evidence_type,
                "manifest_path": relative_manifest_path,
                "member_count": len(members),
                "members": members,
                "command": command,
            },
        )
        conn.commit()
        return {
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
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
        if manifest_path and manifest_path.exists():
            manifest_path.unlink()
        raise DataStoreError(f"Could not record adhoc evidence: {exc}") from exc
    finally:
        conn.close()


def _adhoc_members(paths: ProjectPaths, files: list[str]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
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
                "size_bytes": stat.st_size,
                "sha256": sha256,
            }
        )
    return members


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


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None
