from __future__ import annotations

import copy
import hashlib
from pathlib import PurePosixPath
from typing import Any

from ._profile_contract import (
    ProfileContractValidationResult,
    canonical_json,
    duplicate_ids,
    load_strict_json,
    schema_resource,
    validate_schema,
)


PROFILE_OUTPUT_BUNDLE_CONTRACT_VERSION = "profile-output-bundle/v1"
SCHEMA_RESOURCE = "profile-output-bundle-v1.schema.json"

_ROLE_CONTRACT = {
    "run_manifest": "council-run/v0",
    "claims": "claim-set/v0",
    "verification_plan": "verification-plan/v0",
    "decision_proposal": "decision-proposal/v0",
    "revised_work_brief": "work-brief/v1",
    "report": "agent-output/v1",
}
_JSON_ROLES = set(_ROLE_CONTRACT) - {"report"}


def profile_output_bundle_schema() -> dict[str, Any]:
    return schema_resource(SCHEMA_RESOURCE)


def load_profile_output_bundle(path: str) -> Any:
    return load_strict_json(path)


def bundle_digest(value: dict[str, Any]) -> str:
    normalized = copy.deepcopy(value)
    normalized.pop("bundle_digest", None)
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


def validate_profile_output_bundle(value: Any) -> ProfileContractValidationResult:
    errors = validate_schema(value, profile_output_bundle_schema())
    if not isinstance(value, dict):
        return ProfileContractValidationResult(
            PROFILE_OUTPUT_BUNDLE_CONTRACT_VERSION,
            tuple(errors),
        )

    digest = value.get("bundle_digest")
    if isinstance(digest, dict) and digest.get("value") != bundle_digest(value):
        errors.append("$.bundle_digest.value: does not match the canonical bundle")

    artifacts = value.get("artifacts")
    artifact_ids = duplicate_ids(
        artifacts,
        field="artifact_id",
        path="$.artifacts",
        errors=errors,
    )
    paths: list[str] = []
    decision_ids: set[str] = set()
    if isinstance(artifacts, list):
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                continue
            path = str(artifact.get("path") or "")
            paths.append(path)
            if path and (
                PurePosixPath(path).is_absolute()
                or any(part in {"", ".", ".."} for part in path.split("/"))
            ):
                errors.append(f"$.artifacts[{index}].path: must be a normalized relative path")
            role = artifact.get("role")
            expected_contract = _ROLE_CONTRACT.get(role)
            if expected_contract and artifact.get("contract_version") != expected_contract:
                errors.append(
                    f"$.artifacts[{index}].contract_version: does not match role {role!r}"
                )
            if role in _JSON_ROLES and artifact.get("media_type") != "application/json":
                errors.append(
                    f"$.artifacts[{index}].media_type: role {role!r} requires application/json"
                )
            if role == "report" and artifact.get("media_type") != "text/markdown":
                errors.append(
                    f"$.artifacts[{index}].media_type: report requires text/markdown"
                )
            if role == "decision_proposal" and isinstance(
                artifact.get("artifact_id"), str
            ):
                decision_ids.add(str(artifact["artifact_id"]))
    if len(paths) != len(set(paths)):
        errors.append("$.artifacts: paths must be unique")
    folded = [path.casefold() for path in paths]
    if len(folded) != len(set(folded)):
        errors.append("$.artifacts: paths must be unique after case folding")

    proposal_refs = value.get("decision_proposal_artifact_ids")
    if isinstance(proposal_refs, list):
        unknown = sorted(set(proposal_refs) - artifact_ids)
        if unknown:
            errors.append(
                "$.decision_proposal_artifact_ids: unknown artifact IDs "
                + ", ".join(unknown)
            )
        wrong_role = sorted(set(proposal_refs) - decision_ids)
        if wrong_role:
            errors.append(
                "$.decision_proposal_artifact_ids: referenced artifacts must have decision_proposal role"
            )
        status = value.get("status")
        if status == "needs_human" and not 1 <= len(proposal_refs) <= 3:
            errors.append(
                "$.decision_proposal_artifact_ids: needs_human requires one to three proposals"
            )
        if status == "failed" and proposal_refs:
            errors.append(
                "$.decision_proposal_artifact_ids: failed bundles cannot propose decisions"
            )

    return ProfileContractValidationResult(
        PROFILE_OUTPUT_BUNDLE_CONTRACT_VERSION,
        tuple(errors),
    )

