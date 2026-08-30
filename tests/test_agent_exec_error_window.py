from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from pcl.cli import main as cli_main


def test_streaming_error_window_preserves_redacted_true_middle_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = tmp_path / "state"
    work_root = tmp_path / "work"
    work_root.mkdir()
    monkeypatch.setenv("PCL_AGENT_EXEC_STATE_DIR", str(state_root))
    monkeypatch.chdir(work_root)
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"
    script = (
        "import sys; "
        "sys.stdout.write('before\\n' * 20000); "
        f"sys.stdout.write('RuntimeError: TRUE_MIDDLE_SENTINEL {secret}\\n'); "
        "sys.stdout.write('after\\n' * 20000); "
        "raise SystemExit(7)"
    )

    exit_code = cli_main(
        [
            "exec",
            "--max-output-bytes",
            "32768",
            "--",
            sys.executable,
            "-c",
            script,
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 7
    assert "TRUE_MIDDLE_SENTINEL" in captured.out
    assert secret not in captured.out
    metadata_path = next(state_root.rglob("meta.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["diagnostics"]["strategy"] == "error-block"
    assert metadata["output_truncated"] is True
    diagnostic = next(state_root.rglob("diagnostic.redacted.log")).read_text(
        encoding="utf-8"
    )
    assert "TRUE_MIDDLE_SENTINEL" in diagnostic
    assert secret not in diagnostic
