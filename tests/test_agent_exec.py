from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

import pytest

import pcl.agent_exec as agent_exec_module
from pcl.agent_exec import AgentExecStore, run_agent_command
from pcl.cli import main as cli_main
from pcl.contracts.agent_exec_result import validate_agent_exec_result
from pcl.redaction import REDACTED_SECRET


def _state_dir(tmp_path: Path) -> Path:
    return tmp_path / "agent-exec-state"


def _json_result(capsys: pytest.CaptureFixture[str]) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_6500_line_pass_is_one_line_and_creates_no_project_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = _state_dir(tmp_path)
    script = "for index in range(6500): print(f'passed {index}')"

    exit_code = cli_main([
        "--root", str(tmp_path),
        "exec", "--state-dir", str(state_dir),
        "--max-output-bytes", "4096",
        "--", sys.executable, "-c", script,
    ])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert len(output.splitlines()) <= 5
    assert len(output.encode("utf-8")) <= 2048
    assert output.startswith("PASS run=AX-")
    assert not (tmp_path / ".project-loop").exists()

    run_id = output.split("run=", 1)[1].split(" ", 1)[0]
    run_dir = AgentExecStore(state_dir).run_dir(run_id)
    metadata = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "PASS"
    assert metadata["raw"]["stdout_bytes"] > metadata["exposed"]["bytes"]
    assert metadata["diagnostics"]["preview"] == []
    assert not (run_dir / "diagnostic.redacted.log").exists()
    assert validate_agent_exec_result(metadata) == []


def test_middle_failure_survives_bounded_capture_and_preserves_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = _state_dir(tmp_path)
    script = (
        "import os, sys; "
        "os.write(1, b'prefix\\n' * 20000); "
        "os.write(1, b'AssertionError: middle boom\\n'); "
        "os.write(1, b'suffix\\n' * 20000); "
        "sys.exit(7)"
    )

    exit_code = cli_main([
        "--root", str(tmp_path), "--json",
        "exec", "--state-dir", str(state_dir),
        "--max-output-bytes", "4096",
        "--", sys.executable, "-c", script,
    ])

    assert exit_code == 7
    payload = _json_result(capsys)
    assert payload["status"] == "FAIL"
    assert payload["exit_code"] == 7
    assert payload["shell_exit_code"] == 7
    assert payload["capture"]["stdout_truncated"] is True
    assert any("AssertionError: middle boom" in line for line in payload["diagnostics"]["preview"])
    assert payload["exposed"]["lines"] <= 120
    assert payload["exposed"]["bytes"] <= 24 * 1024
    assert payload["raw"]["stdout_bytes"] > payload["exposed"]["bytes"]
    assert not (tmp_path / ".project-loop").exists()
    assert validate_agent_exec_result(payload) == []

    diagnostic = AgentExecStore(state_dir).read_diagnostic(payload["run_id"])
    assert "AssertionError: middle boom" in diagnostic
    assert len(diagnostic.splitlines()) <= 117
    assert len(diagnostic.encode("utf-8")) <= 16 * 1024


def test_child_global_looking_arguments_after_separator_are_not_consumed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = _state_dir(tmp_path)
    captured_argv = tmp_path / "child-argv.json"
    script = tmp_path / "capture_argv.py"
    script.write_text(
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(captured_argv)!r}).write_text(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )

    exit_code = cli_main([
        "--root", str(tmp_path),
        "exec", "--state-dir", str(state_dir),
        "--", sys.executable, str(script), "--json", "--root", "child-value",
    ])

    assert exit_code == 0
    capsys.readouterr()
    assert json.loads(captured_argv.read_text(encoding="utf-8")) == [
        "--json", "--root", "child-value"
    ]


def test_spawn_failure_is_typed_and_returns_shell_127(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli_main([
        "--root", str(tmp_path), "--json",
        "exec", "--state-dir", str(_state_dir(tmp_path)),
        "--", "pcl-command-that-does-not-exist-0228",
    ])

    assert exit_code == 127
    payload = _json_result(capsys)
    assert payload["status"] == "INFRA_ERROR"
    assert payload["exit_code"] is None
    assert payload["shell_exit_code"] == 127
    assert any("FileNotFoundError" in line for line in payload["diagnostics"]["preview"])


def test_timeout_is_typed_and_process_group_cleanup_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli_main([
        "--root", str(tmp_path), "--json",
        "exec", "--state-dir", str(_state_dir(tmp_path)),
        "--timeout-seconds", "1",
        "--", sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)",
    ])

    assert exit_code == 124
    payload = _json_result(capsys)
    assert payload["status"] == "TIMEOUT"
    assert payload["termination"]["requested"] is True
    assert payload["shell_exit_code"] == 124


def test_secret_shaped_output_and_argv_are_not_persisted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    exit_code = cli_main([
        "--root", str(tmp_path), "--json",
        "exec", "--state-dir", str(_state_dir(tmp_path)),
        "--", sys.executable, "-c",
        "import sys; print(sys.argv[1]); raise RuntimeError('token=' + sys.argv[1])",
        secret,
    ])

    assert exit_code == 1
    payload = _json_result(capsys)
    serialized = json.dumps(payload, ensure_ascii=False)
    diagnostic = AgentExecStore(_state_dir(tmp_path)).read_diagnostic(payload["run_id"])
    metadata = (AgentExecStore(_state_dir(tmp_path)).run_dir(payload["run_id"]) / "meta.json").read_text(
        encoding="utf-8"
    )
    assert secret not in serialized
    assert secret not in diagnostic
    assert secret not in metadata
    assert REDACTED_SECRET in serialized or REDACTED_SECRET in diagnostic
    assert payload["command"]["argv_omitted"] is True
    assert payload["command"]["redacted"] is True


def test_binary_failure_is_not_decoded_into_persisted_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli_main([
        "--root", str(tmp_path), "--json",
        "exec", "--state-dir", str(_state_dir(tmp_path)),
        "--", sys.executable, "-c",
        "import os, sys; os.write(2, b'prefix\\xffsuffix'); sys.exit(3)",
    ])

    assert exit_code == 3
    payload = _json_result(capsys)
    diagnostic = AgentExecStore(_state_dir(tmp_path)).read_diagnostic(payload["run_id"])
    assert "binary or invalid UTF-8" in diagnostic
    assert "prefix" not in diagnostic


def test_show_meta_and_gc_are_bounded_local_reads_and_cleanup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = _state_dir(tmp_path)
    exit_code = cli_main([
        "--root", str(tmp_path), "--json",
        "exec", "--state-dir", str(state_dir),
        "--", sys.executable, "-c", "raise AssertionError('inspect me')",
    ])
    assert exit_code == 1
    result = _json_result(capsys)
    run_id = result["run_id"]

    assert cli_main([
        "--json", "exec", "--state-dir", str(state_dir), "show", run_id, "--tail", "2"
    ]) == 0
    shown = _json_result(capsys)
    assert shown["schema"] == "agent-exec-diagnostic/v1"
    assert len(shown["lines"]) <= 2

    assert cli_main([
        "--json", "exec", "--state-dir", str(state_dir), "meta", run_id
    ]) == 0
    metadata = _json_result(capsys)
    assert metadata["run_id"] == run_id
    assert "path" not in json.dumps(metadata)

    run_dir = AgentExecStore(state_dir).run_dir(run_id)
    old = datetime.now(timezone.utc) - timedelta(hours=100)
    os.utime(run_dir, (old.timestamp(), old.timestamp()))

    assert cli_main([
        "--json", "exec", "--state-dir", str(state_dir), "gc", "--dry-run"
    ]) == 0
    dry_run = _json_result(capsys)
    assert run_id in dry_run["selected_runs"]
    assert run_dir.exists()

    assert cli_main([
        "--json", "exec", "--state-dir", str(state_dir), "gc"
    ]) == 0
    removed = _json_result(capsys)
    assert run_id in removed["selected_runs"]
    assert not run_dir.exists()


def test_interrupted_result_has_explicit_status_and_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_execute(argv, *, stdout_path, stderr_path, **kwargs):
        del argv, kwargs
        stdout_path.write_bytes(b"")
        stderr_path.write_bytes(b"Interrupted by caller.\n")
        stream = {
            "original_byte_count": 0,
            "captured_byte_count": 0,
            "artifact_byte_count": 0,
            "max_bytes": 4096,
            "truncated": False,
            "truncation_reason": "",
            "capture_strategy": "head_tail",
            "capture_mode": "fixture",
            "redacted": False,
            "raw_output_persisted": False,
            "encoding": "utf-8",
            "binary": False,
            "sha256": "sha256:" + "0" * 64,
        }
        return {
            "exit_code": None,
            "timed_out": False,
            "interrupted": True,
            "duration_seconds": 0.1,
            "failure_kind": "interrupted",
            "spawn_error_kind": "",
            "stdout": dict(stream),
            "stderr": {**stream, "original_byte_count": 23, "captured_byte_count": 23},
            "output_truncated": False,
            "redacted": False,
            "termination": {
                "requested": True,
                "escalated": False,
                "group_state": "gone",
                "group_uncertain": False,
                "pipes_eof": True,
            },
        }

    monkeypatch.setattr(agent_exec_module, "execute_guarded_process", fake_execute)
    payload, exit_code, _ = run_agent_command(
        ["fixture"],
        cwd=tmp_path,
        store=AgentExecStore(_state_dir(tmp_path)),
        max_output_bytes=4096,
    )
    assert exit_code == 130
    assert payload["status"] == "INTERRUPTED"
    assert payload["signal"] == 2
    assert validate_agent_exec_result(payload) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_agent_exec_state_is_owner_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state_dir = _state_dir(tmp_path)
    assert cli_main([
        "exec", "--state-dir", str(state_dir),
        "--", sys.executable, "-c", "raise SystemExit(2)",
    ]) == 2
    output = capsys.readouterr().out
    run_id = output.split("run=", 1)[1].split(" ", 1)[0]
    run_dir = AgentExecStore(state_dir).run_dir(run_id)
    assert state_dir.stat().st_mode & 0o777 == 0o700
    assert run_dir.stat().st_mode & 0o777 == 0o700
    assert (run_dir / "meta.json").stat().st_mode & 0o777 == 0o600
    assert (run_dir / "diagnostic.redacted.log").stat().st_mode & 0o777 == 0o600
