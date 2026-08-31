from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys

import pytest

from pcl.agent_exec import (
    FAIL_MAX_BYTES,
    FAIL_MAX_LINES,
    REDACTED_ARGUMENT,
    gc_agent_exec,
    run_agent_exec,
)
from pcl.cli import _extract_global_options, main as cli_main
from pcl.parser_agent_exec import AGENT_EXEC_ARGV_SENTINEL


RUN_ID_RE = re.compile(r"AX-\d{8}T\d{6}Z-[a-f0-9]{12}")


def _assert_no_sensitive_fixture_leak(value: str) -> None:
    if "SENTINEL" in value:
        raise AssertionError("sensitive fixture value was leaked")


def _assert_no_path_fixture_leak(value: str) -> None:
    if "REVIEWER_PATH_SENTINEL" in value:
        raise AssertionError("path fixture value was leaked")


def _prepare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    state_root = tmp_path / "state"
    work_root = tmp_path / "work"
    work_root.mkdir()
    monkeypatch.setenv("PCL_AGENT_EXEC_STATE_DIR", str(state_root))
    monkeypatch.chdir(work_root)
    return state_root


def _run_python(script: str, *extra: str) -> list[str]:
    return ["exec", "--", sys.executable, "-c", script, *extra]


def _run_id(text: str) -> str:
    match = RUN_ID_RE.search(text)
    assert match is not None
    return match.group(0)


def test_success_compresses_6500_lines_and_creates_no_project_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = _prepare(monkeypatch, tmp_path)
    script = "for i in range(6500): print(f'passed {i}')"

    exit_code = cli_main(_run_python(script))
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.startswith("PASS run=AX-")
    assert len(captured.out.splitlines()) <= 5
    assert len(captured.out.encode("utf-8")) <= 2_048
    assert not (tmp_path / "work" / ".project-loop").exists()
    metadata_files = list(state_root.rglob("meta.json"))
    assert len(metadata_files) == 1
    assert list(state_root.rglob("diagnostic.redacted.log")) == []
    payload = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["raw"]["stdout_bytes"] > payload["exposed"]["bytes"]
    assert payload["retry_count"] == 0
    assert payload["command"][0].startswith("<executable:")
    if os.name == "posix":
        assert state_root.stat().st_mode & 0o777 == 0o700
        assert metadata_files[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("position", ["head", "middle", "tail"])
def test_failure_location_remains_visible_within_bounded_diagnostics(
    position: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = _prepare(monkeypatch, tmp_path)
    if position == "head":
        script = "print('AssertionError: HEAD_SENTINEL'); [print('ok') for _ in range(3000)]; raise SystemExit(7)"
        argv = _run_python(script)
    elif position == "middle":
        script = (
            "[print('before') for _ in range(3000)]; "
            "print('AssertionError: MIDDLE_SENTINEL'); "
            "[print('after') for _ in range(3000)]; raise SystemExit(7)"
        )
        argv = _run_python(script)
    else:
        script = (
            "[print('x'*80) for _ in range(8000)]; "
            "print('AssertionError: TAIL_SENTINEL'); raise SystemExit(7)"
        )
        argv = ["exec", "--max-output-bytes", "262144", "--", sys.executable, "-c", script]

    exit_code = cli_main(argv)
    captured = capsys.readouterr()

    assert exit_code == 7
    assert f"{position.upper()}_SENTINEL" in captured.out
    assert len(captured.out.splitlines()) <= FAIL_MAX_LINES
    assert len(captured.out.encode("utf-8")) <= FAIL_MAX_BYTES
    diagnostic_files = list(state_root.rglob("diagnostic.redacted.log"))
    assert len(diagnostic_files) == 1
    assert f"{position.upper()}_SENTINEL" in diagnostic_files[0].read_text(encoding="utf-8")


def test_child_global_looking_options_after_separator_are_not_consumed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(monkeypatch, tmp_path)
    script = "import sys; raise SystemExit(0 if sys.argv[1:] == ['--json', '--root', 'child'] else 9)"

    exit_code = cli_main(
        [
            "--json",
            "exec",
            "--",
            sys.executable,
            "-c",
            script,
            "--json",
            "--root",
            "child",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert payload["command"][-3:] == ["--json", "--root", "child"]


def test_global_option_normalization_replaces_only_exec_separator() -> None:
    normalized, root, json_output = _extract_global_options(
        ["--json", "exec", "--timeout-seconds", "3", "--", "tool", "--json", "--root", "child"]
    )

    assert normalized == [
        "exec",
        "--timeout-seconds",
        "3",
        AGENT_EXEC_ARGV_SENTINEL,
        "tool",
        "--json",
        "--root",
        "child",
    ]
    assert root is None
    assert json_output is True


def test_spawn_failure_is_typed_and_preserves_conventional_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(monkeypatch, tmp_path)

    exit_code = cli_main(["--json", "exec", "--", "pcl-definitely-missing-executable"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 127
    assert payload["status"] == "INFRA_ERROR"
    assert payload["exit_code"] is None
    assert payload["diagnostics"]["available"] is True
    assert payload["termination"]["group_state"] == "not_started"


def test_timeout_terminates_without_false_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(monkeypatch, tmp_path)

    exit_code = cli_main(
        [
            "--json",
            "exec",
            "--timeout-seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(5)",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 124
    assert payload["status"] == "TIMEOUT"
    assert payload["termination"]["requested"] is True
    assert payload["status"] != "PASS"


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal exit semantics")
def test_signal_exit_is_interrupted_not_failure_or_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(monkeypatch, tmp_path)
    script = "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"

    exit_code = cli_main(["--json", *_run_python(script)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 128 + signal.SIGTERM
    assert payload["status"] == "INTERRUPTED"
    assert payload["signal"] == signal.SIGTERM


def test_secret_shaped_argv_and_output_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = _prepare(monkeypatch, tmp_path)
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"
    script = "import sys; print(sys.argv[-1]); raise SystemExit(1)"

    exit_code = cli_main(_run_python(script, "--token", secret))
    captured = capsys.readouterr()

    assert exit_code == 1
    assert secret not in captured.out
    for artifact in state_root.rglob("*"):
        if artifact.is_file():
            assert secret not in artifact.read_text(encoding="utf-8")
    metadata = json.loads(next(state_root.rglob("meta.json")).read_text(encoding="utf-8"))
    assert metadata["command"][-1] == REDACTED_ARGUMENT
    assert metadata["command_redacted"] is True


@pytest.mark.parametrize(
    "secret_argv",
    [
        ["--client-secret", "SENTINEL"],
        ["--client-secret=SENTINEL"],
        ["--AuthToken=SENTINEL"],
        ["--Client-Secret=SENTINEL"],
        ["--ClientSecret=SENTINEL"],
        ["--clientSecret=SENTINEL"],
        ["--client_secret=SENTINEL"],
        ["--client-secret:SENTINEL=tail"],
        ["--client-secret:SENTINEL"],
        ["authorization:SENTINEL=tail"],
        ["proxy-authorization:SENTINEL=tail"],
        ["API_TOKEN=SENTINEL"],
        ["--CLIENT_SECRET=SENTINEL"],
        ["AWS_SECRET_ACCESS_KEY=SENTINEL"],
    ],
)
def test_compound_secret_keys_are_redacted_from_exec_metadata(
    secret_argv: list[str],
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    outcome = run_agent_exec(
        [sys.executable, "-c", "raise SystemExit(0)", *secret_argv],
        cwd=tmp_path,
        timeout_seconds=5,
        max_output_bytes=1024,
        state_root=state_root,
    )

    metadata_path = next(state_root.rglob("meta.json"))
    metadata_text = metadata_path.read_text(encoding="utf-8")
    assert outcome.result["status"] == "PASS"
    _assert_no_sensitive_fixture_leak(metadata_text)
    assert REDACTED_ARGUMENT in metadata_text


def test_local_absolute_paths_are_omitted_from_command_and_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = _prepare(monkeypatch, tmp_path)
    work_root = tmp_path / "work"
    script = "import os; print(f'RuntimeError: {os.getcwd()}/private/file.py'); raise SystemExit(2)"

    exit_code = cli_main(_run_python(script, str(work_root / "input.txt")))
    captured = capsys.readouterr()

    assert exit_code == 2
    assert str(work_root) not in captured.out
    assert "<project-root>" in captured.out
    metadata_text = next(state_root.rglob("meta.json")).read_text(encoding="utf-8")
    assert str(work_root) not in metadata_text
    assert "<absolute-path>" in metadata_text


@pytest.mark.parametrize(
    "path_argv",
    [
        pytest.param(["/private/REVIEWER_PATH_SENTINEL/file.py"], id="posix-raw"),
        pytest.param([r"C:\REVIEWER_PATH_SENTINEL\file.py"], id="windows-drive-raw"),
        pytest.param([r"\\REVIEWER_PATH_SENTINEL\share\file.py"], id="windows-unc-raw"),
        pytest.param(["~/REVIEWER_PATH_SENTINEL/file.py"], id="home-raw"),
        pytest.param(
            ["--rootdir:/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="posix-colon",
        ),
        pytest.param(
            ["--rootdir=/private/REVIEWER_PATH_SENTINEL/file=tail.py"],
            id="posix-equals-with-equals",
        ),
        pytest.param(
            ["--rootdir", "/private/REVIEWER_PATH_SENTINEL/file.py"],
            id="posix-separated",
        ),
        pytest.param(
            [r"--rootdir:C:\REVIEWER_PATH_SENTINEL\file.py"],
            id="windows-drive-colon",
        ),
        pytest.param(
            [r"--rootdir=\\REVIEWER_PATH_SENTINEL\share\file.py"],
            id="windows-unc-equals",
        ),
        pytest.param(
            ["--rootdir:~/REVIEWER_PATH_SENTINEL/file.py"],
            id="home-colon",
        ),
    ],
)
def test_path_bearing_argv_reaches_child_unchanged_but_metadata_is_redacted(
    path_argv: list[str],
    tmp_path: Path,
) -> None:
    expected_digests = repr(
        [hashlib.sha256(value.encode("utf-8")).hexdigest() for value in path_argv]
    )
    script = (
        "import hashlib, sys; "
        "actual = [hashlib.sha256(value.encode('utf-8')).hexdigest() "
        "for value in sys.argv[1:]]; "
        f"raise SystemExit(0 if actual == {expected_digests} else 17)"
    )
    state_root = tmp_path / "state"

    outcome = run_agent_exec(
        [sys.executable, "-c", script, *path_argv],
        cwd=tmp_path,
        timeout_seconds=5,
        max_output_bytes=1024,
        state_root=state_root,
    )

    metadata_text = next(state_root.rglob("meta.json")).read_text(encoding="utf-8")
    assert outcome.result["status"] == "PASS"
    assert outcome.result["command_redacted"] is True
    _assert_no_path_fixture_leak(json.dumps(outcome.result))
    _assert_no_path_fixture_leak(metadata_text)
    assert "<absolute-path>" in metadata_text


def test_windows_absolute_executable_is_redacted_without_echoing_path(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    outcome = run_agent_exec(
        [r"C:\REVIEWER_PATH_SENTINEL\tool.exe"],
        cwd=tmp_path,
        timeout_seconds=5,
        max_output_bytes=1024,
        state_root=state_root,
    )

    metadata_text = next(state_root.rglob("meta.json")).read_text(encoding="utf-8")
    assert outcome.result["status"] == "INFRA_ERROR"
    _assert_no_path_fixture_leak(json.dumps(outcome.result))
    _assert_no_path_fixture_leak(metadata_text)


def test_long_argv_is_bounded_in_machine_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(monkeypatch, tmp_path)
    long_argument = "z" * 20_000

    exit_code = cli_main(["--json", *_run_python("raise SystemExit(0)", long_argument)])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["command_redacted"] is True
    assert max(len(item) for item in payload["command"]) <= 320
    assert len(output.encode("utf-8")) < 8_192


def test_binary_failure_is_omitted_from_text_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(monkeypatch, tmp_path)
    script = "import sys; sys.stdout.buffer.write(b'\\xff\\x00'); raise SystemExit(3)"

    exit_code = cli_main(["--json", *_run_python(script)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert payload["status"] == "FAIL"
    assert payload["diagnostics"]["strategy"] == "binary-omitted"


def test_show_meta_and_retention_gc_use_opaque_run_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = _prepare(monkeypatch, tmp_path)
    exit_code = cli_main(_run_python("print('RuntimeError: retained'); raise SystemExit(4)"))
    first = capsys.readouterr()
    assert exit_code == 4
    run_id = _run_id(first.out)

    assert cli_main(["exec", "show", run_id, "--tail", "1"]) == 0
    shown = capsys.readouterr().out
    assert "RuntimeError: retained" in shown
    assert len(shown.splitlines()) == 1

    assert cli_main(["--json", "exec", "meta", run_id]) == 0
    metadata = json.loads(capsys.readouterr().out)
    assert metadata["run_id"] == run_id
    assert metadata["status"] == "FAIL"
    assert str(state_root) not in json.dumps(metadata)

    run_dir = next(path for path in state_root.rglob(run_id) if path.is_dir())
    os.utime(run_dir, (1, 1))
    preview = gc_agent_exec(
        state_root=state_root,
        dry_run=True,
        now_timestamp=10_000,
        retention_seconds=1,
    )
    assert preview["candidate_run_ids"] == [run_id]
    assert run_dir.exists()
    applied = gc_agent_exec(
        state_root=state_root,
        dry_run=False,
        now_timestamp=10_000,
        retention_seconds=1,
    )
    assert applied["removed_run_ids"] == [run_id]
    assert not run_dir.exists()


def test_direct_execution_without_separator_fails_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = _prepare(monkeypatch, tmp_path)

    exit_code = cli_main(["exec", sys.executable, "-c", "print('must not run')"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "requires the `--` separator" in captured.err
    assert not state_root.exists()


def test_unsafe_run_directory_is_never_deleted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = _prepare(monkeypatch, tmp_path)
    assert cli_main(_run_python("raise SystemExit(1)")) == 1
    output = capsys.readouterr().out
    run_id = _run_id(output)
    run_dir = next(path for path in state_root.rglob(run_id) if path.is_dir())
    (run_dir / "unexpected.txt").write_text("keep", encoding="utf-8")
    os.utime(run_dir, (1, 1))

    result = gc_agent_exec(
        state_root=state_root,
        dry_run=False,
        now_timestamp=10_000,
        retention_seconds=1,
    )

    assert result["ok"] is False
    assert result["unsafe_run_ids"] == [run_id]
    assert run_dir.exists()
