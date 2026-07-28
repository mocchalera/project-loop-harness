from __future__ import annotations

from pathlib import Path

import pytest

from pcl.cli import main
from pcl.db import connect
from pcl.errors import InvalidInputError
from pcl.target_resolver import resolve_routing_target


def test_routing_target_resolves_parent_once_and_rejects_parent_mismatch(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    for title in ("Expected parent", "Other parent"):
        assert main([
            "--root", str(tmp_path), "goal", "create", "--title", title,
        ]) == 0
    assert main([
        "--root", str(tmp_path), "task", "create", "--title", "Bound child",
        "--goal", "G-0001",
    ]) == 0
    capsys.readouterr()

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        target = resolve_routing_target(
            conn,
            "T-0001",
            expected_type="task",
            expected_goal_id="G-0001",
        )
        assert target.binding() == {
            "target_type": "task",
            "target_id": "T-0001",
            "source": "explicit",
        }
        assert target.contract_version == "routing-target/v1"
        assert target.goal_id == "G-0001"
        assert target.blocks_ref("task", "T-0001")
        assert target.blocks_ref("goal", "G-0001")

        with pytest.raises(InvalidInputError) as exc_info:
            resolve_routing_target(
                conn,
                "T-0001",
                expected_type="task",
                expected_goal_id="G-0002",
            )
    finally:
        conn.close()

    assert exc_info.value.details == {
        "target": "T-0001",
        "target_type": "task",
        "expected_goal_id": "G-0002",
        "actual_goal_id": "G-0001",
    }
