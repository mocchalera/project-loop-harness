from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any

from .errors import InvalidInputError


ESCALATION_LINK_TYPE = "escalation"


def normalized_json_array(raw: str, field_name: str) -> str:
    try:
        value = json.loads(raw)
    except JSONDecodeError as exc:
        raise InvalidInputError(
            f"{field_name} must be valid JSON: {exc.msg}.",
            details={"field": field_name, "position": exc.pos},
        ) from exc
    if not isinstance(value, list):
        raise InvalidInputError(
            f"{field_name} must be a JSON array.",
            details={"field": field_name, "type": type(value).__name__},
        )
    return dumps_json_array(value)


def dumps_json_array(value: list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def merge_escalation_link(blocks_json: str, escalation_id: str) -> str:
    blocks = json.loads(normalized_json_array(blocks_json, "blocks-json"))
    if not _contains_escalation_link(blocks, escalation_id):
        blocks.append({"type": ESCALATION_LINK_TYPE, "id": escalation_id})
    return dumps_json_array(blocks)


def linked_escalation_ids(blocks_json: str | None) -> list[str]:
    try:
        blocks = json.loads(str(blocks_json or "[]"))
    except JSONDecodeError:
        return []
    if not isinstance(blocks, list):
        return []
    ids = {
        str(item["id"])
        for item in blocks
        if isinstance(item, dict)
        and item.get("type") == ESCALATION_LINK_TYPE
        and isinstance(item.get("id"), str)
        and item.get("id")
    }
    return sorted(ids)


def has_escalation_link(blocks_json: str | None, escalation_id: str) -> bool:
    return escalation_id in linked_escalation_ids(blocks_json)


def enrich_decisions_with_links(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for decision in decisions:
        row = dict(decision)
        row["linked_escalation_ids"] = linked_escalation_ids(str(row.get("blocks_json") or "[]"))
        enriched.append(row)
    return enriched


def enrich_escalations_with_links(
    escalations: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched = []
    decisions_with_links = enrich_decisions_with_links(decisions)
    for escalation in escalations:
        escalation_id = str(escalation["id"])
        linked_decision_ids = sorted(
            str(decision["id"])
            for decision in decisions_with_links
            if escalation_id in decision.get("linked_escalation_ids", [])
        )
        row = dict(escalation)
        row["linked_decision_ids"] = linked_decision_ids
        enriched.append(row)
    return enriched


def linked_decisions_for_escalation(
    decisions: list[dict[str, Any]],
    escalation_id: str,
) -> list[dict[str, Any]]:
    decisions_with_links = enrich_decisions_with_links(decisions)
    return [
        decision
        for decision in decisions_with_links
        if escalation_id in decision.get("linked_escalation_ids", [])
    ]


def _contains_escalation_link(blocks: list[Any], escalation_id: str) -> bool:
    return any(
        isinstance(item, dict)
        and item.get("type") == ESCALATION_LINK_TYPE
        and item.get("id") == escalation_id
        for item in blocks
    )
