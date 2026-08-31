from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
import re
from typing import Any

from .contracts._profile_contract import loads_strict_json
from .contracts.agent_output import (
    AGENT_OUTPUT_CLASSIFICATION_CONTRACT_VERSION,
    validate_agent_output_classification,
    validate_agent_output_policy,
)
from .agent_exec_validation import (
    is_valid_agent_exec_env_name,
    is_valid_agent_exec_max_output_bytes,
    is_valid_agent_exec_redaction_pattern,
    is_valid_agent_exec_timeout,
    parse_agent_exec_integer,
)
from .resources import read_text_resource
from .path_safety import is_path_like, is_path_list_like, split_path_list_value, split_path_value
from .sensitive import (
    contains_secret_signature,
    is_option_shaped_key,
    is_sensitive_header_value,
    is_sensitive_key,
    is_sensitive_key_value,
    split_nested_sensitive_header,
    split_key_value,
)


CANONICAL_POLICY_RESOURCE = "templates/agent-output-budget/policy.json"
MAX_ARGV_ITEMS = 256
MAX_ARGV_ITEM_BYTES = 4_096
MAX_ARGV_TOTAL_BYTES = 8_192
MAX_ARGV_JSON_BYTES = 64 * 1024
RECOMMENDED_ARGV_PREFIX = ["pcl", "exec", "--"]

_REPORT_TOKEN = re.compile(r"(?i)(?:^|[-_.:/=])report(?:[-_.:/=]|$)")
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
_COMPLETE_OUTPUT_FLAGS = frozenset({"-h", "--help", "--version"})
_PYTEST_COMPLETE_OUTPUT_FLAGS = frozenset(
    {
        "--co",
        "--collect-only",
        "--collectonly",
        "--durations",
        "--report-chars",
        "--fixtures",
        "--fixtures-per-test",
        "--funcargs",
        "--markers",
        "--setup-only",
        "--setup-plan",
        "--setup-show",
        "--trace-config",
        "-V",
        "-r",
    }
)
_PYTEST_VALUE_OPTIONS = frozenset({"-k", "--keyword", "-m", "--markexpr"})
_PYTEST_REPORT_CHARS = frozenset("fFEsxXpPaAwN")
_PYTEST_SHORT_CLUSTER_FLAGS = frozenset({"q", "v", "s", "x", "f", "l"})
_GO_LIST_FLAGS = frozenset({"-list", "--list"})
_RUFF_COMPLETE_OUTPUT_OPTIONS = frozenset({"--output-format", "--output-file"})
_NON_INTERACTIVE_INSTALL_FLAG = "--no-input"
_PIP_COMMANDS = frozenset({"pip", "pip3"})
_PYTHON_COMMANDS = frozenset({"python", "python3"})
_MODE_SCRIPT_WORDS = frozenset({"watch", "server", "serve", "dev", "repl", "debug"})
_WRAPPED_EXEC_VALUE_OPTIONS = {
    "--timeout-seconds": "timeout_seconds",
    "--max-output-bytes": "max_output_bytes",
    "--redact-pattern": "redaction_pattern",
    "--allow-env": "env_name",
}
_WORD_UNSAFE_SHELL_MARKERS = frozenset({"function", "heredoc"})
_WORD_MARKER_BOUNDARY_CHARS = " \t\r\n;|&<>`"


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
    option_value_next = False
    selection_value_next = False
    for token in tokens:
        if redact_next:
            return True
        if option_value_next and is_sensitive_header_value(token):
            return True
        option_value_next = False
        if selection_value_next:
            selection_value_next = False
            if contains_secret_signature(token):
                return True
            continue
        if contains_secret_signature(token):
            return True
        if split_nested_sensitive_header(token) is not None:
            return True
        key_value = split_key_value(token)
        if key_value is not None:
            _key, _separator, value = key_value
            if is_sensitive_key_value(token) or contains_secret_signature(value):
                return True
        elif _is_selection_value_option(token):
            selection_value_next = token in _PYTEST_VALUE_OPTIONS
        elif is_option_shaped_key(token) and is_sensitive_key(token):
            redact_next = True
        elif is_option_shaped_key(token):
            option_value_next = True
    return redact_next


def _contains_absolute_path(tokens: Sequence[str]) -> bool:
    path_value_next = False
    selection_value_next = False
    for token in tokens:
        if selection_value_next:
            selection_value_next = False
            continue
        if path_value_next:
            path_value_next = False
            if is_path_like(token) or is_path_list_like(token):
                return True
        if (
            is_path_like(token)
            or split_path_value(token) is not None
            or split_path_list_value(token) is not None
        ):
            return True
        if _is_selection_value_option(token):
            selection_value_next = token in _PYTEST_VALUE_OPTIONS
        elif is_option_shaped_key(token):
            path_value_next = True
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
    for token in tokens:
        for marker in markers:
            if not isinstance(marker, str):
                continue
            if marker in _WORD_UNSAFE_SHELL_MARKERS:
                if _contains_word_shell_marker(token, marker):
                    return True
            elif marker == "&":
                if token == marker:
                    return True
            elif marker in token:
                return True
    return False


def _contains_word_shell_marker(token: str, marker: str) -> bool:
    if token == marker:
        return True
    escaped_marker = re.escape(marker)
    boundary_chars = re.escape(_WORD_MARKER_BOUNDARY_CHARS)
    return (
        re.search(
            rf"(?:^|[{boundary_chars}]){escaped_marker}"
            rf"(?:$|[{boundary_chars}(){{])",
            token,
        )
        is not None
    )


def _contains_shell_invocation(tokens: Sequence[str]) -> bool:
    command = tokens[0].lower()
    if command not in _SHELL_EXECUTABLES:
        return False
    if command in {"sh", "bash", "zsh", "fish", "pwsh", "cmd"}:
        return True
    return any(token in {"-c", "-e", "--command", "--eval"} for token in tokens[1:])


def _is_already_wrapped(tokens: Sequence[str]) -> bool:
    index = _wrapped_program_start(tokens)
    if index is None:
        return False

    while index < len(tokens) and tokens[index] != "exec":
        token = tokens[index]
        if token == "--json":
            index += 1
            continue
        if token == "--root":
            if index + 1 >= len(tokens) or not _valid_separated_option_value(tokens[index + 1]):
                return False
            index += 2
            continue
        if token.startswith("--root="):
            if not token[7:]:
                return False
            index += 1
            continue
        return False
    if index >= len(tokens):
        return False
    index += 1

    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1 < len(tokens) and bool(tokens[index + 1])
        if token == "--json":
            index += 1
            continue
        if token == "--root":
            if index + 1 >= len(tokens) or not _valid_separated_option_value(tokens[index + 1]):
                return False
            index += 2
            continue
        if token.startswith("--root="):
            if not token[7:]:
                return False
            index += 1
            continue
        next_index = _consume_wrapped_exec_option(tokens, index)
        if next_index is None:
            return False
        index = next_index
    return False


def _wrapped_program_start(tokens: Sequence[str]) -> int | None:
    if tokens and tokens[0] == "pcl":
        return 1
    if len(tokens) >= 3 and tuple(tokens[:2]) in (("python", "-m"), ("python3", "-m")):
        return 3 if tokens[2] == "pcl" else None
    return None


def _valid_separated_option_value(value: str) -> bool:
    return bool(value) and not value.startswith("-")


def _valid_wrapped_exec_value(value: str, value_kind: str) -> bool:
    if value == "--":
        return False
    if value_kind == "timeout_seconds":
        parsed = parse_agent_exec_integer(value)
        return parsed is not None and is_valid_agent_exec_timeout(parsed)
    if value_kind == "max_output_bytes":
        parsed = parse_agent_exec_integer(value)
        return parsed is not None and is_valid_agent_exec_max_output_bytes(parsed)
    if value_kind == "redaction_pattern":
        return is_valid_agent_exec_redaction_pattern(value)
    if value_kind == "env_name":
        return is_valid_agent_exec_env_name(value)
    return False


def _consume_wrapped_exec_option(tokens: Sequence[str], index: int) -> int | None:
    token = tokens[index]
    for option, value_kind in _WRAPPED_EXEC_VALUE_OPTIONS.items():
        if token == option:
            if index + 1 >= len(tokens) or tokens[index + 1] == "--":
                return None
            value = tokens[index + 1]
            if value_kind == "redaction_pattern" and not _valid_separated_option_value(value):
                return None
            return index + 2 if _valid_wrapped_exec_value(value, value_kind) else None
        prefix = f"{option}="
        if token.startswith(prefix):
            value = token[len(prefix) :]
            return index + 1 if _valid_wrapped_exec_value(value, value_kind) else None
    return None


def _negative_reason(tokens: Sequence[str], policy: Mapping[str, Any]) -> str | None:
    for rule in policy.get("negative_argv_rules", []):
        if _rule_matches(tokens, rule):
            return str(rule["reason_code"])
    if _contains_complete_output_request(tokens):
        return "complete_output"
    if _contains_report_output_request(tokens):
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


def _contains_report_output_request(tokens: Sequence[str]) -> bool:
    command = tokens[0]
    if _REPORT_TOKEN.search(command):
        return True
    if len(tokens) >= 3 and command.lower() in {"python", "python3"}:
        if tokens[1].lower() == "-m" and _REPORT_TOKEN.search(tokens[2]):
            return True
    if len(tokens) >= 3 and list(tokens[:2]) in (
        ["npm", "run"],
        ["pnpm", "run"],
        ["yarn", "run"],
    ):
        if _REPORT_TOKEN.search(tokens[2]):
            return True
    for token in tokens[1:]:
        key_value = split_key_value(token)
        key = key_value[0] if key_value is not None else token
        if is_option_shaped_key(key) and _REPORT_TOKEN.search(key):
            return True
    return False


def _contains_complete_output_request(tokens: Sequence[str]) -> bool:
    command = tokens[0].lower()
    if command == "mypy" and _contains_exact_option(
        tokens[1:], _COMPLETE_OUTPUT_FLAGS | frozenset({"-V"})
    ):
        return True
    if (
        len(tokens) >= 2
        and command == "ruff"
        and tokens[1].lower() == "check"
        and _contains_exact_option(tokens[2:], _RUFF_COMPLETE_OUTPUT_OPTIONS)
    ):
        return True
    if command in {"pytest", "python", "python3"}:
        pytest_start = 1 if command == "pytest" else 3
        if command != "pytest" and list(tokens[1:3]) != ["-m", "pytest"]:
            pytest_start = -1
        if pytest_start >= 0 and _contains_pytest_complete_output_request(tokens[pytest_start:]):
            return True
    if command not in {"pytest", "mypy"} and not (
        command in {"python", "python3"} and list(tokens[1:3]) == ["-m", "pytest"]
    ) and _contains_exact_option(tokens[1:], _COMPLETE_OUTPUT_FLAGS):
        return True
    if (
        len(tokens) >= 2
        and command == "go"
        and tokens[1].lower() == "test"
        and any(_option_key(token) in _GO_LIST_FLAGS for token in tokens[2:])
    ):
        return True
    if (
        len(tokens) >= 2
        and command == "npm"
        and tokens[1].lower() == "test"
        and any(_option_key(token) in {"--listtests", "--list-tests"} for token in tokens[2:])
    ):
        return True
    return (
        len(tokens) >= 2
        and command == "cargo"
        and tokens[1].lower() == "test"
        and any(_option_key(token) == "--list" for token in tokens[2:])
    )


def _contains_pytest_complete_output_request(tokens: Sequence[str]) -> bool:
    skip_selection_value = False
    flags = _PYTEST_COMPLETE_OUTPUT_FLAGS | _COMPLETE_OUTPUT_FLAGS
    for token in tokens:
        if skip_selection_value:
            skip_selection_value = False
            continue
        if token in _PYTEST_VALUE_OPTIONS:
            skip_selection_value = True
            continue
        if _is_selection_value_option(token):
            continue
        if _option_key(token) in flags or _is_pytest_short_presentation_option(token):
            return True
    return False


def _is_selection_value_option(token: str) -> bool:
    if token in _PYTEST_VALUE_OPTIONS:
        return True
    if token.startswith(("-k", "-m")) and not token.startswith("--") and len(token) > 2:
        return True
    return "=" in token and token.split("=", 1)[0].lower() in {"--keyword", "--markexpr"}


def _is_pytest_short_presentation_option(token: str) -> bool:
    if not token.startswith("-") or token.startswith("--") or len(token) < 2:
        return False
    body = token[1:]
    index = 0
    while index < len(body):
        option = body[index]
        if option == "h":
            return True
        if option == "V":
            return True
        if option == "r":
            return index == len(body) - 1 or all(
                character in _PYTEST_REPORT_CHARS for character in body[index + 1 :]
            )
        if option not in _PYTEST_SHORT_CLUSTER_FLAGS:
            return False
        index += 1
    return False


def _contains_exact_option(
    tokens: Sequence[str],
    flags: frozenset[str],
    *,
    value_options: frozenset[str] = frozenset(),
) -> bool:
    skip_next = False
    for token in tokens:
        option = _option_key(token)
        if skip_next:
            skip_next = False
            continue
        if option in flags:
            return True
        if option in value_options and "=" not in token:
            skip_next = True
    return False


def _option_key(token: str) -> str:
    key = token.split("=", 1)[0]
    return key if key.startswith("-") and not key.startswith("--") else key.lower()


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
    option_start = 2 if _is_pip_install(tokens) else 4
    if not _has_non_interactive_pip_option(tokens[option_start:]):
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


def _has_non_interactive_pip_option(tokens: Sequence[str]) -> bool:
    for token in tokens:
        if token == "--":
            return False
        if token.lower() == _NON_INTERACTIVE_INSTALL_FLAG:
            return True
    return False


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
