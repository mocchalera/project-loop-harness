from __future__ import annotations

from typing import Any

from ._profile_contract import (
    ProfileContractValidationResult,
    duplicate_ids,
    load_strict_json,
    schema_resource,
    validate_schema,
)


COUNCIL_RUN_CONTRACT_VERSION = "council-run/v0"
SCHEMA_RESOURCE = "council-run-v0.schema.json"


def council_run_schema() -> dict[str, Any]:
    return schema_resource(SCHEMA_RESOURCE)


def load_council_run(path: str) -> Any:
    return load_strict_json(path)


def validate_council_run(value: Any) -> ProfileContractValidationResult:
    errors = validate_schema(value, council_run_schema())
    if isinstance(value, dict):
        participant_ids = duplicate_ids(
            value.get("participants"),
            field="participant_id",
            path="$.participants",
            errors=errors,
        )
        rounds = value.get("rounds")
        if isinstance(rounds, list):
            round_numbers: set[int] = set()
            for index, round_item in enumerate(rounds):
                if not isinstance(round_item, dict):
                    continue
                number = round_item.get("round")
                if isinstance(number, int) and number in round_numbers:
                    errors.append(f"$.rounds[{index}].round: duplicate round number")
                if isinstance(number, int):
                    round_numbers.add(number)
                refs = round_item.get("participant_ids")
                if isinstance(refs, list):
                    unknown = sorted(set(refs) - participant_ids)
                    if unknown:
                        errors.append(
                            f"$.rounds[{index}].participant_ids: unknown participants "
                            + ", ".join(unknown)
                        )
    return ProfileContractValidationResult(COUNCIL_RUN_CONTRACT_VERSION, tuple(errors))

