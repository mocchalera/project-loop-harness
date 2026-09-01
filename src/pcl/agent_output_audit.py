from __future__ import annotations

from pcl.agent_output_policy import classify_agent_output_command
from pcl.contracts.agent_output import (
    AGENT_OUTPUT_AUDIT_HOST_PROTOCOLS,
    build_agent_output_audit_record,
)


def normalize_agent_output_audit_event(
    *,
    host: object,
    observed_at: object,
    event: object,
) -> dict[str, object]:
    """Normalize one synthetic host event without parsing or retaining its command."""

    if not isinstance(host, str):
        raise ValueError("host must be a supported string")
    protocol = AGENT_OUTPUT_AUDIT_HOST_PROTOCOLS.get(host)
    if protocol is None:
        raise ValueError("unsupported agent-output audit host")
    if not isinstance(event, dict):
        raise ValueError("host event must be a JSON object")

    expected_event, expected_tool = protocol
    if (
        event.get("hook_event_name") != expected_event
        or event.get("tool_name") != expected_tool
    ):
        raise ValueError("host event identity does not match the accepted audit protocol")

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        raise ValueError("tool_input must be a JSON object")
    command = tool_input.get("command")
    if not isinstance(command, str):
        raise ValueError("tool_input.command must be a string")

    classification = classify_agent_output_command(command)
    return build_agent_output_audit_record(
        observed_at=observed_at,
        host=host,
        event=expected_event,
        tool=expected_tool,
        classification=classification,
    )
