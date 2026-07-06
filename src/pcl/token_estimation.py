from __future__ import annotations

import math


TOKEN_ESTIMATOR = "charclass/v1"


def estimate_token_count(text: str) -> int:
    tokens = 0
    ascii_word_length = 0
    in_whitespace_run = False

    def flush_ascii_word() -> None:
        nonlocal ascii_word_length, tokens
        if ascii_word_length:
            tokens += max(1, math.ceil(ascii_word_length / 4))
            ascii_word_length = 0

    def flush_whitespace() -> None:
        nonlocal in_whitespace_run, tokens
        if in_whitespace_run:
            tokens += 1
            in_whitespace_run = False

    for char in text:
        if _is_ascii_word_char(char):
            flush_whitespace()
            ascii_word_length += 1
            continue
        flush_ascii_word()
        if char.isspace():
            in_whitespace_run = True
            continue
        flush_whitespace()
        tokens += 1

    flush_ascii_word()
    flush_whitespace()
    return tokens


def _is_ascii_word_char(char: str) -> bool:
    return char.isascii() and (char.isalnum() or char == "_")
