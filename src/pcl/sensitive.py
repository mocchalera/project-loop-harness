from __future__ import annotations

import re


_KEY_COMPONENT = re.compile(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+")
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SUPPORTED_KEY_VALUE_SEPARATORS = ("=", ":")
_SENSITIVE_HEADER_KEYS = frozenset({"authorization", "proxy-authorization"})
_SENSITIVE_KEY_WORDS = frozenset(
    {
        "auth",
        "authorization",
        "bearer",
        "credential",
        "credentials",
        "pass",
        "passwd",
        "password",
        "passphrase",
        "secret",
        "token",
    }
)
_SENSITIVE_COMPOUND_KEYS = frozenset(
    {
        "accesskey",
        "apikey",
        "authkey",
        "clientkey",
        "clientsecret",
        "encryptionkey",
        "privatekey",
        "secretkey",
        "signingkey",
        "sshkey",
    }
)
_KEY_CONTEXT_WORDS = frozenset(
    {"access", "api", "auth", "client", "encryption", "private", "secret", "signing", "ssh"}
)


def is_option_shaped_key(value: str) -> bool:
    """Return whether a token has the shape of an option key."""

    if not isinstance(value, str):
        return False
    candidate = value.strip()
    return bool(candidate and candidate.startswith("-") and candidate.strip("-") and not any(
        separator in candidate for separator in SUPPORTED_KEY_VALUE_SEPARATORS
    ))


def is_env_key_shaped(value: str) -> bool:
    """Return whether a token has a conventional environment-key shape."""

    if not isinstance(value, str) or _ENV_KEY.fullmatch(value) is None:
        return False
    return "_" in value or any(char.isupper() for char in value)


def split_key_value(value: str) -> tuple[str, str, str] | None:
    """Split a supported key/value token at its first separator."""

    if not isinstance(value, str):
        return None
    separators = [
        (index, separator)
        for separator in SUPPORTED_KEY_VALUE_SEPARATORS
        if (index := value.find(separator)) > 0
    ]
    if not separators:
        return None
    index, separator = min(separators)
    return value[:index], separator, value[index + 1 :]


def is_sensitive_header_key(value: str) -> bool:
    """Return whether a token is a sensitive authorization header key."""

    return isinstance(value, str) and value.strip().lower() in _SENSITIVE_HEADER_KEYS


def is_sensitive_header_value(value: str) -> bool:
    """Return whether a value starts with a sensitive authorization header."""

    key_value = split_key_value(value)
    if key_value is None or not is_sensitive_header_key(key_value[0]):
        return False
    _key, separator, remainder = key_value
    return not (separator == ":" and remainder.startswith("//"))


def split_nested_sensitive_header(value: str) -> tuple[str, str, str] | None:
    """Split an option token whose value starts with a sensitive header."""

    outer = split_key_value(value)
    if outer is None or not is_option_shaped_key(outer[0]):
        return None
    if not is_sensitive_header_value(outer[2]):
        return None
    return outer


def is_sensitive_key(key: str) -> bool:
    """Return whether an argv or mapping key is shaped like a secret name."""

    if not isinstance(key, str):
        return False
    candidate = key.strip()
    if is_option_shaped_key(candidate):
        candidate = candidate.lstrip("-")
    elif not is_env_key_shaped(candidate):
        return False
    if not candidate:
        return False
    components = tuple(
        item.lower()
        for segment in re.split(r"[^A-Za-z0-9]+", candidate)
        for item in _KEY_COMPONENT.findall(segment)
    )
    if not components:
        return False
    compact = "".join(components)
    if compact in _SENSITIVE_COMPOUND_KEYS:
        return True
    if any(item in _SENSITIVE_KEY_WORDS for item in components):
        return True
    return "key" in components and bool(_KEY_CONTEXT_WORDS.intersection(components))
