from __future__ import annotations

import os
import re

from .sensitive import is_env_key_shaped, is_option_shaped_key, split_key_value


_WINDOWS_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_HOME_RELATIVE_PREFIXES = ("~/", "~\\")


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
