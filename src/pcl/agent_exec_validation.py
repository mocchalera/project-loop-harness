from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Pattern


AGENT_EXEC_MIN_TIMEOUT_SECONDS = 1
AGENT_EXEC_MIN_OUTPUT_BYTES = 1
AGENT_EXEC_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_AGENT_EXEC_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def parse_agent_exec_integer(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def is_valid_agent_exec_timeout(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= AGENT_EXEC_MIN_TIMEOUT_SECONDS
    )


def is_valid_agent_exec_max_output_bytes(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and AGENT_EXEC_MIN_OUTPUT_BYTES <= value <= AGENT_EXEC_MAX_OUTPUT_BYTES
    )


def compile_agent_exec_redaction_patterns(
    patterns: Iterable[str],
) -> tuple[Pattern[str], ...]:
    return tuple(re.compile(pattern) for pattern in patterns)


def is_valid_agent_exec_redaction_pattern(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        compile_agent_exec_redaction_patterns((value,))
    except (re.error, TypeError):
        return False
    return True


def is_valid_agent_exec_env_name(value: object) -> bool:
    return isinstance(value, str) and _AGENT_EXEC_ENV_NAME.fullmatch(value) is not None


def are_valid_agent_exec_env_names(values: Iterable[object]) -> bool:
    return all(is_valid_agent_exec_env_name(value) for value in values)
