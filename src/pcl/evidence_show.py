from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .db import connect
from .errors import EXIT_USAGE, PclError
from .guards import require_initialized
from .paths import ProjectPaths


EVIDENCE_ID_RE = re.compile(r"^E-[0-9]{4,}$")
MANIFEST_EVIDENCE_TYPES = {"adhoc_artifact", "adhoc_bundle"}


class EvidenceShowError(PclError):
    def __init__(self, message: str, *, code: str, details: dict[str, Any]) -> None:
        super().__init__(message=message, code=code, exit_code=EXIT_USAGE, details=details)


def show_evidence(paths: ProjectPaths, evidence_id: str) -> dict[str, Any]:
    """Resolve one Evidence row and supported manifest metadata without inlining bodies."""

    require_initialized(paths)
    if EVIDENCE_ID_RE.fullmatch(evidence_id) is None:
        raise EvidenceShowError(
            f"Invalid Evidence id: {evidence_id}",
            code="invalid_evidence_id",
            details={"evidence_id": evidence_id, "expected": "E-XXXX"},
        )
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, type, summary, command, path, created_at
            FROM evidence
            WHERE id = ?
            """,
            (evidence_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise EvidenceShowError(
            f"Evidence does not exist: {evidence_id}",
            code="evidence_not_found",
            details={"evidence_id": evidence_id},
        )

    evidence = {
        "id": str(row["id"]),
        "type": str(row["type"]),
        "summary": row["summary"],
        "claimed_command": row["command"],
        "recorded_path": str(row["path"]),
        "created_at": str(row["created_at"]),
    }
    manifest = _manifest_metadata(
        paths,
        evidence_type=evidence["type"],
        path=evidence["recorded_path"],
    )
    if manifest is not None:
        evidence["manifest"] = manifest
    return {"ok": True, "evidence": evidence}


def render_evidence_metadata(payload: dict[str, Any]) -> str:
    evidence = payload["evidence"]
    lines = [
        f"Evidence {evidence['id']}",
        f"type: {evidence['type']}",
        f"summary: {evidence['summary'] or ''}",
        f"claimed_command: {evidence['claimed_command'] or ''}",
        f"recorded_path: {evidence['recorded_path']}",
        f"created_at: {evidence['created_at']}",
    ]
    manifest = evidence.get("manifest")
    if isinstance(manifest, dict):
        lines.append(f"manifest_contract_version: {manifest['contract_version']}")
        for member in manifest["members"]:
            line = f"member: {member['path']} sha256:{member['sha256']}"
            if member.get("stored_path"):
                line += f" stored_path:{member['stored_path']}"
            lines.append(line)
    return "\n".join(lines) + "\n"


def _manifest_metadata(
    paths: ProjectPaths,
    *,
    evidence_type: str,
    path: str,
) -> dict[str, Any] | None:
    if evidence_type not in MANIFEST_EVIDENCE_TYPES or path.startswith("inline:"):
        return None
    manifest_path = Path(path)
    if not manifest_path.is_absolute():
        manifest_path = paths.root / manifest_path
    try:
        resolved = manifest_path.resolve()
        if not resolved.is_relative_to(paths.root.resolve()):
            return None
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("contract_version") != "adhoc-evidence/v0":
        return None
    members = payload.get("members")
    if not isinstance(members, list):
        return None
    public_members = []
    for member in members:
        if not isinstance(member, dict):
            return None
        member_path = member.get("path")
        digest = member.get("sha256")
        if not isinstance(member_path, str) or not isinstance(digest, str):
            return None
        public_member = {"path": member_path, "sha256": digest}
        stored_path = member.get("stored_path")
        if isinstance(stored_path, str):
            public_member["stored_path"] = stored_path
        public_members.append(public_member)
    return {"contract_version": "adhoc-evidence/v0", "members": public_members}
