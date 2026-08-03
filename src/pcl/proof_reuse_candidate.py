from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3
from typing import Any

from .contracts.authority_surface import validate_authority_surface_resolution
from .contracts.proof_anchor import canonical_proof_anchor_bytes
from .contracts.proof_reuse_candidate import (
    MAX_ANCHOR_ROWS,
    MAX_PARTICIPANTS,
    MAX_PUBLIC_ID_BYTES,
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
from .db import MutationConnection, connect, connect_mutation, connect_read_only
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

_CANDIDATE_IDENTIFIER = re.compile(r"^PRC-[0-9A-F]{64}$")
_EVENT_IDENTIFIER = re.compile(r"^EV-[0-9A-F]{64}$")
_EVIDENCE_IDENTIFIER = re.compile(r"^E-[0-9A-Z]+$")
_OUTBOX_IDENTIFIER = re.compile(r"^OB-[0-9A-F]{64}$")
_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SHA_IDENTIFIER = re.compile(r"^sha256:[0-9a-f]{64}$")
_OID = re.compile(r"^[0-9a-f]+$")


class ProofReuseCandidateError(PclError):
    pass


class _StoredIdentifierError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__("Stored C7 identifier is invalid.")
        self.code = code


@dataclass(frozen=True, slots=True)
class ProofReuseCandidateInventorySelection:
    """Read-only inventory selection; never a reuse or lifecycle capability."""

    status: str
    reason: str
    current_anchor_event_id: str | None
    candidate: Mapping[str, Any] | None


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


def select_current_proof_reuse_candidate(
    paths: ProjectPaths,
    *,
    anchor_event_id: str,
) -> ProofReuseCandidateInventorySelection:
    """Select the current C7 inventory item without granting or mutating authority."""
    if not platform_supported():
        raise _error("reuse_candidate_platform_unsupported", "preflight", EXIT_USAGE)
    _require_inventory_inputs(paths, anchor_event_id)
    conn: sqlite3.Connection | None = None
    try:
        conn = connect_read_only(paths.db_path)
        conn.execute("BEGIN")
        _require_schema(conn)
        resolution = resolve_proof_anchor_drift_authority(
            paths,
            conn,
            anchor_event_id=anchor_event_id,
            anchor_row_limit=MAX_ANCHOR_ROWS + 1,
        )
        head = _healthy_current_anchor(resolution)
        if head is None:
            return ProofReuseCandidateInventorySelection(
                status="none",
                reason="current_anchor_unavailable",
                current_anchor_event_id=None,
                candidate=None,
            )
        expected_identity = _current_head_identity(resolution, head)
        if expected_identity is None:
            return ProofReuseCandidateInventorySelection(
                status="none",
                reason="current_anchor_unavailable",
                current_anchor_event_id=None,
                candidate=None,
            )
        rows = conn.execute(
            """
            SELECT payload_json
            FROM events
            WHERE event_type = ? AND entity_type = 'task' AND entity_id = ?
            ORDER BY sequence, id
            """,
            (
                PROOF_REUSE_CANDIDATE_EVENT_TYPE,
                expected_identity["target"]["id"],
            ),
        ).fetchall()
        candidates: dict[str, tuple[int, Mapping[str, Any]]] = {}
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
                candidate_id = payload["candidate_id"]
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if not _candidate_identifier(candidate_id):
                continue
            committed = _read_committed_candidate(
                paths,
                conn,
                candidate_id=candidate_id,
                expected_identity=expected_identity,
            )
            if committed is None or not committed["healthy"]:
                continue
            candidate = committed["candidate"]
            observation_sequence = candidate["observation"][
                "observed_through_event_sequence"
            ]
            candidates[candidate_id] = (observation_sequence, candidate)
        if not candidates:
            return ProofReuseCandidateInventorySelection(
                status="none",
                reason="current_candidate_not_found",
                current_anchor_event_id=head.event_id,
                candidate=None,
            )
        maximum = max(item[0] for item in candidates.values())
        winners = sorted(
            (candidate_id, candidate)
            for candidate_id, (sequence, candidate) in candidates.items()
            if sequence == maximum
        )
        if len(winners) != 1:
            return ProofReuseCandidateInventorySelection(
                status="ambiguous",
                reason="current_candidate_ambiguous",
                current_anchor_event_id=head.event_id,
                candidate=None,
            )
        return ProofReuseCandidateInventorySelection(
            status="selected",
            reason="selected",
            current_anchor_event_id=head.event_id,
            candidate=winners[0][1],
        )
    except ProofReuseCandidateError:
        raise
    except ProofAnchorAuthorityCapacityError:
        raise _error("reuse_candidate_capacity_exceeded", "authority", EXIT_DATA_ERROR) from None
    except sqlite3.DatabaseError:
        raise _error(
            "reuse_candidate_database_schema_unsupported",
            "preflight",
            EXIT_DATA_ERROR,
        ) from None
    except (OSError, UnicodeError):
        raise _error("reuse_candidate_store_invalid", "replay", EXIT_DATA_ERROR) from None
    except (KeyError, TypeError, ValueError, AssertionError):
        raise _error("reuse_candidate_internal_error", "replay", EXIT_DATA_ERROR) from None
    finally:
        if conn is not None:
            conn.close()


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
        committed = _read_committed_candidate(
            paths,
            conn,
            candidate_id=candidate_id,
            expected_identity={**identity_input, "candidate_id": candidate_id},
        )
        if committed is not None:
            conn.rollback()
            if not committed["healthy"]:
                error_code = committed.get("error_code")
                if error_code in {
                    "reuse_candidate_capacity_exceeded",
                    "reuse_candidate_contract_invalid",
                }:
                    raise _error(error_code, "replay", EXIT_DATA_ERROR)
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
            "target": deepcopy(candidate["target"]),
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


def _healthy_current_anchor(resolution: Any) -> Any | None:
    if (
        resolution.tombstone_status != "absent"
        or resolution.exhaustion_witness is not None
        or not resolution.assertion_found
        or resolution.authority_corrupt
        or resolution.malformed_group_present
        or len(resolution.valid_chains) != 1
        or not resolution.valid_chains[0]
        or resolution.target_id is None
    ):
        return None
    head = resolution.valid_chains[0][-1]
    return head if head.health_status == "healthy" else None


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


def _current_basis_role_identity(
    basis: Mapping[str, Any],
) -> list[dict[str, Any]] | None:
    policy = basis.get("policy")
    admission = basis.get("admission")
    if not isinstance(policy, Mapping) or not isinstance(admission, Mapping):
        return None
    requirements = policy.get("required_roles")
    observations = admission.get("role_observations")
    participants = admission.get("participants")
    if (
        not isinstance(requirements, list)
        or not 1 <= len(requirements) <= MAX_ROLES
        or not isinstance(observations, list)
        or len(observations) != len(requirements)
        or not isinstance(participants, list)
        or not 1 <= len(participants) <= MAX_PARTICIPANTS
        or any(not isinstance(item, Mapping) for item in observations)
    ):
        return None

    participant_by_sha: dict[str, Mapping[str, Any]] = {}
    for participant in participants:
        if not isinstance(participant, Mapping):
            return None
        participant_sha = participant.get("participant_sha256")
        if not _is_sha(participant_sha) or participant_sha in participant_by_sha:
            return None
        participant_by_sha[participant_sha] = participant

    roles: list[dict[str, Any]] = []
    used_observations: set[int] = set()
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            return None
        expected_check = requirement.get("expected_check")
        expected_execution = requirement.get("expected_execution")
        if not isinstance(expected_check, Mapping) or not isinstance(
            expected_execution, Mapping
        ):
            return None
        role_name = requirement.get("role")
        kind = requirement.get("kind")
        canary_id = requirement.get("canary_id")
        requirement_sha = requirement.get("requirement_sha256")
        check_id = expected_check.get("check_id")
        if (
            not _public_identifier(role_name)
            or not _public_identifier(kind)
            or (canary_id is not None and not _public_identifier(canary_id))
            or not _is_sha(requirement_sha)
            or not _public_identifier(check_id)
            or expected_check.get("role") != role_name
        ):
            return None

        matching_observations = [
            (index, observation)
            for index, observation in enumerate(observations)
            if observation.get("role") == role_name
            and observation.get("kind") == kind
            and observation.get("canary_id") == canary_id
            and observation.get("requirement_sha256") == requirement_sha
            and observation.get("check_id") == check_id
        ]
        if len(matching_observations) != 1:
            return None
        observation_index, observation = matching_observations[0]
        if observation_index in used_observations:
            return None
        used_observations.add(observation_index)

        participant_sha = observation.get("selected_participant_sha256")
        matching_checks = observation.get("matching_checks")
        if (
            not _is_sha(participant_sha)
            or not isinstance(matching_checks, list)
            or len(matching_checks) != 1
            or not isinstance(matching_checks[0], Mapping)
            or set(matching_checks[0]) != {"check_id", "participant_sha256"}
            or matching_checks[0].get("check_id") != check_id
            or matching_checks[0].get("participant_sha256") != participant_sha
        ):
            return None
        participant = participant_by_sha.get(participant_sha)
        if participant is None:
            return None

        role = {
            "role": role_name,
            "kind": kind,
            "canary_id": canary_id,
            "requirement_sha256": requirement_sha,
            "participant_sha256": participant_sha,
            "check_id": check_id,
            "plan_sha256": expected_execution.get("plan_sha256"),
            "tool_identity_sha256": expected_execution.get("tool_identity_sha256"),
            "public_execution_sha256": expected_execution.get(
                "public_execution_sha256"
            ),
            "spawn_vector_sha256": expected_execution.get("spawn_vector_sha256"),
            "external_input_binding_sha256": expected_execution.get(
                "external_input_binding_sha256"
            ),
            "execution_binding_sha256": expected_execution.get(
                "execution_binding_sha256"
            ),
            "packet_sha256": participant.get("packet_sha256"),
            "result_sha256": observation.get("result_sha256"),
            "receipt_sha256": observation.get("receipt_sha256"),
            "aggregate_sha256": participant.get("aggregate_sha256"),
            "bundle_sha256": participant.get("bundle_sha256"),
        }
        if participant.get("external_input_binding_sha256") != role[
            "external_input_binding_sha256"
        ] or any(
            not _is_sha(role[name])
            for name in set(role) - {"role", "kind", "canary_id", "check_id"}
        ):
            return None
        roles.append(role)

    if len(used_observations) != len(observations):
        return None
    roles.sort(
        key=lambda item: (
            str(item["kind"]),
            str(item["role"]),
            str(item["check_id"]),
            str(item["participant_sha256"]),
        )
    )
    sort_keys = [
        (
            item["kind"],
            item["role"],
            item["check_id"],
            item["participant_sha256"],
        )
        for item in roles
    ]
    if len(sort_keys) != len(set(sort_keys)):
        return None
    # C5 does not retain the final checkpoint or receipt effect classification;
    # those fields remain live-C2/C3-only and are deliberately not fabricated.
    return roles


def _current_head_identity(resolution: Any, head: Any) -> dict[str, Any] | None:
    basis = head.members.get("basis")
    if not isinstance(basis, Mapping):
        return None
    bindings = basis.get("bindings")
    admission = basis.get("admission")
    target = basis.get("target")
    git_candidate = basis.get("candidate")
    if not all(
        isinstance(item, Mapping)
        for item in (bindings, admission, target, git_candidate)
    ):
        return None
    current_proof = admission.get("current_proof")
    if not isinstance(current_proof, Mapping):
        return None
    roles = _current_basis_role_identity(basis)
    if roles is None:
        return None
    try:
        source = {
            "anchor_event_id": head.event_id,
            "anchor_event_sequence": head.sequence,
            "anchor_generation": head.generation,
            "anchor_sha256": head.payload["anchor_sha256"],
            "manifest_file_sha256": head.payload["manifest_file_sha256"],
            "basis_sha256": basis["basis_sha256"],
            "policy_sha256": bindings["policy_sha256"],
            "coverage_group_sha256": bindings["coverage_group_sha256"],
            "admission_sha256": bindings["admission_sha256"],
        }
        expected = {
            "contract_version": PROOF_REUSE_CANDIDATE_CONTRACT_VERSION,
            "source": source,
            "target": deepcopy(target),
            "candidate": deepcopy(git_candidate),
            "current_proof": {
                "scope": current_proof["scope"],
                "status": current_proof["status"],
                "match_status": current_proof["match_status"],
                "proof_sha256": current_proof["proof_sha256"],
            },
            "roles": roles,
        }
    except (KeyError, TypeError):
        return None
    if (
        resolution.target_id != expected["target"].get("id")
        or resolution.basis_sha256 != source["basis_sha256"]
        or head.payload.get("basis_sha256") != source["basis_sha256"]
        or set(expected["target"]) != {"type", "id"}
        or expected["target"].get("type") != "task"
        or not _public_identifier(expected["target"].get("id"))
        or set(expected["candidate"]) != {"object_format", "commit_oid", "tree_oid"}
        or not _git_candidate_assertion(expected["candidate"])
        or set(expected["current_proof"])
        != {"scope", "status", "match_status", "proof_sha256"}
        or expected["current_proof"].get("scope") != "feature"
        or expected["current_proof"].get("status") != "healthy"
        or expected["current_proof"].get("match_status") != "matched"
        or not _is_sha(expected["current_proof"].get("proof_sha256"))
        or not _event_identifier(source["anchor_event_id"])
        or type(source["anchor_event_sequence"]) is not int
        or source["anchor_event_sequence"] < 1
        or type(source["anchor_generation"]) is not int
        or not 0 <= source["anchor_generation"] <= 3
        or any(
            not _is_sha(source[name])
            for name in (
                "anchor_sha256",
                "manifest_file_sha256",
                "basis_sha256",
                "policy_sha256",
                "coverage_group_sha256",
                "admission_sha256",
            )
        )
    ):
        return None
    return expected


def _read_committed_candidate(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    expected_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        _require_stored_identifier(candidate_id, _CANDIDATE_IDENTIFIER)
    except _StoredIdentifierError as exc:
        return {"healthy": False, "error_code": exc.code}
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
        _require_stored_identifier(row["id"], _EVENT_IDENTIFIER)
        _require_stored_identifier(row["entity_type"], _PUBLIC_IDENTIFIER)
        _require_stored_identifier(row["entity_id"], _PUBLIC_IDENTIFIER)
        payload = json.loads(str(row["payload_json"]))
        _require_event_payload(payload)
        evidence = conn.execute(
            "SELECT id, type, path, summary FROM evidence WHERE id = ?",
            (payload["evidence_id"],),
        ).fetchone()
        links = conn.execute(
            """
            SELECT target_type, target_id, link_role
            FROM evidence_links WHERE evidence_id = ?
            ORDER BY target_type, target_id, link_role LIMIT 2
            """,
            (payload["evidence_id"],),
        ).fetchall()
        outbox_id = _candidate_outbox_id(candidate_id)
        outboxes = conn.execute(
            """
            SELECT id, event_id, sink, idempotency_key
            FROM outbox_records WHERE event_id = ? ORDER BY id LIMIT 2
            """,
            (event_id,),
        ).fetchall()
        summary = None if evidence is None else json.loads(str(evidence["summary"]))
        if evidence is not None:
            _require_stored_identifier(evidence["id"], _EVIDENCE_IDENTIFIER)
            _require_stored_identifier(evidence["type"], _PUBLIC_IDENTIFIER)
        for link in links:
            _require_stored_identifier(link["target_type"], _PUBLIC_IDENTIFIER)
            _require_stored_identifier(link["target_id"], _PUBLIC_IDENTIFIER)
            _require_stored_identifier(link["link_role"], _PUBLIC_IDENTIFIER)
        for outbox in outboxes:
            _require_stored_identifier(outbox["id"], _OUTBOX_IDENTIFIER)
            _require_stored_identifier(outbox["event_id"], _EVENT_IDENTIFIER)
            _require_stored_identifier(outbox["sink"], _PUBLIC_IDENTIFIER)
            _require_stored_identifier(outbox["idempotency_key"], _PUBLIC_IDENTIFIER)
        _require_evidence_summary_identifiers(summary)
    except _StoredIdentifierError as exc:
        return {"healthy": False, "error_code": exc.code}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, sqlite3.Error):
        return {"healthy": False}
    assessment = assess_proof_reuse_candidate_artifact(
        paths,
        candidate_id=candidate_id,
        expected_sha256=payload["artifact_file_sha256"],
        expected_size_bytes=int(payload["artifact_size_bytes"]),
    )
    if not assessment.healthy or assessment.candidate is None:
        return {"healthy": False}
    candidate = assessment.candidate
    try:
        _require_candidate_identifiers(candidate)
    except _StoredIdentifierError as exc:
        return {"healthy": False, "error_code": exc.code}
    except (KeyError, TypeError, ValueError):
        return {"healthy": False}
    target = candidate.get("target")
    source = candidate.get("source")
    if not isinstance(target, Mapping) or not isinstance(source, Mapping):
        return {"healthy": False}
    target_type = target.get("type")
    target_id = target.get("id")
    expected_summary = {
        "contract_version": PROOF_REUSE_CANDIDATE_EVIDENCE_SUMMARY_VERSION,
        "candidate_id": candidate_id,
        "candidate_sha256": payload["candidate_sha256"],
        "artifact_file_sha256": payload["artifact_file_sha256"],
        "artifact_size_bytes": payload["artifact_size_bytes"],
        "source_anchor_event_id": payload["source_anchor_event_id"],
        "target": {"type": target_type, "id": target_id},
    }
    expected_path = (
        ".project-loop/evidence/proof-reuse-candidates/"
        f"{candidate_id[4:].lower()}/candidate.json"
    )
    outbox = outboxes[0] if len(outboxes) == 1 else None
    if (
        row["id"] != event_id
        or row["entity_type"] != target_type
        or row["entity_id"] != target_id
        or payload["candidate_id"] != candidate_id
        or payload["candidate_sha256"] != candidate.get("candidate_sha256")
        or payload["source_anchor_event_id"] != source.get("anchor_event_id")
        or evidence is None
        or evidence["id"] != payload["evidence_id"]
        or evidence["type"] != PROOF_REUSE_CANDIDATE_EVIDENCE_TYPE
        or evidence["path"] != expected_path
        or summary != expected_summary
        or len(links) != 1
        or links[0]["target_type"] != target_type
        or links[0]["target_id"] != target_id
        or links[0]["link_role"] != PROOF_REUSE_CANDIDATE_LINK_ROLE
        or len(outboxes) != 1
        or outbox is None
        or outbox["id"] != outbox_id
        or outbox["event_id"] != event_id
        or outbox["sink"] != "jsonl"
        or outbox["idempotency_key"] != f"jsonl:{event_id}"
    ):
        return {"healthy": False}
    if expected_identity is not None and not _matches_authenticated_identity(
        candidate,
        expected_identity,
    ):
        return {"healthy": False}
    return {
        "healthy": True,
        "candidate": candidate,
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
        or type(payload.get("artifact_size_bytes")) is not int
        or not 1 <= payload["artifact_size_bytes"] <= 8 * 1024 * 1024
    ):
        raise ValueError("Invalid C7 event payload.")
    _require_stored_identifier(payload.get("candidate_id"), _CANDIDATE_IDENTIFIER)
    _require_stored_identifier(payload.get("candidate_sha256"), _SHA_IDENTIFIER)
    _require_stored_identifier(payload.get("artifact_file_sha256"), _SHA_IDENTIFIER)
    _require_stored_identifier(payload.get("source_anchor_event_id"), _EVENT_IDENTIFIER)
    _require_stored_identifier(payload.get("evidence_id"), _EVIDENCE_IDENTIFIER)


def _require_evidence_summary_identifiers(summary: Any) -> None:
    expected = {
        "contract_version",
        "candidate_id",
        "candidate_sha256",
        "artifact_file_sha256",
        "artifact_size_bytes",
        "source_anchor_event_id",
        "target",
    }
    if (
        not isinstance(summary, Mapping)
        or set(summary) != expected
        or summary.get("contract_version")
        != PROOF_REUSE_CANDIDATE_EVIDENCE_SUMMARY_VERSION
        or type(summary.get("artifact_size_bytes")) is not int
        or not 1 <= summary["artifact_size_bytes"] <= 8 * 1024 * 1024
    ):
        raise ValueError("Invalid C7 Evidence summary.")
    target = summary.get("target")
    if not isinstance(target, Mapping) or set(target) != {"type", "id"}:
        raise ValueError("Invalid C7 Evidence target.")
    _require_stored_identifier(summary.get("candidate_id"), _CANDIDATE_IDENTIFIER)
    _require_stored_identifier(summary.get("candidate_sha256"), _SHA_IDENTIFIER)
    _require_stored_identifier(summary.get("artifact_file_sha256"), _SHA_IDENTIFIER)
    _require_stored_identifier(summary.get("source_anchor_event_id"), _EVENT_IDENTIFIER)
    _require_stored_identifier(target.get("type"), _PUBLIC_IDENTIFIER)
    _require_stored_identifier(target.get("id"), _PUBLIC_IDENTIFIER)


def _require_candidate_identifiers(candidate: Mapping[str, Any]) -> None:
    _require_stored_identifier(candidate.get("candidate_id"), _CANDIDATE_IDENTIFIER)
    _require_stored_identifier(candidate.get("candidate_sha256"), _SHA_IDENTIFIER)
    source = candidate.get("source")
    observation = candidate.get("observation")
    target = candidate.get("target")
    git_candidate = candidate.get("candidate")
    current_proof = candidate.get("current_proof")
    roles = candidate.get("roles")
    if not all(
        isinstance(item, Mapping)
        for item in (source, observation, target, git_candidate, current_proof)
    ) or not isinstance(roles, list):
        raise ValueError("Invalid C7 candidate identifiers.")
    _require_stored_identifier(source.get("anchor_event_id"), _EVENT_IDENTIFIER)
    for name in (
        "anchor_sha256",
        "manifest_file_sha256",
        "basis_sha256",
        "policy_sha256",
        "coverage_group_sha256",
        "admission_sha256",
    ):
        _require_stored_identifier(source.get(name), _SHA_IDENTIFIER)
    _require_stored_identifier(
        observation.get("observed_through_event_id"),
        _PUBLIC_IDENTIFIER,
    )
    _require_stored_identifier(
        observation.get("observed_through_anchor_event_id"),
        _EVENT_IDENTIFIER,
    )
    _require_stored_identifier(target.get("type"), _PUBLIC_IDENTIFIER)
    _require_stored_identifier(target.get("id"), _PUBLIC_IDENTIFIER)
    _require_stored_identifier(git_candidate.get("object_format"), _PUBLIC_IDENTIFIER)
    _require_stored_identifier(git_candidate.get("commit_oid"), _OID)
    _require_stored_identifier(git_candidate.get("tree_oid"), _OID)
    for name in ("scope", "status", "match_status"):
        _require_stored_identifier(current_proof.get(name), _PUBLIC_IDENTIFIER)
    _require_stored_identifier(current_proof.get("proof_sha256"), _SHA_IDENTIFIER)
    role_sha_fields = {
        "requirement_sha256",
        "participant_sha256",
        "plan_sha256",
        "tool_identity_sha256",
        "public_execution_sha256",
        "spawn_vector_sha256",
        "external_input_binding_sha256",
        "execution_binding_sha256",
        "packet_sha256",
        "final_authority_checkpoint_sha256",
        "result_sha256",
        "receipt_sha256",
        "aggregate_sha256",
        "bundle_sha256",
    }
    for role in roles:
        if not isinstance(role, Mapping):
            raise ValueError("Invalid C7 role identifiers.")
        for name in ("role", "kind", "check_id"):
            _require_stored_identifier(role.get(name), _PUBLIC_IDENTIFIER)
        if role.get("canary_id") is not None:
            _require_stored_identifier(role.get("canary_id"), _PUBLIC_IDENTIFIER)
        for name in role_sha_fields:
            _require_stored_identifier(role.get(name), _SHA_IDENTIFIER)


def _matches_authenticated_identity(
    candidate: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    identity_fields = {
        "contract_version",
        "candidate_id",
        "source",
        "target",
        "candidate",
        "current_proof",
        "roles",
    }
    if not set(expected).issubset(identity_fields):
        return False
    for name, value in expected.items():
        if name == "roles":
            if not _matches_authenticated_roles(candidate.get(name), value):
                return False
        elif candidate.get(name) != value:
            return False
    return True


def _matches_authenticated_roles(actual: Any, expected: Any) -> bool:
    if (
        not isinstance(actual, list)
        or not isinstance(expected, list)
        or not 1 <= len(actual) == len(expected) <= MAX_ROLES
    ):
        return False
    for actual_role, expected_role in zip(actual, expected, strict=True):
        if (
            not isinstance(actual_role, Mapping)
            or not isinstance(expected_role, Mapping)
            or not set(expected_role).issubset(actual_role)
            or any(
                actual_role.get(name) != value
                for name, value in expected_role.items()
            )
        ):
            return False
    return True


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
    asserted_identifiers = [
        anchor_event_id,
        expected_target_id,
        expected_basis_sha256,
        *(
            item
            for item in expected_candidate.values()
            if isinstance(item, str)
        ),
    ]
    if len(participants) > MAX_PARTICIPANTS or any(
        (_utf8_size(item) or 0) > MAX_PUBLIC_ID_BYTES
        for item in asserted_identifiers
    ):
        raise _error("reuse_candidate_capacity_exceeded", "preflight", EXIT_USAGE)
    if (
        any(_utf8_size(item) is None for item in asserted_identifiers)
        or not _event_identifier(anchor_event_id)
        or not _public_identifier(expected_target_id)
        or not _is_sha(expected_basis_sha256)
        or set(expected_candidate) != {"object_format", "commit_oid", "tree_oid"}
        or not _git_candidate_assertion(expected_candidate)
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


def _require_inventory_inputs(paths: ProjectPaths, anchor_event_id: str) -> None:
    if type(paths) is not ProjectPaths or type(anchor_event_id) is not str:
        raise _error("reuse_candidate_input_type_invalid", "preflight", EXIT_USAGE)
    size = _utf8_size(anchor_event_id)
    if size is not None and size > MAX_PUBLIC_ID_BYTES:
        raise _error("reuse_candidate_capacity_exceeded", "preflight", EXIT_USAGE)
    if size is None or not _event_identifier(anchor_event_id):
        raise _error("reuse_candidate_contract_invalid", "preflight", EXIT_USAGE)
    redacted, changed = redact_value({"anchor_event_id": anchor_event_id})
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
    return _identifier_issue(value, _PUBLIC_IDENTIFIER) is None


def _candidate_identifier(value: Any) -> bool:
    return _identifier_issue(value, _CANDIDATE_IDENTIFIER) is None


def _event_identifier(value: Any) -> bool:
    return _identifier_issue(value, _EVENT_IDENTIFIER) is None


def _evidence_identifier(value: Any) -> bool:
    return _identifier_issue(value, _EVIDENCE_IDENTIFIER) is None


def _identifier_issue(value: Any, pattern: re.Pattern[str]) -> str | None:
    size = _utf8_size(value)
    if size is not None and size > MAX_PUBLIC_ID_BYTES:
        return "reuse_candidate_capacity_exceeded"
    if (
        not isinstance(value, str)
        or size is None
        or size < 1
        or pattern.fullmatch(value) is None
    ):
        return "reuse_candidate_contract_invalid"
    return None


def _require_stored_identifier(value: Any, pattern: re.Pattern[str]) -> None:
    issue = _identifier_issue(value, pattern)
    if issue is not None:
        raise _StoredIdentifierError(issue)


def _git_candidate_assertion(value: Mapping[str, Any]) -> bool:
    object_format = value.get("object_format")
    width = 40 if object_format == "sha1" else 64 if object_format == "sha256" else 0
    return bool(
        width
        and all(
            isinstance(value.get(name), str)
            and len(value[name]) == width
            and _OID.fullmatch(value[name])
            for name in ("commit_oid", "tree_oid")
        )
    )


def _utf8_size(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return None


def _is_sha(value: Any) -> bool:
    return _identifier_issue(value, _SHA_IDENTIFIER) is None


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
    "ProofReuseCandidateInventorySelection",
    "record_proof_reuse_candidate",
    "select_current_proof_reuse_candidate",
]
