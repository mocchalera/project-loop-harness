from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Any, Literal

from .errors import InvalidInputError


TargetType = Literal["task", "goal"]
ROUTING_TARGET_CONTRACT_VERSION = "routing-target/v1"


@dataclass(frozen=True)
class ResolvedTaskGoalTarget:
    type: TargetType
    row: dict[str, Any]


@dataclass(frozen=True)
class ResolvedRoutingTarget:
    """One fail-closed Task/Goal binding shared by command surfaces."""

    type: TargetType
    row: dict[str, Any]
    goal_row: dict[str, Any] | None
    scope_refs: frozenset[tuple[str, str]]

    @property
    def contract_version(self) -> str:
        return ROUTING_TARGET_CONTRACT_VERSION

    @property
    def id(self) -> str:
        return str(self.row["id"])

    @property
    def status(self) -> str:
        return str(self.row["status"])

    @property
    def goal_id(self) -> str | None:
        if self.type == "goal":
            return self.id
        value = self.row.get("related_goal_id")
        return str(value) if value else None

    def binding(self, *, source: str = "explicit") -> dict[str, str]:
        return {
            "target_type": self.type,
            "target_id": self.id,
            "source": source,
        }

    def blocks_ref(self, target_type: object, target_id: object) -> bool:
        return (str(target_type or ""), str(target_id or "")) in self.scope_refs

    def decision_blocks(self, blocks_json: object) -> bool:
        try:
            blocks = json.loads(str(blocks_json or "[]"))
        except json.JSONDecodeError:
            return False
        if not isinstance(blocks, list):
            return False
        return any(
            isinstance(item, dict)
            and self.blocks_ref(item.get("type"), item.get("id"))
            for item in blocks
        )


class TaskGoalTargetNotFoundError(LookupError):
    def __init__(self, *, target_id: str, target_type: TargetType) -> None:
        super().__init__(target_id)
        self.target_id = target_id
        self.target_type = target_type


def resolve_existing_task_goal(
    conn: sqlite3.Connection,
    target_id: str,
) -> ResolvedTaskGoalTarget:
    """Resolve the shared bare Task/Goal ID grammar without choosing a target."""

    if target_id.startswith("T-"):
        target_type: TargetType = "task"
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (target_id,)).fetchone()
    elif target_id.startswith("G-"):
        target_type = "goal"
        row = conn.execute("SELECT * FROM goals WHERE id = ?", (target_id,)).fetchone()
    else:
        raise InvalidInputError(
            "--target must be a task or goal ID.",
            details={"target": target_id, "accepted_prefixes": ["T-", "G-"]},
        )

    if row is None:
        raise TaskGoalTargetNotFoundError(
            target_id=target_id,
            target_type=target_type,
        )
    return ResolvedTaskGoalTarget(type=target_type, row=dict(row))


def resolve_routing_target(
    conn: sqlite3.Connection,
    target_id: str,
    *,
    expected_type: TargetType | None = None,
    expected_goal_id: str | None = None,
) -> ResolvedRoutingTarget:
    """Resolve a Task/Goal plus the references that can legitimately block it.

    No target is inferred here. Callers must pass an ID or implement their
    existing unbound selection policy separately.
    """

    resolved = resolve_existing_task_goal(conn, target_id)
    if expected_type is not None and resolved.type != expected_type:
        raise InvalidInputError(
            f"Expected a {expected_type} target, got {resolved.type} {target_id}.",
            details={
                "target": target_id,
                "target_type": resolved.type,
                "expected_target_type": expected_type,
            },
        )

    row = resolved.row
    goal_row: dict[str, Any] | None = None
    if resolved.type == "goal":
        goal_row = row
    else:
        related_goal_id = row.get("related_goal_id")
        if related_goal_id:
            parent = conn.execute(
                "SELECT * FROM goals WHERE id = ?",
                (related_goal_id,),
            ).fetchone()
            if parent is None:
                raise InvalidInputError(
                    f"Task {target_id} references missing parent Goal {related_goal_id}.",
                    details={
                        "target": target_id,
                        "target_type": "task",
                        "related_goal_id": str(related_goal_id),
                        "issue": "missing_parent_goal",
                    },
                )
            goal_row = dict(parent)

    actual_goal_id = (
        str(goal_row["id"])
        if goal_row is not None
        else None
    )
    if expected_goal_id is not None and actual_goal_id != expected_goal_id:
        raise InvalidInputError(
            f"Target {target_id} belongs to Goal {actual_goal_id or '<none>'}, not {expected_goal_id}.",
            details={
                "target": target_id,
                "target_type": resolved.type,
                "expected_goal_id": expected_goal_id,
                "actual_goal_id": actual_goal_id,
            },
        )

    return ResolvedRoutingTarget(
        type=resolved.type,
        row=row,
        goal_row=goal_row,
        scope_refs=frozenset(_routing_scope_refs(conn, resolved=resolved)),
    )


def _routing_scope_refs(
    conn: sqlite3.Connection,
    *,
    resolved: ResolvedTaskGoalTarget,
) -> set[tuple[str, str]]:
    refs = {(resolved.type, str(resolved.row["id"]))}
    task_rows: list[dict[str, Any]]
    if resolved.type == "task":
        task_rows = [resolved.row]
        goal_id = resolved.row.get("related_goal_id")
        if goal_id:
            refs.add(("goal", str(goal_id)))
    else:
        goal_id = str(resolved.row["id"])
        task_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, related_feature_id, related_defect_id
                FROM tasks
                WHERE related_goal_id = ?
                ORDER BY id
                """,
                (goal_id,),
            ).fetchall()
        ]
        refs.update(("task", str(row["id"])) for row in task_rows)

    feature_ids = {
        str(row["related_feature_id"])
        for row in task_rows
        if row.get("related_feature_id")
    }
    defect_ids = {
        str(row["related_defect_id"])
        for row in task_rows
        if row.get("related_defect_id")
    }
    refs.update(("feature", feature_id) for feature_id in feature_ids)
    refs.update(("defect", defect_id) for defect_id in defect_ids)

    if feature_ids:
        placeholders = ", ".join("?" for _ in feature_ids)
        ordered_features = tuple(sorted(feature_ids))
        story_rows = conn.execute(
            f"SELECT id FROM user_stories WHERE feature_id IN ({placeholders}) ORDER BY id",
            ordered_features,
        ).fetchall()
        test_rows = conn.execute(
            f"SELECT id FROM test_cases WHERE feature_id IN ({placeholders}) ORDER BY id",
            ordered_features,
        ).fetchall()
        refs.update(("user_story", str(row["id"])) for row in story_rows)
        refs.update(("test_case", str(row["id"])) for row in test_rows)

    goal_id = (
        str(resolved.row["id"])
        if resolved.type == "goal"
        else (
            str(resolved.row["related_goal_id"])
            if resolved.row.get("related_goal_id")
            else None
        )
    )
    if goal_id:
        run_rows = conn.execute(
            "SELECT id FROM workflow_runs WHERE goal_id = ? ORDER BY id",
            (goal_id,),
        ).fetchall()
        run_ids = tuple(str(row["id"]) for row in run_rows)
        refs.update(("workflow_run", run_id) for run_id in run_ids)
        if run_ids:
            placeholders = ", ".join("?" for _ in run_ids)
            for target_type, table, column in (
                ("agent_job", "agent_jobs", "workflow_run_id"),
                ("verification", "verifications", "workflow_run_id"),
                ("escalation", "escalations", "workflow_run_id"),
            ):
                rows = conn.execute(
                    f"SELECT id FROM {table} WHERE {column} IN ({placeholders}) ORDER BY id",
                    run_ids,
                ).fetchall()
                refs.update((target_type, str(row["id"])) for row in rows)
    return refs
