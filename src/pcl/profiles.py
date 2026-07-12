from __future__ import annotations

import hashlib
from importlib.resources import files
import json
from typing import Any

from .contracts.claim_set import CLAIM_SET_CONTRACT_VERSION
from .contracts.council_run import COUNCIL_RUN_CONTRACT_VERSION
from .contracts.decision_proposal import DECISION_PROPOSAL_CONTRACT_VERSION
from .contracts.profile_manifest import validate_profile_manifest
from .contracts.profile_output_bundle import PROFILE_OUTPUT_BUNDLE_CONTRACT_VERSION
from .contracts.profile_run_request import PROFILE_RUN_REQUEST_CONTRACT_VERSION
from .contracts.verification_plan import VERIFICATION_PLAN_CONTRACT_VERSION
from .contracts.work_brief import WORK_BRIEF_CONTRACT_VERSION
from .errors import InvalidInputError


PROFILE_REGISTRY_CONTRACT_VERSION = "profile-registry/v1"
PROFILE_ENTRY_CONTRACT_VERSION = "profile-registry-entry/v1"
PROFILE_VALIDATION_CONTRACT_VERSION = "profile-validation/v1"
BUILTIN_PROFILE_RESOURCES = {
    "council.discovery": "profiles/builtin/council.discovery.json",
}
SUPPORTED_CONTRACTS = {
    PROFILE_RUN_REQUEST_CONTRACT_VERSION,
    PROFILE_OUTPUT_BUNDLE_CONTRACT_VERSION,
    COUNCIL_RUN_CONTRACT_VERSION,
    CLAIM_SET_CONTRACT_VERSION,
    VERIFICATION_PLAN_CONTRACT_VERSION,
    DECISION_PROPOSAL_CONTRACT_VERSION,
    WORK_BRIEF_CONTRACT_VERSION,
}


def list_profiles() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for runner_profile_id in sorted(BUILTIN_PROFILE_RESOURCES):
        entry = show_profile(runner_profile_id)
        manifest = entry["manifest"]
        entries.append(
            {
                "runner_profile_id": runner_profile_id,
                "profile_version": manifest["profile_version"],
                "display_name": manifest["display_name"],
                "profile_kind": manifest["profile_kind"],
                "supported_routes": list(manifest["supported_routes"]),
                "source": entry["source"],
                "trust": entry["trust"],
                "manifest_sha256": entry["manifest_sha256"],
                "executed_by_plh": False,
            }
        )
    return {
        "contract_version": PROFILE_REGISTRY_CONTRACT_VERSION,
        "profiles": entries,
    }


def show_profile(runner_profile_id: str) -> dict[str, Any]:
    manifest, raw = _load_builtin(runner_profile_id)
    return {
        "contract_version": PROFILE_ENTRY_CONTRACT_VERSION,
        "runner_profile_id": runner_profile_id,
        "source": "builtin",
        "trust": "builtin",
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "executed_by_plh": False,
        "manifest": manifest,
    }


def validate_profile(runner_profile_id: str) -> dict[str, Any]:
    entry = show_profile(runner_profile_id)
    manifest = entry["manifest"]
    validation = validate_profile_manifest(manifest)
    errors = list(validation.errors)

    if manifest.get("runner_profile_id") != runner_profile_id:
        errors.append(
            "$.runner_profile_id: does not match the built-in registry key"
        )
    required_contracts = {
        manifest.get("input_contract"),
        manifest.get("output_contract"),
    }
    produced = manifest.get("produced_contracts")
    if isinstance(produced, list):
        required_contracts.update(produced)
    unsupported = sorted(
        str(item)
        for item in required_contracts
        if isinstance(item, str) and item not in SUPPORTED_CONTRACTS
    )
    if unsupported:
        errors.append(
            "$.produced_contracts: unsupported contracts " + ", ".join(unsupported)
        )
    external_runner = manifest.get("external_runner")
    if not isinstance(external_runner, dict) or external_runner.get("executed_by_plh") is not False:
        errors.append("$.external_runner.executed_by_plh: must remain false")

    return {
        "contract_version": PROFILE_VALIDATION_CONTRACT_VERSION,
        "runner_profile_id": runner_profile_id,
        "source": entry["source"],
        "trust": entry["trust"],
        "manifest_sha256": entry["manifest_sha256"],
        "errors": errors,
        "ok": not errors,
    }


def _load_builtin(runner_profile_id: str) -> tuple[dict[str, Any], bytes]:
    resource_name = BUILTIN_PROFILE_RESOURCES.get(runner_profile_id)
    if resource_name is None:
        raise InvalidInputError(
            f"Unknown runner Profile ID: {runner_profile_id}",
            details={
                "runner_profile_id": runner_profile_id,
                "available_runner_profile_ids": sorted(BUILTIN_PROFILE_RESOURCES),
                "registry_scope": "builtin_only",
            },
        )
    resource = files("pcl").joinpath(resource_name)
    try:
        raw = resource.read_bytes()
    except OSError as exc:
        raise InvalidInputError(
            f"Built-in runner Profile manifest is unavailable: {runner_profile_id}",
            details={
                "runner_profile_id": runner_profile_id,
                "resource": resource_name,
                "reason": str(exc),
            },
        ) from exc
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InvalidInputError(
            f"Built-in runner Profile manifest is invalid: {runner_profile_id}",
            details={
                "runner_profile_id": runner_profile_id,
                "resource": resource_name,
                "reason": str(exc),
            },
        ) from exc
    if not isinstance(value, dict):
        raise InvalidInputError(
            f"Built-in runner Profile manifest is not an object: {runner_profile_id}",
            details={"runner_profile_id": runner_profile_id, "resource": resource_name},
        )
    return value, raw


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key {key!r} is not allowed")
        value[key] = item
    return value


def _reject_non_finite(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value} is not allowed")
