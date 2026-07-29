from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pcl.cli import main
from pcl.paths import resolve_paths
from pcl.validators import ValidationResult, validate_project


def _json_output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _initialized_target(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert (
        main(
            [
                "--root",
                str(root),
                "start",
                "Validation projection target",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()


def _mixed_validation_result() -> ValidationResult:
    result = ValidationResult()
    result.add_warning(
        "Current target warning",
        code="task_current_warning",
        entity={"type": "task", "id": "T-0001"},
        repair_class="inspect",
    )
    result.add_warning(
        "Historical target warning",
        code="task_historical_warning",
        entity={"type": "task", "id": "T-0001"},
        repair_class="inspect",
    )
    result.findings[-1].proof_scope = "historical"
    result.add_warning(
        "Unrelated warning",
        code="feature_unrelated_warning",
        entity={"type": "feature", "id": "F-9999"},
        repair_class="inspect",
    )
    result.add_warning(
        "Unknown warning must remain visible",
        code="future_unknown_warning",
        entity={"type": "feature", "id": "F-9998"},
        repair_class="inspect",
    )
    result.add_warning(
        "Human gate must remain visible",
        code="human_gate_warning",
        entity={"type": "decision", "id": "DEC-9999"},
        repair_class="semantic",
        requires_human=True,
    )
    result.add_error(
        "Global integrity error",
        code="audit_projection_event_missing",
        entity={"type": "project", "id": "/tmp/project"},
        repair_class="inspect",
    )
    return result


def test_validate_active_only_aggregates_historical_without_returning_its_message(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _initialized_target(tmp_path, capsys)
    full = _mixed_validation_result()
    monkeypatch.setattr("pcl.control_handlers.validate_project", lambda *args, **kwargs: full)

    assert main(["--root", str(tmp_path), "validate", "--active-only", "--json"]) == 1
    payload = _json_output(capsys)

    assert "Historical target warning" not in payload["warnings"]
    assert all(
        finding["message"] != "Historical target warning"
        for finding in payload["findings"]
    )
    assert payload["finding_counts"] == {"active": 5, "historical": 1}
    assert payload["validation_projection"]["historical"] == {
        "count": 1,
        "codes": {"task_historical_warning": 1},
    }
    assert payload["full_validation"]["finding_count"] == 6


def test_validate_target_keeps_global_unknown_and_human_findings(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _initialized_target(tmp_path, capsys)
    full = _mixed_validation_result()
    monkeypatch.setattr("pcl.control_handlers.validate_project", lambda *args, **kwargs: full)

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "validate",
                "--target",
                "T-0001",
                "--summary",
                "--json",
            ]
        )
        == 1
    )
    payload = _json_output(capsys)

    messages = [finding["message"] for finding in payload["findings"]]
    assert messages == [
        "Current target warning",
        "Unknown warning must remain visible",
        "Human gate must remain visible",
        "Global integrity error",
    ]
    assert "Unrelated warning" not in payload["warnings"]
    assert payload["validation_projection"]["target"] == {
        "target_id": "T-0001",
        "target_type": "task",
    }
    assert payload["validation_projection"]["omitted"]["count"] == 2
    assert payload["ok"] is False


def test_validate_target_keeps_real_global_audit_integrity_error(
    tmp_path: Path,
    capsys,
) -> None:
    _initialized_target(tmp_path, capsys)
    (tmp_path / ".project-loop" / "events.jsonl").write_text("", encoding="utf-8")

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "validate",
                "--strict",
                "--target",
                "T-0001",
                "--summary",
                "--json",
            ]
        )
        == 1
    )
    payload = _json_output(capsys)

    assert any(
        finding["code"] == "audit_projection_event_missing"
        for finding in payload["findings"]
    )
    assert payload["ok"] is False
    assert payload["full_validation"]["error_count"] > 0


def test_validate_target_is_fail_closed_after_full_evaluation(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _initialized_target(tmp_path, capsys)
    calls: list[bool] = []

    def fake_validate(*args, **kwargs):
        calls.append(bool(kwargs.get("strict")))
        return ValidationResult()

    monkeypatch.setattr("pcl.control_handlers.validate_project", fake_validate)

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "validate",
                "--target",
                "T-9999",
                "--json",
            ]
        )
        == 2
    )
    payload = _json_output(capsys)

    assert calls == [False]
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"]["target"] == "T-9999"


def test_validate_projection_preserves_full_digest_and_totals(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _initialized_target(tmp_path, capsys)
    full = _mixed_validation_result()
    canonical = json.dumps(
        full.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    monkeypatch.setattr("pcl.control_handlers.validate_project", lambda *args, **kwargs: full)

    assert main(["--root", str(tmp_path), "validate", "--summary", "--json"]) == 1
    payload = _json_output(capsys)

    assert payload["full_validation"] == {
        "digest": f"sha256:{hashlib.sha256(canonical).hexdigest()}",
        "error_count": 1,
        "finding_count": 6,
        "finding_counts": {"active": 5, "historical": 1},
        "warning_count": 5,
    }


def test_validate_default_json_and_text_contract_remain_unchanged(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()
    expected = validate_project(resolve_paths(tmp_path)).to_dict()

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    assert _json_output(capsys) == expected
    assert main(["--root", str(tmp_path), "validate"]) == 0
    assert capsys.readouterr().out == "OK\n"
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True
