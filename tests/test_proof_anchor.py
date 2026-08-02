from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any

import pytest

import pcl.proof_anchor as anchor_runtime
import pcl.outbox as outbox_runtime
import test_proof_admission as c4
import test_proof_execution as c3
from pcl.audit import audit_check
from pcl.contracts.proof_anchor import (
    ANCHOR_EFFECTS_SUCCESS,
    ANCHOR_EFFECTS_ZERO,
    EXHAUSTION_EFFECTS_SUCCESS,
    finalize_proof_admission_authorization,
)
from pcl.db import connect
from pcl.init_project import init_project
from pcl.errors import ProjectionPendingError
from pcl.outbox import ProjectionResult
from pcl.paths import ProjectPaths
from pcl.proof_anchor import (
    ProofAdmissionAuthorizationIssuerCapability,
    ProofAnchorError,
    anchor_proof_admission,
    bind_proof_admission_authorization,
    build_proof_admission_anchor_basis,
    issue_proof_admission_authorization_issuer_capability,
)
from pcl.proof_anchor_store import anchor_directory, anchor_storage_root
from pcl.validators import validate_project


def _initialize(paths: ProjectPaths) -> None:
    init_project(paths, with_claude=False)
    conn = connect(paths.db_path)
    try:
        now = "2026-08-02T00:00:00Z"
        conn.execute(
            """
            INSERT INTO tasks(id,title,status,priority,created_at,updated_at)
            VALUES ('T-0001','C5 target','in_progress',1,?,?)
            """,
            (now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _basis(live: dict[str, Any]):
    return build_proof_admission_anchor_basis(
        policy=live["bound"],
        participants=live["participants"],
        authority_provider=lambda: live["authority"],
        current_proof_provider=c3._not_applicable,
    )


def _authorization(
    basis,
    *,
    authorization_kind: str = "independent_review",
    actor_id: str = "agent:c5-reviewer",
    revision: int = 0,
):
    human = authorization_kind == "human_gate"
    actor_kind = "human" if human else "agent"
    if human and actor_id == "agent:c5-reviewer":
        actor_id = "human:c5-owner"
    capability = issue_proof_admission_authorization_issuer_capability(
        authorization_kind=authorization_kind,
        actor_kind=actor_kind,
        actor_id=actor_id,
        source_kind="cli",
    )
    policy = basis["policy"]
    document = finalize_proof_admission_authorization(
        {
            "contract_version": "proof-admission-authorization/v1",
            "authorization_id": f"PAUTH-{authorization_kind}-{revision}",
            "authorization_kind": authorization_kind,
            "decision": "approved",
            "authority": {
                "actor_kind": actor_kind,
                "actor_id": actor_id,
                "recorder_kind": actor_kind,
                "recorder_id": actor_id,
                "source_kind": "cli",
                "source_ref": "",
                "candidate_controlled": False,
            },
            "target": deepcopy(basis["target"]),
            "candidate": deepcopy(basis["candidate"]),
            "bindings": {
                "basis_sha256": basis["basis_sha256"],
                "policy_sha256": basis["bindings"]["policy_sha256"],
                "coverage_group_sha256": basis["bindings"]["coverage_group_sha256"],
                "admission_sha256": basis["bindings"]["admission_sha256"],
                "producer_sha256": policy["producer"]["producer_sha256"],
            },
            "authorization_subject_sha256": "sha256:" + "0" * 64,
            "review": (
                None
                if human
                else {
                    "report_sha256": "sha256:" + "c" * 64,
                    "report_size_bytes": 123,
                    "findings": {"high": 0, "medium": 0, "low": 1},
                }
            ),
            "scope": {
                "anchor": True,
                "reuse": False,
                "terminal": False,
                "publication": False,
            },
            "issued_at": f"2026-08-02T00:00:{revision:02d}Z",
            "reason": f"Anchor-only authorization revision {revision}.",
            "authorization_sha256": "sha256:" + "0" * 64,
        }
    )
    trusted = bind_proof_admission_authorization(
        document,
        expected_authorization_sha256=document["authorization_sha256"],
        issuer_capability=capability,
    )
    return document, capability, trusted


def _authorizations(basis, *, revision: int = 0, actor_id: str = "agent:c5-reviewer"):
    review = _authorization(basis, revision=revision, actor_id=actor_id)
    human = None
    if basis["policy"]["authorization_requirements"]["human_gate"] == "required":
        human = _authorization(
            basis,
            authorization_kind="human_gate",
            revision=revision,
        )
    return review, human


def _anchor(paths: ProjectPaths, live, basis, authorizations):
    review, human = authorizations
    return anchor_proof_admission(
        paths,
        policy=live["bound"],
        participants=live["participants"],
        authority_provider=lambda: live["authority"],
        expected_basis_sha256=basis["basis_sha256"],
        independent_review=review[2],
        human_gate=None if human is None else human[2],
    )


def _counts(paths: ProjectPaths) -> dict[str, int]:
    conn = connect(paths.db_path)
    try:
        return {
            "evidence": int(
                conn.execute(
                    "SELECT COUNT(*) FROM evidence WHERE type='proof_admission_anchor'"
                ).fetchone()[0]
            ),
            "links": int(
                conn.execute(
                    "SELECT COUNT(*) FROM evidence_links WHERE link_role='proof_admission_anchor'"
                ).fetchone()[0]
            ),
            "events": int(
                conn.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type='proof_admission_anchored'"
                ).fetchone()[0]
            ),
            "outbox": int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM outbox_records
                    JOIN events ON events.id=outbox_records.event_id
                    WHERE events.event_type='proof_admission_anchored'
                    """
                ).fetchone()[0]
            ),
            "tombstones": int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM events
                    WHERE event_type='proof_admission_anchor_recovery_exhausted'
                    """
                ).fetchone()[0]
            ),
        }
    finally:
        conn.close()


def _tamper_basis(paths: ProjectPaths, result: dict[str, Any]) -> None:
    path = anchor_directory(paths, result["request_id"]) / "basis.json"
    original = path.read_bytes()
    path.write_bytes(b"X" + original[1:])


def _rewrite_jsonl_basis(paths: ProjectPaths, event_id: str, basis_sha256: str) -> None:
    records = [json.loads(line) for line in paths.events_path.read_text().splitlines()]
    record = next(item for item in records if item["id"] == event_id)
    record["payload"]["basis_sha256"] = basis_sha256
    paths.events_path.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for item in records
        ),
        encoding="utf-8",
    )


def test_authorization_is_detached_deep_frozen_and_registry_bound(tmp_path: Path) -> None:
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        document, capability, trusted = _authorization(basis)
        before = trusted.document["authorization_sha256"]
        document["reason"] = "mutated"
        document["bindings"]["basis_sha256"] = "sha256:" + "f" * 64
        assert trusted.document["authorization_sha256"] == before
        with pytest.raises(TypeError):
            trusted.document["reason"] = "cannot mutate"
        with pytest.raises(TypeError):
            ProofAdmissionAuthorizationIssuerCapability(
                authorization_kind="independent_review",
                actor_kind="agent",
                actor_id="agent:forged",
                recorder_kind="agent",
                recorder_id="agent:forged",
                source_kind="cli",
                source_ref="",
                candidate_controlled=False,
                _issuer=object(),
            )
        assert capability.candidate_controlled is False
        paths = ProjectPaths(tmp_path / "project")
        _initialize(paths)
        producer_review = _authorization(
            basis,
            actor_id=basis["policy"]["producer"]["producer_id"],
        )
        human = None
        if basis["policy"]["authorization_requirements"]["human_gate"] == "required":
            human = _authorization(basis, authorization_kind="human_gate")
        with pytest.raises(ProofAnchorError) as collision:
            _anchor(paths, live, basis, (producer_review, human))
        assert collision.value.code == "proof_anchor_review_independence_invalid"
        assert _counts(paths)["events"] == 0

        secret_document, secret_capability, _trusted = _authorization(basis)
        secret_document["reason"] = "token=0123456789abcdef0123456789abcdef"
        secret_document = finalize_proof_admission_authorization(secret_document)
        secret_review = bind_proof_admission_authorization(
            secret_document,
            expected_authorization_sha256=secret_document["authorization_sha256"],
            issuer_capability=secret_capability,
        )
        with pytest.raises(ProofAnchorError) as secret:
            _anchor(
                paths,
                live,
                basis,
                ((secret_document, secret_capability, secret_review), human),
            )
        assert secret.value.code == "proof_anchor_sensitive_content_detected"
        assert secret.value.details["effects"] == ANCHOR_EFFECTS_ZERO
        assert _counts(paths)["events"] == 0


def test_atomic_fresh_anchor_exact_replay_and_16_way_same_request(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _initialize(paths)
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        authorizations = _authorizations(basis)
        first = _anchor(paths, live, basis, authorizations)
        assert first["status"] == "anchored"
        assert first["effects"] == ANCHOR_EFFECTS_SUCCESS
        assert _counts(paths) == {
            "evidence": 1,
            "links": 1,
            "events": 1,
            "outbox": 1,
            "tombstones": 0,
        }
        assert audit_check(paths)["ok"] is True
        strict_validation = validate_project(paths, strict=True)
        assert not [
            finding
            for finding in strict_validation.findings
            if finding.code.startswith("proof_anchor_")
        ]
        manifest_path = anchor_directory(paths, first["request_id"]) / "evidence-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        assert "evidence_id" not in manifest
        assert [member["role"] for member in manifest["members"]] in (
            ["basis", "independent_review"],
            ["basis", "independent_review", "human_gate"],
        )
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(
                pool.map(
                    lambda _: _anchor(paths, live, basis, authorizations),
                    range(16),
                )
            )
        assert {item["status"] for item in results} == {"already_anchored"}
        assert all(item["effects"] == ANCHOR_EFFECTS_ZERO for item in results)
        assert _counts(paths)["events"] == 1
        assert sum(
            1
            for line in paths.events_path.read_text().splitlines()
            if json.loads(line)["event_type"] == "proof_admission_anchored"
        ) == 1
        with pytest.raises(ProofAnchorError) as changed_authorization:
            _anchor(
                paths,
                live,
                basis,
                _authorizations(basis, revision=1),
            )
        assert changed_authorization.value.code == "proof_anchor_idempotency_conflict"
        assert changed_authorization.value.details["effects"] == ANCHOR_EFFECTS_ZERO
        assert _counts(paths)["events"] == 1


def test_database_schema_must_be_exactly_8_before_mutation(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _initialize(paths)
    conn = connect(paths.db_path)
    try:
        conn.execute(
            "UPDATE metadata SET value='7' WHERE key='schema_version'"
        )
        conn.commit()
    finally:
        conn.close()
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        before = _counts(paths)
        with pytest.raises(ProofAnchorError) as mismatch:
            _anchor(paths, live, basis, _authorizations(basis))
    assert mismatch.value.code == "proof_anchor_input_invalid"
    assert mismatch.value.exit_code == 2
    assert mismatch.value.details == {
        "phase": "schema_version",
        "effects": ANCHOR_EFFECTS_ZERO,
    }
    assert _counts(paths) == before
    assert not anchor_storage_root(paths).exists()
    conn = connect(paths.db_path)
    try:
        assert conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()["value"] == "7"
    finally:
        conn.close()


def test_unhealthy_generation_recovery_blocks_other_reviewer_and_exhausts(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _initialize(paths)
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        first = _anchor(paths, live, basis, _authorizations(basis, revision=0))
        _tamper_basis(paths, first)
        audit = audit_check(paths)
        assert any(
            item["type"] == "proof_anchor_postcommit_unhealthy"
            for item in audit["anomalies"]["human_review"]
        )
        assert any(
            finding.code == "proof_anchor_postcommit_unhealthy"
            for finding in validate_project(paths, strict=True).findings
        )

        other = _anchor(
            paths,
            live,
            basis,
            _authorizations(basis, revision=1, actor_id="agent:other-reviewer"),
        )
        assert other == {
            "status": "proof_anchor_existing_chain_recovery_required",
            "base_request_sha256": first["base_request_sha256"],
            "head_generation": 0,
            "head_health": "postcommit_unhealthy",
            "required_generation": 1,
            "changed": False,
            "safe_to_retry_original": False,
        }
        assert _counts(paths)["events"] == 1

        generation1_authorizations = _authorizations(basis, revision=1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            generation1_results = list(
                pool.map(
                    lambda _: _anchor(
                        paths,
                        live,
                        basis,
                        generation1_authorizations,
                    ),
                    range(2),
                )
            )
        generation1 = next(
            item for item in generation1_results if item["status"] == "anchored"
        )
        generation1_replay = next(
            item for item in generation1_results if item["status"] == "already_anchored"
        )
        assert generation1["anchor_generation"] == 1
        assert generation1_replay["anchor_generation"] == 1
        assert generation1_replay["effects"] == ANCHOR_EFFECTS_ZERO
        recovery_manifest = json.loads(
            (
                anchor_directory(paths, generation1["request_id"])
                / "evidence-manifest.json"
            ).read_bytes()
        )
        recovery_health = recovery_manifest["request"]["recovery"]
        assert recovery_health["contract_version"] == "proof-admission-anchor-health/v1"
        assert recovery_health["predecessor"]["request_id"] == first["request_id"]
        assert recovery_manifest["epoch"]["recovery_predecessor"] == {
            "request_id": first["request_id"],
            "anchor_generation": 0,
            "event_id": first["event_id"],
            "anchor_sha256": first["anchor_sha256"],
            "health_sha256": recovery_health["health_sha256"],
        }
        _tamper_basis(paths, generation1)

        def generation1_race(actor_id: str):
            try:
                return _anchor(
                    paths,
                    live,
                    basis,
                    _authorizations(basis, revision=2, actor_id=actor_id),
                )
            except ProofAnchorError as exc:
                return {"error": exc.code}

        with ThreadPoolExecutor(max_workers=2) as pool:
            race = list(
                pool.map(
                    generation1_race,
                    ("agent:c5-reviewer", "agent:other-reviewer"),
                )
            )
        generation2 = next(item for item in race if item.get("anchor_generation") == 2)
        other_disposition = next(item for item in race if item is not generation2)
        assert other_disposition.get("status") in {
            "proof_anchor_existing_chain_recovery_required",
            None,
        }
        if "error" in other_disposition:
            assert other_disposition["error"] == "proof_anchor_duplicate_basis_conflict"
        assert _counts(paths)["events"] == 3
        _tamper_basis(paths, generation2)

        generation3 = _anchor(
            paths,
            live,
            basis,
            _authorizations(basis, revision=3),
        )
        assert generation3["anchor_generation"] == 3
        _tamper_basis(paths, generation3)

        def exhaustion_race(actor_id: str):
            return _anchor(
                paths,
                live,
                basis,
                _authorizations(basis, revision=4, actor_id=actor_id),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            exhausted_results = list(
                pool.map(
                    exhaustion_race,
                    ("agent:other-reviewer", "agent:third-reviewer"),
                )
            )
        assert {item["status"] for item in exhausted_results} == {
            "proof_anchor_recovery_generation_exhausted"
        }
        assert sorted((item["effects"] for item in exhausted_results), key=str) == sorted(
            (EXHAUSTION_EFFECTS_SUCCESS, ANCHOR_EFFECTS_ZERO),
            key=str,
        )
        assert _counts(paths) == {
            "evidence": 4,
            "links": 4,
            "events": 4,
            "outbox": 4,
            "tombstones": 1,
        }
        replay = _anchor(
            paths,
            live,
            basis,
            _authorizations(basis, revision=5, actor_id="agent:third-reviewer"),
        )
        assert replay["idempotent"] is True
        assert replay["effects"] == ANCHOR_EFFECTS_ZERO
        assert _counts(paths)["tombstones"] == 1
        exhausted_audit = audit_check(paths)
        assert not any(
            item["type"] == "proof_anchor_exhaustion_event_invalid"
            for item in exhausted_audit["anomalies"]["human_review"]
        )
        exhausted_validation = validate_project(paths, strict=True)
        assert not any(
            finding.code == "proof_anchor_exhaustion_event_invalid"
            for finding in exhausted_validation.findings
        )


def test_mixed_request_16_way_race_never_opens_parallel_chain(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _initialize(paths)
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        review_a = _authorizations(basis, actor_id="agent:reviewer-a")
        review_b = _authorizations(basis, actor_id="agent:reviewer-b")

        def call(index: int):
            try:
                return _anchor(
                    paths,
                    live,
                    basis,
                    review_a if index % 2 == 0 else review_b,
                )
            except ProofAnchorError as exc:
                return {"error": exc.code}

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(call, range(16)))
        assert sum(item.get("status") == "anchored" for item in results) == 1
        winning_statuses = {
            item.get("status")
            for item in results
            if item.get("status") is not None
        }
        assert winning_statuses <= {"anchored", "already_anchored"}
        assert {
            item["error"] for item in results if "error" in item
        } <= {"proof_anchor_duplicate_basis_conflict"}
        assert _counts(paths)["events"] == 1


def test_basis_wide_parallel_and_gap_corruption_fail_closed(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _initialize(paths)
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        first = _anchor(
            paths,
            live,
            basis,
            _authorizations(basis, actor_id="agent:reviewer-a"),
        )
        hidden_basis = "sha256:" + "f" * 64
        conn = connect(paths.db_path)
        try:
            event = conn.execute(
                "SELECT payload_json FROM events WHERE id = ?",
                (first["event_id"],),
            ).fetchone()
            payload = json.loads(event["payload_json"])
            payload["basis_sha256"] = hidden_basis
            evidence = conn.execute(
                "SELECT summary FROM evidence WHERE id = ?",
                (first["evidence_id"],),
            ).fetchone()
            summary = json.loads(evidence["summary"])
            summary["basis_sha256"] = hidden_basis
            conn.execute(
                "UPDATE events SET payload_json = ? WHERE id = ?",
                (json.dumps(payload), first["event_id"]),
            )
            conn.execute(
                "UPDATE evidence SET summary = ? WHERE id = ?",
                (json.dumps(summary), first["evidence_id"]),
            )
            conn.commit()
        finally:
            conn.close()
        _rewrite_jsonl_basis(paths, first["event_id"], hidden_basis)

        second = _anchor(
            paths,
            live,
            basis,
            _authorizations(basis, actor_id="agent:reviewer-b"),
        )
        assert second["status"] == "anchored"

        conn = connect(paths.db_path)
        try:
            payload["basis_sha256"] = basis["basis_sha256"]
            summary["basis_sha256"] = basis["basis_sha256"]
            conn.execute(
                "UPDATE events SET payload_json = ? WHERE id = ?",
                (json.dumps(payload), first["event_id"]),
            )
            conn.execute(
                "UPDATE evidence SET summary = ? WHERE id = ?",
                (json.dumps(summary), first["evidence_id"]),
            )
            conn.commit()
        finally:
            conn.close()
        _rewrite_jsonl_basis(paths, first["event_id"], basis["basis_sha256"])

        before = _counts(paths)
        with pytest.raises(ProofAnchorError) as parallel:
            _anchor(
                paths,
                live,
                basis,
                _authorizations(basis, actor_id="agent:reviewer-c"),
            )
        assert parallel.value.code == "proof_anchor_parallel_chain_conflict"
        assert parallel.value.details["effects"] == ANCHOR_EFFECTS_ZERO
        assert _counts(paths) == before

        conn = connect(paths.db_path)
        try:
            payload["anchor_generation"] = 2
            summary["anchor_generation"] = 2
            conn.execute(
                "UPDATE events SET payload_json = ? WHERE id = ?",
                (json.dumps(payload), first["event_id"]),
            )
            conn.execute(
                "UPDATE evidence SET summary = ? WHERE id = ?",
                (json.dumps(summary), first["evidence_id"]),
            )
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(ProofAnchorError) as corrupt:
            _anchor(
                paths,
                live,
                basis,
                _authorizations(basis, actor_id="agent:reviewer-d"),
            )
        assert corrupt.value.code == "proof_anchor_committed_authority_corrupt"
        assert corrupt.value.details["effects"] == ANCHOR_EFFECTS_ZERO
        assert _counts(paths) == before


def test_each_committed_authority_quartet_component_fails_closed(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _initialize(paths)
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        authorizations = _authorizations(basis)
        first = _anchor(paths, live, basis, authorizations)
        mutations = (
            (
                "UPDATE evidence_links SET link_role='wrong' WHERE evidence_id=?",
                "UPDATE evidence_links SET link_role='proof_admission_anchor' WHERE evidence_id=?",
                first["evidence_id"],
            ),
            (
                "UPDATE outbox_records SET idempotency_key='wrong' WHERE event_id=?",
                "UPDATE outbox_records SET idempotency_key=? WHERE event_id=?",
                first["event_id"],
            ),
            (
                "UPDATE evidence SET path='wrong' WHERE id=?",
                "UPDATE evidence SET path=? WHERE id=?",
                first["evidence_id"],
            ),
        )
        for mutate, restore, identity in mutations:
            conn = connect(paths.db_path)
            try:
                original = None
                if "outbox_records" in mutate:
                    original = f"jsonl:{first['event_id']}"
                elif "SET path" in mutate:
                    original = (
                        ".project-loop/evidence/proof-admission-anchors/"
                        f"{first['request_id'][3:].lower()}/evidence-manifest.json"
                    )
                conn.execute(mutate, (identity,))
                conn.commit()
            finally:
                conn.close()
            before = _counts(paths)
            with pytest.raises(ProofAnchorError) as corrupt:
                _anchor(paths, live, basis, authorizations)
            assert corrupt.value.code == "proof_anchor_committed_authority_corrupt"
            assert corrupt.value.details["effects"] == ANCHOR_EFFECTS_ZERO
            assert _counts(paths) == before
            conn = connect(paths.db_path)
            try:
                if original is None:
                    conn.execute(restore, (identity,))
                else:
                    conn.execute(restore, (original, identity))
                conn.commit()
            finally:
                conn.close()
        conn = connect(paths.db_path)
        try:
            row = conn.execute(
                "SELECT summary FROM evidence WHERE id=?",
                (first["evidence_id"],),
            ).fetchone()
            original_summary = str(row["summary"])
            changed_summary = json.loads(original_summary)
            changed_summary["unexpected"] = True
            conn.execute(
                "UPDATE evidence SET summary=? WHERE id=?",
                (json.dumps(changed_summary), first["evidence_id"]),
            )
            conn.commit()
        finally:
            conn.close()
        before = _counts(paths)
        with pytest.raises(ProofAnchorError) as corrupt_summary:
            _anchor(paths, live, basis, authorizations)
        assert corrupt_summary.value.code == "proof_anchor_committed_authority_corrupt"
        assert corrupt_summary.value.details["effects"] == ANCHOR_EFFECTS_ZERO
        assert _counts(paths) == before
        conn = connect(paths.db_path)
        try:
            conn.execute(
                "UPDATE evidence SET summary=? WHERE id=?",
                (original_summary, first["evidence_id"]),
            )
            conn.commit()
        finally:
            conn.close()

        paired_summary = json.loads(original_summary)
        assert paired_summary["bindings"]["human_gate_authorization_sha256"] is None
        assert paired_summary["bindings"]["human_gate_subject_sha256"] is None
        paired_summary["bindings"]["human_gate_authorization_sha256"] = (
            "sha256:" + "f" * 64
        )
        conn = connect(paths.db_path)
        try:
            conn.execute(
                "UPDATE evidence SET summary=? WHERE id=?",
                (json.dumps(paired_summary), first["evidence_id"]),
            )
            conn.commit()
        finally:
            conn.close()
        before = _counts(paths)
        with pytest.raises(ProofAnchorError) as mismatched_human_binding:
            _anchor(paths, live, basis, authorizations)
        assert (
            mismatched_human_binding.value.code
            == "proof_anchor_committed_authority_corrupt"
        )
        assert mismatched_human_binding.value.details["effects"] == ANCHOR_EFFECTS_ZERO
        assert _counts(paths) == before
        conn = connect(paths.db_path)
        try:
            conn.execute(
                "UPDATE evidence SET summary=? WHERE id=?",
                (original_summary, first["evidence_id"]),
            )
            conn.commit()
        finally:
            conn.close()
        assert audit_check(paths)["ok"] is True


def test_final_guard_external_tamper_rolls_back_db_and_preserves_orphan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _initialize(paths)
    original_append = anchor_runtime.append_event
    request_ids: list[str] = []

    def append_and_tamper(**kwargs):
        event_id = original_append(**kwargs)
        if kwargs["event_type"] == "proof_admission_anchored":
            request_id = kwargs["payload"]["request_id"]
            request_ids.append(request_id)
            path = anchor_directory(paths, request_id) / "basis.json"
            content = path.read_bytes()
            path.write_bytes(b"X" + content[1:])
        return event_id

    monkeypatch.setattr(anchor_runtime, "append_event", append_and_tamper)
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        with pytest.raises(ProofAnchorError) as failure:
            _anchor(paths, live, basis, _authorizations(basis))
        assert failure.value.code == "proof_anchor_strict_store_invalid"
    assert _counts(paths) == {
        "evidence": 0,
        "links": 0,
        "events": 0,
        "outbox": 0,
        "tombstones": 0,
    }
    assert len(request_ids) == 1
    assert anchor_directory(paths, request_ids[0]).is_dir()
    assert any(
        item["type"] == "proof_anchor_orphan_finalized"
        for item in audit_check(paths)["anomalies"]["human_review"]
    )
    assert not any(
        json.loads(line)["event_type"] == "proof_admission_anchored"
        for line in paths.events_path.read_text().splitlines()
    )


def test_final_guard_authority_drift_rolls_back_filesystem_and_database(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _initialize(paths)
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        authorizations = _authorizations(basis)
        calls = 0

        def provider():
            nonlocal calls
            calls += 1
            if calls >= 5:
                raise OSError("authority changed")
            return live["authority"]

        review, human = authorizations
        with pytest.raises(ProofAnchorError) as failure:
            anchor_proof_admission(
                paths,
                policy=live["bound"],
                participants=live["participants"],
                authority_provider=provider,
                expected_basis_sha256=basis["basis_sha256"],
                independent_review=review[2],
                human_gate=None if human is None else human[2],
            )
        assert failure.value.code == "proof_anchor_live_canary_unresolved"
        assert failure.value.details["effects"] == ANCHOR_EFFECTS_ZERO
    assert _counts(paths) == {
        "evidence": 0,
        "links": 0,
        "events": 0,
        "outbox": 0,
        "tombstones": 0,
    }
    assert not anchor_storage_root(paths).exists()


def test_event_payload_is_private_and_task_scoped(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _initialize(paths)
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        result = _anchor(paths, live, basis, _authorizations(basis))
    conn = sqlite3.connect(paths.db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT entity_type,entity_id,payload_json FROM events WHERE id=?",
            (result["event_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row["entity_type"] == "task"
    assert row["entity_id"] == "T-0001"
    payload = json.loads(row["payload_json"])
    assert set(payload) == {
        "contract_version",
        "request_id",
        "base_request_sha256",
        "anchor_generation",
        "basis_sha256",
        "anchor_sha256",
        "manifest_file_sha256",
        "evidence_id",
    }
    serialized = json.dumps(payload)
    for forbidden in (
        "actor_id",
        "recorder_id",
        "source_ref",
        "reason",
        "report_bytes",
    ):
        assert forbidden not in serialized


def test_projection_pending_commits_once_and_recovers_only_through_flush(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _initialize(paths)
    original_project = outbox_runtime.project_pending_events
    monkeypatch.setattr(
        outbox_runtime,
        "project_pending_events",
        lambda *_args, **_kwargs: ProjectionResult(
            committed=True,
            projection="pending",
            delivered=0,
            pending_count=1,
            first_pending_sequence=2,
            safe_next_action="Run `pcl audit flush --json`; do not retry.",
        ),
    )
    with c4._live_join(tmp_path / "live") as live:
        basis = _basis(live)
        authorizations = _authorizations(basis)
        with pytest.raises(ProjectionPendingError) as pending:
            _anchor(paths, live, basis, authorizations)
        assert pending.value.exit_code == 6
        assert pending.value.details["mutation_committed"] is True
        assert _counts(paths)["events"] == 1
        assert not any(
            json.loads(line)["event_type"] == "proof_admission_anchored"
            for line in paths.events_path.read_text().splitlines()
        )
        with pytest.raises(ProofAnchorError) as blocked:
            _anchor(paths, live, basis, authorizations)
        assert blocked.value.code == "audit_projection_pending"
        assert _counts(paths)["events"] == 1

        monkeypatch.setattr(outbox_runtime, "project_pending_events", original_project)
        assert original_project(paths).ok
        replay = _anchor(paths, live, basis, authorizations)
        assert replay["status"] == "already_anchored"
        assert replay["effects"] == ANCHOR_EFFECTS_ZERO
        assert _counts(paths)["events"] == 1


@pytest.mark.parametrize(
    "fault_point",
    [
        "proof_anchor_before_staging",
        "proof_anchor_after_staging_directory",
        "proof_anchor_after_staging_files",
        "proof_anchor_after_publish",
        "proof_anchor_after_publish_before_database",
        "proof_anchor_after_evidence_insert",
        "proof_anchor_after_link_insert",
        "proof_anchor_after_event_before_commit",
        "before_sqlite_commit",
        "after_sqlite_commit_before_projector",
    ],
)
def test_crash_boundaries_never_create_partial_database_authority(
    tmp_path: Path,
    fault_point: str,
) -> None:
    root = tmp_path / fault_point
    script = """
from pathlib import Path
import sys
import test_proof_admission as c4
from pcl.paths import ProjectPaths
from test_proof_anchor import _anchor, _authorizations, _basis, _initialize
root = Path(sys.argv[1])
paths = ProjectPaths(root / "project")
_initialize(paths)
with c4._live_join(root / "live") as live:
    basis = _basis(live)
    _anchor(paths, live, basis, _authorizations(basis))
"""
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "src:tests",
        "PCL_ENABLE_TEST_FAULTS": "1",
        "PCL_TEST_FAULT_POINT": fault_point,
        "PCL_TEST_FAULT_OCCURRENCE": (
            "2"
            if fault_point in {"before_sqlite_commit", "after_sqlite_commit_before_projector"}
            else "1"
        ),
    }
    completed = subprocess.run(
        [sys.executable, "-c", script, str(root)],
        cwd=Path(__file__).parents[1],
        env=environment,
        check=False,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode != 0
    paths = ProjectPaths(root / "project")
    counts = _counts(paths)
    committed = fault_point == "after_sqlite_commit_before_projector"
    assert counts["evidence"] == (1 if committed else 0)
    assert counts["links"] == (1 if committed else 0)
    assert counts["events"] == (1 if committed else 0)
    assert counts["outbox"] == (1 if committed else 0)
    if committed:
        assert not any(
            json.loads(line)["event_type"] == "proof_admission_anchored"
            for line in paths.events_path.read_text().splitlines()
        )
    assert (root / "live" / "leases").exists()
