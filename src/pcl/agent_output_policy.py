from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
import os
import re
from typing import Any

from .contracts._profile_contract import loads_strict_json
from .contracts.agent_output import (
    AGENT_OUTPUT_CLASSIFICATION_CONTRACT_VERSION,
    validate_agent_output_classification,
    validate_agent_output_policy,
)
from .resources import read_text_resource
from .sensitive import is_sensitive_key


CANONICAL_POLICY_RESOURCE = "templates/agent-output-budget/policy.json"
MAX_ARGV_ITEMS = 256
MAX_ARGV_ITEM_BYTES = 4_096
MAX_ARGV_TOTAL_BYTES = 8_192
MAX_ARGV_JSON_BYTES = 64 * 1024
RECOMMENDED_ARGV_PREFIX = ["pcl", "exec", "--"]

_ABSOLUTE_WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_SECRET_VALUE = re.compile(
    r"(?i)(?:sk-[a-z0-9]{12,}|gh[pousr]_[a-z0-9]{12,}|xox[baprs]-[a-z0-9-]{12,}|"
    r"bearer\s+[a-z0-9._-]{12,}|-----begin [a-z ]+ key-----)"
)
_REPORT_TOKEN = re.compile(r"(?i)(?:^|[-_.:/])report(?:[-_.:/]|$)")
_ARTIFACT_MARKERS = frozenset(
    {
        "--output-is-artifact",
        "output_is_artifact=true",
        "--report-file",
        "--junitxml",
        "--junit-xml",
    }
)
_ARTIFACT_MARKER_PREFIXES = (
    "--output-is-artifact=",
    "output_is_artifact=",
    "--report-file=",
    "--junitxml=",
    "--junit-xml=",
)
_SHELL_EXECUTABLES = frozenset({"sh", "bash", "zsh", "fish", "pwsh", "cmd", "python", "python3", "node"})
_INTERACTIVE_EXECUTABLES = frozenset({"bash", "zsh", "fish", "pwsh", "cmd", "repl", "interactive"})
_INTERACTIVE_FLAGS = frozenset(
    {
        "--interactive",
        "--watch",
        "--watchall",
        "--watch-all",
        "--watch_all",
        "--watch-mode",
        "--server",
        "--serve",
        "--dev",
        "--repl",
        "--follow",
        "--stream",
        "--reload",
        "--live",
        "--live-reload",
        "--pdb",
        "--pdbcls",
        "--trace",
        "--debug",
        "--debug-brk",
        "--debug-mode",
        "--debug-port",
        "--inspect",
        "--inspect-brk",
        "--inspect-port",
    }
)
_STREAM_FLAGS = frozenset({"--follow", "--stream"})
_INSTALLER_COMMANDS = frozenset({"init", "create", "new"})
_COMPLETE_OUTPUT_FLAGS = frozenset({"-h", "--help", "-V", "--version"})
_PYTEST_COMPLETE_OUTPUT_FLAGS = frozenset({"--collect-only", "--collectonly"})
_GO_LIST_FLAGS = frozenset({"-list", "--list"})
_NON_INTERACTIVE_INSTALL_FLAG = "--no-input"
_PIP_COMMANDS = frozenset({"pip", "pip3"})
_PYTHON_COMMANDS = frozenset({"python", "python3"})
_MODE_SCRIPT_WORDS = frozenset({"watch", "server", "serve", "dev", "repl", "debug"})


def _load_canonical_policy() -> dict[str, Any]:
    try:
        value = loads_strict_json(read_text_resource(CANONICAL_POLICY_RESOURCE))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("The packaged agent-output policy cannot be loaded.") from exc
    validation = validate_agent_output_policy(value)
    if not validation.ok:
        raise RuntimeError("The packaged agent-output policy is invalid.")
    return value


CANONICAL_AGENT_OUTPUT_POLICY = _load_canonical_policy()


def canonical_agent_output_policy() -> dict[str, Any]:
    """Return an isolated copy of the one packaged policy source."""

    return deepcopy(CANONICAL_AGENT_OUTPUT_POLICY)


def load_canonical_agent_output_policy() -> dict[str, Any]:
    return canonical_agent_output_policy()


def classify_agent_output_argv(
    argv: object,
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify an already-tokenized argv without executing or rewriting it."""

    active_policy = CANONICAL_AGENT_OUTPUT_POLICY if policy is None else policy
    if not validate_agent_output_policy(active_policy).ok:
        return _classification("unknown", "invalid_policy")

    checked = _bounded_argv(argv)
    if checked is None:
        return _classification("unknown", "invalid_argv")
    if isinstance(checked, dict):
        return _classification("unknown", checked["reason_code"])
    tokens = checked
    if _contains_secret_shape(tokens):
        return _classification("unknown", "secret_shaped_argv")
    if _contains_absolute_path(tokens):
        return _classification("unknown", "absolute_path_argv")
    if _contains_malformed_quoting(tokens):
        return _classification("unknown", "malformed_quoting")
    if _contains_unsafe_shell_marker(tokens, active_policy):
        return _classification("unknown", "unsafe_shell_expression")
    if _contains_shell_invocation(tokens):
        return _classification("unknown", "shell_invocation")
    if _is_already_wrapped(tokens):
        return _classification("already_wrapped", "already_wrapped_pcl_exec")

    negative_reason = _negative_reason(tokens, active_policy)
    if negative_reason:
        return _classification("negative", negative_reason)

    eligible_reason = _eligible_reason(tokens, active_policy)
    if eligible_reason:
        return _classification("eligible", eligible_reason)
    return _classification("unknown", "unsupported_argv")


def classify_agent_output_command(command: object) -> dict[str, Any]:
    """Observe a host command conservatively; strings are never shell-parsed."""

    if isinstance(command, str):
        return _classification("unknown", "host_command_string_not_tokenized")
    return classify_agent_output_argv(command)


def classify_agent_output_argv_json(value: object) -> dict[str, Any]:
    """Decode only a bounded JSON argv array, returning a non-leaking result."""

    if not isinstance(value, str):
        return _classification("unknown", "invalid_argv_json")
    if len(value.encode("utf-8", errors="replace")) > MAX_ARGV_JSON_BYTES:
        return _classification("unknown", "argv_json_too_large")
    try:
        parsed = loads_strict_json(value)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return _classification("unknown", "malformed_argv_json")
    return classify_agent_output_argv(parsed)


def _classification(classification: str, reason_code: str) -> dict[str, Any]:
    payload = {
        "schema": AGENT_OUTPUT_CLASSIFICATION_CONTRACT_VERSION,
        "classification": classification,
        "reason_code": reason_code,
        "recommended_argv_prefix": (
            list(RECOMMENDED_ARGV_PREFIX) if classification == "eligible" else []
        ),
        "may_rewrite": False,
    }
    validation = validate_agent_output_classification(payload)
    if not validation.ok:
        raise RuntimeError("invalid internal agent-output classification")
    return payload


def _bounded_argv(argv: object) -> list[str] | dict[str, str] | None:
    if not isinstance(argv, (list, tuple)):
        return None
    if not argv:
        return {"reason_code": "empty_argv"}
    if len(argv) > MAX_ARGV_ITEMS:
        return {"reason_code": "argv_too_large"}
    tokens: list[str] = []
    total_bytes = 0
    for item in argv:
        if not isinstance(item, str) or "\x00" in item:
            return {"reason_code": "invalid_argv"}
        try:
            item_bytes = len(item.encode("utf-8"))
        except UnicodeEncodeError:
            return {"reason_code": "invalid_argv"}
        if item_bytes > MAX_ARGV_ITEM_BYTES:
            return {"reason_code": "argv_item_too_large"}
        total_bytes += item_bytes + 1
        if total_bytes > MAX_ARGV_TOTAL_BYTES:
            return {"reason_code": "argv_too_large"}
        tokens.append(item)
    return tokens


def _contains_secret_shape(tokens: Sequence[str]) -> bool:
    redact_next = False
    for token in tokens:
        if redact_next:
            return True
        if is_sensitive_key(token):
            redact_next = True
            continue
        if _SECRET_VALUE.search(token):
            return True
        if "=" in token:
            key, value = token.split("=", 1)
            if is_sensitive_key(key) or _SECRET_VALUE.search(value):
                return True
        if token.lower().startswith(("authorization:", "proxy-authorization:")):
            return True
    return redact_next


def _contains_absolute_path(tokens: Sequence[str]) -> bool:
    for token in tokens:
        if token.startswith(("~/", "~\\")) or os.path.isabs(token) or _ABSOLUTE_WINDOWS_PATH.match(token):
            return True
        if "=" in token:
            _key, value = token.split("=", 1)
            if value.startswith(("~/", "~\\")) or os.path.isabs(value) or _ABSOLUTE_WINDOWS_PATH.match(value):
                return True
    return False


def _contains_malformed_quoting(tokens: Sequence[str]) -> bool:
    for token in tokens:
        single = False
        double = False
        escaped = False
        for char in token:
            if escaped:
                escaped = False
            elif char == "\\" and not single:
                escaped = True
            elif char == "'" and not double:
                single = not single
            elif char == '"' and not single:
                double = not double
        if single or double or escaped:
            return True
    return False


def _contains_unsafe_shell_marker(
    tokens: Sequence[str],
    policy: Mapping[str, Any],
) -> bool:
    markers = policy.get("unsafe_shell_markers")
    if not isinstance(markers, list):
        return True
    return any(marker in token for token in tokens for marker in markers if isinstance(marker, str))


def _contains_shell_invocation(tokens: Sequence[str]) -> bool:
    command = tokens[0].lower()
    if command not in _SHELL_EXECUTABLES:
        return False
    if command in {"sh", "bash", "zsh", "fish", "pwsh", "cmd"}:
        return True
    return any(token in {"-c", "-e", "--command", "--eval"} for token in tokens[1:])


def _is_already_wrapped(tokens: Sequence[str]) -> bool:
    prefixes = (
        ("pcl", "exec", "--"),
        ("pcl", "--json", "exec", "--"),
        ("python", "-m", "pcl", "exec", "--"),
    )
    return any(len(tokens) > len(prefix) and tuple(tokens[: len(prefix)]) == prefix for prefix in prefixes)


def _negative_reason(tokens: Sequence[str], policy: Mapping[str, Any]) -> str | None:
    for rule in policy.get("negative_argv_rules", []):
        if _rule_matches(tokens, rule):
            return str(rule["reason_code"])
    if _contains_complete_output_request(tokens):
        return "complete_output"
    if any(_REPORT_TOKEN.search(token) for token in tokens):
        return "report_output_artifact"
    if any(_is_artifact_marker(token) for token in tokens):
        return "output_is_artifact"
    command = tokens[0].lower()
    if command in _INTERACTIVE_EXECUTABLES:
        return "interactive_command"
    if any(_is_enabled_mode_flag(token) for token in tokens[1:]):
        return "interactive_or_watch_mode"
    if command in {"tail", "less", "more", "logs", "journalctl"} and any(
        token.lower() in _STREAM_FLAGS or token == "-f" for token in tokens[1:]
    ):
        return "streaming_command"
    if command == "docker" and len(tokens) >= 2 and tokens[1].lower() == "logs" and any(
        token.lower() in _STREAM_FLAGS or token == "-f" for token in tokens[2:]
    ):
        return "streaming_command"
    if len(tokens) >= 3 and tokens[:2] in (["npm", "run"], ["pnpm", "run"], ["yarn", "run"]):
        if _script_has_mode_token(tokens[2]):
            return "watch_or_server_script"
    if _is_pip_install(tokens) and not _is_non_interactive_pip_install(tokens):
        return "pip_install"
    if _is_python_pip_install(tokens) and not _is_non_interactive_pip_install(tokens):
        return "python_pip_install"
    if command in {"npm", "pnpm", "yarn"} and len(tokens) >= 2 and tokens[1].lower() in _INSTALLER_COMMANDS:
        return "interactive_installer"
    return None


def _is_artifact_marker(token: str) -> bool:
    lowered = token.lower()
    return lowered in _ARTIFACT_MARKERS or any(
        lowered.startswith(prefix) for prefix in _ARTIFACT_MARKER_PREFIXES
    )


def _script_has_mode_token(script_name: str) -> bool:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", script_name)
    return any(
        part in _MODE_SCRIPT_WORDS
        for part in re.split(r"[-_.:]+", separated.lower())
        if part
    )


def _contains_complete_output_request(tokens: Sequence[str]) -> bool:
    if any(_option_key(token) in _COMPLETE_OUTPUT_FLAGS for token in tokens[1:]):
        return True
    command = tokens[0].lower()
    if command in {"pytest", "python", "python3"}:
        pytest_start = 1 if command == "pytest" else 3
        if command != "pytest" and list(tokens[1:3]) != ["-m", "pytest"]:
            pytest_start = -1
        if pytest_start >= 0 and any(
            _option_key(token) in _PYTEST_COMPLETE_OUTPUT_FLAGS
            for token in tokens[pytest_start:]
        ):
            return True
    return (
        len(tokens) >= 2
        and command == "go"
        and tokens[1].lower() == "test"
        and any(_option_key(token) in _GO_LIST_FLAGS for token in tokens[2:])
    )


def _option_key(token: str) -> str:
    return token.lower().split("=", 1)[0]


def _is_enabled_mode_flag(token: str) -> bool:
    key = _option_key(token)
    if key not in _INTERACTIVE_FLAGS:
        return False
    if "=" not in token:
        return True
    return token.split("=", 1)[1].lower() not in {"0", "false", "no", "off"}


def _is_pip_install(tokens: Sequence[str]) -> bool:
    return len(tokens) >= 2 and tokens[0].lower() in _PIP_COMMANDS and tokens[1].lower() == "install"


def _is_python_pip_install(tokens: Sequence[str]) -> bool:
    return (
        len(tokens) >= 4
        and tokens[0].lower() in _PYTHON_COMMANDS
        and list(tokens[1:4]) == ["-m", "pip", "install"]
    )


def _is_non_interactive_pip_install(tokens: Sequence[str]) -> bool:
    return _non_interactive_pip_install_reason(tokens) is not None


def _non_interactive_pip_install_reason(tokens: Sequence[str]) -> str | None:
    if not (_is_pip_install(tokens) or _is_python_pip_install(tokens)):
        return None
    if not any(token.lower() == _NON_INTERACTIVE_INSTALL_FLAG for token in tokens[2:]):
        return None
    if _is_pip_install(tokens):
        return (
            "pip3_install_non_interactive"
            if tokens[0].lower() == "pip3"
            else "pip_install_non_interactive"
        )
    return (
        "python3_pip_install_non_interactive"
        if tokens[0].lower() == "python3"
        else "python_pip_install_non_interactive"
    )


def _eligible_reason(tokens: Sequence[str], policy: Mapping[str, Any]) -> str | None:
    for rule in policy.get("eligible_argv_rules", []):
        if _rule_matches(tokens, rule):
            return str(rule["reason_code"])
    non_interactive_reason = _non_interactive_pip_install_reason(tokens)
    if non_interactive_reason:
        return non_interactive_reason
    return None


def _rule_matches(tokens: Sequence[str], rule: object) -> bool:
    if not isinstance(rule, dict):
        return False
    prefix = rule.get("argv_prefix")
    return (
        isinstance(prefix, list)
        and bool(prefix)
        and len(tokens) >= len(prefix)
        and all(tokens[index] == item for index, item in enumerate(prefix))
    )
