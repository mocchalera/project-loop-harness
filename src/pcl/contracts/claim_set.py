from __future__ import annotations

from typing import Any

from ._profile_contract import (
    ProfileContractValidationResult,
    duplicate_ids,
    load_strict_json,
    schema_resource,
    validate_schema,
)


CLAIM_SET_CONTRACT_VERSION = "claim-set/v0"
SCHEMA_RESOURCE = "claim-set-v0.schema.json"


def claim_set_schema() -> dict[str, Any]:
    return schema_resource(SCHEMA_RESOURCE)


def load_claim_set(path: str) -> Any:
    return load_strict_json(path)


def validate_claim_set(value: Any) -> ProfileContractValidationResult:
    errors = validate_schema(value, claim_set_schema())
    if isinstance(value, dict):
        duplicate_ids(
            value.get("claims"),
            field="claim_id",
            path="$.claims",
            errors=errors,
        )
    return ProfileContractValidationResult(CLAIM_SET_CONTRACT_VERSION, tuple(errors))

