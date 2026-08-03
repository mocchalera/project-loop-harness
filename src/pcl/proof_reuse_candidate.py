from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import sqlite3
from typing import Any

from .contracts.authority_surface import validate_authority_surface_resolution
from .contracts.proof_anchor import canonical_proof_anchor_bytes
from .contracts.proof_reuse_candidate import (
    MAX_ANCHOR_ROWS,
    MAX_PARTICIPANTS,
    MAX_ROLES,
    PROOF_REUSE_CANDIDATE_CONTRACT_VERSION,
    PROOF_REUSE_CANDIDATE_RESULT_CONTRACT_VERSION,
    REUSE_CANDIDATE_AUTHORIZATION,
    REUSE_CANDIDATE_EFFECTS_SUCCESS,
    REUSE_CANDIDATE_EFFECTS_ZERO,
    REUSE_CANDIDATE_HANDOFF,
    REUSE_CANDIDATE_STATUS_RANK,
    canonical_proof_reuse_candidate_bytes,
    domain_sha256,
    finalize_proof_reuse_candidate,
    finalize_proof_reuse_candidate_result,
    status_for_reasons,
    validate_proof_reuse_candidate,
    validate_proof_reuse_candidate_result,
)
from .db import MutationConnection, connect, connect_mutation
from .errors import EXIT_DATA_ERROR, EXIT_USAGE, PclError, ProjectionPendingError
from .events import append_event
from .ids import next_prefixed_id
from .outbox import project_pending_events
from .paths import ProjectPaths
from .proof_admission import ProofCoverageParticipant, TrustedCoveragePolicy
from .proof_anchor import (
    ProofAnchorAuthorityCapacityError,
    _build_locked_basis,
    _event_at_sequence,
    _event_hwm,
    _require_live_canaries,
    resolve_proof_anchor_drift_authority,
)
from .proof_execution import AuthorityInputSnapshot
from .proof_reuse_candidate_store import (
    PublishedProofReuseCandidate,
    assess_proof_reuse_candidate_artifact,
    platform_supported,
    publish_proof_reuse_candidate,
    remove_published_proof_reuse_candidate,
)
from .redaction import redact_value
from .timeutil import utc_now_iso
from .test_faults import crash_if_requested


PROOF_REUSE_CANDIDATE_EVIDENCE_TYPE = "proof_reuse_candidate"
PROOF_REUSE_CANDIDATE_LINK_ROLE = "proof_reuse_candidate"
PROOF_REUSE_CANDIDATE_EVENT_TYPE = "proof_reuse_candidate_recorded"
PROOF_REUSE_CANDIDATE_EVENT_CONTRACT_VERSION = "proof-reuse-candidate-event/v1"
PROOF_REUSE_CANDIDATE_EVIDENCE_SUMMARY_VERSION = (
    "proof-reuse-candidate-evidence-summary/v1"
)
PROOF_REUSE_CANDIDATE_DATABASE_SCHEMA_VERSION = "8"


class ProofReuseCandidateError(PclError):
    pass


def record_proof_reuse_candidate(
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
    """Record one local, durable, non-consumable C7 proof-reuse candidate."""
    if not platform_supported():
        raise _error("reuse_candidate_platform_unsupported", "preflight", EXIT_USAGE)
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
    try:
        return _record(
            paths,
            anchor_event_id=anchor_event_id,
            expected_target_id=expected_target_id,
            expected_candidate=expected_candidate,
            expected_basis_sha256=expected_basis_sha256,
            policy=policy,
            participants=participants,
            authority_provider=authority_provider,
        )
    except ProofReuseCandidateError:
        raise
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except ProofAnchorAuthorityCapacityError:
        raise _error("reuse_candidate_capacity_exceeded", "authority", EXIT_DATA_ERROR) from None
    except sqlite3.DatabaseError:
        raise _error(
            "reuse_candidate_database_schema_unsupported",
            "transaction",
            EXIT_DATA_ERROR,
        ) from None
    except PclError:
        raise _error("reuse_candidate_live_domain_error", "live", EXIT_DATA_ERROR) from None
    except (OSError, UnicodeError):
        raise _error("reuse_candidate_store_invalid", "publication", EXIT_DATA_ERROR) from None
    except (KeyError, TypeError, ValueError, AssertionError):
        raise _error("reuse_candidate_internal_error", "live", EXIT_DATA_ERROR) from None


def _record(
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
    try:
        conn = connect_mutation(paths, exclusive=True)
    except PclError:
        raise _error("reuse_candidate_lock_unavailable", "lock") from None
    except OSError:
        raise _error("reuse_candidate_lock_identity_invalid", "lock") from None
    publication: PublishedProofReuseCandidate | None = None
    mutation_committed = False
    try:
        _require_schema(conn)
        pending_before = _pending_count(conn)
        observed = _observe_recordability(
            paths,
            conn,
            anchor_event_id=anchor_event_id,
            expected_target_id=expected_target_id,
            expected_candidate=expected_candidate,
            expected_basis_sha256=expected_basis_sha256,
            policy=policy,
            participants=participants,
            authority_provider=authority_provider,
        )
        if observed["reasons"]:
            conn.rollback()
            return _nonrecordable_result(
                reasons=observed["reasons"],
                source_health=observed["source_health"],
            )

        identity_input = _candidate_identity_input(observed)
        provisional = {
            **identity_input,
            "observation": observed["observation"],
            "authorization": dict(REUSE_CANDIDATE_AUTHORIZATION),
            "handoff": dict(REUSE_CANDIDATE_HANDOFF),
            "effects": dict(REUSE_CANDIDATE_EFFECTS_SUCCESS),
            "candidate_sha256": "sha256:" + "0" * 64,
        }
        candidate_id = finalize_proof_reuse_candidate(provisional)["candidate_id"]
        committed = _read_committed_candidate(paths, conn, candidate_id=candidate_id)
        if committed is not None:
            conn.rollback()
            if not committed["healthy"]:
                raise _error(
                    "reuse_candidate_idempotency_conflict",
                    "replay",
                    EXIT_DATA_ERROR,
                )
            _recover_projection_only(paths, committed["outbox_id"])
            delivery = _read_outbox_delivery(paths, committed["outbox_id"])
            return _success_result(
                candidate=committed["candidate"],
                changed=False,
                idempotent=True,
                mutation_committed=False,
                safe_to_retry_original=True,
                projection_status="replayed",
                evidence_id=committed["evidence_id"],
                event_id=committed["event_id"],
                event_sequence=committed["event_sequence"],
                outbox_id=committed["outbox_id"],
                outbox_delivery=delivery,
                artifact_health="healthy",
                effects=REUSE_CANDIDATE_EFFECTS_ZERO,
            )
        if _candidate_event_exists(conn, candidate_id):
            raise _error(
                "reuse_candidate_idempotency_conflict",
                "replay",
                EXIT_DATA_ERROR,
            )
        if pending_before:
            raise _error(
                "reuse_candidate_projection_pending",
                "projection",
                EXIT_DATA_ERROR,
            )

        candidate = finalize_proof_reuse_candidate(provisional)
        if candidate["candidate_id"] != candidate_id:
            raise _error("reuse_candidate_internal_error", "identity", EXIT_DATA_ERROR)
        validation = validate_proof_reuse_candidate(candidate)
        if not validation.ok:
            raise _error("reuse_candidate_contract_invalid", "identity", EXIT_USAGE)
        candidate_bytes = canonical_proof_reuse_candidate_bytes(candidate)
        artifact_file_sha256 = "sha256:" + hashlib.sha256(candidate_bytes).hexdigest()
        crash_if_requested("proof_reuse_candidate_before_staging")
        try:
            publication = publish_proof_reuse_candidate(
                paths,
                candidate_id=candidate_id,
                content=candidate_bytes,
            )
        except FileExistsError:
            raise _error(
                "reuse_candidate_idempotency_conflict",
                "publication",
                EXIT_DATA_ERROR,
            ) from None
        except (OSError, TypeError, ValueError):
            raise _error(
                "reuse_candidate_store_invalid",
                "publication",
                EXIT_DATA_ERROR,
            ) from None

        evidence_id = next_prefixed_id(conn, "evidence", "E")
        event_id = _candidate_event_id(candidate_id)
        outbox_id = _candidate_outbox_id(candidate_id)
        now = utc_now_iso()
        summary = {
            "contract_version": PROOF_REUSE_CANDIDATE_EVIDENCE_SUMMARY_VERSION,
            "candidate_id": candidate_id,
            "candidate_sha256": candidate["candidate_sha256"],
            "artifact_file_sha256": artifact_file_sha256,
            "artifact_size_bytes": len(candidate_bytes),
            "source_anchor_event_id": anchor_event_id,
        }
        crash_if_requested("proof_reuse_candidate_after_publish_before_database")
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (
                evidence_id,
                PROOF_REUSE_CANDIDATE_EVIDENCE_TYPE,
                publication.relative_candidate_path,
                json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                now,
            ),
        )
        crash_if_requested("proof_reuse_candidate_after_evidence_insert")
        conn.execute(
            """
            INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
            VALUES (?, 'task', ?, ?, ?)
            """,
            (
                evidence_id,
                expected_target_id,
                PROOF_REUSE_CANDIDATE_LINK_ROLE,
                now,
            ),
        )
        crash_if_requested("proof_reuse_candidate_after_link_insert")
        payload = {
            "contract_version": PROOF_REUSE_CANDIDATE_EVENT_CONTRACT_VERSION,
            "candidate_id": candidate_id,
            "candidate_sha256": candidate["candidate_sha256"],
            "artifact_file_sha256": artifact_file_sha256,
            "artifact_size_bytes": len(candidate_bytes),
            "source_anchor_event_id": anchor_event_id,
            "evidence_id": evidence_id,
        }
        _require_event_payload(payload)
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=PROOF_REUSE_CANDIDATE_EVENT_TYPE,
            entity_type="task",
            entity_id=expected_target_id,
            payload=payload,
            event_id=event_id,
            outbox_id=outbox_id,
            created_at=now,
        )
        event_sequence = _event_sequence(conn, event_id)
        crash_if_requested("proof_reuse_candidate_after_event_before_commit")

        def precommit_guard() -> None:
            final = _observe_recordability(
                paths,
                conn,
                anchor_event_id=anchor_event_id,
                expected_target_id=expected_target_id,
                expected_candidate=expected_candidate,
                expected_basis_sha256=expected_basis_sha256,
                policy=policy,
                participants=participants,
                authority_provider=authority_provider,
            )
            if final["reasons"]:
                raise _error(
                    "reuse_candidate_live_domain_error",
                    "final_guard",
                    EXIT_DATA_ERROR,
                )
            final_identity = _candidate_identity_input(final)
            final_id = finalize_proof_reuse_candidate(
                {
                    **final_identity,
                    "observation": final["observation"],
                    "authorization": dict(REUSE_CANDIDATE_AUTHORIZATION),
                    "handoff": dict(REUSE_CANDIDATE_HANDOFF),
                    "effects": dict(REUSE_CANDIDATE_EFFECTS_SUCCESS),
                    "candidate_sha256": "sha256:" + "0" * 64,
                }
            )["candidate_id"]
            if final_id != candidate_id:
                raise _error(
                    "reuse_candidate_live_domain_error",
                    "final_guard",
                    EXIT_DATA_ERROR,
                )
            assessment = assess_proof_reuse_candidate_artifact(
                paths,
                candidate_id=candidate_id,
                expected_sha256=artifact_file_sha256,
                expected_size_bytes=len(candidate_bytes),
            )
            if not assessment.healthy:
                raise _error(
                    "reuse_candidate_store_invalid",
                    "final_guard",
                    EXIT_DATA_ERROR,
                )

        postcommit_assessment: dict[str, str] = {"status": "postcommit_unhealthy"}

        def postcommit_guard() -> None:
            crash_if_requested("proof_reuse_candidate_after_sqlite_commit_before_health")
            assessment = assess_proof_reuse_candidate_artifact(
                paths,
                candidate_id=candidate_id,
                expected_sha256=artifact_file_sha256,
                expected_size_bytes=len(candidate_bytes),
            )
            postcommit_assessment["status"] = assessment.status

        assert isinstance(conn, MutationConnection)
        conn._precommit_guard = precommit_guard
        conn._postcommit_guard = postcommit_guard
        crash_if_requested("proof_reuse_candidate_before_sqlite_commit")
        try:
            conn.commit()
        except ProjectionPendingError:
            if not conn._authoritative_commit_completed:
                raise
        mutation_committed = bool(conn._authoritative_commit_completed)
        delivery = _read_outbox_delivery(paths, outbox_id)
        return _success_result(
            candidate=candidate,
            changed=True,
            idempotent=False,
            mutation_committed=True,
            safe_to_retry_original=False,
            projection_status="committed",
            evidence_id=evidence_id,
            event_id=event_id,
            event_sequence=event_sequence,
            outbox_id=outbox_id,
            outbox_delivery=delivery,
            artifact_health=postcommit_assessment["status"],
            effects=REUSE_CANDIDATE_EFFECTS_SUCCESS,
        )
    except BaseException:
        mutation_committed = mutation_committed or bool(
            getattr(conn, "_authoritative_commit_completed", False)
        )
        if conn.in_transaction:
            conn.rollback()
        if publication is not None and not mutation_committed:
            remove_published_proof_reuse_candidate(publication)
        raise
    finally:
        conn.close()


def _observe_recordability(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    anchor_event_id: str,
    expected_target_id: str,
    expected_candidate: Mapping[str, str],
    expected_basis_sha256: str,
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    authority_provider: Callable[[], AuthorityInputSnapshot],
) -> dict[str, Any]:
    resolution = resolve_proof_anchor_drift_authority(
        paths,
        conn,
        anchor_event_id=anchor_event_id,
        anchor_row_limit=MAX_ANCHOR_ROWS + 1,
    )
    special = _authority_disposition(resolution, anchor_event_id)
    if special is not None:
        reason, health = special
        return {"reasons": [reason], "source_health": health}
    head = resolution.valid_chains[0][-1]
    reasons: set[str] = set()
    if (
        resolution.target_id != expected_target_id
        or resolution.basis_sha256 != expected_basis_sha256
    ):
        reasons.add("source_authorization_invalid")
    stored_basis = head.members.get("basis")
    if not isinstance(stored_basis, Mapping):
        return {
            "reasons": ["source_anchor_unhealthy"],
            "source_health": "unhealthy",
        }
    if stored_basis.get("candidate") != dict(expected_candidate):
        reasons.add("source_authorization_invalid")

    hwm = _event_hwm(conn)
    locked_basis = _build_locked_basis(
        paths,
        conn,
        hwm=hwm,
        policy=policy,
        participants=participants,
        authority_provider=authority_provider,
    )
    _require_live_canaries(policy, participants, locked_basis, authority_provider)
    stored_current = stored_basis.get("admission", {}).get("current_proof")
    live_current = locked_basis.get("admission", {}).get("current_proof")
    if stored_current != live_current:
        reasons.add("source_current_proof_changed")
    if canonical_proof_anchor_bytes(locked_basis) != canonical_proof_anchor_bytes(
        stored_basis
    ):
        reasons.add("source_live_basis_changed")

    roles, role_reasons = _normalize_roles(
        locked_basis,
        policy=policy,
        participants=participants,
        authority_provider=authority_provider,
    )
    reasons.update(role_reasons)
    admission = locked_basis["admission"]
    current = admission["current_proof"]
    if admission.get("admission_state") != "reviewable":
        reasons.add("source_verdict_not_passed")
    if (
        current.get("scope") != "feature"
        or current.get("status") != "healthy"
        or current.get("match_status") != "matched"
        or not _is_sha(current.get("proof_sha256"))
    ):
        reasons.add("source_current_proof_changed")
    if len(roles) != len(policy.document["required_roles"]):
        reasons.add("source_role_coverage_incomplete")
    observation_event_id = _event_at_sequence(conn, hwm)
    if hwm < 1 or observation_event_id is None:
        raise _error("reuse_candidate_live_domain_error", "live", EXIT_DATA_ERROR)
    return {
        "reasons": sorted(reasons),
        "source_health": "healthy",
        "head": head,
        "basis": locked_basis,
        "roles": roles,
        "observation": {
            "observed_through_event_sequence": hwm,
            "observed_through_event_id": observation_event_id,
            "observed_through_anchor_event_id": anchor_event_id,
        },
    }


def _authority_disposition(resolution: Any, anchor_event_id: str) -> tuple[str, str] | None:
    if resolution.tombstone_status in {"invalid", "multiple"}:
        return "source_anchor_authority_corrupt", "invalid"
    if resolution.tombstone_status == "valid":
        return "source_anchor_exhaustion_tombstoned", "unavailable"
    if resolution.exhaustion_witness is not None:
        return "source_anchor_exhaustion_pending", "unavailable"
    if not resolution.assertion_found:
        return "source_anchor_not_found", "unavailable"
    if resolution.authority_corrupt or resolution.malformed_group_present:
        return "source_anchor_authority_corrupt", "invalid"
    if len(resolution.valid_chains) > 1:
        return "source_anchor_parallel_chain", "invalid"
    if len(resolution.valid_chains) != 1 or not resolution.valid_chains[0]:
        return "source_anchor_authority_corrupt", "invalid"
    head = resolution.valid_chains[0][-1]
    if head.event_id != anchor_event_id:
        return "source_anchor_not_current", "unavailable"
    if head.health_status == "postcommit_unhealthy" and head.generation <= 2:
        return "source_anchor_recovery_required", "recovery_required"
    if head.health_status != "healthy":
        return "source_anchor_unhealthy", "unhealthy"
    return None


def _normalize_roles(
    basis: Mapping[str, Any],
    *,
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    authority_provider: Callable[[], AuthorityInputSnapshot],
) -> tuple[list[dict[str, Any]], set[str]]:
    reasons: set[str] = set()
    if len(participants) > MAX_PARTICIPANTS:
        raise _error("reuse_candidate_capacity_exceeded", "live", EXIT_USAGE)
    policy_document = _json_copy(policy.document)
    requirements = policy_document.get("required_roles")
    admission = basis.get("admission")
    if not isinstance(requirements, list) or not isinstance(admission, Mapping):
        raise _error("reuse_candidate_live_domain_error", "live", EXIT_DATA_ERROR)
    if not 1 <= len(requirements) <= MAX_ROLES:
        raise _error("reuse_candidate_capacity_exceeded", "live", EXIT_USAGE)
    try:
        authority = authority_provider()
        if type(authority) is not AuthorityInputSnapshot:
            raise TypeError
        authority_resolution = authority.resolve()
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except BaseException:
        raise _error("reuse_candidate_live_domain_error", "live", EXIT_DATA_ERROR) from None
    if not validate_authority_surface_resolution(authority_resolution).ok:
        raise _error("reuse_candidate_live_domain_error", "live", EXIT_DATA_ERROR)
    if (
        authority_resolution.get("base", {}).get("status") != "resolved"
        or authority_resolution.get("effective", {}).get("reuse_allowed") is not True
    ):
        reasons.add("source_reuse_forbidden")

    observations = admission.get("role_observations")
    public_participants = admission.get("participants")
    if not isinstance(observations, list) or not isinstance(public_participants, list):
        raise _error("reuse_candidate_live_domain_error", "live", EXIT_DATA_ERROR)
    observation_by_role: dict[str, list[Mapping[str, Any]]] = {}
    for observation in observations:
        if isinstance(observation, Mapping):
            observation_by_role.setdefault(str(observation.get("role")), []).append(
                observation
            )
    participant_public_by_sha = {
        str(item.get("participant_sha256")): item
        for item in public_participants
        if isinstance(item, Mapping)
    }
    normalized: list[dict[str, Any]] = []
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            reasons.add("source_role_coverage_incomplete")
            continue
        role_name = str(requirement.get("role"))
        matches = observation_by_role.get(role_name, [])
        if len(matches) != 1:
            reasons.add("source_role_coverage_incomplete")
            continue
        observation = matches[0]
        participant_sha = str(observation.get("selected_participant_sha256") or "")
        public = participant_public_by_sha.get(participant_sha)
        if public is None:
            reasons.add("source_role_coverage_incomplete")
            continue
        participant_matches = [
            participant
            for participant in participants
            if participant.bundle.packet.get("packet_sha256")
            == public.get("packet_sha256")
            and participant.bundle.aggregate.get("aggregate_sha256")
            == public.get("aggregate_sha256")
            and participant.bundle.bundle_receipt.get("bundle_sha256")
            == public.get("bundle_sha256")
        ]
        if len(participant_matches) != 1:
            reasons.add("source_role_coverage_incomplete")
            continue
        participant = participant_matches[0]
        check_id = str(observation.get("check_id") or "")
        binding_checks = [
            item
            for item in participant.prepared.binding.get("checks", ())
            if item.get("check_id") == check_id
        ]
        results = [
            item for item in participant.bundle.check_results if item.get("check_id") == check_id
        ]
        receipts = [
            item for item in participant.bundle.check_receipts if item.get("check_id") == check_id
        ]
        if len(binding_checks) != 1 or len(results) != 1 or len(receipts) != 1:
            reasons.add("source_role_coverage_incomplete")
            continue
        binding = binding_checks[0]
        result = results[0]
        receipt = receipts[0]
        aggregate = participant.bundle.aggregate
        if (
            observation.get("attempt_status") != "executed"
            or len(observation.get("matching_checks") or ()) != 1
        ):
            reasons.add("source_role_coverage_incomplete")
        if result.get("verdict") != "passed" or aggregate.get("verdict") != "passed":
            reasons.add("source_verdict_not_passed")
        if (
            observation.get("output_commitment_status") != "committed"
            or aggregate.get("output_commitment_status") != "committed"
            or receipt.get("proof_validity") != "valid"
        ):
            reasons.add("source_output_uncommitted")
        if receipt.get("reseal", {}).get("effect_classification") != "read_only":
            reasons.add("source_effect_not_read_only")
        expected_check = requirement.get("expected_check")
        if not isinstance(expected_check, Mapping) or expected_check.get(
            "declared_outputs"
        ) != []:
            reasons.add("source_declared_outputs_present")
        if (
            participant.prepared.binding.get("reuse", {}).get("disposition") != "eligible"
            or result.get("reuse_disposition") != "eligible"
            or aggregate.get("reuse_disposition") != "eligible"
            or observation.get("aggregate_reuse_disposition") != "eligible"
        ):
            reasons.add("source_reuse_forbidden")
        expected_execution = requirement.get("expected_execution")
        if not isinstance(expected_execution, Mapping):
            reasons.add("source_private_identity")
            continue
        role = {
            "role": role_name,
            "kind": requirement.get("kind"),
            "canary_id": requirement.get("canary_id"),
            "requirement_sha256": requirement.get("requirement_sha256"),
            "participant_sha256": participant_sha,
            "check_id": check_id,
            "plan_sha256": binding.get("plan_sha256"),
            "tool_identity_sha256": binding.get("tool_identity_sha256"),
            "public_execution_sha256": binding.get("public_execution_sha256"),
            "spawn_vector_sha256": binding.get("spawn_vector_sha256"),
            "external_input_binding_sha256": expected_execution.get(
                "external_input_binding_sha256"
            ),
            "execution_binding_sha256": expected_execution.get(
                "execution_binding_sha256"
            ),
            "packet_sha256": participant.bundle.packet.get("packet_sha256"),
            "final_authority_checkpoint_sha256": aggregate.get(
                "final_authority_checkpoint_sha256"
            ),
            "result_sha256": result.get("result_sha256"),
            "receipt_sha256": receipt.get("receipt_sha256"),
            "aggregate_sha256": aggregate.get("aggregate_sha256"),
            "bundle_sha256": participant.bundle.bundle_receipt.get("bundle_sha256"),
            "verdict": "passed",
            "output_commitment_status": "committed",
            "effect_classification": "read_only",
        }
        if _contains_private_identity(role):
            reasons.add("source_private_identity")
        normalized.append(role)
    normalized.sort(
        key=lambda item: (
            str(item["kind"]),
            str(item["role"]),
            str(item["check_id"]),
            str(item["participant_sha256"]),
        )
    )
    return normalized, reasons


def _candidate_identity_input(observed: Mapping[str, Any]) -> dict[str, Any]:
    head = observed["head"]
    basis = observed["basis"]
    admission = basis["admission"]
    return {
        "contract_version": PROOF_REUSE_CANDIDATE_CONTRACT_VERSION,
        "candidate_id": "PRC-" + "0" * 64,
        "source": {
            "anchor_event_id": head.event_id,
            "anchor_event_sequence": head.sequence,
            "anchor_generation": head.generation,
            "anchor_sha256": head.payload["anchor_sha256"],
            "manifest_file_sha256": head.payload["manifest_file_sha256"],
            "basis_sha256": basis["basis_sha256"],
            "policy_sha256": basis["bindings"]["policy_sha256"],
            "coverage_group_sha256": basis["bindings"]["coverage_group_sha256"],
            "admission_sha256": basis["bindings"]["admission_sha256"],
        },
        "target": deepcopy(basis["target"]),
        "candidate": deepcopy(basis["candidate"]),
        "current_proof": {
            "scope": admission["current_proof"]["scope"],
            "status": admission["current_proof"]["status"],
            "match_status": admission["current_proof"]["match_status"],
            "proof_sha256": admission["current_proof"]["proof_sha256"],
        },
        "roles": deepcopy(observed["roles"]),
    }


def _read_committed_candidate(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
) -> dict[str, Any] | None:
    event_id = _candidate_event_id(candidate_id)
    row = conn.execute(
        """
        SELECT id, sequence, entity_type, entity_id, payload_json
        FROM events WHERE id = ? AND event_type = ?
        """,
        (event_id, PROOF_REUSE_CANDIDATE_EVENT_TYPE),
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(str(row["payload_json"]))
        _require_event_payload(payload)
        evidence = conn.execute(
            "SELECT id, type, path, summary FROM evidence WHERE id = ?",
            (payload["evidence_id"],),
        ).fetchone()
        links = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM evidence_links
                WHERE evidence_id = ? AND target_type = 'task'
                  AND target_id = ? AND link_role = ?
                """,
                (
                    payload["evidence_id"],
                    row["entity_id"],
                    PROOF_REUSE_CANDIDATE_LINK_ROLE,
                ),
            ).fetchone()[0]
        )
        outbox_id = _candidate_outbox_id(candidate_id)
        outbox = conn.execute(
            "SELECT id, event_id, sink, idempotency_key FROM outbox_records WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        summary = None if evidence is None else json.loads(str(evidence["summary"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, sqlite3.Error):
        return {"healthy": False}
    expected_summary = {
        "contract_version": PROOF_REUSE_CANDIDATE_EVIDENCE_SUMMARY_VERSION,
        "candidate_id": candidate_id,
        "candidate_sha256": payload["candidate_sha256"],
        "artifact_file_sha256": payload["artifact_file_sha256"],
        "artifact_size_bytes": payload["artifact_size_bytes"],
        "source_anchor_event_id": payload["source_anchor_event_id"],
    }
    expected_path = (
        ".project-loop/evidence/proof-reuse-candidates/"
        f"{candidate_id[4:].lower()}/candidate.json"
    )
    if (
        row["entity_type"] != "task"
        or row["entity_id"] is None
        or payload["candidate_id"] != candidate_id
        or evidence is None
        or evidence["type"] != PROOF_REUSE_CANDIDATE_EVIDENCE_TYPE
        or evidence["path"] != expected_path
        or summary != expected_summary
        or links != 1
        or outbox is None
        or outbox["id"] != outbox_id
        or outbox["event_id"] != event_id
        or outbox["sink"] != "jsonl"
        or outbox["idempotency_key"] != f"jsonl:{event_id}"
    ):
        return {"healthy": False}
    assessment = assess_proof_reuse_candidate_artifact(
        paths,
        candidate_id=candidate_id,
        expected_sha256=payload["artifact_file_sha256"],
        expected_size_bytes=int(payload["artifact_size_bytes"]),
    )
    if (
        not assessment.healthy
        or assessment.candidate is None
        or assessment.candidate.get("candidate_sha256") != payload["candidate_sha256"]
    ):
        return {"healthy": False}
    return {
        "healthy": True,
        "candidate": assessment.candidate,
        "evidence_id": str(evidence["id"]),
        "event_id": event_id,
        "event_sequence": int(row["sequence"]),
        "outbox_id": outbox_id,
    }


def _candidate_event_exists(conn: sqlite3.Connection, candidate_id: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM events WHERE id = ?",
            (_candidate_event_id(candidate_id),),
        ).fetchone()
    )


def _candidate_event_id(candidate_id: str) -> str:
    digest = domain_sha256("proof-reuse-candidate-event-id/v1", candidate_id)[7:]
    return "EV-" + digest.upper()


def _candidate_outbox_id(candidate_id: str) -> str:
    digest = domain_sha256("proof-reuse-candidate-outbox-id/v1", candidate_id)[7:]
    return "OB-" + digest.upper()


def _require_event_payload(payload: Mapping[str, Any]) -> None:
    expected = {
        "contract_version",
        "candidate_id",
        "candidate_sha256",
        "artifact_file_sha256",
        "artifact_size_bytes",
        "source_anchor_event_id",
        "evidence_id",
    }
    if (
        not isinstance(payload, Mapping)
        or set(payload) != expected
        or payload.get("contract_version") != PROOF_REUSE_CANDIDATE_EVENT_CONTRACT_VERSION
        or not isinstance(payload.get("candidate_id"), str)
        or not payload["candidate_id"].startswith("PRC-")
        or not _is_sha(payload.get("candidate_sha256"))
        or not _is_sha(payload.get("artifact_file_sha256"))
        or type(payload.get("artifact_size_bytes")) is not int
        or not 1 <= payload["artifact_size_bytes"] <= 8 * 1024 * 1024
        or not isinstance(payload.get("source_anchor_event_id"), str)
        or not payload["source_anchor_event_id"].startswith("EV-")
        or not isinstance(payload.get("evidence_id"), str)
        or not payload["evidence_id"].startswith("E-")
    ):
        raise ValueError("Invalid C7 event payload.")


def _nonrecordable_result(*, reasons: Sequence[str], source_health: str) -> Mapping[str, Any]:
    status = status_for_reasons(reasons)
    result = finalize_proof_reuse_candidate_result(
        {
            "contract_version": PROOF_REUSE_CANDIDATE_RESULT_CONTRACT_VERSION,
            "ok": False,
            "status": status,
            "status_rank": REUSE_CANDIDATE_STATUS_RANK[status],
            "changed": False,
            "idempotent": False,
            "mutation_committed": False,
            "safe_to_retry_original": True,
            "candidate_id": None,
            "candidate": None,
            "reason_codes": sorted(set(reasons)),
            "projection": _projection("none"),
            "outbox_delivery": "not_applicable",
            "health": {
                "source_anchor": source_health,
                "candidate_artifact": "not_applicable",
                "postcommit_checked": False,
            },
            "effects": dict(REUSE_CANDIDATE_EFFECTS_ZERO),
            "result_sha256": "sha256:" + "0" * 64,
        }
    )
    if not validate_proof_reuse_candidate_result(result).ok:
        raise _error("reuse_candidate_contract_invalid", "live", EXIT_DATA_ERROR)
    return result


def _success_result(
    *,
    candidate: Mapping[str, Any],
    changed: bool,
    idempotent: bool,
    mutation_committed: bool,
    safe_to_retry_original: bool,
    projection_status: str,
    evidence_id: str,
    event_id: str,
    event_sequence: int,
    outbox_id: str,
    outbox_delivery: str,
    artifact_health: str,
    effects: Mapping[str, Any],
) -> Mapping[str, Any]:
    candidate_copy = _json_copy(candidate)
    result = finalize_proof_reuse_candidate_result(
        {
            "contract_version": PROOF_REUSE_CANDIDATE_RESULT_CONTRACT_VERSION,
            "ok": artifact_health == "healthy",
            "status": "recordable",
            "status_rank": 0,
            "changed": changed,
            "idempotent": idempotent,
            "mutation_committed": mutation_committed,
            "safe_to_retry_original": safe_to_retry_original,
            "candidate_id": candidate_copy["candidate_id"],
            "candidate": candidate_copy,
            "reason_codes": [],
            "projection": _projection(
                projection_status,
                evidence_id=evidence_id,
                event_id=event_id,
                event_sequence=event_sequence,
                outbox_id=outbox_id,
                artifact_id=candidate_copy["candidate_id"],
            ),
            "outbox_delivery": outbox_delivery,
            "health": {
                "source_anchor": "healthy",
                "candidate_artifact": artifact_health,
                "postcommit_checked": True,
            },
            "effects": dict(effects),
            "result_sha256": "sha256:" + "0" * 64,
        }
    )
    validation = validate_proof_reuse_candidate_result(result)
    if not validation.ok:
        raise _error("reuse_candidate_contract_invalid", "postcommit", EXIT_DATA_ERROR)
    return result


def _projection(
    status: str,
    *,
    evidence_id: str | None = None,
    event_id: str | None = None,
    event_sequence: int | None = None,
    outbox_id: str | None = None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "evidence_id": evidence_id,
        "event_id": event_id,
        "event_sequence": event_sequence,
        "outbox_id": outbox_id,
        "artifact_id": artifact_id,
    }


def _recover_projection_only(paths: ProjectPaths, outbox_id: str) -> None:
    if _read_outbox_delivery(paths, outbox_id) == "delivered":
        return
    try:
        project_pending_events(paths)
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except Exception:
        return


def _read_outbox_delivery(paths: ProjectPaths, outbox_id: str) -> str:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            "SELECT status FROM outbox_records WHERE id = ?",
            (outbox_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return "failed_needs_review"
    status = str(row["status"])
    if status == "delivered":
        return "delivered"
    if status == "failed_needs_review":
        return "failed_needs_review"
    return "pending"


def _pending_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM outbox_records WHERE status != 'delivered'"
        ).fetchone()[0]
    )


def _require_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT value FROM metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None or str(row["value"]) != PROOF_REUSE_CANDIDATE_DATABASE_SCHEMA_VERSION:
        raise _error(
            "reuse_candidate_database_schema_unsupported",
            "preflight",
            EXIT_USAGE,
        )


def _event_sequence(conn: sqlite3.Connection, event_id: str) -> int:
    row = conn.execute("SELECT sequence FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise ValueError("Missing event sequence.")
    return int(row["sequence"])


def _require_inputs(
    paths: ProjectPaths,
    anchor_event_id: str,
    expected_target_id: str,
    expected_candidate: Mapping[str, str],
    expected_basis_sha256: str,
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    authority_provider: Callable[[], AuthorityInputSnapshot],
) -> None:
    if (
        type(paths) is not ProjectPaths
        or type(anchor_event_id) is not str
        or type(expected_target_id) is not str
        or not isinstance(expected_candidate, Mapping)
        or type(expected_basis_sha256) is not str
        or type(policy) is not TrustedCoveragePolicy
        or not isinstance(participants, Sequence)
        or isinstance(participants, (str, bytes, bytearray))
        or any(type(item) is not ProofCoverageParticipant for item in participants)
        or not callable(authority_provider)
    ):
        raise _error("reuse_candidate_input_type_invalid", "preflight", EXIT_USAGE)
    if (
        not anchor_event_id.startswith("EV-")
        or not _public_identifier(expected_target_id)
        or not _is_sha(expected_basis_sha256)
        or set(expected_candidate) != {"object_format", "commit_oid", "tree_oid"}
        or len(participants) > MAX_PARTICIPANTS
    ):
        raise _error("reuse_candidate_contract_invalid", "preflight", EXIT_USAGE)
    redacted, changed = redact_value(
        {
            "anchor_event_id": anchor_event_id,
            "expected_target_id": expected_target_id,
        }
    )
    del redacted
    if changed:
        raise _error(
            "reuse_candidate_secret_shaped_identifier",
            "preflight",
            EXIT_USAGE,
        )


def _contains_private_identity(value: Mapping[str, Any]) -> bool:
    for key, item in value.items():
        if item is None and key == "canary_id":
            continue
        if key in {"role", "kind", "check_id", "canary_id"}:
            if not _public_identifier(item):
                return True
        elif key not in {"verdict", "output_commitment_status", "effect_classification"}:
            if not _is_sha(item):
                return True
    redacted, changed = redact_value(_json_copy(value))
    del redacted
    return changed


def _public_identifier(value: Any) -> bool:
    if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= 4096:
        return False
    return value[0].isalnum() and all(
        character.isalnum() or character in "_.:-" for character in value
    )


def _is_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(canonical_proof_reuse_candidate_bytes(value))


def _error(code: str, phase: str, exit_code: int = 1) -> ProofReuseCandidateError:
    return ProofReuseCandidateError(
        "Proof-reuse candidate operation failed.",
        code=code,
        exit_code=exit_code,
        details={"phase": phase},
    )


__all__ = [
    "PROOF_REUSE_CANDIDATE_EVIDENCE_TYPE",
    "PROOF_REUSE_CANDIDATE_EVENT_TYPE",
    "PROOF_REUSE_CANDIDATE_LINK_ROLE",
    "ProofReuseCandidateError",
    "record_proof_reuse_candidate",
]
