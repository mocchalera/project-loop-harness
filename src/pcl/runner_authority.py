"""Parent-owned runner authority and its local PCL anchor.

The JSON receipt written by the runner is intentionally only a projection.  A
parent process freezes the execution inputs before spawning a child, observes
the child, and creates one immutable :class:`AuthoritySealDraft`.  Finish (or
another in-process supervisor) may then commit that draft through the normal
Evidence/event mutation path.  Nothing in this module can repair, adopt, or
re-sign an existing anchor.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .db import MutationConnection, connect_mutation, connect_read_only
from .errors import PclError
from .events import append_event
from .evidence import insert_evidence_link, record_inline_evidence
from .paths import ProjectPaths
from .test_faults import crash_if_requested
from .timeutil import utc_now_iso


RUNNER_AUTHORITY_CONTRACT_VERSION = "runner-authority/v1"
RUNNER_AUTHORITY_SNAPSHOT_CONTRACT_VERSION = "runner-authority-snapshot/v1"
RUNNER_AUTHORITY_ANCHOR_EVENT_TYPE = "runner_authority_anchor_committed"
RUNNER_AUTHORITY_ANCHOR_EVIDENCE_TYPE = "runner_authority_anchor"
RUNNER_AUTHORITY_ANCHOR_LINK_ROLE = "runner_authority_anchor"
MAX_RUNNER_FRAME_COUNT = 16_384

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_REQUIRED_SNAPSHOT_FIELDS = {
    "contract_version",
    "authority",
    "execution_instance_id",
    "attempt_id",
    "attempt_index",
    "previous",
    "requested_argv_sha256",
    "spawned_argv_sha256",
    "cwd_identity_sha256",
    "env_identity_sha256",
    "sidecar_policy",
    "snapshot_sha256",
}
_REQUIRED_POLICY_FIELDS = {"mode", "required_names", "paths"}
_REQUIRED_DRAFT_FIELDS = {
    "contract_version",
    "authority",
    "snapshot",
    "observations",
    "sidecars",
    "receipt_projection",
    "canonical_hashes",
    "gate_issues",
    "draft_sha256",
}
_REQUIRED_ANCHOR_FIELDS = {
    "contract_version",
    "anchor_id",
    "draft",
    "result_binding",
    "previous_anchor_id",
    "anchor_sha256",
}


class RunnerAuthorityError(PclError):
    """Raised when a parent authority draft or committed anchor is invalid."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "runner_authority_invalid",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            details=dict(details or {}),
        )


@dataclass(frozen=True)
class RunnerAuthoritySnapshot:
    """Frozen parent inputs captured before child spawn."""

    document: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self.document))

    def __getitem__(self, key: str) -> Any:
        return self.document[key]

    @property
    def snapshot_sha256(self) -> str:
        return str(self.document["snapshot_sha256"])


@dataclass(frozen=True)
class AuthoritySealDraft:
    """The one parent-created authority snapshot for an execution attempt."""

    document: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self.document))

    def __getitem__(self, key: str) -> Any:
        return self.document[key]

    @property
    def draft_sha256(self) -> str:
        return str(self.document["draft_sha256"])

    @property
    def snapshot(self) -> dict[str, Any]:
        return deepcopy(dict(self.document["snapshot"]))


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def hash_file(path: Path | str) -> str | None:
    try:
        with Path(path).open("rb") as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(65_536), b""):
                digest.update(chunk)
            return "sha256:" + digest.hexdigest()
    except OSError:
        return None


def _pair(previous_attempt_id: str | None, previous_receipt_sha256: str | None) -> dict[str, str] | None:
    if previous_attempt_id is None and previous_receipt_sha256 is None:
        return None
    if previous_attempt_id is None or previous_receipt_sha256 is None:
        raise RunnerAuthorityError(
            "Previous attempt ID and receipt hash must be supplied as one pair.",
            code="runner_authority_previous_pair_incomplete",
        )
    return {
        "attempt_id": str(previous_attempt_id),
        "receipt_sha256": str(previous_receipt_sha256),
    }


def normalize_sidecar_policy(
    policy: str | Mapping[str, Any] | None,
    *,
    summary_path: Path | str | None = None,
    events_path: Path | str | None = None,
) -> dict[str, Any]:
    """Freeze the policy and declared paths before spawn.

    Required paths are part of the parent snapshot.  A later verifier never
    takes an omitted caller path as permission to skip a required sidecar.
    """

    if policy is None:
        mode = "optional"
        required_names: list[str] = []
    elif isinstance(policy, str):
        mode = policy
        required_names = ["summary", "events"] if mode == "required" else []
    elif isinstance(policy, Mapping):
        mode = str(policy.get("mode") or ("required" if policy.get("required") else "optional"))
        raw_names = policy.get("required_names")
        required_names = (
            sorted({str(item) for item in raw_names})
            if isinstance(raw_names, Sequence) and not isinstance(raw_names, (str, bytes))
            else (["summary", "events"] if mode == "required" else [])
        )
    else:
        raise RunnerAuthorityError(
            "Runner sidecar policy must be a string or object.",
            code="runner_authority_policy_invalid",
        )
    if mode not in {"required", "optional", "not_applicable"}:
        raise RunnerAuthorityError(
            "Runner sidecar policy mode is invalid.",
            code="runner_authority_policy_invalid",
        )
    allowed_names = {"summary", "events"}
    if set(required_names) - allowed_names:
        raise RunnerAuthorityError(
            "Runner sidecar policy names are invalid.",
            code="runner_authority_policy_invalid",
            details={"required_names": required_names},
        )
    if mode == "required" and not required_names:
        raise RunnerAuthorityError(
            "A required sidecar policy must name at least one sidecar.",
            code="runner_authority_policy_invalid",
        )
    paths: dict[str, str | None] = {
        "summary": _path_text(summary_path),
        "events": _path_text(events_path),
    }
    for name in required_names:
        if not paths.get(name):
            raise RunnerAuthorityError(
                f"Required runner sidecar path is missing: {name}.",
                code="runner_authority_required_sidecar_path_missing",
                details={"sidecar": name},
            )
    return {
        "mode": mode,
        "required_names": required_names,
        "paths": paths,
    }


def create_runner_authority_snapshot(
    *,
    execution_instance_id: str,
    attempt_id: str,
    attempt_index: int,
    previous_attempt_id: str | None,
    previous_receipt_sha256: str | None,
    requested_argv_sha256: str,
    spawned_argv_sha256: str,
    cwd_identity_sha256: str,
    env_identity_sha256: str,
    sidecar_policy: Mapping[str, Any],
) -> RunnerAuthoritySnapshot:
    if not _IDENTIFIER.fullmatch(str(execution_instance_id)):
        raise RunnerAuthorityError(
            "execution_instance_id is invalid.",
            code="runner_authority_snapshot_invalid",
        )
    if not _IDENTIFIER.fullmatch(str(attempt_id)):
        raise RunnerAuthorityError(
            "attempt_id is invalid.",
            code="runner_authority_snapshot_invalid",
        )
    if type(attempt_index) is not int or attempt_index < 0:
        raise RunnerAuthorityError(
            "attempt_index must be a non-negative integer.",
            code="runner_authority_snapshot_invalid",
        )
    previous = _pair(previous_attempt_id, previous_receipt_sha256)
    if attempt_index == 0 and previous is not None:
        raise RunnerAuthorityError(
            "The first attempt cannot bind a previous attempt.",
            code="runner_authority_previous_pair_invalid",
        )
    if attempt_index > 0 and previous is None:
        raise RunnerAuthorityError(
            "A later attempt must bind its previous attempt as one pair.",
            code="runner_authority_previous_pair_incomplete",
        )
    document = {
        "contract_version": RUNNER_AUTHORITY_SNAPSHOT_CONTRACT_VERSION,
        "authority": "parent_supervisor",
        "execution_instance_id": str(execution_instance_id),
        "attempt_id": str(attempt_id),
        "attempt_index": attempt_index,
        "previous": previous,
        "requested_argv_sha256": str(requested_argv_sha256),
        "spawned_argv_sha256": str(spawned_argv_sha256),
        "cwd_identity_sha256": str(cwd_identity_sha256),
        "env_identity_sha256": str(env_identity_sha256),
        "sidecar_policy": deepcopy(dict(sidecar_policy)),
        "snapshot_sha256": "",
    }
    document["snapshot_sha256"] = canonical_hash(
        {key: value for key, value in document.items() if key != "snapshot_sha256"}
    )
    result = RunnerAuthoritySnapshot(document=document)
    errors = validate_runner_authority_snapshot(result.to_dict())
    if errors:
        raise RunnerAuthorityError(
            "Parent authority snapshot is invalid.",
            code="runner_authority_snapshot_invalid",
            details={"issues": errors},
        )
    return result


def build_authority_seal_draft(
    *,
    snapshot: RunnerAuthoritySnapshot,
    observations: Mapping[str, Any],
    sidecar_paths: Mapping[str, Path | str | None] | None = None,
    receipt_path: Path | str | None = None,
    receipt: Mapping[str, Any] | None = None,
) -> AuthoritySealDraft:
    sidecars = {
        name: _file_observation(path)
        for name, path in sorted((sidecar_paths or {}).items())
        if name in {"summary", "events"} and path is not None
    }
    receipt_projection = None
    if receipt_path is not None or receipt is not None:
        receipt_file_sha256 = hash_file(receipt_path) if receipt_path is not None else None
        receipt_projection = {
            "path": _path_text(receipt_path),
            "content_sha256": (
                str(receipt.get("receipt_sha256"))
                if isinstance(receipt, Mapping) and receipt.get("receipt_sha256") is not None
                else None
            ),
            "file_sha256": receipt_file_sha256,
            "sha256": receipt_file_sha256,
            "identity": _file_identity(receipt_path),
        }
    normalized_observations = deepcopy(dict(observations))
    gate_issues = authority_gate_issues(
        snapshot=snapshot.to_dict(),
        observations=normalized_observations,
        sidecars=sidecars,
    )
    canonical_hashes = {
        "snapshot_sha256": snapshot.snapshot_sha256,
        "observations_sha256": canonical_hash(normalized_observations),
        "sidecars_sha256": canonical_hash(sidecars),
    }
    document = {
        "contract_version": RUNNER_AUTHORITY_CONTRACT_VERSION,
        "authority": "parent_supervisor",
        "snapshot": snapshot.to_dict(),
        "observations": normalized_observations,
        "sidecars": sidecars,
        "receipt_projection": receipt_projection,
        "canonical_hashes": canonical_hashes,
        "gate_issues": sorted(set(gate_issues)),
        "draft_sha256": "",
    }
    document["draft_sha256"] = canonical_hash(
        {key: value for key, value in document.items() if key != "draft_sha256"}
    )
    result = AuthoritySealDraft(document=document)
    structural = validate_authority_seal_draft(result.to_dict())
    structural = [issue for issue in structural if not issue.startswith("gate:")]
    if structural:
        raise RunnerAuthorityError(
            "Parent authority seal draft is structurally invalid.",
            code="runner_authority_draft_invalid",
            details={"issues": structural},
        )
    return result


def authority_gate_issues(
    *,
    snapshot: Mapping[str, Any],
    observations: Mapping[str, Any],
    sidecars: Mapping[str, Any],
) -> list[str]:
    issues: list[str] = []
    frames = observations.get("frames") if isinstance(observations.get("frames"), Mapping) else {}
    sequence = frames.get("sequence")
    dropped_count = frames.get("dropped_count")
    if (isinstance(sequence, int) and sequence > MAX_RUNNER_FRAME_COUNT) or frames.get("limit_exceeded") is True:
        issues.append("gate:frame_count_exceeded")
    if isinstance(dropped_count, int) and dropped_count != 0:
        issues.append("gate:frames_dropped")
    if frames.get("partial") is True:
        issues.append("gate:partial_frame")
    if frames.get("reader_error") is True:
        issues.append("gate:frame_reader_error")
    policy_value = snapshot.get("sidecar_policy")
    policy_mode = policy_value.get("mode") if isinstance(policy_value, Mapping) else None
    if frames.get("eof") is not True and policy_mode != "not_applicable":
        issues.append("gate:frame_eof_missing")

    policy = snapshot.get("sidecar_policy")
    if isinstance(policy, Mapping) and policy.get("mode") == "required":
        for name in policy.get("required_names", []):
            item = sidecars.get(str(name))
            if not isinstance(item, Mapping) or not _is_sha(item.get("sha256")):
                issues.append(f"gate:required_sidecar_missing:{name}")
    spawn_value = observations.get("spawn")
    spawn = spawn_value if isinstance(spawn_value, Mapping) else {}
    termination_value = observations.get("termination")
    termination = termination_value if isinstance(termination_value, Mapping) else {}
    streams = observations.get("streams") if isinstance(observations.get("streams"), Mapping) else {}
    timed_out = observations.get("timed_out") is True
    if spawn.get("status") == "spawned":
        if not isinstance(termination_value, Mapping):
            issues.append("gate:termination_missing")
        if timed_out and observations.get("exit_code") is not None:
            issues.append("contradiction:timeout_exit_code")
        if timed_out and termination.get("requested") is not True:
            issues.append("contradiction:timeout_without_termination")
        if timed_out and termination.get("method") == "process_exit":
            issues.append("contradiction:timeout_process_exit_method")
        if not timed_out and termination.get("requested") is True:
            issues.append("contradiction:termination_without_timeout")
        if termination.get("pipes_eof") is not None and termination.get("pipes_eof") != (
            streams.get("stdout_eof") is True and streams.get("stderr_eof") is True
        ):
            issues.append("contradiction:pipes_eof_mismatch")
        if isinstance(termination_value, Mapping):
            if termination.get("pipes_eof") is not True:
                issues.append("gate:stdout_stderr_eof_missing")
            group_state = termination.get("group_state")
            if group_state not in {"gone", "not_applicable"}:
                issues.append("gate:process_group_uncertain")
            if group_state == "not_started":
                issues.append("contradiction:spawned_not_started")
    elif spawn.get("status") == "failed":
        if timed_out or observations.get("exit_code") is not None:
            issues.append("contradiction:failed_spawn_with_process_state")
        if termination.get("requested") is True:
            issues.append("contradiction:failed_spawn_terminated")
        if termination.get("group_state") not in {None, "not_started", "not_applicable"}:
            issues.append("contradiction:failed_spawn_group_state")
    else:
        issues.append("contradiction:spawn_state_invalid")
    return sorted(set(issues))


def validate_runner_authority_snapshot(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return ["$:must_be_object"]
    errors.extend(_exact_fields(value, _REQUIRED_SNAPSHOT_FIELDS, "$"))
    if value.get("contract_version") != RUNNER_AUTHORITY_SNAPSHOT_CONTRACT_VERSION:
        errors.append("$.contract_version:mismatch")
    if value.get("authority") != "parent_supervisor":
        errors.append("$.authority:not_parent")
    for field in ("execution_instance_id", "attempt_id"):
        if not isinstance(value.get(field), str) or _IDENTIFIER.fullmatch(value[field]) is None:
            errors.append(f"$.{field}:invalid")
    if type(value.get("attempt_index")) is not int or value.get("attempt_index", -1) < 0:
        errors.append("$.attempt_index:invalid")
    previous = value.get("previous")
    if previous is not None:
        if not isinstance(previous, Mapping) or set(previous) != {"attempt_id", "receipt_sha256"}:
            errors.append("$.previous:must_be_inseparable_pair")
        else:
            if not isinstance(previous.get("attempt_id"), str) or _IDENTIFIER.fullmatch(previous["attempt_id"]) is None:
                errors.append("$.previous.attempt_id:invalid")
            if not _is_sha(previous.get("receipt_sha256")):
                errors.append("$.previous.receipt_sha256:invalid")
    if value.get("attempt_index") == 0 and previous is not None:
        errors.append("$.previous:first_attempt_must_be_empty")
    if isinstance(value.get("attempt_index"), int) and value["attempt_index"] > 0 and previous is None:
        errors.append("$.previous:required_for_later_attempt")
    for field in (
        "requested_argv_sha256",
        "spawned_argv_sha256",
        "cwd_identity_sha256",
        "env_identity_sha256",
    ):
        if not _is_sha(value.get(field)):
            errors.append(f"$.{field}:invalid")
    policy = value.get("sidecar_policy")
    if not isinstance(policy, Mapping):
        errors.append("$.sidecar_policy:invalid")
    else:
        errors.extend(_exact_fields(policy, _REQUIRED_POLICY_FIELDS, "$.sidecar_policy"))
        if policy.get("mode") not in {"required", "optional", "not_applicable"}:
            errors.append("$.sidecar_policy.mode:invalid")
        names = policy.get("required_names")
        if not isinstance(names, list) or any(item not in {"summary", "events"} for item in names):
            errors.append("$.sidecar_policy.required_names:invalid")
        paths = policy.get("paths")
        if not isinstance(paths, Mapping) or set(paths) != {"summary", "events"}:
            errors.append("$.sidecar_policy.paths:invalid")
        elif any(path is not None and not isinstance(path, str) for path in paths.values()):
            errors.append("$.sidecar_policy.paths:invalid_value")
    expected_hash = canonical_hash({key: value[key] for key in value if key != "snapshot_sha256"}) if "snapshot_sha256" in value else None
    if not _is_sha(value.get("snapshot_sha256")) or value.get("snapshot_sha256") != expected_hash:
        errors.append("$.snapshot_sha256:mismatch")
    return sorted(set(errors))


def validate_authority_seal_draft(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return ["$:must_be_object"]
    errors.extend(_exact_fields(value, _REQUIRED_DRAFT_FIELDS, "$"))
    if value.get("contract_version") != RUNNER_AUTHORITY_CONTRACT_VERSION:
        errors.append("$.contract_version:mismatch")
    if value.get("authority") != "parent_supervisor":
        errors.append("$.authority:not_parent")
    snapshot = value.get("snapshot")
    errors.extend(f"draft:{issue}" for issue in validate_runner_authority_snapshot(snapshot))
    for field in ("observations", "sidecars", "canonical_hashes"):
        if not isinstance(value.get(field), Mapping):
            errors.append(f"$.{field}:invalid")
    observations = value.get("observations")
    if isinstance(observations, Mapping):
        spawn = observations.get("spawn")
        if not isinstance(spawn, Mapping) or spawn.get("status") not in {"not_attempted", "spawned", "failed"}:
            errors.append("$.observations.spawn:invalid")
        frames = observations.get("frames")
        if not isinstance(frames, Mapping):
            errors.append("$.observations.frames:invalid")
        else:
            if type(frames.get("sequence")) is not int or frames.get("sequence", -1) < 0:
                errors.append("$.observations.frames.sequence:invalid")
            if not _is_sha(frames.get("root_sha256")):
                errors.append("$.observations.frames.root_sha256:invalid")
            if type(frames.get("dropped_count")) is not int or frames.get("dropped_count", -1) < 0:
                errors.append("$.observations.frames.dropped_count:invalid")
            for field in ("partial", "reader_error", "eof", "limit_exceeded"):
                if type(frames.get(field)) is not bool:
                    errors.append(f"$.observations.frames.{field}:invalid")
        streams = observations.get("streams")
        if not isinstance(streams, Mapping):
            errors.append("$.observations.streams:invalid")
        else:
            for field in ("stdout_eof", "stderr_eof"):
                if type(streams.get(field)) is not bool:
                    errors.append(f"$.observations.streams.{field}:invalid")
        termination = observations.get("termination")
        if termination is not None and not isinstance(termination, Mapping):
            errors.append("$.observations.termination:invalid")
    sidecars = value.get("sidecars")
    if isinstance(sidecars, Mapping):
        for name, item in sidecars.items():
            if name not in {"summary", "events"} or not isinstance(item, Mapping):
                errors.append(f"$.sidecars.{name}:invalid")
                continue
            if not isinstance(item.get("path"), str) or not item.get("path"):
                errors.append(f"$.sidecars.{name}.path:invalid")
            if not _is_sha(item.get("sha256")):
                errors.append(f"$.sidecars.{name}.sha256:invalid")
            if item.get("identity") is not None and not isinstance(item.get("identity"), Mapping):
                errors.append(f"$.sidecars.{name}.identity:invalid")
    receipt_projection = value.get("receipt_projection")
    if receipt_projection is not None and not isinstance(receipt_projection, Mapping):
        errors.append("$.receipt_projection:invalid")
    elif isinstance(receipt_projection, Mapping):
        if not isinstance(receipt_projection.get("path"), str) or not receipt_projection.get("path"):
            errors.append("$.receipt_projection.path:invalid")
        for field in ("content_sha256", "file_sha256", "sha256"):
            if not _is_sha(receipt_projection.get(field)):
                errors.append(f"$.receipt_projection.{field}:invalid")
        if receipt_projection.get("identity") is not None and not isinstance(receipt_projection.get("identity"), Mapping):
            errors.append("$.receipt_projection.identity:invalid")
    gate_issues = value.get("gate_issues")
    if not isinstance(gate_issues, list) or any(not isinstance(item, str) for item in gate_issues):
        errors.append("$.gate_issues:invalid")
    hashes = value.get("canonical_hashes")
    if isinstance(hashes, Mapping):
        for field in ("snapshot_sha256", "observations_sha256", "sidecars_sha256"):
            if not _is_sha(hashes.get(field)):
                errors.append(f"$.canonical_hashes.{field}:invalid")
        if isinstance(snapshot, Mapping) and hashes.get("snapshot_sha256") != snapshot.get("snapshot_sha256"):
            errors.append("$.canonical_hashes.snapshot_sha256:mismatch")
        if isinstance(value.get("observations"), Mapping) and hashes.get("observations_sha256") != canonical_hash(value["observations"]):
            errors.append("$.canonical_hashes.observations_sha256:mismatch")
        if isinstance(value.get("sidecars"), Mapping) and hashes.get("sidecars_sha256") != canonical_hash(value["sidecars"]):
            errors.append("$.canonical_hashes.sidecars_sha256:mismatch")
    if (
        isinstance(snapshot, Mapping)
        and isinstance(observations, Mapping)
        and isinstance(sidecars, Mapping)
        and isinstance(gate_issues, list)
    ):
        derived_gates = authority_gate_issues(
            snapshot=snapshot,
            observations=observations,
            sidecars=sidecars,
        )
        if sorted(str(item) for item in gate_issues) != sorted(derived_gates):
            errors.append("$.gate_issues:mismatch")
    if isinstance(value.get("draft_sha256"), str):
        expected = canonical_hash({key: value[key] for key in value if key != "draft_sha256"})
        if value.get("draft_sha256") != expected:
            errors.append("$.draft_sha256:mismatch")
    else:
        errors.append("$.draft_sha256:invalid")
    return sorted(set(errors))


def persist_runner_authority_anchor(
    paths: ProjectPaths,
    *,
    draft: AuthoritySealDraft | Mapping[str, Any],
    expected_inputs: Mapping[str, Any],
    result_binding: Mapping[str, Any] | None = None,
    target: Mapping[str, str] | None = None,
    conn: MutationConnection | sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Commit exactly one new immutable runner anchor through PCL services."""

    draft_document = _draft_document(draft)
    structural = validate_authority_seal_draft(draft_document)
    structural = [issue for issue in structural if not issue.startswith("gate:")]
    if structural:
        raise RunnerAuthorityError(
            "Cannot persist an invalid runner authority draft.",
            code="runner_authority_draft_invalid",
            details={"issues": structural},
        )
    contradictions = [
        issue
        for issue in draft_document.get("gate_issues", [])
        if isinstance(issue, str) and issue.startswith("contradiction:")
    ]
    if contradictions:
        raise RunnerAuthorityError(
            "Cannot persist contradictory runner authority observations.",
            code="runner_authority_observation_contradiction",
            details={"issues": contradictions},
        )
    expected = _expected_snapshot(expected_inputs)
    if canonical_json(expected) != canonical_json(draft_document["snapshot"]):
        raise RunnerAuthorityError(
            "Caller expected inputs do not match the parent authority snapshot.",
            code="runner_authority_expected_input_mismatch",
        )
    normalized_result = _normalize_binding(paths, result_binding, name="result")
    previous_anchor_id: str | None = None
    owns_connection = conn is None
    active_conn = conn or connect_mutation(paths)
    try:
        records = _read_anchor_records(active_conn, execution_instance_id=str(expected["execution_instance_id"]))
        current_attempt = next(
            (record for record in records if record["attempt_index"] == expected["attempt_index"]),
            None,
        )
        if current_attempt is not None:
            anchor_id = _anchor_id(draft_document, normalized_result, current_attempt.get("previous_anchor_id"))
            if current_attempt["anchor_id"] == anchor_id and _record_matches(current_attempt, draft_document, normalized_result):
                if owns_connection:
                    active_conn.rollback()
                return _anchor_result(current_attempt, changed=False, idempotent=True)
            raise RunnerAuthorityError(
                "Runner authority attempt already has a different committed anchor.",
                code="runner_authority_anchor_fork",
                details={"attempt_index": expected["attempt_index"]},
            )
        if expected["attempt_index"] == 0:
            if records:
                raise RunnerAuthorityError(
                    "Attempt zero cannot be appended after another attempt.",
                    code="runner_authority_anchor_gap",
                )
        else:
            predecessors = [
                record
                for record in records
                if record["attempt_index"] == expected["attempt_index"] - 1
            ]
            if len(predecessors) != 1:
                raise RunnerAuthorityError(
                    "Runner authority predecessor is missing or forked.",
                    code=("runner_authority_anchor_gap" if not predecessors else "runner_authority_anchor_fork"),
                )
            predecessor = predecessors[0]
            previous_anchor_id = predecessor["anchor_id"]
            predecessor_verification = verify_runner_authority_anchor_in_snapshot(
                paths,
                active_conn,
                anchor_id=previous_anchor_id,
                expected_inputs=predecessor["draft"]["snapshot"],
            )
            if predecessor_verification.get("ok") is not True:
                raise RunnerAuthorityError(
                    "Committed predecessor runner authority anchor is no longer valid.",
                    code="runner_authority_predecessor_invalid",
                    details={"issues": predecessor_verification.get("issues", [])},
                )
            previous = expected["previous"]
            predecessor_projection = predecessor["draft"].get("receipt_projection")
            predecessor_receipt_sha256 = (
                predecessor_projection.get("content_sha256")
                if isinstance(predecessor_projection, Mapping)
                else None
            )
            if (
                not isinstance(previous, Mapping)
                or previous.get("attempt_id") != predecessor["attempt_id"]
                or previous.get("receipt_sha256") != predecessor_receipt_sha256
            ):
                raise RunnerAuthorityError(
                    "Previous attempt ID and receipt hash do not bind the committed predecessor.",
                    code="runner_authority_previous_pair_mismatch",
                )
        anchor_id = _anchor_id(draft_document, normalized_result, previous_anchor_id)
        anchor = {
            "contract_version": RUNNER_AUTHORITY_CONTRACT_VERSION,
            "anchor_id": anchor_id,
            "draft": draft_document,
            "result_binding": normalized_result,
            "previous_anchor_id": previous_anchor_id,
            "anchor_sha256": "",
        }
        anchor["anchor_sha256"] = canonical_hash(
            {key: value for key, value in anchor.items() if key != "anchor_sha256"}
        )
        errors = validate_authority_anchor(anchor)
        if errors:
            raise RunnerAuthorityError(
                "Runner authority anchor is invalid.",
                code="runner_authority_anchor_invalid",
                details={"issues": errors},
            )
        evidence_summary = canonical_json(anchor)
        evidence_id = record_inline_evidence(
            active_conn,
            evidence_type=RUNNER_AUTHORITY_ANCHOR_EVIDENCE_TYPE,
            summary=evidence_summary,
            context=f"runner-authority:{anchor_id}",
            command="pcl finish --emit-packet" if normalized_result is not None else "pcl runner authority",
        )
        crash_if_requested("runner_authority_after_evidence")
        if target is not None:
            insert_evidence_link(
                active_conn,
                evidence_id=evidence_id,
                target_type=str(target["type"]),
                target_id=str(target["id"]),
                link_role=RUNNER_AUTHORITY_ANCHOR_LINK_ROLE,
                created_at=utc_now_iso(),
            )
        payload = {
            "contract_version": RUNNER_AUTHORITY_CONTRACT_VERSION,
            "anchor_id": anchor_id,
            "anchor_sha256": anchor["anchor_sha256"],
            "draft_sha256": draft_document["draft_sha256"],
            "execution_instance_id": expected["execution_instance_id"],
            "attempt_id": expected["attempt_id"],
            "attempt_index": expected["attempt_index"],
            "previous": deepcopy(expected["previous"]),
            "previous_anchor_id": previous_anchor_id,
            "draft": draft_document,
            "result_binding": normalized_result,
            "evidence_id": evidence_id,
        }
        crash_if_requested("runner_authority_before_event")
        event_id = _event_id(anchor_id)
        append_event(
            conn=active_conn,
            events_path=paths.events_path,
            event_type=RUNNER_AUTHORITY_ANCHOR_EVENT_TYPE,
            entity_type="runner_execution",
            entity_id=str(expected["execution_instance_id"]),
            payload=payload,
            event_id=event_id,
            created_at=None,
        )
        crash_if_requested("runner_authority_after_event_before_commit")
        if owns_connection:
            active_conn.commit()
        return {
            "ok": True,
            "status": "anchored",
            "changed": True,
            "idempotent": False,
            "anchor_id": anchor_id,
            "event_id": event_id,
            "evidence_id": evidence_id,
            "anchor_sha256": anchor["anchor_sha256"],
            "draft_sha256": draft_document["draft_sha256"],
            "gate_issues": list(draft_document.get("gate_issues", [])),
        }
    except RunnerAuthorityError:
        if owns_connection and active_conn.in_transaction:
            active_conn.rollback()
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        if owns_connection and active_conn.in_transaction:
            active_conn.rollback()
        raise RunnerAuthorityError(
            f"Could not persist runner authority anchor: {exc}",
            code="runner_authority_anchor_persist_failed",
        ) from exc
    finally:
        if owns_connection:
            active_conn.close()


def verify_runner_authority_anchor(
    paths: ProjectPaths,
    *,
    anchor_id: str,
    expected_inputs: Mapping[str, Any],
    result_path: Path | str | None = None,
    receipt_path: Path | str | None = None,
) -> dict[str, Any]:
    conn = connect_read_only(paths.db_path)
    try:
        return verify_runner_authority_anchor_in_snapshot(
            paths,
            conn,
            anchor_id=anchor_id,
            expected_inputs=expected_inputs,
            result_path=result_path,
            receipt_path=receipt_path,
        )
    finally:
        conn.close()


def verify_runner_authority_anchor_in_snapshot(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    anchor_id: str,
    expected_inputs: Mapping[str, Any],
    result_path: Path | str | None = None,
    receipt_path: Path | str | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    expected = _expected_snapshot(expected_inputs)
    records = _read_anchor_records(conn, execution_instance_id=str(expected["execution_instance_id"]))
    matches = [record for record in records if record["anchor_id"] == anchor_id]
    if len(matches) != 1:
        issues.append("anchor_missing" if not matches else "anchor_ambiguous")
        return _verification_result(issues, anchor_id=anchor_id)
    record = matches[0]
    issues.extend(validate_authority_anchor(record["anchor"]))
    draft_gate_issues = record["draft"].get("gate_issues", [])
    if isinstance(draft_gate_issues, list):
        issues.extend(str(issue) for issue in draft_gate_issues)
    if canonical_json(expected) != canonical_json(record["draft"]["snapshot"]):
        issues.append("expected_inputs_mismatch")
    issues.extend(_validate_anchor_chain(records, record))
    issues.extend(_verify_anchor_files(paths, record, result_path=result_path, receipt_path=receipt_path))
    evidence_id = record.get("evidence_id")
    evidence = conn.execute(
        "SELECT id, type, path, summary FROM evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if evidence is None:
        issues.append("evidence_missing")
    else:
        if evidence["type"] != RUNNER_AUTHORITY_ANCHOR_EVIDENCE_TYPE:
            issues.append("evidence_type_mismatch")
        if evidence["path"] != f"inline:runner-authority:{anchor_id}":
            issues.append("evidence_path_mismatch")
        try:
            evidence_anchor = json.loads(str(evidence["summary"]))
        except (TypeError, json.JSONDecodeError):
            evidence_anchor = None
            issues.append("evidence_summary_invalid")
        if evidence_anchor != record["anchor"]:
            issues.append("evidence_summary_mismatch")
    return _verification_result(issues, anchor_id=anchor_id, record=record)


def validate_authority_anchor(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return ["anchor:must_be_object"]
    errors.extend(_exact_fields(value, _REQUIRED_ANCHOR_FIELDS, "anchor"))
    if value.get("contract_version") != RUNNER_AUTHORITY_CONTRACT_VERSION:
        errors.append("anchor:contract_mismatch")
    draft = value.get("draft")
    draft_errors = validate_authority_seal_draft(draft)
    errors.extend(f"anchor:{issue}" for issue in draft_errors if not issue.startswith("gate:"))
    previous = value.get("previous_anchor_id")
    if previous is not None and (not isinstance(previous, str) or not previous.startswith("RA-")):
        errors.append("anchor:previous_anchor_id_invalid")
    result_binding = value.get("result_binding")
    if result_binding is not None and not isinstance(result_binding, Mapping):
        errors.append("anchor:result_binding_invalid")
    if not isinstance(value.get("anchor_sha256"), str):
        errors.append("anchor:anchor_sha256_invalid")
    else:
        expected = canonical_hash({key: value[key] for key in value if key != "anchor_sha256"})
        if value.get("anchor_sha256") != expected:
            errors.append("anchor:anchor_sha256_mismatch")
    return sorted(set(errors))


def _verify_anchor_files(
    paths: ProjectPaths,
    record: Mapping[str, Any],
    *,
    result_path: Path | str | None,
    receipt_path: Path | str | None,
) -> list[str]:
    issues: list[str] = []
    draft = record["draft"]
    policy = draft["snapshot"].get("sidecar_policy", {})
    sidecars = draft.get("sidecars", {})
    for name in policy.get("required_names", []) if isinstance(policy, Mapping) else []:
        item = sidecars.get(str(name))
        if not isinstance(item, Mapping):
            issues.append(f"required_sidecar_omitted:{name}")
    for name, item in sidecars.items():
        issues.extend(_verify_bound_file(paths, item, label=f"sidecar:{name}"))
    projection = draft.get("receipt_projection")
    if isinstance(projection, Mapping):
        if receipt_path is not None and _canonical_relative(paths.root, receipt_path) != projection.get("path"):
            issues.append("receipt_path_mismatch")
        issues.extend(_verify_bound_file(paths, projection, label="receipt_projection"))
        actual_receipt = _read_json_file(_bound_path(paths, projection.get("path")))
        if not isinstance(actual_receipt, Mapping) or actual_receipt.get("receipt_sha256") != projection.get("content_sha256"):
            issues.append("receipt_projection_content_mismatch")
    binding = record.get("anchor", {}).get("result_binding")
    if isinstance(binding, Mapping):
        if result_path is not None and _canonical_relative(paths.root, result_path) != binding.get("path"):
            issues.append("result_path_mismatch")
        issues.extend(_verify_bound_file(paths, binding, label="result"))
        if binding.get("evidence_id"):
            # The evidence row is checked by the caller; this keeps the result
            # path/hash check independent of result.json's own contents.
            pass
    return sorted(set(issues))


def _verify_bound_file(paths: ProjectPaths, item: Mapping[str, Any], *, label: str) -> list[str]:
    issues: list[str] = []
    path_value = item.get("path")
    if not isinstance(path_value, str) or not path_value:
        return [f"{label}:path_missing"]
    path = _bound_path(paths, path_value)
    if path is None:
        return [f"{label}:path_invalid"]
    try:
        stat = path.lstat()
    except OSError:
        return [f"{label}:missing"]
    if path.is_symlink():
        issues.append(f"{label}:symlink")
    if stat.st_nlink != 1:
        issues.append(f"{label}:hardlink")
    expected_identity = item.get("identity")
    if isinstance(expected_identity, Mapping):
        actual_identity = _file_identity(path)
        if actual_identity != expected_identity:
            issues.append(f"{label}:identity_mismatch")
    actual_sha = hash_file(path)
    if actual_sha != item.get("sha256"):
        issues.append(f"{label}:hash_mismatch")
    return issues


def _validate_anchor_chain(records: list[dict[str, Any]], current: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    by_index: dict[int, list[dict[str, Any]]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        by_index.setdefault(int(record["attempt_index"]), []).append(record)
        if record["anchor_id"] in by_id:
            issues.append("anchor_cycle")
        by_id[record["anchor_id"]] = record
    for index, rows in by_index.items():
        if len(rows) > 1:
            issues.append("anchor_fork")
        if index == 0:
            if any(row.get("previous_anchor_id") is not None for row in rows):
                issues.append("anchor_cycle")
            continue
        for row in rows:
            predecessor_id = row.get("previous_anchor_id")
            predecessor = by_id.get(predecessor_id)
            if predecessor is None:
                issues.append("anchor_gap")
            elif predecessor["attempt_index"] != index - 1:
                issues.append("anchor_cycle")
    return sorted(set(issues))


def _read_anchor_records(conn: sqlite3.Connection, *, execution_instance_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, entity_id, payload_json
        FROM events
        WHERE event_type = ? AND entity_type = 'runner_execution' AND entity_id = ?
        ORDER BY sequence, id
        """,
        (RUNNER_AUTHORITY_ANCHOR_EVENT_TYPE, execution_instance_id),
    ).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        draft = payload.get("draft")
        anchor_id = payload.get("anchor_id")
        if not isinstance(draft, Mapping) or not isinstance(anchor_id, str):
            continue
        records.append(
            {
                "event_id": str(row["id"]),
                "anchor_id": anchor_id,
                "evidence_id": payload.get("evidence_id"),
                "attempt_id": draft.get("snapshot", {}).get("attempt_id"),
                "attempt_index": draft.get("snapshot", {}).get("attempt_index"),
                "previous_anchor_id": payload.get("previous_anchor_id"),
                "draft": deepcopy(dict(draft)),
                "anchor": {
                    "contract_version": payload.get("contract_version"),
                    "anchor_id": anchor_id,
                    "draft": deepcopy(dict(draft)),
                    "result_binding": deepcopy(payload.get("result_binding")),
                    "previous_anchor_id": payload.get("previous_anchor_id"),
                    "anchor_sha256": payload.get("anchor_sha256"),
                },
                "result_binding": deepcopy(payload.get("result_binding")),
                "anchor_sha256": payload.get("anchor_sha256"),
            }
        )
    return records


def _record_matches(record: Mapping[str, Any], draft: Mapping[str, Any], result_binding: Mapping[str, Any] | None) -> bool:
    return (
        record.get("draft") == draft
        and record.get("result_binding") == result_binding
        and record.get("anchor_sha256") == record.get("anchor", {}).get("anchor_sha256")
    )


def _anchor_result(record: Mapping[str, Any], *, changed: bool, idempotent: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "already_anchored" if idempotent else "anchored",
        "changed": changed,
        "idempotent": idempotent,
        "anchor_id": record["anchor_id"],
        "event_id": record.get("event_id"),
        "evidence_id": record.get("evidence_id"),
        "anchor_sha256": record.get("anchor_sha256"),
        "draft_sha256": record.get("draft", {}).get("draft_sha256"),
        "gate_issues": list(record.get("draft", {}).get("gate_issues", [])),
    }


def _verification_result(
    issues: list[str], *, anchor_id: str, record: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    unique = sorted(set(str(issue) for issue in issues))
    return {
        "ok": not unique and record is not None,
        "failure_kind": None if not unique else "runner_authority_invalid",
        "issues": unique,
        "anchor_id": anchor_id,
        "evidence_id": None if record is None else record.get("evidence_id"),
        "anchor_sha256": None if record is None else record.get("anchor_sha256"),
    }


def _draft_document(value: AuthoritySealDraft | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, AuthoritySealDraft):
        return value.to_dict()
    return deepcopy(dict(value))


def _expected_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RunnerAuthorityError(
            "Caller expected authority inputs are required.",
            code="runner_authority_expected_inputs_missing",
        )
    candidate = deepcopy(dict(value))
    if "snapshot" in candidate and isinstance(candidate["snapshot"], Mapping):
        candidate = deepcopy(dict(candidate["snapshot"]))
    errors = validate_runner_authority_snapshot(candidate)
    if errors:
        raise RunnerAuthorityError(
            "Caller expected authority inputs are invalid.",
            code="runner_authority_expected_inputs_invalid",
            details={"issues": errors},
        )
    return candidate


def _normalize_binding(
    paths: ProjectPaths,
    value: Mapping[str, Any] | None,
    *,
    name: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RunnerAuthorityError(
            f"{name} binding must be an object.",
            code="runner_authority_binding_invalid",
        )
    path_value = value.get("path")
    sha_value = value.get("sha256")
    if not isinstance(path_value, str) or not path_value or not _is_sha(sha_value):
        raise RunnerAuthorityError(
            f"{name} binding must include a path and sha256.",
            code="runner_authority_binding_invalid",
        )
    normalized = {
        "path": _canonical_relative(paths.root, path_value),
        "sha256": sha_value,
        "identity": _file_identity(_bound_path(paths, path_value)),
    }
    for optional in ("evidence_id", "kind"):
        if optional in value:
            normalized[optional] = value[optional]
    return normalized


def _path_text(path: Path | str | None) -> str | None:
    return None if path is None else str(path)


def _file_identity(path: Path | str | None) -> dict[str, int] | None:
    if path is None:
        return None
    try:
        stat = Path(path).lstat()
    except OSError:
        return None
    return {
        "device": int(stat.st_dev),
        "inode": int(stat.st_ino),
        "size_bytes": int(stat.st_size),
        "nlink": int(stat.st_nlink),
    }


def _file_observation(path: Path | str | None) -> dict[str, Any]:
    return {
        "path": _path_text(path),
        "sha256": hash_file(path) if path is not None else None,
        "identity": _file_identity(path),
    }


def _canonical_relative(root: Path, value: Path | str) -> str:
    path = Path(value)
    if path.is_absolute():
        try:
            # Keep symlink identity visible to verification.  Lexical
            # containment is checked here; _verify_bound_file uses lstat() to
            # reject a symlink or hardlink replacement.
            relative = path.absolute().relative_to(root.absolute())
        except ValueError as exc:
            raise RunnerAuthorityError(
                "Runner authority artifact is outside the project root.",
                code="runner_authority_path_outside_root",
            ) from exc
    else:
        relative = path
    normalized = Path(relative)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise RunnerAuthorityError(
            "Runner authority artifact path escapes the project root.",
            code="runner_authority_path_invalid",
        )
    return normalized.as_posix()


def _bound_path(paths: ProjectPaths, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        relative = _canonical_relative(paths.root, value)
    except RunnerAuthorityError:
        return None
    return paths.root / relative


def _read_json_file(path: Path | None) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _anchor_id(draft: Mapping[str, Any], result_binding: Mapping[str, Any] | None, previous_anchor_id: str | None) -> str:
    return "RA-" + hashlib.sha256(
        canonical_json(
            {
                "draft_sha256": draft.get("draft_sha256"),
                "result_binding": result_binding,
                "previous_anchor_id": previous_anchor_id,
            }
        ).encode("utf-8")
    ).hexdigest()[:48]


def _event_id(anchor_id: str) -> str:
    return "EV-" + anchor_id.removeprefix("RA-")[:12].upper()


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _exact_fields(value: Mapping[str, Any], fields: set[str], path: str) -> list[str]:
    missing = [f"{path}.{field}:missing" for field in sorted(fields - set(value))]
    extra = [f"{path}.{field}:unexpected" for field in sorted(set(value) - fields)]
    return missing + extra


__all__ = [
    "AuthoritySealDraft",
    "MAX_RUNNER_FRAME_COUNT",
    "RUNNER_AUTHORITY_ANCHOR_EVENT_TYPE",
    "RUNNER_AUTHORITY_ANCHOR_EVIDENCE_TYPE",
    "RunnerAuthorityError",
    "RunnerAuthoritySnapshot",
    "authority_gate_issues",
    "build_authority_seal_draft",
    "canonical_hash",
    "canonical_json",
    "create_runner_authority_snapshot",
    "hash_file",
    "normalize_sidecar_policy",
    "persist_runner_authority_anchor",
    "validate_authority_anchor",
    "validate_authority_seal_draft",
    "validate_runner_authority_snapshot",
    "verify_runner_authority_anchor",
    "verify_runner_authority_anchor_in_snapshot",
]
