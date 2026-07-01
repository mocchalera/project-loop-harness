from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from pcl.cli import main
from pcl.db import connect
from pcl.paths import resolve_paths
from pcl import workflow_proposals


VALID_PROPOSAL = """\
id: dynamic_review
name: "Dynamic Review"
type: closed_loop
version: "0.1.0"
goal:
  description: Review a proposed workflow safely.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review workflow risk.
steps:
  - id: review
    agent: reviewer
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""


def _proposal_with_id(workflow_id: str) -> str:
    return VALID_PROPOSAL.replace("dynamic_review", workflow_id).replace(
        '"Dynamic Review"',
        f'"{workflow_id}"',
    )


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_workflow_proposal_create_list_read_validate_and_dashboard(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    source = tmp_path / "proposal.yaml"
    source.write_text(VALID_PROPOSAL, encoding="utf-8")
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "propose",
        "--file",
        "proposal.yaml",
        "--summary",
        "Review a dynamic workflow",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result == {
        "id": "WP-0001",
        "ok": True,
        "path": ".project-loop/workflow-proposals/WP-0001.yaml",
        "status": "proposed",
        "summary": "Review a dynamic workflow",
        "workflow_id": "dynamic_review",
    }
    proposal_path = tmp_path / result["path"]
    assert proposal_path.exists()
    assert not (tmp_path / ".project-loop" / "workflows" / "dynamic_review.yaml").exists()

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        event = conn.execute(
            """
            SELECT event_type, entity_type, entity_id, payload_json
            FROM events
            WHERE event_type = 'workflow_proposed'
            """
        ).fetchone()
    finally:
        conn.close()
    assert event["entity_type"] == "workflow_proposal"
    assert event["entity_id"] == "WP-0001"
    payload = json.loads(event["payload_json"])
    assert payload["workflow_id"] == "dynamic_review"
    assert payload["path"] == ".project-loop/workflow-proposals/WP-0001.yaml"

    assert main(["--root", str(tmp_path), "workflow", "proposals", "list", "--json"]) == 0
    proposals = _json_output(capsys)["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["id"] == "WP-0001"
    assert proposals[0]["workflow_id"] == "dynamic_review"
    assert proposals[0]["status"] == "proposed"
    assert proposals[0]["workflow_path"] == ""
    assert proposals[0]["review_summary"] == ""
    assert proposals[0]["reviewed_at"] == ""
    assert proposals[0]["content_sha256"] == ""
    assert proposals[0]["summary"] == "Review a dynamic workflow"
    assert proposals[0]["parse_error"] == ""

    assert main(["--root", str(tmp_path), "workflow", "proposals", "read", "WP-0001", "--json"]) == 0
    proposal = _json_output(capsys)["proposal"]
    assert proposal["id"] == "WP-0001"
    assert proposal["status"] == "proposed"
    assert proposal["data"]["id"] == "dynamic_review"
    assert proposal["content"] == VALID_PROPOSAL

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    dashboard_data = json.loads(
        (tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(
            encoding="utf-8"
        )
    )
    assert dashboard_data["counts"]["workflow_proposals"] == 1
    assert dashboard_data["workflow_proposals"][0]["id"] == "WP-0001"
    assert dashboard_data["workflow_proposals"][0]["status"] == "proposed"
    assert dashboard_data["risk_summary"]["items"][0]["type"] == "workflow_proposal_review"
    dashboard_html = (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").read_text(
        encoding="utf-8"
    )
    assert "Workflow Proposals" in dashboard_html
    assert "WP-0001" in dashboard_html
    assert "proposed" in dashboard_html


def test_workflow_proposal_rejects_invalid_yaml_with_typed_error(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "bad.yaml").write_text("id: bad\nname: Missing fields\n", encoding="utf-8")
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "propose",
        "--file",
        "bad.yaml",
        "--json",
    ]) == 2
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "invalid_input"
    assert "missing required field" in payload["error"]["message"]
    assert not list((tmp_path / ".project-loop" / "workflow-proposals").glob("*.yaml"))


def test_workflow_proposal_is_not_executable_by_loop_run(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "proposal.yaml").write_text(VALID_PROPOSAL, encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "propose",
        "--file",
        "proposal.yaml",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "loop", "run", "WP-0001", "--json"]) == 2
    proposal_id_error = _json_output(capsys)
    assert proposal_id_error["error"]["code"] == "invalid_input"
    assert "Workflow template does not exist" in proposal_id_error["error"]["message"]

    assert main(["--root", str(tmp_path), "loop", "run", "dynamic_review", "--json"]) == 2
    workflow_id_error = _json_output(capsys)
    assert workflow_id_error["error"]["code"] == "invalid_input"
    assert "Workflow template does not exist" in workflow_id_error["error"]["message"]


def test_workflow_proposal_approve_promotes_template_and_allows_loop_run(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "proposal.yaml").write_text(VALID_PROPOSAL, encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "propose",
        "--file",
        "proposal.yaml",
        "--summary",
        "Review first",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approved for local use",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result["ok"] is True
    assert result["id"] == "WP-0001"
    assert result["status"] == "approved"
    assert result["workflow_id"] == "dynamic_review"
    assert result["path"] == ".project-loop/workflow-proposals/WP-0001.yaml"
    assert result["workflow_path"] == ".project-loop/workflows/dynamic_review.yaml"
    assert result["summary"] == "Approved for local use"
    assert len(result["content_sha256"]) == 64

    workflow_path = tmp_path / ".project-loop" / "workflows" / "dynamic_review.yaml"
    assert workflow_path.read_text(encoding="utf-8") == VALID_PROPOSAL

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        event = conn.execute(
            """
            SELECT event_type, entity_type, entity_id, payload_json
            FROM events
            WHERE event_type = 'workflow_proposal_approved'
            """
        ).fetchone()
    finally:
        conn.close()
    assert event["entity_type"] == "workflow_proposal"
    assert event["entity_id"] == "WP-0001"
    payload = json.loads(event["payload_json"])
    assert payload["workflow_id"] == "dynamic_review"
    assert payload["workflow_path"] == ".project-loop/workflows/dynamic_review.yaml"
    assert payload["content_sha256"] == result["content_sha256"]

    assert main(["--root", str(tmp_path), "workflow", "proposals", "read", "WP-0001", "--json"]) == 0
    proposal = _json_output(capsys)["proposal"]
    assert proposal["status"] == "approved"
    assert proposal["workflow_path"] == ".project-loop/workflows/dynamic_review.yaml"
    assert proposal["review_summary"] == "Approved for local use"
    assert proposal["content_sha256"] == result["content_sha256"]

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True

    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "dynamic_review",
        "--goal",
        "G-0001",
        "--json",
    ]) == 0
    run = _json_output(capsys)
    assert run["workflow_run"]["workflow_id"] == "dynamic_review"
    assert run["jobs"][0]["role"] == "reviewer"


def test_workflow_proposal_approve_failure_does_not_publish_runnable_template(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "proposal.yaml").write_text(VALID_PROPOSAL, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "proposal.yaml"]) == 0
    capsys.readouterr()

    def fail_append_event(**kwargs) -> str:
        raise RuntimeError("event append failed")

    monkeypatch.setattr(workflow_proposals, "append_event", fail_append_event)

    with pytest.raises(RuntimeError, match="event append failed"):
        workflow_proposals.approve_workflow_proposal(
            resolve_paths(tmp_path),
            "WP-0001",
            summary="Approved",
        )

    workflow_path = tmp_path / ".project-loop" / "workflows" / "dynamic_review.yaml"
    temp_paths = list((tmp_path / ".project-loop" / "workflows").glob(".*.tmp"))
    assert not workflow_path.exists()
    assert temp_paths == []

    assert main(["--root", str(tmp_path), "workflow", "proposals", "read", "WP-0001", "--json"]) == 0
    proposal = _json_output(capsys)["proposal"]
    assert proposal["status"] == "proposed"

    assert main(["--root", str(tmp_path), "loop", "run", "dynamic_review", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Workflow template does not exist" in payload["error"]["message"]


def test_workflow_proposal_cancel_keeps_proposal_non_executable(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "proposal.yaml").write_text(VALID_PROPOSAL, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "proposal.yaml"]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "cancel",
        "WP-0001",
        "--summary",
        "Not needed",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result == {
        "id": "WP-0001",
        "ok": True,
        "path": ".project-loop/workflow-proposals/WP-0001.yaml",
        "status": "cancelled",
        "summary": "Not needed",
        "workflow_id": "dynamic_review",
        "workflow_path": "",
    }

    assert main(["--root", str(tmp_path), "workflow", "proposals", "read", "WP-0001", "--json"]) == 0
    proposal = _json_output(capsys)["proposal"]
    assert proposal["status"] == "cancelled"
    assert proposal["review_summary"] == "Not needed"

    assert not (tmp_path / ".project-loop" / "workflows" / "dynamic_review.yaml").exists()
    assert main(["--root", str(tmp_path), "loop", "run", "dynamic_review", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Workflow template does not exist" in payload["error"]["message"]


def test_workflow_proposal_list_filters_by_derived_status(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    for index, workflow_id in enumerate(["review_a", "review_b", "review_c"], start=1):
        source = tmp_path / f"proposal-{index}.yaml"
        source.write_text(_proposal_with_id(workflow_id), encoding="utf-8")
        assert main([
            "--root",
            str(tmp_path),
            "workflow",
            "propose",
            "--file",
            source.name,
        ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0002",
        "--summary",
        "Approved",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "cancel",
        "WP-0003",
        "--summary",
        "Cancelled",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "workflow", "proposals", "list", "--json"]) == 0
    proposals = _json_output(capsys)["proposals"]
    assert [(proposal["id"], proposal["status"]) for proposal in proposals] == [
        ("WP-0001", "proposed"),
        ("WP-0002", "approved"),
        ("WP-0003", "cancelled"),
    ]

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "list",
        "--status",
        "proposed",
        "--json",
    ]) == 0
    assert [proposal["id"] for proposal in _json_output(capsys)["proposals"]] == ["WP-0001"]

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "list",
        "--status",
        "approved",
        "--json",
    ]) == 0
    assert [proposal["id"] for proposal in _json_output(capsys)["proposals"]] == ["WP-0002"]

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "list",
        "--status",
        "cancelled",
        "--json",
    ]) == 0
    assert [proposal["id"] for proposal in _json_output(capsys)["proposals"]] == ["WP-0003"]

    with pytest.raises(SystemExit) as exc:
        main([
            "--root",
            str(tmp_path),
            "workflow",
            "proposals",
            "list",
            "--status",
            "bogus",
        ])
    assert exc.value.code == 2


def test_workflow_proposal_invalid_review_transitions_return_typed_errors(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "proposal.yaml").write_text(VALID_PROPOSAL, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "proposal.yaml"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approved",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "cancel",
        "WP-0001",
        "--summary",
        "Too late",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Cannot cancel workflow proposal WP-0001 from status approved" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approve again",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Cannot approve workflow proposal WP-0001 from status approved" in payload["error"]["message"]


def test_next_routes_open_workflow_proposal_before_goal_continuation(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    (tmp_path / "proposal.yaml").write_text(VALID_PROPOSAL, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "proposal.yaml"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "review_workflow_proposal"
    assert action["priority"] == 55
    assert action["requires_human"] is True
    assert action["blocking"] is False
    assert action["target"]["id"] == "WP-0001"
    assert action["command"] == "pcl workflow proposals approve WP-0001 --summary 'Approve this workflow template'"

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approved",
    ]) == 0
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "continue_goal"


def test_strict_validation_rejects_corrupt_workflow_proposal(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    proposals_dir = tmp_path / ".project-loop" / "workflow-proposals"
    (proposals_dir / "WP-0001.yaml").write_text("id: bad\n", encoding="utf-8")
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert any("Workflow proposal WP-0001 is invalid" in error for error in payload["errors"])


def test_strict_validation_rejects_missing_workflow_proposal_directory(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "proposal.yaml").write_text(VALID_PROPOSAL, encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "propose",
        "--file",
        "proposal.yaml",
    ]) == 0
    shutil.rmtree(tmp_path / ".project-loop" / "workflow-proposals")
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Workflow proposal event WP-0001 references a missing proposal file." in payload["errors"]


def test_strict_validation_rejects_missing_approved_workflow_template(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "proposal.yaml").write_text(VALID_PROPOSAL, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "proposal.yaml"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approved",
    ]) == 0
    (tmp_path / ".project-loop" / "workflows" / "dynamic_review.yaml").unlink()
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert any("approved workflow template is missing" in error for error in payload["errors"])


def test_strict_validation_rejects_changed_approved_workflow_template(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "proposal.yaml").write_text(VALID_PROPOSAL, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "proposal.yaml"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approved",
    ]) == 0
    workflow_path = tmp_path / ".project-loop" / "workflows" / "dynamic_review.yaml"
    workflow_path.write_text(VALID_PROPOSAL.replace("Dynamic Review", "Changed Review"), encoding="utf-8")
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert any("approved workflow content hash differs" in error for error in payload["errors"])
