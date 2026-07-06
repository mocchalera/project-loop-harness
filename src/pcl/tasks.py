from __future__ import annotations

from typing import Any

from .db import connect
from .errors import InvalidInputError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso


TASK_STATUSES = {"todo", "ready", "in_progress", "blocked", "done", "cancelled", "waived"}
TASK_RISKS = {"low", "medium", "high"}
COMPLETED_DEPENDENCY_STATUSES = {"done", "cancelled", "waived"}

TASK_COLUMNS = (
    "id",
    "title",
    "description",
    "status",
    "priority",
    "owner",
    "risk",
    "effort",
    "related_goal_id",
    "related_feature_id",
    "related_defect_id",
    "created_at",
    "updated_at",
)
TASK_FIELDS = ", ".join(TASK_COLUMNS)
QUALIFIED_TASK_FIELDS = ", ".join(f"tasks.{column}" for column in TASK_COLUMNS)


def create_task(
    paths: ProjectPaths,
    *,
    title: str,
    description: str = "",
    priority: int = 100,
    owner: str = "",
    risk: str | None = None,
    effort: str = "",
    goal_id: str | None = None,
    feature_id: str | None = None,
    defect_id: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _require_text(title, "--title is required to create a task.")
    risk = _clean_optional(risk)
    if risk is not None:
        _require_task_risk(risk)
    _validate_optional_identifier(goal_id, "goal_id")
    _validate_optional_identifier(feature_id, "feature_id")
    _validate_optional_identifier(defect_id, "defect_id")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        if goal_id:
            _get_entity(conn, "goals", goal_id, "Goal", "goal_id")
        if feature_id:
            _get_entity(conn, "features", feature_id, "Feature", "feature_id")
        if defect_id:
            _get_entity(conn, "defects", defect_id, "Defect", "defect_id")
        task_id = next_prefixed_id(conn, "tasks", "T")
        row = {
            "id": task_id,
            "title": title.strip(),
            "description": description.strip(),
            "status": "todo",
            "priority": int(priority),
            "owner": _clean_optional(owner),
            "risk": risk,
            "effort": _clean_optional(effort),
            "related_goal_id": _clean_optional(goal_id),
            "related_feature_id": _clean_optional(feature_id),
            "related_defect_id": _clean_optional(defect_id),
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO tasks(
              id, title, description, status, priority, owner, risk, effort,
              related_goal_id, related_feature_id, related_defect_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["title"],
                row["description"],
                row["status"],
                row["priority"],
                row["owner"],
                row["risk"],
                row["effort"],
                row["related_goal_id"],
                row["related_feature_id"],
                row["related_defect_id"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="task_created",
            entity_type="task",
            entity_id=task_id,
            payload={
                "title": row["title"],
                "description": row["description"],
                "status": row["status"],
                "priority": row["priority"],
                "owner": row["owner"],
                "risk": row["risk"],
                "effort": row["effort"],
                "related_goal_id": row["related_goal_id"],
                "related_feature_id": row["related_feature_id"],
                "related_defect_id": row["related_defect_id"],
            },
        )
        conn.commit()
        return {"ok": True, **row}
    finally:
        conn.close()


def list_tasks(
    paths: ProjectPaths,
    *,
    status: str | None = None,
    goal_id: str | None = None,
    owner: str | None = None,
) -> list[dict[str, Any]]:
    require_initialized(paths)
    if status:
        _require_task_status(status)
    _validate_optional_identifier(goal_id, "goal_id")

    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if goal_id:
        clauses.append("related_goal_id = ?")
        params.append(goal_id)
    if owner:
        clauses.append("owner = ?")
        params.append(owner.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT {TASK_FIELDS}
            FROM tasks
            {where}
            ORDER BY priority, id
            """,
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def read_task(paths: ProjectPaths, task_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(task_id, "task_id")
    conn = connect(paths.db_path)
    try:
        task = dict(_get_task(conn, task_id))
        task["dependencies"] = _related_tasks(conn, task_id, direction="dependencies")
        task["dependents"] = _related_tasks(conn, task_id, direction="dependents")
        return task
    finally:
        conn.close()


def set_task_status(paths: ProjectPaths, task_id: str, *, status: str, reason: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(task_id, "task_id")
    _require_task_status(status)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        task = _get_task(conn, task_id)
        previous_status = str(task["status"])
        if previous_status == status:
            return {
                "ok": True,
                "id": task_id,
                "from_status": previous_status,
                "to_status": status,
                "status": status,
                "changed": False,
                "evidence_recorded": False,
            }
        _require_text(reason, "--reason is required to update task status.")
        conn.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (status, now, task_id))
        cleaned_reason = reason.strip()
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="task_status_changed",
            entity_type="task",
            entity_id=task_id,
            payload={
                "from_status": previous_status,
                "to_status": status,
                "reason": cleaned_reason,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": task_id,
            "from_status": previous_status,
            "to_status": status,
            "reason": cleaned_reason,
            "changed": True,
        }
    finally:
        conn.close()


def add_dependency(paths: ProjectPaths, task_id: str, *, depends_on_task_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(task_id, "task_id")
    _validate_identifier(depends_on_task_id, "depends_on_task_id")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        _get_task(conn, task_id)
        _get_task(conn, depends_on_task_id)
        if task_id == depends_on_task_id:
            raise InvalidInputError(
                "Task cannot depend on itself.",
                details={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
            )
        if _dependency_exists(conn, task_id, depends_on_task_id):
            raise InvalidInputError(
                f"Task {task_id} already depends on {depends_on_task_id}.",
                details={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
            )
        if _would_create_cycle(conn, task_id, depends_on_task_id):
            raise InvalidInputError(
                f"Task dependency would create a cycle: {task_id} -> {depends_on_task_id}.",
                details={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
            )
        conn.execute(
            """
            INSERT INTO task_dependencies(task_id, depends_on_task_id, created_at)
            VALUES (?, ?, ?)
            """,
            (task_id, depends_on_task_id, now),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="task_dependency_added",
            entity_type="task",
            entity_id=task_id,
            payload={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
        )
        conn.commit()
        return {"ok": True, "task_id": task_id, "depends_on_task_id": depends_on_task_id}
    finally:
        conn.close()


def remove_dependency(paths: ProjectPaths, task_id: str, *, depends_on_task_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(task_id, "task_id")
    _validate_identifier(depends_on_task_id, "depends_on_task_id")

    conn = connect(paths.db_path)
    try:
        _get_task(conn, task_id)
        _get_task(conn, depends_on_task_id)
        if not _dependency_exists(conn, task_id, depends_on_task_id):
            raise InvalidInputError(
                f"Task {task_id} does not depend on {depends_on_task_id}.",
                details={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
            )
        conn.execute(
            "DELETE FROM task_dependencies WHERE task_id = ? AND depends_on_task_id = ?",
            (task_id, depends_on_task_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="task_dependency_removed",
            entity_type="task",
            entity_id=task_id,
            payload={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
        )
        conn.commit()
        return {"ok": True, "task_id": task_id, "depends_on_task_id": depends_on_task_id}
    finally:
        conn.close()


def _get_task(conn, task_id: str):
    row = conn.execute(
        f"""
        SELECT {TASK_FIELDS}
        FROM tasks
        WHERE id = ?
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Task does not exist: {task_id}",
            details={"task_id": task_id},
        )
    return row


def _get_entity(conn, table: str, entity_id: str, label: str, field_name: str):
    row = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise InvalidInputError(
            f"{label} does not exist: {entity_id}",
            details={field_name: entity_id},
        )
    return row


def _related_tasks(conn, task_id: str, *, direction: str) -> list[dict[str, Any]]:
    if direction == "dependencies":
        join_column = "depends_on_task_id"
        source_column = "task_id"
    else:
        join_column = "task_id"
        source_column = "depends_on_task_id"
    rows = conn.execute(
        f"""
        SELECT {QUALIFIED_TASK_FIELDS}
        FROM task_dependencies
        JOIN tasks ON tasks.id = task_dependencies.{join_column}
        WHERE task_dependencies.{source_column} = ?
        ORDER BY tasks.priority, tasks.id
        """,
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _dependency_exists(conn, task_id: str, depends_on_task_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM task_dependencies
        WHERE task_id = ? AND depends_on_task_id = ?
        """,
        (task_id, depends_on_task_id),
    ).fetchone()
    return row is not None


def _would_create_cycle(conn, task_id: str, depends_on_task_id: str) -> bool:
    stack = [depends_on_task_id]
    seen: set[str] = set()
    while stack:
        current_id = stack.pop()
        if current_id == task_id:
            return True
        if current_id in seen:
            continue
        seen.add(current_id)
        rows = conn.execute(
            """
            SELECT depends_on_task_id
            FROM task_dependencies
            WHERE task_id = ?
            ORDER BY depends_on_task_id
            """,
            (current_id,),
        ).fetchall()
        stack.extend(str(row["depends_on_task_id"]) for row in rows)
    return False


def _require_task_status(status: str) -> None:
    if status not in TASK_STATUSES:
        raise InvalidInputError(
            f"Invalid task status: {status}",
            details={"status": status, "allowed": sorted(TASK_STATUSES)},
        )


def _require_task_risk(risk: str) -> None:
    if risk not in TASK_RISKS:
        raise InvalidInputError(
            f"Invalid task risk: {risk}",
            details={"risk": risk, "allowed": sorted(TASK_RISKS)},
        )


def _require_text(value: str, message: str) -> None:
    if not value.strip():
        raise InvalidInputError(message)


def _validate_optional_identifier(value: str | None, field_name: str) -> None:
    if value:
        _validate_identifier(value, field_name)


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or not all(c.isalnum() or c in {"_", "-"} for c in value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={"field": field_name, "value": value},
        )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
