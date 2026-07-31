from __future__ import annotations

import sqlite3

import pytest

from pcl.prefixed_ids import increment_decimal_text, next_prefixed_id_strict


def test_decimal_increment_never_uses_machine_integer_limits() -> None:
    assert increment_decimal_text("0") == "1"
    assert increment_decimal_text("0099") == "0100"
    assert increment_decimal_text("9" * 4096) == "1" + ("0" * 4096)


@pytest.mark.parametrize("value", ["", "+1", "-1", "1.0", " 1", "1 ", "１２"])
def test_decimal_increment_rejects_non_ascii_canonical_digits(value: str) -> None:
    with pytest.raises(ValueError):
        increment_decimal_text(value)


def test_allocator_orders_decimal_suffixes_without_casting_to_int() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE evidence(id TEXT PRIMARY KEY)")
    conn.executemany(
        "INSERT INTO evidence(id) VALUES (?)",
        [("E-9",), ("E-10",), ("E-" + ("9" * 4096),), ("not-an-id",)],
    )

    allocated = next_prefixed_id_strict(conn, table="evidence", prefix="E", min_width=4)

    assert allocated == "E-1" + ("0" * 4096)
