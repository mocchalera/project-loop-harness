from __future__ import annotations

from typing import Any

from .db import connect
from .errors import InvalidInputError
from .events import append_event
from .evidence import record_inline_evidence
from .guards import require_initialized
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

    conn = connect(paths.db_path)
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
    now = utc_now_iso()

    conn = connect(paths.db_path)
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
        return {"ok": True, "feature_status": feature_status, **row}
    finally:
        conn.close()


def pass_test_case(
    paths: ProjectPaths,
    *,
    test_case_id: str,
    summary: str,
    evidence: str,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    return _transition_test_case(
        paths,
        test_case_id=test_case_id,
        status="passing",
        event_type="test_case_passed",
        summary=summary,
        evidence=evidence,
        workflow_run_id=workflow_run_id,
        evidence_type="test_case_pass",
        require_evidence=True,
        command_name="pcl test pass",
    )


def fail_test_case(
    paths: ProjectPaths,
    *,
    test_case_id: str,
    summary: str,
    evidence: str,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    return _transition_test_case(
        paths,
        test_case_id=test_case_id,
        status="failing",
        event_type="test_case_failed",
        summary=summary,
        evidence=evidence,
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

    conn = connect(paths.db_path)
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
    evidence_type: str | None = None,
    require_evidence: bool = False,
    text_field: str = "summary",
    command_name: str = "pcl test",
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(test_case_id, "test_case_id")
    if workflow_run_id:
        _validate_identifier(workflow_run_id, "workflow_run_id")
    _require_text(summary, f"--{text_field.replace('_', '-')} is required.")
    now = utc_now_iso()

    conn = connect(paths.db_path)
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
        if require_evidence:
            _require_text(
                evidence,
                "--evidence is required for this test case transition. Use command output, "
                "artifact path, screenshot path, commit, or report path.",
            )
        if workflow_run_id:
            _get_workflow_run(conn, workflow_run_id)
        evidence_id = None
        if evidence_type and evidence.strip():
            evidence_id = record_inline_evidence(
                conn,
                evidence_type=evidence_type,
                summary=evidence.strip(),
                context=f"test-case/{test_case_id}/{status}",
                command=command_name,
            )
        conn.execute(
            """
            UPDATE test_cases
            SET status = ?, last_run_id = COALESCE(?, last_run_id), evidence_id = COALESCE(?, evidence_id), updated_at = ?
            WHERE id = ?
            """,
            (status, workflow_run_id, evidence_id, now, test_case_id),
        )
        feature_status = _refresh_feature_status_for_tests(conn, paths, str(test_case["feature_id"]), now)
        cleaned_summary = summary.strip()
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=event_type,
            entity_type="test_case",
            entity_id=test_case_id,
            payload={
                text_field: cleaned_summary,
                "feature_id": test_case["feature_id"],
                "story_id": test_case["story_id"],
                "workflow_run_id": workflow_run_id,
                "evidence_id": evidence_id,
                "previous_status": test_case["status"],
                "status": status,
                "feature_status": feature_status,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": test_case_id,
            "feature_id": test_case["feature_id"],
            "story_id": test_case["story_id"],
            "status": status,
            "workflow_run_id": workflow_run_id,
            "evidence_id": evidence_id,
            text_field: cleaned_summary,
            "feature_status": feature_status,
            "changed": True,
        }
    finally:
        conn.close()


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
