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
    "restart_context",
    "trace_claim_refs",
    "trace_claim_ref_omissions",
    "trace_claim_ref_budget",
}
_REQUIRED_TOP_LEVEL_FIELDS = _TOP_LEVEL_FIELDS - {
    "intent_index_ref",
    "budget_remaining",
    "restart_context",
    "trace_claim_refs",
    "trace_claim_ref_omissions",
    "trace_claim_ref_budget",
}
_PACKET_ID = re.compile(r"^hp-sha256:[0-9a-f]{64}$")
_EVIDENCE_REF = re.compile(r"^evidence:E-[0-9]{4,}$")
_EVIDENCE_ID = re.compile(r"^E-[0-9]{4,}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_TARGETS = {
    "goal": re.compile(r"^G-[0-9]{4,}$"),
    "task": re.compile(r"^T-[0-9]{4,}$"),
}
_PROOF_LEVELS = {"L1", "L2", "L3", "L4"}
_FRESHNESS = {"current", "stale", "unknown"}
_CHECK_STATUSES = {"passed", "failed", "skipped", "not_run", "timed_out"}
_EVIDENCE_SHOW_COMMAND = re.compile(r"^pcl evidence show E-[0-9]{4,} --json$")
_CHECK_PROOF_SOURCE = re.compile(r"^completion-packet/v1\.checks/CHK-[0-9]{4,}$")


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
    claim_fields = (
        packet.get("trace_claim_refs"),
        packet.get("trace_claim_ref_omissions"),
        packet.get("trace_claim_ref_budget"),
    )
    if any(value is not None for value in claim_fields):
        if not all(value is not None for value in claim_fields):
            errors.append("$.trace_claim_refs: claim refs, omissions, and budget must appear together")
        else:
            _trace_claim_refs(claim_fields[0], errors)
            _trace_claim_ref_omissions(claim_fields[1], errors)
            _trace_claim_ref_budget(claim_fields[2], claim_fields[0], errors)
    restart_context = packet.get("restart_context")
    if restart_context is not None:
        _restart_context(restart_context, errors)
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


def _trace_claim_refs(value: Any, errors: list[str]) -> None:
    path = "$.trace_claim_refs"
    if not _array(value, path, errors):
        return
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not _object(item, item_path, errors):
            continue
        fields = {"intent_index_ref", "item_id", "kind", "claim", "trust", "source_refs"}
        _fields(item, item_path, fields, fields, errors)
        _string(item.get("intent_index_ref"), f"{item_path}.intent_index_ref", errors, pattern=_EVIDENCE_REF)
        for name in ("item_id", "kind", "claim"):
            _string(item.get(name), f"{item_path}.{name}", errors)
        _equal(item.get("trust"), "unverified", f"{item_path}.trust", errors)
        refs = item.get("source_refs")
        if _array(refs, f"{item_path}.source_refs", errors):
            if not refs:
                errors.append(f"{item_path}.source_refs: must not be empty")
            for ref_index, ref in enumerate(refs):
                ref_path = f"{item_path}.source_refs[{ref_index}]"
                if not _object(ref, ref_path, errors):
                    continue
                ref_fields = {"evidence_id", "stored_path", "line_start", "line_end"}
                _fields(ref, ref_path, ref_fields, ref_fields, errors)
                _string(ref.get("evidence_id"), f"{ref_path}.evidence_id", errors, pattern=_EVIDENCE_ID)
                _string(ref.get("stored_path"), f"{ref_path}.stored_path", errors)
                start = ref.get("line_start")
                end = ref.get("line_end")
                _positive_int(start, f"{ref_path}.line_start", errors)
                _positive_int(end, f"{ref_path}.line_end", errors)
                if isinstance(start, int) and isinstance(end, int) and start > end:
                    errors.append(f"{ref_path}: line_start must be <= line_end")
        key = (str(item.get("intent_index_ref")), str(item.get("item_id")))
        if key in seen:
            errors.append(f"{item_path}: duplicate intent-index/item reference")
        seen.add(key)


def _trace_claim_ref_omissions(value: Any, errors: list[str]) -> None:
    path = "$.trace_claim_ref_omissions"
    if not _array(value, path, errors):
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not _object(item, item_path, errors):
            continue
        fields = {"item_id", "reason"}
        _fields(item, item_path, fields, fields, errors)
        _string(item.get("item_id"), f"{item_path}.item_id", errors)
        if item.get("reason") not in {
            "packet_budget",
            "unsupported_item_shape",
            "explicit_non_selection",
        }:
            errors.append(f"{item_path}.reason: has invalid omission reason")
        item_id = str(item.get("item_id"))
        if item_id in seen:
            errors.append(f"{item_path}.item_id: duplicate omission")
        seen.add(item_id)


def _trace_claim_ref_budget(value: Any, refs: Any, errors: list[str]) -> None:
    path = "$.trace_claim_ref_budget"
    if not _object(value, path, errors):
        return
    fields = {"max_items", "max_bytes", "included_items", "included_bytes"}
    _fields(value, path, fields, fields, errors)
    for name in fields:
        _nonnegative_int(value.get(name), f"{path}.{name}", errors)
    if isinstance(refs, list) and value.get("included_items") != len(refs):
        errors.append(f"{path}.included_items: must match trace_claim_refs length")
    if isinstance(refs, list):
        actual_bytes = sum(
            len(json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))
            for item in refs
        )
        if value.get("included_bytes") != actual_bytes:
            errors.append(f"{path}.included_bytes: must match canonical selected item bytes")


def _restart_context(value: Any, errors: list[str]) -> None:
    path = "$.restart_context"
    if not _object(value, path, errors):
        return
    required = {
        "target_intent",
        "acceptance_status",
        "acceptance_ref",
        "target_review_command",
        "verification_commands",
        "evidence_resolution_commands",
        "changed_paths",
        "documentation_candidates",
    }
    allowed = required | {"approval_provenance"}
    _fields(value, path, required, allowed, errors)
    _string(value.get("target_intent"), f"{path}.target_intent", errors)
    if value.get("acceptance_status") not in {"intent_only", "work_brief_linked", "missing"}:
        errors.append(
            f"{path}.acceptance_status: must be one of intent_only, work_brief_linked, missing"
        )
    _optional_ref(value.get("acceptance_ref"), f"{path}.acceptance_ref", errors)
    if value.get("acceptance_status") == "work_brief_linked" and value.get("acceptance_ref") is None:
        errors.append(f"{path}.acceptance_ref: is required when work_brief_linked")
    if value.get("acceptance_status") != "work_brief_linked" and value.get("acceptance_ref") is not None:
        errors.append(f"{path}.acceptance_ref: requires work_brief_linked")
    provenance = value.get("approval_provenance")
    if provenance is not None:
        _approval_provenance(provenance, f"{path}.approval_provenance", errors)
    _string(value.get("target_review_command"), f"{path}.target_review_command", errors)
    commands = value.get("verification_commands")
    if _array(commands, f"{path}.verification_commands", errors):
        seen: set[str] = set()
        for index, item in enumerate(commands):
            item_path = f"{path}.verification_commands[{index}]"
            if not _object(item, item_path, errors):
                continue
            fields = {"command", "previous_status", "evidence_refs", "proof_source"}
            _fields(item, item_path, fields, fields, errors)
            _string(item.get("command"), f"{item_path}.command", errors)
            if item.get("previous_status") not in _CHECK_STATUSES:
                errors.append(f"{item_path}.previous_status: has invalid completion check status")
            _ref_array(item.get("evidence_refs"), f"{item_path}.evidence_refs", errors)
            _string(
                item.get("proof_source"),
                f"{item_path}.proof_source",
                errors,
                pattern=_CHECK_PROOF_SOURCE,
            )
            command = item.get("command")
            if isinstance(command, str):
                if command in seen:
                    errors.append(f"{item_path}.command: duplicate verification command")
                seen.add(command)
    resolution_commands = value.get("evidence_resolution_commands")
    _string_array(resolution_commands, f"{path}.evidence_resolution_commands", errors)
    if isinstance(resolution_commands, list):
        if len(set(resolution_commands)) != len(resolution_commands):
            errors.append(f"{path}.evidence_resolution_commands: must not contain duplicates")
        for index, command in enumerate(resolution_commands):
            if isinstance(command, str) and _EVIDENCE_SHOW_COMMAND.fullmatch(command) is None:
                errors.append(
                    f"{path}.evidence_resolution_commands[{index}]: has invalid command format"
                )
    _bounded_string_array(value.get("changed_paths"), f"{path}.changed_paths", errors)
    _bounded_string_array(
        value.get("documentation_candidates"),
        f"{path}.documentation_candidates",
        errors,
    )


def _approval_provenance(value: Any, path: str, errors: list[str]) -> None:
    if not _object(value, path, errors):
        return
    required = {"event_id", "actor_kind", "actor", "source", "timestamp", "target", "bound_evidence"}
    allowed = required | {"recorder_kind", "recorder", "source_kind", "source_ref"}
    _fields(value, path, required, allowed, errors)
    _string(value.get("event_id"), f"{path}.event_id", errors)
    if value.get("actor_kind") not in {"human", "agent", "system"}:
        errors.append(f"{path}.actor_kind: must be one of human, agent, system")
    if value.get("recorder_kind") is not None and value.get("recorder_kind") not in {"human", "agent", "system"}:
        errors.append(f"{path}.recorder_kind: must be one of human, agent, system")
    for name in ("actor", "source", "timestamp"):
        _string(value.get(name), f"{path}.{name}", errors)
    for name in ("recorder", "source_kind"):
        if value.get(name) is not None:
            _string(value.get(name), f"{path}.{name}", errors)
    if value.get("source_ref") is not None and not isinstance(value.get("source_ref"), str):
        errors.append(f"{path}.source_ref: must be a string")
    target = value.get("target")
    if _object(target, f"{path}.target", errors):
        _fields(target, f"{path}.target", {"type", "id"}, {"type", "id"}, errors)
        _string(target.get("type"), f"{path}.target.type", errors)
        _string(target.get("id"), f"{path}.target.id", errors)
    bound = value.get("bound_evidence")
    if _object(bound, f"{path}.bound_evidence", errors):
        _fields(
            bound,
            f"{path}.bound_evidence",
            {"id", "artifact_sha256"},
            {"id", "artifact_sha256"},
            errors,
        )
        _string(bound.get("id"), f"{path}.bound_evidence.id", errors)
        _string(bound.get("artifact_sha256"), f"{path}.bound_evidence.artifact_sha256", errors)


def _optional_ref(value: Any, path: str, errors: list[str]) -> None:
    if value is not None:
        _string(value, path, errors, pattern=_EVIDENCE_REF)


def _bounded_string_array(value: Any, path: str, errors: list[str]) -> None:
    _string_array(value, path, errors)
    if isinstance(value, list):
        if len(value) > 50:
            errors.append(f"{path}: must contain at most 50 items")
        if len(set(value)) != len(value):
            errors.append(f"{path}: must not contain duplicates")


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


def _positive_int(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        errors.append(f"{path}: must be a positive integer")


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
