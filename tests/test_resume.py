from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from pcl.cli import main
from pcl.contracts.handoff_packet import validate_handoff_packet
from pcl.db import connect
from pcl.resume import render_handoff_markdown


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _start(root: Path, capsys, intent: str = "Resume contract") -> None:
    assert main(["--root", str(root), "start", intent, "--json"]) == 0
    _json_output(capsys)


def _state_fingerprint(root: Path) -> dict[str, object]:
    db = root / ".project-loop" / "project.db"
    events = root / ".project-loop" / "events.jsonl"
    conn = connect(db)
    try:
        event_count = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        evidence_count = int(conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])
    finally:
        conn.close()
    return {
        "db_sha256": hashlib.sha256(db.read_bytes()).hexdigest(),
        "events_sha256": hashlib.sha256(events.read_bytes()).hexdigest(),
        "event_count": event_count,
        "evidence_count": evidence_count,
    }


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _packet_project(root: Path, capsys, *, passing: bool) -> None:
    _init(root, capsys)
    config_path = root / "pcl.yaml"
    config = config_path.read_text(encoding="utf-8")
    config = config.replace('test: ""', 'test: "python -m pytest -q test_sample.py"')
    config_path.write_text(config, encoding="utf-8")
    test_path = root / "test_sample.py"
    test_path.write_text("def test_sample():\n    assert True\n", encoding="utf-8")
    gitignore = root / ".gitignore"
    gitignore.write_text(
        gitignore.read_text(encoding="utf-8") + "\n__pycache__/\n.pytest_cache/\n",
        encoding="utf-8",
    )
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "pcl@example.test")
    _git(root, "config", "user.name", "PCL Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "baseline")
    assert main([
        "--root", str(root), "task", "create", "--title", "Resume packet task",
        "--description", "Exercise handoff packet resume",
    ]) == 0
    assert main([
        "--root", str(root), "task", "status", "T-0001", "in_progress",
        "--reason", "Begin work",
    ]) == 0
    assertion = "True" if passing else "False"
    test_path.write_text(
        f"def test_sample():\n    assert {assertion}\n\n# resume packet change\n",
        encoding="utf-8",
    )
    capsys.readouterr()


def _finish(root: Path, capsys) -> tuple[int, dict]:
    exit_code = main([
        "--root", str(root), "finish", "--emit-packet", "--task", "T-0001",
        "--base", "HEAD", "--json",
    ])
    return exit_code, _json_output(capsys)["finish"]


def test_resume_active_target_is_valid_read_only_and_replayable(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _start(tmp_path, capsys)
    before = _state_fingerprint(tmp_path)

    assert main(["--root", str(tmp_path), "resume", "--json"]) == 0
    packet = _json_output(capsys)["handoff_packet"]

    assert validate_handoff_packet(packet).ok is True
    assert packet["target"]["id"] == "T-0001"
    assert packet["current_state"] == "TODO"
    assert packet["verified"] == []
    assert packet["unverified"]
    assert "full_transcript" in packet["omitted_sections"]
    assert _state_fingerprint(tmp_path) == before

    replay = shlex.split(packet["next_safe_action"]["command"])
    assert replay.pop(0) == "pcl"
    assert main(["--root", str(tmp_path), *replay, "--json"]) == 0
    replayed = _json_output(capsys)
    assert replayed["context_pack"]["target"] == {"type": "task", "id": "T-0001"}


def test_resume_multiple_active_tasks_requires_explicit_selection(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    for title in ("First", "Second"):
        assert main(["--root", str(tmp_path), "task", "create", "--title", title]) == 0
    capsys.readouterr()
    before = _state_fingerprint(tmp_path)

    assert main(["--root", str(tmp_path), "resume", "--json"]) == 2
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "context_pack_target_selection_required"
    candidates = payload["error"]["details"]["candidates"]
    assert [item["id"] for item in candidates] == ["T-0001", "T-0002"]
    assert _state_fingerprint(tmp_path) == before


def test_resume_explicit_goal_without_packet_is_valid(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Goal resume"]) == 0
    capsys.readouterr()

    assert main([
        "--root", str(tmp_path), "resume", "--target", "G-0001", "--json",
    ]) == 0
    packet = _json_output(capsys)["handoff_packet"]

    assert validate_handoff_packet(packet).ok is True
    assert packet["target"]["type"] == "goal"
    assert packet["current_state"] == "OPEN"
    assert packet["next_safe_action"]["command"] == "pcl next --json"


def test_resume_completed_packet_preserves_verified_semantics_and_markdown(
    tmp_path: Path,
    capsys,
) -> None:
    _packet_project(tmp_path, capsys, passing=True)
    exit_code, finish = _finish(tmp_path, capsys)
    assert exit_code == 0
    assert finish["packet"]["outcome"] == "COMPLETED_VERIFIED"
    before = _state_fingerprint(tmp_path)

    assert main(["--root", str(tmp_path), "resume", "--json"]) == 0
    packet = _json_output(capsys)["handoff_packet"]

    assert packet["target"]["id"] == "T-0001"
    assert packet["current_state"] == "DONE"
    assert packet["verified"][0]["proof_level"] == "L2"
    assert packet["verified"][0]["evidence_refs"]
    completion_ref = next(
        item for item in packet["context_refs"] if item["kind"] == "completion-packet/v1"
    )
    assert completion_ref["ref"] == f"evidence:{finish['packet']['evidence_id']}"
    assert completion_ref["sha256"].startswith("sha256:")
    restart = packet["restart_context"]
    assert restart["target_intent"] == "Exercise handoff packet resume"
    assert restart["acceptance_status"] == "intent_only"
    assert restart["acceptance_ref"] is None
    assert restart["target_review_command"] == "pcl task read T-0001 --json"
    assert restart["verification_commands"] == [{
        "command": "python -m pytest -q test_sample.py",
        "previous_status": "passed",
        "evidence_refs": [restart["verification_commands"][0]["evidence_refs"][0]],
        "proof_source": "completion-packet/v1.checks/CHK-0001",
    }]
    assert packet["next_safe_action"]["command"] == "python -m pytest -q test_sample.py"
    assert "test_sample.py" in restart["changed_paths"]
    assert restart["documentation_candidates"] == []
    assert f"pcl evidence show {finish['packet']['evidence_id']} --json" in (
        restart["evidence_resolution_commands"]
    )
    assert _state_fingerprint(tmp_path) == before

    assert main([
        "--root", str(tmp_path), "resume", "--target", "T-0001",
        "--format", "markdown",
    ]) == 0
    markdown = capsys.readouterr().out
    assert "## Verified" in markdown
    assert packet["verified"][0]["text"] in markdown
    assert "## Unverified" in markdown
    assert "## Restart context" in markdown
    assert "Acceptance status: intent_only" in markdown
    assert "commands were not rerun by resume" in markdown


def test_resume_restart_context_is_fresh_session_executable_from_public_commands(
    tmp_path: Path,
    capsys,
) -> None:
    _packet_project(tmp_path, capsys, passing=True)
    exit_code, _finish_payload = _finish(tmp_path, capsys)
    assert exit_code == 0
    before = _state_fingerprint(tmp_path)

    assert main(["--root", str(tmp_path), "resume", "--json"]) == 0
    packet = _json_output(capsys)["handoff_packet"]
    restart = packet["restart_context"]

    for command in restart["evidence_resolution_commands"]:
        argv = shlex.split(command)
        assert argv.pop(0) == "pcl"
        assert main(["--root", str(tmp_path), *argv]) == 0
        resolved = _json_output(capsys)
        assert resolved["evidence"]["id"] in command
        assert "stdout" not in json.dumps(resolved).lower()

    replay = subprocess.run(
        shlex.split(restart["verification_commands"][0]["command"]),
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert _state_fingerprint(tmp_path) == before


def test_restart_context_deduplicates_orders_bounds_and_marks_documentation_candidates() -> None:
    from pcl.resume import _restart_context

    checks = [
        {
            "id": "CHK-0002", "command": "python -m pytest", "status": "passed",
            "artifact_ref": "evidence:E-0002", "reproducible": True,
        },
        {
            "id": "CHK-0001", "command": "ruff check .", "status": "passed",
            "artifact_ref": "evidence:E-0001", "reproducible": True,
        },
        {
            "id": "CHK-0003", "command": "ruff check .", "status": "failed",
            "artifact_ref": "evidence:E-0003", "reproducible": True,
        },
        {
            "id": "CHK-0004", "command": "manual browser", "status": "passed",
            "artifact_ref": None, "reproducible": False,
        },
    ]
    changes = [
        {"path": "src/app.py", "change_type": "modified"},
        {"path": "README.md", "change_type": "modified"},
        {"path": "docs/usage.md", "change_type": "added"},
    ] + [
        {"path": f"src/path-{index:02d}.py", "change_type": "added"}
        for index in range(60)
    ] + [{"path": "src/README-extra.md", "change_type": "added"}]
    completion = {
        "evidence_id": "E-0099",
        "packet": {
            "target": {
                "intent": "Ship executable resume context",
                "work_brief_ref": "evidence:E-0042",
            },
            "checks": checks,
            "changes": changes,
        },
    }

    restart = _restart_context(
        target={"type": "task", "id": "T-0001", "intent": "fallback"},
        completion=completion,
        context_refs=[],
    )

    assert restart["acceptance_status"] == "work_brief_linked"
    assert restart["acceptance_ref"] == "evidence:E-0042"
    assert [item["command"] for item in restart["verification_commands"]] == [
        "python -m pytest", "ruff check .",
    ]
    assert restart["verification_commands"][1] == {
        "command": "ruff check .",
        "previous_status": "failed",
        "evidence_refs": ["evidence:E-0001", "evidence:E-0003"],
        "proof_source": "completion-packet/v1.checks/CHK-0003",
    }
    assert len(restart["changed_paths"]) == 50
    assert restart["documentation_candidates"] == [
        "README.md", "docs/usage.md", "src/README-extra.md",
    ]
    assert restart["evidence_resolution_commands"] == [
        "pcl evidence show E-0001 --json",
        "pcl evidence show E-0002 --json",
        "pcl evidence show E-0003 --json",
        "pcl evidence show E-0042 --json",
        "pcl evidence show E-0099 --json",
    ]


def test_duplicate_reproducible_check_pass_then_fail_is_not_recommended() -> None:
    from pcl.resume import (
        _first_passed_replay_command,
        _next_safe_action,
        _verification_commands,
    )

    packet = {
        "checks": [
            {
                "id": "CHK-0001", "command": "ruff check .", "status": "passed",
                "artifact_ref": "evidence:E-0001", "reproducible": True,
            },
            {
                "id": "CHK-0002", "command": "ruff check .", "status": "failed",
                "artifact_ref": "evidence:E-0002", "reproducible": True,
            },
        ]
    }

    assert _verification_commands(packet) == [{
        "command": "ruff check .",
        "previous_status": "failed",
        "evidence_refs": ["evidence:E-0001", "evidence:E-0002"],
        "proof_source": "completion-packet/v1.checks/CHK-0002",
    }]
    assert _first_passed_replay_command(packet) is None
    assert _next_safe_action({"type": "task", "status": "done"}, packet, [])["command"] is None


def test_duplicate_reproducible_check_fail_then_pass_is_recommended() -> None:
    from pcl.resume import (
        _first_passed_replay_command,
        _next_safe_action,
        _verification_commands,
    )

    packet = {
        "checks": [
            {
                "id": "CHK-0001", "command": "ruff check .", "status": "failed",
                "artifact_ref": "evidence:E-0001", "reproducible": True,
            },
            {
                "id": "CHK-0002", "command": "ruff check .", "status": "passed",
                "artifact_ref": "evidence:E-0002", "reproducible": True,
            },
        ]
    }

    assert _verification_commands(packet) == [{
        "command": "ruff check .",
        "previous_status": "passed",
        "evidence_refs": ["evidence:E-0001", "evidence:E-0002"],
        "proof_source": "completion-packet/v1.checks/CHK-0002",
    }]
    assert _first_passed_replay_command(packet) == "ruff check ."
    assert _next_safe_action({"type": "task", "status": "done"}, packet, [])["command"] == (
        "ruff check ."
    )


def test_resume_incomplete_then_newer_packet_marks_older_packet_omitted(
    tmp_path: Path,
    capsys,
) -> None:
    _packet_project(tmp_path, capsys, passing=False)
    first_exit, first = _finish(tmp_path, capsys)
    assert first_exit == 1
    assert first["packet"]["outcome"] == "INCOMPLETE_VALIDATION"

    test_path = tmp_path / "test_sample.py"
    test_path.write_text(
        "def test_sample():\n    assert True\n\n# fixed resume packet change\n",
        encoding="utf-8",
    )
    second_exit, second = _finish(tmp_path, capsys)
    assert second_exit == 0

    assert main(["--root", str(tmp_path), "resume", "--json"]) == 0
    packet = _json_output(capsys)["handoff_packet"]

    refs = [item["ref"] for item in packet["context_refs"]]
    assert f"evidence:{second['packet']['evidence_id']}" in refs
    assert f"evidence:{first['packet']['evidence_id']}" not in refs
    assert "superseded_completion_packets" in packet["omitted_sections"]
    assert packet["verified"]


def test_resume_marks_completion_packet_stale_after_repository_drift(
    tmp_path: Path,
    capsys,
) -> None:
    _packet_project(tmp_path, capsys, passing=True)
    exit_code, _finish_payload = _finish(tmp_path, capsys)
    assert exit_code == 0
    _git(tmp_path, "add", "test_sample.py")
    _git(tmp_path, "commit", "-m", "advance after completion")

    assert main(["--root", str(tmp_path), "resume", "--json"]) == 0
    packet = _json_output(capsys)["handoff_packet"]

    completion_ref = next(
        item for item in packet["context_refs"] if item["kind"] == "completion-packet/v1"
    )
    assert completion_ref["freshness"] == "stale"


def test_resume_open_decision_becomes_blocker_and_safe_action(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _start(tmp_path, capsys)
    assert main([
        "--root", str(tmp_path), "decision", "open",
        "--question", "Choose compatibility mode",
        "--recommendation", "Keep compatibility",
        "--blocks-json", '[{"type":"task","id":"T-0001"}]',
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "resume", "--json"]) == 0
    packet = _json_output(capsys)["handoff_packet"]

    assert packet["decisions"] == [{"id": "DEC-0001", "summary": "Choose compatibility mode"}]
    assert packet["blockers"] == ["DEC-0001: Choose compatibility mode"]
    assert packet["next_safe_action"]["command"] == "pcl decision read DEC-0001 --json"


def test_resume_references_master_trace_and_intent_index_without_inlining(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _start(tmp_path, capsys)
    master_trace = tmp_path / "master-trace.md"
    master_trace.write_text(
        "---\ncontract_version: master-trace/v0\n---\nRAW_TRANSCRIPT_SENTINEL\n",
        encoding="utf-8",
    )
    assert main([
        "--root", str(tmp_path), "evidence", "add", "--file", master_trace.name,
        "--summary", master_trace.stem, "--task", "T-0001", "--copy", "--json",
    ]) == 0
    trace_evidence = _json_output(capsys)["evidence"]
    trace_member = trace_evidence["members"][0]
    intent_index = tmp_path / "intent-index.json"
    intent_index.write_text(json.dumps({
        "contract_version": "intent-index/v0",
        "index_id": "ii-resume-fixture",
        "generated_at": "2026-07-15T00:00:00Z",
        "generator": "test-fixture",
        "source_trace": {
            "evidence_id": trace_evidence["id"],
            "manifest_path": trace_evidence["manifest_path"],
            "member_path": trace_member["path"],
            "stored_path": trace_member["stored_path"],
            "sha256": trace_member["sha256"],
        },
        "items": [{
            "id": "I-001",
            "kind": "task_hint",
            "claim": "Continue from the source-bound claim.",
            "source_refs": [{
                "evidence_id": trace_evidence["id"],
                "stored_path": trace_member["stored_path"],
                "line_start": 4,
                "line_end": 4,
            }],
        }],
    }) + "\n", encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "evidence", "add", "--file", intent_index.name,
        "--summary", intent_index.stem, "--task", "T-0001", "--copy", "--json",
    ]) == 0
    index_evidence = _json_output(capsys)["evidence"]

    assert main(["--root", str(tmp_path), "resume", "--json"]) == 0
    packet = _json_output(capsys)["handoff_packet"]

    kinds = {item["kind"]: item for item in packet["context_refs"]}
    assert kinds["master-trace/v0"]["freshness"] == "current"
    assert kinds["intent-index/v0"]["freshness"] == "current"
    assert kinds["master-trace/v0"]["sha256"].startswith("sha256:")
    assert packet["intent_index_ref"] == kinds["intent-index/v0"]["ref"]
    assert packet["trace_claim_refs"] == [{
        "intent_index_ref": f"evidence:{index_evidence['id']}",
        "item_id": "I-001",
        "kind": "task_hint",
        "claim": "Continue from the source-bound claim.",
        "trust": "unverified",
        "source_refs": [{
            "evidence_id": trace_evidence["id"],
            "stored_path": trace_member["stored_path"],
            "line_start": 4,
            "line_end": 4,
        }],
    }]
    assert packet["trace_claim_ref_omissions"] == []
    assert packet["trace_claim_ref_budget"]["included_items"] == 1
    assert packet["verified"] == []
    assert "RAW_TRANSCRIPT_SENTINEL" not in json.dumps(packet)
    markdown = render_handoff_markdown(packet)
    assert "Continue from the source-bound claim." in markdown
    assert "RAW_TRANSCRIPT_SENTINEL" not in markdown
    assert "full_transcript" in packet["omitted_sections"]


def test_resume_output_file_is_the_only_write(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _start(tmp_path, capsys)
    before = _state_fingerprint(tmp_path)
    output = tmp_path / "handoff.json"

    assert main([
        "--root", str(tmp_path), "resume", "--target", "T-0001",
        "--format", "json", "--output", str(output), "--json",
    ]) == 0
    payload = _json_output(capsys)

    assert payload["output"] == str(output)
    assert json.loads(output.read_text(encoding="utf-8"))["contract_version"] == "handoff-packet/v1"
    assert _state_fingerprint(tmp_path) == before


def test_resume_invalid_trace_binding_emits_no_claim_refs(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _start(tmp_path, capsys)
    trace = tmp_path / "master-trace.md"
    trace.write_text(
        "---\ncontract_version: master-trace/v0\n---\nRAW_INVALID_TRACE_SENTINEL\n",
        encoding="utf-8",
    )
    index = tmp_path / "intent-index.json"
    index.write_text(
        json.dumps({"contract_version": "intent-index/v0", "items": []}) + "\n",
        encoding="utf-8",
    )
    for path in (trace, index):
        assert main([
            "--root", str(tmp_path), "evidence", "add", "--file", path.name,
            "--summary", path.stem, "--task", "T-0001", "--copy", "--json",
        ]) == 0
        _json_output(capsys)
    before = _state_fingerprint(tmp_path)

    assert main(["--root", str(tmp_path), "resume", "--json"]) == 0
    packet = _json_output(capsys)["handoff_packet"]

    assert "trace_claim_refs" not in packet
    assert "trace_claim_refs:invalid_binding" in packet["omitted_sections"]
    assert "RAW_INVALID_TRACE_SENTINEL" not in json.dumps(packet)
    assert _state_fingerprint(tmp_path) == before


def test_resume_output_refuses_project_loop_state_paths(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _start(tmp_path, capsys)
    before = _state_fingerprint(tmp_path)
    database = tmp_path / ".project-loop" / "project.db"

    assert main([
        "--root", str(tmp_path), "resume", "--output", str(database), "--json",
    ]) == 2
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "invalid_input"
    assert "cannot overwrite Project Loop state" in payload["error"]["message"]
    assert _state_fingerprint(tmp_path) == before
