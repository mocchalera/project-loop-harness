from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import InvalidInputError


FINISH_CHECK_COMMAND_KEYS = ("lint", "typecheck", "test", "e2e", "build")
FINISH_CHECK_EXAMPLE = 'commands:\n  test: "python -m pytest"'
CHECKPOINT_DEFAULT_FEATURE_INTERVAL = 5
CHECKPOINT_DEFAULT_MODE = "advisory"
CHECKPOINT_MODES = {"advisory", "blocking", "off"}


def project_command_specs(root: Path) -> dict[str, dict[str, Any]]:
    """Read the small commands subset of pcl.yaml without adding a YAML dependency."""

    config_path = root / "pcl.yaml"
    if not config_path.exists():
        return {}
    lines = config_path.read_text(encoding="utf-8").splitlines()
    specs: dict[str, dict[str, Any]] = {}
    in_commands = False
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        if raw_line.startswith("commands:"):
            in_commands = True
            index += 1
            continue
        if in_commands and raw_line and not raw_line.startswith(" "):
            break
        if not in_commands or not raw_line.startswith("  ") or raw_line.startswith("    ") or ":" not in raw_line:
            index += 1
            continue
        key, raw_value = raw_line.strip().split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value.lower() in {"null", "~"}:
            specs[key] = {"status": "disabled", "command": None, "syntax": "null"}
        elif value:
            unquoted = _strip_yaml_string(value)
            if unquoted.lower().replace(" ", "") == "{disabled:true}":
                specs[key] = {"status": "disabled", "command": None, "syntax": "disabled"}
            elif unquoted:
                specs[key] = {"status": "enabled", "command": unquoted, "syntax": "command"}
            else:
                specs[key] = {"status": "empty", "command": "", "syntax": "empty"}
        else:
            disabled = False
            cursor = index + 1
            while cursor < len(lines) and (not lines[cursor] or lines[cursor].startswith("    ")):
                nested = lines[cursor].strip()
                if nested.lower().replace(" ", "") == "disabled:true":
                    disabled = True
                cursor += 1
            specs[key] = {
                "status": "disabled" if disabled else "empty",
                "command": None if disabled else "",
                "syntax": "disabled" if disabled else "empty",
            }
        index += 1
    return specs


def enabled_project_commands(root: Path) -> dict[str, str]:
    return {
        key: str(spec["command"])
        for key, spec in project_command_specs(root).items()
        if spec["status"] == "enabled"
    }


def finish_check_configuration(root: Path) -> dict[str, Any]:
    specs = project_command_specs(root)
    enabled = [key for key in FINISH_CHECK_COMMAND_KEYS if specs.get(key, {}).get("status") == "enabled"]
    disabled = [key for key in FINISH_CHECK_COMMAND_KEYS if specs.get(key, {}).get("status") == "disabled"]
    empty = [key for key in FINISH_CHECK_COMMAND_KEYS if specs.get(key, {}).get("status") == "empty"]
    return {
        "configured": bool(enabled),
        "enabled_keys": enabled,
        "disabled_keys": disabled,
        "empty_keys": empty,
        "required_any_of": list(FINISH_CHECK_COMMAND_KEYS),
        "suggested_config": FINISH_CHECK_EXAMPLE,
    }


def finish_check_configuration_warning(root: Path) -> str | None:
    configuration = finish_check_configuration(root)
    if configuration["configured"]:
        return None
    return (
        "No enabled finish checks are configured; `pcl finish --emit-packet` cannot verify completion. "
        f"Add at least one check, for example:\n{FINISH_CHECK_EXAMPLE}"
    )


def checkpoint_configuration(root: Path) -> dict[str, Any]:
    config_path = root / "pcl.yaml"
    values: dict[str, str] = {}
    if config_path.exists():
        try:
            values = _simple_yaml_section(
                config_path.read_text(encoding="utf-8").splitlines(),
                "checkpoint",
            )
        except OSError as exc:
            raise InvalidInputError(
                f"Could not read checkpoint configuration at {config_path}: {exc}",
                details={"path": str(config_path)},
            ) from exc

    mode = values.get("mode", CHECKPOINT_DEFAULT_MODE).strip().lower()
    if mode not in CHECKPOINT_MODES:
        raise InvalidInputError(
            f"Invalid checkpoint.mode: {mode}",
            details={
                "field": "checkpoint.mode",
                "value": mode,
                "allowed": sorted(CHECKPOINT_MODES),
            },
        )

    raw_interval = values.get(
        "feature_interval",
        str(CHECKPOINT_DEFAULT_FEATURE_INTERVAL),
    ).strip()
    try:
        feature_interval = int(raw_interval)
    except ValueError as exc:
        raise InvalidInputError(
            "checkpoint.feature_interval must be an integer of at least 1.",
            details={
                "field": "checkpoint.feature_interval",
                "value": raw_interval,
                "minimum": 1,
            },
        ) from exc
    if feature_interval < 1:
        raise InvalidInputError(
            "checkpoint.feature_interval must be an integer of at least 1.",
            details={
                "field": "checkpoint.feature_interval",
                "value": raw_interval,
                "minimum": 1,
            },
        )
    return {"mode": mode, "feature_interval": feature_interval}


def _simple_yaml_section(lines: list[str], section_name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_section = False
    for raw_line in lines:
        if raw_line.startswith(f"{section_name}:"):
            in_section = True
            continue
        if in_section and raw_line and not raw_line.startswith(" "):
            break
        if (
            not in_section
            or not raw_line.startswith("  ")
            or raw_line.startswith("    ")
            or ":" not in raw_line
        ):
            continue
        key, value = raw_line.strip().split(":", 1)
        values[key.strip()] = _strip_yaml_string(value.strip())
    return values


def _strip_yaml_string(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
