from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .errors import InvalidInputError


KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class _Line:
    number: int
    indent: int
    text: str


def parse_workflow_yaml(text: str) -> dict[str, Any]:
    lines = _prepare_lines(text)
    if not lines:
        raise InvalidInputError("Workflow YAML is empty.")
    value, index = _parse_block(lines, 0, lines[0].indent)
    if index != len(lines):
        line = lines[index]
        raise InvalidInputError(
            f"Unexpected YAML content at line {line.number}.",
            details={"line": line.number, "text": line.text},
        )
    if not isinstance(value, dict):
        raise InvalidInputError("Workflow YAML root must be a mapping.")
    return value


def _prepare_lines(text: str) -> list[_Line]:
    prepared: list[_Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw:
            raise InvalidInputError(
                f"Tabs are not supported in workflow YAML at line {number}.",
                details={"line": number},
            )
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2 != 0:
            raise InvalidInputError(
                f"Workflow YAML indentation must use multiples of two spaces at line {number}.",
                details={"line": number, "indent": indent},
            )
        prepared.append(_Line(number=number, indent=indent, text=raw[indent:]))
    return prepared


def _parse_block(lines: list[_Line], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    line = lines[index]
    if line.indent != indent:
        raise InvalidInputError(
            f"Expected indentation {indent} at line {line.number}; found {line.indent}.",
            details={"line": line.number, "expected_indent": indent, "actual_indent": line.indent},
        )
    if line.text.startswith("- "):
        return _parse_sequence(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_mapping(lines: list[_Line], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise InvalidInputError(
                f"Unexpected indentation at line {line.number}.",
                details={"line": line.number, "indent": line.indent},
            )
        if line.text.startswith("- "):
            break
        key, raw_value = _split_key_value(line)
        if raw_value == "":
            index += 1
            if index < len(lines) and lines[index].indent > indent:
                value, index = _parse_block(lines, index, lines[index].indent)
            else:
                value = {}
        else:
            value = _parse_scalar(raw_value, line.number)
            index += 1
        result[key] = value
    return result, index


def _parse_sequence(lines: list[_Line], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise InvalidInputError(
                f"Unexpected indentation at line {line.number}.",
                details={"line": line.number, "indent": line.indent},
            )
        if not line.text.startswith("- "):
            break

        item_text = line.text[2:].strip()
        index += 1
        if item_text == "":
            if index < len(lines) and lines[index].indent > indent:
                value, index = _parse_block(lines, index, lines[index].indent)
            else:
                value = {}
        elif _looks_like_key_value(item_text):
            synthetic = _Line(number=line.number, indent=indent + 2, text=item_text)
            value, _ = _parse_mapping([synthetic], 0, indent + 2)
            if index < len(lines) and lines[index].indent > indent:
                child, index = _parse_mapping(lines, index, lines[index].indent)
                value.update(child)
        else:
            value = _parse_scalar(item_text, line.number)
            if index < len(lines) and lines[index].indent > indent:
                raise InvalidInputError(
                    f"Scalar list item cannot have nested content at line {line.number}.",
                    details={"line": line.number},
                )
        result.append(value)
    return result, index


def _split_key_value(line: _Line) -> tuple[str, str]:
    if ":" not in line.text:
        raise InvalidInputError(
            f"Expected key/value pair at line {line.number}.",
            details={"line": line.number, "text": line.text},
        )
    key, raw_value = line.text.split(":", 1)
    key = key.strip()
    if not KEY_RE.match(key):
        raise InvalidInputError(
            f"Invalid YAML key at line {line.number}: {key}",
            details={"line": line.number, "key": key},
        )
    return key, raw_value.strip()


def _looks_like_key_value(text: str) -> bool:
    if ":" not in text:
        return False
    key = text.split(":", 1)[0].strip()
    return bool(KEY_RE.match(key))


def _parse_scalar(value: str, line_number: int) -> Any:
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError as exc:
            raise InvalidInputError(
                f"Invalid integer scalar at line {line_number}: {value}",
                details={"line": line_number, "value": value},
            ) from exc
    if value[0] in {"|", ">"}:
        raise InvalidInputError(
            f"Unsupported YAML scalar at line {line_number}: {value}",
            details={"line": line_number, "value": value},
        )
    if any(token in value for token in ["[", "]", "{", "}", "&", "*"]):
        raise InvalidInputError(
            f"Unsupported YAML scalar at line {line_number}: {value}",
            details={"line": line_number, "value": value},
        )
    return value
