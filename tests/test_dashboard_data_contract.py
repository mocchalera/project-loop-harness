from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


TOP_LEVEL_KEYS = {
    "contract_version",
    "generated_at",
    "source_db",
    "validation",
    "next_action",
    "human_decisions",
    "risk_summary",
    "counts",
    "current_goal",
    "active_workflow",
    "active_agent_jobs",
    "features",
    "user_stories",
    "test_cases",
    "defects",
    "tasks",
    "goals",
    "workflow_runs",
    "workflow_proposals",
    "agent_jobs",
    "verifications",
    "decisions",
    "escalations",
    "evidence",
    "recent_events",
    "reports",
}
COUNT_KEYS = {
    "features",
    "user_stories",
    "test_cases",
    "open_defects",
    "goals",
    "open_decisions",
    "workflow_runs",
    "queued_jobs",
    "open_escalations",
    "workflow_proposals",
}
NEXT_ACTION_KEYS = {
    "type",
    "command",
    "reason",
    "priority",
    "blocking",
    "requires_human",
    "safe_to_run",
    "run_policy",
    "human_guidance",
    "expected_after",
    "target",
}
RISK_SUMMARY_KEYS = {"blocking", "highest_severity", "items"}
RISK_ITEM_KEYS = {
    "type",
    "severity",
    "blocking",
    "requires_human",
    "summary",
    "command",
    "target",
    "count",
}
RISK_TARGET_KEYS = {"type", "id"}
HUMAN_DECISIONS_KEYS = {"count", "items"}
VALIDATION_KEYS = {"ok", "errors", "warnings"}
CURRENT_GOAL_KEYS = {"id", "title", "status", "completion_json", "budget_json", "updated_at"}
ACTIVE_WORKFLOW_KEYS = {
    "id",
    "workflow_id",
    "goal_id",
    "status",
    "iteration",
    "started_at",
    "summary",
    "budget",
}
AGENT_JOB_KEYS = {
    "id",
    "workflow_run_id",
    "role",
    "status",
    "prompt_path",
    "output_path",
    "summary",
    "evidence_ids",
    "evidence",
    "latest_evidence_id",
    "latest_evidence_path",
}
EVIDENCE_KEYS = {"id", "type", "path", "command", "summary", "created_at"}
EVIDENCE_NAVIGATION_KEYS = {
    "related_agent_job_ids",
    "related_workflow_run_ids",
    "related_report_paths",
}
EVENT_KEYS = {"id", "event_type", "entity_type", "entity_id", "created_at"}
REPORT_KEYS = {
    "name",
    "path",
    "related_evidence_ids",
    "related_agent_job_ids",
    "related_workflow_run_ids",
}
WORKFLOW_PROPOSAL_KEYS = {
    "id",
    "workflow_id",
    "path",
    "workflow_path",
    "status",
    "summary",
    "review_summary",
    "created_at",
    "reviewed_at",
    "content_sha256",
    "parse_error",
    "data",
}
USER_STORY_KEYS = {
    "id",
    "feature_id",
    "actor",
    "goal",
    "benefit",
    "expected_behavior",
    "status",
    "updated_at",
}
TEST_CASE_KEYS = {
    "id",
    "feature_id",
    "story_id",
    "type",
    "scenario",
    "expected",
    "status",
    "last_run_id",
    "evidence_id",
    "updated_at",
}
VERIFICATION_KEYS = {
    "id",
    "workflow_run_id",
    "target_job_id",
    "target_job_evidence_ids",
    "workflow_report_path",
    "verifier_role",
    "result",
    "reasons_json",
    "created_at",
}
TASK_KEYS = {
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


def test_dashboard_data_contract_shape_for_active_loop(tmp_path: Path) -> None:
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
        "- Captured one agent result.\n\n"
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
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--target-job",
        "J-0001",
        "--result",
        "approved",
        "--reason",
        "Reviewed mapper output",
    ]) == 0
    assert main(["--root", str(tmp_path), "report", "run", "WR-0001"]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    data = _dashboard_data(tmp_path)
    html = (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").read_text(
        encoding="utf-8"
    )

    assert set(data) == TOP_LEVEL_KEYS
    assert data["contract_version"] == "dashboard-data/v1"
    assert set(data["counts"]) == COUNT_KEYS
    assert data["counts"]["workflow_proposals"] == 0
    assert data["counts"]["user_stories"] == 0
    assert data["counts"]["test_cases"] == 0
    assert set(data["next_action"]) == NEXT_ACTION_KEYS
    assert set(data["human_decisions"]) == HUMAN_DECISIONS_KEYS
    assert data["human_decisions"] == {"count": 0, "items": []}
    assert set(data["risk_summary"]) == RISK_SUMMARY_KEYS
    assert data["risk_summary"] == {
        "blocking": False,
        "highest_severity": "none",
        "items": [],
    }
    assert set(data["validation"]) == VALIDATION_KEYS
    assert data["validation"] == {"errors": [], "ok": True, "warnings": []}
    assert CURRENT_GOAL_KEYS <= set(data["current_goal"])
    assert ACTIVE_WORKFLOW_KEYS <= set(data["active_workflow"])
    assert AGENT_JOB_KEYS <= set(data["active_agent_jobs"][0])
    assert AGENT_JOB_KEYS <= set(data["agent_jobs"][0])
    assert EVIDENCE_KEYS | EVIDENCE_NAVIGATION_KEYS <= set(data["evidence"][0])
    assert EVENT_KEYS <= set(data["recent_events"][0])
    assert REPORT_KEYS <= set(data["reports"][0])
    assert data["workflow_proposals"] == []
    assert data["user_stories"] == []
    assert data["test_cases"] == []
    assert data["tasks"] == []
    assert VERIFICATION_KEYS <= set(data["verifications"][0])
    assert data["agent_jobs"][0]["evidence_ids"] == ["E-0001"]
    assert data["agent_jobs"][0]["latest_evidence_id"] == "E-0001"
    assert data["evidence"][0]["related_agent_job_ids"] == ["J-0001"]
    assert data["evidence"][0]["related_workflow_run_ids"] == ["WR-0001"]
    assert data["evidence"][0]["related_report_paths"] == [".project-loop/reports/run-WR-0001.md"]
    assert data["verifications"][0]["target_job_evidence_ids"] == ["E-0001"]
    assert data["verifications"][0]["workflow_report_path"] == ".project-loop/reports/run-WR-0001.md"
    assert data["reports"][0]["path"].startswith(".project-loop/reports/")
    assert data["reports"][0]["related_evidence_ids"] == ["E-0001"]
    assert data["reports"][0]["related_agent_job_ids"] == ["J-0001", "J-0002", "J-0003"]
    assert data["reports"][0]["related_workflow_run_ids"] == ["WR-0001"]
    assert 'id="row-E-0001"' in html
    assert html.count('id="row-J-0001"') == 1
    assert '<a href="#row-E-0001">E-0001</a>' in html
    assert '<a href="#row-J-0001">J-0001</a>' in html
    assert '<a href=".project-loop/reports/run-WR-0001.md">.project-loop/reports/run-WR-0001.md</a>' in html


def test_dashboard_data_contract_is_documented() -> None:
    contract = Path("docs/dashboard-data-contract.md").read_text(encoding="utf-8")

    for required in [
        "dashboard-data/v1",
        "contract_version",
        "next_action",
        "risk_summary",
        "human_decisions",
        "Needs Your Decision",
        "Risk & Blockers",
        "latest_evidence_id",
        "related_report_paths",
        "target_job_evidence_ids",
        "row-<id>",
        "recent_events",
        "reports",
        "workflow_proposals",
        "user_stories",
        "test_cases",
        "tasks",
        "dependency_ids",
        "dependent_ids",
        "must not be edited directly",
    ]:
        assert required in contract


def test_dashboard_render_does_not_require_strict_validation(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / ".project-loop" / "events.jsonl").unlink()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    assert main(["--root", str(tmp_path), "render", "--json"]) == 0

    data = _dashboard_data(tmp_path)
    assert data["contract_version"] == "dashboard-data/v1"
    assert data["validation"]["ok"] is True
    assert any("Missing events.jsonl" in warning for warning in data["validation"]["warnings"])
    assert set(data["risk_summary"]) == RISK_SUMMARY_KEYS
    assert set(data["risk_summary"]["items"][0]) == RISK_ITEM_KEYS
    assert set(data["risk_summary"]["items"][0]["target"]) == RISK_TARGET_KEYS
    assert data["risk_summary"]["highest_severity"] == "low"
    assert data["risk_summary"]["items"][0]["type"] == "validation_warnings"


def _dashboard_data(root: Path) -> dict:
    return json.loads(
        (root / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(
            encoding="utf-8"
        )
    )
