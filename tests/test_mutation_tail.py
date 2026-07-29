from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


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


def _feature_event_count(root: Path) -> int:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM events WHERE event_type = 'feature_added'"
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
