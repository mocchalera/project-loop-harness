from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class ProfileContractValidationResult:
    contract_type: str
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def schema_resource(resource: str) -> dict[str, Any]:
    value = json.loads(
        files("pcl.contracts").joinpath(f"schemas/{resource}").read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError(f"Contract schema is not an object: {resource}")
    return value


def load_strict_json(path: str | Path) -> Any:
    return loads_strict_json(Path(path).read_bytes())


def loads_strict_json(value: str | bytes) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(
        value,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite,
    )


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_schema(value: Any, schema: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    _validate(value, schema, "$", errors)
    return errors


def unique_strings(
    values: Any,
    *,
    path: str,
    errors: list[str],
) -> list[str]:
    if not isinstance(values, list):
        return []
    strings = [item for item in values if isinstance(item, str)]
    if len(strings) == len(values) and len(strings) != len(set(strings)):
        errors.append(f"{path}: values must be unique")
    return strings


def duplicate_ids(
    values: Any,
    *,
    field: str,
    path: str,
    errors: list[str],
) -> set[str]:
    if not isinstance(values, list):
        return set()
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get(field), str):
            continue
        item_id = str(item[field])
        if item_id in seen:
            duplicates.add(item_id)
        seen.add(item_id)
    for item_id in sorted(duplicates):
        errors.append(f"{path}: duplicate {field} {item_id!r}")
    return seen


def _validate(value: Any, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    for branch in _mapping_list(schema.get("allOf")):
        _validate(value, branch, path, errors)

    condition = schema.get("if")
    then = schema.get("then")
    if isinstance(condition, dict) and isinstance(then, dict):
        condition_errors: list[str] = []
        _validate(value, condition, path, condition_errors)
        if not condition_errors:
            _validate(value, then, path, errors)

    one_of = _mapping_list(schema.get("oneOf"))
    if one_of:
        matching = 0
        for branch in one_of:
            branch_errors: list[str] = []
            _validate(value, branch, path, branch_errors)
            if not branch_errors:
                matching += 1
        if matching != 1:
            errors.append(f"{path}: must match exactly one allowed shape")
        return

    expected_type = schema.get("type")
    if expected_type is not None and not _matches_type(value, expected_type):
        errors.append(f"{path}: must be {_type_description(expected_type)}")
        return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{path}: must be one of {', '.join(map(repr, enum))}")

    if isinstance(value, dict):
        required = schema.get("required")
        if isinstance(required, list):
            for field in sorted(item for item in required if isinstance(item, str)):
                if field not in value:
                    errors.append(f"{path}.{field}: is required")
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        if schema.get("additionalProperties") is False:
            for field in sorted(set(value) - set(properties)):
                errors.append(f"{path}.{field}: additional property is not allowed")
        for field in sorted(set(value) & set(properties)):
            field_schema = properties[field]
            if isinstance(field_schema, dict):
                _validate(value[field], field_schema, f"{path}.{field}", errors)

    if isinstance(value, list):
        _array_constraints(value, schema, path, errors)
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate(item, item_schema, f"{path}[{index}]", errors)

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path}: must contain at least {min_length} characters")
        if isinstance(max_length, int) and len(value) > max_length:
            errors.append(f"{path}: must contain at most {max_length} characters")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                matches = re.search(pattern, value) is not None
            except re.error as exc:
                errors.append(f"{path}: contract pattern is invalid: {exc}")
            else:
                if not matches:
                    errors.append(f"{path}: has invalid format")
        if schema.get("format") == "date-time" and not _valid_datetime(value):
            errors.append(f"{path}: must be a real RFC 3339 date-time")

    if _is_number(value):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if _is_number(minimum) and value < minimum:
            errors.append(f"{path}: must be at least {minimum}")
        if _is_number(maximum) and value > maximum:
            errors.append(f"{path}: must be at most {maximum}")


def _array_constraints(
    value: list[Any],
    schema: Mapping[str, Any],
    path: str,
    errors: list[str],
) -> None:
    min_items = schema.get("minItems")
    max_items = schema.get("maxItems")
    if isinstance(min_items, int) and len(value) < min_items:
        errors.append(f"{path}: must contain at least {min_items} items")
    if isinstance(max_items, int) and len(value) > max_items:
        errors.append(f"{path}: must contain at most {max_items} items")
    if schema.get("uniqueItems") is True:
        serialized = [
            json.dumps(item, ensure_ascii=False, allow_nan=False, sort_keys=True)
            for item in value
        ]
        if len(serialized) != len(set(serialized)):
            errors.append(f"{path}: items must be unique")


def _matches_type(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_matches_type(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return _is_number(value)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _type_description(expected: Any) -> str:
    if isinstance(expected, list):
        return "one of " + ", ".join(str(item) for item in expected)
    return f"a JSON {expected}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_datetime(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r} is not allowed")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value} is not allowed")
