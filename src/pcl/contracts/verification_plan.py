from __future__ import annotations

from typing import Any

from ._profile_contract import (
    ProfileContractValidationResult,
    duplicate_ids,
    load_strict_json,
    schema_resource,
    validate_schema,
)


VERIFICATION_PLAN_CONTRACT_VERSION = "verification-plan/v0"
SCHEMA_RESOURCE = "verification-plan-v0.schema.json"


def verification_plan_schema() -> dict[str, Any]:
    return schema_resource(SCHEMA_RESOURCE)


def load_verification_plan(path: str) -> Any:
    return load_strict_json(path)


def validate_verification_plan(value: Any) -> ProfileContractValidationResult:
    errors = validate_schema(value, verification_plan_schema())
    if isinstance(value, dict):
        duplicate_ids(
            value.get("items"),
            field="verification_item_id",
            path="$.items",
            errors=errors,
        )
    return ProfileContractValidationResult(
        VERIFICATION_PLAN_CONTRACT_VERSION,
        tuple(errors),
    )

