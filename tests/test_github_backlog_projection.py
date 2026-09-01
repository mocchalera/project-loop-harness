"""Deterministic read-only GitHub backlog projection (Issue #4).

The projection is generated from repo-verifiable anchors plus optional PCL
state enrichment. PCL state stays authoritative; GitHub Issues are a
contributor-facing view. These tests pin the fail-closed behavior for
missing, duplicate, contradictory, closed, and superseded mappings.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

import pcl.github_backlog as github_backlog_module
from pcl.cli import main as cli_main
from pcl.errors import InvalidInputError
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
        "# 9001 Fixture task\n\n"
        "- **Status:** Active\n"
        "- **Priority:** P1\n\n"
        "## Acceptance criteria\n\n- [ ] fixture\n",
        encoding="utf-8",
    )
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "fixture-doc.md").write_text("# fixture doc\n", encoding="utf-8")


def _entry(**overrides: object) -> dict:
    entry = {
        "issue": 9001,
        "title_hint": "Fixture issue",
        "anchors": {"agent_task_ids": ["9001"], "repo_paths": ["docs/fixture-doc.md"]},
        "acceptance_criteria_refs": ["agent-tasks/9001-fixture-task.md"],
    }
    entry.update(overrides)
    return entry


def _map_file(root: Path, issues: list[dict]) -> Path:
    payload = {
        "schema": "github-issue-map/v0",
        "repository": "mocchalera/project-loop-harness",
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


def _create_feature(root: Path, capsys: pytest.CaptureFixture[str], name: str) -> str:
    assert cli_main([
        "--root", str(root), "feature", "add", "--name", name,
        "--surface", "fixture", "--description", "fixture", "--json",
    ]) == 0
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

    entry = _entry(pcl_entities={"goals": [], "features": [], "tasks": [task_a]})
    map_path = _map_file(scratch_root, [entry])

    first = _run_json(scratch_root, map_path, capsys)
    second = _run_json(scratch_root, map_path, capsys)
    assert first == second, "projection must be deterministic for identical inputs"
    assert first["schema"] == PROJECTION_SCHEMA

    item = first["items"][0]
    assert item["issue"] == 9001
    assert item["priority"] == 10
    assert item["status"] == "todo"
    assert item["dependencies"]["pcl_task_dependencies"] == []
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
    entry = _entry(pcl_entities={"goals": [], "features": [], "tasks": [task_id]})
    map_path = _map_file(scratch_root, [entry])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "markdown"]) == 0
    markdown = capsys.readouterr().out
    assert "PCL state and accepted task/Evidence records are authoritative" in markdown
    assert "render_github_backlog.py" in markdown
    assert "#9001" in markdown
    assert "Last authoritative Evidence" in markdown
    assert f"`{task_id}`" in markdown


def test_pcl_state_absence_is_labeled_not_invented(tmp_path: Path) -> None:
    _write_anchor_files(tmp_path)
    map_path = _map_file(
        tmp_path,
        [_entry(pcl_entities={"goals": ["G-9999"], "features": ["F-9999"], "tasks": ["T-9999"]})],
    )
    projection = build_projection(tmp_path, load_issue_map(map_path))
    assert projection["ok"] is True
    item = projection["items"][0]
    assert item["status"] == "active"
    assert item["pcl"]["available"] is False
    assert item["pcl"]["declared"] == {
        "goals": ["G-9999"],
        "features": ["F-9999"],
        "tasks": ["T-9999"],
    }
    assert not (tmp_path / ".project-loop").exists()


# ---------------------------------------------------------------------------
# fail-closed cases


def test_missing_anchor_fails_closed(scratch_root: Path,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    entry = _entry(anchors={"repo_paths": ["docs/does-not-exist.md"]})
    map_path = _map_file(scratch_root, [entry])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "markdown"]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    codes = {finding["code"] for finding in payload["findings"]}
    assert "anchor_missing" in codes
    assert payload["ok"] is False


def test_duplicate_issue_number_fails_closed(scratch_root: Path,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    map_path = _map_file(scratch_root, [_entry(), _entry(title_hint="Duplicate")])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert any(f["code"] == "duplicate_issue_number" for f in payload["findings"])
    assert payload["ok"] is False


def test_duplicate_anchor_across_issues_fails_closed(scratch_root: Path,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    second = _entry(issue=9002, anchors={"agent_task_ids": ["9001"]})
    map_path = _map_file(scratch_root, [_entry(), second])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert any(f["code"] == "duplicate_anchor" for f in payload["findings"])
    assert payload["ok"] is False


def test_stale_status_contradiction_fails_closed(scratch_root: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    task_id = _create_task(scratch_root, capsys, "Cancelled work", 10)
    _add_task_evidence(scratch_root, capsys, task_id, "terminal proof")
    for status in ("ready", "in_progress", "done"):
        assert cli_main(["--root", str(scratch_root), "task", "status", task_id,
                         status, "--reason", "fixture transition", "--json"]) == 0
    capsys.readouterr()
    entry = _entry(pcl_entities={"goals": [], "features": [], "tasks": [task_id]})
    map_path = _map_file(scratch_root, [entry])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert any(f["code"] == "status_contradiction" for f in payload["findings"])
    assert payload["ok"] is False


def test_missing_pcl_entity_reference_fails_closed(scratch_root: Path,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    entry = _entry(pcl_entities={"goals": ["G-9999"], "features": [], "tasks": []})
    map_path = _map_file(scratch_root, [entry])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert any(f["code"] == "pcl_entity_missing" for f in payload["findings"])
    assert payload["ok"] is False


def test_declared_pcl_state_unavailable_warns_but_stays_honest(tmp_path: Path,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    _write_anchor_files(tmp_path)
    entry = _entry(pcl_entities={"goals": [], "features": [], "tasks": ["T-9999"]})
    map_path = _map_file(tmp_path, [entry])
    assert backlog_main(["--root", str(tmp_path), "--map", str(map_path),
                         "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(f["code"] == "state_unavailable" for f in payload["findings"])
    item = payload["items"][0]
    assert item["status"] == "active"
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
    (scratch_root / "agent-tasks" / "9001-fixture-task.md").write_text(
        "# 9001 Fixture task\n\n- **Status:** Done\n- **Priority:** P1\n\n"
        "## Acceptance criteria\n\n- [x] fixture\n",
        encoding="utf-8",
    )
    entry = _entry(pcl_entities={"goals": [], "features": [], "tasks": [task_id]})
    map_path = _map_file(scratch_root, [entry])
    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    item = payload["items"][0]
    assert item["status"] in {"done", "waived", "cancelled"}
    assert payload["ok"] is True


def test_mapping_rejects_manually_duplicated_mutable_fields(tmp_path: Path) -> None:
    _write_anchor_files(tmp_path)
    for field, value in (
        ("priority", "P1"),
        ("lifecycle", "active"),
        ("depends_on", []),
        ("status", "todo"),
    ):
        map_path = _map_file(tmp_path, [_entry(**{field: value})])
        with pytest.raises(InvalidInputError, match="unknown fields"):
            load_issue_map(map_path)
    payload = json.loads(map_path.read_text(encoding="utf-8"))
    payload["policy"] = "mutable projection policy"
    map_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InvalidInputError, match="root has unknown fields"):
        load_issue_map(map_path)


def test_feature_ids_are_enriched_and_declared(scratch_root: Path,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    feature_id = _create_feature(scratch_root, capsys, "Mapped feature")
    map_path = _map_file(scratch_root, [
        _entry(pcl_entities={"goals": [], "features": [feature_id], "tasks": []})
    ])
    payload = _run_json(scratch_root, map_path, capsys)
    item = payload["items"][0]
    assert item["pcl"]["declared"]["features"] == [feature_id]
    assert item["pcl"]["features"][0]["id"] == feature_id


def test_output_like_argument_cannot_overwrite_authoritative_database(
    scratch_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    map_path = _map_file(scratch_root, [_entry()])
    db_path = scratch_root / ".project-loop" / "project.db"
    before = db_path.read_bytes()
    assert before.startswith(b"SQLite format 3\x00")
    before_hash = hashlib.sha256(before).hexdigest()

    with pytest.raises(SystemExit) as exc_info:
        backlog_main([
            "--root", str(scratch_root), "--map", str(map_path),
            "--format", "json", "--out", str(db_path),
        ])

    assert exc_info.value.code == 2
    after = db_path.read_bytes()
    assert after.startswith(b"SQLite format 3\x00")
    assert hashlib.sha256(after).hexdigest() == before_hash
    capsys.readouterr()


def test_enrichment_uses_query_only_read_only_connection(
    scratch_root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id = _create_task(scratch_root, capsys, "Read-only target", 10)
    map_path = _map_file(scratch_root, [
        _entry(pcl_entities={"goals": [], "features": [], "tasks": [task_id]})
    ])
    observed: dict[str, object] = {}
    original = github_backlog_module.connect_read_only

    def checked_connect(db_path: Path) -> sqlite3.Connection:
        conn = original(db_path)
        observed["query_only"] = conn.execute("PRAGMA query_only").fetchone()[0]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE must_not_exist (id TEXT)")
        observed["read_only"] = True
        return conn

    monkeypatch.setattr(github_backlog_module, "connect_read_only", checked_connect)
    payload = _run_json(scratch_root, map_path, capsys)
    assert payload["ok"] is True
    assert observed == {"query_only": 1, "read_only": True}


def test_duplicate_pcl_id_across_issues_fails_closed(
    scratch_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task_id = _create_task(scratch_root, capsys, "Shared target", 10)
    (scratch_root / "agent-tasks" / "9002-fixture-task.md").write_text(
        "# 9002 Fixture task\n\n- **Status:** Active\n\n## Acceptance criteria\n\n- [ ] fixture\n",
        encoding="utf-8",
    )
    second = _entry(
        issue=9002,
        anchors={"agent_task_ids": ["9002"]},
        acceptance_criteria_refs=["agent-tasks/9002-fixture-task.md"],
        pcl_entities={"goals": [], "features": [], "tasks": [task_id]},
    )
    first = _entry(pcl_entities={"goals": [], "features": [], "tasks": [task_id]})
    payload = _run_json(scratch_root, _map_file(scratch_root, [first, second]), capsys, 1)
    assert any(f["code"] == "duplicate_pcl_id" for f in payload["findings"])


@pytest.mark.parametrize(
    ("dependency_text", "expected_code"),
    [
        ("9999", "dependency_reference_missing"),
        ("9001", "dependency_reference_self"),
        ("9002, 9002", "dependency_reference_duplicate"),
    ],
)
def test_invalid_task_record_dependency_references_fail_closed(
    scratch_root: Path,
    capsys: pytest.CaptureFixture[str],
    dependency_text: str,
    expected_code: str,
) -> None:
    (scratch_root / "agent-tasks" / "9001-fixture-task.md").write_text(
        "# 9001 Fixture task\n\n- **Status:** Active\n"
        f"- **Dependency:** {dependency_text}\n\n## Acceptance criteria\n\n- [ ] fixture\n",
        encoding="utf-8",
    )
    (scratch_root / "agent-tasks" / "9002-upstream.md").write_text(
        "# 9002 Upstream\n", encoding="utf-8"
    )
    payload = _run_json(scratch_root, _map_file(scratch_root, [_entry()]), capsys, 1)
    assert any(f["code"] == expected_code for f in payload["findings"])


def test_missing_repo_local_acceptance_reference_fails_closed(
    scratch_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = _entry(acceptance_criteria_refs=["docs/missing-acceptance.md"])
    payload = _run_json(scratch_root, _map_file(scratch_root, [entry]), capsys, 1)
    assert any(f["code"] == "acceptance_reference_missing" for f in payload["findings"])


def test_mixed_target_statuses_and_upstream_dependencies_render_individually(
    scratch_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    upstream = _create_task(scratch_root, capsys, "Upstream", 10)
    target = _create_task(scratch_root, capsys, "Target", 20)
    downstream = _create_task(scratch_root, capsys, "Downstream", 30)
    feature_id = _create_feature(scratch_root, capsys, "Mixed feature")
    assert cli_main(["--root", str(scratch_root), "task", "depend", target,
                     "--on", upstream, "--json"]) == 0
    assert cli_main(["--root", str(scratch_root), "task", "depend", downstream,
                     "--on", target, "--json"]) == 0
    capsys.readouterr()
    entry = _entry(pcl_entities={
        "goals": [], "features": [feature_id], "tasks": [target],
    })
    map_path = _map_file(scratch_root, [entry])
    payload = _run_json(scratch_root, map_path, capsys)
    item = payload["items"][0]
    assert item["status"] is None
    assert item["pcl"]["available"] is True
    assert item["dependencies"]["pcl_task_dependencies"] == [
        {"task_id": target, "depends_on_task_id": upstream}
    ]

    assert backlog_main(["--root", str(scratch_root), "--map", str(map_path),
                         "--format", "markdown"]) == 0
    markdown = capsys.readouterr().out
    assert "mixed (see individual PCL targets)" in markdown
    assert f"PCL task `{target}`: todo" in markdown
    assert f"PCL feature `{feature_id}`: discovered" in markdown
    assert "no local PCL state" not in markdown


# ---------------------------------------------------------------------------
# committed bootstrap mapping


def test_committed_bootstrap_map_resolves_repo_anchors(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    map_path = repo_root / "scripts" / "github-issue-map.json"
    mapping = load_issue_map(map_path)
    issues = sorted(entry["issue"] for entry in mapping["issues"])
    assert issues == [1, 2, 3, 8, 13]
    shutil.copytree(repo_root / "agent-tasks", tmp_path / "agent-tasks")
    for entry in mapping["issues"]:
        for ref in set(
            entry["anchors"]["repo_paths"] + entry["acceptance_criteria_refs"]
        ):
            source = repo_root / ref
            destination = tmp_path / ref
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    projection = build_projection(tmp_path, mapping)
    assert projection["ok"] is True, projection["findings"]
    assert all(item["pcl"]["available"] is False for item in projection["items"])
    assert all("priority" in item and "evidence" in item and "relevant_commit" in item
               for item in projection["items"])
