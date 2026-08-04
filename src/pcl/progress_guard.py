from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import sqlite3
from typing import Any

from .db import connect, connect_mutation
from .errors import DataStoreError, EXIT_USAGE, InvalidInputError, PclError
from .events import append_event
from .guards import require_initialized
from .outbox import canonical_event_bytes, canonical_event_record
from .paths import ProjectPaths
from .timeutil import utc_now_iso


PROGRESS_GUARD_CONTRACT_VERSION = "progress-guard/v1"
PROGRESS_GUARD_EVENT_CONTRACT_VERSION = "progress-guard-event/v1"
PROGRESS_GUARD_LINEAGE_CONTRACT_VERSION = "progress-guard-lineage/v1"
PROGRESS_GUARD_ACTIVATED = "progress_guard_activated"
PROGRESS_GUARD_OBSERVED = "progress_guard_observation_recorded"
PROGRESS_GUARD_REPLANNED = "progress_guard_replan_recorded"
PROGRESS_GUARD_EVENT_TYPES = (
    PROGRESS_GUARD_ACTIVATED,
    PROGRESS_GUARD_OBSERVED,
    PROGRESS_GUARD_REPLANNED,
)
DEFAULT_STAGNATION_LIMIT = 2
VALUE_KINDS = frozenset(
    {
        "criterion_closed",
        "gate_bound_artifact_ready",
        "human_acceptance",
        "integrated_behavior",
    }
)
WORK_CLASSIFICATIONS = frozenset(
    {"mainline_product", "harness_support", "deferred"}
)
SECURITY_BOUNDARY = (
    "Cooperative policy only; not tamper-proof against a caller that edits DB/files, "
    "bypasses PCL, or falsely supplies operator confirmation. It does not enforce "
    "external Cockpit task creation or provide cryptographic human authentication."
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class ProgressGuardDataError(DataStoreError):
    pass


class ProgressGuardNotActiveError(PclError):
    def __init__(self, *, goal_id: str, exit_gate: str) -> None:
        super().__init__(
            message=f"Progress Guard is not active for Goal {goal_id} and Exit Gate {exit_gate}.",
            code="progress_guard_not_active",
            exit_code=EXIT_USAGE,
            details={"goal": goal_id, "gate": exit_gate, "mutation_committed": False},
        )


class ProgressGuardStoppedError(PclError):
    def __init__(self, status: dict[str, Any]) -> None:
        super().__init__(
            message=(
                f"Goal {status['goal']} is stopped at Exit Gate {status['gate']}; "
                "an explicit operator replan is required before cooperative continuation."
            ),
            code="progress_guard_stopped",
            exit_code=EXIT_USAGE,
            details={
                "mutation_committed": False,
                "progressGuard": status,
                "securityBoundary": SECURITY_BOUNDARY,
            },
        )


@dataclass
class _GuardState:
    project_instance: str
    goal_id: str
    gate: str
    lineage_id: str
    limit: int
    activation_event_id: str
    consecutive_zero: int = 0
    total_observations: int = 0
    value_events: list[dict[str, Any]] = field(default_factory=list)
    mainline_count: int = 0
    support_count: int = 0
    deferred_count: int = 0
    consumed_tokens: list[str] = field(default_factory=list)
    observations_by_token: dict[str, dict[str, Any]] = field(default_factory=dict)
    replan_revisions: list[str] = field(default_factory=list)
    replan_revision: str | None = None
    last_observation: dict[str, Any] | None = None
    stopped: bool = False

    def public(self) -> dict[str, Any]:
        numerator = self.support_count + self.deferred_count
        denominator = self.total_observations
        return {
            "contractVersion": PROGRESS_GUARD_CONTRACT_VERSION,
            "lineage": {
                "contractVersion": PROGRESS_GUARD_LINEAGE_CONTRACT_VERSION,
                "id": self.lineage_id,
                "projectInstance": self.project_instance,
            },
            "goal": self.goal_id,
            "gate": self.gate,
            "active": True,
            "stopped": self.stopped,
            "decision": "stop_and_replan" if self.stopped else "continue",
            "limit": self.limit,
            "consecutiveZero": self.consecutive_zero,
            "totalObservations": self.total_observations,
            "valueEvents": len(self.value_events),
            "valueEventDetails": list(self.value_events),
            "mainlineCount": self.mainline_count,
            "supportCount": self.support_count,
            "deferredCount": self.deferred_count,
            "offMainline": {
                "numerator": numerator,
                "denominator": denominator,
                "ratio": 0.0 if denominator == 0 else numerator / denominator,
            },
            "consumedTokens": list(self.consumed_tokens),
            "lastObservation": self.last_observation,
            "replanRevision": self.replan_revision,
            "policyOnly": True,
            "securityBoundary": SECURITY_BOUNDARY,
            "nextAction": "operator_replan" if self.stopped else "continue_mainline",
        }


def activate_progress_guard(
    paths: ProjectPaths,
    *,
    goal_id: str,
    exit_gate: str,
    limit: int = DEFAULT_STAGNATION_LIMIT,
    now: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    goal_id = _identifier(goal_id, "goal")
    exit_gate = _identifier(exit_gate, "exit_gate")
    if limit < 1 or limit > 100:
        raise InvalidInputError(
            "--limit must be between 1 and 100.",
            details={"field": "limit", "value": limit},
        )
    conn = connect_mutation(paths)
    try:
        _require_goal(conn, goal_id)
        project_instance = _project_instance_id(conn)
        existing = _derive_guard_state(
            conn,
            project_instance=project_instance,
            goal_id=goal_id,
            exit_gate=exit_gate,
        )
        if existing is not None:
            if existing.limit != limit:
                raise InvalidInputError(
                    "Progress Guard is already active with a different stagnation limit.",
                    details={
                        "goal": goal_id,
                        "gate": exit_gate,
                        "existing_limit": existing.limit,
                        "requested_limit": limit,
                    },
                )
            return {
                "ok": True,
                "changed": False,
                "duplicate": True,
                "eventId": existing.activation_event_id,
                "progressGuard": existing.public(),
            }
        lineage = _lineage(project_instance, goal_id, exit_gate)
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=PROGRESS_GUARD_ACTIVATED,
            entity_type="goal",
            entity_id=goal_id,
            payload={
                "contract_version": PROGRESS_GUARD_EVENT_CONTRACT_VERSION,
                "lineage": lineage,
                "limit": limit,
                "policy_only": True,
                "security_boundary": SECURITY_BOUNDARY,
            },
            created_at=now or utc_now_iso(),
        )
        conn.commit()
    except sqlite3.Error as exc:
        _rollback(conn)
        raise ProgressGuardDataError(
            f"Could not activate Progress Guard: {exc}",
            details={"goal": goal_id, "gate": exit_gate, "mutation_committed": False},
        ) from exc
    except BaseException:
        _rollback(conn)
        raise
    finally:
        conn.close()
    return {
        "ok": True,
        "changed": True,
        "duplicate": False,
        "eventId": event_id,
        "progressGuard": progress_guard_status(
            paths, goal_id=goal_id, exit_gate=exit_gate
        ),
    }


def progress_guard_status(
    paths: ProjectPaths,
    *,
    goal_id: str,
    exit_gate: str,
) -> dict[str, Any]:
    require_initialized(paths)
    goal_id = _identifier(goal_id, "goal")
    exit_gate = _identifier(exit_gate, "exit_gate")
    conn = connect(paths.db_path)
    try:
        _require_goal(conn, goal_id)
        state = _derive_guard_state(
            conn,
            project_instance=_project_instance_id(conn),
            goal_id=goal_id,
            exit_gate=exit_gate,
        )
    finally:
        conn.close()
    if state is None:
        raise ProgressGuardNotActiveError(goal_id=goal_id, exit_gate=exit_gate)
    return state.public()


def record_progress_guard_observation(
    paths: ProjectPaths,
    *,
    goal_id: str,
    exit_gate: str,
    delta: int,
    classification: str,
    criterion: str,
    surface: str,
    value_token: str,
    summary: str,
    evidence_ref: str,
    value_kind: str | None = None,
    task_label: str | None = None,
    run_label: str | None = None,
    route_label: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    goal_id = _identifier(goal_id, "goal")
    exit_gate = _identifier(exit_gate, "exit_gate")
    value_token = _identifier(value_token, "value_token")
    classification = classification.strip()
    if classification not in WORK_CLASSIFICATIONS:
        raise InvalidInputError(
            f"Invalid work classification: {classification}",
            details={"field": "classification", "allowed": sorted(WORK_CLASSIFICATIONS)},
        )
    if delta not in {0, 1}:
        raise InvalidInputError(
            "--delta must be 0 or 1.",
            details={"field": "delta", "allowed": ["0", "1"]},
        )
    if delta == 1:
        if classification != "mainline_product":
            raise InvalidInputError(
                "Only mainline_product observations may record behavior-facing delta 1.",
                details={"field": "classification", "classification": classification},
            )
        if value_kind not in VALUE_KINDS:
            raise InvalidInputError(
                "Delta 1 requires one closed behavior-facing --value-kind.",
                details={"field": "value_kind", "allowed": sorted(VALUE_KINDS)},
            )
    elif value_kind is not None:
        raise InvalidInputError(
            "Delta 0 must not claim a behavior-facing --value-kind.",
            details={"field": "value_kind", "value": value_kind},
        )
    criterion = _text(criterion, "criterion")
    surface = _text(surface, "surface")
    summary = _text(summary, "summary")
    evidence_ref = _text(evidence_ref, "evidence_ref")
    source = {
        "task": _optional_text(task_label),
        "run": _optional_text(run_label),
        "route": _optional_text(route_label),
    }

    conn = connect_mutation(paths)
    try:
        _require_goal(conn, goal_id)
        state = _derive_guard_state(
            conn,
            project_instance=_project_instance_id(conn),
            goal_id=goal_id,
            exit_gate=exit_gate,
        )
        if state is None:
            raise ProgressGuardNotActiveError(goal_id=goal_id, exit_gate=exit_gate)
        duplicate = state.observations_by_token.get(value_token)
        if duplicate is not None:
            duplicate_observation = {
                **duplicate,
                "originalEffectiveDelta": duplicate["effectiveDelta"],
                "effectiveDelta": 0,
                "duplicateOfEventId": duplicate["eventId"],
            }
            return {
                "ok": True,
                "changed": False,
                "duplicate": True,
                "observation": duplicate_observation,
                "progressGuard": state.public(),
            }
        if state.stopped:
            raise ProgressGuardStoppedError(state.public())
        observation = {
            "claimedDelta": delta,
            "effectiveDelta": delta,
            "classification": classification,
            "criterion": criterion,
            "surface": surface,
            "valueToken": value_token,
            "valueKind": value_kind,
            "summary": summary,
            "evidenceRef": evidence_ref,
            "source": source,
        }
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=PROGRESS_GUARD_OBSERVED,
            entity_type="goal",
            entity_id=goal_id,
            payload={
                "contract_version": PROGRESS_GUARD_EVENT_CONTRACT_VERSION,
                "lineage": _lineage(state.project_instance, goal_id, exit_gate),
                "observation": observation,
            },
            created_at=now or utc_now_iso(),
        )
        conn.commit()
    except sqlite3.Error as exc:
        _rollback(conn)
        raise ProgressGuardDataError(
            f"Could not record Progress Guard observation: {exc}",
            details={"goal": goal_id, "gate": exit_gate, "mutation_committed": False},
        ) from exc
    except BaseException:
        _rollback(conn)
        raise
    finally:
        conn.close()
    return {
        "ok": True,
        "changed": True,
        "duplicate": False,
        "eventId": event_id,
        "observation": observation,
        "progressGuard": progress_guard_status(
            paths, goal_id=goal_id, exit_gate=exit_gate
        ),
    }


def replan_progress_guard(
    paths: ProjectPaths,
    *,
    goal_id: str,
    exit_gate: str,
    revision_token: str,
    reason: str,
    operator: str,
    now: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    goal_id = _identifier(goal_id, "goal")
    exit_gate = _identifier(exit_gate, "exit_gate")
    revision_token = _identifier(revision_token, "revision_token")
    reason = _text(reason, "reason")
    operator = _text(operator, "operator")
    conn = connect_mutation(paths)
    try:
        _require_goal(conn, goal_id)
        state = _derive_guard_state(
            conn,
            project_instance=_project_instance_id(conn),
            goal_id=goal_id,
            exit_gate=exit_gate,
        )
        if state is None:
            raise ProgressGuardNotActiveError(goal_id=goal_id, exit_gate=exit_gate)
        if revision_token in state.replan_revisions:
            return {
                "ok": True,
                "changed": False,
                "duplicate": True,
                "progressGuard": state.public(),
            }
        if not state.stopped:
            raise InvalidInputError(
                "Progress Guard is not stopped; replan/resume is only valid after stop_and_replan.",
                details={"goal": goal_id, "gate": exit_gate, "decision": state.public()["decision"]},
            )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=PROGRESS_GUARD_REPLANNED,
            entity_type="goal",
            entity_id=goal_id,
            payload={
                "contract_version": PROGRESS_GUARD_EVENT_CONTRACT_VERSION,
                "lineage": _lineage(state.project_instance, goal_id, exit_gate),
                "revision_token": revision_token,
                "reason": reason,
                "operator": operator,
                "operator_attestation": True,
                "cryptographic_human_authentication": False,
                "security_boundary": SECURITY_BOUNDARY,
            },
            created_at=now or utc_now_iso(),
        )
        conn.commit()
    except sqlite3.Error as exc:
        _rollback(conn)
        raise ProgressGuardDataError(
            f"Could not record Progress Guard replan: {exc}",
            details={"goal": goal_id, "gate": exit_gate, "mutation_committed": False},
        ) from exc
    except BaseException:
        _rollback(conn)
        raise
    finally:
        conn.close()
    return {
        "ok": True,
        "changed": True,
        "duplicate": False,
        "eventId": event_id,
        "progressGuard": progress_guard_status(
            paths, goal_id=goal_id, exit_gate=exit_gate
        ),
    }


def stopped_progress_guard_for_goal(
    paths: ProjectPaths,
    *,
    goal_id: str,
) -> dict[str, Any] | None:
    require_initialized(paths)
    conn = connect(paths.db_path)
    try:
        _require_goal(conn, goal_id)
        states = _derive_goal_states(
            conn,
            project_instance=_project_instance_id(conn),
            goal_id=goal_id,
        )
    finally:
        conn.close()
    for state in states:
        if state.stopped:
            return state.public()
    return None


def first_stopped_progress_guard(paths: ProjectPaths) -> dict[str, Any] | None:
    require_initialized(paths)
    conn = connect(paths.db_path)
    try:
        project_instance = _project_instance_id(conn)
        goal_ids = [
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM goals WHERE status IN ('open', 'active', 'blocked') ORDER BY id"
            ).fetchall()
        ]
        for goal_id in goal_ids:
            for state in _derive_goal_states(
                conn, project_instance=project_instance, goal_id=goal_id
            ):
                if state.stopped:
                    return state.public()
    finally:
        conn.close()
    return None


def require_goal_progress_continuation(
    conn: sqlite3.Connection,
    *,
    goal_id: str | None,
) -> None:
    if goal_id is None:
        return
    _require_goal(conn, goal_id)
    project_instance = _project_instance_id(conn)
    for state in _derive_goal_states(
        conn, project_instance=project_instance, goal_id=goal_id
    ):
        if state.stopped:
            raise ProgressGuardStoppedError(state.public())


def _derive_goal_states(
    conn: sqlite3.Connection,
    *,
    project_instance: str,
    goal_id: str,
) -> list[_GuardState]:
    gates: set[str] = set()
    for row in _guard_event_rows(conn, goal_id):
        if str(row["event_type"]) != PROGRESS_GUARD_ACTIVATED:
            continue
        payload = _event_payload(row)
        lineage = payload.get("lineage")
        if isinstance(lineage, dict) and isinstance(lineage.get("gate"), str):
            gates.add(str(lineage["gate"]))
    states: list[_GuardState] = []
    for gate in sorted(gates):
        state = _derive_guard_state(
            conn,
            project_instance=project_instance,
            goal_id=goal_id,
            exit_gate=gate,
        )
        if state is not None:
            states.append(state)
    return states


def _derive_guard_state(
    conn: sqlite3.Connection,
    *,
    project_instance: str,
    goal_id: str,
    exit_gate: str,
) -> _GuardState | None:
    expected_lineage = _lineage(project_instance, goal_id, exit_gate)
    state: _GuardState | None = None
    for row in _guard_event_rows(conn, goal_id):
        payload = _event_payload(row)
        lineage = payload.get("lineage")
        if not isinstance(lineage, dict) or lineage.get("gate") != exit_gate:
            continue
        if (
            payload.get("contract_version") != PROGRESS_GUARD_EVENT_CONTRACT_VERSION
            or lineage != expected_lineage
            or str(row["entity_type"]) != "goal"
            or str(row["entity_id"]) != goal_id
        ):
            raise ProgressGuardDataError(
                "Progress Guard event lineage is invalid.",
                details={"event_id": str(row["id"]), "goal": goal_id, "gate": exit_gate},
            )
        event_type = str(row["event_type"])
        if event_type == PROGRESS_GUARD_ACTIVATED:
            if state is not None:
                raise ProgressGuardDataError(
                    "Progress Guard has multiple activation events for one lineage.",
                    details={"goal": goal_id, "gate": exit_gate},
                )
            limit = payload.get("limit")
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
                raise ProgressGuardDataError(
                    "Progress Guard activation limit is invalid.",
                    details={"event_id": str(row["id"]), "limit": limit},
                )
            state = _GuardState(
                project_instance=project_instance,
                goal_id=goal_id,
                gate=exit_gate,
                lineage_id=str(expected_lineage["id"]),
                limit=limit,
                activation_event_id=str(row["id"]),
            )
            continue
        if state is None:
            raise ProgressGuardDataError(
                "Progress Guard event precedes activation.",
                details={"event_id": str(row["id"]), "goal": goal_id, "gate": exit_gate},
            )
        if event_type == PROGRESS_GUARD_OBSERVED:
            observation = _validated_observation(payload.get("observation"), row)
            token = str(observation["valueToken"])
            if token in state.observations_by_token:
                raise ProgressGuardDataError(
                    "Progress Guard contains duplicate persisted value tokens.",
                    details={"event_id": str(row["id"]), "value_token": token},
                )
            materialized = {
                **observation,
                "eventId": str(row["id"]),
                "sequence": int(row["sequence"]),
                "createdAt": str(row["created_at"]),
            }
            state.observations_by_token[token] = materialized
            state.consumed_tokens.append(token)
            state.total_observations += 1
            classification = str(observation["classification"])
            if classification == "mainline_product":
                state.mainline_count += 1
            elif classification == "harness_support":
                state.support_count += 1
            else:
                state.deferred_count += 1
            if int(observation["effectiveDelta"]) == 1:
                state.consecutive_zero = 0
                state.value_events.append(
                    {
                        "criterion": observation["criterion"],
                        "eventId": str(row["id"]),
                        "kind": observation["valueKind"],
                        "surface": observation["surface"],
                        "token": token,
                    }
                )
            else:
                state.consecutive_zero += 1
            state.stopped = state.consecutive_zero >= state.limit
            state.last_observation = materialized
        elif event_type == PROGRESS_GUARD_REPLANNED:
            revision = payload.get("revision_token")
            if not isinstance(revision, str) or not _IDENTIFIER.fullmatch(revision):
                raise ProgressGuardDataError(
                    "Progress Guard replan revision is invalid.",
                    details={"event_id": str(row["id"])},
                )
            if revision in state.replan_revisions:
                raise ProgressGuardDataError(
                    "Progress Guard contains duplicate persisted replan revisions.",
                    details={"event_id": str(row["id"]), "revision_token": revision},
                )
            state.replan_revisions.append(revision)
            state.replan_revision = revision
            state.consecutive_zero = 0
            state.stopped = False
    return state


def _validated_observation(value: object, row: sqlite3.Row) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProgressGuardDataError(
            "Progress Guard observation payload is invalid.",
            details={"event_id": str(row["id"])},
        )
    required = {
        "claimedDelta",
        "effectiveDelta",
        "classification",
        "criterion",
        "surface",
        "valueToken",
        "valueKind",
        "summary",
        "evidenceRef",
        "source",
    }
    if set(value) != required:
        raise ProgressGuardDataError(
            "Progress Guard observation fields are invalid.",
            details={"event_id": str(row["id"]), "fields": sorted(value)},
        )
    delta = value.get("effectiveDelta")
    classification = value.get("classification")
    kind = value.get("valueKind")
    if delta not in {0, 1} or value.get("claimedDelta") != delta:
        raise ProgressGuardDataError(
            "Progress Guard observation delta is invalid.",
            details={"event_id": str(row["id"])},
        )
    if classification not in WORK_CLASSIFICATIONS:
        raise ProgressGuardDataError(
            "Progress Guard observation classification is invalid.",
            details={"event_id": str(row["id"])},
        )
    if delta == 1 and (classification != "mainline_product" or kind not in VALUE_KINDS):
        raise ProgressGuardDataError(
            "Progress Guard persisted a non-behavior-facing value event.",
            details={"event_id": str(row["id"])},
        )
    if delta == 0 and kind is not None:
        raise ProgressGuardDataError(
            "Progress Guard persisted a value kind for delta 0.",
            details={"event_id": str(row["id"])},
        )
    token = value.get("valueToken")
    if not isinstance(token, str) or not _IDENTIFIER.fullmatch(token):
        raise ProgressGuardDataError(
            "Progress Guard observation token is invalid.",
            details={"event_id": str(row["id"])},
        )
    for key in ("criterion", "surface", "summary", "evidenceRef"):
        if not isinstance(value.get(key), str) or not str(value[key]).strip():
            raise ProgressGuardDataError(
                f"Progress Guard observation {key} is invalid.",
                details={"event_id": str(row["id"])},
            )
    source = value.get("source")
    if not isinstance(source, dict) or set(source) != {"task", "run", "route"}:
        raise ProgressGuardDataError(
            "Progress Guard observation source is invalid.",
            details={"event_id": str(row["id"])},
        )
    return dict(value)


def _guard_event_rows(conn: sqlite3.Connection, goal_id: str) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in PROGRESS_GUARD_EVENT_TYPES)
    return conn.execute(
        f"""
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events
        WHERE entity_type = 'goal'
          AND entity_id = ?
          AND event_type IN ({placeholders})
        ORDER BY sequence
        """,
        (goal_id, *PROGRESS_GUARD_EVENT_TYPES),
    ).fetchall()


def _event_payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(str(row["payload_json"]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProgressGuardDataError(
            "Progress Guard event payload is not valid JSON.",
            details={"event_id": str(row["id"])},
        ) from exc
    if not isinstance(payload, dict):
        raise ProgressGuardDataError(
            "Progress Guard event payload must be an object.",
            details={"event_id": str(row["id"])},
        )
    return payload


def _lineage(project_instance: str, goal_id: str, exit_gate: str) -> dict[str, str]:
    core = {
        "contractVersion": PROGRESS_GUARD_LINEAGE_CONTRACT_VERSION,
        "projectInstance": project_instance,
        "goal": goal_id,
        "gate": exit_gate,
    }
    digest = hashlib.sha256(
        json.dumps(
            core,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {**core, "id": f"pg-sha256:{digest}"}


def _project_instance_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events
        WHERE event_type = 'project_initialized'
        ORDER BY sequence
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise ProgressGuardDataError("Project initialization authority is missing.")
    return hashlib.sha256(canonical_event_bytes(canonical_event_record(row))).hexdigest()


def _require_goal(conn: sqlite3.Connection, goal_id: str) -> None:
    if conn.execute("SELECT 1 FROM goals WHERE id = ?", (goal_id,)).fetchone() is None:
        raise InvalidInputError(
            f"Goal does not exist: {goal_id}",
            details={"goal": goal_id},
        )


def _identifier(value: str, field: str) -> str:
    normalized = value.strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise InvalidInputError(
            f"--{field.replace('_', '-')} must be a stable identifier.",
            details={"field": field, "value": value},
        )
    return normalized


def _text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise InvalidInputError(
            f"--{field.replace('_', '-')} must not be empty.",
            details={"field": field},
        )
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _rollback(conn: sqlite3.Connection) -> None:
    if not bool(getattr(conn, "_authoritative_commit_completed", False)):
        try:
            conn.rollback()
        except BaseException:
            pass
