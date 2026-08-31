from __future__ import annotations

import os
import re

from .sensitive import is_env_key_shaped, is_option_shaped_key, split_key_value


_WINDOWS_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_HOME_RELATIVE_PREFIXES = ("~/", "~\\")
_PATH_LIST_SEPARATORS = frozenset({":", ";", ","})


def is_path_like(value: str) -> bool:
    """Return whether a token is an absolute or home-relative filesystem path."""

    return isinstance(value, str) and (
        value.startswith(_HOME_RELATIVE_PREFIXES)
        or os.path.isabs(value)
        or _WINDOWS_ABSOLUTE_PATH.match(value) is not None
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
