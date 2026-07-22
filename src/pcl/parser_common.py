from __future__ import annotations


def choices_help(values: set[str]) -> str:
    return ", ".join(sorted(values))
