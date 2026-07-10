from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "completion_packet"


def test_contract_validate_json_success_has_pure_stdout(capsys) -> None:
    fixture = FIXTURE_ROOT / "minimal.json"

    assert main(["contract", "validate", "--type", "completion-packet/v1", str(fixture), "--json"]) == 0
    captured = capsys.readouterr()

    assert captured.err == ""
    assert json.loads(captured.out) == {
        "contract_type": "completion-packet/v1",
        "errors": [],
        "ok": True,
        "path": str(fixture),
    }
    assert captured.out.count("\n") == 1


def test_contract_validate_json_failure_has_pure_stdout(capsys) -> None:
    fixture = FIXTURE_ROOT / "negative-critical-proof.json"

    assert main(["contract", "validate", "--type", "completion-packet/v1", str(fixture), "--json"]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert captured.err == ""
    assert payload["ok"] is False
    assert any("critical claims at L2 or above" in error for error in payload["errors"])


def test_contract_validate_malformed_json_is_usage_error(tmp_path: Path, capsys) -> None:
    malformed = tmp_path / "packet.json"
    malformed.write_text("{not-json\n", encoding="utf-8")

    assert main(["contract", "validate", "--type", "completion-packet/v1", str(malformed), "--json"]) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert captured.err == ""
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"]["path"] == str(malformed)


def test_contract_validate_is_read_only(tmp_path: Path, capsys) -> None:
    fixture = FIXTURE_ROOT / "full.json"

    assert main(["--root", str(tmp_path), "contract", "validate", "--type", "completion-packet/v1", str(fixture), "--json"]) == 0
    capsys.readouterr()

    assert list(tmp_path.iterdir()) == []
