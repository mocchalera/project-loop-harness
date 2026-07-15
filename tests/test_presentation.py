from pcl.commands import to_pretty_json as commands_to_pretty_json
from pcl.presentation import (
    format_context_check_summary,
    format_finish_summary,
    format_next_explanation,
    format_start_summary,
    impact_text_payload,
    to_pretty_json,
)


def test_pretty_json_keeps_commands_compatibility_export() -> None:
    value = {"z": 1, "日本語": True}

    assert commands_to_pretty_json is to_pretty_json
    assert to_pretty_json(value) == '{\n  "z": 1,\n  "日本語": true\n}'


def test_impact_text_payload_summarizes_excluded_paths_without_mutation() -> None:
    impact = {
        "changed_files": ["src/pcl/cli.py"],
        "excluded_changed_files": [{"path": f"ignored-{index}.txt"} for index in range(7)],
    }

    display, summary = impact_text_payload(impact)

    assert display == {
        "changed_files": ["src/pcl/cli.py"],
        "excluded_changed_file_count": 7,
    }
    assert summary == (
        "Excluded changed files: 7 (ignored-0.txt, ignored-1.txt, ignored-2.txt, "
        "ignored-3.txt, ignored-4.txt, ... (+2 more))"
    )
    assert len(impact["excluded_changed_files"]) == 7


def test_context_check_summary_preserves_optional_lines_and_order() -> None:
    payload = {
        "target": {"type": "task", "id": "T-0001"},
        "target_bound_code_context": {
            "status": "current",
            "receipt_ref": {"evidence_id": "E-0001", "created_at": "2026-07-15"},
        },
        "supporting_evidence_count": 2,
        "master_trace_context": {"status": "valid"},
        "canonical_context_pack_command": "pcl context pack --task T-0001",
        "recommended_refresh_command": "pcl index build --json",
        "warnings": ["review source drift"],
    }

    assert format_context_check_summary(payload) == "\n".join(
        [
            "Context check: task T-0001",
            "Target-bound code context: current",
            "Receipt: E-0001 (2026-07-15)",
            "Supporting evidence: 2",
            "Master trace context: valid",
            "Canonical pack command: pcl context pack --task T-0001",
            "Recommended refresh command: pcl index build --json",
            "WARNING: review source drift",
        ]
    )


def test_next_explanation_preserves_guided_action_text() -> None:
    action = {
        "type": "continue_task",
        "priority": 59,
        "blocking": False,
        "requires_human": False,
        "safe_to_run": False,
        "run_policy": "agent_safe",
        "human_guidance": "Continue the bounded task.",
        "reason": "The task is ready.",
        "command": "pcl task read T-0001",
        "expected_after": "The task context is available.",
        "target": {"id": "T-0001", "type": "task"},
    }

    assert format_next_explanation(action) == "\n".join(
        [
            "Next action: continue_task",
            "Priority: 59",
            "Blocking: no",
            "Requires human: no",
            "Safe to run: no",
            "Run policy: agent_safe",
            "Human guidance: Continue the bounded task.",
            "Reason: The task is ready.",
            "Command: pcl task read T-0001",
            "Expected after: The task context is available.",
            "Target: T-0001",
        ]
    )


def test_finish_summary_preserves_steps_and_execution_results() -> None:
    payload = {
        "target": {"run": None, "goal": "G-0001"},
        "finished": False,
        "remaining_steps": [
            {
                "command": "pcl task status T-0001 done",
                "requires_human": False,
                "safe_to_run": False,
            }
        ],
        "executed": [{"command": "pcl validate --strict", "ok": True}],
        "changed": True,
    }

    assert format_finish_summary(payload) == "\n".join(
        [
            "Finish target: run=- goal=G-0001",
            "Finished: no",
            "Remaining steps:",
            "1. pcl task status T-0001 done (requires_human=no, safe_to_run=no)",
            "Executed:",
            "- pcl validate --strict: ok",
            "Changed: yes",
        ]
    )


def test_start_summary_preserves_initialization_warnings_and_next_action() -> None:
    payload = {
        "status": "started",
        "mutated": True,
        "result": {
            "intent": "implement the next slice",
            "target": {"type": "task", "id": "T-0001"},
            "initialization": {
                "changes": [
                    {"action": "create", "path": "pcl.yaml", "reason": "missing"}
                ]
            },
        },
        "warnings": ["review the initialization plan"],
        "next_actions": [
            {"text": "Review task context.", "command": "pcl task read T-0001"}
        ],
    }

    assert format_start_summary(payload) == "\n".join(
        [
            "Start status: started",
            "Mutated: yes",
            "Intent: implement the next slice",
            "Target: task T-0001",
            "Initialization plan:",
            "- create: pcl.yaml (missing)",
            "WARNING: review the initialization plan",
            "Next: Review task context.",
            "Run: pcl task read T-0001",
        ]
    )
