from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._profile_contract import load_strict_json, schema_resource, validate_schema


AGENT_OUTPUT_POLICY_CONTRACT_VERSION = "agent-output-policy/v1"
AGENT_OUTPUT_CLASSIFICATION_CONTRACT_VERSION = "agent-output-classification/v1"
AGENT_OUTPUT_CLASSIFICATIONS = frozenset(
    {"eligible", "negative", "unknown", "already_wrapped"}
)
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


def agent_output_policy_schema() -> dict[str, Any]:
    return schema_resource("agent-output-policy-v1.schema.json")


def agent_output_classification_schema() -> dict[str, Any]:
    return schema_resource("agent-output-classification-v1.schema.json")


def load_agent_output_policy(path: str | Path) -> Any:
    return load_strict_json(path)


def load_agent_output_classification(path: str | Path) -> Any:
    return load_strict_json(path)


def canonical_agent_output_policy_json(value: Mapping[str, Any]) -> str:
    return _canonical_json(value)


def canonical_agent_output_classification_json(value: Mapping[str, Any]) -> str:
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


def _canonical_json(value: Mapping[str, Any]) -> str:
    import json

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
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
