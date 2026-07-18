from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any, Literal

from .errors import InvalidInputError


TargetType = Literal["task", "goal"]


@dataclass(frozen=True)
class ResolvedTaskGoalTarget:
    type: TargetType
    row: dict[str, Any]


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
