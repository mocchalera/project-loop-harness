from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pcl.cli import main
from pcl.commands import add_feature
from pcl.db import connect
from pcl.paths import resolve_paths


def _json_output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _event_snapshot(root: Path) -> tuple[int, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(MAX(sequence), 0) AS high_watermark FROM events"
        ).fetchone()
        return int(row["count"]), int(row["high_watermark"])
    finally:
        conn.close()


def _feature_event_count(root: Path, *, entity_id: str | None = None) -> int:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        if entity_id is None:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM events WHERE event_type = 'feature_added'"
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM events
                WHERE event_type = 'feature_added' AND entity_id = ?
                """,
                (entity_id,),
            ).fetchone()
        return int(row["count"])
    finally:
        conn.close()


def _set_auto_render(root: Path, enabled: bool) -> None:
    config = root / "pcl.yaml"
    text = config.read_text(encoding="utf-8")
    text = text.replace(
        "  auto_render: true",
        f"  auto_render: {'true' if enabled else 'false'}",
    )
    config.write_text(text, encoding="utf-8")


def _set_auto_render_value(root: Path, value: str) -> None:
    config = root / "pcl.yaml"
    text = config.read_text(encoding="utf-8")
    text = text.replace("  auto_render: true", f"  auto_render: {value}")
    config.write_text(text, encoding="utf-8")


def _initialized_direct_target(root: Path, capsys, *, auto_render: bool) -> None:
    assert main(["init", "--target", str(root)]) == 0
    _set_auto_render(root, auto_render)
    assert main(["--root", str(root), "start", "Direct mutation target", "--json"]) == 0
    assert main(["--root", str(root), "render", "--json"]) == 0
    capsys.readouterr()


def _add_linked_feature(root: Path) -> list[str]:
    return [
        "--root",
        str(root),
        "feature",
        "add",
        "--name",
        "Mutation tail",
        "--surface",
        "cli:mutation-tail",
        "--task",
        "T-0001",
        "--json",
    ]


def test_feature_add_returns_exact_target_next_action_and_render_receipt(
    tmp_path: Path,
    capsys,
) -> None:
    _initialized_direct_target(tmp_path, capsys, auto_render=True)

    assert main(_add_linked_feature(tmp_path)) == 0
    payload = _json_output(capsys)
    tail = payload["mutation_tail"]

    assert tail["contract_version"] == "mutation-tail/v1"
    assert tail["mutation_committed"] is True
    assert tail["safe_to_retry_original"] is False
    assert tail["target"] == {"type": "task", "id": "T-0001"}
    assert tail["next_action"]["target_binding"] == {
        "target_type": "task",
        "target_id": "T-0001",
        "source": "explicit",
    }
    assert tail["render"]["contract_version"] == "render-receipt/v1"
    assert tail["render"]["status"] == "rendered"
    assert tail["render"]["state_high_watermark"]["sequence"] > 0
    assert len(tail["render"]["artifact"]["sha256"]) == 64
    assert len(tail["render"]["data_artifact"]["sha256"]) == 64
    dashboard = json.loads(
        (tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(
            encoding="utf-8"
        )
    )
    assert dashboard["features"][0]["id"] == "F-0001"


def test_auto_render_false_does_not_write_dashboard(
    tmp_path: Path,
    capsys,
) -> None:
    _initialized_direct_target(tmp_path, capsys, auto_render=False)
    html = tmp_path / ".project-loop" / "dashboard" / "dashboard.html"
    data = tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json"
    before = (_sha256(html), _sha256(data))

    assert main(_add_linked_feature(tmp_path)) == 0
    payload = _json_output(capsys)

    assert payload["mutation_tail"]["render"]["status"] == "disabled"
    assert (_sha256(html), _sha256(data)) == before


def test_idempotent_task_status_adds_no_event_or_render(
    tmp_path: Path,
    capsys,
) -> None:
    _initialized_direct_target(tmp_path, capsys, auto_render=True)
    html = tmp_path / ".project-loop" / "dashboard" / "dashboard.html"
    data = tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json"
    before_events = _event_snapshot(tmp_path)
    before_artifacts = (_sha256(html), _sha256(data))

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "task",
                "status",
                "T-0001",
                "in_progress",
                "--reason",
                "Exact retry",
                "--json",
            ]
        )
        == 0
    )
    payload = _json_output(capsys)

    assert payload["changed"] is False
    assert payload["mutation_tail"]["mutation_committed"] is False
    assert payload["mutation_tail"]["render"]["status"] == "not_changed"
    assert _event_snapshot(tmp_path) == before_events
    assert (_sha256(html), _sha256(data)) == before_artifacts


def test_render_failure_reports_committed_state_and_read_only_recovery(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _initialized_direct_target(tmp_path, capsys, auto_render=True)
    import pcl.mutation_tail as mutation_tail

    def fail_render(*args, **kwargs):
        raise OSError("injected render failure")

    monkeypatch.setattr(mutation_tail, "render_dashboard", fail_render)

    assert main(_add_linked_feature(tmp_path)) == 0
    payload = _json_output(capsys)
    tail = payload["mutation_tail"]

    assert tail["mutation_committed"] is True
    assert tail["safe_to_retry_original"] is False
    assert tail["render"]["status"] == "failed"
    assert tail["render"]["error"] == "injected render failure"
    assert tail["render"]["recovery"] == {
        "authority": "read_only",
        "command": "pcl validate --target T-0001 --summary --json",
        "retry_original": False,
    }
    assert _feature_event_count(tmp_path) == 1
    assert main(["--root", str(tmp_path), "feature", "read", "F-0001", "--json"]) == 0
    assert _json_output(capsys)["feature"]["id"] == "F-0001"


def test_render_receipt_retries_once_when_state_changes_during_render(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _initialized_direct_target(tmp_path, capsys, auto_render=True)
    import pcl.mutation_tail as mutation_tail

    original_render = mutation_tail.render_dashboard
    render_calls = 0

    def render_with_one_concurrent_mutation(paths):
        nonlocal render_calls
        render_calls += 1
        original_render(paths)
        if render_calls == 1:
            add_feature(
                paths,
                name="Concurrent feature",
                surface="test:concurrent",
            )

    monkeypatch.setattr(
        mutation_tail,
        "render_dashboard",
        render_with_one_concurrent_mutation,
    )

    assert main(_add_linked_feature(tmp_path)) == 0
    payload = _json_output(capsys)
    receipt = payload["mutation_tail"]["render"]
    dashboard_data = tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json"
    dashboard = json.loads(dashboard_data.read_text(encoding="utf-8"))

    assert render_calls == 2
    assert receipt["status"] == "rendered"
    assert receipt["consistency"]["attempts"] == 2
    assert receipt["consistency"]["status"] == "stable"
    assert receipt["consistency"]["before"] == receipt["consistency"]["after"]
    assert receipt["consistency"]["after"] == receipt["state_high_watermark"]
    assert receipt["state_high_watermark"]["sequence"] == _event_snapshot(tmp_path)[1]
    assert receipt["data_artifact"]["sha256"] == _sha256(dashboard_data)
    assert [feature["id"] for feature in dashboard["features"][:2]] == [
        "F-0001",
        "F-0002",
    ]


def test_render_receipt_captures_artifacts_before_final_watermark_check(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _initialized_direct_target(tmp_path, capsys, auto_render=True)
    import pcl.mutation_tail as mutation_tail

    original_artifact_receipt = mutation_tail._artifact_receipt
    original_render = mutation_tail.render_dashboard
    injected = False

    def artifact_receipt_with_one_concurrent_render(path):
        nonlocal injected
        if not injected:
            injected = True
            paths = resolve_paths(tmp_path)
            add_feature(
                paths,
                name="Receipt-window concurrent feature",
                surface="test:receipt-window",
            )
            original_render(paths)
        return original_artifact_receipt(path)

    monkeypatch.setattr(
        mutation_tail,
        "_artifact_receipt",
        artifact_receipt_with_one_concurrent_render,
    )

    assert main(_add_linked_feature(tmp_path)) == 0
    payload = _json_output(capsys)
    receipt = payload["mutation_tail"]["render"]
    html = tmp_path / ".project-loop" / "dashboard" / "dashboard.html"
    data = tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json"
    dashboard = json.loads(data.read_text(encoding="utf-8"))

    assert injected is True
    assert receipt["status"] == "rendered"
    assert receipt["consistency"]["status"] == "stable"
    assert receipt["consistency"]["attempts"] == 2
    assert receipt["consistency"]["before"] == receipt["consistency"]["after"]
    assert receipt["state_high_watermark"] == receipt["consistency"]["after"]
    assert receipt["state_high_watermark"]["sequence"] == _event_snapshot(tmp_path)[1]
    assert receipt["artifact"]["sha256"] == _sha256(html)
    assert receipt["data_artifact"]["sha256"] == _sha256(data)
    assert [feature["id"] for feature in dashboard["features"][:2]] == [
        "F-0001",
        "F-0002",
    ]
    assert _feature_event_count(tmp_path, entity_id="F-0001") == 1
    assert _feature_event_count(tmp_path, entity_id="F-0002") == 1


def test_render_receipt_fails_closed_after_bounded_state_changes(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _initialized_direct_target(tmp_path, capsys, auto_render=True)
    import pcl.mutation_tail as mutation_tail

    original_render = mutation_tail.render_dashboard
    render_calls = 0

    def render_with_repeated_mutation(paths):
        nonlocal render_calls
        render_calls += 1
        original_render(paths)
        add_feature(
            paths,
            name=f"Concurrent feature {render_calls}",
            surface="test:concurrent",
        )

    monkeypatch.setattr(
        mutation_tail,
        "render_dashboard",
        render_with_repeated_mutation,
    )

    assert main(_add_linked_feature(tmp_path)) == 0
    payload = _json_output(capsys)
    receipt = payload["mutation_tail"]["render"]

    assert render_calls == 2
    assert payload["post_commit_status"] == "partial"
    assert payload["mutation_committed"] is True
    assert payload["safe_to_retry_original"] is False
    assert receipt["status"] == "failed"
    assert receipt["artifact"] is None
    assert receipt["data_artifact"] is None
    assert receipt["consistency"]["status"] == "unstable"
    assert receipt["consistency"]["attempts"] == 2
    assert payload["post_commit_diagnostics"][0]["code"] == "render_state_changed"
    assert payload["recovery"]["retry_original"] is False


def test_invalid_auto_render_is_top_level_partial_and_recovery_diagnoses_config(
    tmp_path: Path,
    capsys,
) -> None:
    json_root = tmp_path / "json"
    _initialized_direct_target(json_root, capsys, auto_render=True)
    _set_auto_render_value(json_root, "sometimes")

    assert main(_add_linked_feature(json_root)) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["ok"] is True
    assert payload["mutation_committed"] is True
    assert payload["safe_to_retry_original"] is False
    assert payload["post_commit_status"] == "partial"
    assert payload["post_commit_diagnostics"] == [
        {
            "code": "config_dashboard_auto_render_invalid",
            "message": "dashboard.auto_render must be true or false.",
            "phase": "dashboard_config",
        }
    ]
    assert payload["recovery"] == {
        "authority": "read_only",
        "command": "pcl validate --target T-0001 --summary --json",
        "retry_original": False,
    }
    assert "post_commit_status=partial" in captured.err
    assert "Do not retry the original mutation" in captured.err

    assert (
        main(
            [
                "--root",
                str(json_root),
                "validate",
                "--target",
                "T-0001",
                "--summary",
                "--json",
            ]
        )
        == 1
    )
    recovery = _json_output(capsys)
    config_finding = next(
        finding
        for finding in recovery["findings"]
        if finding["code"] == "config_dashboard_auto_render_invalid"
    )
    assert config_finding["entity"] == {
        "type": "project",
        "id": str(json_root),
    }
    assert config_finding["requires_human"] is True

    text_root = tmp_path / "text"
    _initialized_direct_target(text_root, capsys, auto_render=True)
    _set_auto_render_value(text_root, "sometimes")

    text_command = _add_linked_feature(text_root)
    text_command.remove("--json")
    assert main(text_command) == 0
    captured = capsys.readouterr()
    assert captured.out == "F-0001\n"
    assert "post_commit_status=partial" in captured.err
    assert "config_dashboard_auto_render_invalid" in captured.err
    assert "Do not retry the original mutation" in captured.err
