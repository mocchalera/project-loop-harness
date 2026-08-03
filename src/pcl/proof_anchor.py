from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from copy import deepcopy
import hashlib
import json
import sqlite3
import threading
from types import MappingProxyType
from typing import Any

from .approval_provenance import (
    ACTOR_KINDS,
    SOURCE_KINDS,
    resolve_actor_kind,
    resolve_recording_provenance,
)
from .contracts.authority_surface import (
    authority_document_sha256,
    merge_authority_canaries,
    validate_authority_surface_resolution,
)
from .contracts.proof_admission import (
    canary_item_sha256,
    validate_proof_coverage_admission,
    validate_proof_coverage_policy,
)
from .contracts.proof_anchor import (
    ANCHOR_AUTHORIZATION_PROJECTION,
    ANCHOR_EFFECTS_SUCCESS,
    ANCHOR_EFFECTS_ZERO,
    ANCHOR_HANDOFF,
    ANCHOR_SCOPE,
    EXHAUSTION_EFFECTS_SUCCESS,
    MAX_ANCHOR_BYTES,
    MAX_BASIS_BYTES,
    MAX_RECOVERY_GENERATIONS,
    PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION,
    PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION,
    PROOF_ADMISSION_ANCHOR_EPOCH_CONTRACT_VERSION,
    PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION,
    PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION,
    PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION,
    authorization_sha256,
    authorization_subject_sha256,
    base_request_sha256,
    canonical_proof_anchor_bytes,
    exhaustion_event_id,
    exhaustion_outbox_id,
    finalize_proof_admission_anchor,
    finalize_proof_admission_anchor_basis,
    manifest_file_sha256,
    proof_anchor_event_id,
    proof_anchor_outbox_id,
    proof_anchor_request_id,
    validate_proof_admission_anchor,
    validate_proof_admission_anchor_basis,
    validate_proof_admission_anchor_result,
    validate_proof_admission_authorization,
    validate_proof_anchor_event,
    validate_proof_anchor_exhaustion_event,
    validate_proof_anchor_health,
)
from .db import MutationConnection, connect_mutation
from .errors import EXIT_DATA_ERROR, EXIT_RECOVERABLE_PENDING, EXIT_USAGE, PclError
from .events import append_event
from .ids import next_prefixed_id
from .outbox import canonical_event_bytes, canonical_event_record
from .paths import ProjectPaths
from .proof_admission import (
    ProofCoverageParticipant,
    TrustedCoveragePolicy,
    evaluate_proof_coverage,
)
from .proof_anchor_store import (
    PublishedProofAnchor,
    assess_proof_anchor_artifact,
    platform_supported,
    publish_proof_anchor_artifact,
    remove_published_proof_anchor,
)
from .proof_execution import (
    AuthorityInputSnapshot,
    CurrentProofSnapshot,
    capture_current_proof,
    capture_current_proof_in_snapshot,
)
from .redaction import redact_value
from .timeutil import utc_now_iso
from .test_faults import crash_if_requested


PROOF_ANCHOR_EVIDENCE_TYPE = "proof_admission_anchor"
PROOF_ANCHOR_LINK_ROLE = "proof_admission_anchor"
PROOF_ANCHOR_EVENT_TYPE = "proof_admission_anchored"
PROOF_ANCHOR_EXHAUSTION_EVENT_TYPE = "proof_admission_anchor_recovery_exhausted"
PROOF_ANCHOR_DATABASE_SCHEMA_VERSION = "8"

_AUTHORIZATION_ISSUER = object()
_AUTHORIZATION_LOCK = threading.Lock()
_AUTHORIZATION_REGISTRY: dict[
    int,
    tuple[
        ProofAdmissionAuthorizationIssuerCapability,
        str,
        str,
        str,
        str,
        str,
        str,
        bool,
    ],
] = {}


class ProofAnchorError(PclError):
    pass


class ProofAdmissionAuthorizationIssuerCapability:
    """Private live authorization issuer association; never serialized."""

    __slots__ = (
        "authorization_kind",
        "actor_kind",
        "actor_id",
        "recorder_kind",
        "recorder_id",
        "source_kind",
        "source_ref",
        "candidate_controlled",
        "_issuer",
    )

    def __init__(
        self,
        *,
        authorization_kind: str,
        actor_kind: str,
        actor_id: str,
        recorder_kind: str,
        recorder_id: str,
        source_kind: str,
        source_ref: str,
        candidate_controlled: bool,
        _issuer: object,
    ) -> None:
        if _issuer is not _AUTHORIZATION_ISSUER:
            raise TypeError("Proof-admission authorization capabilities are private.")
        self.authorization_kind = authorization_kind
        self.actor_kind = actor_kind
        self.actor_id = actor_id
        self.recorder_kind = recorder_kind
        self.recorder_id = recorder_id
        self.source_kind = source_kind
        self.source_ref = source_ref
        self.candidate_controlled = candidate_controlled
        self._issuer = _issuer


@dataclass(frozen=True, slots=True)
class TrustedProofAdmissionAuthorization:
    document: Mapping[str, Any]
    expected_authorization_sha256: str
    issuer_capability: ProofAdmissionAuthorizationIssuerCapability = field(
        repr=False,
        compare=False,
    )


@dataclass(frozen=True)
class _CommittedAnchor:
    event_id: str
    sequence: int
    payload: Mapping[str, Any]
    evidence: Mapping[str, Any]
    summary: Mapping[str, Any]
    health_status: str
    health: Mapping[str, Any]
    manifest: Mapping[str, Any] | None
    members: Mapping[str, Mapping[str, Any]]

    @property
    def generation(self) -> int:
        return int(self.payload["anchor_generation"])

    @property
    def base_request(self) -> str:
        return str(self.payload["base_request_sha256"])


@dataclass(frozen=True)
class ProofAnchorDriftAuthorityResolution:
    """Event-first, bounded C5 authority view for the read-only C6 predicate."""

    assertion_found: bool
    authority_corrupt: bool
    target_id: str | None
    basis_sha256: str | None
    tombstone_status: str
    tombstone_event_id: str | None
    tombstone_witness: _CommittedAnchor | None
    valid_chains: tuple[tuple[_CommittedAnchor, ...], ...]
    malformed_group_present: bool | None
    exhaustion_witness: _CommittedAnchor | None


class ProofAnchorAuthorityCapacityError(Exception):
    pass


def inspect_committed_proof_anchor(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    event_id: str,
) -> _CommittedAnchor | None:
    """Validate one committed C5 authority quartet from its event identity."""
    row = conn.execute(
        """
        SELECT id, sequence, payload_json
        FROM events
        WHERE id = ? AND event_type = ?
          AND entity_type = 'task' AND entity_id IS NOT NULL
        """,
        (event_id, PROOF_ANCHOR_EVENT_TYPE),
    ).fetchone()
    if row is None:
        return None
    try:
        return _read_committed_anchor(paths, conn, row)
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error):
        return None


def committed_proof_anchor_tombstone_valid(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    event_id: str,
) -> bool:
    """Validate tombstone identity, outbox, and its unhealthy generation-3 witness."""
    row = conn.execute(
        """
        SELECT id, entity_type, entity_id, payload_json
        FROM events
        WHERE id = ? AND event_type = ?
        """,
        (event_id, PROOF_ANCHOR_EXHAUSTION_EVENT_TYPE),
    ).fetchone()
    if row is None or row["entity_type"] != "task" or row["entity_id"] is None:
        return False
    try:
        payload = json.loads(str(row["payload_json"]))
        if not validate_proof_anchor_exhaustion_event(payload).ok:
            return False
        target = {"type": "task", "id": str(row["entity_id"])}
        project_instance_id = _project_instance_id(conn)
        expected_event_id = exhaustion_event_id(
            project_instance_id=project_instance_id,
            target=target,
            basis_sha256_value=str(payload["basis_sha256"]),
        )
        expected_outbox_id = exhaustion_outbox_id(
            project_instance_id=project_instance_id,
            target=target,
            basis_sha256_value=str(payload["basis_sha256"]),
        )
        outbox = conn.execute(
            """
            SELECT id, event_id, sink, idempotency_key
            FROM outbox_records WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        witness = inspect_committed_proof_anchor(
            paths,
            conn,
            event_id=str(payload["exhausted_anchor_event_id"]),
        )
    except (KeyError, TypeError, ValueError, sqlite3.Error):
        return False
    return bool(
        event_id == expected_event_id
        and outbox is not None
        and str(outbox["id"]) == expected_outbox_id
        and str(outbox["event_id"]) == event_id
        and str(outbox["sink"]) == "jsonl"
        and str(outbox["idempotency_key"]) == f"jsonl:{event_id}"
        and witness is not None
        and witness.generation == MAX_RECOVERY_GENERATIONS
        and witness.health_status == "postcommit_unhealthy"
        and payload["base_request_sha256"] == witness.payload["base_request_sha256"]
        and payload["basis_sha256"] == witness.payload["basis_sha256"]
        and payload["anchor_sha256"] == witness.payload["anchor_sha256"]
        and payload["manifest_file_sha256"]
        == witness.payload["manifest_file_sha256"]
        and payload["exhausted_request_id"] == witness.payload["request_id"]
        and payload["health_sha256"] == witness.health["health_sha256"]
    )


def resolve_proof_anchor_drift_authority(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    anchor_event_id: str,
    anchor_row_limit: int = 65,
) -> ProofAnchorDriftAuthorityResolution:
    """Resolve C5 authority with tombstone precedence and bounded enumeration."""
    assertion = conn.execute(
        """
        SELECT id, event_type, entity_type, entity_id, payload_json
        FROM events WHERE id = ?
        """,
        (anchor_event_id,),
    ).fetchone()
    if assertion is None or str(assertion["event_type"]) != PROOF_ANCHOR_EVENT_TYPE:
        return ProofAnchorDriftAuthorityResolution(
            assertion_found=False,
            authority_corrupt=False,
            target_id=None,
            basis_sha256=None,
            tombstone_status="absent",
            tombstone_event_id=None,
            tombstone_witness=None,
            valid_chains=(),
            malformed_group_present=False,
            exhaustion_witness=None,
        )
    try:
        payload = json.loads(str(assertion["payload_json"]))
        structurally_valid = bool(
            assertion["entity_type"] == "task"
            and assertion["entity_id"] is not None
            and validate_proof_anchor_event(payload).ok
            and anchor_event_id == proof_anchor_event_id(str(payload["request_id"]))
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        structurally_valid = False
        payload = {}
    if not structurally_valid:
        return ProofAnchorDriftAuthorityResolution(
            assertion_found=True,
            authority_corrupt=True,
            target_id=None,
            basis_sha256=None,
            tombstone_status="absent",
            tombstone_event_id=None,
            tombstone_witness=None,
            valid_chains=(),
            malformed_group_present=True,
            exhaustion_witness=None,
        )
    target_id = str(assertion["entity_id"])
    basis_value = str(payload["basis_sha256"])
    tombstones = conn.execute(
        """
        SELECT id, payload_json FROM events INDEXED BY idx_events_entity
        WHERE entity_type = 'task' AND entity_id = ? AND event_type = ?
          AND json_extract(payload_json, '$.contract_version') = ?
          AND json_extract(payload_json, '$.basis_sha256') = ?
        ORDER BY sequence DESC, id DESC LIMIT 2
        """,
        (
            target_id,
            PROOF_ANCHOR_EXHAUSTION_EVENT_TYPE,
            PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION,
            basis_value,
        ),
    ).fetchall()
    if len(tombstones) >= 2:
        return ProofAnchorDriftAuthorityResolution(
            assertion_found=True,
            authority_corrupt=True,
            target_id=target_id,
            basis_sha256=basis_value,
            tombstone_status="multiple",
            tombstone_event_id=None,
            tombstone_witness=None,
            valid_chains=(),
            malformed_group_present=None,
            exhaustion_witness=None,
        )
    if tombstones:
        tombstone_id = str(tombstones[0]["id"])
        valid = committed_proof_anchor_tombstone_valid(
            paths,
            conn,
            event_id=tombstone_id,
        )
        witness = None
        if valid:
            try:
                tombstone_payload = json.loads(str(tombstones[0]["payload_json"]))
                witness = inspect_committed_proof_anchor(
                    paths,
                    conn,
                    event_id=str(tombstone_payload["exhausted_anchor_event_id"]),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                valid = False
        return ProofAnchorDriftAuthorityResolution(
            assertion_found=True,
            authority_corrupt=not valid,
            target_id=target_id,
            basis_sha256=basis_value,
            tombstone_status="valid" if valid else "invalid",
            tombstone_event_id=tombstone_id if valid else None,
            tombstone_witness=witness if valid else None,
            valid_chains=(),
            malformed_group_present=None,
            exhaustion_witness=None,
        )
    chains = _enumerate_anchor_chains(
        paths,
        conn,
        target_id=target_id,
        basis_sha256_value=basis_value,
        row_limit=anchor_row_limit,
    )
    valid_chains, corrupt = _classify_chains(chains)
    witnesses = sorted(
        (
            chain[-1]
            for chain in valid_chains
            if chain[-1].generation == MAX_RECOVERY_GENERATIONS
            and chain[-1].health_status == "postcommit_unhealthy"
        ),
        key=lambda item: (item.base_request, item.sequence, item.event_id),
    )
    return ProofAnchorDriftAuthorityResolution(
        assertion_found=True,
        authority_corrupt=corrupt,
        target_id=target_id,
        basis_sha256=basis_value,
        tombstone_status="absent",
        tombstone_event_id=None,
        tombstone_witness=None,
        valid_chains=tuple(tuple(chain) for chain in valid_chains),
        malformed_group_present=corrupt,
        exhaustion_witness=witnesses[0] if witnesses else None,
    )


def issue_proof_admission_authorization_issuer_capability(
    *,
    authorization_kind: str,
    actor_kind: str,
    actor_id: str,
    recorder_kind: str | None = None,
    recorder_id: str | None = None,
    source_kind: str = "cli",
    source_ref: str = "",
    candidate_controlled: bool = False,
) -> ProofAdmissionAuthorizationIssuerCapability:
    if authorization_kind not in {"independent_review", "human_gate"}:
        raise ValueError("Unsupported proof-admission authorization kind.")
    if source_kind not in SOURCE_KINDS:
        raise ValueError("Unsupported proof-admission authorization source kind.")
    resolved_actor_kind = resolve_actor_kind(actor=actor_id, actor_kind=actor_kind)
    if resolved_actor_kind not in ACTOR_KINDS:
        raise ValueError("Unsupported authorization actor kind.")
    if candidate_controlled is not False:
        raise ValueError("Candidate-controlled actors cannot authorize proof anchors.")
    provenance = resolve_recording_provenance(
        actor=actor_id,
        actor_kind=resolved_actor_kind,
        recorded_by=recorder_id,
        recorder_kind=recorder_kind,
        source_kind=source_kind,
        source_ref=source_ref,
        command="proof-admission-anchor",
    )
    capability = ProofAdmissionAuthorizationIssuerCapability(
        authorization_kind=authorization_kind,
        actor_kind=resolved_actor_kind,
        actor_id=actor_id,
        recorder_kind=provenance["recorder_kind"],
        recorder_id=provenance["recorder"],
        source_kind=provenance["source_kind"],
        source_ref=provenance["source_ref"],
        candidate_controlled=False,
        _issuer=_AUTHORIZATION_ISSUER,
    )
    with _AUTHORIZATION_LOCK:
        _AUTHORIZATION_REGISTRY[id(capability)] = (
            capability,
            capability.authorization_kind,
            capability.actor_kind,
            capability.actor_id,
            capability.recorder_kind,
            capability.recorder_id,
            capability.source_kind,
            capability.source_ref,
            capability.candidate_controlled,
        )
    return capability


def bind_proof_admission_authorization(
    document: Mapping[str, Any],
    *,
    expected_authorization_sha256: str,
    issuer_capability: ProofAdmissionAuthorizationIssuerCapability,
) -> TrustedProofAdmissionAuthorization:
    if not isinstance(document, Mapping):
        raise _error("proof_anchor_input_invalid", "authorization", EXIT_USAGE)
    try:
        detached = json.loads(canonical_proof_anchor_bytes(document))
    except (TypeError, ValueError, json.JSONDecodeError):
        raise _error("proof_anchor_contract_invalid", "authorization", EXIT_USAGE) from None
    validation = validate_proof_admission_authorization(detached)
    if not validation.ok:
        raise _error("proof_anchor_contract_invalid", "authorization", EXIT_USAGE)
    if (
        detached["authorization_subject_sha256"]
        != authorization_subject_sha256(detached)
        or detached["authorization_sha256"] != authorization_sha256(detached)
        or detached["authorization_sha256"] != expected_authorization_sha256
    ):
        raise _error(
            "proof_anchor_authorization_binding_mismatch",
            "authorization",
            EXIT_USAGE,
        )
    _require_authorization_capability(issuer_capability, detached)
    frozen = _deep_freeze(detached)
    assert isinstance(frozen, Mapping)
    return TrustedProofAdmissionAuthorization(
        document=frozen,
        expected_authorization_sha256=expected_authorization_sha256,
        issuer_capability=issuer_capability,
    )


def build_proof_admission_anchor_basis(
    *,
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    authority_provider: Callable[[], AuthorityInputSnapshot],
    current_proof_provider: Callable[[], CurrentProofSnapshot],
) -> Mapping[str, Any]:
    admission = evaluate_proof_coverage(
        policy=policy,
        participants=participants,
        authority_provider=authority_provider,
        current_proof_provider=current_proof_provider,
    )
    policy_document = _thaw_mapping(policy.document)
    admission_document = _thaw_mapping(admission)
    if (
        not validate_proof_coverage_policy(policy_document).ok
        or not validate_proof_coverage_admission(admission_document).ok
    ):
        raise _error("proof_anchor_contract_invalid", "basis", EXIT_USAGE)
    basis = finalize_proof_admission_anchor_basis(
        {
            "contract_version": PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION,
            "target": deepcopy(policy_document["target"]),
            "candidate": deepcopy(policy_document["candidate"]),
            "policy": policy_document,
            "admission": admission_document,
            "bindings": {
                "policy_sha256": policy_document["policy_sha256"],
                "coverage_group_sha256": policy_document["coverage_group_sha256"],
                "admission_sha256": admission_document["admission_sha256"],
            },
            "scope": dict(ANCHOR_SCOPE),
            "basis_sha256": "sha256:" + "0" * 64,
        }
    )
    validation = validate_proof_admission_anchor_basis(basis)
    if not validation.ok:
        raise _error("proof_anchor_admission_withheld", "basis")
    _require_sensitive_content_absent(basis)
    return MappingProxyType(basis)


def anchor_proof_admission(
    paths: ProjectPaths,
    *,
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    authority_provider: Callable[[], AuthorityInputSnapshot],
    expected_basis_sha256: str,
    independent_review: TrustedProofAdmissionAuthorization,
    human_gate: TrustedProofAdmissionAuthorization | None,
    operation_capability: object | None = None,
) -> Mapping[str, Any]:
    if not platform_supported():
        raise _error("proof_anchor_platform_unsupported", "preflight", EXIT_USAGE)
    _require_anchor_input_types(
        paths,
        policy,
        participants,
        authority_provider,
        independent_review,
        human_gate,
    )
    target = _thaw_mapping(policy.document)["target"]
    preflight = build_proof_admission_anchor_basis(
        policy=policy,
        participants=participants,
        authority_provider=authority_provider,
        current_proof_provider=lambda: capture_current_proof(paths, target),
    )
    if preflight["basis_sha256"] != expected_basis_sha256:
        raise _error("proof_anchor_currentness_changed", "preflight")
    _require_authorizations(
        policy,
        preflight,
        independent_review,
        human_gate,
    )

    conn = connect_mutation(
        paths,
        exclusive=True,
        operation_capability=operation_capability,
    )
    publication: PublishedProofAnchor | None = None
    mutation_committed = False
    try:
        _require_database_schema_version(conn)
        _require_projection_delivered(conn)
        project_instance_id = _project_instance_id(conn)
        _require_task(conn, str(target["id"]))
        hwm = _event_hwm(conn)
        locked_basis = _build_locked_basis(
            paths,
            conn,
            hwm=hwm,
            policy=policy,
            participants=participants,
            authority_provider=authority_provider,
        )
        if (
            locked_basis["basis_sha256"] != expected_basis_sha256
            or canonical_proof_anchor_bytes(locked_basis)
            != canonical_proof_anchor_bytes(preflight)
        ):
            raise _error("proof_anchor_currentness_changed", "locked")
        _require_live_canaries(
            policy,
            participants,
            locked_basis,
            authority_provider,
        )
        _require_authorizations(
            policy,
            locked_basis,
            independent_review,
            human_gate,
        )

        tombstone = _select_tombstone(
            conn,
            project_instance_id=project_instance_id,
            target=target,
            basis_sha256_value=expected_basis_sha256,
        )
        if tombstone is not None:
            conn.rollback()
            return _exhaustion_result(
                payload=tombstone,
                changed=False,
                idempotent=True,
                mutation_committed=False,
                effects=ANCHOR_EFFECTS_ZERO,
                event_id=exhaustion_event_id(
                    project_instance_id=project_instance_id,
                    target=target,
                    basis_sha256_value=expected_basis_sha256,
                ),
                outbox_id=exhaustion_outbox_id(
                    project_instance_id=project_instance_id,
                    target=target,
                    basis_sha256_value=expected_basis_sha256,
                ),
            )

        chains = _enumerate_anchor_chains(
            paths,
            conn,
            target_id=str(target["id"]),
            basis_sha256_value=expected_basis_sha256,
        )
        valid_chains, corrupt = _classify_chains(chains)
        witnesses = sorted(
            (
                chain[-1]
                for chain in valid_chains
                if chain[-1].generation == MAX_RECOVERY_GENERATIONS
                and chain[-1].health_status == "postcommit_unhealthy"
            ),
            key=lambda item: (item.base_request, item.sequence, item.event_id),
        )
        if witnesses:
            witness = witnesses[0]
            result = _commit_exhaustion(
                paths,
                conn,
                project_instance_id=project_instance_id,
                target=target,
                basis_sha256_value=expected_basis_sha256,
                witness=witness,
            )
            mutation_committed = True
            return result
        if corrupt:
            raise _error(
                "proof_anchor_committed_authority_corrupt",
                "history",
                EXIT_DATA_ERROR,
            )
        if len(valid_chains) > 1:
            raise _error(
                "proof_anchor_parallel_chain_conflict",
                "history",
                EXIT_DATA_ERROR,
            )

        review_document = _authorization_document(independent_review)
        human_document = (
            None if human_gate is None else _authorization_document(human_gate)
        )
        caller_base = base_request_sha256(
            project_instance_id=project_instance_id,
            target=locked_basis["target"],
            candidate=locked_basis["candidate"],
            basis_sha256_value=expected_basis_sha256,
            independent_review_subject_sha256=review_document[
                "authorization_subject_sha256"
            ],
            human_gate_subject_sha256=(
                None
                if human_document is None
                else human_document["authorization_subject_sha256"]
            ),
        )
        generation = 0
        recovery_health: Mapping[str, Any] | None = None
        recovery_predecessor: Mapping[str, Any] | None = None
        if valid_chains:
            chain = valid_chains[0]
            head = chain[-1]
            if caller_base != head.base_request:
                if head.health_status == "postcommit_unhealthy":
                    conn.rollback()
                    return {
                        "status": "proof_anchor_existing_chain_recovery_required",
                        "base_request_sha256": head.base_request,
                        "head_generation": head.generation,
                        "head_health": "postcommit_unhealthy",
                        "required_generation": head.generation + 1,
                        "changed": False,
                        "safe_to_retry_original": False,
                    }
                raise _error("proof_anchor_duplicate_basis_conflict", "history")
            if head.health_status == "healthy":
                _require_replay_bytes(head, review_document, human_document)
                conn.rollback()
                return _anchor_result(
                    status="already_anchored",
                    changed=False,
                    idempotent=True,
                    mutation_committed=False,
                    projection="delivered",
                    health="healthy",
                    effects=ANCHOR_EFFECTS_ZERO,
                    payload=head.payload,
                    evidence_id=str(head.payload["evidence_id"]),
                    outbox_id=proof_anchor_outbox_id(str(head.payload["request_id"])),
                )
            generation = head.generation + 1
            if generation > MAX_RECOVERY_GENERATIONS:
                raise _error(
                    "proof_anchor_recovery_generation_exhausted",
                    "recovery",
                    EXIT_DATA_ERROR,
                )
            _require_recovery_authorizations(head, review_document, human_document)
            recovery_health = deepcopy(head.health)
            recovery_predecessor = _recovery_predecessor(head)

        request_id = proof_anchor_request_id(
            base_request_sha256_value=caller_base,
            anchor_generation=generation,
            recovery_predecessor=recovery_predecessor,
        )
        event_id = proof_anchor_event_id(request_id)
        outbox_id = proof_anchor_outbox_id(request_id)
        if conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone():
            raise _error("proof_anchor_idempotency_conflict", "identity")

        basis_bytes = canonical_proof_anchor_bytes(locked_basis) + b"\n"
        review_bytes = canonical_proof_anchor_bytes(review_document) + b"\n"
        human_bytes = (
            None
            if human_document is None
            else canonical_proof_anchor_bytes(human_document) + b"\n"
        )
        members = [
            _member("basis", "basis.json", basis_bytes),
            _member(
                "independent_review",
                "independent-review.json",
                review_bytes,
            ),
        ]
        if human_bytes is not None:
            members.append(_member("human_gate", "human-gate.json", human_bytes))
        ledger_predecessor = _latest_anchor_ledger_predecessor(conn)
        epoch = {
            "contract_version": PROOF_ADMISSION_ANCHOR_EPOCH_CONTRACT_VERSION,
            "request_id": request_id,
            "base_request_sha256": caller_base,
            "anchor_generation": generation,
            "precommit_hwm": {
                "sequence": hwm,
                "event_id": _event_at_sequence(conn, hwm),
            },
            "ledger_predecessor": ledger_predecessor,
            "recovery_predecessor": deepcopy(recovery_predecessor),
            "epoch_sha256": "sha256:" + "0" * 64,
        }
        projection = dict(ANCHOR_AUTHORIZATION_PROJECTION)
        if human_document is not None:
            projection["human_gate"] = "approved"
        manifest = finalize_proof_admission_anchor(
            {
                "contract_version": PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION,
                "request": {
                    "request_id": request_id,
                    "base_request_sha256": caller_base,
                    "anchor_generation": generation,
                    "recovery": deepcopy(recovery_health),
                },
                "epoch": epoch,
                "target": deepcopy(locked_basis["target"]),
                "candidate": deepcopy(locked_basis["candidate"]),
                "bindings": {
                    "basis_sha256": expected_basis_sha256,
                    "policy_sha256": locked_basis["bindings"]["policy_sha256"],
                    "coverage_group_sha256": locked_basis["bindings"][
                        "coverage_group_sha256"
                    ],
                    "admission_sha256": locked_basis["bindings"]["admission_sha256"],
                    "independent_review_authorization_sha256": review_document[
                        "authorization_sha256"
                    ],
                    "independent_review_subject_sha256": review_document[
                        "authorization_subject_sha256"
                    ],
                    "human_gate_authorization_sha256": (
                        None
                        if human_document is None
                        else human_document["authorization_sha256"]
                    ),
                    "human_gate_subject_sha256": (
                        None
                        if human_document is None
                        else human_document["authorization_subject_sha256"]
                    ),
                },
                "members": members,
                "authorization_projection": projection,
                "handoff": dict(ANCHOR_HANDOFF),
                "effects": dict(ANCHOR_EFFECTS_SUCCESS),
                "anchor_sha256": "sha256:" + "0" * 64,
            }
        )
        if not validate_proof_admission_anchor(manifest).ok:
            raise _error("proof_anchor_contract_invalid", "manifest", EXIT_USAGE)
        manifest_bytes = canonical_proof_anchor_bytes(manifest) + b"\n"
        manifest_sha = manifest_file_sha256(manifest_bytes)
        files = {
            "basis.json": basis_bytes,
            "independent-review.json": review_bytes,
            "evidence-manifest.json": manifest_bytes,
        }
        if human_bytes is not None:
            files["human-gate.json"] = human_bytes
        crash_if_requested("proof_anchor_before_staging")
        try:
            publication = publish_proof_anchor_artifact(
                paths,
                request_id=request_id,
                files=files,
            )
        except FileExistsError:
            raise _error("proof_anchor_orphan_conflict", "store", EXIT_DATA_ERROR) from None
        except (OSError, ValueError, TypeError):
            raise _error("proof_anchor_strict_store_invalid", "store", EXIT_DATA_ERROR) from None

        evidence_id = next_prefixed_id(conn, "evidence", "E")
        crash_if_requested("proof_anchor_after_publish_before_database")
        now = utc_now_iso()
        summary = _evidence_summary(
            manifest=manifest,
            manifest_sha=manifest_sha,
            manifest_size=len(manifest_bytes),
            members=members,
        )
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (
                evidence_id,
                PROOF_ANCHOR_EVIDENCE_TYPE,
                publication.relative_manifest_path,
                json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                now,
            ),
        )
        crash_if_requested("proof_anchor_after_evidence_insert")
        conn.execute(
            """
            INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
            VALUES (?, 'task', ?, ?, ?)
            """,
            (evidence_id, target["id"], PROOF_ANCHOR_LINK_ROLE, now),
        )
        crash_if_requested("proof_anchor_after_link_insert")
        payload = {
            "contract_version": PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION,
            "request_id": request_id,
            "base_request_sha256": caller_base,
            "anchor_generation": generation,
            "basis_sha256": expected_basis_sha256,
            "anchor_sha256": manifest["anchor_sha256"],
            "manifest_file_sha256": manifest_sha,
            "evidence_id": evidence_id,
        }
        if not validate_proof_anchor_event(payload).ok:
            raise _error("proof_anchor_contract_invalid", "event", EXIT_USAGE)
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=PROOF_ANCHOR_EVENT_TYPE,
            entity_type="task",
            entity_id=str(target["id"]),
            payload=payload,
            event_id=event_id,
            outbox_id=outbox_id,
            created_at=now,
        )
        crash_if_requested("proof_anchor_after_event_before_commit")

        def precommit_guard() -> None:
            final_hwm = _event_hwm(conn)
            final_basis = _build_locked_basis(
                paths,
                conn,
                hwm=final_hwm,
                policy=policy,
                participants=participants,
                authority_provider=authority_provider,
            )
            _require_live_canaries(
                policy,
                participants,
                final_basis,
                authority_provider,
            )
            _require_authorizations(
                policy,
                final_basis,
                independent_review,
                human_gate,
            )
            if canonical_proof_anchor_bytes(final_basis) != canonical_proof_anchor_bytes(
                locked_basis
            ):
                raise _error("proof_anchor_currentness_changed", "final_guard")
            if recovery_health is not None:
                refreshed = _enumerate_anchor_chains(
                    paths,
                    conn,
                    target_id=str(target["id"]),
                    basis_sha256_value=expected_basis_sha256,
                    exclude_event_id=event_id,
                )
                refreshed_valid, refreshed_corrupt = _classify_chains(refreshed)
                refreshed_head = (
                    refreshed_valid[0][-1]
                    if not refreshed_corrupt and len(refreshed_valid) == 1
                    else None
                )
                refreshed_predecessor = (
                    None if refreshed_head is None else _recovery_predecessor(refreshed_head)
                )
                refreshed_request_id = (
                    None
                    if refreshed_predecessor is None
                    else proof_anchor_request_id(
                        base_request_sha256_value=caller_base,
                        anchor_generation=generation,
                        recovery_predecessor=refreshed_predecessor,
                    )
                )
                if (
                    refreshed_corrupt
                    or len(refreshed_valid) != 1
                    or refreshed_head is None
                    or canonical_proof_anchor_bytes(refreshed_head.health)
                    != canonical_proof_anchor_bytes(recovery_health)
                    or refreshed_predecessor != recovery_predecessor
                    or refreshed_request_id != request_id
                    or manifest["request"]["recovery"] != refreshed_head.health
                    or manifest["epoch"]["recovery_predecessor"]
                    != refreshed_predecessor
                    or payload["request_id"] != refreshed_request_id
                ):
                    raise _error(
                        "proof_anchor_recovery_predecessor_changed",
                        "final_guard",
                    )
            health = assess_proof_anchor_artifact(
                paths,
                request_id=request_id,
                predecessor_event_id=event_id,
                anchor_generation=generation,
                expected_anchor_sha256=str(manifest["anchor_sha256"]),
                expected_manifest_file_sha256=manifest_sha,
                expected_manifest_size=len(manifest_bytes),
                expected_members=tuple(members),
            )
            if not health.healthy:
                raise _error("proof_anchor_strict_store_invalid", "final_guard", EXIT_DATA_ERROR)

        def postcommit_guard() -> None:
            health = assess_proof_anchor_artifact(
                paths,
                request_id=request_id,
                predecessor_event_id=event_id,
                anchor_generation=generation,
                expected_anchor_sha256=str(manifest["anchor_sha256"]),
                expected_manifest_file_sha256=manifest_sha,
                expected_manifest_size=len(manifest_bytes),
                expected_members=tuple(members),
            )
            if not health.healthy:
                raise ProofAnchorError(
                    "Committed proof anchor is unhealthy.",
                    code="proof_anchor_postcommit_unhealthy",
                    exit_code=EXIT_DATA_ERROR,
                    details={
                        "mutation_committed": True,
                        "safe_to_retry_original": False,
                        "status": "postcommit_unhealthy",
                        "health_sha256": health.health["health_sha256"],
                        "recovery_action": (
                            "new bounded recovery request after fresh live evaluation "
                            "and authorization"
                        ),
                    },
                )

        assert isinstance(conn, MutationConnection)
        conn._precommit_guard = precommit_guard
        conn._postcommit_guard = postcommit_guard
        conn.commit()
        mutation_committed = True
        projection = conn.projection_result
        return _anchor_result(
            status="anchored",
            changed=True,
            idempotent=False,
            mutation_committed=True,
            projection=str(projection.projection),
            health="healthy",
            effects=ANCHOR_EFFECTS_SUCCESS,
            payload=payload,
            evidence_id=evidence_id,
            outbox_id=outbox_id,
        )
    except BaseException:
        mutation_committed = mutation_committed or bool(
            getattr(conn, "_authoritative_commit_completed", False)
        )
        if conn.in_transaction:
            conn.rollback()
        if publication is not None and not mutation_committed:
            remove_published_proof_anchor(publication)
        raise
    finally:
        conn.close()


def _build_locked_basis(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    hwm: int,
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    authority_provider: Callable[[], AuthorityInputSnapshot],
) -> Mapping[str, Any]:
    target = _thaw_mapping(policy.document)["target"]
    return build_proof_admission_anchor_basis(
        policy=policy,
        participants=participants,
        authority_provider=authority_provider,
        current_proof_provider=lambda: capture_current_proof_in_snapshot(
            paths,
            conn,
            target,
            hwm=hwm,
        ),
    )


def _require_live_canaries(
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    basis: Mapping[str, Any],
    authority_provider: Callable[[], AuthorityInputSnapshot],
) -> None:
    try:
        snapshot = authority_provider()
        if type(snapshot) is not AuthorityInputSnapshot:
            raise TypeError
        resolution = snapshot.resolve()
        if not validate_authority_surface_resolution(resolution).ok:
            raise ValueError
        union = merge_authority_canaries(
            merge_authority_canaries(
                snapshot.bootstrap_profile["canary_contract"],
                snapshot.base_canary,
            ),
            snapshot.candidate_canary,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        raise _error("proof_anchor_live_canary_unresolved", "canary") from None
    policy_document = _thaw_mapping(policy.document)
    _require_participant_boundary(policy_document, participants, basis)
    if (
        authority_document_sha256(resolution)
        != policy_document["authority_bindings"][
            "authority_surface_resolution_sha256"
        ]
        or authority_document_sha256(union)
        != policy_document["authority_bindings"]["canary_union_sha256"]
        or basis["candidate"] != policy_document["candidate"]
    ):
        raise _error("proof_anchor_live_identity_mismatch", "canary")
    by_id: dict[str, list[Mapping[str, Any]]] = {}
    for item in union["items"]:
        by_id.setdefault(str(item["id"]), []).append(item)
    observations = {
        (str(item.get("kind")), str(item.get("canary_id"))): item
        for item in basis["admission"]["role_observations"]
    }
    for requirement in policy_document["required_roles"]:
        if requirement["kind"] != "authority_canary":
            if requirement["expected_execution"]["spawn_vector_sha256"] is None:
                raise _error("proof_anchor_live_identity_mismatch", "canary")
            continue
        canary_id = requirement["canary_id"]
        matches = by_id.get(str(canary_id), [])
        if (
            canary_id is None
            or len(matches) != 1
            or canary_item_sha256(matches[0]) != requirement["canary_item_sha256"]
            or ("authority_canary", str(canary_id)) not in observations
            or requirement["expected_execution"]["spawn_vector_sha256"] is None
        ):
            raise _error("proof_anchor_live_canary_unresolved", "canary")


def _require_participant_boundary(
    policy: Mapping[str, Any],
    participants: Sequence[ProofCoverageParticipant],
    basis: Mapping[str, Any],
) -> None:
    candidate = policy["candidate"]
    candidate_core = {
        "commit_oid": candidate["commit_oid"],
        "tree_oid": candidate["tree_oid"],
    }
    for participant in participants:
        if (
            participant.spec.get("candidate") != candidate
            or {
                "commit_oid": participant.authority_resolution.get("candidate", {}).get(
                    "commit_oid"
                ),
                "tree_oid": participant.authority_resolution.get("candidate", {}).get(
                    "tree_oid"
                ),
            }
            != candidate_core
            or participant.prepared.binding.get("repository", {}).get("candidate")
            != candidate
            or any(
                check.get("spawn_vector_sha256") is None
                for check in participant.prepared.binding.get("checks", ())
            )
        ):
            raise _error("proof_anchor_live_identity_mismatch", "participant")
    expected_participant_facts = {
        "aggregate_output_commitment_status": "committed",
        "aggregate_reuse_disposition": "eligible",
        "aggregate_anchoring_eligible": True,
        "aggregate_positive_proof_handoff": "candidate",
    }
    for public in basis["admission"]["participants"]:
        if any(
            public.get(field) != expected
            for field, expected in expected_participant_facts.items()
        ):
            raise _error("proof_anchor_promotion_withheld", "participant")


def _require_authorizations(
    policy: TrustedCoveragePolicy,
    basis: Mapping[str, Any],
    independent_review: TrustedProofAdmissionAuthorization,
    human_gate: TrustedProofAdmissionAuthorization | None,
) -> None:
    policy_document = _thaw_mapping(policy.document)
    review = _authorization_document(independent_review)
    _require_one_authorization(
        independent_review,
        review,
        kind="independent_review",
        policy=policy_document,
        basis=basis,
    )
    required = policy_document["authorization_requirements"]["human_gate"] == "required"
    if required and human_gate is None:
        raise _error("proof_anchor_human_gate_required", "authorization")
    if not required and human_gate is not None:
        raise _error(
            "proof_anchor_authorization_binding_mismatch",
            "authorization",
        )
    if human_gate is not None:
        human = _authorization_document(human_gate)
        _require_one_authorization(
            human_gate,
            human,
            kind="human_gate",
            policy=policy_document,
            basis=basis,
        )
        if human["authorization_sha256"] == review["authorization_sha256"]:
            raise _error(
                "proof_anchor_authorization_binding_mismatch",
                "authorization",
            )


def _require_one_authorization(
    trusted: TrustedProofAdmissionAuthorization,
    document: Mapping[str, Any],
    *,
    kind: str,
    policy: Mapping[str, Any],
    basis: Mapping[str, Any],
) -> None:
    validation = validate_proof_admission_authorization(document)
    if not validation.ok:
        raise _error("proof_anchor_contract_invalid", "authorization", EXIT_USAGE)
    _require_authorization_capability(trusted.issuer_capability, document)
    if (
        document["authorization_sha256"]
        != trusted.expected_authorization_sha256
        or document["authorization_sha256"] != authorization_sha256(document)
        or document["authorization_subject_sha256"]
        != authorization_subject_sha256(document)
        or document["authorization_kind"] != kind
        or document["authority"]["candidate_controlled"] is not False
        or document["target"] != basis["target"]
        or document["candidate"] != basis["candidate"]
        or document["scope"] != ANCHOR_SCOPE
        or document["bindings"]
        != {
            "basis_sha256": basis["basis_sha256"],
            "policy_sha256": basis["bindings"]["policy_sha256"],
            "coverage_group_sha256": basis["bindings"]["coverage_group_sha256"],
            "admission_sha256": basis["bindings"]["admission_sha256"],
            "producer_sha256": policy["producer"]["producer_sha256"],
        }
    ):
        raise _error(
            "proof_anchor_authorization_binding_mismatch",
            "authorization",
        )
    if document["authority"]["actor_id"] == policy["producer"]["producer_id"]:
        raise _error("proof_anchor_review_independence_invalid", "authorization")
    decision = document["decision"]
    if decision == "rejected":
        raise _error("proof_anchor_review_rejected", "authorization")
    if decision == "inconclusive":
        raise _error("proof_anchor_review_inconclusive", "authorization")
    if kind == "independent_review" and (
        document["authority"]["actor_kind"] not in {"human", "agent"}
        or document["review"]["findings"]["high"] != 0
        or document["review"]["findings"]["medium"] != 0
    ):
        raise _error("proof_anchor_review_independence_invalid", "authorization")
    if kind == "human_gate" and document["authority"]["actor_kind"] != "human":
        raise _error("proof_anchor_review_independence_invalid", "authorization")
    _require_sensitive_content_absent(document)


def _require_authorization_capability(
    capability: ProofAdmissionAuthorizationIssuerCapability,
    document: Mapping[str, Any],
) -> None:
    if type(capability) is not ProofAdmissionAuthorizationIssuerCapability:
        raise _error(
            "proof_anchor_authorization_binding_mismatch",
            "authorization",
            EXIT_USAGE,
        )
    with _AUTHORIZATION_LOCK:
        registered = _AUTHORIZATION_REGISTRY.get(id(capability))
    authority = document["authority"]
    expected = (
        capability,
        document["authorization_kind"],
        authority["actor_kind"],
        authority["actor_id"],
        authority["recorder_kind"],
        authority["recorder_id"],
        authority["source_kind"],
        authority["source_ref"],
        authority["candidate_controlled"],
    )
    if registered != expected or capability._issuer is not _AUTHORIZATION_ISSUER:
        raise _error(
            "proof_anchor_authorization_binding_mismatch",
            "authorization",
            EXIT_USAGE,
        )


def _enumerate_anchor_chains(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    target_id: str,
    basis_sha256_value: str,
    exclude_event_id: str | None = None,
    row_limit: int | None = None,
) -> list[list[_CommittedAnchor] | None]:
    sql = """
        SELECT id, sequence, payload_json
        FROM events INDEXED BY idx_events_entity
        WHERE entity_type = 'task'
          AND entity_id = ?
          AND event_type = ?
          AND json_extract(payload_json, '$.contract_version') = ?
          AND json_extract(payload_json, '$.basis_sha256') = ?
        ORDER BY sequence, id
        """
    params: tuple[Any, ...] = (
        target_id,
        PROOF_ANCHOR_EVENT_TYPE,
        PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION,
        basis_sha256_value,
    )
    if row_limit is not None:
        sql += " LIMIT ?"
        params += (row_limit,)
    rows = conn.execute(sql, params).fetchall()
    if row_limit is not None and len(rows) >= row_limit:
        raise ProofAnchorAuthorityCapacityError
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        if exclude_event_id is not None and str(row["id"]) == exclude_event_id:
            continue
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            return [None]
        groups.setdefault(str(payload.get("base_request_sha256")), []).append(row)
    results: list[list[_CommittedAnchor] | None] = []
    for base in sorted(groups):
        chain: list[_CommittedAnchor] = []
        malformed = False
        for row in groups[base]:
            committed = _read_committed_anchor(paths, conn, row)
            if committed is None:
                malformed = True
                break
            chain.append(committed)
        chain.sort(key=lambda item: item.generation)
        generations = [item.generation for item in chain]
        if malformed or generations != list(range(len(chain))):
            results.append(None)
            continue
        for index, item in enumerate(chain):
            if index == 0:
                valid_recovery = (
                    item.summary["recovery"] is None
                )
            else:
                previous = chain[index - 1]
                recovery_health = item.summary["recovery"]
                valid_recovery = isinstance(recovery_health, Mapping) and (
                    validate_proof_anchor_health(recovery_health).ok
                    and canonical_proof_anchor_bytes(recovery_health)
                    == canonical_proof_anchor_bytes(previous.health)
                    and _recovery_predecessor(previous)
                    == _health_recovery_predecessor(recovery_health)
                )
            if not valid_recovery:
                malformed = True
                break
        results.append(None if malformed else chain)
    return results


def _read_committed_anchor(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    row: sqlite3.Row,
) -> _CommittedAnchor | None:
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        return None
    if (
        not validate_proof_anchor_event(payload).ok
        or str(row["id"]) != proof_anchor_event_id(str(payload["request_id"]))
    ):
        return None
    evidence = conn.execute(
        "SELECT id, type, path, summary FROM evidence WHERE id = ?",
        (payload["evidence_id"],),
    ).fetchone()
    if evidence is None or str(evidence["type"]) != PROOF_ANCHOR_EVIDENCE_TYPE:
        return None
    link_count = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM evidence_links
            WHERE evidence_id = ? AND target_type = 'task'
              AND target_id = ? AND link_role = ?
            """,
            (payload["evidence_id"], row_target_id(conn, str(row["id"])), PROOF_ANCHOR_LINK_ROLE),
        ).fetchone()[0]
    )
    outbox = conn.execute(
        "SELECT id, event_id, sink, idempotency_key FROM outbox_records WHERE event_id = ?",
        (row["id"],),
    ).fetchone()
    if (
        link_count != 1
        or outbox is None
        or str(outbox["id"]) != proof_anchor_outbox_id(str(payload["request_id"]))
        or str(outbox["event_id"]) != str(row["id"])
        or str(outbox["sink"]) != "jsonl"
        or str(outbox["idempotency_key"]) != f"jsonl:{row['id']}"
    ):
        return None
    try:
        summary = json.loads(str(evidence["summary"]))
    except json.JSONDecodeError:
        return None
    if not _summary_matches_payload(summary, payload):
        return None
    expected_path = (
        ".project-loop/evidence/proof-admission-anchors/"
        f"{str(payload['request_id'])[3:].lower()}/evidence-manifest.json"
    )
    if str(evidence["path"]) != expected_path:
        return None
    assessment = assess_proof_anchor_artifact(
        paths,
        request_id=str(payload["request_id"]),
        predecessor_event_id=str(row["id"]),
        anchor_generation=int(payload["anchor_generation"]),
        expected_anchor_sha256=str(payload["anchor_sha256"]),
        expected_manifest_file_sha256=str(payload["manifest_file_sha256"]),
        expected_manifest_size=int(summary["manifest_size_bytes"]),
        expected_members=tuple(summary["members"]),
    )
    if assessment.manifest is not None:
        manifest = assessment.manifest
        if (
            manifest["request"]["request_id"] != payload["request_id"]
            or manifest["request"]["base_request_sha256"]
            != payload["base_request_sha256"]
            or manifest["request"]["anchor_generation"]
            != payload["anchor_generation"]
            or manifest["bindings"]["basis_sha256"] != payload["basis_sha256"]
            or manifest["anchor_sha256"] != payload["anchor_sha256"]
        ):
            return None
    return _CommittedAnchor(
        event_id=str(row["id"]),
        sequence=int(row["sequence"]),
        payload=payload,
        evidence=dict(evidence),
        summary=summary,
        health_status=assessment.status,
        health=assessment.health,
        manifest=assessment.manifest,
        members=assessment.member_documents,
    )


def _classify_chains(
    chains: Sequence[list[_CommittedAnchor] | None],
) -> tuple[list[list[_CommittedAnchor]], bool]:
    corrupt = any(chain is None for chain in chains)
    valid = [chain for chain in chains if chain is not None]
    return valid, corrupt


def _select_tombstone(
    conn: sqlite3.Connection,
    *,
    project_instance_id: str,
    target: Mapping[str, Any],
    basis_sha256_value: str,
) -> Mapping[str, Any] | None:
    rows = conn.execute(
        """
        SELECT id, payload_json FROM events INDEXED BY idx_events_entity
        WHERE entity_type = 'task' AND entity_id = ? AND event_type = ?
          AND json_extract(payload_json, '$.contract_version') = ?
          AND json_extract(payload_json, '$.basis_sha256') = ?
        ORDER BY sequence DESC, id DESC
        """,
        (
            target["id"],
            PROOF_ANCHOR_EXHAUSTION_EVENT_TYPE,
            PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION,
            basis_sha256_value,
        ),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise _error("proof_anchor_committed_authority_corrupt", "tombstone", EXIT_DATA_ERROR)
    row = rows[0]
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        raise _error(
            "proof_anchor_committed_authority_corrupt",
            "tombstone",
            EXIT_DATA_ERROR,
        ) from None
    expected_event = exhaustion_event_id(
        project_instance_id=project_instance_id,
        target=target,
        basis_sha256_value=basis_sha256_value,
    )
    expected_outbox = exhaustion_outbox_id(
        project_instance_id=project_instance_id,
        target=target,
        basis_sha256_value=basis_sha256_value,
    )
    outbox = conn.execute(
        "SELECT id, idempotency_key FROM outbox_records WHERE event_id = ?",
        (row["id"],),
    ).fetchone()
    if (
        str(row["id"]) != expected_event
        or not validate_proof_anchor_exhaustion_event(payload).ok
        or outbox is None
        or str(outbox["id"]) != expected_outbox
        or str(outbox["idempotency_key"]) != f"jsonl:{expected_event}"
    ):
        raise _error("proof_anchor_committed_authority_corrupt", "tombstone", EXIT_DATA_ERROR)
    return payload


def _commit_exhaustion(
    paths: ProjectPaths,
    conn: MutationConnection,
    *,
    project_instance_id: str,
    target: Mapping[str, Any],
    basis_sha256_value: str,
    witness: _CommittedAnchor,
) -> Mapping[str, Any]:
    event_id = exhaustion_event_id(
        project_instance_id=project_instance_id,
        target=target,
        basis_sha256_value=basis_sha256_value,
    )
    outbox_id = exhaustion_outbox_id(
        project_instance_id=project_instance_id,
        target=target,
        basis_sha256_value=basis_sha256_value,
    )
    payload = {
        "contract_version": PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION,
        "base_request_sha256": witness.payload["base_request_sha256"],
        "anchor_generation": 3,
        "basis_sha256": basis_sha256_value,
        "anchor_sha256": witness.payload["anchor_sha256"],
        "manifest_file_sha256": witness.payload["manifest_file_sha256"],
        "exhausted_request_id": witness.payload["request_id"],
        "exhausted_anchor_event_id": witness.event_id,
        "health_sha256": witness.health["health_sha256"],
        "disposition": "human_design_required",
    }
    if not validate_proof_anchor_exhaustion_event(payload).ok:
        raise _error("proof_anchor_contract_invalid", "tombstone", EXIT_USAGE)

    def guard() -> None:
        chains = _enumerate_anchor_chains(
            paths,
            conn,
            target_id=str(target["id"]),
            basis_sha256_value=basis_sha256_value,
        )
        valid, _corrupt = _classify_chains(chains)
        candidates = sorted(
            (
                chain[-1]
                for chain in valid
                if chain[-1].generation == 3
                and chain[-1].health_status == "postcommit_unhealthy"
            ),
            key=lambda item: (item.base_request, item.sequence, item.event_id),
        )
        candidate = candidates[0] if candidates else None
        if (
            not candidates
            or candidate is None
            or candidate.event_id != witness.event_id
            or candidate.payload["request_id"] != witness.payload["request_id"]
            or candidate.payload["anchor_sha256"] != witness.payload["anchor_sha256"]
            or candidate.payload["manifest_file_sha256"]
            != witness.payload["manifest_file_sha256"]
            or candidate.health["health_sha256"] != witness.health["health_sha256"]
        ):
            raise _error("proof_anchor_recovery_predecessor_changed", "tombstone")

    conn._precommit_guard = guard
    append_event(
        conn=conn,
        events_path=paths.events_path,
        event_type=PROOF_ANCHOR_EXHAUSTION_EVENT_TYPE,
        entity_type="task",
        entity_id=str(target["id"]),
        payload=payload,
        event_id=event_id,
        outbox_id=outbox_id,
    )
    conn.commit()
    return _exhaustion_result(
        payload=payload,
        changed=True,
        idempotent=False,
        mutation_committed=True,
        effects=EXHAUSTION_EFFECTS_SUCCESS,
        event_id=event_id,
        outbox_id=outbox_id,
    )


def _require_replay_bytes(
    head: _CommittedAnchor,
    review: Mapping[str, Any],
    human: Mapping[str, Any] | None,
) -> None:
    if head.manifest is None:
        raise _error("proof_anchor_idempotency_conflict", "replay", EXIT_DATA_ERROR)
    expected = {
        "independent_review": canonical_proof_anchor_bytes(review) + b"\n",
    }
    if human is not None:
        expected["human_gate"] = canonical_proof_anchor_bytes(human) + b"\n"
    for role, content in expected.items():
        if head.members.get(role) != json.loads(content):
            raise _error("proof_anchor_idempotency_conflict", "replay")


def _require_recovery_authorizations(
    head: _CommittedAnchor,
    review: Mapping[str, Any],
    human: Mapping[str, Any] | None,
) -> None:
    bindings = head.summary["bindings"]
    if (
        review["authorization_subject_sha256"]
        != bindings["independent_review_subject_sha256"]
        or review["authorization_sha256"]
        == bindings["independent_review_authorization_sha256"]
    ):
        raise _error("proof_anchor_authorization_binding_mismatch", "recovery")
    expected_human_subject = bindings["human_gate_subject_sha256"]
    expected_human_authorization = bindings["human_gate_authorization_sha256"]
    if human is None:
        if expected_human_subject is not None:
            raise _error("proof_anchor_authorization_binding_mismatch", "recovery")
    elif (
        human["authorization_subject_sha256"] != expected_human_subject
        or human["authorization_sha256"] == expected_human_authorization
    ):
        raise _error("proof_anchor_authorization_binding_mismatch", "recovery")


def _evidence_summary(
    *,
    manifest: Mapping[str, Any],
    manifest_sha: str,
    manifest_size: int,
    members: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "contract_version": "proof-admission-anchor-evidence/v1",
        "request_id": manifest["request"]["request_id"],
        "base_request_sha256": manifest["request"]["base_request_sha256"],
        "anchor_generation": manifest["request"]["anchor_generation"],
        "basis_sha256": manifest["bindings"]["basis_sha256"],
        "anchor_sha256": manifest["anchor_sha256"],
        "manifest_file_sha256": manifest_sha,
        "manifest_size_bytes": manifest_size,
        "recovery": deepcopy(manifest["request"]["recovery"]),
        "bindings": deepcopy(manifest["bindings"]),
        "members": deepcopy(list(members)),
    }


def _summary_matches_payload(
    summary: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> bool:
    expected_fields = {
        "contract_version",
        "request_id",
        "base_request_sha256",
        "anchor_generation",
        "basis_sha256",
        "anchor_sha256",
        "manifest_file_sha256",
        "manifest_size_bytes",
        "recovery",
        "bindings",
        "members",
    }
    if (
        set(summary) != expected_fields
        or summary.get("contract_version") != "proof-admission-anchor-evidence/v1"
        or not all(
            summary.get(field) == payload.get(field)
            for field in (
                "request_id",
                "base_request_sha256",
                "anchor_generation",
                "basis_sha256",
                "anchor_sha256",
                "manifest_file_sha256",
            )
        )
    ):
        return False
    manifest_size = summary.get("manifest_size_bytes")
    if (
        isinstance(manifest_size, bool)
        or not isinstance(manifest_size, int)
        or not 1 <= manifest_size <= MAX_ANCHOR_BYTES + 1
    ):
        return False
    bindings = summary.get("bindings")
    expected_binding_fields = {
        "basis_sha256",
        "policy_sha256",
        "coverage_group_sha256",
        "admission_sha256",
        "independent_review_authorization_sha256",
        "independent_review_subject_sha256",
        "human_gate_authorization_sha256",
        "human_gate_subject_sha256",
    }
    if not isinstance(bindings, Mapping) or set(bindings) != expected_binding_fields:
        return False
    if bindings.get("basis_sha256") != payload.get("basis_sha256"):
        return False
    if (
        bindings.get("human_gate_authorization_sha256") is None
    ) != (bindings.get("human_gate_subject_sha256") is None):
        return False
    for field_name, value in bindings.items():
        if field_name.startswith("human_gate_") and value is None:
            continue
        if not _is_sha256(value):
            return False
    members = summary.get("members")
    expected_members = [
        ("basis", "basis.json"),
        ("independent_review", "independent-review.json"),
    ]
    if bindings.get("human_gate_subject_sha256") is not None:
        expected_members.append(("human_gate", "human-gate.json"))
    if not isinstance(members, list) or len(members) != len(expected_members):
        return False
    for member, expected in zip(members, expected_members, strict=True):
        if (
            not isinstance(member, Mapping)
            or set(member) != {"role", "storage_name", "size_bytes", "file_sha256"}
            or (member.get("role"), member.get("storage_name")) != expected
            or isinstance(member.get("size_bytes"), bool)
            or not isinstance(member.get("size_bytes"), int)
            or not 1 <= member["size_bytes"] <= MAX_BASIS_BYTES
            or not _is_sha256(member.get("file_sha256"))
        ):
            return False
    generation = payload.get("anchor_generation")
    recovery = summary.get("recovery")
    if generation == 0:
        return recovery is None
    return bool(
        isinstance(generation, int)
        and isinstance(recovery, Mapping)
        and validate_proof_anchor_health(recovery).ok
        and recovery.get("finding_codes")
        and isinstance(recovery.get("predecessor"), Mapping)
        and recovery["predecessor"].get("anchor_generation") == generation - 1
    )


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _recovery_predecessor(anchor: _CommittedAnchor) -> dict[str, Any]:
    return {
        "request_id": anchor.payload["request_id"],
        "anchor_generation": anchor.generation,
        "event_id": anchor.event_id,
        "anchor_sha256": anchor.payload["anchor_sha256"],
        "health_sha256": anchor.health["health_sha256"],
    }


def _health_recovery_predecessor(health: Mapping[str, Any]) -> dict[str, Any] | None:
    predecessor = health.get("predecessor")
    if not isinstance(predecessor, Mapping):
        return None
    return {
        "request_id": predecessor.get("request_id"),
        "anchor_generation": predecessor.get("anchor_generation"),
        "event_id": predecessor.get("event_id"),
        "anchor_sha256": predecessor.get("anchor_sha256"),
        "health_sha256": health.get("health_sha256"),
    }


def _anchor_result(
    *,
    status: str,
    changed: bool,
    idempotent: bool,
    mutation_committed: bool,
    projection: str,
    health: str,
    effects: Mapping[str, Any],
    payload: Mapping[str, Any],
    evidence_id: str,
    outbox_id: str,
) -> Mapping[str, Any]:
    result = {
        "contract_version": PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION,
        "ok": True,
        "status": status,
        "changed": changed,
        "idempotent": idempotent,
        "mutation_committed": mutation_committed,
        "safe_to_retry_original": False,
        "request_id": payload["request_id"],
        "base_request_sha256": payload["base_request_sha256"],
        "anchor_generation": payload["anchor_generation"],
        "basis_sha256": payload["basis_sha256"],
        "anchor_sha256": payload["anchor_sha256"],
        "manifest_file_sha256": payload["manifest_file_sha256"],
        "evidence_id": evidence_id,
        "event_id": proof_anchor_event_id(str(payload["request_id"])),
        "outbox_id": outbox_id,
        "projection": projection,
        "health": health,
        "effects": dict(effects),
        "recovery_action": None,
    }
    if not validate_proof_admission_anchor_result(result).ok:
        raise _error("proof_anchor_contract_invalid", "result", EXIT_USAGE)
    return result


def _exhaustion_result(
    *,
    payload: Mapping[str, Any],
    changed: bool,
    idempotent: bool,
    mutation_committed: bool,
    effects: Mapping[str, Any],
    event_id: str,
    outbox_id: str,
) -> Mapping[str, Any]:
    result = {
        "contract_version": PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION,
        "ok": False,
        "status": "proof_anchor_recovery_generation_exhausted",
        "changed": changed,
        "idempotent": idempotent,
        "mutation_committed": mutation_committed,
        "safe_to_retry_original": False,
        "request_id": payload["exhausted_request_id"],
        "base_request_sha256": payload["base_request_sha256"],
        "anchor_generation": 3,
        "basis_sha256": payload["basis_sha256"],
        "anchor_sha256": payload["anchor_sha256"],
        "manifest_file_sha256": payload["manifest_file_sha256"],
        "evidence_id": None,
        "event_id": event_id,
        "outbox_id": outbox_id,
        "projection": "delivered" if mutation_committed else "not_applicable",
        "health": "postcommit_unhealthy",
        "effects": dict(effects),
        "recovery_action": "human_design_required",
        "disposition": "human_design_required",
    }
    if not validate_proof_admission_anchor_result(result).ok:
        raise _error("proof_anchor_contract_invalid", "result", EXIT_USAGE)
    return result


def _member(role: str, storage_name: str, content: bytes) -> dict[str, Any]:
    return {
        "role": role,
        "storage_name": storage_name,
        "size_bytes": len(content),
        "file_sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
    }


def _require_projection_delivered(conn: sqlite3.Connection) -> None:
    count = int(
        conn.execute(
            "SELECT COUNT(*) FROM outbox_records WHERE status != 'delivered'"
        ).fetchone()[0]
    )
    if count:
        raise ProofAnchorError(
            "A pre-existing JSONL projection is pending.",
            code="audit_projection_pending",
            exit_code=EXIT_RECOVERABLE_PENDING,
            details={
                "mutation_committed": False,
                "safe_to_retry_original": False,
                "safe_next_action": "Run `pcl audit flush --json` before retrying.",
            },
        )


def _require_database_schema_version(conn: sqlite3.Connection) -> None:
    try:
        row = conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.DatabaseError:
        raise _error("proof_anchor_input_invalid", "schema_version", EXIT_USAGE) from None
    if row is None or str(row["value"]) != PROOF_ANCHOR_DATABASE_SCHEMA_VERSION:
        raise _error("proof_anchor_input_invalid", "schema_version", EXIT_USAGE)


def _project_instance_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events WHERE event_type = 'project_initialized'
        ORDER BY sequence LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise _error("proof_anchor_live_identity_mismatch", "project", EXIT_DATA_ERROR)
    return hashlib.sha256(canonical_event_bytes(canonical_event_record(row))).hexdigest()


def _require_task(conn: sqlite3.Connection, task_id: str) -> None:
    if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
        raise _error("proof_anchor_live_identity_mismatch", "task", EXIT_DATA_ERROR)


def _event_hwm(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM events").fetchone()[0])


def _event_at_sequence(conn: sqlite3.Connection, sequence: int) -> str | None:
    if sequence == 0:
        return None
    row = conn.execute("SELECT id FROM events WHERE sequence = ?", (sequence,)).fetchone()
    return None if row is None else str(row["id"])


def _latest_anchor_ledger_predecessor(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, payload_json FROM events
        WHERE event_type = ? ORDER BY sequence DESC, id DESC LIMIT 1
        """,
        (PROOF_ANCHOR_EVENT_TYPE,),
    ).fetchone()
    if row is None:
        return {"event_id": None, "anchor_sha256": None}
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        raise _error("proof_anchor_committed_authority_corrupt", "ledger", EXIT_DATA_ERROR) from None
    if not validate_proof_anchor_event(payload).ok:
        raise _error("proof_anchor_committed_authority_corrupt", "ledger", EXIT_DATA_ERROR)
    return {"event_id": str(row["id"]), "anchor_sha256": payload["anchor_sha256"]}


def row_target_id(conn: sqlite3.Connection, event_id: str) -> str:
    row = conn.execute("SELECT entity_id FROM events WHERE id = ?", (event_id,)).fetchone()
    return "" if row is None else str(row["entity_id"])


def _require_sensitive_content_absent(value: Mapping[str, Any]) -> None:
    redacted, changed = redact_value(_thaw_mapping(value))
    del redacted
    if changed:
        raise _error("proof_anchor_sensitive_content_detected", "disclosure", EXIT_USAGE)


def _require_anchor_input_types(
    paths: ProjectPaths,
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    authority_provider: Callable[[], AuthorityInputSnapshot],
    independent_review: TrustedProofAdmissionAuthorization,
    human_gate: TrustedProofAdmissionAuthorization | None,
) -> None:
    if (
        type(paths) is not ProjectPaths
        or type(policy) is not TrustedCoveragePolicy
        or not isinstance(participants, Sequence)
        or isinstance(participants, (str, bytes, bytearray))
        or any(type(item) is not ProofCoverageParticipant for item in participants)
        or not callable(authority_provider)
        or type(independent_review) is not TrustedProofAdmissionAuthorization
        or (
            human_gate is not None
            and type(human_gate) is not TrustedProofAdmissionAuthorization
        )
    ):
        raise _error("proof_anchor_input_invalid", "input", EXIT_USAGE)


def _authorization_document(
    trusted: TrustedProofAdmissionAuthorization,
) -> dict[str, Any]:
    return _thaw_mapping(trusted.document)


def _thaw_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    thawed = _thaw(value)
    if not isinstance(thawed, dict):
        raise TypeError("Expected a mapping.")
    return thawed


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _error(code: str, phase: str, exit_code: int = 1) -> ProofAnchorError:
    return ProofAnchorError(
        "Proof-admission anchor operation failed.",
        code=code,
        exit_code=exit_code,
        details={"phase": phase, "effects": dict(ANCHOR_EFFECTS_ZERO)},
    )


__all__ = [
    "PROOF_ANCHOR_EVIDENCE_TYPE",
    "PROOF_ANCHOR_EVENT_TYPE",
    "PROOF_ANCHOR_EXHAUSTION_EVENT_TYPE",
    "PROOF_ANCHOR_LINK_ROLE",
    "ProofAdmissionAuthorizationIssuerCapability",
    "ProofAnchorAuthorityCapacityError",
    "ProofAnchorDriftAuthorityResolution",
    "ProofAnchorError",
    "resolve_proof_anchor_drift_authority",
    "TrustedProofAdmissionAuthorization",
    "anchor_proof_admission",
    "bind_proof_admission_authorization",
    "build_proof_admission_anchor_basis",
    "committed_proof_anchor_tombstone_valid",
    "inspect_committed_proof_anchor",
    "issue_proof_admission_authorization_issuer_capability",
]
