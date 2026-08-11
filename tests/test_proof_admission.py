from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

import pcl.proof_workspace as c2_runtime
import test_proof_execution as c3
import test_proof_workspace as c2
from pcl.contracts.authority_surface import authority_document_sha256
from pcl.contracts.proof_admission import (
    canary_item_sha256,
    environment_binding_sha256,
    execution_binding_sha256,
    finalize_proof_coverage_policy,
)
from pcl.contracts.proof_workspace import proof_document_sha256
from pcl.proof_admission import (
    ProofCoverageError,
    ProofCoverageParticipant,
    TrustedCoveragePolicyProducerCapability,
    bind_trusted_coverage_policy,
    evaluate_proof_coverage,
    issue_trusted_coverage_policy_producer_capability,
)


@contextmanager
def _live_join(
    tmp_path: Path,
    *,
    split: bool = True,
    fail_full: bool = False,
    include_blob_lookup_decoy: bool = False,
) -> Iterator[dict[str, Any]]:
    seed = c3._case(tmp_path / "seed")
    blob_oid = c2._git(seed.root, "rev-parse", f"{seed.candidate}:src/candidate_only.py")
    readme_oid = c2._git(seed.root, "rev-parse", f"{seed.candidate}:README.md")
    canary_argv = [
        sys.executable,
        "-c",
        "import candidate_only; print(candidate_only.VALUE)",
    ]
    canary = {
        "id": "coverage-canary",
        "authority_claim_ids": ["C4-canary"],
        "command": canary_argv,
        "selectors": ["test_a", "test_z"],
        "required_outcome": "pass",
        "referenced_blob_oids": [blob_oid],
        "effect_expectations": [
            "canonical-product-inputs-unchanged",
            "pcl-state-effect0",
        ],
        "supported_platform_conditions": ["python>=3.10"],
    }
    bootstrap = deepcopy(seed.bootstrap)
    bootstrap["canary_contract"]["items"] = [canary]
    authority = replace(
        seed.authority,
        packaged_catalog=bootstrap["authority_catalog"],
        bootstrap_profile=bootstrap,
    )
    resolution = authority.resolve()
    full_argv = (
        [sys.executable, "-c", "raise SystemExit(1)"]
        if fail_full
        else canary_argv
    )
    full_check = _profile_check(
        "full-regression",
        "full_regression",
        full_argv,
        readme_oid if include_blob_lookup_decoy else blob_oid,
        selectors=[],
        blob_path="README.md" if include_blob_lookup_decoy else "src/candidate_only.py",
    )
    canary_check = _profile_check(
        "authority-canary",
        "authority_canary.coverage-canary",
        canary_argv,
        blob_oid,
        selectors=["test_z", "test_a"],
    )
    decoy_check = _profile_check(
        "policy-id-decoy",
        "decoy_role",
        canary_argv,
        blob_oid,
        selectors=[],
    )
    combined_checks = [full_check, canary_check]
    if include_blob_lookup_decoy:
        combined_checks.append(decoy_check)
    profiles = (
        [_profile("full-profile", [full_check]), _profile("canary-profile", [canary_check])]
        if split
        else [_profile("combined-profile", combined_checks)]
    )
    lease_parent = tmp_path / "leases"
    lease_parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        runtime_participants: list[ProofCoverageParticipant] = []
        prepared_objects = []
        for profile in profiles:
            spec = c2._spec(resolution, bootstrap, profile)
            case = c3._Case(
                seed.root,
                seed.base,
                seed.candidate,
                resolution,
                bootstrap,
                profile,
                spec,
                authority,
            )
            prepared = stack.enter_context(c3._prepare(case, lease_parent))
            bundle = c3._execute(case, prepared)
            prepared_objects.append(prepared)
            runtime_participants.append(
                ProofCoverageParticipant(
                    prepared=prepared,
                    spec=spec,
                    authority_resolution=resolution,
                    bootstrap_profile=bootstrap,
                    verification_profile=profile,
                    bundle=bundle,
                )
            )
        policy_document = _policy_document(
            runtime_participants,
            resolution=resolution,
            bootstrap=bootstrap,
            canary=canary,
        )
        capability = issue_trusted_coverage_policy_producer_capability(
            kind="external_bootstrap",
            producer_id="c4-test-producer",
        )
        bound = bind_trusted_coverage_policy(
            policy_document,
            expected_policy_sha256=policy_document["policy_sha256"],
            producer_capability=capability,
        )
        yield {
            "authority": authority,
            "bound": bound,
            "capability": capability,
            "canary": canary,
            "participants": runtime_participants,
            "policy": policy_document,
            "prepared": prepared_objects,
        }


def _profile_check(
    check_id: str,
    role: str,
    argv: list[str],
    blob_oid: str,
    *,
    selectors: list[str],
    blob_path: str = "src/candidate_only.py",
) -> dict[str, Any]:
    check = deepcopy(c2._profile(argv=argv)["checks"][0])
    check.update(
        {
            "check_id": check_id,
            "role": role,
            "selectors": selectors,
            "referenced_git_blobs": [
                {"path": blob_path, "oid": blob_oid}
            ],
        }
    )
    return check


def _profile(profile_id: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    profile = c2._profile()
    profile["profile_id"] = profile_id
    profile["checks"] = checks
    return profile


def _policy_document(
    participants: list[ProofCoverageParticipant],
    *,
    resolution: dict[str, Any],
    bootstrap: dict[str, Any],
    canary: dict[str, Any],
) -> dict[str, Any]:
    requirements = []
    for participant in participants:
        for check in participant.verification_profile["checks"]:
            if check["role"] == "decoy_role":
                continue
            binding_check = next(
                item
                for item in participant.prepared.binding["checks"]
                if item["check_id"] == check["check_id"]
            )
            expected_execution = {
                "plan_sha256": binding_check["plan_sha256"],
                "tool_identity_sha256": binding_check["tool_identity_sha256"],
                "environment_binding_sha256": environment_binding_sha256(
                    binding_check["environment"]
                ),
                "public_execution_sha256": binding_check[
                    "public_execution_sha256"
                ],
                "spawn_vector_sha256": binding_check["spawn_vector_sha256"],
                "external_input_binding_sha256": participant.prepared.binding[
                    "external_inputs"
                ]["binding_sha256"],
                "execution_binding_sha256": "sha256:" + "0" * 64,
            }
            expected_execution["execution_binding_sha256"] = execution_binding_sha256(
                check["check_id"],
                expected_execution,
            )
            is_canary = check["role"].startswith("authority_canary.")
            requirements.append(
                {
                    "role": check["role"],
                    "kind": "authority_canary" if is_canary else "full_regression",
                    "canary_id": canary["id"] if is_canary else None,
                    "canary_item_sha256": (
                        canary_item_sha256(canary) if is_canary else None
                    ),
                    "expected_outcome": "pass",
                    "expected_check": deepcopy(check),
                    "selector_audit_labels": sorted(check["selectors"]),
                    "required_candidate_blobs": deepcopy(
                        check["referenced_git_blobs"]
                    ),
                    "expected_execution": expected_execution,
                    "requirement_sha256": "sha256:" + "0" * 64,
                }
            )
    requirements.sort(
        key=lambda item: (0 if item["kind"] == "full_regression" else 1, item["role"])
    )
    spec = participants[0].spec
    return finalize_proof_coverage_policy(
        {
            "contract_version": "proof-coverage-policy/v1",
            "policy_id": "c4-live-policy",
            "producer": {
                "kind": "external_bootstrap",
                "producer_id": "c4-test-producer",
                "producer_sha256": "sha256:" + "0" * 64,
                "candidate_controlled": False,
            },
            "target": deepcopy(spec["target"]),
            "candidate": deepcopy(spec["candidate"]),
            "authority_bindings": {
                "authority_surface_resolution_sha256": authority_document_sha256(
                    resolution
                ),
                "bootstrap_profile_sha256": authority_document_sha256(bootstrap),
                "canary_union_sha256": resolution["canary"]["union_sha256"],
                "isolation_contract_version": "proof-workspace-isolation/v1",
            },
            "coverage_group_sha256": "sha256:" + "0" * 64,
            "required_roles": requirements,
            "authorization_requirements": {
                "independent_review": "required",
                "human_gate": (
                    "required"
                    if resolution["effective"]["human_gate_required"]
                    else "not_required"
                ),
                "self_certification_allowed": False,
            },
            "terminal_authority": False,
            "mandatory_evidence": False,
            "policy_sha256": "sha256:" + "0" * 64,
        }
    )


def _evaluate(live: dict[str, Any], participants=None):
    return evaluate_proof_coverage(
        policy=live["bound"],
        participants=participants or live["participants"],
        authority_provider=lambda: live["authority"],
        current_proof_provider=c3._not_applicable,
    )


def test_live_parallel_join_is_reviewable_permutation_and_concurrency_deterministic(
    tmp_path: Path,
) -> None:
    with _live_join(tmp_path) as live:
        first = _evaluate(live)
        reverse = _evaluate(live, list(reversed(live["participants"])))
        assert dict(first) == dict(reverse)
        assert first["admission_state"] == "reviewable"
        assert first["review_readiness"] == "ready"
        assert first["promotion_suitability"] == "candidate"
        assert first["authorization_status"]["independent_review"] == "pending"
        assert first["authorization_status"]["anchoring_authorized"] is False
        assert first["authorization_status"]["reuse_authorized"] is False
        assert set(first["role_observations"][1]["effect_status"] for _ in [0]) == {
            "not_disproved"
        }
        encoded = json.dumps(dict(first), sort_keys=True, separators=(",", ":"))
        for forbidden in (
            str(tmp_path),
            str(live["prepared"][0].root),
            "stdout",
            "stderr",
            "pid",
            "pgid",
            "event_high_watermark",
            "duration",
            sys.executable,
        ):
            assert forbidden not in encoded
        assert first["effects"] == {
            "schema": 0,
            "migration": 0,
            "database_write": 0,
            "filesystem_write": 0,
            "evidence": 0,
            "event": 0,
            "outbox": 0,
            "render": 0,
            "lifecycle": 0,
        }
        with ThreadPoolExecutor(max_workers=4) as pool:
            documents = list(pool.map(lambda _: dict(_evaluate(live)), range(8)))
        assert all(document == dict(first) for document in documents)


def test_missing_role_is_incomplete_and_low_h_field_is_null(tmp_path: Path) -> None:
    with _live_join(tmp_path) as live:
        admission = _evaluate(live, [live["participants"][0]])
        canary = admission["role_observations"][1]
        assert admission["admission_state"] == "incomplete"
        assert "required_role_missing" in admission["state_reason_codes"]
        assert canary["attempt_status"] == "missing"
        assert canary["output_commitment_status"] is None


def test_not_run_role_keeps_nonnull_output_commitment_status(tmp_path: Path) -> None:
    with _live_join(tmp_path, split=False, fail_full=True) as live:
        admission = _evaluate(live)
        canary = admission["role_observations"][1]
        assert canary["attempt_status"] == "not_run"
        assert canary["output_commitment_status"] == "committed"
        assert "required_role_not_run" in admission["state_reason_codes"]
        assert "participant_aggregate_failed" in admission["state_reason_codes"]
        assert admission["admission_state"] == "blocked"
        retained = live["prepared"][0].lease_root
    assert retained.exists()


def test_policy_capability_identity_copy_and_secret_ids_fail_closed(tmp_path: Path) -> None:
    with _live_join(tmp_path) as live:
        with pytest.raises(TypeError):
            TrustedCoveragePolicyProducerCapability(
                "external_bootstrap",
                "c4-test-producer",
                _issuer=object(),
            )
        forged = issue_trusted_coverage_policy_producer_capability(
            kind="trusted_planner",
            producer_id="different-producer",
        )
        with pytest.raises(ProofCoverageError) as mismatch:
            bind_trusted_coverage_policy(
                live["policy"],
                expected_policy_sha256=live["policy"]["policy_sha256"],
                producer_capability=forged,
            )
        assert mismatch.value.code == "coverage_policy_authority_invalid"
        original_digest = live["bound"].document["policy_sha256"]
        live["policy"]["policy_id"] = "mutated-after-bind"
        assert live["bound"].document["policy_sha256"] == original_digest

        secret = deepcopy(live["policy"])
        secret["policy_id"] = "sk-" + "x" * 24
        secret = finalize_proof_coverage_policy(secret)
        with pytest.raises(ProofCoverageError) as rejected:
            bind_trusted_coverage_policy(
                secret,
                expected_policy_sha256=secret["policy_sha256"],
                producer_capability=live["capability"],
            )
        assert rejected.value.code == "coverage_public_identifier_secret_shaped"
        assert rejected.value.details == {"phase": "policy"}


def test_policy_plan_blob_and_current_authority_mismatches_are_factual(
    tmp_path: Path,
) -> None:
    with _live_join(tmp_path) as live:
        plan = deepcopy(live["policy"])
        plan["required_roles"][0]["expected_check"]["argv"] = [
            *reversed(plan["required_roles"][0]["expected_check"]["argv"])
        ]
        plan = finalize_proof_coverage_policy(plan)
        capability = issue_trusted_coverage_policy_producer_capability(
            kind="external_bootstrap",
            producer_id="c4-test-producer",
        )
        bound = bind_trusted_coverage_policy(
            plan,
            expected_policy_sha256=plan["policy_sha256"],
            producer_capability=capability,
        )
        admission = evaluate_proof_coverage(
            policy=bound,
            participants=live["participants"],
            authority_provider=lambda: live["authority"],
            current_proof_provider=c3._not_applicable,
        )
        assert admission["admission_state"] == "invalid"
        assert "participant_policy_mismatch" in admission["state_reason_codes"]

        admission = evaluate_proof_coverage(
            policy=live["bound"],
            participants=live["participants"],
            authority_provider=lambda: (_ for _ in ()).throw(OSError("unavailable")),
            current_proof_provider=lambda: (_ for _ in ()).throw(
                OSError("db unavailable")
            ),
        )
        assert admission["admission_state"] == "indeterminate"
        assert "authority_current_indeterminate" in admission["state_reason_codes"]
        assert "current_proof_indeterminate" in admission["state_reason_codes"]
        assert admission["effects"]["database_write"] == 0


def test_policy_renamed_selected_check_id_is_typed_policy_mismatch(
    tmp_path: Path,
) -> None:
    with _live_join(tmp_path) as live:
        policy = deepcopy(live["policy"])
        requirement = policy["required_roles"][0]
        requirement["expected_check"]["check_id"] = "renamed-policy-check"
        policy = finalize_proof_coverage_policy(policy)
        capability = issue_trusted_coverage_policy_producer_capability(
            kind="external_bootstrap",
            producer_id="c4-test-producer",
        )
        bound = bind_trusted_coverage_policy(
            policy,
            expected_policy_sha256=policy["policy_sha256"],
            producer_capability=capability,
        )

        admission = evaluate_proof_coverage(
            policy=bound,
            participants=live["participants"],
            authority_provider=lambda: live["authority"],
            current_proof_provider=c3._not_applicable,
        )

        assert admission["admission_state"] == "invalid"
        assert "participant_policy_mismatch" in admission["state_reason_codes"]
        assert admission["review_readiness"] == "withheld"
        assert admission["authorization_status"]["anchoring_authorized"] is False
        assert str(tmp_path) not in json.dumps(dict(admission))


def test_blob_lookup_uses_selected_role_check_not_policy_id_decoy(
    tmp_path: Path,
) -> None:
    with _live_join(
        tmp_path,
        split=False,
        include_blob_lookup_decoy=True,
    ) as live:
        policy = deepcopy(live["policy"])
        requirement = policy["required_roles"][0]
        decoy = next(
            check
            for check in live["participants"][0].verification_profile["checks"]
            if check["check_id"] == "policy-id-decoy"
        )
        requirement["expected_check"] = {**deepcopy(decoy), "role": "full_regression"}
        requirement["required_candidate_blobs"] = deepcopy(
            decoy["referenced_git_blobs"]
        )
        policy = finalize_proof_coverage_policy(policy)
        capability = issue_trusted_coverage_policy_producer_capability(
            kind="external_bootstrap",
            producer_id="c4-test-producer",
        )
        bound = bind_trusted_coverage_policy(
            policy,
            expected_policy_sha256=policy["policy_sha256"],
            producer_capability=capability,
        )

        admission = evaluate_proof_coverage(
            policy=bound,
            participants=live["participants"],
            authority_provider=lambda: live["authority"],
            current_proof_provider=c3._not_applicable,
        )

        full = admission["role_observations"][0]
        assert full["check_id"] == "full-regression"
        assert full["candidate_blob_status"] == "oid_mismatch"
        assert admission["admission_state"] == "invalid"
        assert "participant_policy_mismatch" in admission["state_reason_codes"]
        assert "candidate_blob_oid_mismatch" in admission["state_reason_codes"]
        assert admission["promotion_suitability"] == "withheld"


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (b"120000 blob " + b"b" * 40 + b"\tsrc/candidate_only.py\0", "candidate_blob_type_unsupported"),
        (b"malformed\0", "candidate_blob_resolution_indeterminate"),
        (b"", "candidate_blob_missing"),
    ],
)
def test_direct_git_blob_types_and_sanitized_failures(
    tmp_path: Path,
    record: bytes,
    reason: str,
) -> None:
    with _live_join(tmp_path) as live:
        prepared = live["prepared"][0]
        original = prepared._git

        class Intercept:
            environment = original.environment

            def run(self, cwd, *args, input_bytes=None):
                if args and args[0] == "ls-tree":
                    return subprocess.CompletedProcess(
                        ["git", *args],
                        0,
                        stdout=record,
                        stderr=b"sk-" + b"x" * 40,
                    )
                return original.run(cwd, *args, input_bytes=input_bytes)

        prepared._git = Intercept()
        admission = _evaluate(live)
        assert reason in admission["state_reason_codes"]
        assert "sk-" not in json.dumps(dict(admission))


def test_sha256_blob_parser_and_prohibited_c2_helpers_are_not_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oid = "c" * 64

    class Runner:
        def run(self, _cwd, *_args):
            return subprocess.CompletedProcess(
                ["git"],
                0,
                stdout=f"100755 blob {oid}\tsrc/check.py\0".encode(),
                stderr=b"",
            )

    prepared = SimpleNamespace(
        _git=Runner(),
        _source_root=Path("/unused"),
        _source_object_format="sha256",
    )
    monkeypatch.setattr(
        c2_runtime,
        "_git_bytes",
        lambda *_args, **_kwargs: pytest.fail("C2 Git helper must not be called"),
    )
    from pcl.proof_admission import _ls_tree_blob

    assert _ls_tree_blob(prepared, "d" * 64, "src/check.py") == (
        "100755",
        "blob",
        oid,
    )


def test_source_snapshot_batches_stable_repository_metadata_queries(
    tmp_path: Path,
) -> None:
    from pcl.proof_admission import _source_snapshot

    with _live_join(tmp_path) as live:
        prepared = live["prepared"][0]
        original = prepared._git
        calls: list[tuple[str, ...]] = []

        class RecordingGit:
            environment = original.environment

            def run(self, cwd, *args, input_bytes=None):
                calls.append(tuple(args))
                return original.run(cwd, *args, input_bytes=input_bytes)

        prepared._git = RecordingGit()

        snapshot = _source_snapshot(prepared)

    assert snapshot[2] in {"sha1", "sha256"}
    rev_parse_calls = [args for args in calls if args[0] == "rev-parse"]
    assert rev_parse_calls == [
        (
            "rev-parse",
            "--show-toplevel",
            "--git-common-dir",
            "--git-path",
            "objects",
            "--show-object-format",
            f"{prepared._candidate_commit}^{{commit}}",
            f"{prepared._candidate_commit}^{{tree}}",
        ),
    ]
    reachability_calls = [
        args
        for args in calls
        if args[0] in {"for-each-ref", "merge-base"}
    ]
    assert reachability_calls == [
        (
            "merge-base",
            "--is-ancestor",
            prepared._candidate_commit,
            "HEAD",
        )
    ]


def test_candidate_reachability_falls_back_to_refs_and_fails_closed() -> None:
    from pcl.proof_admission import (
        _GitObservationIndeterminate,
        _candidate_reachable_direct,
    )

    commit = "a" * 40

    class Git:
        environment = {"GIT_OPTIONAL_LOCKS": "0"}

        def __init__(self, *, head_status: int, ref_status: int = 0) -> None:
            self.head_status = head_status
            self.ref_status = ref_status
            self.calls: list[tuple[str, ...]] = []

        def run(self, _cwd, *args, input_bytes=None):
            self.calls.append(tuple(args))
            if args[0] == "for-each-ref":
                return subprocess.CompletedProcess(
                    ["git", *args],
                    0,
                    stdout=b"refs/heads/release\n",
                    stderr=b"",
                )
            status = (
                self.head_status
                if args[-1] == "HEAD"
                else self.ref_status
            )
            return subprocess.CompletedProcess(
                ["git", *args],
                status,
                stdout=b"",
                stderr=b"",
            )

    fallback = Git(head_status=1, ref_status=0)
    prepared = SimpleNamespace(_git=fallback, _source_root=Path("/unused"))
    assert _candidate_reachable_direct(prepared, commit) is True
    assert fallback.calls[-1][-1] == "refs/heads/release"

    absent = Git(head_status=1, ref_status=1)
    prepared._git = absent
    assert _candidate_reachable_direct(prepared, commit) is False

    indeterminate = Git(head_status=2)
    prepared._git = indeterminate
    with pytest.raises(_GitObservationIndeterminate):
        _candidate_reachable_direct(prepared, commit)
    assert len(indeterminate.calls) == 1


def test_live_identity_and_c3_document_tamper_are_hard_errors(tmp_path: Path) -> None:
    with _live_join(tmp_path) as live:
        participant = live["participants"][0]
        copied_check = replace(
            participant.bundle.frozen_packet.prepared_checks[0]
        )
        forged_packet = replace(
            participant.bundle.frozen_packet,
            prepared_checks=(copied_check,),
        )
        forged_bundle = replace(participant.bundle, frozen_packet=forged_packet)
        forged_participant = replace(participant, bundle=forged_bundle)
        with pytest.raises(ProofCoverageError) as identity:
            _evaluate(
                live,
                [forged_participant, live["participants"][1]],
            )
        assert identity.value.code == "coverage_live_identity_mismatch"
        assert identity.value.details == {"phase": "participant"}

        tampered_bundle = replace(
            participant.bundle,
            aggregate={**participant.bundle.aggregate, "verdict": "failed"},
        )
        with pytest.raises(ProofCoverageError) as digest:
            _evaluate(
                live,
                [replace(participant, bundle=tampered_bundle), live["participants"][1]],
            )
        assert digest.value.code == "coverage_digest_mismatch"
        assert set(digest.value.details) == {"phase"}


def test_duplicate_live_chain_is_invalid_not_reused(tmp_path: Path) -> None:
    with _live_join(tmp_path) as live:
        admission = _evaluate(
            live,
            [live["participants"][0], live["participants"][0]],
        )
        assert admission["admission_state"] == "invalid"
        assert "duplicate_bundle" in admission["state_reason_codes"]
        assert "duplicate_proof_key" in admission["state_reason_codes"]
        assert admission["authorization_status"]["reuse_authorized"] is False


def test_runtime_does_not_mutate_project_loop_or_environment(tmp_path: Path) -> None:
    before_environment = dict(os.environ)
    with _live_join(tmp_path) as live:
        before_binding = proof_document_sha256(live["participants"][0].prepared.binding)
        admission = _evaluate(live)
        after_binding = proof_document_sha256(live["participants"][0].prepared.binding)
        assert before_binding == after_binding
        assert admission["effects"]["event"] == 0
        assert admission["effects"]["outbox"] == 0
        assert admission["effects"]["render"] == 0
    assert os.environ == before_environment
