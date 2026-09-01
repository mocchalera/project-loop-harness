from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from pcl.agent_output_policy import canonical_agent_output_policy, classify_agent_output_argv
from pcl.contracts import (
    AGENT_OUTPUT_AUDIT_CONTRACT_VERSION,
    AGENT_OUTPUT_AUDIT_FIELD_ALLOWLIST,
    AGENT_OUTPUT_AUDIT_REASON_CLASSIFICATIONS,
    AGENT_OUTPUT_AUDIT_REASON_CODES,
    agent_output_audit_schema,
    agent_output_command_shape_sha256,
    build_agent_output_audit_record,
    canonical_agent_output_audit_json,
    load_agent_output_audit,
    validate_agent_output_audit,
)


OBSERVED_AT = "2026-09-01T00:00:00Z"


def _record(
    *,
    host: str = "claude-code",
    event: str = "PreToolUse",
    tool: str = "Bash",
    argv: list[str] | None = None,
) -> dict[str, object]:
    classification = classify_agent_output_argv(argv or ["pytest"])
    return build_agent_output_audit_record(
        observed_at=OBSERVED_AT,
        host=host,
        event=event,
        tool=tool,
        classification=classification,
    )


@pytest.mark.parametrize(
    ("host", "event", "tool"),
    [
        ("claude-code", "PreToolUse", "Bash"),
        ("gemini-cli", "BeforeTool", "run_shell_command"),
    ],
)
def test_supported_audit_host_protocols_build_strict_observed_only_records(
    host: str,
    event: str,
    tool: str,
) -> None:
    record = _record(host=host, event=event, tool=tool)

    assert validate_agent_output_audit(record).ok
    assert record["schema"] == AGENT_OUTPUT_AUDIT_CONTRACT_VERSION
    assert record["action"] == "observed_only"
    assert record["may_rewrite"] is False
    assert set(record) == AGENT_OUTPUT_AUDIT_FIELD_ALLOWLIST


def test_command_shape_digest_is_category_only_and_validator_recomputes_it() -> None:
    classification = classify_agent_output_argv(["pytest", "--client-secret=SENTINEL"])
    record = build_agent_output_audit_record(
        observed_at=OBSERVED_AT,
        host="claude-code",
        event="PreToolUse",
        tool="Bash",
        classification=classification,
    )

    assert record["classification"] == "unknown"
    assert record["reason_code"] == "secret_shaped_argv"
    assert "SENTINEL" not in json.dumps(record)
    assert record["command_shape_sha256"] == agent_output_command_shape_sha256(
        classification="unknown",
        reason_code="secret_shaped_argv",
        already_wrapped=False,
    )

    tampered = {**record, "command_shape_sha256": "sha256:" + "0" * 64}
    result = validate_agent_output_audit(tampered)
    assert not result.ok
    assert any("privacy-reduced classification shape" in error for error in result.errors)


@pytest.mark.parametrize(
    "field",
    [
        "argv",
        "command",
        "cwd",
        "environment",
        "raw_output",
        "repository_url",
        "session_id",
        "stderr",
        "stdout",
        "tool_input",
        "transcript_path",
    ],
)
def test_audit_record_rejects_non_allowlisted_sensitive_surfaces_without_value_leak(
    field: str,
) -> None:
    record = {**_record(), field: "/Users/REVIEWER_PATH_SENTINEL/TOKEN_SENTINEL"}

    result = validate_agent_output_audit(record)

    assert not result.ok
    assert f"$.{field}: additional property is not allowed" in result.errors
    assert "REVIEWER_PATH_SENTINEL" not in "\n".join(result.errors)
    assert "TOKEN_SENTINEL" not in "\n".join(result.errors)


@pytest.mark.parametrize(
    ("host", "event", "tool", "expected_fragment"),
    [
        ("claude-code", "BeforeTool", "Bash", "require 'PreToolUse'"),
        ("claude-code", "PreToolUse", "run_shell_command", "require 'Bash'"),
        ("gemini-cli", "PreToolUse", "run_shell_command", "require 'BeforeTool'"),
        ("gemini-cli", "BeforeTool", "Bash", "require 'run_shell_command'"),
    ],
)
def test_host_event_tool_mismatches_fail_closed(
    host: str,
    event: str,
    tool: str,
    expected_fragment: str,
) -> None:
    record = _record()
    record.update({"host": host, "event": event, "tool": tool})

    result = validate_agent_output_audit(record)

    assert not result.ok
    assert any(expected_fragment in error for error in result.errors)


@pytest.mark.parametrize("classification", ["eligible", "negative", "unknown"])
def test_already_wrapped_flag_is_false_for_every_other_classification(
    classification: str,
) -> None:
    record = _record()
    record["classification"] = classification
    record["reason_code"] = "fixture_reason"
    record["already_wrapped"] = True
    record["command_shape_sha256"] = agent_output_command_shape_sha256(
        classification=classification,
        reason_code="fixture_reason",
        already_wrapped=True,
    )

    result = validate_agent_output_audit(record)

    assert not result.ok
    assert any("true exactly when classification" in error for error in result.errors)


def test_already_wrapped_classification_builds_consistent_record() -> None:
    record = _record(argv=["pcl", "exec", "--", "pytest"])

    assert record["classification"] == "already_wrapped"
    assert record["already_wrapped"] is True
    assert record["may_rewrite"] is False
    assert validate_agent_output_audit(record).ok


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_at", "2026-09-01T09:00:00+09:00"),
        ("observed_at", "not-a-time"),
        ("action", "rewrite"),
        ("may_rewrite", True),
        ("reason_code", "contains/slash"),
        ("command_shape_sha256", "sha256:not-a-digest"),
    ],
)
def test_invalid_or_authority_widening_fields_fail_closed(field: str, value: object) -> None:
    record = {**_record(), field: value}

    assert not validate_agent_output_audit(record).ok


def test_schema_property_allowlist_matches_runtime_allowlist() -> None:
    schema = agent_output_audit_schema()

    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == AGENT_OUTPUT_AUDIT_FIELD_ALLOWLIST
    assert set(schema["required"]) == AGENT_OUTPUT_AUDIT_FIELD_ALLOWLIST
    assert set(schema["properties"]["reason_code"]["enum"]) == AGENT_OUTPUT_AUDIT_REASON_CODES


@pytest.mark.parametrize(
    ("reason_code", "expected_classification"),
    sorted(AGENT_OUTPUT_AUDIT_REASON_CLASSIFICATIONS.items()),
)
def test_every_audit_reason_code_has_one_frozen_classification(
    reason_code: str,
    expected_classification: str,
) -> None:
    assert expected_classification in {"eligible", "negative", "unknown", "already_wrapped"}
    assert AGENT_OUTPUT_AUDIT_REASON_CLASSIFICATIONS[reason_code] == expected_classification


def test_canonical_policy_reason_codes_are_covered_by_the_audit_allowlist() -> None:
    policy = canonical_agent_output_policy()

    for section, expected_classification in (
        ("eligible_argv_rules", "eligible"),
        ("negative_argv_rules", "negative"),
    ):
        for rule in policy[section]:
            assert (
                AGENT_OUTPUT_AUDIT_REASON_CLASSIFICATIONS[rule["reason_code"]]
                == expected_classification
            )


def test_reason_code_cannot_smuggle_free_form_data_or_claim_wrong_classification() -> None:
    free_form = _record()
    free_form["reason_code"] = "token_sentinel"
    free_form["command_shape_sha256"] = agent_output_command_shape_sha256(
        classification="eligible",
        reason_code="token_sentinel",
        already_wrapped=False,
    )
    free_form_result = validate_agent_output_audit(free_form)
    assert not free_form_result.ok
    assert "token_sentinel" not in "\n".join(free_form_result.errors)

    wrong_classification = _record()
    wrong_classification["classification"] = "eligible"
    wrong_classification["reason_code"] = "file_read_cat"
    wrong_classification["command_shape_sha256"] = agent_output_command_shape_sha256(
        classification="eligible",
        reason_code="file_read_cat",
        already_wrapped=False,
    )
    wrong_result = validate_agent_output_audit(wrong_classification)
    assert not wrong_result.ok
    assert any("frozen classification" in error for error in wrong_result.errors)


def test_audit_record_canonical_json_is_deterministic() -> None:
    record = _record()
    reordered = dict(reversed(list(record.items())))

    assert canonical_agent_output_audit_json(record) == canonical_agent_output_audit_json(
        reordered
    )
    assert canonical_agent_output_audit_json(record).startswith('{"action":"observed_only"')


def test_strict_audit_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "audit.json"
    path.write_text('{"schema":"agent-output-audit/v1","schema":"duplicate"}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        load_agent_output_audit(path)


def test_builder_rejects_invalid_classification_without_echoing_input() -> None:
    classification = deepcopy(classify_agent_output_argv(["pytest"]))
    classification["reason_code"] = "TOKEN_SENTINEL/invalid"

    with pytest.raises(ValueError, match="must satisfy agent-output-classification/v1") as exc:
        build_agent_output_audit_record(
            observed_at=OBSERVED_AT,
            host="claude-code",
            event="PreToolUse",
            tool="Bash",
            classification=classification,
        )

    assert "TOKEN_SENTINEL" not in str(exc.value)
