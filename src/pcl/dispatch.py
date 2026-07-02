from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .db import connect
from .errors import InvalidInputError
from .escalations import open_escalation
from .events import append_event
from .guards import require_initialized
from .paths import ProjectPaths
from .timeutil import utc_now_iso
from .validators import _simple_yaml_section


DEFAULT_LEASE_TTL_SECONDS = 1800
DEFAULT_MAX_LEASE_ATTEMPTS = 2


def assign_job(paths: ProjectPaths, *, job_id: str, agent_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(job_id, "job_id")
    _validate_identifier(agent_id, "agent_id")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        job = _get_job(conn, job_id)
        agent = _get_agent(conn, agent_id)
        _require_job_status(job, "queued")
        _require_agent_active(agent_id, str(agent["status"]))
        previous_agent_id = job["assigned_agent_id"]
        conn.execute(
            "UPDATE agent_jobs SET assigned_agent_id = ? WHERE id = ?",
            (agent_id, job_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="job_assigned",
            entity_type="agent_job",
            entity_id=job_id,
            payload={
                "workflow_run_id": job["workflow_run_id"],
                "agent_id": agent_id,
                "previous_agent_id": previous_agent_id,
                "assigned_at": now,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "job_id": job_id,
            "workflow_run_id": job["workflow_run_id"],
            "assigned_agent_id": agent_id,
            "previous_agent_id": previous_agent_id,
        }
    finally:
        conn.close()


def lease_job(
    paths: ProjectPaths,
    *,
    job_id: str,
    agent_id: str,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(job_id, "job_id")
    _validate_identifier(agent_id, "agent_id")
    ttl = _lease_ttl_seconds(paths, ttl_seconds)
    now = utc_now_iso()
    lease_expires_at = _add_seconds(now, ttl)

    conn = connect(paths.db_path)
    try:
        job = _get_job(conn, job_id)
        agent = _get_agent(conn, agent_id)
        _require_job_status(job, "queued")
        _require_agent_active(agent_id, str(agent["status"]))
        assigned_agent_id = job["assigned_agent_id"]
        if assigned_agent_id and assigned_agent_id != agent_id:
            raise InvalidInputError(
                f"Agent job {job_id} is assigned to {assigned_agent_id}, not {agent_id}.",
                details={
                    "job_id": job_id,
                    "assigned_agent_id": assigned_agent_id,
                    "agent_id": agent_id,
                },
            )
        active_count = _active_lease_count(conn, agent_id, now=now)
        max_concurrency = int(agent["max_concurrency"])
        if active_count >= max_concurrency:
            raise InvalidInputError(
                f"Agent {agent_id} has reached max_concurrency {max_concurrency}.",
                details={
                    "agent_id": agent_id,
                    "active_lease_count": active_count,
                    "max_concurrency": max_concurrency,
                },
            )
        workflow_started = _start_workflow_run_if_needed(
            conn,
            paths,
            workflow_run_id=str(job["workflow_run_id"]),
            now=now,
        )
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = ?,
                assigned_agent_id = ?,
                started_at = COALESCE(started_at, ?),
                lease_expires_at = ?,
                last_heartbeat_at = ?
            WHERE id = ?
            """,
            ("running", agent_id, now, lease_expires_at, now, job_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="job_leased",
            entity_type="agent_job",
            entity_id=job_id,
            payload={
                "workflow_run_id": job["workflow_run_id"],
                "agent_id": agent_id,
                "assigned_during_lease": assigned_agent_id is None,
                "ttl_seconds": ttl,
                "lease_expires_at": lease_expires_at,
                "last_heartbeat_at": now,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "job_id": job_id,
            "workflow_run_id": job["workflow_run_id"],
            "assigned_agent_id": agent_id,
            "status": "running",
            "ttl_seconds": ttl,
            "lease_expires_at": lease_expires_at,
            "last_heartbeat_at": now,
            "workflow_started": workflow_started,
        }
    finally:
        conn.close()


def heartbeat_job(
    paths: ProjectPaths,
    *,
    job_id: str,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(job_id, "job_id")
    ttl = _lease_ttl_seconds(paths, ttl_seconds)
    now = utc_now_iso()
    lease_expires_at = _add_seconds(now, ttl)

    conn = connect(paths.db_path)
    try:
        job = _get_job(conn, job_id)
        _require_job_status(job, "running")
        _require_unexpired_lease(job, now=now)
        conn.execute(
            """
            UPDATE agent_jobs
            SET lease_expires_at = ?, last_heartbeat_at = ?
            WHERE id = ?
            """,
            (lease_expires_at, now, job_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="job_heartbeat",
            entity_type="agent_job",
            entity_id=job_id,
            payload={
                "workflow_run_id": job["workflow_run_id"],
                "agent_id": job["assigned_agent_id"],
                "ttl_seconds": ttl,
                "lease_expires_at": lease_expires_at,
                "last_heartbeat_at": now,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "job_id": job_id,
            "workflow_run_id": job["workflow_run_id"],
            "assigned_agent_id": job["assigned_agent_id"],
            "ttl_seconds": ttl,
            "lease_expires_at": lease_expires_at,
            "last_heartbeat_at": now,
        }
    finally:
        conn.close()


def release_job(paths: ProjectPaths, *, job_id: str, reason: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(job_id, "job_id")
    cleaned_reason = _require_text(reason, "--reason is required to release a job lease.")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        job = _get_job(conn, job_id)
        _require_job_status(job, "running")
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = ?, lease_expires_at = NULL, last_heartbeat_at = NULL
            WHERE id = ?
            """,
            ("queued", job_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="job_released",
            entity_type="agent_job",
            entity_id=job_id,
            payload={
                "workflow_run_id": job["workflow_run_id"],
                "agent_id": job["assigned_agent_id"],
                "reason": cleaned_reason,
                "released_at": now,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "job_id": job_id,
            "workflow_run_id": job["workflow_run_id"],
            "assigned_agent_id": job["assigned_agent_id"],
            "status": "queued",
            "reason": cleaned_reason,
        }
    finally:
        conn.close()


def reap_expired_leases(paths: ProjectPaths) -> dict[str, Any]:
    require_initialized(paths)
    now = utc_now_iso()
    max_attempts = _max_lease_attempts(paths)
    reaped: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            """
            SELECT
              agent_jobs.id,
              agent_jobs.workflow_run_id,
              agent_jobs.status,
              agent_jobs.assigned_agent_id,
              agent_jobs.lease_expires_at,
              agent_jobs.attempts,
              agents.name AS agent_name
            FROM agent_jobs
            LEFT JOIN agents ON agents.id = agent_jobs.assigned_agent_id
            WHERE agent_jobs.status = 'running'
              AND agent_jobs.lease_expires_at IS NOT NULL
              AND agent_jobs.lease_expires_at <= ?
            ORDER BY agent_jobs.id
            """,
            (now,),
        ).fetchall()
        for row in rows:
            job = dict(row)
            job_id = str(job["id"])
            attempts = int(job["attempts"] or 0) + 1
            agent_id = str(job["assigned_agent_id"] or "")
            if attempts < max_attempts:
                conn.execute(
                    """
                    UPDATE agent_jobs
                    SET status = ?,
                        attempts = ?,
                        lease_expires_at = NULL,
                        last_heartbeat_at = NULL
                    WHERE id = ?
                    """,
                    ("queued", attempts, job_id),
                )
                payload = {
                    "workflow_run_id": job["workflow_run_id"],
                    "agent_id": agent_id or None,
                    "lease_expires_at": job["lease_expires_at"],
                    "attempts": attempts,
                    "max_lease_attempts": max_attempts,
                    "status": "queued",
                }
                append_event(
                    conn=conn,
                    events_path=paths.events_path,
                    event_type="job_lease_expired",
                    entity_type="agent_job",
                    entity_id=job_id,
                    payload=payload,
                )
                reaped.append({"job_id": job_id, **payload})
            else:
                conn.execute(
                    """
                    UPDATE agent_jobs
                    SET status = ?,
                        attempts = ?,
                        lease_expires_at = NULL,
                        last_heartbeat_at = NULL
                    WHERE id = ?
                    """,
                    ("blocked", attempts, job_id),
                )
                payload = {
                    "workflow_run_id": job["workflow_run_id"],
                    "agent_id": agent_id or None,
                    "agent_name": job["agent_name"],
                    "lease_expires_at": job["lease_expires_at"],
                    "attempts": attempts,
                    "max_lease_attempts": max_attempts,
                    "status": "blocked",
                }
                append_event(
                    conn=conn,
                    events_path=paths.events_path,
                    event_type="job_lease_exhausted",
                    entity_type="agent_job",
                    entity_id=job_id,
                    payload=payload,
                )
                blocked.append({"job_id": job_id, **payload})
        conn.commit()
    finally:
        conn.close()

    escalations: list[dict[str, Any]] = []
    for item in blocked:
        escalation = open_escalation(
            paths,
            workflow_run_id=str(item["workflow_run_id"]),
            severity="high",
            question=(
                f"Agent job {item['job_id']} exhausted its lease attempts while assigned "
                f"to {item.get('agent_id') or 'unassigned agent'}."
            ),
            recommendation=(
                f"Reassign {item['job_id']} to another active agent or investigate "
                f"{item.get('agent_id') or 'the previous agent'} before retrying."
            ),
        )
        escalations.append(escalation)

    return {
        "ok": True,
        "reaped": reaped,
        "blocked": blocked,
        "reaped_job_ids": [item["job_id"] for item in reaped],
        "blocked_job_ids": [item["job_id"] for item in blocked],
        "escalations": escalations,
        "max_lease_attempts": max_attempts,
    }


def expired_lease_job_ids(paths: ProjectPaths) -> list[str]:
    require_initialized(paths)
    now = utc_now_iso()
    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            """
            SELECT id
            FROM agent_jobs
            WHERE status = 'running'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at <= ?
            ORDER BY id
            """,
            (now,),
        ).fetchall()
        return [str(row["id"]) for row in rows]
    finally:
        conn.close()


def _get_job(conn, job_id: str):
    row = conn.execute(
        """
        SELECT
          id,
          workflow_run_id,
          status,
          assigned_agent_id,
          lease_expires_at,
          last_heartbeat_at,
          attempts
        FROM agent_jobs
        WHERE id = ?
        """,
        (job_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(f"Agent job does not exist: {job_id}", details={"job_id": job_id})
    return row


def _get_agent(conn, agent_id: str):
    row = conn.execute(
        """
        SELECT id, name, role, adapter, max_concurrency, status
        FROM agents
        WHERE id = ?
        """,
        (agent_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(f"Agent does not exist: {agent_id}", details={"agent_id": agent_id})
    return row


def _active_lease_count(conn, agent_id: str, *, now: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM agent_jobs
        WHERE assigned_agent_id = ?
          AND status = 'running'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at > ?
        """,
        (agent_id, now),
    ).fetchone()
    return int(row["count"])


def _start_workflow_run_if_needed(
    conn,
    paths: ProjectPaths,
    *,
    workflow_run_id: str,
    now: str,
) -> bool:
    row = conn.execute(
        "SELECT id, status FROM workflow_runs WHERE id = ?",
        (workflow_run_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Workflow run does not exist: {workflow_run_id}",
            details={"workflow_run_id": workflow_run_id},
        )
    if row["status"] != "queued":
        return False
    conn.execute(
        "UPDATE workflow_runs SET status = ? WHERE id = ?",
        ("running", workflow_run_id),
    )
    append_event(
        conn=conn,
        events_path=paths.events_path,
        event_type="workflow_run_started",
        entity_type="workflow_run",
        entity_id=workflow_run_id,
        payload={"started_at": now},
    )
    return True


def _require_unexpired_lease(job, *, now: str) -> None:
    if not job["assigned_agent_id"] or not job["lease_expires_at"]:
        raise InvalidInputError(
            f"Agent job {job['id']} does not have an active lease.",
            details={"job_id": job["id"]},
        )
    if str(job["lease_expires_at"]) <= now:
        raise InvalidInputError(
            f"Agent job {job['id']} lease expired; run `pcl jobs reap` before heartbeating.",
            details={
                "job_id": job["id"],
                "lease_expires_at": job["lease_expires_at"],
                "command": "pcl jobs reap",
            },
        )


def _require_job_status(job, status: str) -> None:
    if job["status"] != status:
        raise InvalidInputError(
            f"Agent job {job['id']} must be {status}; current status is {job['status']}.",
            details={"job_id": job["id"], "status": job["status"], "required_status": status},
        )


def _require_agent_active(agent_id: str, status: str) -> None:
    if status != "active":
        raise InvalidInputError(
            f"Agent {agent_id} must be active; current status is {status}.",
            details={"agent_id": agent_id, "status": status},
        )


def _lease_ttl_seconds(paths: ProjectPaths, override: int | None) -> int:
    if override is not None:
        ttl = int(override)
    else:
        ttl = _loop_int(paths, "lease_ttl_seconds", DEFAULT_LEASE_TTL_SECONDS)
    if ttl < 0:
        raise InvalidInputError(
            "ttl_seconds must be at least 0.",
            details={"ttl_seconds": ttl},
        )
    return ttl


def _max_lease_attempts(paths: ProjectPaths) -> int:
    value = _loop_int(paths, "max_lease_attempts", DEFAULT_MAX_LEASE_ATTEMPTS)
    return max(1, value)


def _loop_int(paths: ProjectPaths, key: str, default: int) -> int:
    config_path = paths.root / "pcl.yaml"
    if not config_path.exists():
        return default
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return default
    raw = _simple_yaml_section(lines, "loop").get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _add_seconds(iso_timestamp: str, seconds: int) -> str:
    return (datetime.fromisoformat(iso_timestamp) + timedelta(seconds=seconds)).isoformat()


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
