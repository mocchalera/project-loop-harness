from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

import pcl.cli as cli
import pcl.mcp_server as mcp_server
import pcl.proof_admission as proof_admission
import pcl.renderer as renderer
import test_proof_admission as c4
import test_proof_anchor as c5
from pcl.contracts.proof_anchor_drift import (
    DRIFT_EFFECTS,
    validate_proof_anchor_drift_eligibility,
)
from pcl.contracts.proof_admission import finalize_proof_coverage_policy
from pcl.contracts.proof_execution import finalize_proof_execution_document
from pcl.db import connect
from pcl.locks import ExistingSharedProjectLock, ExistingSharedProjectLockError
from pcl.paths import ProjectPaths
from pcl.proof_anchor_drift import (
    ProofAnchorDriftError,
    _classify_sqlite_error,
    _evaluate_resolution,
    _live_reasons,
    _map_live_domain_error,
    _open_pinned_read_snapshot,
    _soft_live_reconstruction,
    evaluate_proof_anchor_drift_eligibility,
)
from pcl.proof_anchor import (
    ProofAnchorDriftAuthorityResolution,
    ProofAnchorError,
)
from pcl.proof_admission import (
    ProofCoverageError,
    bind_trusted_coverage_policy,
    evaluate_proof_coverage,
    issue_trusted_coverage_policy_producer_capability,
)
from pcl.proof_execution import ProofExecutionError


def _evaluate(paths: ProjectPaths, live: dict, anchor: dict, basis: dict, **overrides):
    values = {
        "anchor_event_id": anchor["event_id"],
        "expected_target_id": "T-0001",
        "expected_candidate": basis["candidate"],
        "expected_basis_sha256": basis["basis_sha256"],
        "policy": live["bound"],
        "participants": live["participants"],
        "authority_provider": lambda: live["authority"],
    }
    values.update(overrides)
    return evaluate_proof_anchor_drift_eligibility(paths, **values)


def _anchored(tmp_path: Path, **live_options):
    paths = ProjectPaths(tmp_path / "project")
    c5._initialize(paths)
    live_context = c4._live_join(tmp_path / "live", **live_options)
    live = live_context.__enter__()
    basis = c5._basis(live)
    anchor = c5._anchor(paths, live, basis, c5._authorizations(basis))
    return paths, live_context, live, basis, anchor


def test_healthy_anchor_is_drift_eligible_deterministic_and_effect_zero(tmp_path: Path) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    try:
        before = c5._counts(paths)
        first = _evaluate(paths, live, anchor, basis)
        reverse = _evaluate(
            paths,
            live,
            anchor,
            basis,
            participants=list(reversed(live["participants"])),
        )
        assert first == reverse
        assert first["eligibility"] == {
            "status": "eligible",
            "predicate_kind": "drift_eligibility_only",
            "matched": True,
            "direct_input_right": False,
            "check_skip_authorized": False,
            "result_substitution_authorized": False,
        }
        assert first["reason_codes"] == []
        assert first["effects"] == DRIFT_EFFECTS
        assert c5._counts(paths) == before
        assert first["authorization_status"]["reuse_authorized"] is False
        assert first["handoff"]["reuse_consumable"] is False
    finally:
        context.__exit__(None, None, None)


def test_assertion_drift_is_withheld_and_never_launders_computed_verdict(
    tmp_path: Path,
) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    try:
        changed_candidate = deepcopy(basis["candidate"])
        changed_candidate["tree_oid"] = "f" * len(changed_candidate["tree_oid"])
        receipt = _evaluate(
            paths,
            live,
            anchor,
            basis,
            expected_candidate=changed_candidate,
        )
        assert receipt["eligibility"]["status"] == "withheld"
        assert receipt["reason_codes"] == ["anchor_candidate_mismatch"]
        assert receipt["eligibility"]["matched"] is False
        assert receipt["eligibility"]["direct_input_right"] is False
    finally:
        context.__exit__(None, None, None)


def test_anchor_artifact_tamper_requires_bounded_c5_recovery_and_is_total(tmp_path: Path) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    try:
        c5._tamper_basis(paths, anchor)
        receipt = _evaluate(paths, live, anchor, basis)
        assert receipt["eligibility"]["status"] == "withheld"
        assert receipt["reason_codes"] == ["anchor_recovery_required"]
        assert receipt["anchor"]["health_status"] == "postcommit_unhealthy"
    finally:
        context.__exit__(None, None, None)


def _fake_head() -> SimpleNamespace:
    return SimpleNamespace(
        event_id="EV-" + "A" * 64,
        sequence=1,
        generation=3,
        health_status="postcommit_unhealthy",
        payload={
            "request_id": "PA-" + "B" * 64,
            "base_request_sha256": "sha256:" + "a" * 64,
            "basis_sha256": "sha256:" + "b" * 64,
            "anchor_sha256": "sha256:" + "c" * 64,
            "manifest_file_sha256": "sha256:" + "d" * 64,
            "evidence_id": "E-0001",
        },
    )


def _special_resolution_receipt(
    tmp_path: Path,
    resolution: ProofAnchorDriftAuthorityResolution,
):
    return _evaluate_resolution(
        paths=ProjectPaths(tmp_path),
        conn=None,
        snapshot={
            "schema_version": 8,
            "evaluated_through_event_sequence": 0,
            "evaluated_through_event_id": None,
        },
        project_instance_id="project-1",
        resolution=resolution,
        anchor_event_id="EV-" + "A" * 64,
        expected_target_id="T-0001",
        expected_candidate={
            "object_format": "sha1",
            "commit_oid": "1" * 40,
            "tree_oid": "2" * 40,
        },
        expected_basis_sha256="sha256:" + "b" * 64,
        policy=object(),
        participants=(),
        authority_provider=lambda: None,
    )


def test_tombstone_precedence_and_gen3_pending_are_exact(tmp_path: Path) -> None:
    head = _fake_head()
    multiple = ProofAnchorDriftAuthorityResolution(
        assertion_found=True,
        authority_corrupt=True,
        target_id="T-0001",
        basis_sha256="sha256:" + "b" * 64,
        tombstone_status="multiple",
        tombstone_event_id=None,
        tombstone_witness=None,
        valid_chains=((head,),),
        malformed_group_present=None,
        exhaustion_witness=head,
    )
    multiple_receipt = _special_resolution_receipt(tmp_path, multiple)
    assert multiple_receipt["reason_codes"] == ["anchor_authority_corrupt"]
    assert multiple_receipt["anchor"] is None
    assert multiple_receipt["observation"]["chain"]["valid_chain_count"] is None

    valid = ProofAnchorDriftAuthorityResolution(
        assertion_found=True,
        authority_corrupt=False,
        target_id="T-0001",
        basis_sha256="sha256:" + "b" * 64,
        tombstone_status="valid",
        tombstone_event_id="EV-" + "C" * 64,
        tombstone_witness=head,
        valid_chains=(),
        malformed_group_present=None,
        exhaustion_witness=None,
    )
    valid_receipt = _special_resolution_receipt(tmp_path, valid)
    assert valid_receipt["reason_codes"] == ["anchor_exhaustion_tombstoned"]
    assert valid_receipt["anchor"]["chain_head"] is None
    assert validate_proof_anchor_drift_eligibility(valid_receipt).ok

    pending = ProofAnchorDriftAuthorityResolution(
        assertion_found=True,
        authority_corrupt=True,
        target_id="T-0001",
        basis_sha256="sha256:" + "b" * 64,
        tombstone_status="absent",
        tombstone_event_id=None,
        tombstone_witness=None,
        valid_chains=((head,),),
        malformed_group_present=True,
        exhaustion_witness=head,
    )
    pending_receipt = _special_resolution_receipt(tmp_path, pending)
    assert pending_receipt["reason_codes"] == ["anchor_exhaustion_pending"]
    assert pending_receipt["anchor"]["chain_head"] is True
    assert pending_receipt["observation"]["chain"]["malformed_group_present"] is True


def test_existing_shared_lock_is_no_create_no_follow_and_rechecks_identity(
    tmp_path: Path,
) -> None:
    loop_dir = tmp_path / ".project-loop"
    loop_dir.mkdir(mode=0o700)
    lock_path = loop_dir / "project.lock"

    with pytest.raises(ExistingSharedProjectLockError) as missing:
        ExistingSharedProjectLock(lock_path).acquire()
    assert missing.value.code == "lock_unavailable"
    assert not lock_path.exists()

    lock_path.write_bytes(b"")
    lock_path.chmod(0o600)
    held = ExistingSharedProjectLock(lock_path)
    held.acquire()
    try:
        held.recheck()
        assert held.descriptor is not None
        assert held.exclusive_capability is None
    finally:
        held.release()

    lock_path.unlink()
    lock_path.symlink_to(loop_dir / "missing-target")
    with pytest.raises(ExistingSharedProjectLockError) as symlink:
        ExistingSharedProjectLock(lock_path).acquire()
    assert symlink.value.code == "lock_identity_invalid"


class _SqliteOperationalError(sqlite3.OperationalError):
    def __init__(self, code: object) -> None:
        super().__init__("sensitive raw sqlite message")
        self.sqlite_errorcode = code


class _ExplodingSqliteOperationalError(sqlite3.OperationalError):
    @property
    def sqlite_errorcode(self):
        raise RuntimeError("do not leak")


class _ControlFlowSqliteOperationalError(sqlite3.OperationalError):
    @property
    def sqlite_errorcode(self):
        raise KeyboardInterrupt


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_SqliteOperationalError(776), "drift_database_recovery_required"),
        (_SqliteOperationalError(264), "drift_database_recovery_required"),
        (_SqliteOperationalError(520), "drift_snapshot_unavailable"),
        (_SqliteOperationalError(5), "drift_snapshot_unavailable"),
        (_SqliteOperationalError(6), "drift_snapshot_unavailable"),
        (_SqliteOperationalError(11), "drift_database_recovery_required"),
        (_SqliteOperationalError(26), "drift_database_recovery_required"),
        (_SqliteOperationalError(None), "drift_database_recovery_required"),
        (_ExplodingSqliteOperationalError("raw"), "drift_database_recovery_required"),
        (sqlite3.DatabaseError("secret"), "drift_snapshot_unavailable"),
    ],
)
def test_sqlite_mapping_is_python310_compatible_total_and_sanitized(error, expected) -> None:
    assert _classify_sqlite_error(error) == expected


def test_sqlite_mapping_never_swallows_control_flow() -> None:
    with pytest.raises(KeyboardInterrupt):
        _classify_sqlite_error(_ControlFlowSqliteOperationalError("stop"))


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ProofAnchorError("x", code="proof_anchor_contract_invalid"), "drift_contract_invalid"),
        (
            ProofAnchorError("x", code="proof_anchor_admission_withheld"),
            "drift_live_domain_error",
        ),
        (
            ProofCoverageError("x", code="coverage_input_type_invalid"),
            "drift_input_type_invalid",
        ),
        (
            ProofCoverageError("x", code="coverage_capacity_exceeded"),
            "drift_capacity_exceeded",
        ),
        (
            ProofCoverageError("x", code="coverage_digest_mismatch"),
            "drift_contract_invalid",
        ),
        (
            ProofCoverageError("x", code="coverage_contract_invalid"),
            "drift_contract_invalid",
        ),
        (
            ProofCoverageError("x", code="coverage_policy_authority_invalid"),
            "drift_contract_invalid",
        ),
        (
            ProofCoverageError("x", code="coverage_public_identifier_secret_shaped"),
            "drift_secret_shaped_identifier",
        ),
        (
            ProofCoverageError("x", code="coverage_live_identity_mismatch"),
            None,
        ),
        (ProofCoverageError("raw", code="future_domain_code"), "drift_live_domain_error"),
    ],
)
def test_live_domain_error_mapping_is_closed_and_sanitized(error, expected) -> None:
    assert _map_live_domain_error(error) == expected


def _assert_soft_live_receipt(
    receipt: dict,
    *,
    reconstruction_status: str,
    reason: str,
) -> None:
    assert receipt["eligibility"] == {
        "status": "withheld",
        "predicate_kind": "drift_eligibility_only",
        "matched": False,
        "direct_input_right": False,
        "check_skip_authorized": False,
        "result_substitution_authorized": False,
    }
    assert receipt["reason_codes"] == [reason]
    assert receipt["observation"]["live"]["reconstruction_status"] == reconstruction_status
    assert receipt["effects"] == DRIFT_EFFECTS
    assert validate_proof_anchor_drift_eligibility(receipt).ok


def test_live_identity_mismatch_uses_only_acquired_live_digests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    try:
        before = c5._counts(paths)

        def changed_identity(*args, **kwargs):
            del args, kwargs
            raise ProofCoverageError(
                "sensitive identity detail",
                code="coverage_live_identity_mismatch",
            )

        monkeypatch.setattr(proof_admission, "_source_snapshot", changed_identity)
        receipt = _evaluate(paths, live, anchor, basis)
        _assert_soft_live_receipt(
            receipt,
            reconstruction_status="indeterminate",
            reason="live_execution_binding_changed",
        )
        observed = receipt["observation"]["live"]
        assert observed["policy_sha256"] == live["policy"]["policy_sha256"]
        assert observed["coverage_group_sha256"] == live["policy"]["coverage_group_sha256"]
        assert observed["basis_sha256"] is None
        assert observed["admission_sha256"] is None
        assert observed["current_proof_sha256"] is None
        assert observed["authority_surface_resolution_sha256"] is None
        assert observed["basis_sha256"] != basis["basis_sha256"]
        assert "sensitive identity detail" not in json.dumps(receipt, sort_keys=True)
        assert c5._counts(paths) == before
    finally:
        context.__exit__(None, None, None)


def test_determinate_candidate_blob_drift_is_a_mismatched_withheld_receipt(
    tmp_path: Path,
) -> None:
    paths, context, live, basis, anchor = _anchored(
        tmp_path,
        split=False,
        include_blob_lookup_decoy=True,
    )
    try:
        before = c5._counts(paths)
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
        changed_policy = bind_trusted_coverage_policy(
            policy,
            expected_policy_sha256=policy["policy_sha256"],
            producer_capability=capability,
        )

        receipt = _evaluate(paths, live, anchor, basis, policy=changed_policy)

        assert receipt["eligibility"]["status"] == "withheld"
        assert receipt["observation"]["live"]["reconstruction_status"] == "mismatched"
        assert "live_policy_changed" in receipt["reason_codes"]
        assert "live_execution_binding_changed" in receipt["reason_codes"]
        assert "computed_verdict_not_passed" in receipt["reason_codes"]
        assert receipt["effects"] == DRIFT_EFFECTS
        assert validate_proof_anchor_drift_eligibility(receipt).ok
        assert c5._counts(paths) == before
    finally:
        context.__exit__(None, None, None)


def _indeterminate_current_proof():
    raise OSError("sensitive current-proof transient")


def _bind_changed_policy(live: dict, *, variant: str):
    policy = deepcopy(live["policy"])
    requirement = policy["required_roles"][0]
    if variant == "candidate-blob":
        decoy = next(
            check
            for check in live["participants"][0].verification_profile["checks"]
            if check["check_id"] == "policy-id-decoy"
        )
        requirement["expected_check"] = {**deepcopy(decoy), "role": "full_regression"}
        requirement["required_candidate_blobs"] = deepcopy(
            decoy["referenced_git_blobs"]
        )
    else:
        requirement["expected_check"]["check_id"] = "renamed-policy-check"
    policy = finalize_proof_coverage_policy(policy)
    capability = issue_trusted_coverage_policy_producer_capability(
        kind="external_bootstrap",
        producer_id="c4-test-producer",
    )
    return bind_trusted_coverage_policy(
        policy,
        expected_policy_sha256=policy["policy_sha256"],
        producer_capability=capability,
    )


@pytest.mark.parametrize(
    ("variant", "live_options", "expected_upstream_reason"),
    [
        (
            "candidate-blob",
            {"split": False, "include_blob_lookup_decoy": True},
            "candidate_blob_oid_mismatch",
        ),
        ("participant-policy", {}, "participant_policy_mismatch"),
    ],
)
def test_determinate_drift_with_indeterminate_current_proof_is_acquired_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
    live_options: dict,
    expected_upstream_reason: str,
) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path, **live_options)
    try:
        before = c5._counts(paths)
        changed_policy = _bind_changed_policy(live, variant=variant)
        admission = evaluate_proof_coverage(
            policy=changed_policy,
            participants=live["participants"],
            authority_provider=lambda: live["authority"],
            current_proof_provider=_indeterminate_current_proof,
        )
        assert admission["admission_state"] == "invalid"
        assert expected_upstream_reason in admission["state_reason_codes"]
        assert "current_proof_indeterminate" in admission["state_reason_codes"]
        assert admission["current_proof"]["proof_sha256"] is None

        monkeypatch.setattr(
            "pcl.proof_anchor_drift.capture_current_proof_in_snapshot",
            lambda *args, **kwargs: _indeterminate_current_proof(),
        )
        receipt = _evaluate(paths, live, anchor, basis, policy=changed_policy)

        assert receipt["eligibility"]["status"] == "withheld"
        assert receipt["observation"]["live"]["reconstruction_status"] == (
            "indeterminate"
        )
        assert receipt["observation"]["live"]["current_proof_sha256"] is None
        assert "computed_verdict_not_passed" in receipt["reason_codes"]
        assert "live_current_proof_changed" in receipt["reason_codes"]
        assert "live_execution_binding_changed" in receipt["reason_codes"]
        assert "live_policy_changed" in receipt["reason_codes"]
        assert "live_chain_unavailable" not in receipt["reason_codes"]
        assert receipt["effects"] == DRIFT_EFFECTS
        assert validate_proof_anchor_drift_eligibility(receipt).ok
        assert "sensitive current-proof transient" not in json.dumps(receipt)
        assert c5._counts(paths) == before
    finally:
        context.__exit__(None, None, None)


def test_nonpassed_c3_and_withheld_c4_cannot_launder_the_computed_verdict(
    tmp_path: Path,
) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    try:
        before = c5._counts(paths)
        original = live["participants"][0]
        aggregate = deepcopy(dict(original.bundle.aggregate))
        aggregate.update(
            {
                "verdict": "failed",
                "anchoring_eligible": False,
                "positive_proof_handoff": "withheld",
                "reuse_disposition": "fresh_only",
            }
        )
        aggregate = finalize_proof_execution_document(aggregate)
        bundle_receipt = deepcopy(dict(original.bundle.bundle_receipt))
        bundle_receipt["aggregate_sha256"] = aggregate["aggregate_sha256"]
        for item in bundle_receipt["objects"]:
            if item["role"] == "aggregate":
                item["sha256"] = aggregate["aggregate_sha256"]
        bundle_receipt["objects"].sort(key=lambda item: (item["role"], item["sha256"]))
        bundle_receipt = finalize_proof_execution_document(bundle_receipt)
        failed = replace(
            original,
            bundle=replace(
                original.bundle,
                aggregate=aggregate,
                bundle_receipt=bundle_receipt,
            ),
        )
        participants = [failed, *live["participants"][1:]]

        receipt = _evaluate(
            paths,
            live,
            anchor,
            basis,
            participants=participants,
        )

        assert receipt["eligibility"]["status"] == "withheld"
        assert receipt["observation"]["live"]["reconstruction_status"] == "mismatched"
        assert "computed_verdict_not_passed" in receipt["reason_codes"]
        assert "live_execution_binding_changed" in receipt["reason_codes"]
        assert receipt["eligibility"]["matched"] is False
        assert receipt["eligibility"]["direct_input_right"] is False
        assert receipt["eligibility"]["check_skip_authorized"] is False
        assert receipt["eligibility"]["result_substitution_authorized"] is False
        assert validate_proof_anchor_drift_eligibility(receipt).ok
        assert c5._counts(paths) == before
    finally:
        context.__exit__(None, None, None)


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("candidate", "live_candidate_changed"),
        ("policy", "live_policy_changed"),
        ("authority", "live_authority_changed"),
        ("canary", "live_canary_changed"),
        ("current_proof", "live_current_proof_changed"),
        ("execution", "live_execution_binding_changed"),
        ("verdict", "computed_verdict_not_passed"),
    ],
)
def test_all_determinate_live_reasons_are_classified(
    tmp_path: Path,
    mutation: str,
    expected_reason: str,
) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    del paths, live, anchor
    try:
        changed = deepcopy(dict(basis))
        if mutation == "candidate":
            changed["candidate"]["tree_oid"] = "f" * len(changed["candidate"]["tree_oid"])
        elif mutation == "policy":
            changed["bindings"]["policy_sha256"] = "sha256:" + "1" * 64
        elif mutation == "authority":
            changed["policy"]["authority_bindings"][
                "authority_surface_resolution_sha256"
            ] = "sha256:" + "2" * 64
        elif mutation == "canary":
            changed["policy"]["authority_bindings"]["canary_union_sha256"] = (
                "sha256:" + "3" * 64
            )
        elif mutation == "current_proof":
            changed["admission"]["current_proof"]["proof_sha256"] = "sha256:" + "4" * 64
        elif mutation == "execution":
            changed["bindings"]["coverage_group_sha256"] = "sha256:" + "5" * 64
        else:
            changed["admission"]["admission_state"] = "invalid"
        assert expected_reason in _live_reasons(basis, changed)
    finally:
        context.__exit__(None, None, None)


def test_invalid_live_state_precedes_transient_indeterminate_reason(tmp_path: Path) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    del paths, live, anchor
    try:
        changed = deepcopy(dict(basis))
        changed["admission"]["admission_state"] = "invalid"
        changed["admission"]["state_reason_codes"] = [
            "candidate_blob_oid_mismatch",
            "current_proof_indeterminate",
        ]
        assert _soft_live_reconstruction(changed) is None
    finally:
        context.__exit__(None, None, None)


def test_participant_aggregate_indeterminate_is_classified(tmp_path: Path) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    del paths, live, anchor
    try:
        changed = deepcopy(dict(basis))
        changed["admission"]["admission_state"] = "indeterminate"
        changed["admission"]["state_reason_codes"] = [
            "participant_aggregate_indeterminate"
        ]
        classified = _soft_live_reconstruction(changed)
        assert classified is not None
        status, reason, _ = classified
        assert status == "indeterminate"
        assert reason == "live_reconstruction_indeterminate"
    finally:
        context.__exit__(None, None, None)


@pytest.mark.parametrize(
    "failure_code",
    [
        "proof_current_task_missing",
        "proof_current_evidence_inconclusive",
        None,
    ],
    ids=["task-missing", "evidence-inconclusive", "provider-unavailable"],
)
def test_current_proof_unavailable_is_an_unavailable_withheld_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_code: str | None,
) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    try:
        before = c5._counts(paths)

        def unavailable_current_proof(*args, **kwargs):
            del args, kwargs
            if failure_code is None:
                raise RuntimeError("sensitive current-proof provider detail")
            raise ProofExecutionError(
                "sensitive current-proof detail",
                code=failure_code,
            )

        monkeypatch.setattr(
            "pcl.proof_anchor_drift.capture_current_proof_in_snapshot",
            unavailable_current_proof,
        )
        receipt = _evaluate(paths, live, anchor, basis)
        _assert_soft_live_receipt(
            receipt,
            reconstruction_status="unavailable",
            reason="live_chain_unavailable",
        )
        assert receipt["observation"]["live"]["current_proof_sha256"] is None
        assert "sensitive current-proof detail" not in json.dumps(receipt, sort_keys=True)
        assert "sensitive current-proof provider detail" not in json.dumps(
            receipt,
            sort_keys=True,
        )
        assert c5._counts(paths) == before
    finally:
        context.__exit__(None, None, None)


def test_authority_provider_unavailable_is_an_unavailable_withheld_receipt(
    tmp_path: Path,
) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    try:
        before = c5._counts(paths)

        def unavailable_authority():
            raise RuntimeError("sensitive authority detail")

        receipt = _evaluate(
            paths,
            live,
            anchor,
            basis,
            authority_provider=unavailable_authority,
        )
        _assert_soft_live_receipt(
            receipt,
            reconstruction_status="unavailable",
            reason="live_chain_unavailable",
        )
        assert (
            receipt["observation"]["live"]["authority_surface_resolution_sha256"]
            is None
        )
        assert "sensitive authority detail" not in json.dumps(receipt, sort_keys=True)
        assert c5._counts(paths) == before
    finally:
        context.__exit__(None, None, None)


def test_git_currentness_unavailable_is_an_indeterminate_withheld_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    try:
        before = c5._counts(paths)

        def unavailable_git(*args, **kwargs):
            del args, kwargs
            raise proof_admission._GitObservationIndeterminate

        monkeypatch.setattr(proof_admission, "_source_snapshot", unavailable_git)
        receipt = _evaluate(paths, live, anchor, basis)
        _assert_soft_live_receipt(
            receipt,
            reconstruction_status="indeterminate",
            reason="live_reconstruction_indeterminate",
        )
        assert c5._counts(paths) == before
    finally:
        context.__exit__(None, None, None)


def test_current_proof_snapshot_invariant_remains_a_sanitized_hard_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    try:
        before = c5._counts(paths)

        def invalid_snapshot(*args, **kwargs):
            del args, kwargs
            raise ProofExecutionError(
                "sensitive snapshot invariant detail",
                code="proof_current_snapshot_required",
            )

        monkeypatch.setattr(
            "pcl.proof_anchor_drift.capture_current_proof_in_snapshot",
            invalid_snapshot,
        )
        with pytest.raises(ProofAnchorDriftError) as exc_info:
            _evaluate(paths, live, anchor, basis)
        assert exc_info.value.code == "drift_internal_error"
        assert exc_info.value.details == {"phase": "live"}
        assert "sensitive snapshot invariant detail" not in json.dumps(
            exc_info.value.to_dict(),
            sort_keys=True,
        )
        assert c5._counts(paths) == before
    finally:
        context.__exit__(None, None, None)


@pytest.mark.skipif(os.name != "posix", reason="C6 is POSIX-only")
def test_genuine_hot_rollback_journal_is_classified_on_python310_and_newer(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "hot.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA page_size=4096")
        conn.execute("CREATE TABLE payloads(id INTEGER PRIMARY KEY, payload BLOB NOT NULL)")
        conn.executemany(
            "INSERT INTO payloads(payload) VALUES (randomblob(8192))",
            [()] * 4096,
        )
        conn.commit()
    finally:
        conn.close()
    child = (
        "import os,sqlite3,sys;"
        "c=sqlite3.connect(sys.argv[1]);"
        "c.execute('PRAGMA journal_mode=DELETE');"
        "c.execute('PRAGMA cache_size=10');"
        "c.execute('BEGIN IMMEDIATE');"
        "c.execute('UPDATE payloads SET payload=zeroblob(8192)');"
        "os._exit(0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", child, str(db_path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert completed.returncode == 0
    assert db_path.with_name(db_path.name + "-journal").exists()
    with pytest.raises(sqlite3.OperationalError) as exc_info:
        _open_pinned_read_snapshot(db_path)
    error_code = getattr(exc_info.value, "sqlite_errorcode", None)
    if error_code is not None:
        assert error_code == 776
    assert _classify_sqlite_error(exc_info.value) == "drift_database_recovery_required"


def test_schema_and_missing_lock_are_typed_receiptless_stops(tmp_path: Path) -> None:
    paths, context, live, basis, anchor = _anchored(tmp_path)
    try:
        paths.loop_dir.joinpath("project.lock").unlink()
        with pytest.raises(ProofAnchorDriftError) as missing:
            _evaluate(paths, live, anchor, basis)
        assert missing.value.code == "drift_lock_unavailable"
        assert set(missing.value.details) == {"phase"}
        assert not paths.loop_dir.joinpath("project.lock").exists()

        paths.loop_dir.joinpath("project.lock").write_bytes(b"")
        paths.loop_dir.joinpath("project.lock").chmod(0o600)
        conn = connect(paths.db_path)
        try:
            conn.execute("UPDATE metadata SET value='7' WHERE key='schema_version'")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(ProofAnchorDriftError) as schema:
            _evaluate(paths, live, anchor, basis)
        assert schema.value.code == "drift_database_schema_unsupported"
        assert set(schema.value.details) == {"phase"}
    finally:
        context.__exit__(None, None, None)


def test_no_public_cli_mcp_renderer_or_legacy_consumer() -> None:
    encoded = "\n".join(
        (
            Path(cli.__file__).read_text(encoding="utf-8"),
            Path(mcp_server.__file__).read_text(encoding="utf-8"),
            Path(renderer.__file__).read_text(encoding="utf-8"),
        )
    )
    assert "proof_anchor_drift" not in encoded
    assert "drift_eligibility_predicate" not in encoded


def test_error_payload_never_contains_raw_details(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "not-initialized")
    paths.loop_dir.mkdir(parents=True)
    paths.loop_dir.joinpath("project.lock").write_bytes(b"")
    paths.loop_dir.joinpath("project.lock").chmod(0o600)
    with pytest.raises(ProofAnchorDriftError) as exc_info:
        evaluate_proof_anchor_drift_eligibility(
            paths,
            anchor_event_id="EV-" + "A" * 64,
            expected_target_id="T-0001",
            expected_candidate={
                "object_format": "sha1",
                "commit_oid": "1" * 40,
                "tree_oid": "2" * 40,
            },
            expected_basis_sha256="sha256:" + "a" * 64,
            policy=object(),
            participants=(),
            authority_provider=lambda: None,
        )
    payload = json.dumps(exc_info.value.to_dict(), sort_keys=True)
    assert str(paths.root) not in payload
    assert "project.db" not in payload
