from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.context import TOKEN_ESTIMATOR, estimate_token_count


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_job(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(root),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    capsys.readouterr()


def _create_task_context(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Task context"]) == 0
    assert main([
        "--root",
        str(root),
        "feature",
        "add",
        "--name",
        "Context packs",
        "--surface",
        "cli:context",
        "--description",
        "Focused handoffs",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "defect",
        "open",
        "--feature",
        "F-0001",
        "--severity",
        "high",
        "--expected",
        "Task pack includes linked data",
        "--actual",
        "Task pack omits linked data",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Done dependency",
        "--priority",
        "20",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "status",
        "T-0001",
        "done",
        "--reason",
        "Dependency already finished",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Target task",
        "--description",
        "Implement context pack for task work.",
        "--priority",
        "10",
        "--owner",
        "codex",
        "--risk",
        "high",
        "--effort",
        "medium",
        "--goal",
        "G-0001",
        "--feature",
        "F-0001",
        "--defect",
        "D-0001",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Unmet dependency",
        "--priority",
        "30",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Dependent task",
        "--priority",
        "40",
        "--goal",
        "G-0001",
    ]) == 0
    assert main(["--root", str(root), "task", "depend", "T-0002", "--on", "T-0001"]) == 0
    assert main(["--root", str(root), "task", "depend", "T-0002", "--on", "T-0003"]) == 0
    assert main(["--root", str(root), "task", "depend", "T-0004", "--on", "T-0002"]) == 0
    capsys.readouterr()


def _rubric_v1() -> str:
    return json.dumps(
        {
            "contract_version": "rubric/v1",
            "acceptance_criteria": [
                {"criterion": "Context pack reviewed", "met": "yes", "evidence_id": None}
            ],
            "regression_risk": {"level": "low", "notes": None},
            "test_evidence": [],
            "security_ux_checks": [],
            "confidence_score": 0.8,
            "evidence_completeness": "partial",
        },
        sort_keys=True,
    )


def test_context_pack_for_job_returns_machine_handoff(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--role",
        "implementer",
        "--max-tokens",
        "12000",
        "--json",
    ]) == 0

    payload = _json_output(capsys)
    assert payload["ok"] is True
    pack = payload["context_pack"]
    assert pack["contract_version"] == "context-pack/v1"
    assert pack["target"] == {"type": "agent_job", "id": "J-0001"}
    assert pack["reader_role"] == "implementer"
    assert pack["role_profile"] == "implementer"
    assert pack["token_estimator"] == TOKEN_ESTIMATOR
    assert pack["budget"]["max_tokens"] == 12000
    assert pack["budget"]["approx_char_limit"] == 48000
    assert pack["budget"]["token_estimator"] == TOKEN_ESTIMATOR
    assert pack["estimated_token_count"] == estimate_token_count(pack["markdown"])
    assert pack["truncated"] is False
    assert "target_job" in pack["included_sections"]
    assert "agent_prompt" in pack["included_sections"]
    assert pack["source_commands"] == [
        "pcl jobs read J-0001 --json",
        "pcl prompt job J-0001 --json",
        "pcl validate --json",
    ]
    assert ".project-loop/evidence/agent-runs/J-0001/prompt.md" in pack["source_paths"]

    markdown = pack["markdown"]
    assert markdown.startswith("# Context Pack: J-0001")
    assert "## Machine Context Rules" in markdown
    assert "Do not read or parse `.project-loop/dashboard/dashboard.html`" in markdown
    assert ".project-loop/dashboard/dashboard-data.json" in markdown
    assert "## Target Job" in markdown
    assert "| id | J-0001 |" in markdown
    assert "| assigned_agent_id |  |" in markdown
    assert "| attempts | 0 |" in markdown
    assert "| lease_expires_at |  |" in markdown
    assert "| last_heartbeat_at |  |" in markdown
    assert "## Workflow Run" in markdown
    assert "## Agent Prompt" in markdown
    assert "# Agent Job J-0001" in markdown


def test_context_pack_non_json_prints_markdown(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "context", "pack", "--job", "J-0001"]) == 0

    captured = capsys.readouterr()
    assert captured.out.startswith("# Context Pack: J-0001")
    assert '"context_pack"' not in captured.out


def test_context_pack_reports_truncation_metadata(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--max-tokens",
        "20",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["truncated"] is True
    assert pack["omitted_sections"]
    assert pack["estimated_token_count"] <= pack["budget"]["max_tokens"]
    assert pack["markdown"].startswith("# Context Pack: J-0001")


def test_context_pack_for_task_returns_task_handoff_with_dependencies(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--json",
    ]) == 0

    payload = _json_output(capsys)
    pack = payload["context_pack"]
    assert pack["contract_version"] == "context-pack/v1"
    assert pack["target"] == {"type": "task", "id": "T-0002"}
    assert pack["reader_role"] == "default"
    assert pack["role_profile"] == "default"
    assert pack["token_estimator"] == TOKEN_ESTIMATOR
    assert pack["budget"]["token_estimator"] == TOKEN_ESTIMATOR
    assert pack["estimated_token_count"] == estimate_token_count(pack["markdown"])
    assert pack["source_commands"] == [
        "pcl task read T-0002 --json",
        "pcl task list --json",
        "pcl validate --json",
    ]
    assert pack["source_paths"] == []
    assert pack["included_sections"] == [
        "machine_context_rules",
        "target_task",
        "dependencies",
        "dependents",
        "goal",
        "related_feature",
        "related_defect",
        "sibling_tasks",
        "recent_events",
    ]

    markdown = pack["markdown"]
    assert markdown.startswith("# Context Pack: T-0002")
    assert "## Target Task" in markdown
    assert "| owner | codex |" in markdown
    assert "````markdown\nImplement context pack for task work.\n````" in markdown
    assert "## Dependencies" in markdown
    assert "| T-0001 | Done dependency | done | yes |" in markdown
    assert "| T-0003 | Unmet dependency | todo | no |" in markdown
    assert "## Dependents" in markdown
    assert "| T-0004 | Dependent task | todo |" in markdown
    assert "## Goal" in markdown
    assert "| title | Task context |" in markdown
    assert "## Related Feature" in markdown
    assert "| name | Context packs |" in markdown
    assert "## Related Defect" in markdown
    assert "| severity | high |" in markdown
    assert "## Sibling Tasks" in markdown
    assert "| T-0003 | Unmet dependency | todo | 30 |" in markdown
    assert "| T-0004 | Dependent task | todo | 40 |" in markdown


def test_context_pack_for_task_without_goal_omits_goal_only_sections(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Unlinked task",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    markdown = pack["markdown"]
    assert "No goal is linked to this task." in markdown
    assert "sibling_tasks" not in pack["included_sections"]
    assert "## Sibling Tasks" not in markdown
    assert "## Related Feature" not in markdown
    assert "## Related Defect" not in markdown


def test_context_pack_for_task_unknown_id_returns_typed_error(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-9999",
        "--json",
    ]) == 2

    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["message"] == "Task does not exist: T-9999"


def test_context_pack_for_task_reports_truncation_metadata(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--max-tokens",
        "80",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["truncated"] is True
    assert pack["omitted_sections"]
    assert pack["estimated_token_count"] <= pack["budget"]["max_tokens"]
    assert pack["markdown"].startswith("# Context Pack: T-0002")


def test_charclass_token_estimator_counts_stable_character_classes() -> None:
    assert estimate_token_count("abcd") == 1
    assert estimate_token_count("abcde") == 2
    assert estimate_token_count("hello world") == 5
    assert estimate_token_count("漢字") == 2
    assert estimate_token_count("a, b") == 4
    assert estimate_token_count("a\n\nb") == 3


def test_context_pack_for_job_tight_budget_omissions_match_markdown(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)

    args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--max-tokens",
        "40",
        "--json",
    ]
    assert main(args) == 0
    first = _json_output(capsys)["context_pack"]
    assert main(args) == 0
    second = _json_output(capsys)["context_pack"]

    assert first["included_sections"] == second["included_sections"]
    assert first["omitted_sections"] == second["omitted_sections"]
    assert first["estimated_token_count"] == estimate_token_count(first["markdown"])
    assert first["estimated_token_count"] <= first["budget"]["max_tokens"]
    for section_id in first["included_sections"]:
        assert _section_heading(section_id) in first["markdown"]
    for section_id in first["omitted_sections"]:
        assert _section_heading(section_id) not in first["markdown"]


def test_context_pack_for_task_tight_budget_omissions_match_markdown(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--max-tokens",
        "45",
        "--json",
    ]
    assert main(args) == 0
    first = _json_output(capsys)["context_pack"]
    assert main(args) == 0
    second = _json_output(capsys)["context_pack"]

    assert first["included_sections"] == second["included_sections"]
    assert first["omitted_sections"] == second["omitted_sections"]
    assert first["estimated_token_count"] == estimate_token_count(first["markdown"])
    assert first["estimated_token_count"] <= first["budget"]["max_tokens"]
    for section_id in first["included_sections"]:
        assert _section_heading(section_id) in first["markdown"]
    for section_id in first["omitted_sections"]:
        assert _section_heading(section_id) not in first["markdown"]


def test_context_pack_for_task_markdown_is_deterministic(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--json",
    ]
    assert main(args) == 0
    first = _json_output(capsys)["context_pack"]
    assert main(args) == 0
    second = _json_output(capsys)["context_pack"]

    assert first["markdown"] == second["markdown"]
    assert first["included_sections"] == second["included_sections"]
    assert first["omitted_sections"] == second["omitted_sections"]


def test_context_pack_role_profiles_prioritize_sections_under_budget(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
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
        "Reviewed handoff",
    ]) == 0
    capsys.readouterr()

    base_args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--max-tokens",
        "360",
    ]
    assert main([*base_args, "--json"]) == 0
    default_pack = _json_output(capsys)["context_pack"]
    assert main([*base_args, "--role", "verifier", "--json"]) == 0
    verifier_pack = _json_output(capsys)["context_pack"]
    assert main([*base_args, "--role", "astronaut", "--json"]) == 0
    unknown_pack = _json_output(capsys)["context_pack"]

    assert default_pack["role_profile"] == "implementer"
    assert "verifications" not in default_pack["included_sections"]
    assert verifier_pack["reader_role"] == "verifier"
    assert verifier_pack["role_profile"] == "verifier"
    assert "verifications" in verifier_pack["included_sections"]
    assert "## Verifications" in verifier_pack["markdown"]
    assert unknown_pack["reader_role"] == "astronaut"
    assert unknown_pack["role_profile"] == "implementer"


def test_context_pack_for_job_renders_active_lease_fields(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "register",
        "--name",
        "local-runner",
        "--role",
        "implementer",
        "--adapter",
        "manual",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "lease",
        "J-0001",
        "--agent",
        "A-0001",
        "--ttl-seconds",
        "600",
        "--json",
    ]) == 0
    lease = _json_output(capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--json",
    ]) == 0

    markdown = _json_output(capsys)["context_pack"]["markdown"]
    assert "| assigned_agent_id | A-0001 |" in markdown
    assert "| attempts | 0 |" in markdown
    assert f"| lease_expires_at | {lease['lease_expires_at']} |" in markdown
    assert f"| last_heartbeat_at | {lease['last_heartbeat_at']} |" in markdown


def test_context_pack_verifications_render_rubric_columns(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
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
        "inconclusive",
        "--reason",
        "Free-form verification",
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
        "--rubric-json",
        _rubric_v1(),
        "--reason",
        "Structured verification",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--json",
    ]) == 0

    markdown = _json_output(capsys)["context_pack"]["markdown"]
    assert "confidence_score" in markdown
    assert "evidence_completeness" in markdown
    assert "| V-0001 | J-0001 | human | inconclusive |  |  |" in markdown
    assert "| V-0002 | J-0001 | human | approved | 0.8 | partial |" in markdown


def _section_heading(section_id: str) -> str:
    return {
        "machine_context_rules": "## Machine Context Rules",
        "target_job": "## Target Job",
        "workflow_run": "## Workflow Run",
        "goal": "## Goal",
        "run_jobs": "## Jobs In This Run",
        "verifications": "## Verifications",
        "human_queue": "## Human Queue",
        "evidence": "## Evidence",
        "recent_events": "## Recent Events",
        "agent_prompt": "## Agent Prompt",
        "target_task": "## Target Task",
        "dependencies": "## Dependencies",
        "dependents": "## Dependents",
        "related_feature": "## Related Feature",
        "related_defect": "## Related Defect",
        "sibling_tasks": "## Sibling Tasks",
    }[section_id]
