from __future__ import annotations

import re
import sqlite3


_ASCII_DIGITS = re.compile(r"^[0-9]+$")


def increment_decimal_text(value: str) -> str:
    """Increment ASCII decimal text without an integer conversion."""

    if not isinstance(value, str) or _ASCII_DIGITS.fullmatch(value) is None:
        raise ValueError("decimal text must contain only ASCII digits")
    digits = list(value)
    carry = 1
    for index in range(len(digits) - 1, -1, -1):
        if not carry:
            break
        digit = ord(digits[index]) - ord("0") + carry
        digits[index] = chr(ord("0") + (digit % 10))
        carry = digit // 10
    if carry:
        digits.insert(0, "1")
    return "".join(digits)


def decimal_sort_key(value: str) -> tuple[int, str]:
    if _ASCII_DIGITS.fullmatch(value) is None:
        raise ValueError("decimal text must contain only ASCII digits")
    canonical = value.lstrip("0") or "0"
    return len(canonical), canonical


def next_prefixed_id_strict(
    conn: sqlite3.Connection,
    *,
    table: str,
    prefix: str,
    min_width: int = 4,
) -> str:
    return next_prefixed_ids_strict(
        conn,
        table=table,
        prefix=prefix,
        count=1,
        min_width=min_width,
    )[0]


def next_prefixed_ids_strict(
    conn: sqlite3.Connection,
    *,
    table: str,
    prefix: str,
    count: int,
    min_width: int = 4,
) -> list[str]:
    if not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    if not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
        raise ValueError("prefix is not registered canonical syntax")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError("table is not a safe SQLite identifier")
    pattern = re.compile(rf"^{re.escape(prefix)}-([0-9]+)$")
    maximum = "0"
    maximum_key = decimal_sort_key(maximum)
    for row in conn.execute(
        f"SELECT id FROM {table} WHERE id LIKE ?",
        (f"{prefix}-%",),
    ).fetchall():
        match = pattern.fullmatch(str(row["id"]))
        if match is None:
            continue
        suffix = match.group(1)
        key = decimal_sort_key(suffix)
        if key > maximum_key:
            maximum = suffix.lstrip("0") or "0"
            maximum_key = key
    values: list[str] = []
    current = maximum
    for _ in range(count):
        current = increment_decimal_text(current)
        values.append(f"{prefix}-{current.zfill(min_width)}")
    return values
