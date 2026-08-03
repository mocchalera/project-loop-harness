from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import quote

from .contracts.proof_anchor import (
    authorization_sha256,
    authorization_subject_sha256,
    canonical_proof_anchor_bytes,
    validate_proof_admission_anchor_basis,
    validate_proof_admission_authorization,
)
from .contracts.proof_anchor_drift import (
    DRIFT_EFFECTS,
    DRIFT_ERROR_PHASES,
    DRIFT_HARD_ERROR_CODES,
    MAX_ANCHOR_ROWS,
    MAX_CHECKS,
    MAX_PARTICIPANTS,
    canonical_proof_anchor_drift_bytes,
    finalize_proof_anchor_drift_eligibility,
    subject_sha256,
    validate_proof_anchor_drift_eligibility,
)
from .db import SQLITE_BUSY_TIMEOUT_MS
from .errors import EXIT_USAGE, PclError
from .locks import ExistingSharedProjectLock, ExistingSharedProjectLockError
from .outbox import canonical_event_bytes, canonical_event_record
from .paths import ProjectPaths
from .proof_admission import (
    ProofCoverageError,
    ProofCoverageParticipant,
    TrustedCoveragePolicy,
)
from .proof_anchor import (
    ProofAnchorAuthorityCapacityError,
    ProofAnchorDriftAuthorityResolution,
    ProofAnchorError,
    _observe_proof_admission_anchor_basis,
    resolve_proof_anchor_drift_authority,
)
from .proof_execution import AuthorityInputSnapshot, capture_current_proof_in_snapshot
from .redaction import redact_value


PROOF_ANCHOR_DRIFT_DATABASE_SCHEMA_VERSION = 8


class ProofAnchorDriftError(PclError):
    pass


def evaluate_proof_anchor_drift_eligibility(
    paths: ProjectPaths,
    *,
    anchor_event_id: str,
    expected_target_id: str,
    expected_candidate: Mapping[str, str],
    expected_basis_sha256: str,
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    authority_provider: Callable[[], AuthorityInputSnapshot],
) -> Mapping[str, Any]:
    """Observe whether one durable C5 anchor still equals the live C1-C4 basis.

    This internal predicate grants no right and has no durable or authoritative
    effect. Callers must never use its receipt as a direct input capability.
    """
    if os.name != "posix":
        raise _error("drift_platform_unsupported", "preflight", EXIT_USAGE)
    _require_inputs(
        paths,
        anchor_event_id,
        expected_target_id,
        expected_candidate,
        expected_basis_sha256,
        policy,
        participants,
        authority_provider,
    )
    lock = ExistingSharedProjectLock(paths.loop_dir / "project.lock")
    conn: sqlite3.Connection | None = None
    try:
        try:
            lock.acquire()
        except ExistingSharedProjectLockError as exc:
            code = {
                "lock_unavailable": "drift_lock_unavailable",
                "lock_identity_invalid": "drift_lock_identity_invalid",
            }.get(exc.code, "drift_lock_identity_invalid")
            raise _error(code, "lock") from None
        try:
            conn, snapshot, project_instance_id = _open_pinned_read_snapshot(paths.db_path)
        except ProofAnchorDriftError:
            raise
        except sqlite3.Error as exc:
            raise _error(_classify_sqlite_error(exc), "snapshot") from None
        try:
            resolution = resolve_proof_anchor_drift_authority(
                paths,
                conn,
                anchor_event_id=anchor_event_id,
                anchor_row_limit=MAX_ANCHOR_ROWS + 1,
            )
        except ProofAnchorAuthorityCapacityError:
            raise _error("drift_capacity_exceeded", "authority") from None
        except sqlite3.Error as exc:
            raise _error(_classify_sqlite_error(exc), "authority") from None

        receipt = _evaluate_resolution(
            paths=paths,
            conn=conn,
            snapshot=snapshot,
            project_instance_id=project_instance_id,
            resolution=resolution,
            anchor_event_id=anchor_event_id,
            expected_target_id=expected_target_id,
            expected_candidate=dict(expected_candidate),
            expected_basis_sha256=expected_basis_sha256,
            policy=policy,
            participants=participants,
            authority_provider=authority_provider,
        )
        lock.recheck()
        validation = validate_proof_anchor_drift_eligibility(receipt)
        if not validation.ok:
            raise _error("drift_internal_error", "receipt")
        return receipt
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except ProofAnchorDriftError:
        raise
    except ExistingSharedProjectLockError:
        raise _error("drift_lock_identity_invalid", "lock") from None
    except sqlite3.Error as exc:
        raise _error(_classify_sqlite_error(exc), "snapshot") from None
    except Exception:
        raise _error("drift_internal_error", "receipt") from None
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            try:
                conn.close()
            except sqlite3.Error:
                pass
        lock.release()


def _open_pinned_read_snapshot(
    db_path: Path,
) -> tuple[sqlite3.Connection, dict[str, Any], str]:
    absolute = db_path if db_path.is_absolute() else Path.cwd() / db_path
    uri = f"file:{quote(str(absolute), safe='/')}?mode=ro"
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute("BEGIN")
        pinned = conn.execute(
            """
            SELECT
              (SELECT value FROM metadata WHERE key='schema_version') AS schema_version,
              (SELECT COALESCE(MAX(sequence), 0) FROM events) AS hwm
            """
        ).fetchone()
        if pinned is None or str(pinned["schema_version"]) != str(
            PROOF_ANCHOR_DRIFT_DATABASE_SCHEMA_VERSION
        ):
            raise _error("drift_database_schema_unsupported", "snapshot")
        project_row = conn.execute(
            """
            SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
            FROM events WHERE event_type = 'project_initialized'
            ORDER BY sequence LIMIT 1
            """
        ).fetchone()
        if project_row is None:
            raise _error("drift_database_schema_unsupported", "snapshot")
        project_instance_id = hashlib.sha256(
            canonical_event_bytes(canonical_event_record(project_row))
        ).hexdigest()
        journal = conn.execute("PRAGMA journal_mode").fetchone()
        if journal is None or str(journal[0]).lower() != "delete":
            raise _error("drift_database_journal_mode_unsupported", "snapshot")
        hwm = int(pinned["hwm"])
        hwm_row = (
            None
            if hwm == 0
            else conn.execute("SELECT id FROM events WHERE sequence = ?", (hwm,)).fetchone()
        )
        hwm_event_id = None if hwm_row is None else str(hwm_row["id"])
        return (
            conn,
            {
                "schema_version": PROOF_ANCHOR_DRIFT_DATABASE_SCHEMA_VERSION,
                "evaluated_through_event_sequence": hwm,
                "evaluated_through_event_id": hwm_event_id,
            },
            project_instance_id,
        )
    except BaseException:
        if conn is not None:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            try:
                conn.close()
            except sqlite3.Error:
                pass
        raise


def _evaluate_resolution(
    *,
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    snapshot: Mapping[str, Any],
    project_instance_id: str,
    resolution: ProofAnchorDriftAuthorityResolution,
    anchor_event_id: str,
    expected_target_id: str,
    expected_candidate: Mapping[str, Any],
    expected_basis_sha256: str,
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    authority_provider: Callable[[], AuthorityInputSnapshot],
) -> dict[str, Any]:
    base = {
        "paths": paths,
        "snapshot": snapshot,
        "project_instance_id": project_instance_id,
        "resolution": resolution,
        "anchor_event_id": anchor_event_id,
        "expected_target_id": expected_target_id,
        "expected_candidate": expected_candidate,
        "expected_basis_sha256": expected_basis_sha256,
    }
    if not resolution.assertion_found:
        return _receipt(**base, status="unavailable", reasons=["anchor_not_found"])
    if resolution.tombstone_status in {"invalid", "multiple"}:
        return _receipt(**base, status="invalid", reasons=["anchor_authority_corrupt"])
    if resolution.tombstone_status == "valid":
        return _receipt(
            **base,
            status="unavailable",
            reasons=["anchor_exhaustion_tombstoned"],
            selected=resolution.tombstone_witness,
            chain_head=None,
        )
    if resolution.authority_corrupt and resolution.target_id is None:
        return _receipt(**base, status="invalid", reasons=["anchor_authority_corrupt"])
    if resolution.exhaustion_witness is not None:
        return _receipt(
            **base,
            status="unavailable",
            reasons=["anchor_exhaustion_pending"],
            selected=resolution.exhaustion_witness,
            chain_head=True,
        )
    if resolution.authority_corrupt:
        return _receipt(**base, status="invalid", reasons=["anchor_authority_corrupt"])
    if len(resolution.valid_chains) > 1:
        return _receipt(
            **base,
            status="invalid",
            reasons=["anchor_parallel_chain_conflict"],
        )
    if not resolution.valid_chains:
        return _receipt(**base, status="invalid", reasons=["anchor_authority_corrupt"])
    head = resolution.valid_chains[0][-1]
    if head.generation < 3 and head.health_status == "postcommit_unhealthy":
        return _receipt(
            **base,
            status="withheld",
            reasons=["anchor_recovery_required"],
            selected=head,
            chain_head=True,
        )
    if head.event_id != anchor_event_id:
        return _receipt(
            **base,
            status="unavailable",
            reasons=["anchor_not_current_head"],
            selected=head,
            chain_head=True,
        )
    assertion_reasons: list[str] = []
    if resolution.target_id != expected_target_id:
        assertion_reasons.append("anchor_target_mismatch")
    if resolution.basis_sha256 != expected_basis_sha256:
        assertion_reasons.append("anchor_basis_mismatch")
    manifest_candidate = None if head.manifest is None else head.manifest.get("candidate")
    if manifest_candidate != expected_candidate:
        assertion_reasons.append("anchor_candidate_mismatch")
    if assertion_reasons:
        return _receipt(
            **base,
            status="withheld",
            reasons=assertion_reasons,
            selected=head,
            chain_head=True,
        )

    stored, stored_reasons = _stored_observation(head, policy)
    if stored_reasons:
        status = "invalid" if "anchor_authorization_document_invalid" in stored_reasons else "withheld"
        if "anchor_authority_corrupt" in stored_reasons:
            status = "invalid"
        return _receipt(
            **base,
            status=status,
            reasons=stored_reasons,
            selected=head,
            chain_head=True,
            stored=stored,
            authorization_status=_stored_authorization_status(head),
            handoff=_stored_handoff(head),
        )

    current_proof_failure_code: str | None = None

    def current_proof_provider():
        nonlocal current_proof_failure_code
        try:
            return capture_current_proof_in_snapshot(
                paths,
                conn,
                {"type": "task", "id": resolution.target_id},
                hwm=int(snapshot["evaluated_through_event_sequence"]),
            )
        except Exception as exc:
            current_proof_failure_code = _safe_exception_code(exc)
            raise

    try:
        live_basis = _observe_proof_admission_anchor_basis(
            policy=policy,
            participants=participants,
            authority_provider=authority_provider,
            current_proof_provider=current_proof_provider,
        )
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except (ProofCoverageError, ProofAnchorError) as exc:
        mapped = _map_live_domain_error(exc)
        if mapped is not None:
            raise _error(mapped, "live") from None
        stored_basis = head.members["basis"]
        live = _live_observation(stored_basis)
        live["reconstruction_status"] = "mismatched"
        return _receipt(
            **base,
            status="withheld",
            reasons=["live_execution_binding_changed"],
            selected=head,
            chain_head=True,
            stored=stored,
            live=live,
            authorization_status=_stored_authorization_status(head),
            handoff=_stored_handoff(head),
        )
    except Exception:
        raise _error("drift_internal_error", "live") from None

    live_document = json.loads(canonical_proof_anchor_bytes(live_basis))
    if current_proof_failure_code in {
        "proof_current_snapshot_required",
        "proof_current_target_invalid",
    }:
        raise _error("drift_internal_error", "live")
    soft = _soft_live_reconstruction(live_document)
    if soft is not None:
        reconstruction_status, reason, live = soft
        live["reconstruction_status"] = reconstruction_status
        return _receipt(
            **base,
            status="withheld",
            reasons=[reason],
            selected=head,
            chain_head=True,
            stored=stored,
            live=live,
            authorization_status=_stored_authorization_status(head),
            handoff=_stored_handoff(head),
        )
    if not validate_proof_admission_anchor_basis(live_document).ok:
        raise _error("drift_live_domain_error", "live")
    redacted, changed = redact_value(live_document)
    del redacted
    if changed:
        raise _error("drift_live_domain_error", "live")

    stored_basis = head.members["basis"]
    live = _live_observation(live_document)
    reasons = _live_reasons(stored_basis, live_document)
    exact = canonical_proof_anchor_bytes(stored_basis) == canonical_proof_anchor_bytes(live_document)
    if exact and not reasons:
        live["reconstruction_status"] = "matched"
        status = "eligible"
    else:
        live["reconstruction_status"] = "mismatched"
        if not reasons:
            reasons.append("live_basis_mismatch")
        status = "withheld"
    return _receipt(
        **base,
        status=status,
        reasons=reasons,
        selected=head,
        chain_head=True,
        stored=stored,
        live=live,
        authorization_status=_stored_authorization_status(head),
        handoff=_stored_handoff(head),
    )


def _stored_observation(head: Any, policy: TrustedCoveragePolicy) -> tuple[dict[str, Any], list[str]]:
    observation = _empty_stored()
    basis = head.members.get("basis")
    manifest = head.manifest
    if (
        not isinstance(basis, Mapping)
        or manifest is None
        or not validate_proof_admission_anchor_basis(basis).ok
        or basis.get("basis_sha256") != head.payload.get("basis_sha256")
        or manifest.get("bindings", {}).get("basis_sha256") != basis.get("basis_sha256")
    ):
        observation["basis_document_status"] = "invalid"
        return observation, ["anchor_authority_corrupt"]
    observation["basis_document_status"] = "valid"
    expected_roles = ["independent_review"]
    if manifest["bindings"]["human_gate_subject_sha256"] is not None:
        expected_roles.append("human_gate")
    documents: list[Mapping[str, Any]] = []
    for role in expected_roles:
        document = head.members.get(role)
        if not isinstance(document, Mapping) or not _authorization_matches(
            document,
            basis,
            manifest,
            role,
        ):
            observation["authorization_documents_status"] = "invalid"
            return observation, ["anchor_authorization_document_invalid"]
        documents.append(document)
    observation["authorization_documents_status"] = "valid"
    producer_id = policy.document.get("producer", {}).get("producer_id")
    actors = [item["authority"]["actor_id"] for item in documents]
    if producer_id in actors:
        observation["recorded_actor_independence"] = "mismatched"
        observation["anchor_authorization_granted"] = True
        return observation, ["anchor_actor_independence_changed"]
    observation["recorded_actor_independence"] = "matched"
    observation["anchor_authorization_granted"] = True
    if not _computed_verdict_passed(basis):
        return observation, ["computed_verdict_not_passed"]
    return observation, []


def _authorization_matches(
    document: Mapping[str, Any],
    basis: Mapping[str, Any],
    manifest: Mapping[str, Any],
    role: str,
) -> bool:
    try:
        kind = document["authorization_kind"]
        prefix = "independent_review" if role == "independent_review" else "human_gate"
        return bool(
            kind == role
            and validate_proof_admission_authorization(document).ok
            and document["authorization_subject_sha256"] == authorization_subject_sha256(document)
            and document["authorization_sha256"] == authorization_sha256(document)
            and document["authorization_sha256"]
            == manifest["bindings"][f"{prefix}_authorization_sha256"]
            and document["authorization_subject_sha256"]
            == manifest["bindings"][f"{prefix}_subject_sha256"]
            and document["target"] == basis["target"]
            and document["candidate"] == basis["candidate"]
            and document["bindings"]["basis_sha256"] == basis["basis_sha256"]
            and document["bindings"]["policy_sha256"] == basis["bindings"]["policy_sha256"]
            and document["bindings"]["coverage_group_sha256"]
            == basis["bindings"]["coverage_group_sha256"]
            and document["bindings"]["admission_sha256"]
            == basis["bindings"]["admission_sha256"]
            and document["bindings"]["producer_sha256"]
            == basis["policy"]["producer"]["producer_sha256"]
            and document["authority"]["candidate_controlled"] is False
        )
    except (KeyError, TypeError, ValueError):
        return False


def _computed_verdict_passed(basis: Mapping[str, Any]) -> bool:
    try:
        admission = basis["admission"]
        return bool(
            admission["admission_state"] == "reviewable"
            and admission["review_readiness"] == "ready"
            and all(
                item["aggregate_verdict"] == "passed"
                and item["aggregate_anchoring_eligible"] is True
                for item in admission["participants"]
            )
        )
    except (KeyError, TypeError):
        return False


def _soft_live_reconstruction(
    basis: Mapping[str, Any],
) -> tuple[str, str, dict[str, Any]] | None:
    admission = basis.get("admission")
    if not isinstance(admission, Mapping):
        return None
    raw_reasons = admission.get("state_reason_codes")
    if not isinstance(raw_reasons, list) or any(
        not isinstance(reason, str) for reason in raw_reasons
    ):
        return None
    reasons = set(raw_reasons)
    live = _live_observation(basis)
    unavailable = {
        "authority_current_indeterminate",
        "current_proof_indeterminate",
        "participant_current_proof_indeterminate",
    }
    if reasons & unavailable:
        if "authority_current_indeterminate" in reasons:
            live["authority_surface_resolution_sha256"] = None
        return "unavailable", "live_chain_unavailable", live
    if "candidate_blob_resolution_indeterminate" in reasons:
        return "indeterminate", "live_reconstruction_indeterminate", live
    return None


def _live_observation(basis: Mapping[str, Any]) -> dict[str, Any]:
    admission = basis["admission"]
    policy = basis["policy"]
    return {
        "reconstruction_status": "mismatched",
        "basis_sha256": basis["basis_sha256"],
        "policy_sha256": basis["bindings"]["policy_sha256"],
        "coverage_group_sha256": basis["bindings"]["coverage_group_sha256"],
        "admission_sha256": basis["bindings"]["admission_sha256"],
        "current_proof_sha256": admission["current_proof"]["proof_sha256"],
        "authority_surface_resolution_sha256": policy["authority_bindings"][
            "authority_surface_resolution_sha256"
        ],
    }


def _live_reasons(stored: Mapping[str, Any], live: Mapping[str, Any]) -> list[str]:
    reasons: set[str] = set()
    if live["candidate"] != stored["candidate"]:
        reasons.add("live_candidate_changed")
    if live["bindings"]["policy_sha256"] != stored["bindings"]["policy_sha256"]:
        reasons.add("live_policy_changed")
    stored_policy = stored["policy"]
    live_policy = live["policy"]
    if (
        live_policy["authority_bindings"]["authority_surface_resolution_sha256"]
        != stored_policy["authority_bindings"]["authority_surface_resolution_sha256"]
    ):
        reasons.add("live_authority_changed")
    if (
        live_policy["authority_bindings"]["canary_union_sha256"]
        != stored_policy["authority_bindings"]["canary_union_sha256"]
    ):
        reasons.add("live_canary_changed")
    if (
        live["admission"]["current_proof"] != stored["admission"]["current_proof"]
    ):
        reasons.add("live_current_proof_changed")
    if (
        live["bindings"]["coverage_group_sha256"]
        != stored["bindings"]["coverage_group_sha256"]
        or live["admission"]["participants"] != stored["admission"]["participants"]
        or live["admission"]["role_observations"]
        != stored["admission"]["role_observations"]
    ):
        reasons.add("live_execution_binding_changed")
    if not _computed_verdict_passed(live):
        reasons.add("computed_verdict_not_passed")
    return sorted(reasons)


def _receipt(
    *,
    paths: ProjectPaths,
    snapshot: Mapping[str, Any],
    project_instance_id: str,
    resolution: ProofAnchorDriftAuthorityResolution,
    anchor_event_id: str,
    expected_target_id: str,
    expected_candidate: Mapping[str, Any],
    expected_basis_sha256: str,
    status: str,
    reasons: Sequence[str],
    selected: Any = None,
    chain_head: bool | None = None,
    stored: Mapping[str, Any] | None = None,
    live: Mapping[str, Any] | None = None,
    authorization_status: Mapping[str, Any] | None = None,
    handoff: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    del paths
    subject = {
        "contract_version": "proof-anchor-drift-subject/v1",
        "project_instance_id": project_instance_id,
        "target": {"type": "task", "id": expected_target_id},
        "candidate": deepcopy(dict(expected_candidate)),
        "expected_basis_sha256": expected_basis_sha256,
        "anchor_event_id": anchor_event_id,
        "requested_use": "drift_eligibility_predicate",
        "subject_sha256": "sha256:" + "0" * 64,
    }
    subject["subject_sha256"] = subject_sha256(subject)
    tombstone = resolution.tombstone_status
    if tombstone == "absent":
        valid_chain_count: int | None = len(resolution.valid_chains)
        malformed: bool | None = bool(resolution.malformed_group_present)
        witness_status = "present" if resolution.exhaustion_witness is not None else "absent"
    else:
        valid_chain_count = None
        malformed = None
        witness_status = "present" if tombstone == "valid" else "not_evaluated"
    anchor = None if selected is None else _anchor_view(selected, chain_head=chain_head)
    reason_codes = sorted(set(reasons))
    receipt = {
        "contract_version": "proof-anchor-drift-eligibility/v1",
        "subject": subject,
        "anchor": anchor,
        "observation": {
            "snapshot": deepcopy(dict(snapshot)),
            "chain": {
                "valid_chain_count": valid_chain_count,
                "malformed_group_present": malformed,
                "tombstone_status": tombstone,
                "tombstone_event_id": resolution.tombstone_event_id,
                "exhaustion_witness_status": witness_status,
                "selected_head_event_id": None if anchor is None else anchor["event_id"],
                "selected_head_generation": (
                    None if anchor is None else anchor["anchor_generation"]
                ),
            },
            "stored": deepcopy(dict(stored or _empty_stored())),
            "live": deepcopy(dict(live or _empty_live("not_run"))),
        },
        "eligibility": {
            "status": status,
            "predicate_kind": "drift_eligibility_only",
            "matched": status == "eligible",
            "direct_input_right": False,
            "check_skip_authorized": False,
            "result_substitution_authorized": False,
        },
        "reason_codes": reason_codes,
        "authorization_status": deepcopy(
            None if authorization_status is None else dict(authorization_status)
        ),
        "handoff": deepcopy(None if handoff is None else dict(handoff)),
        "effects": dict(DRIFT_EFFECTS),
        "eligibility_sha256": "sha256:" + "0" * 64,
    }
    result = finalize_proof_anchor_drift_eligibility(receipt)
    if len(canonical_proof_anchor_drift_bytes(result)) > 131_072:
        raise _error("drift_capacity_exceeded", "receipt")
    return result


def _anchor_view(value: Any, *, chain_head: bool | None) -> dict[str, Any]:
    return {
        "event_id": value.event_id,
        "event_sequence": value.sequence,
        "request_id": value.payload["request_id"],
        "base_request_sha256": value.payload["base_request_sha256"],
        "anchor_generation": value.generation,
        "basis_sha256": value.payload["basis_sha256"],
        "anchor_sha256": value.payload["anchor_sha256"],
        "manifest_file_sha256": value.payload["manifest_file_sha256"],
        "evidence_id": value.payload["evidence_id"],
        "health_status": value.health_status,
        "chain_head": chain_head,
    }


def _empty_stored() -> dict[str, Any]:
    return {
        "basis_document_status": "unavailable",
        "authorization_documents_status": "unavailable",
        "recorded_actor_independence": "not_observed",
        "anchor_authorization_granted": None,
        "issuer_capability_validation": "write_time_only_not_reconstituted",
    }


def _empty_live(status: str) -> dict[str, Any]:
    return {
        "reconstruction_status": status,
        "basis_sha256": None,
        "policy_sha256": None,
        "coverage_group_sha256": None,
        "admission_sha256": None,
        "current_proof_sha256": None,
        "authority_surface_resolution_sha256": None,
    }


def _stored_authorization_status(head: Any) -> Mapping[str, Any] | None:
    if head.manifest is None:
        return None
    basis = head.members.get("basis")
    return None if not isinstance(basis, Mapping) else basis["admission"]["authorization_status"]


def _stored_handoff(head: Any) -> Mapping[str, Any] | None:
    return None if head.manifest is None else head.manifest["handoff"]


def _require_inputs(
    paths: Any,
    anchor_event_id: Any,
    expected_target_id: Any,
    expected_candidate: Any,
    expected_basis_sha256: Any,
    policy: Any,
    participants: Any,
    authority_provider: Any,
) -> None:
    if (
        type(paths) is not ProjectPaths
        or type(policy) is not TrustedCoveragePolicy
        or not isinstance(participants, Sequence)
        or isinstance(participants, (str, bytes, bytearray))
        or not 1 <= len(participants) <= MAX_PARTICIPANTS
        or any(type(item) is not ProofCoverageParticipant for item in participants)
        or sum(len(item.bundle.check_results) for item in participants) > MAX_CHECKS
        or not callable(authority_provider)
    ):
        raise _error("drift_input_type_invalid", "preflight", EXIT_USAGE)
    assertion = {
        "anchor_event_id": anchor_event_id,
        "expected_target_id": expected_target_id,
        "expected_candidate": expected_candidate,
        "expected_basis_sha256": expected_basis_sha256,
    }
    try:
        candidate = dict(expected_candidate)
        object_format = candidate.get("object_format")
        oid_length = {"sha1": 40, "sha256": 64}.get(object_format)
        valid = bool(
            set(candidate) == {"object_format", "commit_oid", "tree_oid"}
            and oid_length is not None
            and all(
                isinstance(candidate.get(field), str)
                and len(candidate[field]) == oid_length
                and all(character in "0123456789abcdef" for character in candidate[field])
                for field in ("commit_oid", "tree_oid")
            )
            and isinstance(anchor_event_id, str)
            and len(anchor_event_id) == 67
            and anchor_event_id.startswith("EV-")
            and all(character in "0123456789ABCDEF" for character in anchor_event_id[3:])
            and _public_identifier(expected_target_id)
            and _sha256(expected_basis_sha256)
        )
    except Exception:
        valid = False
    if not valid:
        raise _error("drift_contract_invalid", "preflight", EXIT_USAGE)
    redacted, changed = redact_value(assertion)
    del redacted
    if changed:
        raise _error("drift_secret_shaped_identifier", "preflight", EXIT_USAGE)


def _public_identifier(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and 1 <= len(value.encode("utf-8")) <= 4096
        and value[0].isalnum()
        and all(character.isascii() and (character.isalnum() or character in "_.:-") for character in value)
    )


def _sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _map_live_domain_error(exc: Exception) -> str | None:
    try:
        code = getattr(exc, "code", None)
    except Exception:
        return "drift_live_domain_error"
    hard = {
        "proof_anchor_contract_invalid": "drift_contract_invalid",
        "proof_anchor_admission_withheld": "drift_live_domain_error",
        "coverage_input_type_invalid": "drift_input_type_invalid",
        "coverage_capacity_exceeded": "drift_capacity_exceeded",
        "coverage_digest_mismatch": "drift_contract_invalid",
        "coverage_contract_invalid": "drift_contract_invalid",
        "coverage_policy_authority_invalid": "drift_contract_invalid",
        "coverage_public_identifier_secret_shaped": "drift_secret_shaped_identifier",
    }
    if code == "coverage_live_identity_mismatch":
        return None
    return hard.get(code, "drift_live_domain_error")


def _safe_exception_code(exc: Exception) -> str | None:
    try:
        code = getattr(exc, "code", None)
    except Exception:
        return None
    return code if isinstance(code, str) else None


def _classify_sqlite_error(exc: sqlite3.Error) -> str:
    try:
        candidate = getattr(exc, "sqlite_errorcode", None)
    except Exception:
        candidate = None
    code = candidate if type(candidate) is int and candidate >= 0 else None
    if isinstance(exc, sqlite3.OperationalError):
        if code in {776, 264}:
            return "drift_database_recovery_required"
        if code == 520:
            return "drift_snapshot_unavailable"
        if code is not None and code & 0xFF in {11, 26}:
            return "drift_database_recovery_required"
        if code is not None and code & 0xFF in {5, 6}:
            return "drift_snapshot_unavailable"
        return "drift_database_recovery_required"
    if code is not None and code & 0xFF in {11, 26}:
        return "drift_database_recovery_required"
    return "drift_snapshot_unavailable"


def _error(code: str, phase: str, exit_code: int = 1) -> ProofAnchorDriftError:
    safe_code = code if code in DRIFT_HARD_ERROR_CODES else "drift_internal_error"
    safe_phase = phase if phase in DRIFT_ERROR_PHASES else "receipt"
    return ProofAnchorDriftError(
        "Proof-anchor drift eligibility evaluation failed.",
        code=safe_code,
        exit_code=exit_code,
        details={"phase": safe_phase},
    )


__all__ = [
    "PROOF_ANCHOR_DRIFT_DATABASE_SCHEMA_VERSION",
    "ProofAnchorDriftError",
    "evaluate_proof_anchor_drift_eligibility",
]
