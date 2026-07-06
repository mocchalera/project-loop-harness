from __future__ import annotations

import json
from json import JSONDecodeError
import re
from typing import Any

from .code_context.receipts import (
    CONTEXT_RECEIPT_EVIDENCE_TYPE,
    CONTEXT_RECEIPT_VERSION,
    evidence_ref_by_id,
    latest_context_receipt_ref,
    resolve_context_receipt_path,
)
from .code_context.summary import summarize_code_context_receipt
from .errors import InvalidInputError
from .guards import require_initialized
from .paths import ProjectPaths


RECEIPT_NEXT_ACTIONS = ["pcl index build --json", "pcl impact --diff --json"]
EVIDENCE_ID_RE = re.compile(r"^E-\d+$")


def receipt_summary_for_ref(
    paths: ProjectPaths,
    *,
    ref: str | None = None,
    latest: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    receipt_ref = _resolve_receipt_ref(paths, ref=ref, latest=latest)
    receipt = _load_receipt_payload(paths, receipt_ref)
    summary = summarize_code_context_receipt(receipt)
    _merge_resolved_receipt_ref(summary, receipt_ref)
    return summary


def _resolve_receipt_ref(
    paths: ProjectPaths,
    *,
    ref: str | None,
    latest: bool,
) -> dict[str, str | None]:
    if latest:
        if ref:
            raise _receipt_error(
                "--latest cannot be combined with a receipt ref. Next action: "
                "run `pcl receipt show --latest` or pass a single receipt ref.",
                receipt_error="ambiguous_receipt_ref",
                next_actions=["pcl receipt show --latest"],
            )
        latest_ref = latest_context_receipt_ref(paths)
        if latest_ref is None:
            raise _receipt_error(
                "No context receipt evidence was found. Next action: "
                "`pcl index build --json`, then `pcl impact --diff --json`.",
                receipt_error="missing_receipt",
                next_actions=RECEIPT_NEXT_ACTIONS,
            )
        return latest_ref

    if not ref:
        raise _receipt_error(
            "Provide a context receipt evidence id or receipt path, or use --latest. "
            "Next action: create a receipt with `pcl impact --diff --json`.",
            receipt_error="missing_receipt_ref",
            next_actions=["pcl impact --diff --json"],
        )

    if EVIDENCE_ID_RE.fullmatch(ref):
        evidence_ref = evidence_ref_by_id(paths, ref)
        if evidence_ref is None:
            raise _receipt_error(
                f"Evidence id not found: {ref}. Next action: pass a context_receipt "
                "evidence id, pass a receipt path, or run `pcl impact --diff --json`.",
                receipt_error="unknown_evidence_id",
                next_actions=["pcl impact --diff --json"],
                evidence_id=ref,
            )
        evidence_type = evidence_ref.get("evidence_type")
        if evidence_type != CONTEXT_RECEIPT_EVIDENCE_TYPE:
            raise _receipt_error(
                f"Evidence {ref} has type {evidence_type!r}, not "
                f"{CONTEXT_RECEIPT_EVIDENCE_TYPE!r}. Next action: pass a "
                "context_receipt evidence id or receipt path.",
                receipt_error="non_receipt_evidence_id",
                next_actions=["pcl receipt show --latest"],
                evidence_id=ref,
                evidence_type=evidence_type,
            )
        return {
            "evidence_id": evidence_ref["evidence_id"],
            "receipt_path": evidence_ref["receipt_path"],
            "created_at": evidence_ref["created_at"],
        }

    return {"evidence_id": None, "receipt_path": ref, "created_at": None}


def _load_receipt_payload(
    paths: ProjectPaths,
    receipt_ref: dict[str, str | None],
) -> dict[str, Any]:
    receipt_path_value = receipt_ref.get("receipt_path")
    if not receipt_path_value:
        raise _receipt_error(
            "Context receipt evidence has no receipt path. Next action: run "
            "`pcl impact --diff --json` to create a fresh receipt.",
            receipt_error="missing_receipt_path",
            next_actions=["pcl impact --diff --json"],
            evidence_id=receipt_ref.get("evidence_id"),
        )

    receipt_path = resolve_context_receipt_path(paths, receipt_path_value)
    try:
        raw = receipt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _receipt_error(
            f"Context receipt file does not exist or cannot be loaded: "
            f"{receipt_path_value}. Next action: pass an existing receipt path "
            "or run `pcl impact --diff --json`.",
            receipt_error="missing_receipt_file",
            next_actions=["pcl impact --diff --json"],
            evidence_id=receipt_ref.get("evidence_id"),
            receipt_path=receipt_path_value,
        ) from exc

    try:
        payload = json.loads(raw)
    except JSONDecodeError as exc:
        raise _receipt_error(
            f"Context receipt is not valid JSON: {receipt_path_value}. Next action: "
            "run `pcl impact --diff --json` to create a fresh receipt.",
            receipt_error="invalid_receipt_json",
            next_actions=["pcl impact --diff --json"],
            receipt_path=receipt_path_value,
        ) from exc

    if not isinstance(payload, dict):
        raise _receipt_error(
            f"Context receipt is not a JSON object: {receipt_path_value}. Next action: "
            "run `pcl impact --diff --json` to create a fresh receipt.",
            receipt_error="invalid_receipt_json",
            next_actions=["pcl impact --diff --json"],
            receipt_path=receipt_path_value,
        )

    contract_version = payload.get("contract_version")
    if contract_version != CONTEXT_RECEIPT_VERSION:
        raise _receipt_error(
            f"Unsupported context receipt contract version: "
            f"{contract_version or 'missing'}. Expected {CONTEXT_RECEIPT_VERSION}. "
            "Next action: run `pcl impact --diff --json` to create a fresh receipt.",
            receipt_error="wrong_receipt_contract_version",
            next_actions=["pcl impact --diff --json"],
            receipt_path=receipt_path_value,
            contract_version=contract_version,
            expected_contract_version=CONTEXT_RECEIPT_VERSION,
        )

    return payload


def _merge_resolved_receipt_ref(
    summary: dict[str, Any],
    receipt_ref: dict[str, str | None],
) -> None:
    summary_ref = summary.get("receipt_ref")
    if not isinstance(summary_ref, dict):
        summary_ref = {}
    summary["receipt_ref"] = {
        "evidence_id": summary_ref.get("evidence_id") or receipt_ref.get("evidence_id"),
        "receipt_path": summary_ref.get("receipt_path") or receipt_ref.get("receipt_path"),
        "created_at": summary_ref.get("created_at") or receipt_ref.get("created_at"),
    }


def _receipt_error(
    message: str,
    *,
    receipt_error: str,
    next_actions: list[str],
    **details: Any,
) -> InvalidInputError:
    payload = {
        "receipt_error": receipt_error,
        "next_actions": next_actions,
        **{key: value for key, value in details.items() if value is not None},
    }
    return InvalidInputError(message, details=payload)
