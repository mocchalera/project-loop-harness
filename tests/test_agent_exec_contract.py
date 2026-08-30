from __future__ import annotations

from copy import deepcopy

import pytest

from pcl.contracts.agent_exec_result import (
    AGENT_EXEC_RESULT_CONTRACT_VERSION,
    agent_exec_result_schema,
    validate_agent_exec_result,
)


def _valid_payload() -> dict:
    return {
        "schema": AGENT_EXEC_RESULT_CONTRACT_VERSION,
        "run_id": "AX-20260830T143909Z-abcdef123456",
        "status": "FAIL",
        "exit_code": 7,
        "signal": None,
        "duration_ms": 3912,
        "command": ["python", "-c", "raise SystemExit(7)"],
        "command_redacted": False,
        "raw": {"stdout_bytes": 65000, "stderr_bytes": 122},
        "exposed": {"lines": 8, "bytes": 512},
        "diagnostics": {
            "available": True,
            "truncated": False,
            "strategy": "error-block",
            "line_count": 5,
            "byte_count": 220,
        },
        "redacted": False,
        "output_truncated": False,
        "termination": {
            "requested": False,
            "method": "",
            "escalated": False,
            "group_state": "gone",
            "group_uncertain": False,
            "pipes_eof": True,
        },
        "retry_count": 0,
    }


def test_agent_exec_schema_and_manual_validator_agree_on_valid_fixture() -> None:
    schema = agent_exec_result_schema()
    payload = _valid_payload()

    assert schema["properties"]["schema"]["const"] == AGENT_EXEC_RESULT_CONTRACT_VERSION
    assert schema["properties"]["exposed"]["properties"]["lines"]["maximum"] == 120
    result = validate_agent_exec_result(payload)
    assert result.ok is True
    assert result.errors == ()


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (lambda payload: payload.pop("raw"), "$.raw: required"),
        (lambda payload: payload.__setitem__("schema", "agent-exec-result/v2"), "$.schema"),
        (lambda payload: payload.__setitem__("run_id", "AX-bad"), "$.run_id"),
        (lambda payload: payload.__setitem__("status", "UNKNOWN"), "$.status"),
        (lambda payload: payload["exposed"].__setitem__("lines", 121), "$.exposed.lines"),
        (lambda payload: payload.__setitem__("retry_count", 1), "$.retry_count"),
        (lambda payload: payload.__setitem__("extra", True), "$.extra"),
    ],
)
def test_agent_exec_result_rejects_contract_drift(mutation, expected_error: str) -> None:
    payload = deepcopy(_valid_payload())
    mutation(payload)

    result = validate_agent_exec_result(payload)

    assert result.ok is False
    assert any(expected_error in error for error in result.errors)
