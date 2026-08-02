from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import signal
import stat
import subprocess
import threading
import time
from types import MappingProxyType
from typing import Any
import weakref

from .authority_surface import canonical_git_diff, resolve_authority_surface
from .contracts.authority_surface import (
    authority_document_sha256,
    validate_authority_surface_resolution,
    validate_bootstrap_authority_profile,
)
from .contracts.proof_execution import (
    MAX_CHECKS,
    MAX_CHECK_ID_LENGTH,
    PROOF_AUTHORITY_CHECKPOINT_CONTRACT_VERSION,
    PROOF_CHECK_EXECUTION_RECEIPT_CONTRACT_VERSION,
    PROOF_CHECK_EXECUTION_RESULT_CONTRACT_VERSION,
    PROOF_EXECUTION_BUNDLE_RECEIPT_CONTRACT_VERSION,
    PROOF_EXECUTION_PACKET_CONTRACT_VERSION,
    PROOF_EXECUTION_RESULT_CONTRACT_VERSION,
    PROOF_STREAM_LOG_CONTRACT_VERSION,
    PUBLIC_STREAM_DISCLOSURE_BYTES,
    finalize_proof_execution_document,
    validate_proof_execution_document,
)
from .contracts.proof_workspace import (
    PROOF_WORKSPACE_ISOLATION_CONTRACT_VERSION,
    proof_document_sha256,
    validate_proof_workspace_binding,
    validate_proof_workspace_spec,
    validate_verification_profile,
)
from .db import connect_read_only
from .evidence import (
    ADHOC_EVIDENCE_TYPES,
    EvidenceAddError,
    newest_linked_evidence_id,
    require_healthy_terminal_evidence,
    resolve_strict_copied_evidence_in_snapshot,
    superseding_evidence_id,
)
from .errors import PclError
from .outbox import canonical_event_bytes, canonical_event_record
from .paths import ProjectPaths
from .proof_workspace import (
    PreparedCheck,
    PreparedProofWorkspace,
    ProofWorkspaceError,
    _bytes_sha256,
    _candidate_reachable,
    _git_returncode,
    _read_regular_file,
    _resolve_exact_commit,
    _source_repository,
    _spawn_vector_sha256,
    _stat_identity_no_follow,
    _verify_authority_diff,
)
from .redaction import redact_bytes


C3_READ_CHUNK_BYTES = 65_536
C3_TERM_GRACE_SECONDS = 1
C3_KILL_GRACE_SECONDS = 1
C3_NORMAL_EOF_GROUP_GRACE_SECONDS = 1
_PROCESS_POPEN = subprocess.Popen

_VERDICT_PRECEDENCE = (
    "invalid",
    "indeterminate",
    "blocked",
    "spawn_failed",
    "timed_out",
    "cancelled",
    "failed",
)
_RETAINED_VERDICTS = set(_VERDICT_PRECEDENCE)
_FIXED_CURRENT_PROOF_FAILURE_CODES = {
    "acceptance_evidence_missing",
    "evidence_superseded",
    "feature_missing",
    "feature_not_done",
    "strict_copied_evidence_invalid",
    "terminal_evidence_unhealthy",
    "unsupported_evidence_type",
}


class ProofExecutionError(PclError):
    pass


@dataclass(frozen=True)
class AuthorityInputSnapshot:
    target: Mapping[str, str]
    candidate: Mapping[str, str]
    base_resolution: Mapping[str, Any]
    actual_diff: Mapping[str, Any]
    existing_route_risk: str
    existing_adaptive_depth: str
    trusted_base_floor: str
    reviewer_escalation: Mapping[str, str]
    packaged_catalog: Mapping[str, Any]
    base_catalog: Mapping[str, Any]
    candidate_catalog: Mapping[str, Any]
    base_canary: Mapping[str, Any]
    candidate_canary: Mapping[str, Any]
    resolver: Mapping[str, str]
    bootstrap_profile: Mapping[str, Any]

    def resolve(self) -> dict[str, Any]:
        return resolve_authority_surface(
            target=self.target,
            candidate=self.candidate,
            base_resolution=self.base_resolution,
            actual_diff=self.actual_diff,
            existing_route_risk=self.existing_route_risk,
            existing_adaptive_depth=self.existing_adaptive_depth,
            trusted_base_floor=self.trusted_base_floor,
            reviewer_escalation=self.reviewer_escalation,
            packaged_catalog=self.packaged_catalog,
            base_catalog=self.base_catalog,
            candidate_catalog=self.candidate_catalog,
            base_canary=self.base_canary,
            candidate_canary=self.candidate_canary,
            resolver=self.resolver,
            bootstrap_profile=self.bootstrap_profile,
        )


@dataclass(frozen=True)
class CurrentProofSnapshot:
    scope: str
    status: str
    preimage: Mapping[str, Any]
    proof_sha256: str
    event_high_watermark: int = field(repr=False, compare=False)


@dataclass(frozen=True)
class FrozenExecutionPacket:
    public: Mapping[str, Any]
    prepared_checks: tuple[PreparedCheck, ...] = field(repr=False, compare=False)


@dataclass(frozen=True)
class ProofExecutionBundle:
    packet: Mapping[str, Any]
    authority_checkpoints: tuple[Mapping[str, Any], ...]
    stream_logs: tuple[Mapping[str, Any], ...]
    check_receipts: tuple[Mapping[str, Any], ...]
    check_results: tuple[Mapping[str, Any], ...]
    aggregate: Mapping[str, Any]
    bundle_receipt: Mapping[str, Any]
    frozen_packet: FrozenExecutionPacket = field(repr=False, compare=False)
    current_proof_start: CurrentProofSnapshot | None = field(repr=False, compare=False)
    current_proof_end: CurrentProofSnapshot | None = field(repr=False, compare=False)

    def public_documents(self) -> tuple[Mapping[str, Any], ...]:
        documents = (
            self.packet,
            *self.authority_checkpoints,
            *self.stream_logs,
            *self.check_receipts,
            *self.check_results,
            self.aggregate,
            self.bundle_receipt,
        )
        return tuple(json.loads(json.dumps(document)) for document in documents)


@dataclass(frozen=True)
class _ExecutionFault(Exception):
    verdict: str
    code: str


@dataclass
class _AttemptEntry:
    workspace_ref: weakref.ReferenceType[PreparedProofWorkspace]
    condition: threading.Condition
    done: bool = False
    result: ProofExecutionBundle | None = None
    error: BaseException | None = None


class ExecutionAttemptLedger:
    """Current-process idempotency keyed to the exact live C2 workspace object."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[int, _AttemptEntry] = {}

    def run(
        self,
        workspace: PreparedProofWorkspace,
        owner: Callable[[], ProofExecutionBundle],
    ) -> ProofExecutionBundle:
        identity = id(workspace)
        with self._lock:
            entry = self._entries.get(identity)
            if entry is None or entry.workspace_ref() is not workspace:
                entry = _AttemptEntry(
                    workspace_ref=weakref.ref(workspace),
                    condition=threading.Condition(self._lock),
                )
                self._entries[identity] = entry
                owns = True
            else:
                owns = False
                while not entry.done:
                    entry.condition.wait()
                if entry.error is not None:
                    raise entry.error
                assert entry.result is not None
                return entry.result
        if owns:
            try:
                result = owner()
            except BaseException as exc:
                with self._lock:
                    entry.error = exc
                    entry.done = True
                    entry.condition.notify_all()
                raise
            with self._lock:
                entry.result = result
                entry.done = True
                entry.condition.notify_all()
            return result
        raise AssertionError("unreachable")


_ATTEMPT_LEDGER = ExecutionAttemptLedger()


class StreamAccumulator:
    def __init__(self, profile_cap: int) -> None:
        self.profile_cap = profile_cap
        self.retain_cap = min(profile_cap, PUBLIC_STREAM_DISCLOSURE_BYTES)
        self.retained = bytearray()
        self.saturating_count = 0
        self.profile_cap_exceeded = False
        self.public_ceiling_exceeded = False
        self.eof = False
        self._candidate_digest: hashlib._Hash | None = hashlib.sha256()  # type: ignore[name-defined]

    def consume(self, chunk: bytes) -> None:
        if not chunk:
            return
        remaining = self.retain_cap - len(self.retained)
        if remaining > 0:
            self.retained.extend(chunk[:remaining])
        self.saturating_count = min(self.profile_cap + 1, self.saturating_count + len(chunk))
        self.profile_cap_exceeded = self.profile_cap_exceeded or self.saturating_count > self.profile_cap
        self.public_ceiling_exceeded = self.public_ceiling_exceeded or (
            self.saturating_count > PUBLIC_STREAM_DISCLOSURE_BYTES
        )
        if self._candidate_digest is not None:
            if self.profile_cap_exceeded or self.public_ceiling_exceeded:
                self._candidate_digest = None
            else:
                self._candidate_digest.update(chunk)

    def public_log(
        self,
        *,
        packet_sha256: str,
        check_id: str,
        stream: str,
        secret_environment: bool,
    ) -> dict[str, Any]:
        reasons: set[str] = set()
        if self.profile_cap_exceeded:
            reasons.add("output_profile_cap_exceeded")
        if self.public_ceiling_exceeded:
            reasons.add("public_disclosure_ceiling_exceeded")
        if secret_environment:
            reasons.add("secret_shaped_environment")
        if not self.eof:
            reasons.add("output_incomplete")
        content = bytes(self.retained)
        if not reasons and _contains_secret_shape(content):
            reasons.add("secret_shape_match")
        if reasons:
            value = {
                "contract_version": PROOF_STREAM_LOG_CONTRACT_VERSION,
                "packet_sha256": packet_sha256,
                "check_id": check_id,
                "stream": stream,
                "commitment": "uncommitted",
                "reason_codes": sorted(reasons),
            }
        else:
            digest = self._candidate_digest.hexdigest() if self._candidate_digest else hashlib.sha256(content).hexdigest()
            value = {
                "contract_version": PROOF_STREAM_LOG_CONTRACT_VERSION,
                "packet_sha256": packet_sha256,
                "check_id": check_id,
                "stream": stream,
                "commitment": "committed",
                "content_byte_count": len(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
                "content_sha256": "sha256:" + digest,
            }
        self._candidate_digest = None
        self.retained.clear()
        return _finalize_valid(value)


@dataclass(frozen=True)
class _ControllerResult:
    verdict: str
    process: Mapping[str, Any]
    stdout: StreamAccumulator
    stderr: StreamAccumulator


def execute_proof_workspace(
    prepared: PreparedProofWorkspace,
    *,
    spec: Mapping[str, Any],
    authority_resolution: Mapping[str, Any],
    bootstrap_profile: Mapping[str, Any],
    verification_profile: Mapping[str, Any],
    authority_provider: Callable[[], AuthorityInputSnapshot],
    current_proof_provider: Callable[[], CurrentProofSnapshot],
    cancel_event: threading.Event | None = None,
) -> ProofExecutionBundle:
    return _ATTEMPT_LEDGER.run(
        prepared,
        lambda: _execute_once(
            prepared,
            spec=spec,
            authority_resolution=authority_resolution,
            bootstrap_profile=bootstrap_profile,
            verification_profile=verification_profile,
            authority_provider=authority_provider,
            current_proof_provider=current_proof_provider,
            cancel_event=cancel_event,
        ),
    )


def capture_current_proof(
    paths: ProjectPaths,
    target: Mapping[str, str],
) -> CurrentProofSnapshot:
    """Capture one Feature-linked proof using one read-only SQLite snapshot."""

    conn = connect_read_only(paths.db_path)
    try:
        conn.execute("BEGIN")
        hwm = int(conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM events").fetchone()[0])
        target_type = str(target.get("type") or "")
        target_id = str(target.get("id") or "")
        if target_type == "task":
            task = conn.execute(
                "SELECT related_feature_id FROM tasks WHERE id = ?",
                (target_id,),
            ).fetchone()
            if task is None:
                raise ProofExecutionError(
                    "Current-proof Task does not exist.",
                    code="proof_current_task_missing",
                    details={"target_id": target_id},
                )
            feature_id = task["related_feature_id"]
            if feature_id is None:
                preimage = {
                    "contract_version": "proof-current-feature-snapshot/v1",
                    "scope": "not_applicable",
                    "status": "not_applicable",
                }
                return _current_snapshot(preimage, hwm)
            feature_id = str(feature_id)
        elif target_type == "feature":
            feature_id = target_id
        else:
            raise ProofExecutionError(
                "Current-proof target must be a Task or Feature.",
                code="proof_current_target_invalid",
                details={"target_type": target_type},
            )
        return _capture_feature_current_proof(paths, conn, feature_id=feature_id, hwm=hwm)
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()


def aggregate_verdict(
    ordered_check_ids: Sequence[str],
    results: Sequence[Mapping[str, Any]],
    not_run_check_ids: Sequence[str],
    *,
    additional_verdict: str | None = None,
) -> str:
    actual_ids = [str(result.get("check_id")) for result in results]
    expected_prefix = list(ordered_check_ids[: len(actual_ids)])
    expected_suffix = list(ordered_check_ids[len(actual_ids) :])
    if (
        actual_ids != expected_prefix
        or list(not_run_check_ids) != expected_suffix
        or len(actual_ids) != len(set(actual_ids))
    ):
        return "invalid"
    verdicts = [str(result.get("verdict")) for result in results]
    if additional_verdict is not None:
        verdicts.append(additional_verdict)
    for verdict in _VERDICT_PRECEDENCE:
        if verdict in verdicts:
            return verdict
    if not_run_check_ids or len(results) != len(ordered_check_ids):
        return "blocked"
    if results and all(result.get("verdict") == "passed" for result in results):
        return "passed"
    return "indeterminate"


def derive_current_proof(
    start: CurrentProofSnapshot | None,
    end: CurrentProofSnapshot | None,
) -> dict[str, Any]:
    if start is None or end is None:
        scope = end.scope if end is not None else start.scope if start is not None else "feature"
        return {"scope": scope, "status": "indeterminate", "proof_sha256": None}
    if (
        start.scope != end.scope
        or start.status != end.status
        or start.proof_sha256 != end.proof_sha256
    ):
        return {"scope": end.scope, "status": "changed", "proof_sha256": end.proof_sha256}
    return {"scope": end.scope, "status": end.status, "proof_sha256": end.proof_sha256}


def _execute_once(
    prepared: PreparedProofWorkspace,
    *,
    spec: Mapping[str, Any],
    authority_resolution: Mapping[str, Any],
    bootstrap_profile: Mapping[str, Any],
    verification_profile: Mapping[str, Any],
    authority_provider: Callable[[], AuthorityInputSnapshot],
    current_proof_provider: Callable[[], CurrentProofSnapshot],
    cancel_event: threading.Event | None,
) -> ProofExecutionBundle:
    ordered_ids = [str(check["check_id"]) for check in verification_profile.get("checks", [])]
    prepared_checks = tuple(
        prepared.prepared_checks[check_id]
        for check_id in ordered_ids
        if check_id in prepared.prepared_checks
    )
    packet = _packet(prepared, ordered_ids, prepared_checks)
    frozen_packet = FrozenExecutionPacket(
        public=MappingProxyType(packet),
        prepared_checks=prepared_checks,
    )
    checkpoints: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    initial_fault: _ExecutionFault | None = None
    try:
        _validate_execution_inputs(
            prepared,
            spec=spec,
            authority_resolution=authority_resolution,
            bootstrap_profile=bootstrap_profile,
            verification_profile=verification_profile,
            ordered_ids=ordered_ids,
        )
    except _ExecutionFault as fault:
        initial_fault = fault
    if initial_fault is None:
        try:
            checkpoints.append(
                _authority_checkpoint(
                    prepared,
                    packet_sha256=packet["packet_sha256"],
                    phase="initial",
                    check_id=None,
                    authority_resolution=authority_resolution,
                    bootstrap_profile=bootstrap_profile,
                    verification_profile=verification_profile,
                    spec=spec,
                    authority_provider=authority_provider,
                    initial_authority_established=False,
                )
            )
        except _ExecutionFault as fault:
            initial_fault = fault
    current_start = _capture_current_safely(current_proof_provider) if initial_fault is None else None

    if not ordered_ids:
        initial_fault = initial_fault or _ExecutionFault("blocked", "proof_check_count_invalid")

    for index, check_id in enumerate(ordered_ids):
        if index > 0 and results and results[-1]["verdict"] != "passed":
            break
        check = prepared.prepared_checks.get(check_id)
        fault = initial_fault if index == 0 else None
        if fault is None and check is None:
            fault = _ExecutionFault("invalid", "proof_prepared_check_missing")
        if fault is None and cancel_event is not None and cancel_event.is_set():
            fault = _ExecutionFault("cancelled", "proof_cancelled_before_spawn")
        if fault is not None:
            check_logs, receipt, result = _nonspawn_result(
                packet_sha256=packet["packet_sha256"],
                check_id=check_id,
                verdict=fault.verdict,
                secret_environment=bool(check and check._secret_names),
                authority_checkpoint_sha256s=[
                    item["checkpoint_sha256"] for item in checkpoints
                ],
            )
        else:
            assert check is not None
            check_logs, receipt, result, check_checkpoints = _execute_check(
                prepared,
                check=check,
                packet_sha256=packet["packet_sha256"],
                authority_resolution=authority_resolution,
                bootstrap_profile=bootstrap_profile,
                verification_profile=verification_profile,
                spec=spec,
                authority_provider=authority_provider,
                cancel_event=cancel_event,
            )
            checkpoints.extend(check_checkpoints)
        logs.extend(check_logs)
        receipts.append(receipt)
        results.append(result)

    not_run = ordered_ids[len(results) :]
    final_fault: _ExecutionFault | None = None
    final_checkpoint: dict[str, Any] | None = None
    if initial_fault is None:
        try:
            final_checkpoint = _authority_checkpoint(
                prepared,
                packet_sha256=packet["packet_sha256"],
                phase="aggregate_final",
                check_id=None,
                authority_resolution=authority_resolution,
                bootstrap_profile=bootstrap_profile,
                verification_profile=verification_profile,
                spec=spec,
                authority_provider=authority_provider,
                initial_authority_established=True,
            )
            checkpoints.append(final_checkpoint)
        except _ExecutionFault as fault:
            final_fault = fault
    current_end = _capture_current_safely(current_proof_provider) if current_start is not None else None
    current = derive_current_proof(current_start, current_end)
    verdict = aggregate_verdict(
        ordered_ids,
        results,
        not_run,
        additional_verdict=None if final_fault is None else final_fault.verdict,
    )
    all_committed = all(item["commitment"] == "committed" for item in logs)
    current_candidate = current["status"] in {"healthy", "not_applicable"}
    anchoring_eligible = (
        verdict == "passed"
        and not not_run
        and final_checkpoint is not None
        and all_committed
        and current_candidate
    )
    reuse_disposition = prepared.reuse_disposition
    if not anchoring_eligible or verdict != "passed":
        reuse_disposition = "fresh_only"
        prepared.reuse_disposition = "fresh_only"
    aggregate = _finalize_valid(
        {
            "contract_version": PROOF_EXECUTION_RESULT_CONTRACT_VERSION,
            "packet_sha256": packet["packet_sha256"],
            "ordered_result_sha256s": [item["result_sha256"] for item in results],
            "not_run_check_ids": list(not_run),
            "final_authority_checkpoint_sha256": (
                None if final_checkpoint is None else final_checkpoint["checkpoint_sha256"]
            ),
            "verdict": verdict,
            "output_commitment_status": "committed" if all_committed else "uncommitted",
            "current_proof": current,
            "anchoring_eligible": anchoring_eligible,
            "positive_proof_handoff": "candidate" if anchoring_eligible else "withheld",
            "reuse_disposition": reuse_disposition,
            "reuse_authorized": False,
        }
    )
    bundle_receipt = _bundle_receipt(
        packet,
        checkpoints,
        logs,
        receipts,
        results,
        aggregate,
    )
    if verdict in _RETAINED_VERDICTS:
        prepared.retain_failure(verdict)
    return ProofExecutionBundle(
        packet=packet,
        authority_checkpoints=tuple(checkpoints),
        stream_logs=tuple(logs),
        check_receipts=tuple(receipts),
        check_results=tuple(results),
        aggregate=aggregate,
        bundle_receipt=bundle_receipt,
        frozen_packet=frozen_packet,
        current_proof_start=current_start,
        current_proof_end=current_end,
    )


def _packet(
    prepared: PreparedProofWorkspace,
    ordered_ids: Sequence[str],
    prepared_checks: Sequence[PreparedCheck],
) -> dict[str, Any]:
    executor_contract_sha256 = proof_document_sha256(
        {
            "contract_version": "proof-executor-contract/v1",
            "max_checks": MAX_CHECKS,
            "check_id_max_length": MAX_CHECK_ID_LENGTH,
            "read_chunk_bytes": C3_READ_CHUNK_BYTES,
            "public_stream_disclosure_bytes": PUBLIC_STREAM_DISCLOSURE_BYTES,
            "term_grace_seconds": C3_TERM_GRACE_SECONDS,
            "kill_grace_seconds": C3_KILL_GRACE_SECONDS,
            "normal_eof_group_grace_seconds": C3_NORMAL_EOF_GROUP_GRACE_SECONDS,
            "platforms": ["darwin", "linux"],
            "reuse_authorized": False,
        }
    )
    return _finalize_valid(
        {
            "contract_version": PROOF_EXECUTION_PACKET_CONTRACT_VERSION,
            "workspace_binding_sha256": proof_document_sha256(prepared.binding),
            "executor_contract_sha256": executor_contract_sha256,
            "ordered_check_ids": list(ordered_ids),
            "initial_reuse_disposition": prepared.reuse_disposition,
        }
    )


def _validate_execution_inputs(
    prepared: PreparedProofWorkspace,
    *,
    spec: Mapping[str, Any],
    authority_resolution: Mapping[str, Any],
    bootstrap_profile: Mapping[str, Any],
    verification_profile: Mapping[str, Any],
    ordered_ids: Sequence[str],
) -> None:
    if os.name != "posix" or platform.system().lower() not in {"darwin", "linux"}:
        raise _ExecutionFault("blocked", "proof_platform_capability_missing")
    if (
        not ordered_ids
        or len(ordered_ids) > MAX_CHECKS
        or any(
            not item
            or len(item) > MAX_CHECK_ID_LENGTH
            or not item.isascii()
            for item in ordered_ids
        )
    ):
        raise _ExecutionFault("blocked", "proof_check_count_invalid")
    if len(ordered_ids) != len(set(ordered_ids)):
        raise _ExecutionFault("invalid", "proof_check_order_invalid")
    validations = (
        validate_proof_workspace_spec(spec),
        validate_authority_surface_resolution(authority_resolution),
        validate_bootstrap_authority_profile(bootstrap_profile),
        validate_verification_profile(verification_profile),
        validate_proof_workspace_binding(prepared.binding),
    )
    if any(not validation.ok for validation in validations):
        raise _ExecutionFault("invalid", "proof_c2_contract_invalid")
    if prepared.state not in {"ready", "yielded_to_executor", "resealed"}:
        raise _ExecutionFault("invalid", "proof_workspace_state_invalid")
    if set(prepared.prepared_checks) != set(ordered_ids):
        raise _ExecutionFault("invalid", "proof_prepared_check_set_mismatch")
    if prepared.binding["spec_sha256"] != proof_document_sha256(spec):
        raise _ExecutionFault("invalid", "proof_spec_binding_mismatch")
    if spec["authority_surface_resolution_sha256"] != authority_document_sha256(authority_resolution):
        raise _ExecutionFault("invalid", "proof_authority_binding_mismatch")
    if spec["bootstrap_profile_sha256"] != authority_document_sha256(bootstrap_profile):
        raise _ExecutionFault("invalid", "proof_bootstrap_binding_mismatch")
    profile_sha256 = proof_document_sha256(verification_profile)
    if spec["verification_profile_sha256"] != profile_sha256:
        raise _ExecutionFault("invalid", "proof_profile_binding_mismatch")
    check_plan_sha256 = proof_document_sha256(
        {"contract_version": "proof-check-plan/v1", "checks": verification_profile["checks"]}
    )
    external_sha256 = proof_document_sha256(
        {
            "contract_version": "proof-external-input-binding/v1",
            "entries": prepared.binding["external_inputs"]["entries"],
        }
    )
    expected_key = proof_document_sha256(
        {
            "contract_version": "proof-key/v1",
            "target": spec["target"],
            "candidate_commit_oid": spec["candidate"]["commit_oid"],
            "candidate_tree_oid": spec["candidate"]["tree_oid"],
            "authority_surface_resolution_sha256": authority_document_sha256(authority_resolution),
            "bootstrap_profile_sha256": authority_document_sha256(bootstrap_profile),
            "actual_diff_sha256": authority_resolution["actual_diff"]["sha256"],
            "verification_profile_sha256": profile_sha256,
            "check_plan_sha256": check_plan_sha256,
            "external_input_binding_sha256": external_sha256,
            "isolation_contract_version": PROOF_WORKSPACE_ISOLATION_CONTRACT_VERSION,
        }
    )
    binding = prepared.binding
    if (
        binding["verification_profile"]["sha256"] != profile_sha256
        or binding["verification_profile"]["check_plan_sha256"] != check_plan_sha256
        or binding["external_inputs"]["binding_sha256"] != external_sha256
        or binding["proof_key"]["sha256"] != expected_key
        or binding["authority"]["resolution_sha256"]
        != authority_document_sha256(authority_resolution)
        or binding["authority"]["actual_diff_sha256"]
        != authority_resolution["actual_diff"]["sha256"]
    ):
        raise _ExecutionFault("invalid", "proof_binding_relationship_mismatch")
    public_by_id = {item["check_id"]: item for item in binding["checks"]}
    for raw_check in verification_profile["checks"]:
        check_id = str(raw_check["check_id"])
        check = prepared.prepared_checks[check_id]
        public = public_by_id.get(check_id)
        plan_sha = proof_document_sha256(
            {"contract_version": "proof-check-plan-entry/v1", "check": raw_check}
        )
        actual_spawn = _spawn_vector_sha256(
            check.argv,
            check.cwd,
            check.env,
            token_map=check._token_map,
        )
        if (
            public is None
            or check.plan_sha256 != plan_sha
            or public["plan_sha256"] != plan_sha
            or public["tool_identity_sha256"] != check.tool_identity["sha256"]
            or public["environment"] != dict(check.environment_binding)
            or check.spawn_vector_sha256 != actual_spawn
            or public["spawn_vector_sha256"]
            != (None if check._secret_names else actual_spawn)
        ):
            raise _ExecutionFault("invalid", "proof_prepared_check_binding_mismatch")


def _authority_checkpoint(
    prepared: PreparedProofWorkspace,
    *,
    packet_sha256: str,
    phase: str,
    check_id: str | None,
    authority_resolution: Mapping[str, Any],
    bootstrap_profile: Mapping[str, Any],
    verification_profile: Mapping[str, Any],
    spec: Mapping[str, Any],
    authority_provider: Callable[[], AuthorityInputSnapshot],
    initial_authority_established: bool,
) -> dict[str, Any]:
    deterministic_verdict = "invalid" if initial_authority_established else "blocked"
    try:
        snapshot = authority_provider()
    except BaseException as exc:
        raise _ExecutionFault("indeterminate", "proof_authority_provider_uncertain") from exc
    if not isinstance(snapshot, AuthorityInputSnapshot):
        raise _ExecutionFault(deterministic_verdict, "proof_authority_input_invalid")
    try:
        fresh_resolution = snapshot.resolve()
    except PclError as exc:
        raise _ExecutionFault(deterministic_verdict, "proof_authority_rederivation_mismatch") from exc
    except BaseException as exc:
        raise _ExecutionFault("indeterminate", "proof_authority_rederivation_uncertain") from exc
    if fresh_resolution != authority_resolution:
        raise _ExecutionFault(deterministic_verdict, "proof_authority_rederivation_mismatch")
    if snapshot.bootstrap_profile != bootstrap_profile:
        raise _ExecutionFault(deterministic_verdict, "proof_bootstrap_rederivation_mismatch")
    try:
        _validate_execution_inputs(
            prepared,
            spec=spec,
            authority_resolution=authority_resolution,
            bootstrap_profile=bootstrap_profile,
            verification_profile=verification_profile,
            ordered_ids=[str(item["check_id"]) for item in verification_profile["checks"]],
        )
        _require_directory_identity(
            prepared._source_root,
            prepared._source_root_stat_identity,
        )
        _require_directory_identity(
            prepared._source_common_dir,
            prepared._source_common_dir_stat_identity,
        )
        _require_directory_identity(
            prepared._source_object_dir,
            prepared._source_object_dir_stat_identity,
        )
        source = _source_repository(prepared._source_root, prepared._git)
        if (
            source["root"] != prepared._source_root
            or source["common_dir"] != prepared._source_common_dir
            or source["object_dir"] != prepared._source_object_dir
            or source["object_format"] != prepared._source_object_format
        ):
            raise _ExecutionFault(deterministic_verdict, "proof_source_capability_mismatch")
        candidate = _resolve_exact_commit(
            source["root"],
            prepared._candidate_commit,
            prepared._git,
            code="proof_candidate_object_unavailable",
        )
        tree = _git_text_exact(
            source["root"],
            prepared,
            "rev-parse",
            "--verify",
            f"{candidate}^{{tree}}",
        )
        if tree != prepared._candidate_tree or not _candidate_reachable(
            source["root"], candidate, prepared._git
        ):
            raise _ExecutionFault(deterministic_verdict, "proof_candidate_authority_mismatch")
        base_status = str(authority_resolution["base"]["status"])
        source_diff_sha256: str | None = None
        if base_status in {"resolved", "no_candidate_change"}:
            base = _resolve_exact_commit(
                source["root"],
                str(authority_resolution["base"]["commit_oid"]),
                prepared._git,
                code="proof_candidate_object_unavailable",
            )
            if base_status == "resolved" and _git_returncode(
                source["root"], prepared._git, "merge-base", "--is-ancestor", base, candidate
            ) != 0:
                raise _ExecutionFault(deterministic_verdict, "proof_base_ancestry_mismatch")
            if base_status == "no_candidate_change" and base != candidate:
                raise _ExecutionFault(deterministic_verdict, "proof_no_candidate_change_mismatch")
            source_diff = canonical_git_diff(
                source["root"],
                base_commit_oid=base,
                candidate_commit_oid=candidate,
                git_runner=prepared._git,
            )
            if source_diff != authority_resolution["actual_diff"]:
                raise _ExecutionFault(deterministic_verdict, "proof_source_diff_mismatch")
            source_diff_sha256 = str(source_diff["sha256"])
        clone_diff_sha256 = _verify_authority_diff(
            prepared.root,
            authority_resolution,
            prepared._git,
        )
    except _ExecutionFault:
        raise
    except ProofWorkspaceError as exc:
        raise _ExecutionFault(deterministic_verdict, "proof_git_authority_mismatch") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise _ExecutionFault("indeterminate", "proof_git_authority_uncertain") from exc
    if base_status == "base_unknown":
        clone_cross = {"status": "not_applicable_base_unknown", "diff_sha256": None}
    else:
        if clone_diff_sha256 != source_diff_sha256:
            raise _ExecutionFault("invalid", "proof_clone_diff_mismatch")
        clone_cross = {"status": "matched", "diff_sha256": clone_diff_sha256}
    if fresh_resolution["effective"]["reuse_allowed"] is not True:
        prepared.reuse_disposition = "fresh_only"
    return _finalize_valid(
        {
            "contract_version": PROOF_AUTHORITY_CHECKPOINT_CONTRACT_VERSION,
            "packet_sha256": packet_sha256,
            "phase": phase,
            "check_id": check_id,
            "source_status": "matched",
            "base_status": base_status,
            "literal_reuse_allowed": fresh_resolution["effective"]["reuse_allowed"],
            "rederived_cross_checks": {
                "binding": True,
                "bootstrap_profile": True,
                "verification_profile": True,
                "check_plan": True,
                "external_inputs": True,
                "proof_key": True,
                "public_execution": True,
            },
            "clone_diff_cross_check": clone_cross,
        }
    )


def _execute_check(
    prepared: PreparedProofWorkspace,
    *,
    check: PreparedCheck,
    packet_sha256: str,
    authority_resolution: Mapping[str, Any],
    bootstrap_profile: Mapping[str, Any],
    verification_profile: Mapping[str, Any],
    spec: Mapping[str, Any],
    authority_provider: Callable[[], AuthorityInputSnapshot],
    cancel_event: threading.Event | None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    checkpoints: list[dict[str, Any]] = []
    before: Mapping[str, Any] | None = None
    reseal_public = {
        "status": "not_run",
        "before_manifest_sha256": None,
        "after_manifest_sha256": None,
        "effect_classification": None,
    }
    spawn = {"status": "not_attempted", "error_kind": None}
    process_public: Mapping[str, Any] = _not_started_process()
    stdout = StreamAccumulator(check.max_output_bytes)
    stderr = StreamAccumulator(check.max_output_bytes)
    stdout.eof = True
    stderr.eof = True
    verdict = "passed"
    try:
        _validate_tool_full(check)
    except ProofWorkspaceError:
        verdict = "invalid"
    except OSError:
        verdict = "indeterminate"
    if verdict == "passed":
        try:
            before = prepared.capture_before(check.check_id)
        except ProofWorkspaceError:
            verdict = "invalid"
        except BaseException:
            verdict = "indeterminate"
    if before is not None:
        try:
            try:
                checkpoints.append(
                    _authority_checkpoint(
                        prepared,
                        packet_sha256=packet_sha256,
                        phase="pre_spawn",
                        check_id=check.check_id,
                        authority_resolution=authority_resolution,
                        bootstrap_profile=bootstrap_profile,
                        verification_profile=verification_profile,
                        spec=spec,
                        authority_provider=authority_provider,
                        initial_authority_established=True,
                    )
                )
                prepared.assert_ready_to_spawn(check.check_id)
                _lightweight_guard(check)
                try:
                    process = _PROCESS_POPEN(
                        check.argv,
                        cwd=check.cwd,
                        env=check.env,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=False,
                        text=False,
                        bufsize=0,
                        close_fds=True,
                        start_new_session=True,
                    )
                except OSError as exc:
                    spawn = {"status": "failed", "error_kind": _spawn_error_kind(exc)}
                    verdict = "spawn_failed"
                else:
                    spawn = {"status": "spawned", "error_kind": None}
                    controlled = _control_process(
                        process,
                        timeout_seconds=check.timeout_seconds,
                        max_output_bytes=check.max_output_bytes,
                        cancel_event=cancel_event,
                    )
                    verdict = controlled.verdict
                    process_public = controlled.process
                    stdout = controlled.stdout
                    stderr = controlled.stderr
            except _ExecutionFault as fault:
                verdict = fault.verdict
            except ProofWorkspaceError:
                verdict = "invalid"
            except BaseException:
                verdict = "indeterminate"
        finally:
            try:
                reseal = prepared.reseal_after(check.check_id, before_manifest=before)
            except ProofWorkspaceError:
                verdict = _dominant(verdict, "invalid")
                reseal_public = {
                    "status": "inconclusive",
                    "before_manifest_sha256": before.get("manifest_sha256"),
                    "after_manifest_sha256": None,
                    "effect_classification": None,
                }
            except BaseException:
                verdict = _dominant(verdict, "indeterminate")
                reseal_public = {
                    "status": "inconclusive",
                    "before_manifest_sha256": before.get("manifest_sha256"),
                    "after_manifest_sha256": None,
                    "effect_classification": None,
                }
            else:
                classification = str(reseal["effect"]["classification"])
                reseal_public = {
                    "status": "matched",
                    "before_manifest_sha256": reseal["before_manifest_sha256"],
                    "after_manifest_sha256": reseal["after_manifest_sha256"],
                    "effect_classification": classification,
                }
                if classification == "mutates_inputs":
                    verdict = _dominant(verdict, "invalid")
                elif classification == "unknown":
                    verdict = _dominant(verdict, "indeterminate")
            try:
                checkpoints.append(
                    _authority_checkpoint(
                        prepared,
                        packet_sha256=packet_sha256,
                        phase="post_execution",
                        check_id=check.check_id,
                        authority_resolution=authority_resolution,
                        bootstrap_profile=bootstrap_profile,
                        verification_profile=verification_profile,
                        spec=spec,
                        authority_provider=authority_provider,
                        initial_authority_established=True,
                    )
                )
            except _ExecutionFault as fault:
                verdict = _dominant(verdict, fault.verdict)
    stdout_log = stdout.public_log(
        packet_sha256=packet_sha256,
        check_id=check.check_id,
        stream="stdout",
        secret_environment=bool(check._secret_names),
    )
    stderr_log = stderr.public_log(
        packet_sha256=packet_sha256,
        check_id=check.check_id,
        stream="stderr",
        secret_environment=bool(check._secret_names),
    )
    if stdout_log["commitment"] == "uncommitted" or stderr_log["commitment"] == "uncommitted":
        prepared.reuse_disposition = "fresh_only"
    if verdict != "passed":
        prepared.reuse_disposition = "fresh_only"
    proof_validity = (
        "invalid"
        if verdict == "invalid"
        else "indeterminate"
        if verdict == "indeterminate"
        else "valid"
    )
    receipt = _finalize_valid(
        {
            "contract_version": PROOF_CHECK_EXECUTION_RECEIPT_CONTRACT_VERSION,
            "packet_sha256": packet_sha256,
            "check_id": check.check_id,
            "authority_checkpoint_sha256s": [
                item["checkpoint_sha256"] for item in checkpoints
            ],
            "spawn": spawn,
            "process": dict(process_public),
            "stdout_log_sha256": stdout_log["log_sha256"],
            "stderr_log_sha256": stderr_log["log_sha256"],
            "reseal": reseal_public,
            "proof_validity": proof_validity,
        }
    )
    result = _finalize_valid(
        {
            "contract_version": PROOF_CHECK_EXECUTION_RESULT_CONTRACT_VERSION,
            "packet_sha256": packet_sha256,
            "check_id": check.check_id,
            "receipt_sha256": receipt["receipt_sha256"],
            "verdict": verdict,
            "reuse_disposition": prepared.reuse_disposition,
        }
    )
    return [stdout_log, stderr_log], receipt, result, checkpoints


def _control_process(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: int,
    max_output_bytes: int,
    cancel_event: threading.Event | None,
) -> _ControllerResult:
    stdout = StreamAccumulator(max_output_bytes)
    stderr = StreamAccumulator(max_output_bytes)
    accumulators = {"stdout": stdout, "stderr": stderr}
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    assert process.stderr is not None
    for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, data=name)
    pgid = process.pid
    deadline = time.monotonic() + timeout_seconds
    normal_deadline: float | None = None
    term_deadline: float | None = None
    kill_deadline: float | None = None
    cause: str | None = None
    term_sent = False
    kill_sent = False
    kill_attempted = False
    uncertain = False
    leader_returncode: int | None = None
    try:
        while True:
            now = time.monotonic()
            wait_candidates = [deadline]
            if normal_deadline is not None:
                wait_candidates.append(normal_deadline)
            if term_deadline is not None:
                wait_candidates.append(term_deadline)
            if kill_deadline is not None:
                wait_candidates.append(kill_deadline)
            timeout = max(0.0, min(0.05, min(wait_candidates) - now))
            for key, _ in selector.select(timeout):
                accumulator = accumulators[str(key.data)]
                _drain_ready_fd(selector, key.fileobj, accumulator)
            leader_returncode = process.poll()
            now = time.monotonic()
            group_state = _process_group_state(pgid)
            pipes_eof = stdout.eof and stderr.eof

            if cause is None and leader_returncode is None:
                if now >= deadline:
                    cause = "timeout"
                    term_sent, signal_uncertain = _signal_process_group(pgid, signal.SIGTERM)
                    uncertain = uncertain or signal_uncertain
                    term_deadline = now + C3_TERM_GRACE_SECONDS
                elif cancel_event is not None and cancel_event.is_set():
                    cause = "cancellation"
                    term_sent, signal_uncertain = _signal_process_group(pgid, signal.SIGTERM)
                    uncertain = uncertain or signal_uncertain
                    term_deadline = now + C3_TERM_GRACE_SECONDS
            elif cause is None and leader_returncode is not None:
                if pipes_eof and group_state == "absent":
                    break
                if normal_deadline is None:
                    normal_deadline = now + C3_NORMAL_EOF_GROUP_GRACE_SECONDS
                elif now >= normal_deadline:
                    cause = "descendant_cleanup"
                    term_sent, signal_uncertain = _signal_process_group(pgid, signal.SIGTERM)
                    uncertain = uncertain or signal_uncertain
                    term_deadline = now + C3_TERM_GRACE_SECONDS

            if cause is not None:
                if (
                    term_deadline is not None
                    and now >= term_deadline
                    and not kill_attempted
                    and (group_state != "absent" or leader_returncode is None or not pipes_eof)
                ):
                    kill_attempted = True
                    kill_sent, signal_uncertain = _signal_process_group(pgid, signal.SIGKILL)
                    uncertain = uncertain or signal_uncertain
                    kill_deadline = now + C3_KILL_GRACE_SECONDS
                if leader_returncode is not None and pipes_eof and group_state == "absent":
                    break
                if kill_deadline is not None and now >= kill_deadline:
                    uncertain = True
                    break
    except BaseException:
        uncertain = True
        _signal_process_group(pgid, signal.SIGKILL)
    finally:
        for key in list(selector.get_map().values()):
            try:
                _drain_ready_fd(selector, key.fileobj, accumulators[str(key.data)])
            except OSError:
                uncertain = True
        selector.close()
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                uncertain = True
    try:
        leader_returncode = process.wait(timeout=0 if process.poll() is not None else 0.05)
    except (subprocess.TimeoutExpired, OSError):
        uncertain = True
        leader_returncode = process.poll()
    final_group_state = _process_group_state(pgid)
    if final_group_state != "absent":
        uncertain = True
    pipes_eof = stdout.eof and stderr.eof
    if not pipes_eof or leader_returncode is None:
        uncertain = True
    if uncertain:
        verdict = "indeterminate"
        public_cause = "uncertain"
    elif cause == "timeout":
        verdict = "timed_out"
        public_cause = "timeout"
    elif cause == "cancellation":
        verdict = "cancelled"
        public_cause = "cancellation"
    elif cause == "descendant_cleanup":
        verdict = "failed"
        public_cause = "descendant_cleanup"
    elif leader_returncode is not None and leader_returncode == 0:
        verdict = "passed"
        public_cause = "exit"
    elif leader_returncode is not None and leader_returncode < 0:
        verdict = "failed"
        public_cause = "signal"
    else:
        verdict = "failed"
        public_cause = "exit"
    leader_kind = (
        "unknown"
        if leader_returncode is None
        else "signaled"
        if leader_returncode < 0
        else "exited"
    )
    leader_value = None if leader_returncode is None else abs(leader_returncode)
    process_public = {
        "controller_cause": public_cause,
        "leader_kind": leader_kind,
        "leader_value": leader_value,
        "term_sent": term_sent,
        "kill_sent": kill_sent,
        "pipes_eof": pipes_eof,
        "group_quiescent": final_group_state == "absent",
    }
    return _ControllerResult(verdict, MappingProxyType(process_public), stdout, stderr)


def _drain_ready_fd(
    selector: selectors.BaseSelector,
    stream: Any,
    accumulator: StreamAccumulator,
) -> None:
    while True:
        try:
            chunk = os.read(stream.fileno(), C3_READ_CHUNK_BYTES)
        except BlockingIOError:
            return
        if not chunk:
            accumulator.eof = True
            try:
                selector.unregister(stream)
            except (KeyError, ValueError):
                pass
            return
        accumulator.consume(chunk)
        if len(chunk) < C3_READ_CHUNK_BYTES:
            return


def _process_group_state(pgid: int) -> str:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return "absent"
    except PermissionError:
        return "uncertain"
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return "absent"
        if exc.errno == errno.EPERM:
            return "uncertain"
        return "uncertain"
    return "present"


def _signal_process_group(pgid: int, selected_signal: signal.Signals) -> tuple[bool, bool]:
    try:
        os.killpg(pgid, selected_signal)
    except ProcessLookupError:
        return False, False
    except PermissionError:
        return False, True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False, False
        return False, True
    return True, False


def _validate_tool_full(check: PreparedCheck) -> None:
    contents, identity = _read_regular_file(check._tool_path, require_single_link=False)
    expected = check.tool_identity
    if (
        identity != check._tool_identity_runtime
        or _bytes_sha256(contents) != expected["sha256"]
        or len(contents) != expected["size"]
        or f"{stat.S_IMODE(identity.mode):04o}" != expected["mode"]
    ):
        raise ProofWorkspaceError(
            "The prepared executable changed before proof execution.",
            code="proof_spawn_vector_mismatch",
            details={"check_id": check.check_id},
        )
    shebang_sha256: str | None = None
    if contents.startswith(b"#!"):
        first_line = contents.splitlines()[0][2:].strip().split(maxsplit=1)[0]
        if first_line:
            interpreter = Path(os.fsdecode(first_line))
            if interpreter.is_absolute() and interpreter.exists():
                interpreter_bytes, _ = _read_regular_file(
                    interpreter.resolve(strict=True),
                    require_single_link=False,
                )
                shebang_sha256 = _bytes_sha256(interpreter_bytes)
    if shebang_sha256 != expected["shebang_interpreter_sha256"]:
        raise ProofWorkspaceError(
            "The prepared executable interpreter changed before proof execution.",
            code="proof_spawn_vector_mismatch",
            details={"check_id": check.check_id},
        )


def _lightweight_guard(check: PreparedCheck) -> None:
    if _stat_identity_no_follow(check._tool_path) != check._tool_identity_runtime:
        raise _ExecutionFault("invalid", "proof_spawn_vector_mismatch")
    if _spawn_vector_sha256(
        check.argv,
        check.cwd,
        check.env,
        token_map=check._token_map,
    ) != check.spawn_vector_sha256:
        raise _ExecutionFault("invalid", "proof_spawn_vector_mismatch")


def _capture_feature_current_proof(
    paths: ProjectPaths,
    conn: Any,
    *,
    feature_id: str,
    hwm: int,
) -> CurrentProofSnapshot:
    feature = conn.execute(
        "SELECT id, status FROM features WHERE id = ?",
        (feature_id,),
    ).fetchone()
    feature_status: str | None = None
    failures: set[str] = set()
    if feature is None:
        failures.add("feature_missing")
    else:
        feature_status = "done" if str(feature["status"]) == "done" else "other"
        if feature_status != "done":
            failures.add("feature_not_done")
    evidence_id = newest_linked_evidence_id(
        conn,
        target_type="feature",
        target_id=feature_id,
        link_role="acceptance",
    )
    evidence_type: str | None = None
    superseded_by: str | None = None
    evidence_content_sha256: str | None = None
    recording_event_id: str | None = None
    recording_event_sha256: str | None = None
    link_identity_sha256: str | None = None
    if evidence_id is None:
        failures.add("acceptance_evidence_missing")
    else:
        row = conn.execute(
            "SELECT id, type FROM evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        if row is None:
            failures.add("terminal_evidence_unhealthy")
        else:
            raw_type = str(row["type"])
            evidence_type = raw_type if raw_type in ADHOC_EVIDENCE_TYPES else "other"
            if raw_type not in ADHOC_EVIDENCE_TYPES:
                failures.add("unsupported_evidence_type")
            superseded_by = superseding_evidence_id(conn, evidence_id)
            if superseded_by is not None:
                failures.add("evidence_superseded")
            try:
                require_healthy_terminal_evidence(
                    paths,
                    conn,
                    evidence_id=evidence_id,
                    error_code="proof_current_evidence_unhealthy",
                    allowed_types=set(ADHOC_EVIDENCE_TYPES),
                )
            except EvidenceAddError:
                failures.add("terminal_evidence_unhealthy")
            strict = resolve_strict_copied_evidence_in_snapshot(
                paths,
                conn,
                evidence_id=evidence_id,
            )
            if strict["ok"]:
                evidence_content_sha256 = _current_evidence_content_sha256(strict)
            else:
                failures.add("strict_copied_evidence_invalid")
        event_rows = conn.execute(
            """
            SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
            FROM events
            WHERE event_type = 'adhoc_evidence_recorded'
              AND entity_type = 'evidence'
              AND entity_id = ?
            ORDER BY sequence, id
            """,
            (evidence_id,),
        ).fetchall()
        if len(event_rows) == 1:
            event_row = event_rows[0]
            recording_event_id = str(event_row["id"])
            try:
                event_bytes = canonical_event_bytes(canonical_event_record(event_row))
            except (TypeError, ValueError):
                failures.add("strict_copied_evidence_invalid")
            else:
                recording_event_sha256 = "sha256:" + hashlib.sha256(event_bytes).hexdigest()
        else:
            failures.add("strict_copied_evidence_invalid")
        link_identity_sha256 = proof_document_sha256(
            {
                "contract_version": "proof-current-feature-link-identity/v1",
                "evidence_id": evidence_id,
                "target_type": "feature",
                "target_id": feature_id,
                "link_role": "acceptance",
            }
        )
    status = "healthy" if not failures else "unhealthy"
    preimage = {
        "contract_version": "proof-current-feature-snapshot/v1",
        "scope": "feature",
        "status": status,
        "feature_id": feature_id,
        "feature_status": feature_status,
        "evidence_id": evidence_id,
        "evidence_type": evidence_type,
        "evidence_content_sha256": evidence_content_sha256,
        "superseded_by": superseded_by,
        "recording_event_id": recording_event_id,
        "recording_event_sha256": recording_event_sha256,
        "link_identity_sha256": link_identity_sha256,
        "health_failure_codes": sorted(failures),
    }
    if not set(preimage["health_failure_codes"]).issubset(_FIXED_CURRENT_PROOF_FAILURE_CODES):
        raise AssertionError("current-proof emitted an unfixed failure code")
    return _current_snapshot(preimage, hwm)


def _current_evidence_content_sha256(strict: Mapping[str, Any]) -> str:
    manifest_bytes = strict.get("manifest_bytes")
    manifest = strict.get("manifest")
    if not isinstance(manifest_bytes, bytes) or not isinstance(manifest, Mapping):
        raise ProofExecutionError(
            "Strict copied Evidence omitted its manifest authority.",
            code="proof_current_evidence_inconclusive",
            details={},
        )
    members: list[dict[str, str]] = []
    resolved = strict.get("members")
    if not isinstance(resolved, list):
        raise ProofExecutionError(
            "Strict copied Evidence omitted its copied members.",
            code="proof_current_evidence_inconclusive",
            details={},
        )
    for item in resolved:
        if not isinstance(item, Mapping):
            raise ProofExecutionError(
                "Strict copied Evidence has an invalid member.",
                code="proof_current_evidence_inconclusive",
                details={},
            )
        metadata = item.get("metadata")
        content = item.get("content")
        if not isinstance(metadata, Mapping) or not isinstance(content, bytes):
            raise ProofExecutionError(
                "Strict copied Evidence has an incomplete member.",
                code="proof_current_evidence_inconclusive",
                details={},
            )
        members.append(
            {
                "metadata_sha256": proof_document_sha256(
                    {
                        "contract_version": "proof-current-feature-member-metadata/v1",
                        "metadata": dict(metadata),
                    }
                ),
                "resolved_sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            }
        )
    if len(members) != len(manifest.get("members") or []):
        raise ProofExecutionError(
            "Strict copied Evidence member order is incomplete.",
            code="proof_current_evidence_inconclusive",
            details={},
        )
    return proof_document_sha256(
        {
            "contract_version": "proof-current-feature-evidence-content/v1",
            "manifest_sha256": "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
            "members": members,
        }
    )


def _current_snapshot(
    preimage: Mapping[str, Any],
    event_high_watermark: int,
) -> CurrentProofSnapshot:
    return CurrentProofSnapshot(
        scope=str(preimage["scope"]),
        status=str(preimage["status"]),
        preimage=MappingProxyType(dict(preimage)),
        proof_sha256=proof_document_sha256(
            {
                "contract_version": "proof-current-feature-snapshot-digest/v1",
                "snapshot": dict(preimage),
            }
        ),
        event_high_watermark=event_high_watermark,
    )


def _capture_current_safely(
    provider: Callable[[], CurrentProofSnapshot],
) -> CurrentProofSnapshot | None:
    try:
        snapshot = provider()
        if not isinstance(snapshot, CurrentProofSnapshot) or not _valid_current_snapshot(snapshot):
            return None
    except BaseException:
        return None
    return snapshot


def _valid_current_snapshot(snapshot: CurrentProofSnapshot) -> bool:
    preimage = dict(snapshot.preimage)
    if (
        type(snapshot.event_high_watermark) is not int
        or snapshot.event_high_watermark < 0
        or snapshot.scope != preimage.get("scope")
        or snapshot.status != preimage.get("status")
        or snapshot.proof_sha256
        != proof_document_sha256(
            {
                "contract_version": "proof-current-feature-snapshot-digest/v1",
                "snapshot": preimage,
            }
        )
    ):
        return False
    if snapshot.scope == "not_applicable":
        return preimage == {
            "contract_version": "proof-current-feature-snapshot/v1",
            "scope": "not_applicable",
            "status": "not_applicable",
        }
    expected = {
        "contract_version",
        "scope",
        "status",
        "feature_id",
        "feature_status",
        "evidence_id",
        "evidence_type",
        "evidence_content_sha256",
        "superseded_by",
        "recording_event_id",
        "recording_event_sha256",
        "link_identity_sha256",
        "health_failure_codes",
    }
    if (
        set(preimage) != expected
        or preimage.get("contract_version") != "proof-current-feature-snapshot/v1"
        or preimage.get("scope") != "feature"
        or preimage.get("status") not in {"healthy", "unhealthy"}
        or not _optional_identifier(preimage.get("feature_id"), required=True)
        or preimage.get("feature_status") not in {"done", "other", None}
        or not _optional_identifier(preimage.get("evidence_id"))
        or preimage.get("evidence_type")
        not in {"adhoc_artifact", "adhoc_bundle", "other", None}
        or not _optional_identifier(preimage.get("superseded_by"))
        or not _optional_identifier(preimage.get("recording_event_id"))
    ):
        return False
    for digest_field in (
        "evidence_content_sha256",
        "recording_event_sha256",
        "link_identity_sha256",
    ):
        value = preimage.get(digest_field)
        if value is not None and not _is_sha256(value):
            return False
    failures = preimage.get("health_failure_codes")
    if (
        not isinstance(failures, list)
        or any(not isinstance(item, str) for item in failures)
        or failures != sorted(set(failures))
        or not set(failures).issubset(_FIXED_CURRENT_PROOF_FAILURE_CODES)
    ):
        return False
    if snapshot.status == "healthy":
        return (
            preimage.get("feature_status") == "done"
            and preimage.get("evidence_type") in ADHOC_EVIDENCE_TYPES
            and preimage.get("superseded_by") is None
            and all(
                preimage.get(required_field) is not None
                for required_field in (
                    "evidence_id",
                    "evidence_content_sha256",
                    "recording_event_id",
                    "recording_event_sha256",
                    "link_identity_sha256",
                )
            )
            and failures == []
        )
    return bool(failures)


def _optional_identifier(value: Any, *, required: bool = False) -> bool:
    if value is None:
        return not required
    return isinstance(value, str) and bool(value) and "\0" not in value


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        return False
    return all(character in "0123456789abcdef" for character in value[7:])


def _nonspawn_result(
    *,
    packet_sha256: str,
    check_id: str,
    verdict: str,
    secret_environment: bool,
    authority_checkpoint_sha256s: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    stdout = StreamAccumulator(1)
    stderr = StreamAccumulator(1)
    stdout.eof = True
    stderr.eof = True
    logs = [
        stdout.public_log(
            packet_sha256=packet_sha256,
            check_id=check_id,
            stream="stdout",
            secret_environment=secret_environment,
        ),
        stderr.public_log(
            packet_sha256=packet_sha256,
            check_id=check_id,
            stream="stderr",
            secret_environment=secret_environment,
        ),
    ]
    receipt = _finalize_valid(
        {
            "contract_version": PROOF_CHECK_EXECUTION_RECEIPT_CONTRACT_VERSION,
            "packet_sha256": packet_sha256,
            "check_id": check_id,
            "authority_checkpoint_sha256s": list(authority_checkpoint_sha256s),
            "spawn": {"status": "not_attempted", "error_kind": None},
            "process": _not_started_process(),
            "stdout_log_sha256": logs[0]["log_sha256"],
            "stderr_log_sha256": logs[1]["log_sha256"],
            "reseal": {
                "status": "not_run",
                "before_manifest_sha256": None,
                "after_manifest_sha256": None,
                "effect_classification": None,
            },
            "proof_validity": "indeterminate" if verdict == "indeterminate" else "invalid" if verdict == "invalid" else "valid",
        }
    )
    result = _finalize_valid(
        {
            "contract_version": PROOF_CHECK_EXECUTION_RESULT_CONTRACT_VERSION,
            "packet_sha256": packet_sha256,
            "check_id": check_id,
            "receipt_sha256": receipt["receipt_sha256"],
            "verdict": verdict,
            "reuse_disposition": "fresh_only",
        }
    )
    return logs, receipt, result


def _bundle_receipt(
    packet: Mapping[str, Any],
    checkpoints: Sequence[Mapping[str, Any]],
    logs: Sequence[Mapping[str, Any]],
    receipts: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    aggregate: Mapping[str, Any],
) -> dict[str, Any]:
    objects = [
        {"role": "aggregate", "sha256": aggregate["aggregate_sha256"]},
        {"role": "packet", "sha256": packet["packet_sha256"]},
    ]
    objects.extend(
        {"role": f"authority:{index:04d}", "sha256": item["checkpoint_sha256"]}
        for index, item in enumerate(checkpoints)
    )
    objects.extend(
        {"role": f"log:{index:04d}", "sha256": item["log_sha256"]}
        for index, item in enumerate(logs)
    )
    objects.extend(
        {"role": f"receipt:{index:04d}", "sha256": item["receipt_sha256"]}
        for index, item in enumerate(receipts)
    )
    objects.extend(
        {"role": f"result:{index:04d}", "sha256": item["result_sha256"]}
        for index, item in enumerate(results)
    )
    objects.sort(key=lambda item: (item["role"], item["sha256"]))
    return _finalize_valid(
        {
            "contract_version": PROOF_EXECUTION_BUNDLE_RECEIPT_CONTRACT_VERSION,
            "packet_sha256": packet["packet_sha256"],
            "aggregate_sha256": aggregate["aggregate_sha256"],
            "objects": objects,
        }
    )


def _finalize_valid(value: Mapping[str, Any]) -> dict[str, Any]:
    finalized = finalize_proof_execution_document(value)
    validation = validate_proof_execution_document(finalized)
    if not validation.ok:
        raise ProofExecutionError(
            "Generated proof execution document failed its strict contract.",
            code="proof_execution_contract_invalid",
            details={"errors": list(validation.errors)},
        )
    return finalized


def _contains_secret_shape(content: bytes) -> bool:
    _, changed = redact_bytes(content)
    return changed


def _not_started_process() -> dict[str, Any]:
    return {
        "controller_cause": "not_started",
        "leader_kind": "not_started",
        "leader_value": None,
        "term_sent": False,
        "kill_sent": False,
        "pipes_eof": True,
        "group_quiescent": True,
    }


def _spawn_error_kind(exc: OSError) -> str:
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        return "not_found"
    if isinstance(exc, PermissionError) or exc.errno == errno.EACCES:
        return "permission_denied"
    return "os_error"


def _dominant(left: str, right: str) -> str:
    ordered = (*_VERDICT_PRECEDENCE, "passed")
    return min((left, right), key=ordered.index)


def _require_directory_identity(path: Path, expected: Any) -> None:
    current = _stat_identity_no_follow(path)
    if (
        current != expected
        or not stat.S_ISDIR(current.mode)
        or stat.S_ISLNK(current.mode)
    ):
        raise ProofWorkspaceError(
            "A canonical source authority directory changed.",
            code="proof_candidate_object_unavailable",
            details={},
        )


def _git_text_exact(
    root: Path,
    prepared: PreparedProofWorkspace,
    *args: str,
) -> str:
    completed = prepared._git.run(root, *args)
    if completed.returncode != 0:
        raise ProofWorkspaceError(
            "A canonical Git authority command failed.",
            code="proof_candidate_object_unavailable",
            details={},
        )
    try:
        return completed.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise ProofWorkspaceError(
            "A canonical Git authority result was not UTF-8.",
            code="proof_candidate_object_unavailable",
            details={},
        ) from exc
