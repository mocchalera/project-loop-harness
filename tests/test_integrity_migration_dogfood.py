from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from pcl.cli import main
from pcl.db import connect


BASELINE_DB = (
    Path(__file__).parent
    / "fixtures"
    / "v0.3.1-baseline"
    / "db"
    / "v0.3.0-integrity-gap-schema-7.sqlite3"
)
BASELINE_EVENTS = BASELINE_DB.with_name("v0.3.0-integrity-gap-events.jsonl")
BASELINE_DB_SHA256 = "a3edf52d790661a77268471ae0b342fffe8a695aa4b32b9c2ebc3de8a99c0e6c"
BASELINE_EVENTS_SHA256 = "633e0f42149b30dc7caabbb7a8e3c3f863338c82f991544171dabb82f98a5689"


def _json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _event_count(root: Path) -> int:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"])
    finally:
        conn.close()


def _project_tree_state(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def test_v030_schema7_integrity_migration_uses_explicit_semantic_commands(
    tmp_path: Path, capsys
) -> None:
    # The immutable DB was created by the released v0.3.0 public `pcl init`.
    # The checked-in report records the separate real-source CLI dogfood that
    # created the legacy lifecycle gap before upgrading this same schema.
    assert hashlib.sha256(BASELINE_DB.read_bytes()).hexdigest() == BASELINE_DB_SHA256
    assert (
        hashlib.sha256(BASELINE_EVENTS.read_bytes()).hexdigest()
        == BASELINE_EVENTS_SHA256
    )
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()
    shutil.copyfile(BASELINE_DB, tmp_path / ".project-loop" / "project.db")
    shutil.copyfile(BASELINE_EVENTS, tmp_path / ".project-loop" / "events.jsonl")
    config = tmp_path / "pcl.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "\nvalidation:\n  lifecycle_integrity: enforced\n", "\n"
        ),
        encoding="utf-8",
    )

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    migrated = _json(capsys)
    assert [item["version"] for item in migrated["applied"]] == [8]

    before = _project_tree_state(tmp_path)
    events_before = _event_count(tmp_path)
    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    first_bytes = capsys.readouterr().out.encode()
    assert main([
        "--root", str(tmp_path), "repair", "lifecycle", "--dry-run", "--json",
    ]) == 0
    second_bytes = capsys.readouterr().out.encode()
    assert first_bytes == second_bytes
    assert _project_tree_state(tmp_path) == before
    assert _event_count(tmp_path) == events_before
    plan = json.loads(first_bytes)
    assert [action["action_kind"] for action in plan["actions"]] == [
        "inspect_story_candidate",
        "report_invalid_test_evidence",
    ]

    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    for action in plan["actions"]:
        emitted = shlex.split(action["command"])
        assert emitted[0] == "pcl"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pcl",
                "--root",
                str(tmp_path),
                *emitted[1:],
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["ok"] is True
        assert result.stderr == ""
    assert _project_tree_state(tmp_path) == before
    assert _event_count(tmp_path) == events_before

    assert main([
        "--root", str(tmp_path), "repair", "lifecycle", "--apply-structural", "--json",
    ]) == 0
    first_structural_bytes = capsys.readouterr().out.encode()
    structural = json.loads(first_structural_bytes)
    assert structural["changed"] is False
    assert structural["event_id"] is None
    assert main([
        "--root", str(tmp_path), "repair", "lifecycle", "--apply-structural", "--json",
    ]) == 0
    second_structural_bytes = capsys.readouterr().out.encode()
    assert second_structural_bytes == first_structural_bytes
    assert json.loads(second_structural_bytes)["event_id"] is None
    assert _project_tree_state(tmp_path) == before
    assert _event_count(tmp_path) == events_before

    assert main([
        "--root", str(tmp_path), "story", "review", "US-0001", "--summary",
        "Operator reviewed the legacy behavior.",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(tmp_path), "story", "approve", "US-0001", "--summary",
        "Operator explicitly approved the legacy contract.",
    ]) == 0
    capsys.readouterr()
    proof = tmp_path / "legacy-proof.txt"
    proof.write_text("reviewed legacy proof\n", encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "evidence", "add", "--file", proof.name,
        "--summary", "Reviewed hash-pinned legacy proof.", "--copy", "--json",
    ]) == 0
    assert _json(capsys)["evidence"]["id"] == "E-0002"
    assert main([
        "--root", str(tmp_path), "test", "link", "TC-0001", "--story", "US-0001",
        "--evidence-id", "E-0002", "--summary", "Explicitly repair reviewed links.",
        "--json",
    ]) == 0
    assert _json(capsys)["changed"] is True

    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    assert _json(capsys)["actions"] == []
    with config.open("a", encoding="utf-8") as handle:
        handle.write("\nvalidation:\n  lifecycle_integrity: enforced\n")
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json(capsys) == {
        "errors": [],
        "findings": [],
        "finding_counts": {"active": 0, "historical": 0},
        "ok": True,
        "warnings": [],
    }
    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    assert _json(capsys)["ok"] is True
