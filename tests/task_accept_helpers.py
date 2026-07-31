from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcl.cli import main
from pcl.db import connect


def json_output(capsys) -> dict[str, Any]:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def run_json(root: Path, capsys, *args: str, expected_exit: int = 0) -> dict[str, Any]:
    assert main(["--root", str(root), *args, "--json"]) == expected_exit
    return json_output(capsys)


def prepare_acceptance(
    root: Path,
    capsys,
    *,
    test_count: int = 2,
    approve_story: bool = True,
) -> dict[str, Any]:
    assert main(["init", "--target", str(root), "--json"]) == 0
    json_output(capsys)
    started = run_json(root, capsys, "start", "Atomic acceptance fixture")
    task_id = str(started["result"]["created_ids"]["task"])
    feature = run_json(
        root,
        capsys,
        "feature",
        "add",
        "--task",
        task_id,
        "--name",
        "Atomic acceptance",
        "--surface",
        "cli:task-accept",
    )
    feature_id = str(feature["id"])
    story = run_json(
        root,
        capsys,
        "story",
        "draft",
        "--feature",
        feature_id,
        "--actor",
        "operator",
        "--goal",
        "accept one complete change",
        "--expected-behavior",
        "all acceptance state commits atomically",
    )
    story_id = str(story["id"])
    if approve_story:
        run_json(
            root,
            capsys,
            "story",
            "approve",
            story_id,
            "--summary",
            "Fixture semantics approved",
        )
    test_ids: list[str] = []
    for index in range(test_count):
        planned = run_json(
            root,
            capsys,
            "test",
            "plan",
            "--feature",
            feature_id,
            "--story",
            story_id,
            "--type",
            "acceptance" if index == 0 else "integration",
            "--scenario",
            f"acceptance check {index + 1}",
            "--expected",
            "passing",
        )
        test_ids.append(str(planned["id"]))
    artifact = root / "artifacts" / "acceptance.txt"
    artifact.parent.mkdir()
    artifact.write_text("verified acceptance\n", encoding="utf-8")
    return {
        "task_id": task_id,
        "feature_id": feature_id,
        "story_id": story_id,
        "test_ids": test_ids,
        "artifact": artifact.relative_to(root).as_posix(),
    }


def accept_args(fixture: dict[str, Any], *, summary: str = "Acceptance verified") -> list[str]:
    args = [
        "task",
        "accept",
        str(fixture["task_id"]),
        "--artifact",
        str(fixture["artifact"]),
        "--command",
        "pytest -q",
        "--summary",
        summary,
        "--copy",
    ]
    for test_id in fixture["test_ids"]:
        args.extend(["--test", str(test_id)])
    return args


def state_counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
            for table in ("evidence", "evidence_links", "events", "outbox_records")
        }
    finally:
        conn.close()
