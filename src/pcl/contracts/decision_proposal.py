from __future__ import annotations

from typing import Any

from ._profile_contract import (
    ProfileContractValidationResult,
    duplicate_ids,
    load_strict_json,
    schema_resource,
    validate_schema,
)


DECISION_PROPOSAL_CONTRACT_VERSION = "decision-proposal/v0"
SCHEMA_RESOURCE = "decision-proposal-v0.schema.json"


def decision_proposal_schema() -> dict[str, Any]:
    return schema_resource(SCHEMA_RESOURCE)


def load_decision_proposal(path: str) -> Any:
    return load_strict_json(path)


def validate_decision_proposal(value: Any) -> ProfileContractValidationResult:
    errors = validate_schema(value, decision_proposal_schema())
    if isinstance(value, dict):
        candidate_ids = duplicate_ids(
            value.get("candidates"),
            field="candidate_id",
            path="$.candidates",
            errors=errors,
        )
        recommended = value.get("recommended_candidate_id")
        if isinstance(recommended, str) and recommended not in candidate_ids:
            errors.append(
                "$.recommended_candidate_id: decision_proposal_reference_missing"
            )
        opinions = value.get("minority_opinions")
        if isinstance(opinions, list):
            for index, opinion in enumerate(opinions):
                if not isinstance(opinion, dict):
                    continue
                candidate_id = opinion.get("candidate_id")
                if candidate_id is not None and candidate_id not in candidate_ids:
                    errors.append(
                        f"$.minority_opinions[{index}].candidate_id: unknown candidate"
                    )
    return ProfileContractValidationResult(
        DECISION_PROPOSAL_CONTRACT_VERSION,
        tuple(errors),
    )
