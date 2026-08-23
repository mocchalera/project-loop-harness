"""Deterministic read-only GitHub backlog projection (Issue #4).

The projection is generated from repo-verifiable anchors plus optional PCL
state enrichment. PCL state stays authoritative; GitHub Issues are a
contributor-facing view. These tests pin the fail-closed behavior for
missing, duplicate, contradictory, closed, and superseded mappings.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcl.cli import main as cli_main
from pcl.github_backlog import (
    PROJECTION_SCHEMA,
    build_projection,
    load_issue_map,
    main as backlog_main,
)


# ---------------------------------------------------------------------------
# fixture helpers


def _write_anchor_files(root: Path) -> None:
    tasks_dir = root / "agent-tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "9001-fixture-task.md").write_text(
        "# 9001 Fixture task\n\n## Acceptance criteria\n\n- [ ] fixture\n",
        encoding="utf-8",
    )
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "fixture-doc.md").write_text("# fixture doc\n", encoding="utf-8")


def _entry(**overrides: object) -> dict:
    entry = {
        "issue": 9001,
        "priority": "P1",
        "lifecycle": "active",
        "depends_on": [],
        "title_hint": "Fixture issue",
        "owner_boundary": "Maintainer-owned; external contributions coordinate via discussion.",
        "anchors": {"agent_task_ids": ["9001"], "repo_paths": ["docs/fixture-doc.md"]},
        "acceptance_criteria_refs": ["agent-tasks/9001-fixture-task.md"],
    }
    entry.update(overrides)
    return entry


def _map_file(root: Path, issues: list[dict]) -> Path:
    payload = {
        "schema": "github-issue-map/v0",
        "repository": "mocchalera/project-loop-harness",
        "policy": "PCL state is authoritative; GitHub Issues are a projection.",
        "issues": issues,
    }
    path = root / "issue-map.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


@pytest.fixture()
def scratch_root(tmp_path: Path) -> Path:
    assert cli_main(["init", "--target", str(tmp_path)]) == 0
    _write_anchor_files(tmp_path)
    return tmp_path


def _create_task(root: Path, capsys: pytest.CaptureFixture[str], title: str, priority: int) -> str:
    assert cli_main(["--root", str(root), "task", "create", "--title", title,
                     "--priority", str(priority), "--json"]) == 0
    return str(json.loads(capsys.readouterr().out)["id"])


def _add_task_evidence(
    root: Path, capsys: pytest.CaptureFixture[str], task_id: str, summary: str
) -> str:
    artifact = root / f"artifact-{summary.replace(' ', '-')}.txt"
    artifact.write_text(f"artifact body: {summary}\n", encoding="utf-8")
    assert cli_main([
        "--root", str(root), "evidence", "add",
        "--file", artifact.name, "--summary", summary, "--task", task_id, "--json",
    ]) == 0
    return str(json.loads(capsys.readouterr().out)["evidence"]["id"])


def _run_json(root: Path, map_path: Path, capsys: pytest.CaptureFixture[str],
              expected_exit: int = 0) -> dict:
    assert backlog_main([
        "--root", str(root), "--map", str(map_path), "--format", "json",
    ]) == expected_exit
    if expected_exit == 0:
        return json.loads(capsys.readouterr().out)
    return json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------------------
# happy path + determinism


def test_projection_is_deterministic_and_complete(scratch_root: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    task_a = _create_task(scratch_root, capsys, "Anchor work", 10)
    task_b = _create_task(scratch_root, capsys, "Dependent work", 20)
    assert cli_main(["--root", str(scratch_root), "task", "depend", task_b,
                     "--on", task_a, "--json"]) == 0
    capsys.readouterr()
    first_evidence = _add_task_evidence(scratch_root, capsys, task_a, "first pass")
    replacement = _add_task_evidence(scratch_root, capsys, task_a, "second pass")
    assert cli_main(["--root", str(scratch_root), "evidence", "supersede", first_evidence,
                     "--with", replacement, "--summary", "superseded by re-run", "--json"]) == 0
    capsys.readouterr()

    entry = _entry(pcl_entities={"goals": [], "tasks": [task_a]})
    map_path = _map_file(scratch_root, [entry])

    first = _run_json(scratch_root, map_path, capsys)
    second = _run_json(scratch_root, map_path, capsys)
    assert first == second, "projection must be deterministic for identical inputs"
    assert first["schema"] == PROJECTION_SCHEMA

    item = first["items"][0]
    assert item["issue"] == 9001
    assert item["priority"] == "P1"
    assert item["status"] in {"todo", "ready", "in_progress"}
    assert item["dependencies"]["declared"] == []
    assert item["dependencies"]["pcl_task_dependencies"] == [
        {"task_id": task_b, "depends_on_task_id": task_a}
    ]
    assert item["acceptance_criteria_refs"] == ["agent-tasks/9001-fixture-task.md"]
    assert item["anchors"]["repo_paths"][0]["path"] == "docs/fixture-doc.md"

    evidence_block = item["pcl"]["tasks"][0]
    assert evidence_block["last_authoritative_evidence"]["id"] == replacement
    superseded = evidence_block["superseded_evidence"]
    assert [row["id"] for row in superseded] == [first_evidence]
    assert superseded[0]["superseded_by"] == replacement

    assert first["ok"] is True
    assert any(finding["code"] == "evidence_superseded" and finding["severity"] == "info"
               for finding in first["findings"])


def test_markdown_renders_policy_and_refresh_command(scratch_root: Path,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    task_id = _create_task(scratch_root, capsys, "Markdown fixture", 10)
    capsys.readouterr()
    entry = _entry(pcl_entities={"goals": [], "tasks": [task_id]})
    map_path = _map_file(scratch_root, [entry])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "markdown"]) == 0
    markdown = capsys.readouterr().out
    assert "PCL state is authoritative" in markdown
    assert "render_github_backlog.py" in markdown
    assert "#9001" in markdown
    assert "Last authoritative Evidence" in markdown
    assert f"`{task_id}`" in markdown


def test_pcl_state_absence_is_labeled_not_invented(tmp_path: Path) -> None:
    _write_anchor_files(tmp_path)
    map_path = _map_file(tmp_path, [_entry()])
    projection = build_projection(tmp_path, load_issue_map(map_path))
    assert projection["ok"] is True
    item = projection["items"][0]
    assert item["status"] is None
    assert item["pcl"]["available"] is False


# ---------------------------------------------------------------------------
# fail-closed cases


def test_missing_anchor_fails_closed_and_writes_nothing(scratch_root: Path,
                                                        tmp_path_factory,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    entry = _entry(anchors={"repo_paths": ["docs/does-not-exist.md"]})
    map_path = _map_file(scratch_root, [entry])
    out_file = tmp_path_factory.mktemp("out") / "backlog.md"
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "markdown", "--out", str(out_file)]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    codes = {finding["code"] for finding in payload["findings"]}
    assert "anchor_missing" in codes
    assert payload["ok"] is False
    assert not out_file.exists(), "fail-closed runs must not write review artifacts"


def test_duplicate_issue_number_fails_closed(scratch_root: Path,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    map_path = _map_file(scratch_root, [_entry(), _entry(priority="P2")])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert any(f["code"] == "duplicate_issue_number" for f in payload["findings"])
    assert payload["ok"] is False


def test_duplicate_anchor_across_issues_fails_closed(scratch_root: Path,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    second = _entry(issue=9002, priority="P2", anchors={"agent_task_ids": ["9001"]})
    map_path = _map_file(scratch_root, [_entry(), second])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert any(f["code"] == "duplicate_anchor" for f in payload["findings"])
    assert payload["ok"] is False


def test_stale_status_contradiction_fails_closed(scratch_root: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    task_id = _create_task(scratch_root, capsys, "Cancelled work", 10)
    assert cli_main(["--root", str(scratch_root), "task", "status", task_id,
                     "cancelled", "--reason", "superseded elsewhere", "--json"]) == 0
    capsys.readouterr()
    entry = _entry(pcl_entities={"goals": [], "tasks": [task_id]})
    map_path = _map_file(scratch_root, [entry])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert any(f["code"] == "status_contradiction" for f in payload["findings"])
    assert payload["ok"] is False


def test_missing_pcl_entity_reference_fails_closed(scratch_root: Path,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    entry = _entry(pcl_entities={"goals": ["G-9999"], "tasks": []})
    map_path = _map_file(scratch_root, [entry])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert any(f["code"] == "pcl_entity_missing" for f in payload["findings"])
    assert payload["ok"] is False


def test_declared_pcl_state_unavailable_warns_but_stays_honest(tmp_path: Path,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    _write_anchor_files(tmp_path)
    entry = _entry(pcl_entities={"goals": [], "tasks": []})
    map_path = _map_file(tmp_path, [entry])
    assert backlog_main(["--root", str(tmp_path), "--map", str(map_path),
                         "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(f["code"] == "state_unavailable" for f in payload["findings"])
    item = payload["items"][0]
    assert item["status"] is None
    assert item["pcl"]["available"] is False


def test_completed_lifecycle_with_done_task_is_not_contradiction(
    scratch_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task_id = _create_task(scratch_root, capsys, "Finished work", 10)
    artifact = scratch_root / "done-artifact.txt"
    artifact.write_text("done\n", encoding="utf-8")
    assert cli_main(["--root", str(scratch_root), "evidence", "add",
                     "--file", artifact.name, "--summary", "completion fixture",
                     "--task", task_id, "--json"]) == 0
    capsys.readouterr()
    for status in ("ready", "in_progress"):
        result = cli_main(["--root", str(scratch_root), "task", "status", task_id,
                           status, "--reason", "fixture transition", "--json"])
        assert result == 0, f"transition to {status} failed"
    result = cli_main(["--root", str(scratch_root), "task", "status", task_id,
                       "waived", "--reason", "fixture close-out", "--json"])
    assert result == 0, "transition to waived failed"
    capsys.readouterr()
    entry = _entry(lifecycle="completed", pcl_entities={"goals": [], "tasks": [task_id]})
    map_path = _map_file(scratch_root, [entry])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    item = payload["items"][0]
    assert item["status"] in {"done", "waived", "cancelled"}
    assert payload["ok"] is True


# ---------------------------------------------------------------------------
# committed bootstrap mapping


def test_committed_bootstrap_map_resolves_repo_anchors() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    map_path = repo_root / "scripts" / "github-issue-map.json"
    mapping = load_issue_map(map_path)
    issues = sorted(entry["issue"] for entry in mapping["issues"])
    assert issues == [1, 2, 3]
    projection = build_projection(repo_root, mapping)
    assert projection["ok"] is True, projection["findings"]
    assert all(item["status"] is None for item in projection["items"])
    assert all(item["pcl"]["available"] is False for item in projection["items"])
