from __future__ import annotations

import re


_KEY_COMPONENT = re.compile(r"[A-Z]+(?=[A-Z][a-z]|[a-z]|$)|[A-Z]?[a-z]+|[0-9]+")
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


def is_sensitive_key(key: str) -> bool:
    """Return whether an argv or mapping key is shaped like a secret name."""

    if not isinstance(key, str):
        return False
    candidate = key.strip().lstrip("-")
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
