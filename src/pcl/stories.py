from __future__ import annotations

from typing import Any

from .db import connect, connect_mutation
from .completion_policies import require_completion_policy
from .errors import InvalidInputError
from .events import append_event
from .evidence import (
    ADHOC_EVIDENCE_TYPES,
    LEGACY_INLINE_EVIDENCE_WARNING,
    EvidenceAddError,
    insert_evidence_link,
    record_inline_evidence,
    require_healthy_terminal_evidence,
)
from .guards import require_initialized
from .evidence_sets import EVIDENCE_SET_EVIDENCE_TYPE
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso


STORY_STATUSES = {"draft", "review", "approved", "waived"}
TEST_CASE_STATUSES = {"planned", "missing", "passing", "failing", "blocked", "waived"}
TEST_CASE_TYPES = {"unit", "integration", "e2e", "manual", "smoke", "acceptance"}
NON_TERMINAL_TEST_CASE_STATUSES = {"planned", "missing", "passing", "failing", "blocked"}


def draft_story(
    paths: ProjectPaths,
    *,
    feature_id: str,
    actor: str,
    goal: str,
    benefit: str = "",
    expected_behavior: str,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(feature_id, "feature_id")
    _require_text(actor, "--actor is required to draft a story.")
    _require_text(goal, "--goal is required to draft a story.")
    _require_text(expected_behavior, "--expected-behavior is required to draft a story.")
    now = utc_now_iso()

    conn = connect_mutation(paths)
    try:
        _get_feature(conn, feature_id)
        story_id = next_prefixed_id(conn, "user_stories", "US")
        row = {
            "id": story_id,
            "feature_id": feature_id,
            "actor": actor.strip(),
            "goal": goal.strip(),
            "benefit": benefit.strip(),
            "expected_behavior": expected_behavior.strip(),
            "status": "draft",
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO user_stories(
              id, feature_id, actor, goal, benefit, expected_behavior, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["feature_id"],
                row["actor"],
                row["goal"],
                row["benefit"],
                row["expected_behavior"],
                row["status"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="user_story_drafted",
            entity_type="user_story",
            entity_id=story_id,
            payload={
                "feature_id": feature_id,
                "actor": row["actor"],
                "goal": row["goal"],
                "benefit": row["benefit"],
                "expected_behavior": row["expected_behavior"],
                "status": "draft",
            },
        )
        conn.commit()
        return {"ok": True, **row}
    finally:
        conn.close()


def review_story(paths: ProjectPaths, *, story_id: str, summary: str) -> dict[str, Any]:
    return _transition_story(
        paths,
        story_id=story_id,
        status="review",
        event_type="user_story_reviewed",
        summary=summary,
        allowed_statuses={"draft"},
        text_field="summary",
    )


def approve_story(paths: ProjectPaths, *, story_id: str, summary: str) -> dict[str, Any]:
    return _transition_story(
        paths,
        story_id=story_id,
        status="approved",
        event_type="user_story_approved",
        summary=summary,
        allowed_statuses={"draft", "review"},
        text_field="summary",
        feature_status_update=("specified", {"discovered"}),
    )


def waive_story(paths: ProjectPaths, *, story_id: str, reason: str) -> dict[str, Any]:
    return _transition_story(
        paths,
        story_id=story_id,
        status="waived",
        event_type="user_story_waived",
        summary=reason,
        allowed_statuses={"draft", "review", "approved"},
        text_field="reason",
    )


def list_stories(
    paths: ProjectPaths,
    *,
    feature_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    require_initialized(paths)
    if feature_id:
        _validate_identifier(feature_id, "feature_id")
    if status:
        _require_story_status(status)
    clauses = []
    params: list[str] = []
    if feature_id:
        clauses.append("feature_id = ?")
        params.append(feature_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT id, feature_id, actor, goal, benefit, expected_behavior, status, created_at, updated_at
            FROM user_stories
            {where}
            ORDER BY created_at DESC, id DESC
            """,
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def read_story(paths: ProjectPaths, story_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(story_id, "story_id")
    conn = connect(paths.db_path)
    try:
        return dict(_get_story(conn, story_id))
    finally:
        conn.close()


def plan_test_case(
    paths: ProjectPaths,
    *,
    feature_id: str,
    test_type: str,
    scenario: str,
    expected: str,
    story_id: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(feature_id, "feature_id")
    if story_id:
        _validate_identifier(story_id, "story_id")
    _require_test_case_type(test_type)
    _require_text(scenario, "--scenario is required to plan a test case.")
    _require_text(expected, "--expected is required to plan a test case.")
    advisory_warning: dict[str, Any] | None = None
    if not story_id:
        policy = _lifecycle_integrity_policy(paths)
        if policy == "enforced":
            raise EvidenceAddError(
                "Test planning requires --story when lifecycle integrity is enforced.",
                code="test_story_required",
                details={"feature_id": feature_id, "policy": policy},
            )
        advisory_warning = {
            "code": "test_story_required",
            "message": "Planned Test has no Story under advisory lifecycle policy.",
        }
    now = utc_now_iso()

    conn = connect_mutation(paths)
    try:
        _get_feature(conn, feature_id)
        if story_id:
            story = _get_story(conn, story_id)
            if story["feature_id"] != feature_id:
                raise InvalidInputError(
                    f"Story {story_id} belongs to {story['feature_id']} and cannot be linked to feature {feature_id}.",
                    details={
                        "story_id": story_id,
                        "story_feature_id": story["feature_id"],
                        "feature_id": feature_id,
                    },
                )
        test_case_id = next_prefixed_id(conn, "test_cases", "TC")
        row = {
            "id": test_case_id,
            "feature_id": feature_id,
            "story_id": story_id,
            "type": test_type,
            "scenario": scenario.strip(),
            "expected": expected.strip(),
            "status": "planned",
            "last_run_id": None,
            "evidence_id": None,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO test_cases(
              id, feature_id, story_id, type, scenario, expected, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["feature_id"],
                row["story_id"],
                row["type"],
                row["scenario"],
                row["expected"],
                row["status"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        feature_status = _set_feature_status(
            conn,
            paths,
            feature_id,
            "needs_test",
            now,
            reason="test_case_planned",
            allowed_previous={"discovered", "specified"},
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="test_case_planned",
            entity_type="test_case",
            entity_id=test_case_id,
            payload={
                "feature_id": feature_id,
                "story_id": story_id,
                "type": test_type,
                "scenario": row["scenario"],
                "expected": row["expected"],
                "status": "planned",
                "feature_status": feature_status,
            },
        )
        conn.commit()
        result = {"ok": True, "feature_status": feature_status, **row}
        if advisory_warning is not None:
            result["warnings"] = [
                {
                    **advisory_warning,
                    "suggested_command": (
                        f"pcl test link {test_case_id} --story US-XXXX "
                        "--summary 'Link planned acceptance contract'"
                    ),
                }
            ]
        return result
    finally:
        conn.close()


def pass_test_case(
    paths: ProjectPaths,
    *,
    test_case_id: str,
    summary: str,
    evidence: str = "",
    evidence_id: str | None = None,
    workflow_run_id: str | None = None,
    completion_policy_file: str | None = None,
) -> dict[str, Any]:
    return _transition_test_case(
        paths,
        test_case_id=test_case_id,
        status="passing",
        event_type="test_case_passed",
        summary=summary,
        evidence=evidence,
        evidence_id=evidence_id,
        workflow_run_id=workflow_run_id,
        evidence_type="test_case_pass",
        require_evidence=True,
        command_name="pcl test pass",
        completion_policy_file=completion_policy_file,
    )


def fail_test_case(
    paths: ProjectPaths,
    *,
    test_case_id: str,
    summary: str,
    evidence: str = "",
    evidence_id: str | None = None,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    return _transition_test_case(
        paths,
        test_case_id=test_case_id,
        status="failing",
        event_type="test_case_failed",
        summary=summary,
        evidence=evidence,
        evidence_id=evidence_id,
        workflow_run_id=workflow_run_id,
        evidence_type="test_case_fail",
        require_evidence=True,
        command_name="pcl test fail",
    )


def block_test_case(
    paths: ProjectPaths,
    *,
    test_case_id: str,
    summary: str,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    return _transition_test_case(
        paths,
        test_case_id=test_case_id,
        status="blocked",
        event_type="test_case_blocked",
        summary=summary,
        workflow_run_id=workflow_run_id,
        command_name="pcl test block",
    )


def missing_test_case(paths: ProjectPaths, *, test_case_id: str, summary: str) -> dict[str, Any]:
    return _transition_test_case(
        paths,
        test_case_id=test_case_id,
        status="missing",
        event_type="test_case_marked_missing",
        summary=summary,
        command_name="pcl test missing",
    )


def waive_test_case(paths: ProjectPaths, *, test_case_id: str, reason: str) -> dict[str, Any]:
    return _transition_test_case(
        paths,
        test_case_id=test_case_id,
        status="waived",
        event_type="test_case_waived",
        summary=reason,
        evidence=reason,
        evidence_type="test_case_waiver",
        require_evidence=True,
        text_field="reason",
        command_name="pcl test waive",
    )


def list_test_cases(
    paths: ProjectPaths,
    *,
    feature_id: str | None = None,
    story_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    require_initialized(paths)
    if feature_id:
        _validate_identifier(feature_id, "feature_id")
    if story_id:
        _validate_identifier(story_id, "story_id")
    if status:
        _require_test_case_status(status)
    clauses = []
    params: list[str] = []
    if feature_id:
        clauses.append("feature_id = ?")
        params.append(feature_id)
    if story_id:
        clauses.append("story_id = ?")
        params.append(story_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT id, feature_id, story_id, type, scenario, expected, status, last_run_id, evidence_id, created_at, updated_at
            FROM test_cases
            {where}
            ORDER BY created_at DESC, id DESC
            """,
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def read_test_case(paths: ProjectPaths, test_case_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(test_case_id, "test_case_id")
    conn = connect(paths.db_path)
    try:
        return dict(_get_test_case(conn, test_case_id))
    finally:
        conn.close()


def _transition_story(
    paths: ProjectPaths,
    *,
    story_id: str,
    status: str,
    event_type: str,
    summary: str,
    allowed_statuses: set[str],
    text_field: str,
    feature_status_update: tuple[str, set[str]] | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(story_id, "story_id")
    _require_text(summary, f"--{text_field.replace('_', '-')} is required.")
    now = utc_now_iso()

    conn = connect_mutation(paths)
    try:
        story = _get_story(conn, story_id)
        if story["status"] not in allowed_statuses:
            raise InvalidInputError(
                f"Story {story_id} is {story['status']} and cannot transition to {status}.",
                details={
                    "story_id": story_id,
                    "status": story["status"],
                    "requested_status": status,
                    "allowed_statuses": sorted(allowed_statuses),
                },
            )
        conn.execute(
            "UPDATE user_stories SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, story_id),
        )
        feature_status = None
        if feature_status_update:
            next_status, allowed_previous = feature_status_update
            feature_status = _set_feature_status(
                conn,
                paths,
                str(story["feature_id"]),
                next_status,
                now,
                reason=event_type,
                allowed_previous=allowed_previous,
            )
        cleaned_summary = summary.strip()
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=event_type,
            entity_type="user_story",
            entity_id=story_id,
            payload={
                text_field: cleaned_summary,
                "feature_id": story["feature_id"],
                "previous_status": story["status"],
                "status": status,
                "feature_status": feature_status,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": story_id,
            "feature_id": story["feature_id"],
            "status": status,
            text_field: cleaned_summary,
            "feature_status": feature_status,
        }
    finally:
        conn.close()


def _transition_test_case(
    paths: ProjectPaths,
    *,
    test_case_id: str,
    status: str,
    event_type: str,
    summary: str,
    workflow_run_id: str | None = None,
    evidence: str = "",
    evidence_id: str | None = None,
    evidence_type: str | None = None,
    require_evidence: bool = False,
    text_field: str = "summary",
    command_name: str = "pcl test",
    completion_policy_file: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(test_case_id, "test_case_id")
    if workflow_run_id:
        _validate_identifier(workflow_run_id, "workflow_run_id")
    _require_text(summary, f"--{text_field.replace('_', '-')} is required.")
    now = utc_now_iso()

    conn = connect_mutation(paths)
    try:
        test_case = _get_test_case(conn, test_case_id)
        if test_case["status"] == status:
            return {
                "ok": True,
                "id": test_case_id,
                "feature_id": test_case["feature_id"],
                "story_id": test_case["story_id"],
                "status": status,
                "workflow_run_id": test_case["last_run_id"],
                "evidence_id": test_case["evidence_id"],
                "changed": False,
                "evidence_recorded": False,
            }
        if test_case["status"] not in NON_TERMINAL_TEST_CASE_STATUSES:
            raise InvalidInputError(
                f"Test case {test_case_id} is {test_case['status']} and cannot transition to {status}.",
                details={
                    "test_case_id": test_case_id,
                    "status": test_case["status"],
                    "requested_status": status,
                },
            )
        if require_evidence and not evidence_id:
            _require_text(
                evidence,
                "--evidence is required for this test case transition. Use command output, "
                "artifact path, screenshot path, commit, or report path.",
            )
        if status == "passing":
            story_id = str(test_case["story_id"] or "")
            if not story_id:
                raise EvidenceAddError(
                    f"Test case {test_case_id} must link to a Story before it can pass.",
                    code="test_story_required",
                    details={"test_case_id": test_case_id},
                )
            story = _get_story(conn, story_id)
            if story["feature_id"] != test_case["feature_id"]:
                raise EvidenceAddError(
                    f"Story {story_id} does not belong to test case feature {test_case['feature_id']}.",
                    code="test_story_required",
                    details={"test_case_id": test_case_id, "story_id": story_id},
                )
            if story["status"] not in {"approved", "waived"}:
                raise EvidenceAddError(
                    f"Story {story_id} is {story['status']}; passing requires approved or waived.",
                    code="test_story_not_terminal",
                    details={"test_case_id": test_case_id, "story_id": story_id, "story_status": story["status"]},
                )
        if workflow_run_id:
            _get_workflow_run(conn, workflow_run_id)
        selected_evidence_id = str(evidence_id or "").strip() or None
        evidence_mode = "id" if selected_evidence_id else None
        completion_evaluation: dict[str, Any] | None = None
        if selected_evidence_id:
            evidence_row = conn.execute(
                "SELECT type FROM evidence WHERE id = ?",
                (selected_evidence_id,),
            ).fetchone()
            evidence_type_value = "" if evidence_row is None else str(evidence_row["type"])
            if evidence_type_value == EVIDENCE_SET_EVIDENCE_TYPE:
                if status != "passing":
                    raise EvidenceAddError(
                        "Evidence set terminal policy is supported only for passing Tests.",
                        code="completion_policy_unsupported_transition",
                        details={"test_case_id": test_case_id, "status": status},
                    )
                if not completion_policy_file:
                    raise EvidenceAddError(
                        "Passing with evidence_set Evidence requires --completion-policy.",
                        code="completion_policy_required",
                        details={"test_case_id": test_case_id, "evidence_id": selected_evidence_id},
                    )
                completion_evaluation = require_completion_policy(
                    paths,
                    conn,
                    policy_file=completion_policy_file,
                    evidence_set_id=selected_evidence_id,
                    test_case_id=test_case_id,
                )
            else:
                if completion_policy_file:
                    raise EvidenceAddError(
                        "--completion-policy requires evidence_set Evidence via --evidence-id.",
                        code="completion_policy_evidence_set_required",
                        details={"test_case_id": test_case_id, "evidence_id": selected_evidence_id},
                    )
                require_healthy_terminal_evidence(
                    paths,
                    conn,
                    evidence_id=selected_evidence_id,
                    error_code="test_acceptance_evidence_required",
                    allowed_types=ADHOC_EVIDENCE_TYPES,
                )
        elif completion_policy_file:
            raise EvidenceAddError(
                "--completion-policy requires evidence_set Evidence via --evidence-id.",
                code="completion_policy_evidence_set_required",
                details={"test_case_id": test_case_id},
            )
        elif status == "passing" and not workflow_run_id:
            raise EvidenceAddError(
                "Direct test passing requires healthy hash-pinned Evidence via --evidence-id.",
                code="test_acceptance_evidence_required",
                details={"test_case_id": test_case_id, "reason": "direct_evidence_required"},
            )
        elif evidence_type and evidence.strip():
            selected_evidence_id = record_inline_evidence(
                conn,
                evidence_type=evidence_type,
                summary=evidence.strip(),
                context=f"test-case/{test_case_id}/{status}",
                command=command_name,
            )
            if command_name in {"pcl test pass", "pcl test fail"}:
                evidence_mode = "legacy_inline"
        if selected_evidence_id and evidence_mode == "id":
            insert_evidence_link(
                conn,
                evidence_id=selected_evidence_id,
                target_type="test_case",
                target_id=test_case_id,
                link_role="acceptance" if status == "passing" else "supporting",
                created_at=now,
            )
        conn.execute(
            """
            UPDATE test_cases
            SET status = ?, last_run_id = COALESCE(?, last_run_id), evidence_id = COALESCE(?, evidence_id), updated_at = ?
            WHERE id = ?
            """,
            (status, workflow_run_id, selected_evidence_id, now, test_case_id),
        )
        feature_status = _refresh_feature_status_for_tests(conn, paths, str(test_case["feature_id"]), now)
        cleaned_summary = summary.strip()
        event_payload = {
            text_field: cleaned_summary,
            "feature_id": test_case["feature_id"],
            "story_id": test_case["story_id"],
            "workflow_run_id": workflow_run_id,
            "evidence_id": selected_evidence_id,
            "previous_status": test_case["status"],
            "status": status,
            "feature_status": feature_status,
        }
        if evidence_mode is not None:
            event_payload["evidence_mode"] = evidence_mode
        if completion_evaluation is not None:
            event_payload["completion_evaluation"] = completion_evaluation
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=event_type,
            entity_type="test_case",
            entity_id=test_case_id,
            payload=event_payload,
        )
        conn.commit()
        result = {
            "ok": True,
            "id": test_case_id,
            "feature_id": test_case["feature_id"],
            "story_id": test_case["story_id"],
            "status": status,
            "workflow_run_id": workflow_run_id,
            "evidence_id": selected_evidence_id,
            text_field: cleaned_summary,
            "feature_status": feature_status,
            "changed": True,
        }
        if evidence_mode is not None:
            result["evidence_mode"] = evidence_mode
        if completion_evaluation is not None:
            result["completion_evaluation"] = completion_evaluation
        if evidence_mode == "legacy_inline":
            result["warnings"] = [dict(LEGACY_INLINE_EVIDENCE_WARNING)]
        return result
    finally:
        conn.close()


def _lifecycle_integrity_policy(paths: ProjectPaths) -> str:
    config_path = paths.root / "pcl.yaml"
    if not config_path.is_file():
        return "advisory"
    in_validation = False
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("validation:"):
            in_validation = True
            continue
        if in_validation and raw_line and not raw_line.startswith(" "):
            break
        if not in_validation or not raw_line.startswith("  ") or ":" not in raw_line:
            continue
        key, value = raw_line.strip().split(":", 1)
        if key == "lifecycle_integrity":
            return value.strip().strip("\"'") or "advisory"
    return "advisory"


def _get_feature(conn, feature_id: str):
    row = conn.execute("SELECT id, status FROM features WHERE id = ?", (feature_id,)).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Feature does not exist: {feature_id}",
            details={"feature_id": feature_id},
        )
    return row


def _get_story(conn, story_id: str):
    row = conn.execute(
        """
        SELECT id, feature_id, actor, goal, benefit, expected_behavior, status, created_at, updated_at
        FROM user_stories
        WHERE id = ?
        """,
        (story_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Story does not exist: {story_id}",
            details={"story_id": story_id},
        )
    return row


def _get_test_case(conn, test_case_id: str):
    row = conn.execute(
        """
        SELECT id, feature_id, story_id, type, scenario, expected, status, last_run_id, evidence_id, created_at, updated_at
        FROM test_cases
        WHERE id = ?
        """,
        (test_case_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Test case does not exist: {test_case_id}",
            details={"test_case_id": test_case_id},
        )
    return row


def _get_workflow_run(conn, workflow_run_id: str):
    row = conn.execute("SELECT id FROM workflow_runs WHERE id = ?", (workflow_run_id,)).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Workflow run does not exist: {workflow_run_id}",
            details={"workflow_run_id": workflow_run_id},
        )
    return row


def _set_feature_status(
    conn,
    paths: ProjectPaths,
    feature_id: str,
    next_status: str,
    now: str,
    *,
    reason: str,
    allowed_previous: set[str] | None = None,
) -> str:
    feature = _get_feature(conn, feature_id)
    previous_status = str(feature["status"])
    if previous_status == next_status:
        return previous_status
    if allowed_previous is not None and previous_status not in allowed_previous:
        return previous_status
    conn.execute("UPDATE features SET status = ?, updated_at = ? WHERE id = ?", (next_status, now, feature_id))
    append_event(
        conn=conn,
        events_path=paths.events_path,
        event_type="feature_status_updated",
        entity_type="feature",
        entity_id=feature_id,
        payload={"previous_status": previous_status, "status": next_status, "reason": reason},
    )
    return next_status


def _refresh_feature_status_for_tests(conn, paths: ProjectPaths, feature_id: str, now: str) -> str:
    active_defect_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM defects
        WHERE feature_id = ? AND status NOT IN ('closed', 'waived')
        """,
        (feature_id,),
    ).fetchone()["count"]
    if int(active_defect_count) > 0:
        return _set_feature_status(
            conn,
            paths,
            feature_id,
            "needs_fix",
            now,
            reason="test_case_status",
        )

    blocking_test_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM test_cases
        WHERE feature_id = ? AND status IN ('missing', 'failing', 'blocked')
        """,
        (feature_id,),
    ).fetchone()["count"]
    if int(blocking_test_count) > 0:
        return _set_feature_status(
            conn,
            paths,
            feature_id,
            "needs_fix",
            now,
            reason="test_case_status",
        )

    non_waived_test_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM test_cases
        WHERE feature_id = ? AND status != 'waived'
        """,
        (feature_id,),
    ).fetchone()["count"]
    non_passing_test_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM test_cases
        WHERE feature_id = ? AND status NOT IN ('passing', 'waived')
        """,
        (feature_id,),
    ).fetchone()["count"]
    if int(non_waived_test_count) > 0 and int(non_passing_test_count) == 0:
        return _set_feature_status(
            conn,
            paths,
            feature_id,
            "passing",
            now,
            reason="test_case_status",
        )

    return str(_get_feature(conn, feature_id)["status"])


def _require_story_status(status: str) -> None:
    if status not in STORY_STATUSES:
        raise InvalidInputError(
            f"Invalid story status: {status}",
            details={"status": status, "allowed": sorted(STORY_STATUSES)},
        )


def _require_test_case_status(status: str) -> None:
    if status not in TEST_CASE_STATUSES:
        raise InvalidInputError(
            f"Invalid test case status: {status}",
            details={"status": status, "allowed": sorted(TEST_CASE_STATUSES)},
        )


def _require_test_case_type(test_type: str) -> None:
    if test_type not in TEST_CASE_TYPES:
        raise InvalidInputError(
            f"Invalid test case type: {test_type}",
            details={"type": test_type, "allowed": sorted(TEST_CASE_TYPES)},
        )


def _require_text(value: str, message: str) -> None:
    if not value.strip():
        raise InvalidInputError(message)


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or not all(c.isalnum() or c in {"_", "-"} for c in value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={"field": field_name, "value": value},
        )
