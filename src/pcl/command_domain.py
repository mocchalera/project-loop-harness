from __future__ import annotations

import json
from json import JSONDecodeError

from .db import connect, connect_mutation
from .evidence import (
    ADHOC_EVIDENCE_TYPES,
    LEGACY_INLINE_EVIDENCE_WARNING,
    EvidenceAddError,
    insert_evidence_link,
    record_inline_evidence,
    require_healthy_terminal_evidence,
)
from .events import append_event
from .errors import InvalidInputError
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso

FEATURE_STATUSES = {"discovered", "specified", "needs_test", "needs_fix", "passing", "done", "waived"}


def _normalized_json_object(raw: str, field_name: str) -> str:
    try:
        value = json.loads(raw)
    except JSONDecodeError as exc:
        raise InvalidInputError(
            f"{field_name} must be valid JSON: {exc.msg}.",
            details={"field": field_name, "position": exc.pos},
        ) from exc
    if not isinstance(value, dict):
        raise InvalidInputError(
            f"{field_name} must be a JSON object.",
            details={"field": field_name, "type": type(value).__name__},
        )
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def create_goal(paths: ProjectPaths, *, title: str, completion_json: str = "{}", budget_json: str = "{}") -> str:
    require_initialized(paths)
    completion_json = _normalized_json_object(completion_json, "completion-json")
    budget_json = _normalized_json_object(budget_json, "budget-json")

    conn = connect_mutation(paths)
    try:
        goal_id = next_prefixed_id(conn, "goals", "G")
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO goals(id, title, status, completion_json, stop_conditions_json, budget_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (goal_id, title, "open", completion_json, "{}", budget_json, now, now),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="goal_created",
            entity_type="goal",
            entity_id=goal_id,
            payload={"title": title},
        )
        conn.commit()
        return goal_id
    finally:
        conn.close()


def add_feature(
    paths: ProjectPaths,
    *,
    name: str,
    surface: str,
    description: str = "",
    evidence: str = "",
    task_id: str | None = None,
) -> str:
    require_initialized(paths)

    conn = connect_mutation(paths)
    try:
        task = None
        if task_id:
            task = conn.execute(
                "SELECT id, related_feature_id FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise InvalidInputError(
                    f"Task does not exist: {task_id}", details={"task_id": task_id}
                )
            if task["related_feature_id"]:
                raise InvalidInputError(
                    f"Task {task_id} is already linked to Feature {task['related_feature_id']}.",
                    details={
                        "task_id": task_id,
                        "related_feature_id": str(task["related_feature_id"]),
                    },
                )
        feature_id = next_prefixed_id(conn, "features", "F")
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO features(id, name, surface, description, status, confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (feature_id, name, surface, description, "discovered", "medium", now, now),
        )
        if task_id:
            conn.execute(
                "UPDATE tasks SET related_feature_id = ?, updated_at = ? WHERE id = ?",
                (feature_id, now, task_id),
            )
        payload = {
            "name": name,
            "surface": surface,
            "description": description,
            "evidence": evidence,
            "related_task_id": task_id,
        }
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="feature_added",
            entity_type="feature",
            entity_id=feature_id,
            payload=payload,
        )
        if task_id:
            append_event(
                conn=conn,
                events_path=paths.events_path,
                event_type="task_feature_linked",
                entity_type="task",
                entity_id=task_id,
                payload={"feature_id": feature_id},
            )
        conn.commit()
        return feature_id
    finally:
        conn.close()


def list_features(paths: ProjectPaths, *, status: str | None = None) -> list[dict]:
    require_initialized(paths)
    if status:
        _require_feature_status(status)

    clauses: list[str] = []
    params: list[str] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT id, name, surface, description, status, confidence, created_at, updated_at
            FROM features
            {where_sql}
            ORDER BY id
            """,
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def read_feature(paths: ProjectPaths, feature_id: str) -> dict:
    require_initialized(paths)
    _validate_identifier(feature_id, "feature_id")

    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, name, surface, description, status, confidence, created_at, updated_at
            FROM features
            WHERE id = ?
            """,
            (feature_id,),
        ).fetchone()
        if row is None:
            raise InvalidInputError(
                f"Feature does not exist: {feature_id}",
                details={"feature_id": feature_id},
            )
        return dict(row)
    finally:
        conn.close()


def set_feature_status(
    paths: ProjectPaths,
    feature_id: str,
    *,
    status: str,
    summary: str,
    evidence: str = "",
    evidence_id: str | None = None,
) -> dict:
    require_initialized(paths)
    _validate_identifier(feature_id, "feature_id")
    _require_feature_status(status)

    conn = connect_mutation(paths)
    try:
        feature = conn.execute(
            "SELECT id, status FROM features WHERE id = ?",
            (feature_id,),
        ).fetchone()
        if feature is None:
            raise InvalidInputError(
                f"Feature does not exist: {feature_id}",
                details={"feature_id": feature_id},
            )
        previous_status = str(feature["status"])
        if previous_status == status:
            return {
                "ok": True,
                "feature_id": feature_id,
                "previous_status": previous_status,
                "status": status,
                "changed": False,
                "evidence_recorded": False,
            }

        _require_text(summary, "--summary is required to update feature status.")
        selected_evidence_id = str(evidence_id or "").strip() or None
        evidence_mode = "id" if selected_evidence_id else "legacy_inline"
        if not selected_evidence_id:
            _require_text(
                evidence,
                "--evidence or --evidence-id is required to update feature status.",
            )

        if status == "done":
            _guard_feature_done(conn, feature_id)
            if not selected_evidence_id:
                raise EvidenceAddError(
                    "Feature done requires healthy target-bound Evidence via --evidence-id.",
                    code="feature_done_evidence_required",
                    details={"feature_id": feature_id},
                )
        if selected_evidence_id:
            require_healthy_terminal_evidence(
                paths,
                conn,
                evidence_id=selected_evidence_id,
                error_code="feature_done_evidence_required",
                allowed_types=ADHOC_EVIDENCE_TYPES,
            )

        now = utc_now_iso()
        if selected_evidence_id is None:
            selected_evidence_id = record_inline_evidence(
                conn,
                evidence_type="feature_status",
                summary=evidence.strip(),
                context=f"feature/{feature_id}/status",
                command="pcl feature status",
            )
        else:
            insert_evidence_link(
                conn,
                evidence_id=selected_evidence_id,
                target_type="feature",
                target_id=feature_id,
                link_role="acceptance" if status == "done" else "supporting",
                created_at=now,
            )
        conn.execute(
            "UPDATE features SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, feature_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="feature_status_updated",
            entity_type="feature",
            entity_id=feature_id,
            payload={
                "previous_status": previous_status,
                "status": status,
                "summary": summary.strip(),
                "evidence": evidence.strip(),
                "evidence_id": selected_evidence_id,
                "evidence_mode": evidence_mode,
                "source": "manual",
            },
        )
        conn.commit()
        result = {
            "ok": True,
            "feature_id": feature_id,
            "previous_status": previous_status,
            "status": status,
            "summary": summary.strip(),
            "evidence_id": selected_evidence_id,
            "evidence_mode": evidence_mode,
            "changed": True,
        }
        if evidence_mode == "legacy_inline":
            result["warnings"] = [dict(LEGACY_INLINE_EVIDENCE_WARNING)]
        return result
    finally:
        conn.close()


def _guard_feature_done(conn, feature_id: str) -> None:
    stories = conn.execute(
        "SELECT id, status FROM user_stories WHERE feature_id = ? ORDER BY id",
        (feature_id,),
    ).fetchall()
    incomplete_stories = [dict(row) for row in stories if row["status"] not in {"approved", "waived"}]
    if not stories or incomplete_stories:
        raise EvidenceAddError(
            f"Feature {feature_id} has missing or incomplete Stories.",
            code="feature_done_story_incomplete",
            details={"feature_id": feature_id, "stories": incomplete_stories, "story_count": len(stories)},
        )
    tests = conn.execute(
        "SELECT id, status FROM test_cases WHERE feature_id = ? AND status != 'waived' ORDER BY id",
        (feature_id,),
    ).fetchall()
    incomplete_tests = [dict(row) for row in tests if row["status"] != "passing"]
    if not tests or incomplete_tests:
        raise EvidenceAddError(
            f"Feature {feature_id} has missing or incomplete non-waived Tests.",
            code="feature_done_tests_incomplete",
            details={"feature_id": feature_id, "tests": incomplete_tests, "test_count": len(tests)},
        )
    defects = conn.execute(
        "SELECT id, status FROM defects WHERE feature_id = ? AND status NOT IN ('closed', 'waived') ORDER BY id",
        (feature_id,),
    ).fetchall()
    if defects:
        raise EvidenceAddError(
            f"Feature {feature_id} has active Defects.",
            code="feature_done_open_defects",
            details={"feature_id": feature_id, "defects": [dict(row) for row in defects]},
        )


def open_defect(
    paths: ProjectPaths,
    *,
    feature_id: str,
    severity: str,
    expected: str,
    actual: str,
    test_case_id: str | None = None,
    reproduction: str = "",
    evidence: str = "",
) -> str:
    require_initialized(paths)

    conn = connect_mutation(paths)
    try:
        row = conn.execute("SELECT id FROM features WHERE id = ?", (feature_id,)).fetchone()
        if row is None:
            raise InvalidInputError(
                f"Feature does not exist: {feature_id}",
                details={"feature_id": feature_id},
            )
        defect_id = next_prefixed_id(conn, "defects", "D")
        now = utc_now_iso()
        evidence_id = None
        if evidence.strip():
            evidence_id = record_inline_evidence(
                conn,
                evidence_type="defect_open",
                summary=evidence.strip(),
                context=f"defect/{defect_id}/open",
                command="pcl defect open",
            )
        conn.execute(
            """
            INSERT INTO defects(id, feature_id, test_case_id, severity, expected, actual, reproduction, status, evidence_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                defect_id,
                feature_id,
                test_case_id or None,
                severity,
                expected,
                actual,
                reproduction,
                "open",
                evidence_id,
                now,
                now,
            ),
        )
        conn.execute("UPDATE features SET status = ?, updated_at = ? WHERE id = ?", ("needs_fix", now, feature_id))
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="defect_opened",
            entity_type="defect",
            entity_id=defect_id,
            payload={
                "feature_id": feature_id,
                "severity": severity,
                "expected": expected,
                "actual": actual,
                "test_case_id": test_case_id,
                "evidence": evidence,
                "evidence_id": evidence_id,
            },
        )
        conn.commit()
        return defect_id
    finally:
        conn.close()


def loop_status(paths: ProjectPaths) -> dict:
    require_initialized(paths)

    conn = connect(paths.db_path)
    try:
        open_goals = conn.execute(
            """
            SELECT id, title, status
            FROM goals
            WHERE status NOT IN ('closed', 'cancelled')
            ORDER BY created_at DESC
            """
        ).fetchall()
        open_defects = conn.execute(
            """
            SELECT id, feature_id, severity, status
            FROM defects
            WHERE status NOT IN ('closed', 'waived')
            ORDER BY created_at DESC
            """
        ).fetchall()
        runs = conn.execute("SELECT id, workflow_id, status, iteration FROM workflow_runs ORDER BY started_at DESC LIMIT 10").fetchall()
        return {
            "open_goals": [dict(r) for r in open_goals],
            "open_defects": [dict(r) for r in open_defects],
            "recent_workflow_runs": [dict(r) for r in runs],
        }
    finally:
        conn.close()


def _require_feature_status(status: str) -> None:
    if status not in FEATURE_STATUSES:
        raise InvalidInputError(
            f"Invalid feature status: {status}",
            details={"status": status, "allowed": sorted(FEATURE_STATUSES)},
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
