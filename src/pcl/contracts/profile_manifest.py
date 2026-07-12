from __future__ import annotations

from typing import Any

from ._profile_contract import (
    ProfileContractValidationResult,
    load_strict_json,
    schema_resource,
    validate_schema,
)


PROFILE_MANIFEST_CONTRACT_VERSION = "profile-manifest/v1"
SCHEMA_RESOURCE = "profile-manifest-v1.schema.json"


def profile_manifest_schema() -> dict[str, Any]:
    return schema_resource(SCHEMA_RESOURCE)


def load_profile_manifest(path: str) -> Any:
    return load_strict_json(path)


def validate_profile_manifest(value: Any) -> ProfileContractValidationResult:
    errors = validate_schema(value, profile_manifest_schema())
    return ProfileContractValidationResult(
        PROFILE_MANIFEST_CONTRACT_VERSION,
        tuple(errors),
    )

