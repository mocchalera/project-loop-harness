from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
from importlib.resources import files
import json
import math
from pathlib import Path
import re
from typing import Any

from ..token_estimation import TOKEN_ESTIMATOR, estimate_token_count


HANDOFF_PACKET_CONTRACT_VERSION = "handoff-packet/v1"
SCHEMA_RESOURCE = "schemas/handoff-packet-v1.schema.json"

_TOP_LEVEL_FIELDS = {
    "contract_version",
    "packet_id",
    "producer",
    "generated_at",
    "target",
    "current_state",
    "summary",
    "verified",
    "unverified",
    "decisions",
    "blockers",
    "risks",
    "next_safe_action",
    "context_refs",
    "intent_index_ref",
    "budget_remaining",
    "token_estimator",
    "estimated_token_count",
    "size_bytes",
    "omitted_sections",
}
_REQUIRED_TOP_LEVEL_FIELDS = _TOP_LEVEL_FIELDS - {"intent_index_ref", "budget_remaining"}
_PACKET_ID = re.compile(r"^hp-sha256:[0-9a-f]{64}$")
_EVIDENCE_REF = re.compile(r"^evidence:E-[0-9]{4,}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_TARGETS = {
    "goal": re.compile(r"^G-[0-9]{4,}$"),
    "task": re.compile(r"^T-[0-9]{4,}$"),
}
_PROOF_LEVELS = {"L1", "L2", "L3", "L4"}
_FRESHNESS = {"current", "stale", "unknown"}


@dataclass(frozen=True)
class HandoffPacketValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": HANDOFF_PACKET_CONTRACT_VERSION,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def handoff_packet_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(SCHEMA_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def canonical_json(packet: Mapping[str, Any]) -> str:
    return json.dumps(
        packet,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def compute_packet_id(packet: Mapping[str, Any]) -> str:
    content = dict(packet)
    content.pop("packet_id", None)
    digest = hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()
    return f"hp-sha256:{digest}"


def finalize_handoff_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Attach deterministic content metrics and a content-derived packet ID."""

    result = deepcopy(dict(packet))
    result["packet_id"] = "hp-sha256:" + "0" * 64
    result["token_estimator"] = TOKEN_ESTIMATOR
    result["estimated_token_count"] = 0
    result["size_bytes"] = 0
    for _ in range(8):
        result["packet_id"] = compute_packet_id(result)
        serialized = canonical_json(result)
        metrics = (
            estimate_token_count(serialized),
            len(serialized.encode("utf-8")),
        )
        previous = (result["estimated_token_count"], result["size_bytes"])
        result["estimated_token_count"], result["size_bytes"] = metrics
        if metrics == previous:
            result["packet_id"] = compute_packet_id(result)
            return result
    raise ValueError("handoff packet metrics did not stabilize")


def load_handoff_packet(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_non_finite_json_number)


def validate_handoff_packet(packet: Any) -> HandoffPacketValidationResult:
    errors: list[str] = []
    if not isinstance(packet, dict):
        return HandoffPacketValidationResult(("$: must be an object",))

    _collect_non_finite(packet, "$", errors)
    _fields(packet, "$", _REQUIRED_TOP_LEVEL_FIELDS, _TOP_LEVEL_FIELDS, errors)
    _equal(packet.get("contract_version"), HANDOFF_PACKET_CONTRACT_VERSION, "$.contract_version", errors)
    _string(packet.get("packet_id"), "$.packet_id", errors, pattern=_PACKET_ID)
    _timestamp(packet.get("generated_at"), "$.generated_at", errors)
    _producer(packet.get("producer"), errors)
    _target(packet.get("target"), errors)
    _string(packet.get("current_state"), "$.current_state", errors)
    _string(packet.get("summary"), "$.summary", errors)
    _verified(packet.get("verified"), errors)
    _unverified(packet.get("unverified"), errors)
    _decisions(packet.get("decisions"), errors)
    _string_array(packet.get("blockers"), "$.blockers", errors)
    _string_array(packet.get("risks"), "$.risks", errors)
    _next_action(packet.get("next_safe_action"), errors)
    _context_refs(packet.get("context_refs"), errors)
    _optional_string(packet.get("intent_index_ref"), "$.intent_index_ref", errors)
    budget = packet.get("budget_remaining")
    if budget is not None and not isinstance(budget, dict):
        errors.append("$.budget_remaining: must be an object or null")
    _equal(packet.get("token_estimator"), TOKEN_ESTIMATOR, "$.token_estimator", errors)
    _nonnegative_int(packet.get("estimated_token_count"), "$.estimated_token_count", errors)
    _nonnegative_int(packet.get("size_bytes"), "$.size_bytes", errors)
    _string_array(packet.get("omitted_sections"), "$.omitted_sections", errors)

    packet_id = packet.get("packet_id")
    if isinstance(packet_id, str) and _PACKET_ID.fullmatch(packet_id) and not _has_non_finite(packet):
        if packet_id != compute_packet_id(packet):
            errors.append("$.packet_id: does not match the canonical packet content hash")
        serialized = canonical_json(packet)
        if packet.get("estimated_token_count") != estimate_token_count(serialized):
            errors.append("$.estimated_token_count: does not match canonical JSON")
        if packet.get("size_bytes") != len(serialized.encode("utf-8")):
            errors.append("$.size_bytes: does not match canonical UTF-8 JSON")
    return HandoffPacketValidationResult(tuple(errors))


def _producer(value: Any, errors: list[str]) -> None:
    if not _object(value, "$.producer", errors):
        return
    _fields(value, "$.producer", {"name", "version"}, {"name", "version"}, errors)
    _equal(value.get("name"), "project-loop-harness", "$.producer.name", errors)
    _string(value.get("version"), "$.producer.version", errors)


def _target(value: Any, errors: list[str]) -> None:
    if not _object(value, "$.target", errors):
        return
    allowed = {"type", "id", "work_brief_ref", "repository_revision"}
    _fields(value, "$.target", {"type", "id"}, allowed, errors)
    target_type = value.get("type")
    if target_type not in _TARGETS:
        errors.append("$.target.type: must be one of goal, task")
    _string(value.get("id"), "$.target.id", errors, pattern=_TARGETS.get(target_type))
    _optional_string(value.get("work_brief_ref"), "$.target.work_brief_ref", errors)
    _optional_string(value.get("repository_revision"), "$.target.repository_revision", errors)


def _verified(value: Any, errors: list[str]) -> None:
    if not _array(value, "$.verified", errors):
        return
    for index, item in enumerate(value):
        path = f"$.verified[{index}]"
        if not _object(item, path, errors):
            continue
        allowed = {"text", "proof_level", "evidence_refs"}
        _fields(item, path, allowed, allowed, errors)
        _string(item.get("text"), f"{path}.text", errors)
        if item.get("proof_level") not in _PROOF_LEVELS:
            errors.append(f"{path}.proof_level: must be one of L1, L2, L3, L4")
        refs = item.get("evidence_refs")
        _ref_array(refs, f"{path}.evidence_refs", errors)
        if isinstance(refs, list) and not refs:
            errors.append(f"{path}.evidence_refs: verified claims require Evidence refs")


def _unverified(value: Any, errors: list[str]) -> None:
    if not _array(value, "$.unverified", errors):
        return
    for index, item in enumerate(value):
        path = f"$.unverified[{index}]"
        if not _object(item, path, errors):
            continue
        allowed = {"text", "reason"}
        _fields(item, path, allowed, allowed, errors)
        _string(item.get("text"), f"{path}.text", errors)
        _string(item.get("reason"), f"{path}.reason", errors)


def _decisions(value: Any, errors: list[str]) -> None:
    if not _array(value, "$.decisions", errors):
        return
    for index, item in enumerate(value):
        path = f"$.decisions[{index}]"
        if not _object(item, path, errors):
            continue
        allowed = {"id", "summary", "evidence_refs"}
        _fields(item, path, {"id", "summary"}, allowed, errors)
        _string(item.get("id"), f"{path}.id", errors)
        _string(item.get("summary"), f"{path}.summary", errors)
        if "evidence_refs" in item:
            _ref_array(item.get("evidence_refs"), f"{path}.evidence_refs", errors)


def _next_action(value: Any, errors: list[str]) -> None:
    if not _object(value, "$.next_safe_action", errors):
        return
    allowed = {"text", "command"}
    _fields(value, "$.next_safe_action", allowed, allowed, errors)
    _string(value.get("text"), "$.next_safe_action.text", errors)
    _optional_string(value.get("command"), "$.next_safe_action.command", errors)


def _context_refs(value: Any, errors: list[str]) -> None:
    if not _array(value, "$.context_refs", errors):
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        path = f"$.context_refs[{index}]"
        if not _object(item, path, errors):
            continue
        allowed = {"ref", "kind", "freshness", "sha256"}
        _fields(item, path, {"ref", "kind", "freshness"}, allowed, errors)
        _string(item.get("ref"), f"{path}.ref", errors)
        _string(item.get("kind"), f"{path}.kind", errors)
        if item.get("freshness") not in _FRESHNESS:
            errors.append(f"{path}.freshness: must be one of current, stale, unknown")
        sha = item.get("sha256")
        if sha is not None:
            _string(sha, f"{path}.sha256", errors, pattern=_SHA256)
        ref = item.get("ref")
        if isinstance(ref, str):
            if ref in seen:
                errors.append(f"{path}.ref: duplicate context ref")
            seen.add(ref)


def _fields(
    value: dict[str, Any],
    path: str,
    required: set[str],
    allowed: set[str],
    errors: list[str],
) -> None:
    for name in sorted(required - set(value)):
        errors.append(f"{path}.{name}: is required")
    for name in sorted(set(value) - allowed):
        errors.append(f"{path}.{name}: additional property is not allowed")


def _object(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return False
    return True


def _array(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return False
    return True


def _string(value: Any, path: str, errors: list[str], *, pattern: re.Pattern[str] | None = None) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: must be a non-empty string")
    elif pattern is not None and pattern.fullmatch(value) is None:
        errors.append(f"{path}: has invalid format")


def _optional_string(value: Any, path: str, errors: list[str]) -> None:
    if value is not None:
        _string(value, path, errors)


def _string_array(value: Any, path: str, errors: list[str]) -> None:
    if not _array(value, path, errors):
        return
    for index, item in enumerate(value):
        _string(item, f"{path}[{index}]", errors)


def _ref_array(value: Any, path: str, errors: list[str]) -> None:
    if not _array(value, path, errors):
        return
    for index, item in enumerate(value):
        _string(item, f"{path}[{index}]", errors, pattern=_EVIDENCE_REF)


def _equal(value: Any, expected: Any, path: str, errors: list[str]) -> None:
    if value != expected:
        errors.append(f"{path}: must equal {expected!r}")


def _nonnegative_int(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(f"{path}: must be a non-negative integer")


def _timestamp(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        errors.append(f"{path}: must be an RFC 3339 UTC date-time")
        return
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        errors.append(f"{path}: must be a real RFC 3339 UTC date-time")


def _collect_non_finite(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path}: non-finite JSON numbers are not allowed")
    elif isinstance(value, dict):
        for key, item in value.items():
            _collect_non_finite(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_non_finite(item, f"{path}[{index}]", errors)


def _has_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_has_non_finite(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_non_finite(item) for item in value)
    return False


def _reject_non_finite_json_number(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value} is not allowed")
