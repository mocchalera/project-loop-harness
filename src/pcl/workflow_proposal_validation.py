from __future__ import annotations

import re
from typing import Any

from .errors import InvalidInputError
from .workflow_yaml import parse_workflow_yaml


PROPOSAL_ID_RE = re.compile(r"^WP-(\d{4})$")
REQUIRED_WORKFLOW_FIELDS = [
    "id",
    "name",
    "type",
    "version",
    "goal",
    "agents",
    "steps",
    "budget",
    "stop_conditions",
]


def validate_workflow_proposal_text(text: str, *, source_label: str) -> dict[str, Any]:
    data = parse_workflow_yaml(text)
    validate_workflow_proposal_data(data, source_label=source_label)
    return data


def validate_workflow_proposal_data(data: dict[str, Any], *, source_label: str) -> None:
    for field in REQUIRED_WORKFLOW_FIELDS:
        if field not in data:
            raise InvalidInputError(
                f"Workflow proposal {source_label} is missing required field: {field}",
                details={"source": source_label, "field": field},
            )
    workflow_id = str(data["id"])
    if not _is_identifier(workflow_id):
        raise InvalidInputError(
            f"Workflow proposal {source_label} has invalid workflow id: {workflow_id}",
            details={"source": source_label, "workflow_id": workflow_id},
        )
    if not isinstance(data["agents"], dict):
        raise InvalidInputError(f"Workflow proposal {source_label} agents must be a mapping.")
    if not isinstance(data["steps"], list):
        raise InvalidInputError(f"Workflow proposal {source_label} steps must be a list.")


def _is_identifier(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"_", "-"} for char in value)
