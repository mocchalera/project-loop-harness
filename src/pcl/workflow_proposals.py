from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .db import connect, connect_mutation
from .errors import InvalidInputError
from .events import append_event
from .guards import require_initialized
from .paths import ProjectPaths
from .workflow_proposal_validation import PROPOSAL_ID_RE, validate_workflow_proposal_text
from .workflow_verifier import verify_workflow_text

TERMINAL_PROPOSAL_EVENTS = {
    "workflow_proposal_approved": "approved",
    "workflow_proposal_cancelled": "cancelled",
}
PROPOSAL_STATUSES = {"proposed", "approved", "cancelled", "unknown"}


def propose_workflow(paths: ProjectPaths, *, source_path: str, summary: str = "") -> dict[str, Any]:
    require_initialized(paths)
    source = _resolve_source_path(paths, source_path)
    if not source.exists() or not source.is_file():
        raise InvalidInputError(
            f"Workflow proposal source does not exist: {source_path}",
            details={"source_path": source_path},
        )
    text = source.read_text(encoding="utf-8")
    data = validate_workflow_proposal_text(text, source_label=str(source))

    paths.workflow_proposals_dir.mkdir(parents=True, exist_ok=True)
    conn = connect_mutation(paths)
    try:
        proposal_id = _next_proposal_id(conn, paths.workflow_proposals_dir)
        proposal_path = paths.workflow_proposals_dir / f"{proposal_id}.yaml"
        proposal_path.write_text(_normalize_proposal_text(text), encoding="utf-8")
        relative_path = str(proposal_path.relative_to(paths.root))
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_proposed",
            entity_type="workflow_proposal",
            entity_id=proposal_id,
            payload={
                "workflow_id": data["id"],
                "path": relative_path,
                "source_path": _display_path(paths, source),
                "summary": summary,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": proposal_id,
            "workflow_id": str(data["id"]),
            "path": relative_path,
            "status": "proposed",
            "summary": summary,
        }
    finally:
        conn.close()


def approve_workflow_proposal(paths: ProjectPaths, proposal_id: str, *, summary: str = "") -> dict[str, Any]:
    require_initialized(paths)
    _validate_proposal_id(proposal_id)
    path = paths.workflow_proposals_dir / f"{proposal_id}.yaml"
    if not path.exists():
        raise InvalidInputError(
            f"Workflow proposal does not exist: {proposal_id}",
            details={"proposal_id": proposal_id, "path": str(path)},
        )

    text = path.read_text(encoding="utf-8")
    data = validate_workflow_proposal_text(text, source_label=str(path))
    workflow_id = str(data["id"])
    workflow_path = paths.workflows_dir / f"{workflow_id}.yaml"
    temp_workflow_path = _approval_temp_path(workflow_path, proposal_id)
    normalized_text = _normalize_proposal_text(text)
    content_sha256 = _sha256_text(normalized_text)
    verification = verify_workflow_text(
        normalized_text,
        source_label=str(path.relative_to(paths.root)),
        path=str(path.relative_to(paths.root)),
        target_type="workflow_proposal",
        target_id=proposal_id,
    )
    if not verification["ok"]:
        raise InvalidInputError(
            f"Workflow proposal failed verification: {proposal_id}",
            details={
                "proposal_id": proposal_id,
                "errors": verification["errors"],
                "warnings": verification["warnings"],
            },
        )

    conn = connect_mutation(paths)
    try:
        events = _proposal_events_by_id(conn)
        event_group = events.get(proposal_id, {})
        _require_proposed_status(proposal_id, event_group, action="approve")
        if workflow_path.exists():
            raise InvalidInputError(
                f"Workflow template already exists: {workflow_id}",
                details={
                    "proposal_id": proposal_id,
                    "workflow_id": workflow_id,
                    "workflow_path": str(workflow_path),
                },
            )

        paths.workflows_dir.mkdir(parents=True, exist_ok=True)
        temp_workflow_path.unlink(missing_ok=True)
        temp_workflow_path.write_text(normalized_text, encoding="utf-8")
        proposal_relative_path = str(path.relative_to(paths.root))
        workflow_relative_path = str(workflow_path.relative_to(paths.root))
        try:
            append_event(
                conn=conn,
                events_path=paths.events_path,
                event_type="workflow_proposal_approved",
                entity_type="workflow_proposal",
                entity_id=proposal_id,
                payload={
                    "workflow_id": workflow_id,
                    "proposal_path": proposal_relative_path,
                    "workflow_path": workflow_relative_path,
                    "summary": summary,
                    "content_sha256": content_sha256,
                    "verification": _verification_event_payload(verification),
                },
            )
            conn.commit()
            temp_workflow_path.replace(workflow_path)
        except Exception:
            temp_workflow_path.unlink(missing_ok=True)
            raise
        return {
            "ok": True,
            "id": proposal_id,
            "workflow_id": workflow_id,
            "path": proposal_relative_path,
            "workflow_path": workflow_relative_path,
            "status": "approved",
            "summary": summary,
            "content_sha256": content_sha256,
            "verification": verification,
        }
    finally:
        conn.close()


def cancel_workflow_proposal(paths: ProjectPaths, proposal_id: str, *, summary: str = "") -> dict[str, Any]:
    require_initialized(paths)
    _validate_proposal_id(proposal_id)
    path = paths.workflow_proposals_dir / f"{proposal_id}.yaml"
    if not path.exists():
        raise InvalidInputError(
            f"Workflow proposal does not exist: {proposal_id}",
            details={"proposal_id": proposal_id, "path": str(path)},
        )

    text = path.read_text(encoding="utf-8")
    data = validate_workflow_proposal_text(text, source_label=str(path))
    conn = connect_mutation(paths)
    try:
        events = _proposal_events_by_id(conn)
        event_group = events.get(proposal_id, {})
        _require_proposed_status(proposal_id, event_group, action="cancel")
        relative_path = str(path.relative_to(paths.root))
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_proposal_cancelled",
            entity_type="workflow_proposal",
            entity_id=proposal_id,
            payload={
                "workflow_id": str(data["id"]),
                "proposal_path": relative_path,
                "summary": summary,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": proposal_id,
            "workflow_id": str(data["id"]),
            "path": relative_path,
            "workflow_path": "",
            "status": "cancelled",
            "summary": summary,
        }
    finally:
        conn.close()


def list_workflow_proposals(
    paths: ProjectPaths,
    *,
    status: str | None = None,
    validate: bool = True,
) -> list[dict[str, Any]]:
    require_initialized(paths)
    if status is not None and status not in PROPOSAL_STATUSES:
        raise InvalidInputError(
            f"Invalid workflow proposal status: {status}",
            details={"status": status, "allowed": sorted(PROPOSAL_STATUSES)},
        )
    if not paths.workflow_proposals_dir.exists():
        return []
    conn = connect(paths.db_path)
    try:
        events = _proposal_events_by_id(conn)
    finally:
        conn.close()
    proposals = []
    for path in sorted(paths.workflow_proposals_dir.glob("WP-*.yaml"), key=lambda item: item.name):
        proposal_id = path.stem
        proposal = _proposal_record(paths, path, events.get(proposal_id, {}), validate=validate)
        if status is not None and proposal["status"] != status:
            continue
        proposals.append(proposal)
    return proposals


def next_reviewable_workflow_proposal(paths: ProjectPaths) -> dict[str, Any] | None:
    require_initialized(paths)
    proposals = list_workflow_proposals(paths, validate=False)
    for proposal in sorted(proposals, key=lambda item: (str(item.get("created_at") or ""), str(item.get("id") or ""))):
        if proposal.get("status") == "proposed":
            return proposal
    return None


def read_workflow_proposal(
    paths: ProjectPaths,
    proposal_id: str,
    *,
    validate: bool = True,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_proposal_id(proposal_id)
    path = paths.workflow_proposals_dir / f"{proposal_id}.yaml"
    if not path.exists():
        raise InvalidInputError(
            f"Workflow proposal does not exist: {proposal_id}",
            details={"proposal_id": proposal_id, "path": str(path)},
        )
    conn = connect(paths.db_path)
    try:
        events = _proposal_events_by_id(conn)
    finally:
        conn.close()
    record = _proposal_record(paths, path, events.get(proposal_id, {}), validate=validate)
    record["content"] = path.read_text(encoding="utf-8")
    return record


def _proposal_record(
    paths: ProjectPaths,
    path: Path,
    event: dict[str, Any],
    *,
    validate: bool,
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    parse_error = ""
    data: dict[str, Any] = {}
    try:
        data = validate_workflow_proposal_text(text, source_label=str(path))
    except InvalidInputError as exc:
        if validate:
            raise
        parse_error = str(exc)
    proposed_event = _event_of_type(event, "workflow_proposed")
    terminal_event = _terminal_event(event)
    proposed_payload = _payload(proposed_event)
    terminal_payload = _payload(terminal_event)
    status = _status_from_event_group(event)
    return {
        "id": path.stem,
        "workflow_id": str(data.get("id") or proposed_payload.get("workflow_id") or terminal_payload.get("workflow_id") or ""),
        "path": str(path.relative_to(paths.root)),
        "workflow_path": str(terminal_payload.get("workflow_path") or ""),
        "status": status,
        "summary": str(proposed_payload.get("summary") or ""),
        "review_summary": str(terminal_payload.get("summary") or ""),
        "created_at": str(proposed_event.get("created_at") or "") if proposed_event else "",
        "reviewed_at": str(terminal_event.get("created_at") or "") if terminal_event else "",
        "content_sha256": str(terminal_payload.get("content_sha256") or ""),
        "parse_error": parse_error,
        "data": data,
    }


def _next_proposal_id(conn, proposals_dir: Path) -> str:
    max_n = 0
    if proposals_dir.exists():
        for path in proposals_dir.glob("WP-*.yaml"):
            match = PROPOSAL_ID_RE.match(path.stem)
            if match:
                max_n = max(max_n, int(match.group(1)))
    rows = conn.execute(
        """
        SELECT entity_id FROM events
        WHERE entity_type = 'workflow_proposal'
          AND entity_id LIKE 'WP-%'
        """
    ).fetchall()
    for row in rows:
        match = PROPOSAL_ID_RE.match(str(row["entity_id"] or ""))
        if match:
            max_n = max(max_n, int(match.group(1)))
    return f"WP-{max_n + 1:04d}"


def _proposal_events_by_id(conn) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_type, entity_id, payload_json, created_at
        FROM events
        WHERE event_type IN (
          'workflow_proposed',
          'workflow_proposal_approved',
          'workflow_proposal_cancelled'
        )
          AND entity_type = 'workflow_proposal'
        ORDER BY rowid
        """
    ).fetchall()
    events = {}
    for row in rows:
        proposal_id = str(row["entity_id"] or "")
        if not PROPOSAL_ID_RE.match(proposal_id):
            continue
        event = {
            "event_type": str(row["event_type"] or ""),
            "created_at": str(row["created_at"] or ""),
            "payload": _json_object(row["payload_json"]),
        }
        events.setdefault(proposal_id, {"events": []})["events"].append(event)
    return events


def _require_proposed_status(proposal_id: str, event_group: dict[str, Any], *, action: str) -> None:
    if not _event_of_type(event_group, "workflow_proposed"):
        raise InvalidInputError(
            f"Workflow proposal has no workflow_proposed event: {proposal_id}",
            details={"proposal_id": proposal_id},
        )
    status = _status_from_event_group(event_group)
    if status != "proposed":
        raise InvalidInputError(
            f"Cannot {action} workflow proposal {proposal_id} from status {status}.",
            details={"proposal_id": proposal_id, "status": status, "expected_status": "proposed"},
        )


def _status_from_event_group(event_group: dict[str, Any]) -> str:
    terminal_event = _terminal_event(event_group)
    if terminal_event:
        return TERMINAL_PROPOSAL_EVENTS[str(terminal_event.get("event_type") or "")]
    if _event_of_type(event_group, "workflow_proposed"):
        return "proposed"
    return "unknown"


def _terminal_event(event_group: dict[str, Any]) -> dict[str, Any] | None:
    events = event_group.get("events", []) if isinstance(event_group, dict) else []
    terminal_events = [
        event
        for event in events
        if isinstance(event, dict) and str(event.get("event_type") or "") in TERMINAL_PROPOSAL_EVENTS
    ]
    return terminal_events[-1] if terminal_events else None


def _event_of_type(event_group: dict[str, Any], event_type: str) -> dict[str, Any] | None:
    events = event_group.get("events", []) if isinstance(event_group, dict) else []
    for event in events:
        if isinstance(event, dict) and event.get("event_type") == event_type:
            return event
    return None


def _payload(event: dict[str, Any] | None) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event, dict) else None
    return payload if isinstance(payload, dict) else {}


def _validate_proposal_id(proposal_id: str) -> None:
    if not PROPOSAL_ID_RE.match(proposal_id):
        raise InvalidInputError(
            f"Invalid workflow proposal id: {proposal_id}",
            details={"proposal_id": proposal_id},
        )


def _resolve_source_path(paths: ProjectPaths, source_path: str) -> Path:
    path = Path(source_path)
    return path if path.is_absolute() else paths.root / path


def _display_path(paths: ProjectPaths, path: Path) -> str:
    try:
        return str(path.relative_to(paths.root))
    except ValueError:
        return str(path)


def _normalize_proposal_text(text: str) -> str:
    return text.strip() + "\n"


def _approval_temp_path(workflow_path: Path, proposal_id: str) -> Path:
    return workflow_path.with_name(f".{workflow_path.name}.{proposal_id}.tmp")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _verification_event_payload(verification: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": verification["contract_version"],
        "ok": verification["ok"],
        "errors": list(verification["errors"]),
        "warnings": list(verification["warnings"]),
        "check_count": len(verification["checks"]),
    }


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
