from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import unquote, urlsplit

from .sensitive import is_env_key_shaped, is_option_shaped_key, split_key_value


_WINDOWS_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_HOME_RELATIVE_PREFIXES = ("~/", "~\\")
_PATH_LIST_SEPARATORS = frozenset({":", ";", ","})
_FILE_URI = re.compile(r"(?i)(?<![A-Za-z0-9+.-])file:[^\s\"'<>]+")


def _is_local_file_uri_host(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    if normalized in {"", "localhost"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def is_local_file_uri(value: str) -> bool:
    """Return whether a file URI names a local absolute filesystem path."""

    if not isinstance(value, str) or not value.lower().startswith("file:"):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme.lower() != "file":
        return False
    try:
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if not _is_local_file_uri_host(host):
        return False
    path = unquote(parsed.path)
    return bool(path) and (path.startswith("/") or _WINDOWS_ABSOLUTE_PATH.match(path) is not None)


def redact_local_file_uris(
    value: str, *, replacement: str = "<absolute-path>"
) -> tuple[str, bool]:
    """Replace local file URIs in text while preserving remote URI schemes."""

    if not isinstance(value, str):
        return value, False

    def replace(match: re.Match[str]) -> str:
        return replacement if is_local_file_uri(match.group(0)) else match.group(0)

    redacted, count = _FILE_URI.subn(replace, value)
    return redacted, count > 0 and redacted != value


def is_path_like(value: str) -> bool:
    """Return whether a token is an absolute or home-relative filesystem path."""

    return isinstance(value, str) and (
        value.startswith(_HOME_RELATIVE_PREFIXES)
        or os.path.isabs(value)
        or _WINDOWS_ABSOLUTE_PATH.match(value) is not None
        or is_local_file_uri(value)
    )


def split_path_value(value: str) -> tuple[str, str, str] | None:
    """Return a shaped key/value pair whose value starts as a filesystem path."""

    key_value = split_key_value(value)
    if key_value is None:
        return None
    key, separator, candidate = key_value
    if not (is_option_shaped_key(key) or is_env_key_shaped(key)):
        return None
    if not is_path_like(candidate):
        return None
    return key, separator, candidate


def _path_list_members(value: str) -> tuple[str, ...]:
    members: list[str] = []
    start = 0
    index = 0
    while index < len(value):
        character = value[index]
        is_uri_scheme = character == ":" and value[index + 1 : index + 3] == "//"
        is_windows_drive = (
            character == ":"
            and index == start + 1
            and value[start].isalpha()
            and index + 1 < len(value)
            and value[index + 1] in "\\/"
        )
        if character in _PATH_LIST_SEPARATORS and not is_uri_scheme and not is_windows_drive:
            members.append(value[start:index].strip())
            start = index + 1
        index += 1
    members.append(value[start:].strip())
    return tuple(members)


def is_path_list_like(value: str) -> bool:
    """Return whether a value contains a path-like member in a path list."""

    if not isinstance(value, str):
        return False
    members = _path_list_members(value)
    return len(members) > 1 and any(is_path_like(member) for member in members)


def split_path_list_value(value: str) -> tuple[str, str, str] | None:
    """Return a shaped key/value pair whose value contains a filesystem path list."""

    key_value = split_key_value(value)
    if key_value is None:
        return None
    key, separator, candidate = key_value
    if not (is_option_shaped_key(key) or is_env_key_shaped(key)):
        return None
    if not is_path_list_like(candidate):
        return None
    return key, separator, candidate
