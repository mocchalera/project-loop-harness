from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any
import uuid

from .db import connect_mutation
from .direct_spec import DirectSpecDocument
from .errors import (
    DirectSetupConflictError,
    ProjectionPendingError,
)
from .events import append_event
from .evidence import record_inline_evidence
from .paths import ProjectPaths
from .prefixed_ids import next_prefixed_ids_strict
from .timeutil import utc_now_iso
from .validators import collect_authoritative_admission_findings


DIRECT_SETUP_RECEIPT_CONTRACT_VERSION = "direct-setup-receipt/v1"
DIRECT_SETUP_REQUEST_CONTRACT_VERSION = "direct-setup-request/v1"
DIRECT_SETUP_BINDING_CONTRACT_VERSION = "direct-setup-binding/v1"
DIRECT_SETUP_IDENTITY_CONTRACT_VERSION = "direct-setup-request-identity/v1"
START_RECEIPT_CONTRACT_VERSION = "start-receipt/v1"
START_ACTOR = "pcl:start"
_ACTIVE_GOAL_STATUSES = ("open", "active", "blocked")
_ACTIVE_DEFECT_STATUSES = ("open", "triaged", "in_progress", "fixed", "verified")
_ACTIVE_RUN_STATUSES = ("queued", "running", "blocked")
_ID_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def commit_direct_setup(
    paths: ProjectPaths,
    *,
    intent: str,
    spec: DirectSpecDocument,
    new: bool,
    preflight_repository_revision: str | None,
) -> dict[str, Any]:
    """Commit one Direct Setup bundle or return its verified idempotent receipt."""

    _require_bound_root(spec, paths, phase="before_authoritative_connection")
    mutation_paths = spec.root_binding.bound_paths()
    conn = connect_mutation(mutation_paths, exclusive=True)
    try:
        _require_bound_root(spec, paths, phase="authoritative_admission")
        admission_now = utc_now_iso()
        try:
            admission = collect_authoritative_admission_findings(
                conn,
                now=admission_now,
            )
        except sqlite3.Error as exc:
            raise DirectSetupConflictError(
                "Direct setup authoritative admission could not inspect project state.",
                code="direct_setup_admission_failed",
                details={"database_error": str(exc)},
            ) from exc
        if not admission.ok:
            raise DirectSetupConflictError(
                "Direct setup authoritative admission failed.",
                code="direct_setup_admission_failed",
                details={
                    "errors": list(admission.errors),
                    "warnings": list(admission.warnings),
                    "finding_codes": [
                        finding.code
                        for finding in admission.findings
                        if finding.severity == "error"
                    ],
                },
            )
        _require_delivered_outbox(conn)

        anchor_id = direct_setup_anchor_id(spec.request_id)
        anchor = conn.execute(
            """
            SELECT id, sequence, event_type, entity_type, entity_id, payload_json
                 , created_at
            FROM events
            WHERE id = ?
            """,
            (anchor_id,),
        ).fetchone()
        legacy_anchor_id = _legacy_direct_setup_anchor_id(spec.request_id)
        legacy_anchor = None
        if legacy_anchor_id != anchor_id:
            legacy_anchor = conn.execute(
                """
                SELECT id, sequence, event_type, entity_type, entity_id, payload_json
                     , created_at
                FROM events
                WHERE id = ?
                """,
                (legacy_anchor_id,),
            ).fetchone()
        ambiguous_ids = _matching_request_event_ids(
            conn,
            request_id=spec.request_id,
        )
        if anchor is not None:
            retry = _load_verified_retry(
                conn,
                anchor=anchor,
                intent=intent,
                spec=spec,
                new=new,
                current_repository_revision=spec.root_binding.repository_revision(),
                ambiguous_ids=ambiguous_ids,
            )
            conn.rollback()
            return retry
        if legacy_anchor is not None:
            legacy_ambiguity = (
                ambiguous_ids
                if legacy_anchor_id in ambiguous_ids
                else [legacy_anchor_id]
            )
            try:
                retry = _load_verified_retry(
                    conn,
                    anchor=legacy_anchor,
                    intent=intent,
                    spec=spec,
                    new=new,
                    current_repository_revision=(
                        spec.root_binding.repository_revision()
                    ),
                    ambiguous_ids=legacy_ambiguity,
                )
            except DirectSetupConflictError as exc:
                if exc.code != "direct_setup_idempotency_conflict":
                    raise
            else:
                conn.rollback()
                return retry
        if ambiguous_ids:
            raise DirectSetupConflictError(
                "Direct setup request has an ambiguous non-anchor event.",
                code="direct_setup_anchor_ambiguous",
                details={
                    "request_id": spec.request_id,
                    "event_count": len(ambiguous_ids),
                },
            )
        if not new:
            active = _active_work_counts(conn)
            if any(active.values()):
                raise DirectSetupConflictError(
                    "Active work already exists; use --new for a separate Direct Setup bundle.",
                    code="direct_setup_active_work_exists",
                    details={"active": active},
                )

        current_repository_revision = spec.root_binding.repository_revision()
        if current_repository_revision != preflight_repository_revision:
            raise DirectSetupConflictError(
                "Repository revision changed before Direct Setup admission.",
                code="direct_setup_repository_revision_changed",
                details={
                    "preflight": preflight_repository_revision,
                    "admission": current_repository_revision,
                },
            )
        ids = _allocate_bundle_ids(conn, spec)
        event_plan = _build_event_plan(
            conn,
            spec=spec,
            ids=ids,
            anchor_id=anchor_id,
        )
        request = _direct_request(
            intent=intent,
            spec=spec,
            new=new,
            initial_repository_revision=current_repository_revision,
        )
        request_identity_sha256 = _canonical_sha256(
            {
                "contract_version": DIRECT_SETUP_IDENTITY_CONTRACT_VERSION,
                "request": request,
            }
        )
        direct_setup = {
            "contract_version": DIRECT_SETUP_RECEIPT_CONTRACT_VERSION,
            "request": request,
            "request_identity_sha256": request_identity_sha256,
            "bundle_created_ids": {
                "goal": ids["goal"],
                "task": ids["task"],
                "feature": ids["feature"],
                "stories": list(ids["stories"]),
                "tests": list(ids["tests"]),
                "start_receipt_evidence": ids["evidence"],
                "events": [item["id"] for item in event_plan],
                "outbox": [item["outbox_id"] for item in event_plan],
            },
            "event_range": {
                "start_sequence": event_plan[0]["sequence"],
                "end_sequence": event_plan[-1]["sequence"],
                "count": len(event_plan),
                "ordered": [
                    {
                        key: item[key]
                        for key in (
                            "sequence",
                            "id",
                            "event_type",
                            "entity_type",
                            "entity_id",
                        )
                    }
                    for item in event_plan
                ],
            },
        }
        direct_setup["binding"] = {
            "contract_version": DIRECT_SETUP_BINDING_CONTRACT_VERSION,
            "algorithm": "sha256",
            "canonical_sha256": _direct_setup_binding(direct_setup),
        }
        receipt = {
            "contract_version": START_RECEIPT_CONTRACT_VERSION,
            "generated_at": admission_now,
            "intent": intent,
            "actor": START_ACTOR,
            "repository_revision": current_repository_revision,
            "created_ids": {
                "goal": ids["goal"],
                "task": ids["task"],
            },
            "target": {"type": "task", "id": ids["task"]},
            "direct_setup": direct_setup,
        }
        _insert_bundle(
            conn,
            mutation_paths,
            spec=spec,
            ids=ids,
            event_plan=event_plan,
            receipt=receipt,
            now=admission_now,
        )
        _require_bound_root(spec, paths, phase="before_authoritative_commit")
        conn.commit()
        return {
            "task_id": ids["task"],
            "created_ids": {
                "goal": ids["goal"],
                "task": ids["task"],
                "evidence": ids["evidence"],
                "event": anchor_id,
            },
            "receipt": {
                **receipt,
                "evidence_id": ids["evidence"],
                "event_id": anchor_id,
            },
            "idempotent": False,
            "reused_ids": None,
            "repository_revision": {
                "initial": current_repository_revision,
                "current": current_repository_revision,
                "changed_since_initial": False,
            },
        }
    except BaseException:
        committed = bool(getattr(conn, "_authoritative_commit_completed", False))
        if not committed:
            try:
                conn.rollback()
            except BaseException:
                pass
        raise
    finally:
        conn.close()


def direct_setup_anchor_id(request_id: str) -> str:
    digest = hashlib.sha256(
        b"pcl:direct-setup-anchor:v1\0" + request_id.encode("utf-8")
    ).hexdigest()
    return f"EV-{digest.upper()}"


def _legacy_direct_setup_anchor_id(request_id: str) -> str:
    digest = hashlib.sha256(
        b"pcl:direct-setup-anchor:v1\0" + request_id.encode("utf-8")
    ).hexdigest()
    return f"EV-{digest[:12].upper()}"


def _require_bound_root(
    spec: DirectSpecDocument,
    paths: ProjectPaths,
    *,
    phase: str,
) -> None:
    if spec.root_binding.current_matches(paths):
        return
    raise DirectSetupConflictError(
        "Project root changed after the Direct spec was read.",
        code="direct_setup_root_changed",
        details={
            "phase": phase,
            "root": str(paths.root),
        },
    )


def _require_delivered_outbox(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM outbox_records
        WHERE status != 'delivered'
        GROUP BY status
        ORDER BY status
        """
    ).fetchall()
    if not rows:
        return
    raise ProjectionPendingError(
        details={
            "projection": "pending",
            "mutation_committed": False,
            "statuses": {
                str(row["status"]): int(row["count"])
                for row in rows
            },
            "recovery_command": "pcl audit flush --json",
        }
    )


def _active_work_counts(conn: sqlite3.Connection) -> dict[str, int]:
    goal_placeholders = ", ".join("?" for _ in _ACTIVE_GOAL_STATUSES)
    defect_placeholders = ", ".join("?" for _ in _ACTIVE_DEFECT_STATUSES)
    run_placeholders = ", ".join("?" for _ in _ACTIVE_RUN_STATUSES)
    return {
        "goals": int(
            conn.execute(
                f"SELECT COUNT(*) FROM goals WHERE status IN ({goal_placeholders})",
                _ACTIVE_GOAL_STATUSES,
            ).fetchone()[0]
        ),
        "defects": int(
            conn.execute(
                f"SELECT COUNT(*) FROM defects WHERE status IN ({defect_placeholders})",
                _ACTIVE_DEFECT_STATUSES,
            ).fetchone()[0]
        ),
        "workflow_runs": int(
            conn.execute(
                f"SELECT COUNT(*) FROM workflow_runs WHERE status IN ({run_placeholders})",
                _ACTIVE_RUN_STATUSES,
            ).fetchone()[0]
        ),
    }


def _allocate_bundle_ids(
    conn: sqlite3.Connection,
    spec: DirectSpecDocument,
) -> dict[str, Any]:
    return {
        "goal": _next_ids(conn, "goals", "G", 1)[0],
        "task": _next_ids(conn, "tasks", "T", 1)[0],
        "feature": _next_ids(conn, "features", "F", 1)[0],
        "evidence": _next_ids(conn, "evidence", "E", 1)[0],
        "stories": _next_ids(
            conn,
            "user_stories",
            "US",
            len(spec.value["stories"]),
        ),
        "tests": _next_ids(
            conn,
            "test_cases",
            "TC",
            len(spec.value["tests"]),
        ),
    }


def _next_ids(
    conn: sqlite3.Connection,
    table: str,
    prefix: str,
    count: int,
) -> list[str]:
    return next_prefixed_ids_strict(
        conn,
        table=table,
        prefix=prefix,
        count=count,
    )


def _build_event_plan(
    conn: sqlite3.Connection,
    *,
    spec: DirectSpecDocument,
    ids: dict[str, Any],
    anchor_id: str,
) -> list[dict[str, Any]]:
    event_specs = [
        ("goal_created", "goal", ids["goal"]),
        ("task_created", "task", ids["task"]),
        ("work_started", "task", ids["task"]),
        ("feature_added", "feature", ids["feature"]),
        ("task_feature_linked", "task", ids["task"]),
        *(
            ("user_story_drafted", "user_story", story_id)
            for story_id in ids["stories"]
        ),
        ("feature_status_updated", "feature", ids["feature"]),
        *(
            ("test_case_planned", "test_case", test_id)
            for test_id in ids["tests"]
        ),
    ]
    expected_count = 6 + len(spec.value["stories"]) + len(spec.value["tests"])
    if len(event_specs) != expected_count:
        raise AssertionError("Direct Setup event plan count is invalid.")
    event_ids = [_random_id("EV") for _ in event_specs]
    event_ids[2] = anchor_id
    outbox_ids = [_random_id("OB") for _ in event_specs]
    if len(set(event_ids)) != len(event_ids) or len(set(outbox_ids)) != len(outbox_ids):
        raise DirectSetupConflictError(
            "Direct Setup generated a duplicate event or outbox ID.",
            code="direct_setup_id_collision",
        )
    existing_events = {
        str(row["id"])
        for row in conn.execute(
            f"SELECT id FROM events WHERE id IN ({', '.join('?' for _ in event_ids)})",
            tuple(event_ids),
        ).fetchall()
    }
    existing_outbox = {
        str(row["id"])
        for row in conn.execute(
            f"SELECT id FROM outbox_records WHERE id IN ({', '.join('?' for _ in outbox_ids)})",
            tuple(outbox_ids),
        ).fetchall()
    }
    if existing_events or existing_outbox:
        raise DirectSetupConflictError(
            "Direct Setup event or outbox ID collides with existing state.",
            code="direct_setup_id_collision",
            details={
                "event_collision_count": len(existing_events),
                "outbox_collision_count": len(existing_outbox),
            },
        )
    start_sequence = int(
        conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM events").fetchone()[0]
    )
    return [
        {
            "sequence": start_sequence + index,
            "id": event_ids[index],
            "outbox_id": outbox_ids[index],
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
        for index, (event_type, entity_type, entity_id) in enumerate(event_specs)
    ]


def _insert_bundle(
    conn: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    spec: DirectSpecDocument,
    ids: dict[str, Any],
    event_plan: list[dict[str, Any]],
    receipt: dict[str, Any],
    now: str,
) -> None:
    event_index = 0
    conn.execute(
        """
        INSERT INTO goals(
          id, title, status, completion_json, stop_conditions_json, budget_json,
          created_at, updated_at
        ) VALUES (?, ?, 'open', '{}', '{}', '{}', ?, ?)
        """,
        (ids["goal"], receipt["intent"], now, now),
    )
    _append_planned_event(
        conn,
        paths,
        event_plan[event_index],
        {"title": receipt["intent"]},
        now,
    )
    event_index += 1

    conn.execute(
        """
        INSERT INTO tasks(
          id, title, description, status, priority, owner, risk, effort,
          related_goal_id, related_feature_id, related_defect_id, created_at, updated_at
        ) VALUES (?, ?, '', 'in_progress', 100, NULL, NULL, NULL, ?, NULL, NULL, ?, ?)
        """,
        (ids["task"], receipt["intent"], ids["goal"], now, now),
    )
    _append_planned_event(
        conn,
        paths,
        event_plan[event_index],
        {
            "title": receipt["intent"],
            "description": "",
            "status": "in_progress",
            "priority": 100,
            "owner": None,
            "risk": None,
            "effort": None,
            "related_goal_id": ids["goal"],
            "related_feature_id": None,
            "related_defect_id": None,
        },
        now,
    )
    event_index += 1

    record_inline_evidence(
        conn,
        evidence_type=START_RECEIPT_CONTRACT_VERSION,
        summary=json.dumps(receipt, ensure_ascii=False, sort_keys=True),
        context=f"start:{ids['task']}",
        command="pcl start",
        evidence_id=ids["evidence"],
        created_at=now,
    )
    _append_planned_event(
        conn,
        paths,
        event_plan[event_index],
        {"evidence_id": ids["evidence"], "receipt": receipt},
        now,
    )
    event_index += 1

    feature = spec.value["feature"]
    conn.execute(
        """
        INSERT INTO features(
          id, name, surface, description, status, confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'discovered', 'medium', ?, ?)
        """,
        (
            ids["feature"],
            feature["name"],
            feature["surface"],
            feature["description"],
            now,
            now,
        ),
    )
    conn.execute(
        "UPDATE tasks SET related_feature_id = ?, updated_at = ? WHERE id = ?",
        (ids["feature"], now, ids["task"]),
    )
    _append_planned_event(
        conn,
        paths,
        event_plan[event_index],
        {
            "name": feature["name"],
            "surface": feature["surface"],
            "description": feature["description"],
            "evidence": "",
            "related_task_id": ids["task"],
        },
        now,
    )
    event_index += 1
    _append_planned_event(
        conn,
        paths,
        event_plan[event_index],
        {"feature_id": ids["feature"]},
        now,
    )
    event_index += 1

    story_ids_by_ref: dict[str, str] = {}
    for story_id, story in zip(ids["stories"], spec.value["stories"], strict=True):
        story_ids_by_ref[story["ref"]] = story_id
        conn.execute(
            """
            INSERT INTO user_stories(
              id, feature_id, actor, goal, benefit, expected_behavior, status,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                story_id,
                ids["feature"],
                story["actor"],
                story["goal"],
                story["benefit"],
                story["expected_behavior"],
                now,
                now,
            ),
        )
        _append_planned_event(
            conn,
            paths,
            event_plan[event_index],
            {
                "feature_id": ids["feature"],
                "actor": story["actor"],
                "goal": story["goal"],
                "benefit": story["benefit"],
                "expected_behavior": story["expected_behavior"],
                "status": "draft",
            },
            now,
        )
        event_index += 1

    conn.execute(
        "UPDATE features SET status = 'needs_test', updated_at = ? WHERE id = ?",
        (now, ids["feature"]),
    )
    _append_planned_event(
        conn,
        paths,
        event_plan[event_index],
        {
            "previous_status": "discovered",
            "status": "needs_test",
            "reason": "test_case_planned",
        },
        now,
    )
    event_index += 1

    for test_id, test in zip(ids["tests"], spec.value["tests"], strict=True):
        story_id = story_ids_by_ref[test["story_ref"]]
        conn.execute(
            """
            INSERT INTO test_cases(
              id, feature_id, story_id, type, scenario, expected, status,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'planned', ?, ?)
            """,
            (
                test_id,
                ids["feature"],
                story_id,
                test["type"],
                test["scenario"],
                test["expected"],
                now,
                now,
            ),
        )
        _append_planned_event(
            conn,
            paths,
            event_plan[event_index],
            {
                "feature_id": ids["feature"],
                "story_id": story_id,
                "type": test["type"],
                "scenario": test["scenario"],
                "expected": test["expected"],
                "status": "planned",
                "feature_status": "needs_test",
            },
            now,
        )
        event_index += 1
    if event_index != len(event_plan):
        raise AssertionError("Direct Setup did not consume its complete event plan.")


def _append_planned_event(
    conn: sqlite3.Connection,
    paths: ProjectPaths,
    plan: dict[str, Any],
    payload: dict[str, Any],
    now: str,
) -> None:
    event_id = append_event(
        conn=conn,
        events_path=paths.events_path,
        event_type=str(plan["event_type"]),
        entity_type=str(plan["entity_type"]),
        entity_id=str(plan["entity_id"]),
        payload=payload,
        event_id=str(plan["id"]),
        outbox_id=str(plan["outbox_id"]),
        created_at=now,
    )
    row = conn.execute(
        "SELECT sequence FROM events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if row is None or int(row["sequence"]) != int(plan["sequence"]):
        raise DirectSetupConflictError(
            "Direct Setup event sequence changed during its transaction.",
            code="direct_setup_event_range_changed",
        )


def _load_verified_retry(
    conn: sqlite3.Connection,
    *,
    anchor,
    intent: str,
    spec: DirectSpecDocument,
    new: bool,
    current_repository_revision: str | None,
    ambiguous_ids: list[str],
) -> dict[str, Any]:
    if (
        str(anchor["event_type"]) != "work_started"
        or str(anchor["entity_type"]) != "task"
        or len(ambiguous_ids) != 1
        or ambiguous_ids[0] != str(anchor["id"])
    ):
        raise DirectSetupConflictError(
            "Direct Setup deterministic anchor collides with existing or ambiguous state.",
            code="direct_setup_anchor_collision",
            details={"anchor_id": str(anchor["id"])},
        )
    try:
        payload = json.loads(str(anchor["payload_json"]))
    except json.JSONDecodeError as exc:
        raise _anchor_corrupt(str(anchor["id"]), "event_payload_invalid") from exc
    if not isinstance(payload, dict):
        raise _anchor_corrupt(str(anchor["id"]), "event_payload_invalid")
    receipt = payload.get("receipt")
    evidence_id = payload.get("evidence_id")
    if (
        not isinstance(receipt, dict)
        or receipt.get("contract_version") != START_RECEIPT_CONTRACT_VERSION
        or not isinstance(evidence_id, str)
    ):
        raise _anchor_corrupt(str(anchor["id"]), "receipt_missing")
    direct_setup = receipt.get("direct_setup")
    if (
        not isinstance(direct_setup, dict)
        or direct_setup.get("contract_version")
        != DIRECT_SETUP_RECEIPT_CONTRACT_VERSION
        or not _valid_direct_setup_binding(direct_setup)
    ):
        raise _anchor_corrupt(str(anchor["id"]), "direct_setup_binding_invalid")
    _require_receipt_shape(receipt, direct_setup, anchor_id=str(anchor["id"]))
    request = direct_setup.get("request")
    if not isinstance(request, dict):
        raise _anchor_corrupt(str(anchor["id"]), "request_missing")
    expected_without_revision = _direct_request(
        intent=intent,
        spec=spec,
        new=new,
        initial_repository_revision=None,
    )
    stored_without_revision = dict(request)
    stored_initial_revision = stored_without_revision.pop(
        "initial_repository_revision",
        None,
    )
    expected_without_revision.pop("initial_repository_revision")
    expected_identity = _canonical_sha256(
        {
            "contract_version": DIRECT_SETUP_IDENTITY_CONTRACT_VERSION,
            "request": request,
        }
    )
    if direct_setup.get("request_identity_sha256") != expected_identity:
        raise _anchor_corrupt(str(anchor["id"]), "request_identity_invalid")
    if (
        receipt.get("actor") != START_ACTOR
        or receipt.get("intent") != request.get("intent")
        or receipt.get("repository_revision") != stored_initial_revision
        or str(anchor["created_at"]) != receipt.get("generated_at")
    ):
        raise _anchor_corrupt(str(anchor["id"]), "start_receipt_identity_invalid")
    bundle = direct_setup.get("bundle_created_ids")
    event_range = direct_setup.get("event_range")
    if not isinstance(bundle, dict) or not isinstance(event_range, dict):
        raise _anchor_corrupt(str(anchor["id"]), "bundle_or_range_missing")
    if (
        bundle.get("start_receipt_evidence") != evidence_id
        or receipt.get("target") != {"type": "task", "id": bundle.get("task")}
        or receipt.get("created_ids")
        != {"goal": bundle.get("goal"), "task": bundle.get("task")}
        or str(anchor["entity_id"]) != bundle.get("task")
    ):
        raise _anchor_corrupt(str(anchor["id"]), "created_ids_mismatch")
    evidence = conn.execute(
        "SELECT type, path, command, summary, created_at FROM evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if evidence is None:
        raise _anchor_corrupt(str(anchor["id"]), "evidence_missing")
    try:
        evidence_receipt = json.loads(str(evidence["summary"]))
    except json.JSONDecodeError as exc:
        raise _anchor_corrupt(str(anchor["id"]), "evidence_invalid") from exc
    if (
        str(evidence["type"]) != START_RECEIPT_CONTRACT_VERSION
        or str(evidence["path"]) != f"inline:start:{bundle.get('task')}"
        or str(evidence["command"]) != "pcl start"
        or evidence_receipt != receipt
        or str(evidence["created_at"]) != receipt.get("generated_at")
    ):
        raise _anchor_corrupt(str(anchor["id"]), "evidence_receipt_mismatch")
    _verify_event_range(
        conn,
        event_range=event_range,
        bundle=bundle,
        expected_created_at=str(receipt["generated_at"]),
    )
    _verify_bundle_entities(conn, request=request, bundle=bundle)
    if stored_without_revision != expected_without_revision:
        raise DirectSetupConflictError(
            "Direct Setup request identity conflicts with the stored request.",
            code="direct_setup_idempotency_conflict",
            details={"request_id": spec.request_id},
        )
    return {
        "task_id": str(bundle["task"]),
        "created_ids": {},
        "receipt": {
            **receipt,
            "evidence_id": evidence_id,
            "event_id": str(anchor["id"]),
        },
        "idempotent": True,
        "reused_ids": {
            "goal": str(bundle["goal"]),
            "task": str(bundle["task"]),
            "feature": str(bundle["feature"]),
            "evidence": evidence_id,
            "event": str(anchor["id"]),
        },
        "repository_revision": {
            "initial": stored_initial_revision,
            "current": current_repository_revision,
            "changed_since_initial": current_repository_revision
            != stored_initial_revision,
        },
    }


def _require_receipt_shape(
    receipt: dict[str, Any],
    direct_setup: dict[str, Any],
    *,
    anchor_id: str,
) -> None:
    if set(receipt) != {
        "contract_version",
        "generated_at",
        "intent",
        "actor",
        "repository_revision",
        "created_ids",
        "target",
        "direct_setup",
    }:
        raise _anchor_corrupt(anchor_id, "start_receipt_shape_invalid")
    if (
        type(receipt.get("generated_at")) is not str
        or type(receipt.get("intent")) is not str
        or (
            receipt.get("repository_revision") is not None
            and type(receipt.get("repository_revision")) is not str
        )
        or type(receipt.get("created_ids")) is not dict
        or type(receipt.get("target")) is not dict
    ):
        raise _anchor_corrupt(anchor_id, "start_receipt_shape_invalid")
    if set(direct_setup) != {
        "contract_version",
        "request",
        "request_identity_sha256",
        "bundle_created_ids",
        "event_range",
        "binding",
    }:
        raise _anchor_corrupt(anchor_id, "direct_setup_shape_invalid")
    request = direct_setup.get("request")
    bundle = direct_setup.get("bundle_created_ids")
    event_range = direct_setup.get("event_range")
    binding = direct_setup.get("binding")
    if not all(type(value) is dict for value in (request, bundle, event_range, binding)):
        raise _anchor_corrupt(anchor_id, "direct_setup_shape_invalid")
    assert isinstance(request, dict)
    assert isinstance(bundle, dict)
    assert isinstance(event_range, dict)
    assert isinstance(binding, dict)
    if set(request) != {
        "contract_version",
        "request_id",
        "intent",
        "new",
        "spec",
        "spec_raw_sha256",
        "spec_canonical_sha256",
        "initial_repository_revision",
    }:
        raise _anchor_corrupt(anchor_id, "request_shape_invalid")
    if (
        request.get("contract_version") != DIRECT_SETUP_REQUEST_CONTRACT_VERSION
        or type(request.get("request_id")) is not str
        or type(request.get("intent")) is not str
        or type(request.get("new")) is not bool
        or type(request.get("spec")) is not dict
        or (
            request.get("initial_repository_revision") is not None
            and type(request.get("initial_repository_revision")) is not str
        )
        or not _is_sha256(request.get("spec_raw_sha256"))
        or not _is_sha256(request.get("spec_canonical_sha256"))
        or not _is_sha256(direct_setup.get("request_identity_sha256"))
    ):
        raise _anchor_corrupt(anchor_id, "request_shape_invalid")
    if set(bundle) != {
        "goal",
        "task",
        "feature",
        "stories",
        "tests",
        "start_receipt_evidence",
        "events",
        "outbox",
    }:
        raise _anchor_corrupt(anchor_id, "bundle_shape_invalid")
    if (
        any(
            type(bundle.get(key)) is not str
            for key in ("goal", "task", "feature", "start_receipt_evidence")
        )
        or any(
            type(bundle.get(key)) is not list
            or not all(type(item) is str for item in bundle[key])
            for key in ("stories", "tests", "events", "outbox")
        )
    ):
        raise _anchor_corrupt(anchor_id, "bundle_shape_invalid")
    if set(event_range) != {
        "start_sequence",
        "end_sequence",
        "count",
        "ordered",
    } or any(
        type(event_range.get(key)) is not int
        for key in ("start_sequence", "end_sequence", "count")
    ):
        raise _anchor_corrupt(anchor_id, "event_range_invalid")
    ordered = event_range.get("ordered")
    if type(ordered) is not list or any(
        type(item) is not dict
        or set(item)
        != {"sequence", "id", "event_type", "entity_type", "entity_id"}
        for item in ordered
    ):
        raise _anchor_corrupt(anchor_id, "event_range_invalid")
    if set(binding) != {
        "contract_version",
        "algorithm",
        "canonical_sha256",
    } or not _is_sha256(binding.get("canonical_sha256")):
        raise _anchor_corrupt(anchor_id, "direct_setup_binding_invalid")


def _is_sha256(value: Any) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _verify_event_range(
    conn: sqlite3.Connection,
    *,
    event_range: dict[str, Any],
    bundle: dict[str, Any],
    expected_created_at: str,
) -> None:
    ordered = event_range.get("ordered")
    if not isinstance(ordered, list) or not ordered:
        raise _anchor_corrupt(None, "event_range_invalid")
    try:
        start = int(event_range["start_sequence"])
        end = int(event_range["end_sequence"])
        count = int(event_range["count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _anchor_corrupt(None, "event_range_invalid") from exc
    rows = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, created_at
        FROM events
        WHERE sequence BETWEEN ? AND ?
        ORDER BY sequence
        """,
        (start, end),
    ).fetchall()
    actual = [
        {
            "sequence": int(row["sequence"]),
            "id": str(row["id"]),
            "event_type": str(row["event_type"]),
            "entity_type": str(row["entity_type"]),
            "entity_id": None if row["entity_id"] is None else str(row["entity_id"]),
        }
        for row in rows
    ]
    if (
        count != len(ordered)
        or count != len(actual)
        or end - start + 1 != count
        or ordered != actual
        or bundle.get("events") != [item["id"] for item in actual]
        or any(str(row["created_at"]) != expected_created_at for row in rows)
    ):
        raise _anchor_corrupt(None, "event_range_mismatch")
    outbox_ids = bundle.get("outbox")
    if not isinstance(outbox_ids, list) or len(outbox_ids) != count:
        raise _anchor_corrupt(None, "outbox_range_invalid")
    placeholders = ", ".join("?" for _ in outbox_ids)
    outbox_rows = conn.execute(
        f"""
        SELECT id, event_id, sink, idempotency_key, status
        FROM outbox_records
        WHERE id IN ({placeholders})
        """,
        tuple(outbox_ids),
    ).fetchall()
    outbox_by_id = {str(row["id"]): row for row in outbox_rows}
    for event, outbox_id in zip(actual, outbox_ids, strict=True):
        row = outbox_by_id.get(str(outbox_id))
        if (
            row is None
            or str(row["event_id"]) != event["id"]
            or str(row["sink"]) != "jsonl"
            or str(row["idempotency_key"]) != f"jsonl:{event['id']}"
            or str(row["status"]) != "delivered"
        ):
            raise _anchor_corrupt(None, "outbox_range_mismatch")


def _verify_bundle_entities(
    conn: sqlite3.Connection,
    *,
    request: dict[str, Any],
    bundle: dict[str, Any],
) -> None:
    spec = request.get("spec")
    stories = bundle.get("stories")
    tests = bundle.get("tests")
    if (
        not isinstance(spec, dict)
        or not isinstance(stories, list)
        or not isinstance(tests, list)
        or len(stories) != len(spec.get("stories", []))
        or len(tests) != len(spec.get("tests", []))
    ):
        raise _anchor_corrupt(None, "bundle_shape_invalid")
    goal = conn.execute(
        "SELECT title, status FROM goals WHERE id = ?",
        (bundle.get("goal"),),
    ).fetchone()
    task = conn.execute(
        """
        SELECT title, status, related_goal_id, related_feature_id
        FROM tasks WHERE id = ?
        """,
        (bundle.get("task"),),
    ).fetchone()
    feature = conn.execute(
        "SELECT name, surface, description, status FROM features WHERE id = ?",
        (bundle.get("feature"),),
    ).fetchone()
    feature_spec = spec.get("feature", {})
    if (
        goal is None
        or str(goal["title"]) != request.get("intent")
        or str(goal["status"]) != "open"
        or task is None
        or str(task["title"]) != request.get("intent")
        or str(task["status"]) != "in_progress"
        or str(task["related_goal_id"]) != bundle.get("goal")
        or str(task["related_feature_id"]) != bundle.get("feature")
        or feature is None
        or str(feature["name"]) != feature_spec.get("name")
        or str(feature["surface"]) != feature_spec.get("surface")
        or str(feature["description"] or "") != feature_spec.get("description")
        or str(feature["status"]) != "needs_test"
    ):
        raise _anchor_corrupt(None, "domain_state_mismatch")
    story_rows = conn.execute(
        f"""
        SELECT id, feature_id, actor, goal, benefit, expected_behavior, status
        FROM user_stories
        WHERE id IN ({', '.join('?' for _ in stories)})
        """,
        tuple(stories),
    ).fetchall()
    story_by_id = {str(row["id"]): row for row in story_rows}
    story_id_by_ref: dict[str, str] = {}
    for story_id, expected in zip(stories, spec["stories"], strict=True):
        row = story_by_id.get(str(story_id))
        if (
            row is None
            or str(row["feature_id"]) != bundle.get("feature")
            or str(row["actor"]) != expected["actor"]
            or str(row["goal"]) != expected["goal"]
            or str(row["benefit"] or "") != expected["benefit"]
            or str(row["expected_behavior"]) != expected["expected_behavior"]
            or str(row["status"]) != "draft"
        ):
            raise _anchor_corrupt(None, "story_state_mismatch")
        story_id_by_ref[expected["ref"]] = str(story_id)
    test_rows = conn.execute(
        f"""
        SELECT id, feature_id, story_id, type, scenario, expected, status
        FROM test_cases
        WHERE id IN ({', '.join('?' for _ in tests)})
        """,
        tuple(tests),
    ).fetchall()
    test_by_id = {str(row["id"]): row for row in test_rows}
    for test_id, expected in zip(tests, spec["tests"], strict=True):
        row = test_by_id.get(str(test_id))
        if (
            row is None
            or str(row["feature_id"]) != bundle.get("feature")
            or str(row["story_id"]) != story_id_by_ref[expected["story_ref"]]
            or str(row["type"]) != expected["type"]
            or str(row["scenario"]) != expected["scenario"]
            or str(row["expected"]) != expected["expected"]
            or str(row["status"]) != "planned"
        ):
            raise _anchor_corrupt(None, "test_state_mismatch")


def _matching_request_event_ids(
    conn: sqlite3.Connection,
    *,
    request_id: str,
) -> list[str]:
    matches: list[str] = []
    for row in conn.execute(
        """
        SELECT id, payload_json
        FROM events
        WHERE event_type = 'work_started'
        ORDER BY sequence
        """
    ).fetchall():
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        receipt = payload.get("receipt") if isinstance(payload, dict) else None
        direct = receipt.get("direct_setup") if isinstance(receipt, dict) else None
        request = direct.get("request") if isinstance(direct, dict) else None
        if isinstance(request, dict) and request.get("request_id") == request_id:
            matches.append(str(row["id"]))
    return matches


def _direct_request(
    *,
    intent: str,
    spec: DirectSpecDocument,
    new: bool,
    initial_repository_revision: str | None,
) -> dict[str, Any]:
    return {
        "contract_version": DIRECT_SETUP_REQUEST_CONTRACT_VERSION,
        "request_id": spec.request_id,
        "intent": intent,
        "new": new,
        "spec": spec.stored_spec,
        "spec_raw_sha256": spec.raw_sha256,
        "spec_canonical_sha256": spec.canonical_sha256,
        "initial_repository_revision": initial_repository_revision,
    }


def _direct_setup_binding(value: dict[str, Any]) -> str:
    content = dict(value)
    content.pop("binding", None)
    return _canonical_sha256(content)


def _valid_direct_setup_binding(value: dict[str, Any]) -> bool:
    binding = value.get("binding")
    return (
        isinstance(binding, dict)
        and binding.get("contract_version") == DIRECT_SETUP_BINDING_CONTRACT_VERSION
        and binding.get("algorithm") == "sha256"
        and binding.get("canonical_sha256") == _direct_setup_binding(value)
    )


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _random_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _anchor_corrupt(
    anchor_id: str | None,
    reason: str,
) -> DirectSetupConflictError:
    details = {"reason": reason}
    if anchor_id is not None:
        details["anchor_id"] = anchor_id
    return DirectSetupConflictError(
        "Direct Setup deterministic anchor is corrupt.",
        code="direct_setup_anchor_corrupt",
        details=details,
    )
