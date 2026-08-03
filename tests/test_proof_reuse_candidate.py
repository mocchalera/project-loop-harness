from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator

import pytest

import pcl.outbox as outbox_runtime
import pcl.proof_reuse_candidate as candidate_runtime
import pcl.proof_reuse_candidate_store as candidate_store
import test_proof_admission as c4
import test_proof_anchor as c5
import test_proof_execution as c3
import test_proof_workspace as c2
from pcl.contracts.authority_surface import authority_document_sha256
from pcl.contracts.proof_admission import (
    canary_item_sha256,
)
from pcl.init_project import init_project
from pcl.db import connect
from pcl.outbox import ProjectionResult
from pcl.paths import ProjectPaths
from pcl.proof_admission import (
    ProofCoverageParticipant,
    bind_trusted_coverage_policy,
    issue_trusted_coverage_policy_producer_capability,
)
from pcl.proof_anchor import build_proof_admission_anchor_basis
from pcl.proof_execution import capture_current_proof
from pcl.proof_reuse_candidate import (
    PROOF_REUSE_CANDIDATE_EVIDENCE_TYPE,
    PROOF_REUSE_CANDIDATE_EVENT_TYPE,
    PROOF_REUSE_CANDIDATE_LINK_ROLE,
    ProofReuseCandidateError,
    _authority_disposition,
    record_proof_reuse_candidate,
)
from pcl.proof_reuse_candidate_store import candidate_directory


@contextmanager
def _authentic_c1_c5(tmp_path: Path) -> Iterator[dict[str, Any]]:
    init_project(ProjectPaths(tmp_path / "project"), with_claude=False)
    paths, _evidence_id, task_id = c3._current_proof_project(tmp_path / "project")
    seed = c3._case(tmp_path / "seed")
    blob_oid = c2._git(seed.root, "rev-parse", f"{seed.candidate}:src/candidate_only.py")
    canary_argv = [
        sys.executable,
        "-c",
        "import candidate_only; print(candidate_only.VALUE)",
    ]
    canary = {
        "id": "coverage-canary",
        "authority_claim_ids": ["C7-canary"],
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
    checks = [
        c4._profile_check(
            "full-regression",
            "full_regression",
            canary_argv,
            blob_oid,
            selectors=[],
        ),
        c4._profile_check(
            "authority-canary",
            "authority_canary.coverage-canary",
            canary_argv,
            blob_oid,
            selectors=["test_z", "test_a"],
        ),
    ]
    profiles = [
        c4._profile("full-profile", [checks[0]]),
        c4._profile("canary-profile", [checks[1]]),
    ]
    lease_parent = tmp_path / "leases"
    lease_parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        participants: list[ProofCoverageParticipant] = []
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
            target = dict(spec["target"])
            bundle = c3._execute(
                case,
                prepared,
                current_proof_provider=lambda target=target: capture_current_proof(
                    paths,
                    target,
                ),
            )
            participants.append(
                ProofCoverageParticipant(
                    prepared=prepared,
                    spec=spec,
                    authority_resolution=resolution,
                    bootstrap_profile=bootstrap,
                    verification_profile=profile,
                    bundle=bundle,
                )
            )
        policy_document = c4._policy_document(
            participants,
            resolution=resolution,
            bootstrap=bootstrap,
            canary=canary,
        )
        capability = issue_trusted_coverage_policy_producer_capability(
            kind="external_bootstrap",
            producer_id="c4-test-producer",
        )
        policy = bind_trusted_coverage_policy(
            policy_document,
            expected_policy_sha256=policy_document["policy_sha256"],
            producer_capability=capability,
        )
        target = {"type": "task", "id": task_id}
        basis = build_proof_admission_anchor_basis(
            policy=policy,
            participants=participants,
            authority_provider=lambda: authority,
            current_proof_provider=lambda: capture_current_proof(paths, target),
        )
        anchor = c5._anchor(
            paths,
            {
                "bound": policy,
                "participants": participants,
                "authority": authority,
            },
            basis,
            c5._authorizations(basis),
        )
        yield {
            "paths": paths,
            "target": target,
            "policy": policy,
            "participants": participants,
            "authority": authority,
            "basis": basis,
            "anchor": anchor,
            "resolution_sha256": authority_document_sha256(resolution),
            "canary_sha256": canary_item_sha256(canary),
        }


def _record(live: dict[str, Any], **overrides: Any):
    values = {
        "anchor_event_id": live["anchor"]["event_id"],
        "expected_target_id": live["target"]["id"],
        "expected_candidate": live["basis"]["candidate"],
        "expected_basis_sha256": live["basis"]["basis_sha256"],
        "policy": live["policy"],
        "participants": live["participants"],
        "authority_provider": lambda: live["authority"],
    }
    values.update(overrides)
    return record_proof_reuse_candidate(live["paths"], **values)


def _counts(paths: ProjectPaths) -> dict[str, int]:
    conn = connect(paths.db_path)
    try:
        return {
            "evidence": int(
                conn.execute(
                    "SELECT COUNT(*) FROM evidence WHERE type = ?",
                    (PROOF_REUSE_CANDIDATE_EVIDENCE_TYPE,),
                ).fetchone()[0]
            ),
            "links": int(
                conn.execute(
                    "SELECT COUNT(*) FROM evidence_links WHERE link_role = ?",
                    (PROOF_REUSE_CANDIDATE_LINK_ROLE,),
                ).fetchone()[0]
            ),
            "events": int(
                conn.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type = ?",
                    (PROOF_REUSE_CANDIDATE_EVENT_TYPE,),
                ).fetchone()[0]
            ),
            "outbox": int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM outbox_records
                    JOIN events ON events.id = outbox_records.event_id
                    WHERE events.event_type = ?
                    """,
                    (PROOF_REUSE_CANDIDATE_EVENT_TYPE,),
                ).fetchone()[0]
            ),
        }
    finally:
        conn.close()


def test_authentic_c1_c5_source_can_record_one_c7_candidate(tmp_path: Path) -> None:
    with _authentic_c1_c5(tmp_path) as live:
        result = _record(live)

    assert result["ok"] is True
    assert result["status"] == "recordable"
    assert result["changed"] is True
    assert result["candidate"]["current_proof"] == {
        "scope": "feature",
        "status": "healthy",
        "match_status": "matched",
        "proof_sha256": live["basis"]["admission"]["current_proof"][
            "proof_sha256"
        ],
    }
    assert result["candidate"]["authorization"]["reuse_authorized"] is False
    assert result["candidate"]["handoff"] == {
        "status": "durable_candidate",
        "consumer_enabled": False,
        "separate_authorization_required": True,
    }


def test_first_writer_stored_body_replay_and_16_way_concurrency(tmp_path: Path) -> None:
    with _authentic_c1_c5(tmp_path) as live:
        first = _record(live)
        first_body = json.dumps(
            first["candidate"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        first_observation = deepcopy(first["candidate"]["observation"])
        with ThreadPoolExecutor(max_workers=15) as pool:
            replays = list(pool.map(lambda _: _record(live), range(15)))
        assert {item["projection"]["status"] for item in replays} == {"replayed"}
        assert all(item["idempotent"] is True for item in replays)
        assert all(item["effects"]["events_appended"] == 0 for item in replays)
        assert all(item["candidate"]["observation"] == first_observation for item in replays)
        assert all(
            json.dumps(
                item["candidate"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            == first_body
            for item in replays
        )
        stored = (
            candidate_directory(live["paths"], first["candidate_id"])
            / "candidate.json"
        ).read_bytes()
        assert stored == first_body
        assert _counts(live["paths"]) == {
            "evidence": 1,
            "links": 1,
            "events": 1,
            "outbox": 1,
        }
        assert sum(
            1
            for line in live["paths"].events_path.read_text().splitlines()
            if json.loads(line)["event_type"] == PROOF_REUSE_CANDIDATE_EVENT_TYPE
        ) == 1


def test_assertion_failure_and_unhealthy_c5_have_zero_c7_effect(tmp_path: Path) -> None:
    with _authentic_c1_c5(tmp_path) as live:
        before = _counts(live["paths"])
        invalid = _record(live, expected_target_id="T-9999")
        assert invalid["status"] == "invalid"
        assert invalid["reason_codes"] == ["source_authorization_invalid"]
        assert invalid["effects"]["events_appended"] == 0
        assert _counts(live["paths"]) == before

        c5._tamper_basis(live["paths"], live["anchor"])
        unavailable = _record(live)
        assert unavailable["status"] == "withheld"
        assert unavailable["reason_codes"] == ["source_anchor_recovery_required"]
        assert _counts(live["paths"]) == before


def test_postcommit_filesystem_health_failure_returns_truthful_committed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _authentic_c1_c5(tmp_path) as live:
        original = candidate_runtime.assess_proof_reuse_candidate_artifact
        calls = 0

        def filesystem_boundary_fault(*args: Any, **kwargs: Any):
            nonlocal calls
            calls += 1
            assessment = original(*args, **kwargs)
            if calls == 2:
                return replace(
                    assessment,
                    status="postcommit_unhealthy",
                    finding_codes=("reuse_candidate_file_hash_mismatch",),
                )
            return assessment

        monkeypatch.setattr(
            candidate_runtime,
            "assess_proof_reuse_candidate_artifact",
            filesystem_boundary_fault,
        )
        committed = _record(live)
        assert committed["ok"] is False
        assert committed["status"] == "recordable"
        assert committed["changed"] is True
        assert committed["mutation_committed"] is True
        assert committed["safe_to_retry_original"] is False
        assert committed["health"]["candidate_artifact"] == "postcommit_unhealthy"
        assert committed["projection"]["status"] == "committed"
        assert _counts(live["paths"])["events"] == 1

        replay = _record(live)
        assert replay["ok"] is True
        assert replay["projection"]["status"] == "replayed"
        assert replay["candidate"] == committed["candidate"]
        assert _counts(live["paths"])["events"] == 1


@pytest.mark.parametrize("delivery", ["pending", "failed_needs_review"])
def test_outbox_delivery_is_separate_and_recovery_never_replays_candidate_dml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    delivery: str,
) -> None:
    with _authentic_c1_c5(tmp_path) as live:
        original = outbox_runtime.project_pending_events

        def projection_boundary(paths: ProjectPaths, **_kwargs: Any) -> ProjectionResult:
            if delivery == "failed_needs_review":
                conn = connect(paths.db_path)
                try:
                    conn.execute(
                        """
                        UPDATE outbox_records SET status='failed_needs_review'
                        WHERE status != 'delivered'
                        """
                    )
                    conn.commit()
                finally:
                    conn.close()
            return ProjectionResult(
                committed=True,
                projection=delivery,
                delivered=0,
                pending_count=1,
                first_pending_sequence=1,
            )

        monkeypatch.setattr(outbox_runtime, "project_pending_events", projection_boundary)
        fresh = _record(live)
        assert fresh["mutation_committed"] is True
        assert fresh["outbox_delivery"] == delivery
        assert fresh["projection"]["status"] == "committed"
        assert _counts(live["paths"])["events"] == 1

        monkeypatch.setattr(outbox_runtime, "project_pending_events", original)
        replay = _record(live)
        assert replay["projection"]["status"] == "replayed"
        assert replay["outbox_delivery"] == (
            "delivered" if delivery == "pending" else "failed_needs_review"
        )
        assert replay["effects"]["events_appended"] == 0
        assert _counts(live["paths"])["events"] == 1


@pytest.mark.parametrize(
    "fault_point",
    [
        "proof_reuse_candidate_before_staging",
        "proof_reuse_candidate_after_staging_directory",
        "proof_reuse_candidate_after_staging_file",
        "proof_reuse_candidate_after_publish",
        "proof_reuse_candidate_after_publish_before_database",
        "proof_reuse_candidate_after_evidence_insert",
        "proof_reuse_candidate_after_link_insert",
        "proof_reuse_candidate_after_event_before_commit",
        "proof_reuse_candidate_before_sqlite_commit",
        "proof_reuse_candidate_after_sqlite_commit_before_health",
        "after_sqlite_commit_before_projector",
        "before_jsonl_append",
        "after_jsonl_fsync_before_delivered_commit",
        "after_outbox_delivered_commit",
    ],
)
def test_crash_boundaries_preserve_one_quartet_or_zero(
    tmp_path: Path,
    fault_point: str,
) -> None:
    if not hasattr(os, "fork"):
        pytest.skip("C7 crash fixture requires POSIX fork")
    with _authentic_c1_c5(tmp_path) as live:
        pid = os.fork()
        if pid == 0:  # pragma: no cover - child is intentionally killed
            os.environ["PCL_ENABLE_TEST_FAULTS"] = "1"
            os.environ["PCL_TEST_FAULT_POINT"] = fault_point
            os.environ["PCL_TEST_FAULT_OCCURRENCE"] = "1"
            _record(live)
            os._exit(0)
        _waited, status = os.waitpid(pid, 0)
        assert status != 0
        committed = fault_point in {
            "proof_reuse_candidate_after_sqlite_commit_before_health",
            "after_sqlite_commit_before_projector",
            "before_jsonl_append",
            "after_jsonl_fsync_before_delivered_commit",
            "after_outbox_delivered_commit",
        }
        assert _counts(live["paths"]) == {
            "evidence": 1 if committed else 0,
            "links": 1 if committed else 0,
            "events": 1 if committed else 0,
            "outbox": 1 if committed else 0,
        }
        if committed:
            replay = _record(live)
            assert replay["projection"]["status"] == "replayed"
            assert replay["outbox_delivery"] == "delivered"
            assert replay["effects"]["events_appended"] == 0
            assert _counts(live["paths"])["events"] == 1


@pytest.mark.parametrize(
    "attack",
    ["hash", "size", "mode", "nlink", "symlink", "ownership", "replacement", "unexpected"],
)
def test_candidate_store_attacks_fail_closed_without_replacement(
    tmp_path: Path,
    attack: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _authentic_c1_c5(tmp_path) as live:
        first = _record(live)
        directory = candidate_directory(live["paths"], first["candidate_id"])
        path = directory / "candidate.json"
        if attack == "hash":
            original = path.read_bytes()
            path.write_bytes(b"X" + original[1:])
        elif attack == "size":
            path.write_bytes(path.read_bytes() + b"X")
        elif attack == "mode":
            path.chmod(0o644)
        elif attack == "nlink":
            os.link(path, directory / "candidate-hardlink.json")
        elif attack == "symlink":
            retained = directory / "candidate-retained.json"
            path.replace(retained)
            path.symlink_to(retained.name)
        elif attack == "ownership":
            monkeypatch.setattr(candidate_store, "_expected_owner", lambda: -1)
        elif attack == "replacement":
            strict_read = candidate_store.strict_read_canonical_file

            def read_then_replace(*args: Any, **kwargs: Any) -> Any:
                receipt = strict_read(*args, **kwargs)
                original = path.read_bytes()
                path.unlink()
                path.write_bytes(original)
                path.chmod(0o600)
                return receipt

            monkeypatch.setattr(
                candidate_store,
                "strict_read_canonical_file",
                read_then_replace,
            )
        else:
            (directory / "unexpected.json").write_text("{}", encoding="utf-8")
        before = _counts(live["paths"])
        with pytest.raises(ProofReuseCandidateError) as conflict:
            _record(live)
        assert conflict.value.code == "reuse_candidate_idempotency_conflict"
        assert conflict.value.details == {"phase": "replay"}
        assert _counts(live["paths"]) == before


def test_c5_authority_precedence_is_closed_before_live_reconstruction() -> None:
    class Resolution:
        tombstone_status = "absent"
        exhaustion_witness = None
        assertion_found = True
        authority_corrupt = False
        malformed_group_present = False
        valid_chains: tuple = ()

    value = Resolution()
    value.tombstone_status = "multiple"
    assert _authority_disposition(value, "EV-X") == (
        "source_anchor_authority_corrupt",
        "invalid",
    )
    value.tombstone_status = "valid"
    assert _authority_disposition(value, "EV-X") == (
        "source_anchor_exhaustion_tombstoned",
        "unavailable",
    )
    value.tombstone_status = "absent"
    value.exhaustion_witness = object()
    assert _authority_disposition(value, "EV-X") == (
        "source_anchor_exhaustion_pending",
        "unavailable",
    )
    value.exhaustion_witness = None
    value.assertion_found = False
    assert _authority_disposition(value, "EV-X") == (
        "source_anchor_not_found",
        "unavailable",
    )


def test_internal_only_firewall_schema8_dependency0_and_no_consumer() -> None:
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in pyproject
    assert candidate_runtime.PROOF_REUSE_CANDIDATE_DATABASE_SCHEMA_VERSION == "8"
    for relative in (
        "src/pcl/cli.py",
        "src/pcl/mcp_server.py",
        "src/pcl/renderer.py",
        "src/pcl/finish_execution.py",
        "src/pcl/finish_planning.py",
        "src/pcl/finish_progress.py",
        "src/pcl/terminal_readiness.py",
        "src/pcl/completion_policies.py",
    ):
        content = (root / relative).read_text(encoding="utf-8")
        assert "record_proof_reuse_candidate" not in content
        assert "proof_reuse_candidate" not in content
