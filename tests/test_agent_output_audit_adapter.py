from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from pcl.agent_output_audit import normalize_agent_output_audit_event
from pcl.contracts import validate_agent_output_audit


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "agent_output_audit_events"
OBSERVED_AT = "2026-09-01T00:00:00Z"


def _event(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("host", "fixture", "expected_event", "expected_tool"),
    [
        ("claude-code", "claude-pre-tool-use.json", "PreToolUse", "Bash"),
        ("gemini-cli", "gemini-before-tool.json", "BeforeTool", "run_shell_command"),
    ],
)
def test_synthetic_host_events_normalize_to_strict_nonleaking_audit_records(
    host: str,
    fixture: str,
    expected_event: str,
    expected_tool: str,
) -> None:
    event = _event(fixture)
    original = deepcopy(event)

    record = normalize_agent_output_audit_event(
        host=host,
        observed_at=OBSERVED_AT,
        event=event,
    )

    assert event == original
    assert validate_agent_output_audit(record).ok
    assert record["host"] == host
    assert record["event"] == expected_event
    assert record["tool"] == expected_tool
    assert record["classification"] == "unknown"
    assert record["reason_code"] == "host_command_string_not_tokenized"
    assert record["action"] == "observed_only"
    assert record["may_rewrite"] is False
    serialized = json.dumps(record, sort_keys=True)
    assert "SENTINEL" not in serialized
    assert "command" not in record
    assert "tool_input" not in record


def test_normalization_is_deterministic_for_the_same_trusted_time_and_event() -> None:
    event = _event("claude-pre-tool-use.json")

    first = normalize_agent_output_audit_event(
        host="claude-code",
        observed_at=OBSERVED_AT,
        event=event,
    )
    second = normalize_agent_output_audit_event(
        host="claude-code",
        observed_at=OBSERVED_AT,
        event=event,
    )

    assert first == second


@pytest.mark.parametrize(
    ("host", "event", "expected_error"),
    [
        ([], {}, "host must be a supported string"),
        ("opencode", {}, "unsupported agent-output audit host"),
        ("claude-code", [], "host event must be a JSON object"),
        (
            "claude-code",
            {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {}},
            "host event identity does not match the accepted audit protocol",
        ),
        (
            "claude-code",
            {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {}},
            "host event identity does not match the accepted audit protocol",
        ),
        (
            "claude-code",
            {"hook_event_name": "PreToolUse", "tool_name": "Bash"},
            "tool_input must be a JSON object",
        ),
        (
            "claude-code",
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": []},
            "tool_input must be a JSON object",
        ),
        (
            "claude-code",
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {}},
            "tool_input.command must be a string",
        ),
        (
            "claude-code",
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": ["pytest"]},
            },
            "tool_input.command must be a string",
        ),
    ],
)
def test_malformed_or_unsupported_events_fail_closed_without_echoing_input(
    host: object,
    event: object,
    expected_error: str,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        normalize_agent_output_audit_event(
            host=host,
            observed_at=OBSERVED_AT,
            event=event,
        )

    assert str(exc_info.value) == expected_error
    assert "SENTINEL" not in str(exc_info.value)


@pytest.mark.parametrize(
    "command",
    [
        "pytest --token=SECRET_SENTINEL",
        "pytest /Users/fixture/ABSOLUTE_PATH_SENTINEL",
        "X" * 1_000_000 + "OVERSIZED_SENTINEL",
    ],
)
def test_untrusted_command_strings_are_discarded_without_tokenization_or_leakage(
    command: str,
) -> None:
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "untrusted_extra": "EXTRA_SENTINEL",
    }

    record = normalize_agent_output_audit_event(
        host="claude-code",
        observed_at=OBSERVED_AT,
        event=event,
    )

    assert record["classification"] == "unknown"
    assert record["reason_code"] == "host_command_string_not_tokenized"
    assert "SENTINEL" not in json.dumps(record, sort_keys=True)


def test_invalid_observation_time_fails_without_echoing_the_value() -> None:
    with pytest.raises(ValueError) as exc_info:
        normalize_agent_output_audit_event(
            host="claude-code",
            observed_at="TIME_SECRET_SENTINEL",
            event=_event("claude-pre-tool-use.json"),
        )

    assert str(exc_info.value) == "audit fields must satisfy agent-output-audit/v1"
    assert "TIME_SECRET_SENTINEL" not in str(exc_info.value)
