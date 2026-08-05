from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from pcl.cli import main
from pcl.contracts.completion_packet import with_computed_packet_id
from pcl.errors import InvalidInputError


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _set_commands(root: Path, body: str) -> None:
    config = root / "pcl.yaml"
    before = config.read_text(encoding="utf-8")
    prefix, separator, suffix = before.partition("commands:\n")
    assert separator
    _, discovery, remainder = suffix.partition("\ndiscovery:\n")
    assert discovery
    config.write_text(
        prefix + "commands:\n" + body + "\ndiscovery:\n" + remainder,
        encoding="utf-8",
    )


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_stdout(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _prepare_terminal_goal(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    _set_commands(tmp_path, '  lint: "ruff check --no-cache source.py"\n')
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "pcl@example.test")
    _git(tmp_path, "config", "user.name", "PCL Test")
    (tmp_path / "source.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    assert main(["--root", str(tmp_path), "start", "Direct work", "--json"]) == 0
    _json_output(capsys)
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "task",
                "status",
                "T-0001",
                "done",
                "--reason",
                "Implementation complete",
                "--json",
            ]
        )
        == 0
    )
    _json_output(capsys)
    (tmp_path / "source.py").write_text("VALUE = 2\n", encoding="utf-8")


def _emit_goal_packet(
    tmp_path: Path,
    capsys,
    *,
    timeout: int = 10,
    base: str | None = None,
) -> dict:
    base_args = ["--base", base] if base is not None else []
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "finish",
                "--emit-packet",
                "--goal",
                "G-0001",
                "--timeout",
                str(timeout),
                *base_args,
                "--json",
            ]
        )
        == 0
    )
    return _json_output(capsys)["finish"]


def _next_goal(tmp_path: Path, capsys) -> dict:
    assert main(["--root", str(tmp_path), "next", "--target", "G-0001", "--json"]) == 0
    return _json_output(capsys)


def _record_fake_timeout(root: Path, command: dict, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "01-finish.stdout.txt"
    stderr_path = run_dir / "01-finish.stderr.txt"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("Timed out during test.\n", encoding="utf-8")
    command.update(
        {
            "exit_code": None,
            "status": "failed",
            "timed_out": True,
            "stdout_path": str(stdout_path.relative_to(root)),
            "stderr_path": str(stderr_path.relative_to(root)),
            "stdout": {"text": "", "path": str(stdout_path.relative_to(root))},
            "stderr": {
                "text": "Timed out during test.\n",
                "path": str(stderr_path.relative_to(root)),
            },
            "output_truncated": False,
            "redacted": False,
            "termination": {"reason": "timeout", "signal": "SIGTERM"},
            "failure_kind": "timeout",
            "permission_contract": {"backend": "test"},
        }
    )


def test_next_routes_current_goal_packet_to_agent_safe_close(
    tmp_path: Path,
    capsys,
) -> None:
    _prepare_terminal_goal(tmp_path, capsys)
    finish = _emit_goal_packet(tmp_path, capsys)
    packet = finish["packet"]
    events_before = (tmp_path / ".project-loop" / "events.jsonl").read_bytes()

    action = _next_goal(tmp_path, capsys)

    assert action["type"] == "close_goal"
    assert action["command"] == (
        "pcl goal close G-0001 --summary 'Summarize completed goal' "
        f"--evidence-id {packet['evidence_id']}"
    )
    assert action["target"]["completion_packet_evidence_id"] == packet["evidence_id"]
    assert action["target"]["packet_outcome"] == packet["outcome"]
    assert action["target_binding"] == {
        "source": "explicit",
        "target_id": "G-0001",
        "target_type": "goal",
    }
    assert action["routing_scope"] == "target"
    assert action["blocking"] is False
    assert action["requires_human"] is False
    assert action["safe_to_run"] is True
    assert action["run_policy"] == "agent_safe"
    assert (tmp_path / ".project-loop" / "events.jsonl").read_bytes() == events_before

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "close_goal"

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "goal",
                "close",
                "G-0001",
                "--summary",
                "Verified direct work is complete",
                "--evidence-id",
                packet["evidence_id"],
                "--json",
            ]
        )
        == 0
    )
    closed = _json_output(capsys)
    assert closed["goal_id"] == "G-0001"
    assert closed["status"] == "closed"

    terminal = _next_goal(tmp_path, capsys)
    assert terminal["type"] == "target_terminal"
    assert terminal["target"]["id"] == "G-0001"
    assert terminal["target"]["status"] == "closed"


def test_next_routes_current_goal_packet_with_explicit_ancestor_base(
    tmp_path: Path,
    capsys,
) -> None:
    _prepare_terminal_goal(tmp_path, capsys)
    base = _git_stdout(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "add", "source.py")
    _git(tmp_path, "commit", "-m", "current head")
    (tmp_path / "source.py").write_text("VALUE = 3\n", encoding="utf-8")
    finish = _emit_goal_packet(tmp_path, capsys, base=base)
    packet = finish["packet"]
    packet_body = json.loads((tmp_path / packet["path"]).read_text(encoding="utf-8"))
    events_before = (tmp_path / ".project-loop" / "events.jsonl").read_bytes()

    action = _next_goal(tmp_path, capsys)

    assert packet_body["repository"]["base_revision"] == base
    assert packet_body["repository"]["head_revision"] != base
    assert action["type"] == "close_goal"
    assert action["command"].endswith(f"--evidence-id {packet['evidence_id']}")
    assert action["target"]["completion_packet_evidence_id"] == packet["evidence_id"]
    assert (tmp_path / ".project-loop" / "events.jsonl").read_bytes() == events_before


def test_next_fails_closed_when_recorded_packet_base_cannot_be_recaptured(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _prepare_terminal_goal(tmp_path, capsys)
    base = _git_stdout(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "add", "source.py")
    _git(tmp_path, "commit", "-m", "current head")
    (tmp_path / "source.py").write_text("VALUE = 3\n", encoding="utf-8")
    _emit_goal_packet(tmp_path, capsys, base=base)
    observed_bases: list[str | None] = []

    def reject_snapshot(paths, *, base_revision=None):
        observed_bases.append(base_revision)
        raise InvalidInputError("Recorded base cannot be resolved.")

    monkeypatch.setattr(
        "pcl.action_routing.capture_finish_repository_snapshot",
        reject_snapshot,
    )

    action = _next_goal(tmp_path, capsys)

    assert observed_bases == [base]
    assert action["type"] == "emit_completion_packet"
    assert action["command"] == "pcl finish --emit-packet --goal G-0001 --json"


def test_next_does_not_fall_back_to_older_packet_when_latest_is_invalid(
    tmp_path: Path,
    capsys,
) -> None:
    _prepare_terminal_goal(tmp_path, capsys)
    first = _emit_goal_packet(tmp_path, capsys)
    second = _emit_goal_packet(tmp_path, capsys)
    assert first["packet"]["evidence_id"] != second["packet"]["evidence_id"]
    latest_path = tmp_path / second["packet"]["path"]
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest["target"]["id"] = "G-9999"
    latest_path.write_text(json.dumps(latest), encoding="utf-8")

    action = _next_goal(tmp_path, capsys)

    assert action["type"] == "emit_completion_packet"
    assert action["command"] == "pcl finish --emit-packet --goal G-0001 --json"


def test_goal_fake_timeout_without_deferred_recorder_fails_closed(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _prepare_terminal_goal(tmp_path, capsys)
    completed = _emit_goal_packet(tmp_path, capsys)

    def fake_timeout(paths, command, *, run_dir, **kwargs):
        _record_fake_timeout(paths.root, command, run_dir)

    monkeypatch.setattr(
        "pcl.finish_execution.execute_planned_guarded_command",
        fake_timeout,
    )
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "finish",
                "--emit-packet",
                "--goal",
                "G-0001",
                "--timeout",
                "600",
                "--json",
            ]
        )
        == 4
    )
    assert _json_output(capsys) == {
        "ok": False,
        "error": {
            "code": "data_store_error",
            "message": (
                "Finish check did not produce a deferred parent runner authority seal."
            ),
            "details": {"failure_kind": "runner_authority_anchor_missing"},
        },
    }

    action = _next_goal(tmp_path, capsys)

    assert action["type"] == "close_goal"
    assert action["target"]["completion_packet_evidence_id"] == (
        completed["packet"]["evidence_id"]
    )
    assert action["target_binding"]["target_id"] == "G-0001"


def test_next_rejects_superseded_goal_packet(
    tmp_path: Path,
    capsys,
) -> None:
    _prepare_terminal_goal(tmp_path, capsys)
    finish = _emit_goal_packet(tmp_path, capsys)
    replacement_path = tmp_path.parent / f"{tmp_path.name}-replacement.txt"
    replacement_path.write_text("replacement proof\n", encoding="utf-8")
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "evidence",
                "add",
                "--file",
                str(replacement_path),
                "--summary",
                "Replacement proof",
                "--copy",
                "--json",
            ]
        )
        == 0
    )
    replacement_id = _json_output(capsys)["evidence"]["id"]
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "evidence",
                "supersede",
                finish["packet"]["evidence_id"],
                "--with",
                replacement_id,
                "--summary",
                "Packet no longer authoritative",
                "--json",
            ]
        )
        == 0
    )
    _json_output(capsys)

    action = _next_goal(tmp_path, capsys)

    assert action["type"] == "emit_completion_packet"


def test_next_rejects_high_risk_goal_packet(
    tmp_path: Path,
    capsys,
) -> None:
    _prepare_terminal_goal(tmp_path, capsys)
    finish = _emit_goal_packet(tmp_path, capsys)
    packet_path = tmp_path / finish["packet"]["path"]
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["risks"].append(
        {
            "severity": "high",
            "text": "Human review is still required.",
            "mitigation": "Do not close the Goal automatically.",
        }
    )
    packet = with_computed_packet_id(packet)
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    action = _next_goal(tmp_path, capsys)

    assert action["type"] == "emit_completion_packet"


def test_next_rejects_completed_packet_after_repository_drift(
    tmp_path: Path,
    capsys,
) -> None:
    _prepare_terminal_goal(tmp_path, capsys)
    _emit_goal_packet(tmp_path, capsys)
    (tmp_path / "source.py").write_text("VALUE = 3\n", encoding="utf-8")

    action = _next_goal(tmp_path, capsys)

    assert action["type"] == "emit_completion_packet"
    assert action["command"] == "pcl finish --emit-packet --goal G-0001 --json"


def test_next_without_goal_packet_retains_emit_contract(
    tmp_path: Path,
    capsys,
) -> None:
    _prepare_terminal_goal(tmp_path, capsys)

    action = _next_goal(tmp_path, capsys)

    assert action["type"] == "emit_completion_packet"
    assert action["command"] == "pcl finish --emit-packet --goal G-0001 --json"
    assert action["safe_to_run"] is True
    assert action["target_binding"]["target_id"] == "G-0001"


def test_goal_close_help_names_terminal_proof_identifier_types(
    capsys,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["goal", "close", "--help"])
    assert exc_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split()).replace("- ", "-")

    assert "--evidence-id E-XXXX" in help_text
    assert "Completed goal-bound packet Evidence ID for a direct-route Goal." in help_text
    assert "--verification V-XXXX" in help_text
    assert "Approved Verification ID from a Workflow Run for this Goal." in help_text
    assert "Raw inline Evidence" in help_text
