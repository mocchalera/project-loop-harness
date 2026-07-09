from __future__ import annotations

from typing import Any


def _receipt_target_binding_agrees(
    receipt_payload: Any,
    *,
    target_type: str,
    target_id: str,
) -> bool:
    if not isinstance(receipt_payload, dict):
        return False
    binding = receipt_payload.get("target_binding")
    if not isinstance(binding, dict):
        return False
    return (
        str(binding.get("target_type")) == target_type
        and str(binding.get("target_id")) == target_id
    )
