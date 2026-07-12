from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "docs" / "proposals" / "council-profile" / "contracts"
SCHEMA_ROOT = CONTRACT_ROOT / "schemas"
EXAMPLE_ROOT = CONTRACT_ROOT / "examples"
NEGATIVE_ROOT = CONTRACT_ROOT / "negative"

SCHEMA_TO_EXAMPLE = {
    "profile-manifest-v1.schema.json": "profile-manifest.discovery-council.json",
    "profile-run-request-v1.schema.json": "profile-run-request.json",
    "profile-output-bundle-v1.schema.json": "profile-output-bundle.json",
    "council-run-v0.schema.json": "council-run.json",
    "claim-set-v0.schema.json": "claim-set.json",
    "verification-plan-v0.schema.json": "verification-plan.json",
    "decision-proposal-v0.schema.json": "decision-proposal.json",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _request_basis(value: dict[str, Any]) -> str:
    normalized = json.loads(json.dumps(value))
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
    return hashlib.sha256(_canonical_bytes(normalized)).hexdigest()


def _request_digest(value: dict[str, Any]) -> str:
    normalized = json.loads(json.dumps(value))
    normalized.pop("request_digest", None)
    return hashlib.sha256(_canonical_bytes(normalized)).hexdigest()


def _bundle_digest(value: dict[str, Any]) -> str:
    normalized = json.loads(json.dumps(value))
    normalized.pop("bundle_digest", None)
    return hashlib.sha256(_canonical_bytes(normalized)).hexdigest()


def test_seven_proposal_schemas_are_draft_2020_12_and_examples_match() -> None:
    assert sorted(path.name for path in SCHEMA_ROOT.glob("*.json")) == sorted(
        SCHEMA_TO_EXAMPLE
    )
    for schema_name, example_name in SCHEMA_TO_EXAMPLE.items():
        schema = _load(SCHEMA_ROOT / schema_name)
        example = _load(EXAMPLE_ROOT / example_name)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        contract_const = schema["properties"]["contract_version"]["const"]
        assert example["contract_version"] == contract_const
        assert set(schema["required"]).issubset(example)


def test_candidate_and_authorized_requests_have_stable_basis() -> None:
    candidate = _load(EXAMPLE_ROOT / "profile-run-request.candidate.json")
    authorized = _load(EXAMPLE_ROOT / "profile-run-request.authorized.json")
    candidate_basis = _request_basis(candidate)
    authorized_basis = _request_basis(authorized)

    assert candidate["generated_at"] != authorized["generated_at"]
    assert candidate["context"]["receipt_age"] != authorized["context"]["receipt_age"]
    assert candidate_basis == authorized_basis
    assert candidate["request_basis_digest"]["value"] == candidate_basis
    assert authorized["request_basis_digest"]["value"] == authorized_basis
    assert authorized["authorization"]["request_basis_digest"] == authorized_basis
    assert candidate["request_id"] == authorized["request_id"]
    assert candidate["request_digest"]["value"] == _request_digest(candidate)
    assert authorized["request_digest"]["value"] == _request_digest(authorized)


def test_manifest_request_run_and_bundle_digests_cross_reference_exact_bytes() -> None:
    manifest_path = EXAMPLE_ROOT / "profile-manifest.discovery-council.json"
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    authorized = _load(EXAMPLE_ROOT / "profile-run-request.authorized.json")
    request_digest = authorized["request_digest"]["value"]
    council_run = _load(EXAMPLE_ROOT / "council-run.json")
    bundle = _load(EXAMPLE_ROOT / "profile-output-bundle.json")

    assert authorized["profile"]["manifest_sha256"] == manifest_sha
    assert bundle["profile"]["manifest_sha256"] == manifest_sha
    assert council_run["request_ref"]["request_digest"] == request_digest
    assert bundle["request_ref"]["request_digest"] == request_digest
    assert bundle["bundle_digest"]["value"] == _bundle_digest(bundle)

    for artifact in bundle["artifacts"]:
        artifact_path = EXAMPLE_ROOT / artifact["path"]
        data = artifact_path.read_bytes()
        assert artifact["sha256"] == hashlib.sha256(data).hexdigest()
        assert artifact["size_bytes"] == len(data)


def test_semantic_request_change_invalidates_authorization_binding() -> None:
    changed = _load(
        NEGATIVE_ROOT / "profile-run-request-authorization-basis-mismatch.json"
    )
    recomputed = _request_basis(changed)
    assert changed["request_basis_digest"]["value"] == recomputed
    assert changed["authorization"]["request_basis_digest"] != recomputed


def test_targeted_negative_corpus_is_complete() -> None:
    manifest = _load(NEGATIVE_ROOT / "negative-cases.json")
    cases = manifest["cases"]
    assert {item["expected_code"] for item in cases} == {
        "unknown_field",
        "unsupported_contract_version",
        "invalid_status",
        "decision_proposal_reference_missing",
        "invalid_path_or_digest",
        "invalid_path_segment",
        "profile_authorization_basis_mismatch",
    }
    for item in cases:
        assert (NEGATIVE_ROOT / item["path"]).is_file()

    assert "unexpected_field" in _load(
        NEGATIVE_ROOT / "profile-manifest-unknown-field.json"
    )
    assert (
        _load(NEGATIVE_ROOT / "profile-run-request-unsupported-version.json")[
            "contract_version"
        ]
        == "profile-run-request/v9"
    )
    assert (
        _load(NEGATIVE_ROOT / "profile-output-bundle-bad-status.json")["status"]
        == "succeeded"
    )
    bad_ref = _load(NEGATIVE_ROOT / "decision-proposal-bad-reference.json")
    assert bad_ref["recommended_candidate_id"] not in {
        item["candidate_id"] for item in bad_ref["candidates"]
    }
    bad_artifact = _load(
        NEGATIVE_ROOT / "profile-output-bundle-invalid-path-digest.json"
    )["artifacts"][0]
    assert bad_artifact["path"].startswith("../")
    assert len(bad_artifact["sha256"]) != 64
    assert "/./" in _load(
        NEGATIVE_ROOT / "profile-output-bundle-invalid-segments.json"
    )["artifacts"][0]["path"]


def test_integrated_decision_proposal_draft_is_visibly_superseded() -> None:
    proposal_schema = _load(SCHEMA_ROOT / "decision-proposal-v0.schema.json")
    integrated_schema = _load(
        ROOT
        / "docs"
        / "roadmap"
        / "integrated"
        / "schemas"
        / "decision-proposal-v0.schema.json"
    )
    proposal_example = _load(EXAMPLE_ROOT / "decision-proposal.json")
    integrated_example = _load(
        ROOT
        / "docs"
        / "roadmap"
        / "integrated"
        / "examples"
        / "decision-proposal.json"
    )
    contract_doc = (
        ROOT / "docs" / "roadmap" / "integrated" / "02-contracts-and-data-model.md"
    ).read_text(encoding="utf-8")

    assert integrated_schema == proposal_schema
    assert integrated_example == proposal_example
    assert "Superseded planning shape (2026-07-12)" in contract_doc


def test_public_profile_terminology_is_not_overloaded() -> None:
    manifest = _load(EXAMPLE_ROOT / "profile-manifest.discovery-council.json")
    request = _load(EXAMPLE_ROOT / "profile-run-request.json")
    assert manifest["runner_profile_id"] == "council.discovery"
    assert request["profile"]["runner_profile_id"] == "council.discovery"
    assert request["route"]["route_profile"] == "discover"
    assert request["context"]["role_profile"] == "default"
    assert "profile_id" not in manifest
    assert "effective_profile" not in request["route"]


def test_bundle_paths_and_next_actions_are_fail_closed_in_schema() -> None:
    schema = _load(SCHEMA_ROOT / "profile-output-bundle-v1.schema.json")
    artifact_properties = schema["properties"]["artifacts"]["items"]["properties"]
    path_pattern = re.compile(artifact_properties["path"]["pattern"])
    assert path_pattern.fullmatch("reports/council-run.json")
    for invalid in ("../escape.json", "a/./b", "a//b", "a/b/", "./x"):
        assert path_pattern.fullmatch(invalid) is None
    assert (
        schema["properties"]["next_action"]["properties"]["safe_to_run"]["const"]
        is False
    )
