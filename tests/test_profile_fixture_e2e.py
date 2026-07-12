from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parent / "fixtures" / "profile_e2e" / "run_offline_e2e.py"
STATUSES = [
    "completed",
    "needs_human",
    "partial",
    "budget_exhausted",
    "failed",
    "skipped",
    "malformed",
]


@pytest.mark.parametrize("status", STATUSES)
def test_source_offline_fixture_e2e(tmp_path: Path, status: str) -> None:
    env = {**os.environ, "PYTHONPATH": str(Path("src").resolve())}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path / "project"), "--status", status],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["deterministic"] is True
    assert payload["provider_code_present"] is False
    if status == "malformed":
        assert payload["malformed_rejected"] is True
    else:
        assert payload["next_action"]["safe_to_run"] is False
        assert payload["network_used"] is False
        assert payload["paid_service_used"] is False
    if status == "needs_human":
        assert payload["selection"]["selected_option"] == "OPT-A"
        assert payload["projection_ok"] is True
        assert payload["brief_revision_review_approval_separate"] is True
