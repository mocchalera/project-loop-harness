from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ._profile_contract import load_strict_json, schema_resource, validate_schema


AGENT_OUTPUT_POLICY_CONTRACT_VERSION = "agent-output-policy/v1"
AGENT_OUTPUT_CLASSIFICATION_CONTRACT_VERSION = "agent-output-classification/v1"
AGENT_OUTPUT_AUDIT_CONTRACT_VERSION = "agent-output-audit/v1"
AGENT_OUTPUT_COMMAND_SHAPE_CONTRACT_VERSION = "agent-output-command-shape/v1"
AGENT_OUTPUT_CLASSIFICATIONS = frozenset(
    {"eligible", "negative", "unknown", "already_wrapped"}
)
AGENT_OUTPUT_AUDIT_FIELD_ALLOWLIST = frozenset(
    {
        "schema",
        "observed_at",
        "host",
        "event",
        "tool",
        "classification",
        "reason_code",
        "already_wrapped",
        "action",
        "command_shape_sha256",
        "may_rewrite",
    }
)
AGENT_OUTPUT_AUDIT_HOST_PROTOCOLS = MappingProxyType(
    {
        "claude-code": ("PreToolUse", "Bash"),
        "gemini-cli": ("BeforeTool", "run_shell_command"),
    }
)
_AGENT_OUTPUT_AUDIT_ELIGIBLE_REASONS = frozenset(
    {
        "cargo_build",
        "cargo_clippy",
        "cargo_test",
        "eslint",
        "go_build",
        "go_install",
        "go_test",
        "go_test_all_packages",
        "mypy",
        "npm_run_build_script",
        "npm_run_lint_script",
        "npm_run_test_script",
        "npm_run_test_unit_script",
        "npm_run_typecheck_script",
        "npm_run_verify_command",
        "npm_run_verify_script",
        "npm_test",
        "pip3_install_non_interactive",
        "pip_install_non_interactive",
        "pnpm_test",
        "pyright",
        "pytest_direct",
        "python3_pip_install_non_interactive",
        "python_module_build",
        "python_module_pytest",
        "python_pip_install_non_interactive",
        "ruff_check",
        "tsc_no_emit",
        "yarn_test",
    }
)
_AGENT_OUTPUT_AUDIT_NEGATIVE_REASONS = frozenset(
    {
        "cargo_install",
        "cargo_watch",
        "complete_output",
        "coverage_output_artifact",
        "development_server",
        "file_read_cat",
        "file_read_head",
        "file_read_sed",
        "file_read_tail",
        "git_diff",
        "git_log",
        "git_show",
        "interactive_command",
        "interactive_installer",
        "interactive_or_watch_mode",
        "npm_install",
        "output_is_artifact",
        "pip_install",
        "pnpm_install",
        "python_http_server",
        "python_pip_install",
        "report_output_artifact",
        "search_find",
        "search_grep",
        "search_rg",
        "serve_command",
        "server_command",
        "streaming_command",
        "streaming_tail",
        "watch_command",
        "watch_or_server_script",
        "yarn_install",
    }
)
_AGENT_OUTPUT_AUDIT_UNKNOWN_REASONS = frozenset(
    {
        "absolute_path_argv",
        "argv_item_too_large",
        "argv_json_too_large",
        "argv_too_large",
        "empty_argv",
        "host_command_string_not_tokenized",
        "invalid_argv",
        "invalid_argv_json",
        "invalid_policy",
        "malformed_argv_json",
        "malformed_quoting",
        "secret_shaped_argv",
        "shell_invocation",
        "unsafe_shell_expression",
        "unsupported_argv",
    }
)
AGENT_OUTPUT_AUDIT_REASON_CLASSIFICATIONS = MappingProxyType(
    {
        **dict.fromkeys(_AGENT_OUTPUT_AUDIT_ELIGIBLE_REASONS, "eligible"),
        **dict.fromkeys(_AGENT_OUTPUT_AUDIT_NEGATIVE_REASONS, "negative"),
        **dict.fromkeys(_AGENT_OUTPUT_AUDIT_UNKNOWN_REASONS, "unknown"),
        "already_wrapped_pcl_exec": "already_wrapped",
    }
)
AGENT_OUTPUT_AUDIT_REASON_CODES = frozenset(AGENT_OUTPUT_AUDIT_REASON_CLASSIFICATIONS)
AGENT_OUTPUT_REASON_CODE_PATTERN = r"^[a-z0-9][a-z0-9_.-]*$"
CANONICAL_UNSAFE_SHELL_MARKERS = (
    "|",
    ">",
    ">>",
    "<",
    "$(",
    "`",
    "&&",
    "||",
    ";",
    "&",
    "\n",
    "\r",
    "heredoc",
    "function",
)


@dataclass(frozen=True)
class AgentOutputPolicyValidationResult:
    contract_type: str
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "errors": list(self.errors),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class AgentOutputClassificationValidationResult:
    contract_type: str
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "errors": list(self.errors),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class AgentOutputAuditValidationResult:
    contract_type: str
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def agent_output_policy_schema() -> dict[str, Any]:
    return schema_resource("agent-output-policy-v1.schema.json")


def agent_output_classification_schema() -> dict[str, Any]:
    return schema_resource("agent-output-classification-v1.schema.json")


def agent_output_audit_schema() -> dict[str, Any]:
    return schema_resource("agent-output-audit-v1.schema.json")


def load_agent_output_policy(path: str | Path) -> Any:
    return load_strict_json(path)


def load_agent_output_classification(path: str | Path) -> Any:
    return load_strict_json(path)


def load_agent_output_audit(path: str | Path) -> Any:
    return load_strict_json(path)


def canonical_agent_output_policy_json(value: Mapping[str, Any]) -> str:
    return _canonical_json(value)


def canonical_agent_output_classification_json(value: Mapping[str, Any]) -> str:
    return _canonical_json(value)


def canonical_agent_output_audit_json(value: Mapping[str, Any]) -> str:
    return _canonical_json(value)


def validate_agent_output_policy(value: Any) -> AgentOutputPolicyValidationResult:
    errors = validate_schema(value, agent_output_policy_schema())
    if isinstance(value, dict):
        _validate_required_unsafe_shell_markers(value, errors)
        _validate_rule_shapes(value, errors)
        _validate_unique_rule_reasons(value, errors)
    return AgentOutputPolicyValidationResult(
        AGENT_OUTPUT_POLICY_CONTRACT_VERSION,
        tuple(errors),
    )


def validate_agent_output_classification(
    value: Any,
) -> AgentOutputClassificationValidationResult:
    errors = validate_schema(value, agent_output_classification_schema())
    if isinstance(value, dict):
        if value.get("may_rewrite") is not False:
            errors.append("$.may_rewrite: must be false")
        classification = value.get("classification")
        prefix = value.get("recommended_argv_prefix")
        if classification == "eligible" and prefix != ["pcl", "exec", "--"]:
            errors.append(
                "$.recommended_argv_prefix: eligible commands require ['pcl', 'exec', '--']"
            )
        if classification != "eligible" and prefix != []:
            errors.append("$.recommended_argv_prefix: non-eligible commands require an empty array")
    return AgentOutputClassificationValidationResult(
        AGENT_OUTPUT_CLASSIFICATION_CONTRACT_VERSION,
        tuple(errors),
    )


def validate_agent_output_audit(value: Any) -> AgentOutputAuditValidationResult:
    errors = validate_schema(value, agent_output_audit_schema())
    if isinstance(value, dict):
        host = value.get("host")
        protocol = AGENT_OUTPUT_AUDIT_HOST_PROTOCOLS.get(host) if isinstance(host, str) else None
        if protocol is not None:
            expected_event, expected_tool = protocol
            if value.get("event") != expected_event:
                errors.append(
                    f"$.event: {host} observations require {expected_event!r}"
                )
            if value.get("tool") != expected_tool:
                errors.append(f"$.tool: {host} observations require {expected_tool!r}")
        classification = value.get("classification")
        reason_code = value.get("reason_code")
        expected_classification = (
            AGENT_OUTPUT_AUDIT_REASON_CLASSIFICATIONS.get(reason_code)
            if isinstance(reason_code, str)
            else None
        )
        if expected_classification is not None and classification != expected_classification:
            errors.append(
                "$.classification: must match the frozen classification for the reason code"
            )
        already_wrapped = value.get("already_wrapped")
        if isinstance(classification, str) and isinstance(already_wrapped, bool):
            expected_already_wrapped = classification == "already_wrapped"
            if already_wrapped is not expected_already_wrapped:
                errors.append(
                    "$.already_wrapped: must be true exactly when classification is "
                    "'already_wrapped'"
                )
        if _can_compute_command_shape(value):
            expected_digest = agent_output_command_shape_sha256(
                classification=str(value["classification"]),
                reason_code=str(value["reason_code"]),
                already_wrapped=bool(value["already_wrapped"]),
            )
            if value.get("command_shape_sha256") != expected_digest:
                errors.append(
                    "$.command_shape_sha256: must match the privacy-reduced classification shape"
                )
    return AgentOutputAuditValidationResult(
        AGENT_OUTPUT_AUDIT_CONTRACT_VERSION,
        tuple(errors),
    )


def agent_output_command_shape_sha256(
    *,
    classification: str,
    reason_code: str,
    already_wrapped: bool,
) -> str:
    """Hash only the bounded classification category, never argv or host input."""

    shape = {
        "schema": AGENT_OUTPUT_COMMAND_SHAPE_CONTRACT_VERSION,
        "classification": classification,
        "reason_code": reason_code,
        "already_wrapped": already_wrapped,
    }
    digest = hashlib.sha256(_canonical_json(shape).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_agent_output_audit_record(
    *,
    observed_at: str,
    host: str,
    event: str,
    tool: str,
    classification: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a validated audit-only record without accepting raw command data."""

    classification_validation = validate_agent_output_classification(classification)
    if not classification_validation.ok:
        raise ValueError("classification must satisfy agent-output-classification/v1")
    classification_name = str(classification["classification"])
    reason_code = str(classification["reason_code"])
    already_wrapped = classification_name == "already_wrapped"
    record = {
        "schema": AGENT_OUTPUT_AUDIT_CONTRACT_VERSION,
        "observed_at": observed_at,
        "host": host,
        "event": event,
        "tool": tool,
        "classification": classification_name,
        "reason_code": reason_code,
        "already_wrapped": already_wrapped,
        "action": "observed_only",
        "command_shape_sha256": agent_output_command_shape_sha256(
            classification=classification_name,
            reason_code=reason_code,
            already_wrapped=already_wrapped,
        ),
        "may_rewrite": False,
    }
    validation = validate_agent_output_audit(record)
    if not validation.ok:
        raise ValueError("audit fields must satisfy agent-output-audit/v1")
    return record


def _canonical_json(value: Mapping[str, Any]) -> str:
    import json

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _can_compute_command_shape(value: Mapping[str, Any]) -> bool:
    return (
        isinstance(value.get("classification"), str)
        and isinstance(value.get("reason_code"), str)
        and isinstance(value.get("already_wrapped"), bool)
    )


def _validate_unique_rule_reasons(value: Mapping[str, Any], errors: list[str]) -> None:
    seen: dict[str, str] = {}
    for section in ("eligible_argv_rules", "negative_argv_rules"):
        rules = value.get(section)
        if not isinstance(rules, list):
            continue
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            reason = rule.get("reason_code")
            if not isinstance(reason, str):
                continue
            previous = seen.get(reason)
            if previous is not None:
                errors.append(
                    f"$.{section}[{index}].reason_code: duplicate reason_code {reason!r}"
                )
            else:
                seen[reason] = f"$.{section}[{index}]"


def _validate_required_unsafe_shell_markers(
    value: Mapping[str, Any], errors: list[str]
) -> None:
    markers = value.get("unsafe_shell_markers")
    if not isinstance(markers, list):
        errors.append("$.unsafe_shell_markers: must include the canonical marker set")
        return
    for marker in CANONICAL_UNSAFE_SHELL_MARKERS:
        if marker not in markers:
            errors.append(f"$.unsafe_shell_markers: missing required marker {marker!r}")


def _validate_rule_shapes(value: Mapping[str, Any], errors: list[str]) -> None:
    expected = {"reason_code", "argv_prefix"}
    for section in ("eligible_argv_rules", "negative_argv_rules"):
        rules = value.get(section)
        if not isinstance(rules, list):
            continue
        for index, rule in enumerate(rules):
            path = f"$.{section}[{index}]"
            if not isinstance(rule, dict):
                continue
            for field in sorted(expected - set(rule)):
                errors.append(f"{path}.{field}: is required")
            for field in sorted(set(rule) - expected):
                errors.append(f"{path}.{field}: additional property is not allowed")
