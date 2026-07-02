from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pcl.cli import main
from pcl.db import connect
from pcl.tasks import TASK_STATUSES


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _create_task(root: Path, capsys, *, title: str, priority: int = 100, owner: str = "") -> dict:
    command = [
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        title,
        "--priority",
        str(priority),
        "--json",
    ]
    if owner:
        command.extend(["--owner", owner])
    assert main(command) == 0
    return _json_output(capsys)


def _task_event_types(root: Path) -> list[str]:
    jsonl_events = [
        json.loads(line)
        for line in (root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    jsonl_types = [event["event_type"] for event in jsonl_events if event["event_type"].startswith("task_")]

    conn = connect(root / ".project-loop" / "project.db")
    try:
        rows = conn.execute(
            """
            SELECT event_type
            FROM events
            WHERE event_type LIKE 'task_%'
            ORDER BY rowid
            """
        ).fetchall()
    finally:
        conn.close()
    db_types = [str(row["event_type"]) for row in rows]
    assert db_types == jsonl_types
    return jsonl_types


def test_task_crud_ordering_and_filters(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Task goal", "--json"]) == 0
    goal_id = str(_json_output(capsys)["id"])

    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Medium priority",
        "--description",
        "Track a normal task",
        "--priority",
        "50",
        "--owner",
        "agent-a",
        "--risk",
        "medium",
        "--effort",
        "small",
        "--goal",
        goal_id,
        "--json",
    ]) == 0
    first = _json_output(capsys)
    assert first["id"] == "T-0001"
    assert first["status"] == "todo"
    assert first["related_goal_id"] == goal_id

    _create_task(tmp_path, capsys, title="Highest priority", priority=10, owner="agent-b")
    _create_task(tmp_path, capsys, title="Same priority tie", priority=50, owner="agent-a")

    assert main(["--root", str(tmp_path), "task", "list", "--json"]) == 0
    listed = _json_output(capsys)
    assert [task["id"] for task in listed["tasks"]] == ["T-0002", "T-0001", "T-0003"]

    assert main(["--root", str(tmp_path), "task", "list", "--owner", "agent-a", "--json"]) == 0
    owner_filtered = _json_output(capsys)
    assert [task["id"] for task in owner_filtered["tasks"]] == ["T-0001", "T-0003"]

    assert main(["--root", str(tmp_path), "task", "list", "--goal", goal_id, "--json"]) == 0
    goal_filtered = _json_output(capsys)
    assert [task["id"] for task in goal_filtered["tasks"]] == ["T-0001"]

    assert main(["--root", str(tmp_path), "task", "read", "T-0001", "--json"]) == 0
    read = _json_output(capsys)
    assert read["task"]["title"] == "Medium priority"
    assert read["task"]["dependencies"] == []
    assert read["task"]["dependents"] == []


def test_task_status_transitions_require_reason(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)

    created = _create_task(tmp_path, capsys, title="Needs reason")
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "status",
        created["id"],
        "ready",
        "--reason",
        "",
        "--json",
    ]) == 2
    error = _json_output(capsys)
    assert error["error"]["code"] == "invalid_input"
    assert "reason is required" in error["error"]["message"]

    for status in sorted(TASK_STATUSES):
        task = _create_task(tmp_path, capsys, title=f"Transition to {status}")
        task_id = str(task["id"])
        if status == "todo":
            assert main([
                "--root",
                str(tmp_path),
                "task",
                "status",
                task_id,
                "ready",
                "--reason",
                "stage work",
                "--json",
            ]) == 0
            _json_output(capsys)
        assert main([
            "--root",
            str(tmp_path),
            "task",
            "status",
            task_id,
            status,
            "--reason",
            f"move to {status}",
            "--json",
        ]) == 0
        result = _json_output(capsys)
        assert result["to_status"] == status
        assert result["reason"] == f"move to {status}"

    event_types = _task_event_types(tmp_path)
    assert event_types.count("task_created") == 1 + len(TASK_STATUSES)
    assert event_types.count("task_status_changed") == len(TASK_STATUSES) + 1


def test_task_dependencies_reject_invalid_edges_and_dual_write_events(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _create_task(tmp_path, capsys, title="Foundation")
    _create_task(tmp_path, capsys, title="Build")
    _create_task(tmp_path, capsys, title="Ship")

    assert main(["--root", str(tmp_path), "task", "depend", "T-0002", "--on", "T-0001", "--json"]) == 0
    assert _json_output(capsys)["depends_on_task_id"] == "T-0001"

    assert main(["--root", str(tmp_path), "task", "depend", "T-0002", "--on", "T-0001", "--json"]) == 2
    duplicate = _json_output(capsys)
    assert duplicate["error"]["code"] == "invalid_input"
    assert "already depends" in duplicate["error"]["message"]

    assert main(["--root", str(tmp_path), "task", "depend", "T-0001", "--on", "T-0001", "--json"]) == 2
    self_dependency = _json_output(capsys)
    assert self_dependency["error"]["code"] == "invalid_input"
    assert "depend on itself" in self_dependency["error"]["message"]

    assert main(["--root", str(tmp_path), "task", "depend", "T-0001", "--on", "T-0002", "--json"]) == 2
    direct_cycle = _json_output(capsys)
    assert direct_cycle["error"]["code"] == "invalid_input"
    assert "cycle" in direct_cycle["error"]["message"]

    assert main(["--root", str(tmp_path), "task", "depend", "T-0003", "--on", "T-0002", "--json"]) == 0
    _json_output(capsys)
    assert main(["--root", str(tmp_path), "task", "depend", "T-0001", "--on", "T-0003", "--json"]) == 2
    transitive_cycle = _json_output(capsys)
    assert transitive_cycle["error"]["code"] == "invalid_input"
    assert "cycle" in transitive_cycle["error"]["message"]

    assert main(["--root", str(tmp_path), "task", "read", "T-0003", "--json"]) == 0
    read = _json_output(capsys)
    assert [task["id"] for task in read["task"]["dependencies"]] == ["T-0002"]
    assert [task["id"] for task in read["task"]["dependents"]] == []

    assert main(["--root", str(tmp_path), "task", "undepend", "T-0003", "--on", "T-0002", "--json"]) == 0
    assert _json_output(capsys)["depends_on_task_id"] == "T-0002"
    assert main(["--root", str(tmp_path), "task", "read", "T-0003", "--json"]) == 0
    assert _json_output(capsys)["task"]["dependencies"] == []

    event_types = _task_event_types(tmp_path)
    assert event_types == [
        "task_created",
        "task_created",
        "task_created",
        "task_dependency_added",
        "task_dependency_added",
        "task_dependency_removed",
    ]


def test_task_validation_detects_warnings_cycles_and_missing_references(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _create_task(tmp_path, capsys, title="Blocked done task")
    _create_task(tmp_path, capsys, title="Incomplete dependency")
    assert main(["--root", str(tmp_path), "task", "depend", "T-0001", "--on", "T-0002", "--json"]) == 0
    _json_output(capsys)
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "status",
        "T-0001",
        "done",
        "--reason",
        "operator override",
        "--json",
    ]) == 0
    _json_output(capsys)

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    normal = _json_output(capsys)
    assert normal["ok"] is True
    assert any("is done but depends on incomplete task T-0002" in warning for warning in normal["warnings"])

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    strict = _json_output(capsys)
    assert strict["ok"] is False
    assert any("Strict mode treats warning as error" in error for error in strict["errors"])

    raw = sqlite3.connect(tmp_path / ".project-loop" / "project.db")
    try:
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.execute(
            """
            INSERT INTO task_dependencies(task_id, depends_on_task_id, created_at)
            VALUES (?, ?, ?)
            """,
            ("T-0002", "T-0001", "2026-01-01T00:00:00Z"),
        )
        raw.execute(
            """
            INSERT INTO tasks(
              id, title, description, status, priority, owner, risk, effort,
              related_goal_id, related_feature_id, related_defect_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "T-9999",
                "Broken reference",
                "",
                "todo",
                100,
                None,
                None,
                None,
                "G-9999",
                None,
                None,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        raw.commit()
    finally:
        raw.close()

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 1
    invalid = _json_output(capsys)
    assert invalid["ok"] is False
    assert any("Task dependency cycle detected" in error for error in invalid["errors"])
    assert any("Task T-9999 references missing goal G-9999" in error for error in invalid["errors"])
