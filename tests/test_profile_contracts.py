from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pcl.cli import main
from pcl.contracts.claim_set import load_claim_set, validate_claim_set
from pcl.contracts.council_run import load_council_run, validate_council_run
from pcl.contracts.decision_proposal import (
    load_decision_proposal,
    validate_decision_proposal,
)
from pcl.contracts.profile_manifest import (
    load_profile_manifest,
    validate_profile_manifest,
)
from pcl.contracts.profile_output_bundle import (
    load_profile_output_bundle,
    validate_profile_output_bundle,
)
from pcl.contracts.profile_run_request import (
    load_profile_run_request,
    validate_profile_run_request,
)
from pcl.contracts.verification_plan import (
    load_verification_plan,
    validate_verification_plan,
)
from pcl.profiles import list_profiles, show_profile, validate_profile


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "docs" / "proposals" / "council-profile" / "contracts"
EXAMPLES = CONTRACT_ROOT / "examples"
NEGATIVE = CONTRACT_ROOT / "negative"

CONTRACTS = {
    "profile-manifest/v1": (
        load_profile_manifest,
        validate_profile_manifest,
        "profile-manifest.discovery-council.json",
    ),
    "profile-run-request/v1": (
        load_profile_run_request,
        validate_profile_run_request,
        "profile-run-request.json",
    ),
    "profile-output-bundle/v1": (
        load_profile_output_bundle,
        validate_profile_output_bundle,
        "profile-output-bundle.json",
    ),
    "council-run/v0": (
        load_council_run,
        validate_council_run,
        "council-run.json",
    ),
    "claim-set/v0": (
        load_claim_set,
        validate_claim_set,
        "claim-set.json",
    ),
    "verification-plan/v0": (
        load_verification_plan,
        validate_verification_plan,
        "verification-plan.json",
    ),
    "decision-proposal/v0": (
        load_decision_proposal,
        validate_decision_proposal,
        "decision-proposal.json",
    ),
}


@pytest.mark.parametrize(
    ("contract_version", "loader", "validator", "fixture_name"),
    [
        (contract_version, loader, validator, fixture_name)
        for contract_version, (loader, validator, fixture_name) in CONTRACTS.items()
    ],
)
def test_canonical_profile_contracts_pass_manual_validators(
    contract_version,
    loader,
    validator,
    fixture_name,
) -> None:
    result = validator(loader(EXAMPLES / fixture_name))
    assert result.ok, result.errors
    assert result.to_dict() == {
        "contract_type": contract_version,
        "errors": [],
        "ok": True,
    }


@pytest.mark.parametrize(
    ("contract_version", "fixture_name"),
    [
        ("profile-manifest/v1", "profile-manifest-unknown-field.json"),
        ("profile-run-request/v1", "profile-run-request-unsupported-version.json"),
        ("profile-run-request/v1", "profile-run-request-authorization-basis-mismatch.json"),
        ("profile-output-bundle/v1", "profile-output-bundle-bad-status.json"),
        ("profile-output-bundle/v1", "profile-output-bundle-invalid-path-digest.json"),
        ("profile-output-bundle/v1", "profile-output-bundle-invalid-segments.json"),
        ("decision-proposal/v0", "decision-proposal-bad-reference.json"),
    ],
)
def test_negative_profile_contracts_fail_manual_validators(
    contract_version: str,
    fixture_name: str,
) -> None:
    loader, validator, _ = CONTRACTS[contract_version]
    result = validator(loader(NEGATIVE / fixture_name))
    assert not result.ok
    assert result.errors == tuple(sorted(result.errors, key=result.errors.index))


def test_duplicate_json_keys_fail_before_contract_validation(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"contract_version":"claim-set/v0","contract_version":"claim-set/v0"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        load_claim_set(path)


def test_duplicate_contract_ids_and_cross_references_fail() -> None:
    run = load_council_run(EXAMPLES / "council-run.json")
    run["participants"].append(dict(run["participants"][0]))
    run_result = validate_council_run(run)
    assert any("duplicate participant_id" in error for error in run_result.errors)

    proposal = load_decision_proposal(EXAMPLES / "decision-proposal.json")
    proposal["candidates"].append(dict(proposal["candidates"][0]))
    proposal_result = validate_decision_proposal(proposal)
    assert any("duplicate candidate_id" in error for error in proposal_result.errors)


def test_authorization_semantics_require_human_binding_and_scope() -> None:
    request = load_profile_run_request(EXAMPLES / "profile-run-request.authorized.json")
    request["authorization"]["actor_kind"] = "agent"
    request["authorization"]["source_kind"] = "cli"
    request["authorization"]["source_ref"] = ""
    request["authorization"]["scope"]["data_classes"] = ["metadata"]
    request["authorization"]["scope"]["allowed_providers"] = ["provider-a"]
    request["authorization"]["scope"]["max_cost"] = None
    request["authorization"]["scope"]["currency"] = None

    result = validate_profile_run_request(request)
    joined = "\n".join(result.errors)
    assert "must equal 'human'" in joined
    assert "requires conversation or cockpit" in joined
    assert "requires a source ref" in joined
    assert "does not cover repository_content_policy" in joined
    assert "missing requested providers provider-b" in joined
    assert "max_cost: is required" in joined
    assert "currency: is required" in joined


def test_builtin_registry_is_deterministic_data_only_and_hashes_exact_bytes() -> None:
    first = list_profiles()
    second = list_profiles()
    assert first == second
    assert [item["runner_profile_id"] for item in first["profiles"]] == [
        "council.discovery"
    ]
    assert first["profiles"][0]["executed_by_plh"] is False

    entry = show_profile("council.discovery")
    proposal_manifest = (
        EXAMPLES / "profile-manifest.discovery-council.json"
    ).read_bytes()
    assert entry["manifest_sha256"] == hashlib.sha256(proposal_manifest).hexdigest()
    assert entry["manifest"]["external_runner"]["executed_by_plh"] is False
    assert validate_profile("council.discovery")["ok"] is True


def test_profile_cli_json_surfaces_are_read_only(tmp_path: Path, capsys) -> None:
    commands = [
        ["--root", str(tmp_path), "profile", "list", "--json"],
        [
            "--root",
            str(tmp_path),
            "profile",
            "show",
            "council.discovery",
            "--json",
        ],
        [
            "--root",
            str(tmp_path),
            "profile",
            "validate",
            "council.discovery",
            "--json",
        ],
    ]
    payloads = []
    for command in commands:
        assert main(command) == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        payloads.append(json.loads(captured.out))
    assert payloads[0]["profiles"][0]["runner_profile_id"] == "council.discovery"
    assert payloads[1]["manifest"]["runner_profile_id"] == "council.discovery"
    assert payloads[2]["ok"] is True
    assert list(tmp_path.iterdir()) == []


def test_profile_cli_text_and_help_keep_profile_terms_distinct(capsys) -> None:
    assert main(["profile", "list"]) == 0
    list_output = capsys.readouterr().out
    assert "council.discovery" in list_output
    assert "executed_by_plh=false" in list_output

    assert main(["profile", "show", "council.discovery"]) == 0
    show_output = capsys.readouterr().out
    assert "route_profile" in show_output
    assert "role_profile" in show_output

    with pytest.raises(SystemExit) as exc:
        main(["profile", "--help"])
    assert exc.value.code == 0
    help_output = capsys.readouterr().out
    assert "runner Profiles" in help_output
    assert "route_profile" in help_output
    assert "role_profile" in help_output


def test_profile_cli_unknown_runner_profile_is_structured_error(capsys) -> None:
    assert main(["profile", "show", "unknown.profile", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"] == {
        "available_runner_profile_ids": ["council.discovery"],
        "registry_scope": "builtin_only",
        "runner_profile_id": "unknown.profile",
    }


@pytest.mark.parametrize(
    ("contract_version", "fixture_name"),
    [
        (contract_version, fixture_name)
        for contract_version, (_, _, fixture_name) in CONTRACTS.items()
    ],
)
def test_contract_cli_validates_all_profile_contracts(
    contract_version: str,
    fixture_name: str,
    capsys,
) -> None:
    assert (
        main(
            [
                "contract",
                "validate",
                "--type",
                contract_version,
                str(EXAMPLES / fixture_name),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["contract_type"] == contract_version
    assert payload["ok"] is True
