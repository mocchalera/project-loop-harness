from __future__ import annotations

import re
from typing import Any, Iterable, Pattern

from .agent_exec_validation import compile_agent_exec_redaction_patterns
from .errors import InvalidInputError
from .sensitive import SECRET_SIGNATURE_PATTERNS


REDACTED_SECRET = "[REDACTED_SECRET]"

SECRET_PATTERNS: tuple[Pattern[str], ...] = SECRET_SIGNATURE_PATTERNS
KEY_VALUE_SECRET = re.compile(
    r"\b(api[_-]?key|token|secret|password|private[_-]?key)\b"
    r"(\s*[:=]\s*)(['\"]?)([^'\"\s,}]{8,})(['\"]?)",
    re.IGNORECASE,
)


def compile_redaction_patterns(patterns: Iterable[str] = ()) -> tuple[Pattern[str], ...]:
    try:
        return compile_agent_exec_redaction_patterns(patterns)
    except re.error as exc:
        raise InvalidInputError(f"Invalid executor redaction pattern: {exc}") from exc


def redact_text(
    value: str,
    *,
    additional_patterns: Iterable[Pattern[str]] = (),
) -> tuple[str, bool]:
    redacted = value
    for pattern in (*SECRET_PATTERNS, *tuple(additional_patterns)):
        redacted = pattern.sub(REDACTED_SECRET, redacted)
    redacted = KEY_VALUE_SECRET.sub(_redact_key_value_secret, redacted)
    return redacted, redacted != value


def redact_bytes(
    value: bytes,
    *,
    additional_patterns: Iterable[Pattern[str]] = (),
) -> tuple[bytes, bool]:
    # latin-1 is a lossless byte-to-codepoint mapping. It lets the conservative
    # ASCII-shaped filters run without corrupting invalid UTF-8 or binary output.
    text = value.decode("latin-1")
    redacted, changed = redact_text(text, additional_patterns=additional_patterns)
    return redacted.encode("latin-1"), changed


def redact_value(
    value: Any,
    *,
    additional_patterns: Iterable[Pattern[str]] = (),
) -> tuple[Any, bool]:
    patterns = tuple(additional_patterns)
    if isinstance(value, dict):
        changed = False
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_secret_key(key) and item is not None:
                result[key] = REDACTED_SECRET
                changed = True
                continue
            result[key], item_changed = redact_value(item, additional_patterns=patterns)
            changed = changed or item_changed
        return result, changed
    if isinstance(value, list):
        changed = False
        result = []
        for item in value:
            redacted_item, item_changed = redact_value(item, additional_patterns=patterns)
            result.append(redacted_item)
            changed = changed or item_changed
        return result, changed
    if isinstance(value, str):
        return redact_text(value, additional_patterns=patterns)
    return value, False


def _is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(marker in normalized for marker in ("secret", "password", "apikey", "token", "privatekey"))


def _redact_key_value_secret(match: re.Match[str]) -> str:
    quote = match.group(3)
    closing_quote = match.group(5) if quote else ""
    return f"{match.group(1)}{match.group(2)}{quote}{REDACTED_SECRET}{closing_quote}"
