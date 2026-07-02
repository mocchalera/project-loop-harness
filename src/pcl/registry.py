from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any

from .agents import ADAPTERS
from .db import connect
from .errors import InvalidInputError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso


AGENT_STATUSES = {"active", "paused", "retired"}
UPDATABLE_AGENT_STATUSES = {"active", "paused"}

AGENT_COLUMNS = (
    "id",
    "name",
    "role",
    "adapter",
    "max_concurrency",
    "status",
    "metadata_json",
    "created_at",
    "updated_at",
)
AGENT_FIELDS = ", ".join(AGENT_COLUMNS)


def register_agent(
    paths: ProjectPaths,
    *,
    name: str,
    role: str,
    adapter: str,
    max_concurrency: int = 1,
    metadata_json: str = "{}",
) -> dict[str, Any]:
    require_initialized(paths)
    cleaned_name = _require_text(name, "--name is required to register an agent.")
    cleaned_role = _require_text(role, "--role is required to register an agent.")
    _require_adapter(adapter)
    _require_max_concurrency(max_concurrency)
    metadata = _normalized_json_object(metadata_json, "metadata-json")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        if _agent_name_exists(conn, cleaned_name):
            raise InvalidInputError(
                f"Agent name already exists: {cleaned_name}",
                details={"name": cleaned_name},
            )
        agent_id = next_prefixed_id(conn, "agents", "A")
        conn.execute(
            """
            INSERT INTO agents(
              id, name, role, adapter, max_concurrency, status, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                cleaned_name,
                cleaned_role,
                adapter,
                int(max_concurrency),
                "active",
                metadata,
                now,
                now,
            ),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="agent_registered",
            entity_type="agent",
            entity_id=agent_id,
            payload={
                "name": cleaned_name,
                "role": cleaned_role,
                "adapter": adapter,
                "max_concurrency": int(max_concurrency),
                "status": "active",
                "metadata_json": metadata,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": agent_id,
            "name": cleaned_name,
            "role": cleaned_role,
            "adapter": adapter,
            "max_concurrency": int(max_concurrency),
            "status": "active",
            "metadata_json": metadata,
            "created_at": now,
            "updated_at": now,
        }
    finally:
        conn.close()


def list_agents(paths: ProjectPaths, *, status: str | None = None) -> list[dict[str, Any]]:
    require_initialized(paths)
    if status is not None:
        _require_status(status)

    conn = connect(paths.db_path)
    try:
        if status is None:
            rows = conn.execute(
                f"""
                SELECT {AGENT_FIELDS}
                FROM agents
                ORDER BY id
                """
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT {AGENT_FIELDS}
                FROM agents
                WHERE status = ?
                ORDER BY id
                """,
                (status,),
            ).fetchall()
        agents = [dict(row) for row in rows]
        _enrich_agents_with_active_leases(conn, agents)
        return agents
    finally:
        conn.close()


def read_agent(paths: ProjectPaths, agent_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(agent_id, "agent_id")
    conn = connect(paths.db_path)
    try:
        agent = dict(_get_agent(conn, agent_id))
        _enrich_agents_with_active_leases(conn, [agent])
        return agent
    finally:
        conn.close()


def update_agent(
    paths: ProjectPaths,
    agent_id: str,
    *,
    fields: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(agent_id, "agent_id")
    cleaned_reason = _require_text(reason, "--reason is required to update an agent.")
    updates = _normalized_update_fields(fields)
    if not updates:
        raise InvalidInputError(
            "At least one agent field is required to update an agent.",
            details={"agent_id": agent_id},
        )
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        before = dict(_get_agent(conn, agent_id))
        if "name" in updates and updates["name"] != before["name"] and _agent_name_exists(
            conn,
            str(updates["name"]),
        ):
            raise InvalidInputError(
                f"Agent name already exists: {updates['name']}",
                details={"name": updates["name"]},
            )
        assignments = [f"{column} = ?" for column in updates]
        values = list(updates.values())
        values.extend([now, agent_id])
        conn.execute(
            f"""
            UPDATE agents
            SET {", ".join(assignments)}, updated_at = ?
            WHERE id = ?
            """,
            tuple(values),
        )
        after = dict(_get_agent(conn, agent_id))
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="agent_updated",
            entity_type="agent",
            entity_id=agent_id,
            payload={
                "reason": cleaned_reason,
                "updated_fields": sorted(updates),
                "before": _agent_payload(before),
                "after": _agent_payload(after),
            },
        )
        conn.commit()
        _enrich_agents_with_active_leases(conn, [after])
        return {"ok": True, "agent": after, "reason": cleaned_reason}
    finally:
        conn.close()


def retire_agent(paths: ProjectPaths, agent_id: str, *, reason: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(agent_id, "agent_id")
    cleaned_reason = _require_text(reason, "--reason is required to retire an agent.")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        agent = dict(_get_agent(conn, agent_id))
        active_job_ids = _active_lease_job_ids(conn, agent_id)
        if active_job_ids:
            raise InvalidInputError(
                f"Agent {agent_id} cannot be retired while it holds active leases.",
                details={"agent_id": agent_id, "active_job_ids": active_job_ids},
            )
        if agent["status"] == "retired":
            raise InvalidInputError(
                f"Agent {agent_id} is already retired.",
                details={"agent_id": agent_id},
            )
        previous_status = str(agent["status"])
        conn.execute(
            "UPDATE agents SET status = ?, updated_at = ? WHERE id = ?",
            ("retired", now, agent_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="agent_retired",
            entity_type="agent",
            entity_id=agent_id,
            payload={
                "reason": cleaned_reason,
                "previous_status": previous_status,
                "status": "retired",
            },
        )
        conn.commit()
        retired = dict(_get_agent(conn, agent_id))
        retired["active_lease_count"] = 0
        retired["active_job_ids"] = []
        return {"ok": True, "agent": retired, "reason": cleaned_reason}
    finally:
        conn.close()


def _get_agent(conn, agent_id: str):
    row = conn.execute(
        f"""
        SELECT {AGENT_FIELDS}
        FROM agents
        WHERE id = ?
        """,
        (agent_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(f"Agent does not exist: {agent_id}", details={"agent_id": agent_id})
    return row


def _agent_name_exists(conn, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM agents WHERE name = ?", (name,)).fetchone()
    return row is not None


def _enrich_agents_with_active_leases(conn, agents: list[dict[str, Any]]) -> None:
    for agent in agents:
        active_job_ids = _active_lease_job_ids(conn, str(agent["id"]))
        agent["active_lease_count"] = len(active_job_ids)
        agent["active_job_ids"] = active_job_ids


def _active_lease_job_ids(conn, agent_id: str) -> list[str]:
    now = utc_now_iso()
    rows = conn.execute(
        """
        SELECT id
        FROM agent_jobs
        WHERE assigned_agent_id = ?
          AND status = 'running'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at > ?
        ORDER BY id
        """,
        (agent_id, now),
    ).fetchall()
    return [str(row["id"]) for row in rows]


def _normalized_update_fields(fields: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if "name" in fields and fields["name"] is not None:
        updates["name"] = _require_text(str(fields["name"]), "--name cannot be empty.")
    if "role" in fields and fields["role"] is not None:
        updates["role"] = _require_text(str(fields["role"]), "--role cannot be empty.")
    if "adapter" in fields and fields["adapter"] is not None:
        adapter = str(fields["adapter"])
        _require_adapter(adapter)
        updates["adapter"] = adapter
    if "max_concurrency" in fields and fields["max_concurrency"] is not None:
        max_concurrency = int(fields["max_concurrency"])
        _require_max_concurrency(max_concurrency)
        updates["max_concurrency"] = max_concurrency
    if "metadata_json" in fields and fields["metadata_json"] is not None:
        updates["metadata_json"] = _normalized_json_object(str(fields["metadata_json"]), "metadata-json")
    if "status" in fields and fields["status"] is not None:
        status = str(fields["status"])
        if status == "retired":
            raise InvalidInputError("Use `pcl agent retire` to retire an agent.")
        if status not in UPDATABLE_AGENT_STATUSES:
            raise InvalidInputError(
                f"Invalid agent status: {status}",
                details={"status": status, "allowed": sorted(UPDATABLE_AGENT_STATUSES)},
            )
        updates["status"] = status
    return updates


def _agent_payload(agent: dict[str, Any]) -> dict[str, Any]:
    return {column: agent[column] for column in AGENT_COLUMNS if column in agent}


def _normalized_json_object(raw: str, field_name: str) -> str:
    try:
        value = json.loads(raw)
    except JSONDecodeError as exc:
        raise InvalidInputError(
            f"{field_name} must be valid JSON: {exc.msg}.",
            details={"field": field_name, "position": exc.pos},
        ) from exc
    if not isinstance(value, dict):
        raise InvalidInputError(
            f"{field_name} must be a JSON object.",
            details={"field": field_name, "type": type(value).__name__},
        )
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _require_adapter(adapter: str) -> None:
    if adapter not in ADAPTERS:
        raise InvalidInputError(
            f"Unknown agent adapter: {adapter}",
            details={"adapter": adapter, "available": sorted(ADAPTERS)},
        )


def _require_status(status: str) -> None:
    if status not in AGENT_STATUSES:
        raise InvalidInputError(
            f"Invalid agent status: {status}",
            details={"status": status, "allowed": sorted(AGENT_STATUSES)},
        )


def _require_max_concurrency(max_concurrency: int) -> None:
    if int(max_concurrency) < 1:
        raise InvalidInputError(
            "max_concurrency must be at least 1.",
            details={"max_concurrency": max_concurrency},
        )


def _require_text(value: str, message: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InvalidInputError(message)
    return cleaned


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or not all(c.isalnum() or c in {"_", "-"} for c in value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={"field": field_name, "value": value},
        )
