from __future__ import annotations

import copy
import hashlib
from typing import Any

from ._profile_contract import (
    ProfileContractValidationResult,
    canonical_json,
    load_strict_json,
    schema_resource,
    validate_schema,
)


PROFILE_RUN_REQUEST_CONTRACT_VERSION = "profile-run-request/v1"
SCHEMA_RESOURCE = "profile-run-request-v1.schema.json"

_DATA_CLASS = {
    "none": "metadata",
    "selected_snippets": "selected_snippets",
    "full_allowed": "full_repository",
}


def profile_run_request_schema() -> dict[str, Any]:
    return schema_resource(SCHEMA_RESOURCE)


def load_profile_run_request(path: str) -> Any:
    return load_strict_json(path)


def request_basis_digest(value: dict[str, Any]) -> str:
    normalized = copy.deepcopy(value)
    for field in (
        "generated_at",
        "authorization",
        "request_digest",
        "request_basis_digest",
    ):
        normalized.pop(field, None)
    context = normalized.get("context")
    if isinstance(context, dict):
        context.pop("receipt_age", None)
        context.pop("age_warning", None)
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


def request_digest(value: dict[str, Any]) -> str:
    normalized = copy.deepcopy(value)
    normalized.pop("request_digest", None)
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


def validate_profile_run_request(value: Any) -> ProfileContractValidationResult:
    errors = validate_schema(value, profile_run_request_schema())
    if not isinstance(value, dict):
        return ProfileContractValidationResult(
            PROFILE_RUN_REQUEST_CONTRACT_VERSION,
            tuple(errors),
        )

    expected_basis = request_basis_digest(value)
    basis = value.get("request_basis_digest")
    if isinstance(basis, dict) and basis.get("value") != expected_basis:
        errors.append(
            "$.request_basis_digest.value: does not match the canonical request basis"
        )
    expected_request = request_digest(value)
    digest = value.get("request_digest")
    if isinstance(digest, dict) and digest.get("value") != expected_request:
        errors.append("$.request_digest.value: does not match the canonical request")

    _validate_authorization(value, expected_basis, errors)
    return ProfileContractValidationResult(
        PROFILE_RUN_REQUEST_CONTRACT_VERSION,
        tuple(errors),
    )


def _validate_authorization(
    value: dict[str, Any],
    expected_basis: str,
    errors: list[str],
) -> None:
    policy = value.get("data_policy")
    if not isinstance(policy, dict):
        return
    authorization = value.get("authorization")
    if not isinstance(authorization, dict):
        return

    if authorization.get("request_basis_digest") != expected_basis:
        errors.append(
            "$.authorization.request_basis_digest: profile_authorization_basis_mismatch"
        )
    if authorization.get("target") != value.get("target"):
        errors.append("$.authorization.target: must equal the request target")
    if authorization.get("actor_kind") != "human":
        errors.append("$.authorization.actor_kind: must equal 'human'")
    actor = authorization.get("actor")
    recorder = authorization.get("recorder")
    actor_kind = authorization.get("actor_kind")
    recorder_kind = authorization.get("recorder_kind")
    mediated = recorder != actor or recorder_kind != actor_kind
    if mediated:
        if authorization.get("source_kind") not in {"conversation", "cockpit"}:
            errors.append(
                "$.authorization.source_kind: mediated human approval requires conversation or cockpit"
            )
        if not str(authorization.get("source_ref") or "").strip():
            errors.append(
                "$.authorization.source_ref: mediated human approval requires a source ref"
            )

    scope = authorization.get("scope")
    if not isinstance(scope, dict):
        return
    if scope.get("revoked_event_id") is not None:
        errors.append("$.authorization.scope: revoked authorization cannot be used")
    required_class = _DATA_CLASS.get(policy.get("repository_content_policy"))
    classes = scope.get("data_classes")
    if required_class and (
        not isinstance(classes, list) or required_class not in classes
    ):
        errors.append(
            "$.authorization.scope.data_classes: does not cover repository_content_policy"
        )
    requested_providers = policy.get("allowed_providers")
    allowed_providers = scope.get("allowed_providers")
    if isinstance(requested_providers, list) and isinstance(allowed_providers, list):
        missing = sorted(set(requested_providers) - set(allowed_providers))
        if missing:
            errors.append(
                "$.authorization.scope.allowed_providers: missing requested providers "
                + ", ".join(missing)
            )
    if policy.get("paid_service_requested") is True:
        if scope.get("max_cost") is None:
            errors.append("$.authorization.scope.max_cost: is required for paid service use")
        if scope.get("currency") is None:
            errors.append("$.authorization.scope.currency: is required for paid service use")
