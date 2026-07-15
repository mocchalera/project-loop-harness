from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


INTENT_INDEX_CONTRACT_VERSION = "intent-index/v0"
INTENT_INDEX_BINDING_CONTRACT_VERSION = "intent-index-binding/v0"
TRACE_CLAIM_MAX_ITEMS = 8
TRACE_CLAIM_MAX_BYTES = 4096


@dataclass(frozen=True)
class IntentIndexValidationResult:
    diagnostics: tuple[dict[str, str], ...]

    @property
    def ok(self) -> bool:
        return not self.diagnostics

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(
            f"{item['code']}: {item['path']}: {item['message']}"
            for item in self.diagnostics
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": INTENT_INDEX_CONTRACT_VERSION,
            "diagnostics": list(self.diagnostics),
            "errors": list(self.errors),
            "ok": self.ok,
            "validation_scope": "structure_only",
            "evidence_binding_checked": False,
            "semantic_validation": False,
        }


def load_intent_index(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_non_finite)


def validate_intent_index(value: Any) -> IntentIndexValidationResult:
    diagnostics: list[dict[str, str]] = []
    if not isinstance(value, dict):
        _add(diagnostics, "intent_index_not_object", "$", "must be an object")
        return IntentIndexValidationResult(tuple(diagnostics))

    if value.get("contract_version") != INTENT_INDEX_CONTRACT_VERSION:
        _add(
            diagnostics,
            "unsupported_intent_index_contract",
            "$.contract_version",
            f"must equal {INTENT_INDEX_CONTRACT_VERSION}",
        )
    for field in ("index_id", "generated_at", "generator"):
        _required_string(value.get(field), f"$.{field}", diagnostics)

    source = value.get("source_trace")
    if not isinstance(source, dict):
        _add(diagnostics, "source_trace_not_object", "$.source_trace", "must be an object")
    else:
        for field in ("evidence_id", "manifest_path", "member_path", "stored_path", "sha256"):
            _required_string(source.get(field), f"$.source_trace.{field}", diagnostics)
        digest = source.get("sha256")
        if isinstance(digest, str) and (
            len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
        ):
            _add(
                diagnostics,
                "trace_hash_invalid",
                "$.source_trace.sha256",
                "must be a lowercase 64-character SHA-256",
            )

    items = value.get("items")
    if not isinstance(items, list):
        _add(diagnostics, "items_not_array", "$.items", "must be an array")
        return IntentIndexValidationResult(tuple(diagnostics))

    seen_ids: set[str] = set()
    for item_index, item in enumerate(items):
        item_path = f"$.items[{item_index}]"
        if not isinstance(item, dict):
            _add(diagnostics, "item_not_object", item_path, "must be an object")
            continue
        item_id = item.get("id")
        _required_string(item_id, f"{item_path}.id", diagnostics)
        if isinstance(item_id, str) and item_id:
            if item_id in seen_ids:
                _add(diagnostics, "duplicate_item_id", f"{item_path}.id", "must be unique")
            seen_ids.add(item_id)
        for field in ("kind", "claim"):
            _required_string(item.get(field), f"{item_path}.{field}", diagnostics)
        refs = item.get("source_refs")
        if not isinstance(refs, list):
            _add(diagnostics, "source_refs_not_array", f"{item_path}.source_refs", "must be an array")
            continue
        if not refs:
            _add(diagnostics, "empty_source_refs", f"{item_path}.source_refs", "must not be empty")
            continue
        for ref_index, ref in enumerate(refs):
            ref_path = f"{item_path}.source_refs[{ref_index}]"
            if not isinstance(ref, dict):
                _add(diagnostics, "source_ref_not_object", ref_path, "must be an object")
                continue
            for field in ("evidence_id", "stored_path"):
                _required_string(ref.get(field), f"{ref_path}.{field}", diagnostics)
            start = ref.get("line_start")
            end = ref.get("line_end")
            if not _positive_int(start):
                _add(diagnostics, "line_start_invalid", f"{ref_path}.line_start", "must be a positive integer")
            if not _positive_int(end):
                _add(diagnostics, "line_end_invalid", f"{ref_path}.line_end", "must be a positive integer")
            if _positive_int(start) and _positive_int(end) and start > end:
                _add(diagnostics, "reversed_line_range", ref_path, "line_start must be <= line_end")

    return IntentIndexValidationResult(tuple(diagnostics))


def validate_intent_index_binding(
    value: Any,
    *,
    trace_evidence_id: str,
    trace_manifest_path: str,
    trace_member_path: str,
    trace_stored_path: str,
    recorded_trace_sha256: str,
    trace_bytes: bytes,
) -> dict[str, Any]:
    structural = validate_intent_index(value)
    diagnostics = list(structural.diagnostics)
    actual_sha256 = hashlib.sha256(trace_bytes).hexdigest()
    line_count = len(trace_bytes.decode("utf-8").splitlines())
    source = value.get("source_trace") if isinstance(value, dict) else None

    if isinstance(source, dict):
        checks = (
            ("evidence_id", trace_evidence_id, "trace_evidence_mismatch"),
            ("manifest_path", trace_manifest_path, "trace_manifest_path_mismatch"),
            ("member_path", trace_member_path, "trace_member_path_mismatch"),
            ("stored_path", trace_stored_path, "trace_stored_path_mismatch"),
            ("sha256", recorded_trace_sha256, "trace_hash_mismatch"),
        )
        for field, expected, code in checks:
            if isinstance(source.get(field), str) and source[field] != expected:
                _add(diagnostics, code, f"$.source_trace.{field}", "does not match copied trace Evidence")
        if recorded_trace_sha256 != actual_sha256:
            _add(
                diagnostics,
                "recorded_trace_hash_mismatch",
                "$.source_trace.sha256",
                "recorded trace SHA-256 does not match copied bytes",
            )
        items = value.get("items") if isinstance(value, dict) else None
        if isinstance(items, list):
            for item_index, item in enumerate(items):
                if not isinstance(item, dict) or not isinstance(item.get("source_refs"), list):
                    continue
                for ref_index, ref in enumerate(item["source_refs"]):
                    if not isinstance(ref, dict):
                        continue
                    path = f"$.items[{item_index}].source_refs[{ref_index}]"
                    if isinstance(ref.get("evidence_id"), str) and ref["evidence_id"] != source.get("evidence_id"):
                        _add(diagnostics, "source_ref_evidence_mismatch", f"{path}.evidence_id", "does not match source_trace")
                    if isinstance(ref.get("stored_path"), str) and ref["stored_path"] != source.get("stored_path"):
                        _add(diagnostics, "source_ref_stored_path_mismatch", f"{path}.stored_path", "does not match source_trace")
                    start = ref.get("line_start")
                    end = ref.get("line_end")
                    if _positive_int(start) and _positive_int(end) and start <= end and end > line_count:
                        _add(diagnostics, "line_range_out_of_bounds", path, "line range exceeds copied trace")

    return {
        "contract_version": INTENT_INDEX_BINDING_CONTRACT_VERSION,
        "status": "valid" if not diagnostics else "invalid",
        "diagnostics": diagnostics,
        "trace": {
            "evidence_id": trace_evidence_id,
            "manifest_path": trace_manifest_path,
            "member_path": trace_member_path,
            "stored_path": trace_stored_path,
            "recorded_sha256": recorded_trace_sha256,
            "actual_sha256": actual_sha256,
            "line_count": line_count,
        },
        "structural_validation": structural.ok,
        "source_binding_checked": True,
        "semantic_validation": False,
    }


def select_trace_claim_refs(
    value: Any,
    *,
    intent_index_ref: str,
    max_items: int = TRACE_CLAIM_MAX_ITEMS,
    max_bytes: int = TRACE_CLAIM_MAX_BYTES,
) -> dict[str, Any]:
    """Select complete unverified claim refs under deterministic item/byte caps."""

    if not validate_intent_index(value).ok:
        return {
            "trace_claim_refs": [],
            "trace_claim_ref_omissions": [],
            "trace_claim_ref_budget": _claim_budget(max_items, max_bytes, 0, 0),
        }
    items = sorted(value["items"], key=lambda item: str(item["id"]))
    selected: list[dict[str, Any]] = []
    omissions: list[dict[str, str]] = []
    selected_bytes = 0
    for item in items:
        claim_ref = {
            "intent_index_ref": intent_index_ref,
            "item_id": str(item["id"]),
            "kind": str(item["kind"]),
            "claim": str(item["claim"]),
            "trust": "unverified",
            "source_refs": sorted(
                [
                {
                    "evidence_id": str(ref["evidence_id"]),
                    "stored_path": str(ref["stored_path"]),
                    "line_start": int(ref["line_start"]),
                    "line_end": int(ref["line_end"]),
                }
                for ref in item["source_refs"]
                ],
                key=lambda ref: (
                    ref["evidence_id"],
                    ref["stored_path"],
                    ref["line_start"],
                    ref["line_end"],
                ),
            ),
        }
        item_bytes = len(
            json.dumps(
                claim_ref,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        if len(selected) >= max_items or selected_bytes + item_bytes > max_bytes:
            omissions.append({"item_id": claim_ref["item_id"], "reason": "packet_budget"})
            continue
        selected.append(claim_ref)
        selected_bytes += item_bytes
    return {
        "trace_claim_refs": selected,
        "trace_claim_ref_omissions": omissions,
        "trace_claim_ref_budget": _claim_budget(
            max_items,
            max_bytes,
            len(selected),
            selected_bytes,
        ),
    }


def _required_string(value: Any, path: str, diagnostics: list[dict[str, str]]) -> None:
    if not isinstance(value, str) or not value:
        _add(diagnostics, "required_string", path, "must be a non-empty string")


def _claim_budget(
    max_items: int,
    max_bytes: int,
    included_items: int,
    included_bytes: int,
) -> dict[str, int]:
    return {
        "max_items": max_items,
        "max_bytes": max_bytes,
        "included_items": included_items,
        "included_bytes": included_bytes,
    }


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _add(diagnostics: list[dict[str, str]], code: str, path: str, message: str) -> None:
    diagnostics.append({"code": code, "path": path, "message": message})


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")
