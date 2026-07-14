from __future__ import annotations

import json
from pathlib import Path

import pcl.skill_usage_report as skill_usage_report
from pcl.cli import main
from pcl.skill_usage_report import render_skill_usage_markdown, report_skill_usage


WINDOW = {"since": "2026-07-01", "until": "2026-07-31"}


def _write_jsonl(path: Path, rows: list[dict], *, malformed: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    if malformed:
        serialized += "{not-json project-control-loop/SKILL.md SECRET_MALFORMED\n"
    path.write_text(serialized, encoding="utf-8")


def _codex_call(command: str, *, call_id: str) -> dict:
    payload = json.dumps({"cmd": command, "workdir": "/workspace/SECRET_PROJECT"})
    return {
        "timestamp": "2026-07-14T00:01:00Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "name": "exec",
            "call_id": call_id,
            "input": f"const r = await tools.exec_command({payload}); text(r.output);",
        },
    }


def _codex_output(output: str, *, call_id: str) -> dict:
    return {
        "timestamp": "2026-07-14T00:02:00Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": call_id,
            "output": output,
        },
    }


def _codex_fixture(root: Path) -> None:
    _write_jsonl(
        root / "2026" / "07" / "catalog-only.jsonl",
        [
            {
                "timestamp": "2026-07-14T00:00:00Z",
                "type": "session_meta",
                "payload": {"id": "SECRET-CATALOG-ID", "cwd": "/SECRET/catalog"},
            },
            {
                "timestamp": "2026-07-14T00:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "content": "available skill: project-control-loop/SKILL.md SECRET_CATALOG",
                },
            },
        ],
    )
    _write_jsonl(
        root / "2026" / "07" / "used.jsonl",
        [
            {
                "timestamp": "2026-07-14T00:00:00Z",
                "type": "session_meta",
                "payload": {"id": "SECRET-CODEX-ID", "cwd": "/SECRET/codex-workspace"},
            },
            _codex_call(
                "sed -n '1,380p' /SECRET/project-control-loop/SKILL.md",
                call_id="SECRET-READ-CALL",
            ),
            _codex_call(
                "PYTHONPATH=src python -m pcl validate --json; "
                "PYTHONPATH=src python -m pcl validate --json; "
                "PYTHONPATH=src python -m pcl finish --emit-packet --goal G-SECRET "
                "--token SECRET_TOKEN --json; pcl migrate /SECRET/private",
                call_id="SECRET-PCL-CALL",
            ),
            {
                "timestamp": "2026-07-14T00:02:00Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "SECRET-PCL-CALL",
                    "output": (
                        "finish_checks_not_configured at /SECRET/codex-workspace "
                        "token=SECRET_TOKEN"
                    ),
                },
            },
            {
                "timestamp": "2026-07-14T00:03:00Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "SECRET-UNRELATED-CALL",
                    "output": "unrelated process timed out in /SECRET/unrelated",
                },
            },
        ],
    )


def _claude_fixture(root: Path) -> None:
    _write_jsonl(
        root / "project" / "session.jsonl",
        [
            {
                "timestamp": "2026-07-14T01:00:00Z",
                "type": "assistant",
                "sessionId": "SECRET-CLAUDE-ID",
                "cwd": "/SECRET/claude-workspace",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Skill",
                            "id": "SECRET-SKILL-CALL",
                            "input": {"skill": "project-control-loop"},
                        },
                        {
                            "type": "tool_use",
                            "name": "Read",
                            "id": "SECRET-READ-CALL",
                            "input": {
                                "file_path": "/SECRET/project-control-loop/SKILL.md"
                            },
                        },
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "id": "SECRET-BASH-CALL",
                            "input": {
                                "command": (
                                    "pcl next --json && "
                                    "pcl --root /SECRET/root report kpi --json"
                                )
                            },
                        },
                    ]
                },
            },
            {
                "timestamp": "2026-07-14T01:01:00Z",
                "type": "user",
                "sessionId": "SECRET-CLAUDE-ID",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "SECRET-BASH-CALL",
                            "is_error": True,
                            "content": "Exit code 2 SECRET_FAILURE /SECRET/root",
                        }
                    ]
                },
            },
        ],
    )


def _cockpit_fixture(root: Path) -> None:
    _write_jsonl(
        root / "SECRET-TASK-ID.jsonl",
        [
            {
                "createdAt": "2026-07-14T02:00:00Z",
                "taskId": "SECRET-TASK-ID",
                "seq": 1,
                "message": "Use [skill:project-control-loop] for SECRET_TASK",
            },
            {
                "createdAt": "2026-07-14T02:01:00Z",
                "taskId": "SECRET-TASK-ID",
                "seq": 2,
                "message": "Still using $project-control-loop in /SECRET/task",
            },
        ],
    )


def _report(tmp_path: Path) -> dict:
    codex = tmp_path / "codex"
    claude = tmp_path / "claude"
    cockpit = tmp_path / "cockpit"
    _codex_fixture(codex)
    _claude_fixture(claude)
    _cockpit_fixture(cockpit)
    return report_skill_usage(
        since=WINDOW["since"],
        until=WINDOW["until"],
        sources=["codex", "claude", "cockpit"],
        codex_root=codex,
        claude_root=claude,
        cockpit_root=cockpit,
    )


def test_skill_usage_report_counts_execution_not_catalog_and_keeps_cockpit_separate(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)

    assert report["contract_version"] == "skill-usage-report/v1"
    assert report["window"] == WINDOW
    assert report["summary"] == {
        "agent_skill_sessions": 2,
        "agent_sessions_with_pcl_commands": 2,
        "pcl_commands_detected": 6,
        "distinct_workspaces": 2,
        "cockpit_control_plane_tasks": 1,
    }
    assert report["sources"]["codex"]["skill_sessions"] == 1
    assert report["sources"]["claude"]["skill_sessions"] == 1
    assert report["sources"]["cockpit"]["control_plane_tasks"] == 1
    assert report["commands"] == [
        {"command": "validate", "count": 2, "session_count": 1},
        {"command": "finish", "count": 1, "session_count": 1},
        {"command": "migrate", "count": 1, "session_count": 1},
        {"command": "next", "count": 1, "session_count": 1},
        {"command": "report kpi", "count": 1, "session_count": 1},
    ]


def test_skill_usage_report_classifies_friction_and_emits_advisory_candidates(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)
    friction = {item["code"]: item for item in report["friction"]}

    assert friction["finish_checks_not_configured"]["session_count"] == 1
    assert friction["command_error"]["session_count"] == 1
    assert "repeated_command" not in friction
    assert "timeout" not in friction
    assert friction["finish_checks_not_configured"]["commands"] == [
        {"command": "finish", "occurrence_count": 1, "session_count": 1},
        {"command": "migrate", "occurrence_count": 1, "session_count": 1},
        {"command": "validate", "occurrence_count": 1, "session_count": 1},
    ]
    assert friction["command_error"]["commands"] == [
        {"command": "next", "occurrence_count": 1, "session_count": 1},
        {"command": "report kpi", "occurrence_count": 1, "session_count": 1},
    ]
    candidates = {item["code"]: item for item in report["improvement_candidates"]}
    assert candidates["finish_check_bootstrap"]["priority"] == "P0"
    assert candidates["finish_check_bootstrap"]["evidence"]["leading_command"] == {
        "command": "finish",
        "occurrence_count": 1,
        "session_count": 1,
    }
    assert "reduce_repeated_command_roundtrips" not in candidates
    assert all(item["advisory"] is True for item in candidates.values())


def test_skill_usage_report_counts_only_failure_driven_matching_retries(
    tmp_path: Path,
) -> None:
    codex = tmp_path / "codex"
    skill_read = _codex_call(
        "sed -n '1,380p' /SECRET/project-control-loop/SKILL.md",
        call_id="SECRET-READ",
    )
    session_meta = {
        "timestamp": "2026-07-14T00:00:00Z",
        "type": "session_meta",
        "payload": {"cwd": "/SECRET/workspace"},
    }
    _write_jsonl(
        codex / "2026" / "07" / "routine.jsonl",
        [
            {**session_meta, "payload": {**session_meta["payload"], "id": "ROUTINE"}},
            skill_read,
            _codex_call("pcl validate --json", call_id="ROUTINE-1"),
            _codex_call("pcl validate --json", call_id="ROUTINE-2"),
        ],
    )
    _write_jsonl(
        codex / "2026" / "07" / "matching-retry.jsonl",
        [
            {**session_meta, "payload": {**session_meta["payload"], "id": "MATCH"}},
            skill_read,
            _codex_call("pcl validate --json", call_id="MATCH-1"),
            _codex_output("Exit code 2 SECRET_FAILURE", call_id="MATCH-1"),
            _codex_call("pcl validate --json", call_id="MATCH-2"),
        ],
    )
    _write_jsonl(
        codex / "2026" / "07" / "different-command.jsonl",
        [
            {**session_meta, "payload": {**session_meta["payload"], "id": "DIFFERENT"}},
            skill_read,
            _codex_call("pcl validate --json", call_id="DIFFERENT-1"),
            _codex_output("Exit code 2 SECRET_FAILURE", call_id="DIFFERENT-1"),
            _codex_call("pcl render --json", call_id="DIFFERENT-2"),
            _codex_output("Exit code 2 SECRET_UNKNOWN", call_id="UNKNOWN"),
        ],
    )

    report = report_skill_usage(
        since=WINDOW["since"],
        until=WINDOW["until"],
        sources=["codex"],
        codex_root=codex,
    )
    friction = {item["code"]: item for item in report["friction"]}

    assert friction["repeated_command"] == {
        "code": "repeated_command",
        "occurrence_count": 1,
        "session_count": 1,
        "classification": "observed_signal_not_proven_product_defect",
        "commands": [
            {"command": "validate", "occurrence_count": 1, "session_count": 1}
        ],
    }
    assert friction["command_error"]["occurrence_count"] == 2
    assert friction["command_error"]["commands"] == [
        {"command": "validate", "occurrence_count": 2, "session_count": 2}
    ]


def test_skill_usage_report_attributes_help_probe_to_normalized_command(
    tmp_path: Path,
) -> None:
    codex = tmp_path / "codex"
    _write_jsonl(
        codex / "2026" / "07" / "help.jsonl",
        [
            {
                "timestamp": "2026-07-14T00:00:00Z",
                "type": "session_meta",
                "payload": {"id": "SECRET-ID", "cwd": "/SECRET/workspace"},
            },
            _codex_call(
                "sed -n '1,380p' /SECRET/project-control-loop/SKILL.md",
                call_id="SECRET-READ",
            ),
            _codex_call("pcl test pass --help SECRET_ARGUMENT", call_id="SECRET-HELP"),
        ],
    )

    report = report_skill_usage(
        since=WINDOW["since"],
        until=WINDOW["until"],
        sources=["codex"],
        codex_root=codex,
    )
    friction = {item["code"]: item for item in report["friction"]}

    assert friction["help_probe"]["commands"] == [
        {"command": "test pass", "occurrence_count": 1, "session_count": 1}
    ]
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    markdown = render_skill_usage_markdown(report)
    assert "SECRET_ARGUMENT" not in serialized
    assert "`test pass` 1" in markdown
    assert "SECRET_ARGUMENT" not in markdown


def test_skill_usage_report_tracks_guide_without_retaining_topic_or_arguments(
    tmp_path: Path,
) -> None:
    codex = tmp_path / "codex"
    _write_jsonl(
        codex / "2026" / "07" / "guide.jsonl",
        [
            {
                "timestamp": "2026-07-14T00:00:00Z",
                "type": "session_meta",
                "payload": {"id": "SECRET-ID", "cwd": "/SECRET/workspace"},
            },
            _codex_call(
                "sed -n '1,380p' /SECRET/project-control-loop/SKILL.md",
                call_id="SECRET-READ",
            ),
            _codex_call(
                "pcl guide direct --json SECRET_ARGUMENT",
                call_id="SECRET-GUIDE",
            ),
        ],
    )

    report = report_skill_usage(
        since=WINDOW["since"],
        until=WINDOW["until"],
        sources=["codex"],
        codex_root=codex,
    )

    assert report["commands"] == [
        {"command": "guide", "count": 1, "session_count": 1}
    ]
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    markdown = render_skill_usage_markdown(report)
    assert "direct" not in serialized
    assert "SECRET_ARGUMENT" not in serialized
    assert "| `guide` | 1 | 1 |" in markdown
    assert "SECRET_ARGUMENT" not in markdown


def test_skill_usage_report_never_retains_sensitive_raw_values(tmp_path: Path) -> None:
    report = _report(tmp_path)
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    markdown = render_skill_usage_markdown(report)

    for forbidden in (
        "SECRET",
        "G-SECRET",
        "SECRET_TOKEN",
        "Exit code 2",
        "pcl validate",
        str(tmp_path),
    ):
        assert forbidden not in serialized
        assert forbidden not in markdown
    assert report["privacy"] == {
        "raw_content_retained": False,
        "command_arguments_retained": False,
        "session_identifiers_retained": False,
        "workspace_paths_retained": False,
        "external_transmission": False,
    }


def test_skill_usage_report_source_health_window_and_invalid_json(tmp_path: Path) -> None:
    codex = tmp_path / "codex"
    _write_jsonl(
        codex / "broken.jsonl",
        [
            {
                "timestamp": "2026-07-14T00:00:00Z",
                "type": "session_meta",
                "payload": {"id": "hidden", "cwd": "/hidden"},
            },
            _codex_call(
                "sed -n '1,20p' /hidden/project-control-loop/SKILL.md",
                call_id="hidden-read",
            ),
        ],
        malformed=True,
    )
    missing = tmp_path / "missing"

    report = report_skill_usage(
        since=WINDOW["since"],
        until=WINDOW["until"],
        sources=["codex", "claude"],
        codex_root=codex,
        claude_root=missing,
    )

    assert report["sources"]["codex"]["status"] == "available"
    assert report["sources"]["codex"]["parse_errors"] == 1
    assert report["sources"]["claude"] == {
        "status": "unavailable",
        "files_scanned": 0,
        "parse_errors": 0,
        "skill_sessions": 0,
        "sessions_with_pcl_commands": 0,
        "commands_detected": 0,
        "distinct_workspaces": 0,
    }
    assert "cockpit" not in report["sources"]


def test_skill_usage_report_has_standard_library_fallback(tmp_path: Path, monkeypatch) -> None:
    codex = tmp_path / "codex"
    _codex_fixture(codex)
    monkeypatch.setattr(skill_usage_report.shutil, "which", lambda _name: None)

    report = report_skill_usage(
        since=WINDOW["since"],
        until=WINDOW["until"],
        sources=["codex"],
        codex_root=codex,
    )

    assert report["summary"]["agent_skill_sessions"] == 1
    assert report["summary"]["pcl_commands_detected"] == 4


def test_skill_usage_cli_is_read_only_and_output_is_deterministic(
    tmp_path: Path,
    capsys,
) -> None:
    project = tmp_path / "project"
    codex = tmp_path / "codex"
    _codex_fixture(codex)
    assert main(["init", "--target", str(project), "--json"]) == 0
    capsys.readouterr()
    db_path = project / ".project-loop" / "project.db"
    events_path = project / ".project-loop" / "events.jsonl"
    source_path = next(codex.rglob("used.jsonl"))
    before = (db_path.read_bytes(), events_path.read_bytes(), source_path.read_bytes())
    output = tmp_path / "reports" / "usage.md"
    args = [
        "--root",
        str(project),
        "report",
        "skill-usage",
        "--since",
        WINDOW["since"],
        "--until",
        WINDOW["until"],
        "--source",
        "codex",
        "--codex-root",
        str(codex),
        "--output",
        str(output),
    ]

    assert main(args) == 0
    first_stdout = capsys.readouterr().out
    first_bytes = output.read_bytes()
    assert main(args) == 0
    assert capsys.readouterr().out == first_stdout
    assert output.read_bytes() == first_bytes
    assert (db_path.read_bytes(), events_path.read_bytes(), source_path.read_bytes()) == before


def test_skill_usage_cli_rejects_invalid_window_and_unknown_source(
    tmp_path: Path,
    capsys,
) -> None:
    assert main([
        "report",
        "skill-usage",
        "--since",
        "yesterday",
        "--json",
    ]) == 2
    invalid_date = json.loads(capsys.readouterr().out)["error"]
    assert invalid_date["code"] == "invalid_input"

    assert main([
        "report",
        "skill-usage",
        "--source",
        "gemini",
        "--json",
    ]) == 2
    invalid_source = json.loads(capsys.readouterr().out)["error"]
    assert invalid_source["code"] == "invalid_input"
    assert invalid_source["details"] == {
        "unknown_sources": ["gemini"],
        "allowed_sources": ["codex", "claude", "cockpit"],
    }


def test_skill_usage_cli_rejects_output_over_source_or_authoritative_state(
    tmp_path: Path,
    capsys,
) -> None:
    project = tmp_path / "project"
    codex = tmp_path / "codex"
    _codex_fixture(codex)
    assert main(["init", "--target", str(project), "--json"]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(project),
        "report",
        "skill-usage",
        "--since",
        WINDOW["since"],
        "--until",
        WINDOW["until"],
        "--source",
        "codex",
        "--codex-root",
        str(codex),
        "--output",
        str(codex / "overwritten.jsonl"),
        "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["details"] == {
        "output_rejected": True
    }
