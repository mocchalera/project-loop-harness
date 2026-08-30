from __future__ import annotations

from pathlib import Path
import sys

import pytest

from pcl.cli import main as cli_main


def test_printable_sentinel_text_cannot_replace_explicit_separator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = tmp_path / "must-not-run"
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main(
        [
            "exec",
            "__PCL_AGENT_EXEC_ARGV__",
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "requires the `--` separator" in captured.err
    assert not marker.exists()
