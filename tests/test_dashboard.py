from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


def _read_dashboard(root: Path) -> str:
    return (root / ".project-loop" / "dashboard" / "dashboard.html").read_text(encoding="utf-8")


def _read_dashboard_data(root: Path) -> dict:
    return json.loads(
        (root / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(
            encoding="utf-8"
        )
    )


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


COCKPIT_ITEM_KEYS = {
    "why_blocked",
    "options",
    "recommendation",
    "recommendation_reason",
    "related_evidence_paths",
    "receipt_paths",
}
COCKPIT_OPTION_KEYS = {"label", "command", "why_safe", "risk_if_run"}
COCKPIT_OPTION_LABELS = ["Approve", "Reject", "Hold", "Request more evidence"]


def _set_dashboard_locale(root: Path, locale: str) -> None:
    config_path = root / "pcl.yaml"
    text = config_path.read_text(encoding="utf-8")
    if "dashboard:\n  locale:" in text:
        text = text.replace(
            "dashboard:\n  locale:",
            f'dashboard:\n  locale: "{locale}"\n  previous_locale:',
            1,
        )
    elif "dashboard:\n  output:" in text:
        text = text.replace(
            "dashboard:\n  output:",
            f'dashboard:\n  locale: "{locale}"\n  output:',
            1,
        )
    else:
        text += f'\ndashboard:\n  locale: "{locale}"\n'
    config_path.write_text(text, encoding="utf-8")


def test_dashboard_renders_control_panels_and_workflow_state(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    html = _read_dashboard(tmp_path)
    assert "<!doctype html>" in html
    assert "Source DB:" in html
    assert "Next Human Action" in html
    assert "Risk &amp; Blockers" in html
    assert "Needs Your Decision" in html
    assert "No decisions are waiting on you." in html
    assert "Current Goal" in html
    assert "Active Workflow" in html
    assert "Budget Usage" in html
    assert "Active Agent Jobs" in html
    assert "Verification Results" in html
    assert "Escalation Queue" in html
    assert "Evidence Links" in html
    assert "Recent Events" in html
    assert "Validation OK" in html
    assert "WR-0001" in html
    assert "J-0001" in html
    assert ".project-loop/evidence/agent-runs/J-0001/prompt.md" in html
    assert "pcl jobs read J-0001" in html
    assert "http://" not in html
    assert "https://" not in html
    assert "<script" not in html

    data = _read_dashboard_data(tmp_path)
    assert data["source_db"] == str(tmp_path / ".project-loop" / "project.db")
    assert data["validation"] == {"errors": [], "ok": True, "warnings": [], "findings": []}
    assert data["active_workflow"]["id"] == "WR-0001"
    assert data["active_workflow"]["budget"]["max_iterations"] == 2
    assert data["active_agent_jobs"][0]["id"] == "J-0001"
    assert data["counts"]["queued_jobs"] == 3
    assert data["next_action"]["type"] == "continue_workflow"
    assert data["human_decisions"] == {"count": 0, "items": []}
    assert data["risk_summary"] == {
        "blocking": False,
        "highest_severity": "none",
        "items": [],
    }


def test_dashboard_surfaces_validation_warnings(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    skill_path = tmp_path / ".agents" / "skills" / "project-control-loop" / "SKILL.md"
    skill_path.unlink()

    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0

    html = _read_dashboard(tmp_path)
    data = _read_dashboard_data(tmp_path)
    assert "検証警告" in html
    assert "Missing project-control-loop Skill" in html
    assert data["risk_summary"]["highest_severity"] == "low"
    assert data["risk_summary"]["items"][0]["type"] == "validation_warnings"
    assert data["risk_summary"]["items"][0]["blocking"] is False
    summary_start = html.index('id="operator-summary"')
    summary_html = html[summary_start : html.index("</section>", summary_start)]
    assert "確認すべき注意点が 1 件あります（最大: 低）。" in summary_html


def test_dashboard_surfaces_open_human_queue_risks(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--severity",
        "critical",
        "--question",
        "Which path should ship?",
        "--recommendation",
        "Choose the reversible path",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Which path should ship?",
        "--recommendation",
        "Choose the reversible path",
    ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    html = _read_dashboard(tmp_path)
    data = _read_dashboard_data(tmp_path)
    items_by_type = {item["type"]: item for item in data["risk_summary"]["items"]}

    assert data["risk_summary"]["blocking"] is True
    assert data["risk_summary"]["highest_severity"] == "critical"
    assert items_by_type["open_escalation"]["requires_human"] is True
    assert items_by_type["open_escalation"]["target"] == {"type": "escalation", "id": "ESC-0001"}
    assert items_by_type["open_decision"]["requires_human"] is True
    assert items_by_type["open_decision"]["target"] == {"type": "decision", "id": "DEC-0001"}
    assert "Risk &amp; Blockers" in html
    assert "Needs Your Decision" in html
    assert "pcl decision open --escalation ESC-0001" in html
    assert "pcl decision resolve DEC-0001 --selected-option" in html
    assert "Open escalation ESC-0001" in html
    assert "Open decision DEC-0001" in html


def test_dashboard_human_decisions_contract_orders_and_links_items(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Human queue"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# Mapper result\n\n"
        "## Findings\n\n"
        "- Captured evidence for a human decision.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )
    assert main([
        "--root",
        str(tmp_path),
        "ingest-agent-run",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
    ]) == 0
    assert main(["--root", str(tmp_path), "report", "run", "WR-0001"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "needs_human",
        "--reason",
        "Product decision required",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--run",
        "WR-0001",
        "--severity",
        "low",
        "--question",
        "Can this wait?",
        "--recommendation",
        "Wait if low risk",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--run",
        "WR-0001",
        "--severity",
        "high",
        "--question",
        "What should ship?",
        "--recommendation",
        "Safest reversible path",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--escalation",
        "ESC-0002",
        "--question",
        "Which path?",
        "--recommendation",
        "Ship locally first",
    ]) == 0

    assert main(["--root", str(tmp_path), "render"]) == 0

    data = _read_dashboard_data(tmp_path)
    human_decisions = data["human_decisions"]
    items = human_decisions["items"]
    items_by_kind = {item["kind"]: item for item in items}

    assert human_decisions["count"] == 5
    for item in items:
        assert COCKPIT_ITEM_KEYS <= set(item)
        assert [option["label"] for option in item["options"]] == COCKPIT_OPTION_LABELS
        assert all(set(option) == COCKPIT_OPTION_KEYS for option in item["options"])
        assert item["receipt_paths"] == []
        assert item["why_blocked"]
        assert item["recommendation_reason"]
    assert [(item["kind"], item.get("id")) for item in items[:2]] == [
        ("escalation", "ESC-0002"),
        ("escalation", "ESC-0001"),
    ]
    assert items[0]["severity"] == "high"
    assert items[1]["severity"] == "low"
    assert items_by_kind["decision"]["linked_escalation_ids"] == ["ESC-0002"]
    assert items_by_kind["decision"]["related_evidence_paths"] == [
        ".project-loop/evidence/agent-runs/J-0001/output.md",
        ".project-loop/reports/run-WR-0001.md",
    ]
    assert items_by_kind["decision"]["resolve_command"] == (
        "pcl decision resolve DEC-0001 --selected-option '<option>' --reason '<why>'"
    )
    assert items_by_kind["decision"]["options"][1]["command"] == (
        "pcl decision resolve DEC-0001 --selected-option 'Reject recommended path' "
        "--reason '<why this should not proceed>'"
    )
    assert items[0]["linked_decision_ids"] == ["DEC-0001"]
    assert items[0]["resolve_command"] == (
        "pcl escalation resolve ESC-0002 --decision DEC-0001 --summary '<summary>'"
    )
    assert items_by_kind["verification"]["workflow_run_id"] == "WR-0001"
    assert items_by_kind["verification"]["reasons"] == ["Product decision required"]
    assert items_by_kind["verification"]["resolve_command"].startswith(
        "pcl escalation open --run WR-0001"
    )
    next_items = [item for item in items if item["kind"] == "next_action"]
    assert len(next_items) == 1
    assert COCKPIT_ITEM_KEYS <= set(next_items[0])
    assert next_items[0]["type"] == data["next_action"]["type"]


def test_dashboard_human_decisions_filters_inactive_needs_human_verifications(
    tmp_path: Path,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Human queue"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "needs_human",
        "--reason",
        "Product decision required",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "cancel",
        "WR-0001",
        "--summary",
        "Stop inactive run",
    ]) == 0

    assert main(["--root", str(tmp_path), "render"]) == 0

    data = _read_dashboard_data(tmp_path)
    assert [item for item in data["human_decisions"]["items"] if item["kind"] == "verification"] == []


def test_dashboard_locale_flag_renders_japanese_and_is_deterministic(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0

    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0
    first_html = _read_dashboard(tmp_path)
    first_data = _read_dashboard_data(tmp_path)

    assert '<html lang="ja">' in first_html
    assert "あなたの判断が必要です" in first_html
    assert "あなたの判断待ちはありません。" in first_html
    assert "Project Loop ダッシュボード" in first_html
    assert "役割" in first_html
    assert "プロンプトパス" in first_html

    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0
    assert _read_dashboard(tmp_path) == first_html
    assert _read_dashboard_data(tmp_path) == first_data


def test_dashboard_operator_summary_precedes_advanced_details_in_japanese(
    tmp_path: Path,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "create",
        "--title",
        "日本語の案内を確認する",
    ]) == 0

    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0

    dashboard = _read_dashboard(tmp_path)
    summary_start = dashboard.index('id="operator-summary"')
    advanced_start = dashboard.index('<details class="advanced-details"')
    summary_html = dashboard[summary_start : dashboard.index("</section>", summary_start)]

    assert summary_start < advanced_start
    assert all(label in summary_html for label in ["今", "完了", "次", "あなたの判断", "注意点"])
    assert "日本語の案内を確認する" in summary_html
    assert "次の処理は確認待ちです。" in summary_html
    assert "今、あなたの判断は必要ありません。" in summary_html
    assert "証跡付きの完了記録はまだありません。" in summary_html
    assert "詳細なProject Loop情報" in dashboard
    assert "<script" not in dashboard


def test_dashboard_operator_summary_localizes_human_gate_without_english_reason(
    tmp_path: Path,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "公開方法を選びますか？",
        "--recommendation",
        "可逆な方法を選ぶ",
    ]) == 0

    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0

    dashboard = _read_dashboard(tmp_path)
    summary_start = dashboard.index('id="operator-summary"')
    summary_html = dashboard[summary_start : dashboard.index("</section>", summary_start)]
    assert "あなたの判断を待って停止しています。" in summary_html
    assert "あなたの判断が 1 件必要です。" in summary_html
    assert "Open decision" not in summary_html
    assert "blocks safe continuation" not in summary_html


def test_dashboard_operator_summary_distinguishes_idle_manual_and_agent_safe(
    tmp_path: Path,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0

    idle_dashboard = _read_dashboard(tmp_path)
    idle_start = idle_dashboard.index('id="operator-summary"')
    idle_summary = idle_dashboard[idle_start : idle_dashboard.index("</section>", idle_start)]
    assert "次の作業は登録されていません。" in idle_summary

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "create",
        "--title",
        "<script>手動確認 & 続行</script>",
    ]) == 0
    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0

    manual_dashboard = _read_dashboard(tmp_path)
    manual_start = manual_dashboard.index('id="operator-summary"')
    manual_summary = manual_dashboard[
        manual_start : manual_dashboard.index("</section>", manual_start)
    ]
    assert "次の処理は確認待ちです。" in manual_summary
    assert "次の安全な処理はエージェントが続けます。" not in manual_summary
    assert "&lt;script&gt;手動確認 &amp; 続行&lt;/script&gt;" in manual_summary
    assert "<script>手動確認" not in manual_summary

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0

    safe_dashboard = _read_dashboard(tmp_path)
    safe_start = safe_dashboard.index('id="operator-summary"')
    safe_summary = safe_dashboard[safe_start : safe_dashboard.index("</section>", safe_start)]
    assert "次の安全な処理はエージェントが続けます。" in safe_summary


def test_dashboard_keeps_detailed_risks_decisions_and_commands_inside_disclosure(
    tmp_path: Path,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Which release path?",
        "--recommendation",
        "Use the reversible path",
    ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    dashboard = _read_dashboard(tmp_path)
    details_start = dashboard.index('<details class="advanced-details"')
    before_details = dashboard[:details_start]
    inside_details = dashboard[details_start:]

    assert 'id="operator-summary"' in before_details
    assert "Risk &amp; Blockers" not in before_details
    assert "Needs Your Decision" not in before_details
    assert "<code>" not in before_details
    assert "Risk &amp; Blockers" in inside_details
    assert "Needs Your Decision" in inside_details
    assert "pcl decision resolve DEC-0001 --selected-option" in inside_details


def test_dashboard_operator_done_only_reports_evidence_backed_transitions(
    tmp_path: Path,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "add",
        "--name",
        "Guided summary",
        "--surface",
        "dashboard",
        "--description",
        "Show an honest summary",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "story",
        "draft",
        "--feature",
        "F-0001",
        "--actor",
        "operator",
        "--goal",
        "understand progress",
        "--expected-behavior",
        "Show evidence-backed completion",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "story",
        "approve",
        "US-0001",
        "--summary",
        "Approved for acceptance testing",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "test",
        "plan",
        "--feature",
        "F-0001",
        "--story",
        "US-0001",
        "--type",
        "acceptance",
        "--scenario",
        "Render completion",
        "--expected",
        "Evidence is named",
    ]) == 0
    artifact = tmp_path / "acceptance.txt"
    artifact.write_text("acceptance passed\n", encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "acceptance.txt",
        "--summary",
        "Acceptance output",
        "--command",
        "pytest",
        "--copy",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "test",
        "pass",
        "TC-0001",
        "--summary",
        "Acceptance passed",
        "--evidence-id",
        "E-0001",
    ]) == 0

    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0

    dashboard = _read_dashboard(tmp_path)
    summary_start = dashboard.index('id="operator-summary"')
    summary_html = dashboard[summary_start : dashboard.index("</section>", summary_start)]
    assert "TC-0001" in summary_html
    assert "E-0001" in summary_html
    assert "証跡付きで完了記録済み" in summary_html
    assert "successfully" not in summary_html


def test_dashboard_operator_done_reconciles_current_state_without_event_window_loss(
    tmp_path: Path,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root", str(tmp_path), "feature", "add", "--name", "Current Done",
        "--surface", "dashboard",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "story", "draft", "--feature", "F-0001",
        "--actor", "operator", "--goal", "trust Done",
        "--expected-behavior", "Only current terminal states appear",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "story", "approve", "US-0001",
        "--summary", "Approved current-state semantics",
    ]) == 0
    for scenario in ["remains passing", "is later superseded"]:
        assert main([
            "--root", str(tmp_path), "test", "plan", "--feature", "F-0001",
            "--story", "US-0001", "--type", "acceptance", "--scenario", scenario,
            "--expected", "Done follows current state",
        ]) == 0

    artifact = tmp_path / "acceptance.txt"
    artifact.write_text("acceptance passed\n", encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "evidence", "add", "--file", "acceptance.txt",
        "--summary", "Acceptance output", "--command", "pytest", "--copy",
    ]) == 0
    for test_case_id in ["TC-0001", "TC-0002"]:
        assert main([
            "--root", str(tmp_path), "test", "pass", test_case_id,
            "--summary", "Acceptance passed", "--evidence-id", "E-0001",
        ]) == 0
    assert main([
        "--root", str(tmp_path), "feature", "status", "F-0001", "--status", "done",
        "--summary", "Feature completed", "--evidence-id", "E-0001",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "feature", "status", "F-0001", "--status", "needs_fix",
        "--summary", "Feature reopened after review", "--evidence-id", "E-0001",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "test", "fail", "TC-0002",
        "--summary", "Regression found", "--evidence-id", "E-0001",
    ]) == 0

    assert main([
        "--root", str(tmp_path), "feature", "add", "--name", "Event Noise",
        "--surface", "internal",
    ]) == 0
    for index in range(52):
        status = "specified" if index % 2 == 0 else "needs_test"
        assert main([
            "--root", str(tmp_path), "feature", "status", "F-0002", "--status", status,
            "--summary", f"Noise transition {index}", "--evidence-id", "E-0001",
        ]) == 0

    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0
    dashboard = _read_dashboard(tmp_path)
    summary_start = dashboard.index('id="operator-summary"')
    summary_html = dashboard[summary_start : dashboard.index("</section>", summary_start)]

    assert "TC-0001" in summary_html
    assert "TC-0002" not in summary_html
    assert "F-0001" not in summary_html


def test_dashboard_operator_done_covers_goal_verification_and_excludes_tasks(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001",
    ]) == 0
    output_path = (
        tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    )
    output_path.write_text(
        "# Mapper result\n\n## Findings\n\n- Mapped.\n\n## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )
    assert main([
        "--root", str(tmp_path), "jobs", "complete", "J-0001", "--summary", "Mapped",
        "--output", ".project-loop/evidence/agent-runs/J-0001/output.md", "--json",
    ]) == 0
    capsys.readouterr()
    for job_id in ["J-0002", "J-0003"]:
        assert main([
            "--root", str(tmp_path), "jobs", "complete", job_id,
            "--summary", "Completed review job", "--json",
        ]) == 0
        capsys.readouterr()
    assert main([
        "--root", str(tmp_path), "verification", "record", "--run", "WR-0001",
        "--result", "approved", "--reason", "Reviewed evidence", "--json",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(tmp_path), "loop", "complete", "WR-0001",
        "--summary", "Coverage complete", "--json",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(tmp_path), "goal", "close", "G-0001", "--summary", "Goal done",
        "--verification", "V-0001", "--json",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(tmp_path), "task", "create", "--title", "Reason-only task",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "task", "status", "T-0001", "done",
        "--reason", "No evidence attached to this task transition",
    ]) == 0

    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0
    dashboard = _read_dashboard(tmp_path)
    summary_start = dashboard.index('id="operator-summary"')
    summary_html = dashboard[summary_start : dashboard.index("</section>", summary_start)]

    assert "ゴール G-0001" in summary_html
    assert "検証 V-0001" in summary_html
    assert "T-0001" not in summary_html


def test_dashboard_human_decision_cockpit_renders_japanese_chrome(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Which release path?",
        "--recommendation",
        "Use the reversible path",
    ]) == 0

    assert main(["--root", str(tmp_path), "render", "--locale", "ja"]) == 0

    html = _read_dashboard(tmp_path)
    data = _read_dashboard_data(tmp_path)
    decision = data["human_decisions"]["items"][0]

    assert '<html lang="ja">' in html
    assert "あなたの判断が必要です" in html
    assert "停止理由" in html
    assert "推奨理由" in html
    assert "選択肢" in html
    assert "安全な理由" in html
    assert "実行時のリスク" in html
    assert "Approve" in html
    assert "Reject" in html
    assert "Hold" in html
    assert "Request more evidence" in html
    assert [option["label"] for option in decision["options"]] == COCKPIT_OPTION_LABELS


def test_dashboard_locale_precedence_and_invalid_locale(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0

    assert main(["--root", str(tmp_path), "render"]) == 0
    assert '<html lang="en">' in _read_dashboard(tmp_path)

    _set_dashboard_locale(tmp_path, "ja")
    assert main(["--root", str(tmp_path), "render"]) == 0
    assert '<html lang="ja">' in _read_dashboard(tmp_path)

    assert main(["--root", str(tmp_path), "render", "--locale", "en"]) == 0
    assert '<html lang="en">' in _read_dashboard(tmp_path)

    capsys.readouterr()
    assert main(["--root", str(tmp_path), "render", "--locale", "fr", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Supported locales: en, ja" in payload["error"]["message"]


def test_dashboard_risk_summary_includes_open_items_outside_table_limit(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Old open decision?",
        "--recommendation",
        "Keep tracking it",
    ]) == 0
    for index in range(2, 22):
        decision_id = f"DEC-{index:04d}"
        assert main([
            "--root",
            str(tmp_path),
            "decision",
            "open",
            "--question",
            f"Resolved filler decision {index}?",
            "--recommendation",
            "Resolve it",
        ]) == 0
        assert main([
            "--root",
            str(tmp_path),
            "decision",
            "resolve",
            decision_id,
            "--selected-option",
            "Resolved",
            "--reason",
            "Filler row",
        ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    data = _read_dashboard_data(tmp_path)
    open_decision_items = [
        item for item in data["risk_summary"]["items"] if item["type"] == "open_decision"
    ]

    assert data["counts"]["open_decisions"] == 1
    assert all(decision["id"] != "DEC-0001" for decision in data["decisions"])
    assert open_decision_items == [
        {
            "type": "open_decision",
            "severity": "high",
            "blocking": True,
            "requires_human": True,
            "summary": "Open decision DEC-0001: Old open decision?",
            "command": "pcl decision resolve DEC-0001 --selected-option 'Record the choice' --reason 'Record the reason'",
            "target": {"type": "decision", "id": "DEC-0001"},
            "count": 1,
        }
    ]


def test_dashboard_surfaces_failed_run_and_job_risks(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "fail",
        "J-0001",
        "--summary",
        "mapper failed",
    ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    data = _read_dashboard_data(tmp_path)
    items_by_type = {item["type"]: item for item in data["risk_summary"]["items"]}

    assert data["risk_summary"]["highest_severity"] == "high"
    assert items_by_type["failed_workflow_run"]["target"] == {"type": "workflow_run", "id": "WR-0001"}
    assert items_by_type["failed_agent_job"]["target"] == {"type": "agent_job", "id": "J-0001"}
    assert items_by_type["failed_agent_job"]["command"] == "pcl jobs read J-0001"


def test_dashboard_renders_task_backlog_data_and_table(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Backlog"]) == 0
    task_specs = [
        ("Todo task", "5", None),
        ("In progress task", "99", "in_progress"),
        ("Ready task", "1", "ready"),
        ("Blocked task", "1", "blocked"),
        ("Done dependency", "1", "done"),
        ("Waived task", "1", "waived"),
        ("Cancelled task", "1", "cancelled"),
    ]
    for index, (title, priority, status) in enumerate(task_specs, start=1):
        assert main([
            "--root",
            str(tmp_path),
            "task",
            "create",
            "--title",
            title,
            "--priority",
            priority,
            "--goal",
            "G-0001",
        ]) == 0
        if status is not None:
            task_id = f"T-{index:04d}"
            assert main([
                "--root",
                str(tmp_path),
                "task",
                "status",
                task_id,
                status,
                "--reason",
                f"Set {status}",
            ]) == 0
    assert main(["--root", str(tmp_path), "task", "depend", "T-0001", "--on", "T-0005"]) == 0

    assert main(["--root", str(tmp_path), "render"]) == 0

    data = _read_dashboard_data(tmp_path)
    html = _read_dashboard(tmp_path)
    assert [task["id"] for task in data["tasks"]] == [
        "T-0002",
        "T-0003",
        "T-0001",
        "T-0004",
        "T-0005",
        "T-0006",
        "T-0007",
    ]
    assert set(data["tasks"][0]) == {
        "id",
        "title",
        "status",
        "priority",
        "owner",
        "risk",
        "effort",
        "related_goal_id",
        "related_feature_id",
        "related_defect_id",
        "dependency_ids",
        "dependent_ids",
        "created_at",
        "updated_at",
    }
    tasks_by_id = {task["id"]: task for task in data["tasks"]}
    assert tasks_by_id["T-0001"]["dependency_ids"] == ["T-0005"]
    assert tasks_by_id["T-0005"]["dependent_ids"] == ["T-0001"]
    assert "Task Backlog" in html
    assert "In progress task" in html
    assert '<a href="#row-T-0005">T-0005</a>' in html


def test_dashboard_all_jobs_preserves_output_path_after_run_is_inactive(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# Mapper result\n\n"
        "## Findings\n\n"
        "- Captured output before run cancellation.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )
    assert main([
        "--root",
        str(tmp_path),
        "ingest-agent-run",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "cancel",
        "WR-0001",
        "--summary",
        "cancel remaining jobs",
    ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    data = _read_dashboard_data(tmp_path)
    jobs_by_id = {job["id"]: job for job in data["agent_jobs"]}
    assert data["active_agent_jobs"] == []
    assert jobs_by_id["J-0001"]["output_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"
    assert jobs_by_id["J-0001"]["latest_evidence_id"] == "E-0001"


def test_dashboard_data_is_deterministic_for_unchanged_state(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0
    first_html = _read_dashboard(tmp_path)
    first_data = _read_dashboard_data(tmp_path)

    assert main(["--root", str(tmp_path), "render"]) == 0
    assert _read_dashboard(tmp_path) == first_html
    assert _read_dashboard_data(tmp_path) == first_data
