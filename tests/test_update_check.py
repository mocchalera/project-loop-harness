from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from pcl import update_check
from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _fixed_now() -> datetime:
    return datetime(2026, 7, 2, 3, 0, 0, tzinfo=timezone.utc)


def test_update_check_reports_newer_version_without_upgrading(tmp_path: Path) -> None:
    result = update_check.check_for_update(
        current_version="0.1.5",
        cache_path=tmp_path / "cache.json",
        env={},
        fetcher=lambda _url, _timeout: {"info": {"version": "0.1.6"}},
        now=_fixed_now,
    )

    payload = result.to_dict()
    assert payload["ok"] is True
    assert payload["current_version"] == "0.1.5"
    assert payload["latest_version"] == "0.1.6"
    assert payload["update_available"] is True
    assert payload["install"]["command"]
    assert "upgrade" in payload["install"]["command"] or "install -e" in payload["install"]["command"]


def test_update_check_uses_cache_for_24_hours(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps({"checked_at": "2026-07-02T02:00:00Z", "latest_version": "0.1.6"}),
        encoding="utf-8",
    )

    def fail_fetcher(_url: str, _timeout: float) -> dict:
        raise AssertionError("fresh cache should avoid network fetch")

    result = update_check.check_for_update(
        current_version="0.1.5",
        cache_path=cache_path,
        env={},
        fetcher=fail_fetcher,
        now=_fixed_now,
    )

    assert result.ok is True
    assert result.cache_used is True
    assert result.latest_version == "0.1.6"
    assert result.update_available is True


def test_update_check_is_fail_open_on_network_errors(tmp_path: Path) -> None:
    def fail_fetcher(_url: str, _timeout: float) -> dict:
        raise OSError("network unavailable")

    result = update_check.check_for_update(
        current_version="0.1.5",
        cache_path=tmp_path / "cache.json",
        env={},
        fetcher=fail_fetcher,
        now=_fixed_now,
    )

    assert result.ok is False
    assert result.update_available is False
    assert result.error == "network unavailable"


def test_update_check_can_be_disabled(tmp_path: Path) -> None:
    result = update_check.check_for_update(
        current_version="0.1.5",
        cache_path=tmp_path / "cache.json",
        env={update_check.NO_VERSION_CHECK_ENV: "1"},
        fetcher=lambda _url, _timeout: {"info": {"version": "9.9.9"}},
        now=_fixed_now,
    )

    assert result.ok is True
    assert result.disabled is True
    assert result.latest_version is None
    assert result.update_available is False


def test_update_check_cli_json(monkeypatch, capsys) -> None:
    install = update_check.InstallContext(
        method="pipx",
        command="pipx upgrade project-loop-harness",
        reason="test install context",
    )
    result = update_check.UpdateCheckResult(
        ok=True,
        package="project-loop-harness",
        current_version="0.1.5",
        latest_version="0.1.6",
        update_available=True,
        source_url="https://pypi.org/pypi/project-loop-harness/json",
        checked_at="2026-07-02T03:00:00Z",
        install=install,
    )
    monkeypatch.setattr(update_check, "check_for_update", lambda **_kwargs: result)

    assert main(["update", "check", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["ok"] is True
    assert payload["latest_version"] == "0.1.6"
    assert payload["update_available"] is True
    assert payload["install"]["command"] == "pipx upgrade project-loop-harness"


def test_doctor_check_updates_is_advisory(monkeypatch, tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    install = update_check.InstallContext(
        method="pipx",
        command="pipx upgrade project-loop-harness",
        reason="test install context",
    )
    result = update_check.UpdateCheckResult(
        ok=True,
        package="project-loop-harness",
        current_version="0.1.5",
        latest_version="0.1.6",
        update_available=True,
        source_url="https://pypi.org/pypi/project-loop-harness/json",
        checked_at="2026-07-02T03:00:00Z",
        install=install,
    )
    monkeypatch.setattr(update_check, "check_for_update", lambda **_kwargs: result)

    assert main(["--root", str(tmp_path), "doctor", "--check-updates", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["ok"] is True
    assert payload["update"]["update_available"] is True
    assert any("pcl 0.1.6 is available" in warning for warning in payload["warnings"])


def test_doctor_update_network_failure_does_not_fail_health(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    install = update_check.InstallContext(
        method="pip",
        command="python -m pip install --upgrade project-loop-harness",
        reason="test install context",
    )
    result = update_check.UpdateCheckResult(
        ok=False,
        package="project-loop-harness",
        current_version="0.1.5",
        latest_version=None,
        update_available=False,
        source_url="https://pypi.org/pypi/project-loop-harness/json",
        checked_at="2026-07-02T03:00:00Z",
        install=install,
        error="network unavailable",
    )
    monkeypatch.setattr(update_check, "check_for_update", lambda **_kwargs: result)

    assert main(["--root", str(tmp_path), "doctor", "--check-updates", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["ok"] is True
    assert payload["update"]["ok"] is False
    assert "Could not check for pcl updates: network unavailable" in payload["warnings"]


def test_update_command_cli_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        update_check,
        "detect_install_context",
        lambda: update_check.InstallContext(
            method="pipx",
            command="pipx upgrade project-loop-harness",
            reason="test install context",
        ),
    )

    assert main(["update", "command", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload == {
        "install": {
            "command": "pipx upgrade project-loop-harness",
            "method": "pipx",
            "reason": "test install context",
        },
        "ok": True,
    }
