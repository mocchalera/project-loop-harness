from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import stat
import threading
from types import MappingProxyType
from typing import Any

from .contracts.authority_surface import (
    authority_document_sha256,
    merge_authority_canaries,
    validate_authority_surface_resolution,
    validate_bootstrap_authority_profile,
)
from .contracts.proof_admission import (
    EFFECTS_ZERO,
    PROOF_COVERAGE_ADMISSION_CONTRACT_VERSION,
    PROOF_COVERAGE_OBSERVATION_CONTRACT_VERSION,
    canary_item_sha256,
    derive_admission_state,
    derive_current_proof_match_status,
    derive_effect_status,
    derive_role_freshness,
    environment_binding_sha256,
    execution_binding_sha256,
    finalize_proof_coverage_admission,
    finalize_proof_coverage_observation,
    finalize_proof_coverage_participant,
    validate_proof_coverage_admission,
    validate_proof_coverage_policy,
)
from .contracts.proof_execution import validate_proof_execution_document
from .contracts.proof_workspace import (
    proof_document_sha256,
    validate_proof_workspace_binding,
    validate_proof_workspace_spec,
    validate_verification_profile,
)
from .errors import PclError
from .proof_execution import (
    AuthorityInputSnapshot,
    CurrentProofSnapshot,
    ProofExecutionBundle,
)
from .proof_workspace import PreparedProofWorkspace
from .redaction import redact_text


_CAPABILITY_ISSUER = object()
_CAPABILITY_LOCK = threading.Lock()
_CAPABILITY_REGISTRY: dict[
    int, tuple[TrustedCoveragePolicyProducerCapability, str, str]
] = {}

_PHASES = {"input", "policy", "participant", "source", "join", "admission"}
_AGGREGATE_REASONS = {
    "invalid": "participant_aggregate_invalid",
    "indeterminate": "participant_aggregate_indeterminate",
    "blocked": "participant_aggregate_blocked",
    "cancelled": "participant_aggregate_cancelled",
    "failed": "participant_aggregate_failed",
    "spawn_failed": "participant_aggregate_spawn_failed",
    "timed_out": "participant_aggregate_timed_out",
}
_BLOB_REASON = {
    "missing": "candidate_blob_missing",
    "oid_mismatch": "candidate_blob_oid_mismatch",
    "unsupported_type": "candidate_blob_type_unsupported",
    "indeterminate": "candidate_blob_resolution_indeterminate",
}
_BLOB_STATUS_PRECEDENCE = (
    "indeterminate",
    "unsupported_type",
    "missing",
    "oid_mismatch",
    "matched",
)


class ProofCoverageError(PclError):
    pass


class TrustedCoveragePolicyProducerCapability:
    """Private in-process producer association; never serialized or hashed."""

    __slots__ = ("kind", "producer_id", "_issuer")

    def __init__(self, kind: str, producer_id: str, *, _issuer: object) -> None:
        if _issuer is not _CAPABILITY_ISSUER:
            raise TypeError("Trusted coverage capabilities are issued by the composition root.")
        self.kind = kind
        self.producer_id = producer_id
        self._issuer = _issuer


@dataclass(frozen=True, slots=True)
class TrustedCoveragePolicy:
    document: Mapping[str, Any]
    expected_policy_sha256: str
    producer_capability: TrustedCoveragePolicyProducerCapability = field(
        repr=False,
        compare=False,
    )


@dataclass(frozen=True, slots=True)
class ProofCoverageParticipant:
    prepared: PreparedProofWorkspace
    spec: Mapping[str, Any]
    authority_resolution: Mapping[str, Any]
    bootstrap_profile: Mapping[str, Any]
    verification_profile: Mapping[str, Any]
    bundle: ProofExecutionBundle


@dataclass
class _ParticipantRuntime:
    supplied: ProofCoverageParticipant
    public: dict[str, Any]
    profile_checks: dict[str, Mapping[str, Any]]
    binding_checks: dict[str, Mapping[str, Any]]
    results: dict[str, Mapping[str, Any]]
    receipts: dict[str, Mapping[str, Any]]
    source_before: tuple[str, str, str, str] | None


@dataclass(frozen=True)
class _BlobResolution:
    status: str
    sha256: str
    statuses: frozenset[str]


class _GitObservationIndeterminate(Exception):
    pass


def issue_trusted_coverage_policy_producer_capability(
    *,
    kind: str,
    producer_id: str,
) -> TrustedCoveragePolicyProducerCapability:
    """Composition-root hook for a fixed trusted producer association."""

    if kind not in {"external_bootstrap", "pinned_installed", "trusted_planner"}:
        raise ValueError("Unsupported trusted coverage producer kind.")
    if not _public_identifier(producer_id):
        raise ValueError("Invalid trusted coverage producer identifier.")
    capability = TrustedCoveragePolicyProducerCapability(
        kind,
        producer_id,
        _issuer=_CAPABILITY_ISSUER,
    )
    with _CAPABILITY_LOCK:
        _CAPABILITY_REGISTRY[id(capability)] = (
            capability,
            kind,
            producer_id,
        )
    return capability


def bind_trusted_coverage_policy(
    document: Mapping[str, Any],
    *,
    expected_policy_sha256: str,
    producer_capability: TrustedCoveragePolicyProducerCapability,
) -> TrustedCoveragePolicy:
    if not isinstance(document, Mapping):
        raise _error("coverage_input_type_invalid", "policy")
    try:
        normalized = _json_copy(document)
    except (TypeError, ValueError):
        raise _error("coverage_contract_invalid", "policy") from None
    validation = validate_proof_coverage_policy(normalized)
    if not validation.ok:
        raise _error("coverage_contract_invalid", "policy")
    if normalized["policy_sha256"] != expected_policy_sha256:
        raise _error("coverage_policy_authority_invalid", "policy")
    if not isinstance(producer_capability, TrustedCoveragePolicyProducerCapability):
        raise _error("coverage_input_type_invalid", "policy")
    with _CAPABILITY_LOCK:
        registered = _CAPABILITY_REGISTRY.get(id(producer_capability))
    producer = normalized["producer"]
    if (
        registered is None
        or registered[0] is not producer_capability
        or registered[1:] != (producer["kind"], producer["producer_id"])
        or producer_capability._issuer is not _CAPABILITY_ISSUER
    ):
        raise _error("coverage_policy_authority_invalid", "policy")
    if _secret_shaped_public_identifier(normalized):
        raise _error("coverage_public_identifier_secret_shaped", "policy")
    frozen = _deep_freeze(normalized)
    assert isinstance(frozen, Mapping)
    return TrustedCoveragePolicy(
        document=frozen,
        expected_policy_sha256=expected_policy_sha256,
        producer_capability=producer_capability,
    )


def evaluate_proof_coverage(
    *,
    policy: TrustedCoveragePolicy,
    participants: Sequence[ProofCoverageParticipant],
    authority_provider: Callable[[], AuthorityInputSnapshot],
    current_proof_provider: Callable[[], CurrentProofSnapshot],
) -> Mapping[str, Any]:
    if type(policy) is not TrustedCoveragePolicy:
        raise _error("coverage_input_type_invalid", "input")
    if (
        not isinstance(participants, Sequence)
        or isinstance(participants, (str, bytes, bytearray))
        or not 1 <= len(participants) <= 256
        or any(type(participant) is not ProofCoverageParticipant for participant in participants)
    ):
        raise _error("coverage_input_type_invalid", "input")
    if not callable(authority_provider) or not callable(current_proof_provider):
        raise _error("coverage_input_type_invalid", "input")
    document = _thaw(policy.document)
    if not isinstance(document, dict):
        raise _error("coverage_input_type_invalid", "policy")
    validation = validate_proof_coverage_policy(document)
    if not validation.ok or document["policy_sha256"] != policy.expected_policy_sha256:
        raise _error("coverage_digest_mismatch", "policy")
    _require_live_capability(policy, document)

    total_checks = sum(
        len(participant.verification_profile.get("checks", ()))
        if isinstance(participant.verification_profile, Mapping)
        else 0
        for participant in participants
    )
    if total_checks > 4096:
        raise _error("coverage_capacity_exceeded", "input")

    runtimes = [
        _prepare_participant(participant, document)
        for participant in participants
    ]
    runtimes.sort(key=lambda item: item.public["participant_sha256"])
    public_participants = [runtime.public for runtime in runtimes]
    reasons: set[str] = set()

    group_digests = {item["participant_group_sha256"] for item in public_participants}
    if group_digests != {document["coverage_group_sha256"]}:
        reasons.add("coverage_group_mismatch")
    bundle_digests = [item["bundle_sha256"] for item in public_participants]
    if len(bundle_digests) != len(set(bundle_digests)):
        reasons.add("duplicate_bundle")
    proof_keys = [item["proof_key_sha256"] for item in public_participants]
    if len(proof_keys) != len(set(proof_keys)):
        reasons.add("duplicate_proof_key")

    role_set = {requirement["role"] for requirement in document["required_roles"]}
    for runtime in runtimes:
        if not any(check.get("role") in role_set for check in runtime.profile_checks.values()):
            reasons.add("participant_without_required_role")
        aggregate_verdict = runtime.public["aggregate_verdict"]
        aggregate_reason = _AGGREGATE_REASONS.get(aggregate_verdict)
        if aggregate_reason is not None:
            reasons.add(aggregate_reason)

    blob_resolutions: dict[tuple[str, str], _BlobResolution] = {}
    for requirement in document["required_roles"]:
        selected = _selected_runtime_check_for_requirement(requirement, runtimes)
        if selected is None:
            continue
        selected_runtime, selected_check_id = selected
        cache_key = (
            selected_runtime.public["participant_sha256"],
            requirement["requirement_sha256"],
        )
        blob_resolutions[cache_key] = _resolve_candidate_blobs(
            selected_runtime,
            requirement,
            selected_check_id,
        )

    source_indeterminate: set[str] = set()
    for runtime in runtimes:
        try:
            source_after = _source_snapshot(runtime.supplied.prepared)
        except _GitObservationIndeterminate:
            source_indeterminate.add(runtime.public["participant_sha256"])
            continue
        if runtime.source_before is not None and source_after != runtime.source_before:
            raise _error("coverage_live_identity_mismatch", "source")
    if source_indeterminate:
        for requirement in document["required_roles"]:
            selected = _selected_runtime_check_for_requirement(requirement, runtimes)
            if (
                selected is None
                or selected[0].public["participant_sha256"]
                not in source_indeterminate
            ):
                continue
            selected_runtime, selected_check_id = selected
            cache_key = (
                selected_runtime.public["participant_sha256"],
                requirement["requirement_sha256"],
            )
            blob_resolutions[cache_key] = _indeterminate_blob_resolution(
                selected_runtime,
                requirement,
                selected_check_id,
            )

    current_authority, current_canaries, authority_status = _current_authority(
        authority_provider,
        document,
        runtimes,
    )
    if authority_status == "indeterminate":
        reasons.add("authority_current_indeterminate")
    elif authority_status == "mismatched":
        reasons.add("authority_current_mismatch")
    required_canary_ids = {
        str(requirement["canary_id"])
        for requirement in document["required_roles"]
        if requirement["kind"] == "authority_canary"
    }
    if authority_status != "indeterminate" and required_canary_ids != set(current_canaries):
        reasons.add("canary_plan_mismatch")

    observations: list[dict[str, Any]] = []
    for requirement in document["required_roles"]:
        observation, observation_reasons = _observe_role(
            requirement,
            runtimes,
            current_canaries=current_canaries,
            authority_determinate=current_authority is not None,
            blob_resolutions=blob_resolutions,
        )
        observations.append(observation)
        reasons.update(observation_reasons)

    final_current = _capture_join_final_current(current_proof_provider)
    current_public = {
        **final_current,
        "match_status": derive_current_proof_match_status(
            public_participants,
            final_current,
        ),
    }
    reasons.update(_current_proof_reasons(public_participants, final_current))

    runtime_by_digest = {
        runtime.public["participant_sha256"]: runtime for runtime in runtimes
    }
    finalized_observations: list[dict[str, Any]] = []
    for observation in observations:
        selected = observation["selected_participant_sha256"]
        if observation["attempt_status"] == "executed":
            selected_runtime = runtime_by_digest[selected]
            observation["freshness"] = derive_role_freshness(
                "executed",
                selected_runtime.public["aggregate_current_proof"],
                final_current,
            )
        else:
            observation["freshness"] = "not_observed"
        finalized_observations.append(
            finalize_proof_coverage_observation(observation)
        )

    promotion_codes = _promotion_codes(public_participants)
    sorted_reasons = sorted(reasons)
    admission_state = derive_admission_state(sorted_reasons)
    human_gate = document["authorization_requirements"]["human_gate"]
    admission = finalize_proof_coverage_admission(
        {
            "contract_version": PROOF_COVERAGE_ADMISSION_CONTRACT_VERSION,
            "policy_sha256": document["policy_sha256"],
            "coverage_group_sha256": document["coverage_group_sha256"],
            "participants": public_participants,
            "role_observations": finalized_observations,
            "current_proof": current_public,
            "admission_state": admission_state,
            "state_reason_codes": sorted_reasons,
            "review_readiness": "ready" if admission_state == "reviewable" else "withheld",
            "promotion_suitability": (
                "candidate"
                if admission_state == "reviewable" and not promotion_codes
                else "withheld"
            ),
            "promotion_withholding_codes": promotion_codes,
            "authorization_status": {
                "independent_review": "pending",
                "human_gate": "pending" if human_gate == "required" else "not_required",
                "anchoring_authorized": False,
                "reuse_authorized": False,
                "terminal_authority": False,
                "mandatory_evidence": False,
            },
            "effects": dict(EFFECTS_ZERO),
        }
    )
    admission_validation = validate_proof_coverage_admission(admission)
    if not admission_validation.ok:
        raise _error("coverage_contract_invalid", "admission")
    if _secret_shaped_public_identifier(admission):
        raise _error("coverage_public_identifier_secret_shaped", "admission")
    return MappingProxyType(admission)


def _prepare_participant(
    participant: ProofCoverageParticipant,
    policy: Mapping[str, Any],
) -> _ParticipantRuntime:
    if (
        type(participant.prepared) is not PreparedProofWorkspace
        or type(participant.bundle) is not ProofExecutionBundle
        or any(
            not isinstance(value, Mapping)
            for value in (
                participant.spec,
                participant.authority_resolution,
                participant.bootstrap_profile,
                participant.verification_profile,
            )
        )
    ):
        raise _error("coverage_input_type_invalid", "participant")
    _validate_participant_contracts(participant)
    profile_checks = {
        str(check["check_id"]): check
        for check in participant.verification_profile["checks"]
    }
    ordered_ids = [str(check["check_id"]) for check in participant.verification_profile["checks"]]
    expected_objects = tuple(
        participant.prepared.prepared_checks[check_id]
        for check_id in ordered_ids
        if check_id in participant.prepared.prepared_checks
    )
    actual_objects = participant.bundle.frozen_packet.prepared_checks
    if len(actual_objects) != len(expected_objects) or any(
        actual is not expected
        for actual, expected in zip(actual_objects, expected_objects, strict=True)
    ):
        raise _error("coverage_live_identity_mismatch", "participant")
    if dict(participant.bundle.frozen_packet.public) != dict(participant.bundle.packet):
        raise _error("coverage_digest_mismatch", "participant")

    binding_checks = {
        str(check["check_id"]): check
        for check in participant.prepared.binding["checks"]
    }
    result_by_id = {
        str(result["check_id"]): result for result in participant.bundle.check_results
    }
    receipt_by_id = {
        str(receipt["check_id"]): receipt for receipt in participant.bundle.check_receipts
    }
    try:
        source_before = _source_snapshot(participant.prepared)
    except _GitObservationIndeterminate:
        source_before = None
    spec = participant.spec
    authority = participant.authority_resolution
    candidate = {
        "object_format": spec["candidate"]["object_format"],
        "commit_oid": spec["candidate"]["commit_oid"],
        "tree_oid": spec["candidate"]["tree_oid"],
    }
    group = proof_document_sha256(
        {
            "contract_version": "proof-coverage-group/v1",
            "target": dict(spec["target"]),
            "candidate": candidate,
            "authority_surface_resolution_sha256": authority_document_sha256(authority),
            "bootstrap_profile_sha256": authority_document_sha256(
                participant.bootstrap_profile
            ),
            "canary_union_sha256": authority["canary"]["union_sha256"],
            "isolation_contract_version": spec["isolation_contract_version"],
        }
    )
    aggregate = participant.bundle.aggregate
    public = finalize_proof_coverage_participant(
        {
            "participant_group_sha256": group,
            "spec_sha256": proof_document_sha256(spec),
            "workspace_binding_sha256": proof_document_sha256(
                participant.prepared.binding
            ),
            "proof_key_sha256": participant.prepared.binding["proof_key"]["sha256"],
            "verification_profile_sha256": proof_document_sha256(
                participant.verification_profile
            ),
            "check_plan_sha256": participant.prepared.binding[
                "verification_profile"
            ]["check_plan_sha256"],
            "external_input_binding_sha256": participant.prepared.binding[
                "external_inputs"
            ]["binding_sha256"],
            "packet_sha256": participant.bundle.packet["packet_sha256"],
            "executor_contract_sha256": participant.bundle.packet[
                "executor_contract_sha256"
            ],
            "aggregate_sha256": aggregate["aggregate_sha256"],
            "bundle_sha256": participant.bundle.bundle_receipt["bundle_sha256"],
            "aggregate_verdict": aggregate["verdict"],
            "aggregate_output_commitment_status": aggregate[
                "output_commitment_status"
            ],
            "aggregate_reuse_disposition": aggregate["reuse_disposition"],
            "aggregate_anchoring_eligible": aggregate["anchoring_eligible"],
            "aggregate_positive_proof_handoff": aggregate[
                "positive_proof_handoff"
            ],
            "aggregate_current_proof": dict(aggregate["current_proof"]),
        }
    )
    if policy["candidate"] != candidate:
        # This remains a document outcome through the participant group digest.
        pass
    return _ParticipantRuntime(
        supplied=participant,
        public=public,
        profile_checks=profile_checks,
        binding_checks=binding_checks,
        results=result_by_id,
        receipts=receipt_by_id,
        source_before=source_before,
    )


def _validate_participant_contracts(participant: ProofCoverageParticipant) -> None:
    validations = (
        validate_proof_workspace_spec(dict(participant.spec)),
        validate_authority_surface_resolution(dict(participant.authority_resolution)),
        validate_bootstrap_authority_profile(dict(participant.bootstrap_profile)),
        validate_verification_profile(dict(participant.verification_profile)),
        validate_proof_workspace_binding(dict(participant.prepared.binding)),
    )
    if any(not validation.ok for validation in validations):
        raise _error("coverage_contract_invalid", "participant")
    documents = (
        participant.bundle.packet,
        *participant.bundle.authority_checkpoints,
        *participant.bundle.stream_logs,
        *participant.bundle.check_receipts,
        *participant.bundle.check_results,
        participant.bundle.aggregate,
        participant.bundle.bundle_receipt,
    )
    if any(
        not isinstance(document, dict)
        or not validate_proof_execution_document(document).ok
        for document in documents
    ):
        raise _error("coverage_digest_mismatch", "participant")
    spec = participant.spec
    authority = participant.authority_resolution
    bootstrap = participant.bootstrap_profile
    profile = participant.verification_profile
    binding = participant.prepared.binding
    if (
        spec["authority_surface_resolution_sha256"]
        != authority_document_sha256(authority)
        or spec["bootstrap_profile_sha256"] != authority_document_sha256(bootstrap)
        or spec["verification_profile_sha256"] != proof_document_sha256(profile)
        or binding["spec_sha256"] != proof_document_sha256(spec)
        or binding["authority"]["resolution_sha256"]
        != authority_document_sha256(authority)
        or binding["verification_profile"]["sha256"]
        != proof_document_sha256(profile)
        or binding["repository"]["candidate"] != spec["candidate"]
        or spec["target"] != authority["target"]
        or {
            "commit_oid": spec["candidate"]["commit_oid"],
            "tree_oid": spec["candidate"]["tree_oid"],
        }
        != authority["candidate"]
    ):
        raise _error("coverage_digest_mismatch", "participant")
    packet = participant.bundle.packet
    aggregate = participant.bundle.aggregate
    receipt = participant.bundle.bundle_receipt
    if (
        packet["workspace_binding_sha256"] != proof_document_sha256(binding)
        or aggregate["packet_sha256"] != packet["packet_sha256"]
        or receipt["packet_sha256"] != packet["packet_sha256"]
        or receipt["aggregate_sha256"] != aggregate["aggregate_sha256"]
    ):
        raise _error("coverage_digest_mismatch", "participant")
    expected_objects = [
        {"role": "aggregate", "sha256": aggregate["aggregate_sha256"]},
        {"role": "packet", "sha256": packet["packet_sha256"]},
    ]
    expected_objects.extend(
        {"role": f"authority:{index:04d}", "sha256": item["checkpoint_sha256"]}
        for index, item in enumerate(participant.bundle.authority_checkpoints)
    )
    expected_objects.extend(
        {"role": f"log:{index:04d}", "sha256": item["log_sha256"]}
        for index, item in enumerate(participant.bundle.stream_logs)
    )
    expected_objects.extend(
        {"role": f"receipt:{index:04d}", "sha256": item["receipt_sha256"]}
        for index, item in enumerate(participant.bundle.check_receipts)
    )
    expected_objects.extend(
        {"role": f"result:{index:04d}", "sha256": item["result_sha256"]}
        for index, item in enumerate(participant.bundle.check_results)
    )
    expected_objects.sort(key=lambda item: (item["role"], item["sha256"]))
    if receipt["objects"] != expected_objects:
        raise _error("coverage_digest_mismatch", "participant")


def _current_authority(
    provider: Callable[[], AuthorityInputSnapshot],
    policy: Mapping[str, Any],
    runtimes: Sequence[_ParticipantRuntime],
) -> tuple[dict[str, Any] | None, dict[str, Mapping[str, Any]], str]:
    try:
        snapshot = provider()
        if type(snapshot) is not AuthorityInputSnapshot:
            raise TypeError
        resolution = snapshot.resolve()
        validation = validate_authority_surface_resolution(resolution)
        if not validation.ok:
            raise TypeError
        union = merge_authority_canaries(
            merge_authority_canaries(
                snapshot.bootstrap_profile["canary_contract"],
                snapshot.base_canary,
            ),
            snapshot.candidate_canary,
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        fallback = _bootstrap_canaries(policy, runtimes)
        return None, fallback, "indeterminate"
    canaries = {str(item["id"]): item for item in union["items"]}
    expected_resolution = policy["authority_bindings"][
        "authority_surface_resolution_sha256"
    ]
    matched = (
        authority_document_sha256(resolution) == expected_resolution
        and authority_document_sha256(union)
        == policy["authority_bindings"]["canary_union_sha256"]
        and all(
            authority_document_sha256(runtime.supplied.authority_resolution)
            == expected_resolution
            for runtime in runtimes
        )
    )
    return resolution, canaries, "matched" if matched else "mismatched"


def _bootstrap_canaries(
    policy: Mapping[str, Any],
    runtimes: Sequence[_ParticipantRuntime],
) -> dict[str, Mapping[str, Any]]:
    candidates: dict[str, Mapping[str, Any]] = {}
    expected = {
        requirement["canary_id"]: requirement["canary_item_sha256"]
        for requirement in policy["required_roles"]
        if requirement["kind"] == "authority_canary"
    }
    for runtime in runtimes:
        for item in runtime.supplied.bootstrap_profile["canary_contract"]["items"]:
            item_id = str(item["id"])
            if expected.get(item_id) == canary_item_sha256(item):
                candidates[item_id] = item
    return candidates


def _selected_runtime_check_for_requirement(
    requirement: Mapping[str, Any],
    runtimes: Sequence[_ParticipantRuntime],
) -> tuple[_ParticipantRuntime, str] | None:
    role = requirement["role"]
    matches = [
        (runtime.public["participant_sha256"], check_id, runtime)
        for runtime in runtimes
        for check_id, check in runtime.profile_checks.items()
        if check.get("role") == role
    ]
    if not matches:
        return None
    _, check_id, runtime = min(matches, key=lambda item: (item[0], item[1]))
    return runtime, check_id


def _observe_role(
    requirement: Mapping[str, Any],
    runtimes: Sequence[_ParticipantRuntime],
    *,
    current_canaries: Mapping[str, Mapping[str, Any]],
    authority_determinate: bool,
    blob_resolutions: dict[tuple[str, str], _BlobResolution],
) -> tuple[dict[str, Any], set[str]]:
    reasons: set[str] = set()
    role = str(requirement["role"])
    raw_matching = list(
        (
            {
                "participant_sha256": runtime.public["participant_sha256"],
                "check_id": check_id,
            }
            for runtime in runtimes
            for check_id, check in runtime.profile_checks.items()
            if check.get("role") == role
        )
    )
    matching = sorted(
        {
            (item["participant_sha256"], item["check_id"]): item
            for item in raw_matching
        }.values(),
        key=lambda item: (item["participant_sha256"], item["check_id"]),
    )
    if len(raw_matching) > 1:
        reasons.add("duplicate_required_role")
    if not matching:
        observation = _empty_observation(requirement)
        reasons.add("required_role_missing")
        return observation, reasons
    selected = matching[0]
    runtime = next(
        item
        for item in runtimes
        if item.public["participant_sha256"] == selected["participant_sha256"]
    )
    check_id = selected["check_id"]
    result = runtime.results.get(check_id)
    receipt = runtime.receipts.get(check_id)
    attempt_status = "executed" if result is not None and receipt is not None else "not_run"
    if attempt_status == "not_run":
        reasons.add("required_role_not_run")
    plan_status = _plan_binding_status(requirement, runtime, check_id)
    if plan_status == "mismatched":
        reasons.add("participant_policy_mismatch")
    canary_item = (
        current_canaries.get(str(requirement["canary_id"]))
        if requirement["kind"] == "authority_canary"
        else None
    )
    selector_status = "not_applicable"
    if requirement["kind"] == "authority_canary":
        selector_status = _selector_status(requirement, runtime, check_id, canary_item)
        if selector_status == "mismatched":
            reasons.add("canary_plan_mismatch")
        if authority_determinate and not _canary_matches(requirement, canary_item):
            reasons.add("canary_plan_mismatch")
    cache_key = (runtime.public["participant_sha256"], requirement["requirement_sha256"])
    blob_resolution = blob_resolutions.get(cache_key)
    if blob_resolution is None:
        blob_resolution = _resolve_candidate_blobs(runtime, requirement, check_id)
        blob_resolutions[cache_key] = blob_resolution
    for status in blob_resolution.statuses:
        reason = _BLOB_REASON.get(status)
        if reason is not None:
            reasons.add(reason)
    effect_status = "not_applicable"
    if requirement["kind"] == "authority_canary":
        if attempt_status == "not_run":
            effect_status = "not_observed"
        else:
            expectations = (
                list(canary_item["effect_expectations"])
                if canary_item is not None
                else []
            )
            effect_status = derive_effect_status(
                kind="authority_canary",
                attempt_status="executed",
                expectations=expectations,
                canonical_unchanged=_canonical_unchanged(receipt),
                hwm_equality=_hwm_equality(runtime.supplied.bundle),
            )
        effect_reason = {
            "unsupported": "canary_effect_expectation_unsupported",
            "mismatched": "canary_effect_mismatch",
            "unproved": "canary_pcl_state_effect_unproved",
        }.get(effect_status)
        if effect_reason is not None:
            reasons.add(effect_reason)
    aggregate = runtime.supplied.bundle.aggregate
    observation = {
        "contract_version": PROOF_COVERAGE_OBSERVATION_CONTRACT_VERSION,
        "role": role,
        "kind": requirement["kind"],
        "canary_id": requirement["canary_id"],
        "requirement_sha256": requirement["requirement_sha256"],
        "matching_checks": matching,
        "selected_participant_sha256": selected["participant_sha256"],
        "check_id": check_id,
        "attempt_status": attempt_status,
        "attempt_sha256": (
            None
            if attempt_status == "not_run"
            else proof_document_sha256(
                {
                    "contract_version": "proof-coverage-attempt/v1",
                    "participant_sha256": selected["participant_sha256"],
                    "packet_sha256": runtime.public["packet_sha256"],
                    "check_id": check_id,
                    "result_sha256": result["result_sha256"],
                    "receipt_sha256": receipt["receipt_sha256"],
                }
            )
        ),
        "result_sha256": None if result is None else result["result_sha256"],
        "receipt_sha256": None if receipt is None else receipt["receipt_sha256"],
        "c3_verdict": None if result is None else result["verdict"],
        "aggregate_verdict": aggregate["verdict"],
        "aggregate_reuse_disposition": aggregate["reuse_disposition"],
        "aggregate_anchoring_eligible": aggregate["anchoring_eligible"],
        "aggregate_positive_proof_handoff": aggregate["positive_proof_handoff"],
        # L-H: missing -> null; both not_run and executed -> non-null.
        "output_commitment_status": aggregate["output_commitment_status"],
        "plan_binding_status": plan_status,
        "selector_audit_status": selector_status,
        "candidate_blob_status": blob_resolution.status,
        "candidate_blob_resolution_sha256": blob_resolution.sha256,
        "effect_status": effect_status,
        "freshness": "not_observed",
    }
    return observation, reasons


def _empty_observation(requirement: Mapping[str, Any]) -> dict[str, Any]:
    kind = requirement["kind"]
    return {
        "contract_version": PROOF_COVERAGE_OBSERVATION_CONTRACT_VERSION,
        "role": requirement["role"],
        "kind": kind,
        "canary_id": requirement["canary_id"],
        "requirement_sha256": requirement["requirement_sha256"],
        "matching_checks": [],
        "selected_participant_sha256": None,
        "check_id": None,
        "attempt_status": "missing",
        "attempt_sha256": None,
        "result_sha256": None,
        "receipt_sha256": None,
        "c3_verdict": None,
        "aggregate_verdict": None,
        "aggregate_reuse_disposition": None,
        "aggregate_anchoring_eligible": None,
        "aggregate_positive_proof_handoff": None,
        "output_commitment_status": None,
        "plan_binding_status": "not_observed",
        "selector_audit_status": "not_applicable" if kind == "full_regression" else "not_observed",
        "candidate_blob_status": "not_observed",
        "candidate_blob_resolution_sha256": None,
        "effect_status": "not_applicable" if kind == "full_regression" else "not_observed",
        "freshness": "not_observed",
    }


def _plan_binding_status(
    requirement: Mapping[str, Any],
    runtime: _ParticipantRuntime,
    check_id: str,
) -> str:
    profile_check = runtime.profile_checks.get(check_id)
    binding_check = runtime.binding_checks.get(check_id)
    prepared = runtime.supplied.prepared.prepared_checks.get(check_id)
    if profile_check is None or binding_check is None or prepared is None:
        return "mismatched"
    expected_check = requirement["expected_check"]
    expected_execution = requirement["expected_execution"]
    actual_execution = {
        "plan_sha256": binding_check["plan_sha256"],
        "tool_identity_sha256": binding_check["tool_identity_sha256"],
        "environment_binding_sha256": environment_binding_sha256(
            binding_check["environment"]
        ),
        "public_execution_sha256": binding_check["public_execution_sha256"],
        "spawn_vector_sha256": binding_check["spawn_vector_sha256"],
        "external_input_binding_sha256": runtime.public[
            "external_input_binding_sha256"
        ],
    }
    actual_execution["execution_binding_sha256"] = execution_binding_sha256(
        check_id,
        actual_execution,
    )
    prepared_matches = (
        prepared.plan_sha256 == binding_check["plan_sha256"]
        and prepared.tool_identity["sha256"] == binding_check["tool_identity_sha256"]
        and prepared.environment_binding == binding_check["environment"]
        and prepared.spawn_vector_sha256
        == (binding_check["spawn_vector_sha256"] or prepared.spawn_vector_sha256)
    )
    return (
        "matched"
        if dict(profile_check) == dict(expected_check)
        and actual_execution == expected_execution
        and prepared_matches
        else "mismatched"
    )


def _selector_status(
    requirement: Mapping[str, Any],
    runtime: _ParticipantRuntime,
    check_id: str,
    canary_item: Mapping[str, Any] | None,
) -> str:
    profile_check = runtime.profile_checks[check_id]
    labels = requirement["selector_audit_labels"]
    matched = sorted(profile_check["selectors"]) == labels
    if canary_item is not None:
        matched = matched and labels == list(canary_item["selectors"])
    return "matched" if matched else "mismatched"


def _canary_matches(
    requirement: Mapping[str, Any],
    item: Mapping[str, Any] | None,
) -> bool:
    if item is None:
        return False
    expected_check = requirement["expected_check"]
    return (
        canary_item_sha256(item) == requirement["canary_item_sha256"]
        and item["id"] == requirement["canary_id"]
        and item["required_outcome"] == requirement["expected_outcome"]
        and list(item["command"]) == expected_check["argv"]
        and list(item["selectors"]) == requirement["selector_audit_labels"]
        and set(item["referenced_blob_oids"])
        == {blob["oid"] for blob in requirement["required_candidate_blobs"]}
    )


def _resolve_candidate_blobs(
    runtime: _ParticipantRuntime,
    requirement: Mapping[str, Any],
    selected_check_id: str,
) -> _BlobResolution:
    prepared = runtime.supplied.prepared
    candidate = runtime.supplied.spec["candidate"]
    selected_check = runtime.profile_checks.get(selected_check_id)
    if selected_check is None:
        raise _error("coverage_live_identity_mismatch", "participant")
    profile_blobs = {
        item["path"]: item["oid"]
        for item in selected_check["referenced_git_blobs"]
    }
    if runtime.source_before is None:
        return _indeterminate_blob_resolution(
            runtime,
            requirement,
            selected_check_id,
        )
    rows: list[dict[str, Any]] = []
    statuses: set[str] = set()
    for blob in requirement["required_candidate_blobs"]:
        path = blob["path"]
        declared = profile_blobs.get(path)
        row = {
            "path": path,
            "expected_oid": blob["oid"],
            "declared_oid": declared,
            "actual_oid": None,
            "mode": None,
            "type": None,
            "status": "indeterminate",
        }
        try:
            mode, object_type, actual_oid = _ls_tree_blob(prepared, candidate["tree_oid"], path)
        except _GitObservationIndeterminate:
            status = "indeterminate"
        else:
            row.update({"mode": mode, "type": object_type, "actual_oid": actual_oid})
            if mode is None:
                status = "missing"
            elif object_type != "blob" or mode not in {"100644", "100755"}:
                status = "unsupported_type"
            elif actual_oid != blob["oid"] or declared != blob["oid"]:
                status = "oid_mismatch"
            else:
                status = "matched"
        row["status"] = status
        statuses.add(status)
        rows.append(row)
    dominant = next(status for status in _BLOB_STATUS_PRECEDENCE if status in statuses)
    digest = proof_document_sha256(
        {
            "contract_version": "proof-candidate-blob-resolution/v1",
            "participant_sha256": runtime.public["participant_sha256"],
            "requirement_sha256": requirement["requirement_sha256"],
            "candidate": {
                "object_format": candidate["object_format"],
                "tree_oid": candidate["tree_oid"],
            },
            "blobs": rows,
        }
    )
    return _BlobResolution(dominant, digest, frozenset(statuses))


def _indeterminate_blob_resolution(
    runtime: _ParticipantRuntime,
    requirement: Mapping[str, Any],
    selected_check_id: str,
) -> _BlobResolution:
    candidate = runtime.supplied.spec["candidate"]
    profile_check = runtime.profile_checks.get(selected_check_id, {})
    profile_blobs = {
        item["path"]: item["oid"]
        for item in profile_check.get("referenced_git_blobs", [])
        if isinstance(item, Mapping)
    }
    rows = [
        {
            "path": blob["path"],
            "expected_oid": blob["oid"],
            "declared_oid": profile_blobs.get(blob["path"]),
            "actual_oid": None,
            "mode": None,
            "type": None,
            "status": "indeterminate",
        }
        for blob in requirement["required_candidate_blobs"]
    ]
    digest = proof_document_sha256(
        {
            "contract_version": "proof-candidate-blob-resolution/v1",
            "participant_sha256": runtime.public["participant_sha256"],
            "requirement_sha256": requirement["requirement_sha256"],
            "candidate": {
                "object_format": candidate["object_format"],
                "tree_oid": candidate["tree_oid"],
            },
            "blobs": rows,
        }
    )
    return _BlobResolution("indeterminate", digest, frozenset({"indeterminate"}))


def _ls_tree_blob(
    prepared: PreparedProofWorkspace,
    tree_oid: str,
    path: str,
) -> tuple[str | None, str | None, str | None]:
    completed = prepared._git.run(
        prepared._source_root,
        "ls-tree",
        "-z",
        "--full-tree",
        tree_oid,
        "--",
        f":(literal){path}",
    )
    if completed.returncode != 0 or len(completed.stdout) > 8192:
        raise _GitObservationIndeterminate
    output = completed.stdout
    if output == b"":
        return None, None, None
    records = output.split(b"\0")
    if records[-1] != b"" or len(records) != 2:
        raise _GitObservationIndeterminate
    record = records[0]
    try:
        header, raw_path = record.split(b"\t", 1)
        mode, object_type, raw_oid = header.split(b" ", 2)
        decoded_path = raw_path.decode("utf-8", errors="strict")
        decoded_mode = mode.decode("ascii", errors="strict")
        decoded_type = object_type.decode("ascii", errors="strict")
        decoded_oid = raw_oid.decode("ascii", errors="strict")
    except (UnicodeDecodeError, ValueError):
        raise _GitObservationIndeterminate from None
    object_format = prepared._source_object_format
    expected_length = 40 if object_format == "sha1" else 64 if object_format == "sha256" else 0
    if (
        decoded_path != path
        or len(decoded_oid) != expected_length
        or any(character not in "0123456789abcdef" for character in decoded_oid)
    ):
        raise _GitObservationIndeterminate
    return decoded_mode, decoded_type, decoded_oid


def _source_snapshot(prepared: PreparedProofWorkspace) -> tuple[str, str, str, str]:
    if not isinstance(prepared._git.environment, Mapping) or prepared._git.environment.get(
        "GIT_OPTIONAL_LOCKS"
    ) != "0":
        raise _error("coverage_live_identity_mismatch", "source")
    for path, expected in (
        (prepared._source_root, prepared._source_root_stat_identity),
        (prepared._source_common_dir, prepared._source_common_dir_stat_identity),
        (prepared._source_object_dir, prepared._source_object_dir_stat_identity),
    ):
        try:
            current = type(expected).from_stat(os.stat(path, follow_symlinks=False))
        except OSError:
            raise _error("coverage_live_identity_mismatch", "source") from None
        if current != expected or not stat.S_ISDIR(current.mode) or stat.S_ISLNK(current.mode):
            raise _error("coverage_live_identity_mismatch", "source")
    root = _git_text(prepared, "rev-parse", "--show-toplevel")
    common_raw = _git_text(prepared, "rev-parse", "--git-common-dir")
    object_raw = _git_text(prepared, "rev-parse", "--git-path", "objects")
    object_format = _git_text(prepared, "rev-parse", "--show-object-format")
    commit = _git_text(
        prepared,
        "rev-parse",
        "--verify",
        f"{prepared._candidate_commit}^{{commit}}",
    )
    tree = _git_text(
        prepared,
        "rev-parse",
        "--verify",
        f"{prepared._candidate_commit}^{{tree}}",
    )
    reachable = _candidate_reachable_direct(prepared, commit)
    common = _resolve_git_path(prepared._source_root, common_raw)
    object_dir = _resolve_git_path(prepared._source_root, object_raw)
    if (
        Path(root).resolve() != prepared._source_root
        or common != prepared._source_common_dir
        or object_dir != prepared._source_object_dir
        or object_format != prepared._source_object_format
        or commit != prepared._candidate_commit
        or tree != prepared._candidate_tree
        or not reachable
    ):
        raise _error("coverage_live_identity_mismatch", "source")
    return root, common_raw, object_format, tree


def _git_text(prepared: PreparedProofWorkspace, *args: str) -> str:
    completed = prepared._git.run(prepared._source_root, *args)
    if completed.returncode != 0 or len(completed.stdout) > 8192:
        raise _GitObservationIndeterminate
    try:
        value = completed.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError:
        raise _GitObservationIndeterminate from None
    if not value or "\0" in value:
        raise _GitObservationIndeterminate
    return value


def _resolve_git_path(root: Path, raw: str) -> Path:
    path = Path(raw)
    return (path if path.is_absolute() else root / path).resolve()


def _candidate_reachable_direct(prepared: PreparedProofWorkspace, commit: str) -> bool:
    refs: list[str] = ["HEAD"]
    completed = prepared._git.run(
        prepared._source_root,
        "for-each-ref",
        "--format=%(refname)",
        "refs/heads",
        "refs/tags",
    )
    if completed.returncode != 0 or len(completed.stdout) > 1_048_576:
        raise _GitObservationIndeterminate
    try:
        refs.extend(
            line
            for line in completed.stdout.decode("utf-8", errors="strict").splitlines()
            if line
        )
    except UnicodeDecodeError:
        raise _GitObservationIndeterminate from None
    for ref in refs:
        result = prepared._git.run(
            prepared._source_root,
            "merge-base",
            "--is-ancestor",
            commit,
            ref,
        )
        if result.returncode == 0:
            return True
        if result.returncode not in {0, 1}:
            raise _GitObservationIndeterminate
    return False


def _capture_join_final_current(
    provider: Callable[[], CurrentProofSnapshot],
) -> dict[str, Any]:
    try:
        snapshot = provider()
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return {"scope": "unknown", "status": "indeterminate", "proof_sha256": None}
    if type(snapshot) is not CurrentProofSnapshot:
        return {"scope": "unknown", "status": "indeterminate", "proof_sha256": None}
    if (
        snapshot.scope == "feature"
        and snapshot.status in {"healthy", "unhealthy"}
        and _sha256(snapshot.proof_sha256)
    ):
        return {
            "scope": snapshot.scope,
            "status": snapshot.status,
            "proof_sha256": snapshot.proof_sha256,
        }
    if (
        snapshot.scope == "not_applicable"
        and snapshot.status == "not_applicable"
        and _sha256(snapshot.proof_sha256)
    ):
        return {
            "scope": snapshot.scope,
            "status": snapshot.status,
            "proof_sha256": snapshot.proof_sha256,
        }
    return {"scope": "unknown", "status": "indeterminate", "proof_sha256": None}


def _current_proof_reasons(
    participants: Sequence[Mapping[str, Any]],
    final: Mapping[str, Any],
) -> set[str]:
    reasons: set[str] = set()
    final_indeterminate = final["status"] == "indeterminate"
    if final_indeterminate:
        reasons.add("current_proof_indeterminate")
    if final["status"] == "unhealthy":
        reasons.add("current_proof_unhealthy")
    final_tuple = (final["scope"], final["status"], final["proof_sha256"])
    for participant in participants:
        current = participant["aggregate_current_proof"]
        status = current["status"]
        if status == "indeterminate":
            reasons.add("participant_current_proof_indeterminate")
        if status == "changed":
            reasons.add("participant_current_proof_changed")
        if (
            not final_indeterminate
            and status != "indeterminate"
            and (current["scope"], current["status"], current["proof_sha256"])
            != final_tuple
        ):
            reasons.add("current_proof_mismatch")
    return reasons


def _canonical_unchanged(receipt: Mapping[str, Any] | None) -> bool:
    if receipt is None:
        return False
    reseal = receipt.get("reseal")
    return (
        isinstance(reseal, Mapping)
        and reseal.get("status") == "matched"
        and reseal.get("effect_classification") in {"read_only", "declared_outputs"}
    )


def _hwm_equality(bundle: ProofExecutionBundle) -> bool | None:
    start = bundle.current_proof_start
    end = bundle.current_proof_end
    if (
        type(start) is not CurrentProofSnapshot
        or type(end) is not CurrentProofSnapshot
        or not isinstance(start.event_high_watermark, int)
        or isinstance(start.event_high_watermark, bool)
        or not isinstance(end.event_high_watermark, int)
        or isinstance(end.event_high_watermark, bool)
        or start.event_high_watermark < 0
        or end.event_high_watermark < 0
    ):
        return None
    return True if start.event_high_watermark == end.event_high_watermark else None


def _promotion_codes(participants: Sequence[Mapping[str, Any]]) -> list[str]:
    reasons: set[str] = set()
    for participant in participants:
        if participant["aggregate_reuse_disposition"] == "fresh_only":
            reasons.add("participant_fresh_only")
        if participant["aggregate_output_commitment_status"] == "uncommitted":
            reasons.add("participant_output_uncommitted")
        if not participant["aggregate_anchoring_eligible"]:
            reasons.add("participant_anchoring_ineligible")
        if participant["aggregate_positive_proof_handoff"] == "withheld":
            reasons.add("participant_handoff_withheld")
    return sorted(reasons)


def _require_live_capability(
    policy: TrustedCoveragePolicy,
    document: Mapping[str, Any],
) -> None:
    capability = policy.producer_capability
    with _CAPABILITY_LOCK:
        registered = _CAPABILITY_REGISTRY.get(id(capability))
    producer = document["producer"]
    if (
        registered is None
        or registered[0] is not capability
        or registered[1:] != (producer["kind"], producer["producer_id"])
    ):
        raise _error("coverage_policy_authority_invalid", "policy")


def _secret_shaped_public_identifier(value: Any, key: str | None = None) -> bool:
    if isinstance(value, Mapping):
        return any(
            _secret_shaped_public_identifier(item, str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_secret_shaped_public_identifier(item, key) for item in value)
    if not isinstance(value, str):
        return False
    identifier_key = key is not None and (
        key in {"role", "policy_id", "producer_id", "canary_id", "check_id"}
        or key == "id"
        or key.endswith("_id")
        or key.endswith("_ids")
    )
    return identifier_key and redact_text(value)[1]


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _public_identifier(value: str) -> bool:
    return (
        bool(value)
        and value.isascii()
        and len(value.encode("utf-8")) <= 4096
        and value[0].isalnum()
        and all(character.isalnum() or character in "_.-" for character in value)
    )


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _error(code: str, phase: str) -> ProofCoverageError:
    if phase not in _PHASES:
        phase = "input"
    return ProofCoverageError(
        "Proof coverage admission failed closed.",
        code=code,
        details={"phase": phase},
    )


__all__ = [
    "ProofCoverageError",
    "ProofCoverageParticipant",
    "TrustedCoveragePolicy",
    "TrustedCoveragePolicyProducerCapability",
    "bind_trusted_coverage_policy",
    "evaluate_proof_coverage",
    "issue_trusted_coverage_policy_producer_capability",
]
