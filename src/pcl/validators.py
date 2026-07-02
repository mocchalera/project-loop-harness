from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from json import JSONDecodeError
import sqlite3
from typing import Any

from .db import connect, get_metadata, table_exists
from .errors import InvalidInputError
from .migrations import migration_status
from .paths import ProjectPaths
from .rubric import claims_rubric_v1, evidence_ids_in_rubric, validate_rubric
from .timeutil import utc_now_iso
from .workflow_proposal_validation import PROPOSAL_ID_RE, validate_workflow_proposal_text
from .workflow_verifier import verify_workflow_text


REQUIRED_TABLES = [
    "metadata",
    "events",
    "goals",
    "workflows",
    "workflow_runs",
    "agent_jobs",
    "features",
    "user_stories",
    "test_cases",
    "defects",
    "decisions",
    "evidence",
    "verifications",
    "escalations",
]
VERSIONED_REQUIRED_TABLES = {
    2: [
        "tasks",
        "task_dependencies",
    ],
    3: [
        "agents",
    ],
}

ACTIVE_RUN_STATUSES = ("blocked", "queued", "running")
TERMINAL_WORKFLOW_PROPOSAL_EVENT_TYPES = {
    "workflow_proposal_approved",
    "workflow_proposal_cancelled",
}


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def validate_project(
    paths: ProjectPaths,
    *,
    strict: bool = False,
    include_config_advice: bool = False,
) -> ValidationResult:
    result = ValidationResult()
    if not paths.loop_dir.exists():
        result.add_error(
            f"Missing .project-loop directory at {paths.loop_dir}. "
            f"Run `pcl init --target {paths.root}`."
        )
        return result
    if not paths.db_path.exists():
        result.add_error(
            f"Missing .project-loop/project.db at {paths.db_path}. "
            f"Run `pcl init --target {paths.root}`."
        )
        return result
    if not paths.events_path.exists():
        if strict:
            result.add_error(f"Missing events.jsonl at {paths.events_path}.")
        else:
            result.add_warning(f"Missing events.jsonl at {paths.events_path}.")

    try:
        conn = connect(paths.db_path)
    except sqlite3.Error as exc:
        result.add_error(f"Cannot open SQLite database at {paths.db_path}: {exc}")
        return result

    try:
        missing_tables: list[str] = []
        for table in REQUIRED_TABLES:
            if not table_exists(conn, table):
                missing_tables.append(table)
                result.add_error(f"Missing table: {table}")
        schema_version = get_metadata(conn, "schema_version")
        current_version: int | None = None
        if schema_version is None:
            result.add_error("Missing metadata.schema_version")
        status = migration_status(paths)
        if schema_version is not None:
            try:
                current_version = int(schema_version)
            except ValueError:
                result.add_error(f"Invalid metadata.schema_version: {schema_version}")
            else:
                if current_version > status.latest_version:
                    result.add_error(
                        f"Unsupported schema_version {schema_version}; "
                        f"latest supported is {status.latest_version}."
                    )
                elif current_version < status.latest_version:
                    result.add_warning(
                        f"Schema version {current_version} is behind latest "
                        f"{status.latest_version}. Run `pcl migrate --root {paths.root}`."
                    )
                for version, tables in sorted(VERSIONED_REQUIRED_TABLES.items()):
                    if current_version >= version:
                        for table in tables:
                            if not table_exists(conn, table):
                                missing_tables.append(table)
                                result.add_error(f"Missing table: {table}")
        if status.pending:
            pending = ", ".join(migration.id for migration in status.pending)
            result.add_warning(f"Pending migrations: {pending}. Run `pcl migrate --root {paths.root}`.")
        if not paths.root.joinpath("pcl.yaml").exists():
            result.add_warning(f"Missing pcl.yaml at {paths.root / 'pcl.yaml'}.")
        elif include_config_advice:
            _validate_pcl_yaml_advice(paths, result)
        skill_path = paths.agents_skill_dir.joinpath("SKILL.md")
        if not skill_path.exists():
            result.add_warning(f"Missing project-control-loop Skill at {skill_path}.")
        if table_exists(conn, "tasks") and table_exists(conn, "task_dependencies"):
            _validate_task_invariants(conn, result)
        if table_exists(conn, "agents") and _agent_jobs_has_lease_columns(conn):
            _validate_agent_registry_invariants(conn, result)
        if "verifications" not in missing_tables:
            _validate_verification_rubrics(
                conn,
                result,
                strict=strict,
                check_evidence="evidence" not in missing_tables,
            )
        if strict and not missing_tables:
            _validate_strict_invariants(paths, conn, result)
        if strict and result.warnings:
            for warning in result.warnings:
                result.add_error(f"Strict mode treats warning as error: {warning}")
            result.warnings.clear()
    except sqlite3.Error as exc:
        result.add_error(f"Cannot validate SQLite database at {paths.db_path}: {exc}")
    finally:
        conn.close()
    return result


def _validate_pcl_yaml_advice(paths: ProjectPaths, result: ValidationResult) -> None:
    config_path = paths.root / "pcl.yaml"
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        result.add_warning(f"Could not read pcl.yaml at {config_path}: {exc}.")
        return

    project = _simple_yaml_section(lines, "project")
    project_name = project.get("name", "")
    if project_name == "CHANGE_ME":
        result.add_warning("pcl.yaml project.name is CHANGE_ME; set it to the real project name.")
    elif not project_name:
        result.add_warning("pcl.yaml project.name is empty; set it to the real project name.")

    commands = _simple_yaml_section(lines, "commands")
    if commands:
        empty_commands = sorted(key for key, value in commands.items() if not value)
        if empty_commands:
            result.add_warning(
                "pcl.yaml commands are empty: "
                f"{', '.join(empty_commands)}. Fill them in or leave intentionally unused commands documented."
            )
    else:
        result.add_warning("pcl.yaml has no commands section; configured checks cannot be discovered.")


def _simple_yaml_section(lines: list[str], section_name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_section = False
    for raw_line in lines:
        if raw_line.startswith(f"{section_name}:"):
            in_section = True
            continue
        if in_section and raw_line and not raw_line.startswith(" "):
            break
        if not in_section or not raw_line.startswith("  ") or ":" not in raw_line:
            continue
        key, value = raw_line.strip().split(":", 1)
        values[key.strip()] = _strip_yaml_string(value.strip())
    return values


def _strip_yaml_string(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _validate_strict_invariants(paths: ProjectPaths, conn: sqlite3.Connection, result: ValidationResult) -> None:
    _validate_audit_log_integrity(paths, conn, result)
    _validate_workflow_proposals(paths, conn, result)
    _validate_foreign_keys(conn, result)
    _validate_closed_goals(conn, result)
    _validate_passed_workflow_runs(conn, result)
    _validate_verified_or_closed_defects(conn, result)
    _validate_terminal_test_cases(conn, result)
    _validate_duplicate_active_runs(conn, result)


def _validate_verification_rubrics(
    conn: sqlite3.Connection,
    result: ValidationResult,
    *,
    strict: bool,
    check_evidence: bool,
) -> None:
    rows = conn.execute(
        """
        SELECT id, rubric_json
        FROM verifications
        ORDER BY created_at, id
        """
    ).fetchall()
    for row in rows:
        verification_id = str(row["id"])
        rubric = _json_object(row["rubric_json"])
        if not claims_rubric_v1(rubric):
            continue
        for problem in validate_rubric(rubric):
            _add_rubric_validation_problem(
                result,
                strict=strict,
                message=f"Verification {verification_id} rubric/v1 invalid: {problem}",
            )
        if strict and check_evidence:
            for evidence_id in _missing_evidence_ids(conn, evidence_ids_in_rubric(rubric)):
                result.add_error(
                    f"Verification {verification_id} rubric/v1 references missing evidence {evidence_id}."
                )


def _add_rubric_validation_problem(
    result: ValidationResult,
    *,
    strict: bool,
    message: str,
) -> None:
    if strict:
        result.add_error(message)
    else:
        result.add_warning(message)


def _validate_workflow_proposals(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    result: ValidationResult,
) -> None:
    event_rows = conn.execute(
        """
        SELECT event_type, entity_id, payload_json
        FROM events
        WHERE event_type IN (
          'workflow_proposed',
          'workflow_proposal_approved',
          'workflow_proposal_cancelled'
        )
          AND entity_type = 'workflow_proposal'
        ORDER BY rowid
        """
    ).fetchall()
    events_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in event_rows:
        proposal_id = str(row["entity_id"] or "")
        if not PROPOSAL_ID_RE.match(proposal_id):
            result.add_error(f"Workflow proposal event has invalid id: {proposal_id}.")
            continue
        event_type = str(row["event_type"] or "")
        events_by_id.setdefault(proposal_id, []).append(
            {"event_type": event_type, "payload": _json_object(row["payload_json"])}
        )

    proposal_files = (
        sorted(paths.workflow_proposals_dir.glob("*.yaml"), key=lambda path: path.name)
        if paths.workflow_proposals_dir.exists()
        else []
    )
    file_ids: set[str] = set()
    for path in proposal_files:
        proposal_id = path.stem
        relative_path = str(path.relative_to(paths.root))
        if not PROPOSAL_ID_RE.match(proposal_id):
            result.add_error(f"Workflow proposal file has invalid name: {relative_path}.")
            continue
        file_ids.add(proposal_id)
        try:
            data = validate_workflow_proposal_text(
                path.read_text(encoding="utf-8"),
                source_label=relative_path,
            )
        except (InvalidInputError, OSError) as exc:
            result.add_error(f"Workflow proposal {proposal_id} is invalid: {exc}.")
            continue
        events = events_by_id.get(proposal_id, [])
        proposed_events = _workflow_proposal_events_of_type(events, "workflow_proposed")
        if not proposed_events:
            result.add_error(f"Workflow proposal {proposal_id} has no workflow_proposed event.")
            continue
        if len(proposed_events) > 1:
            result.add_error(f"Workflow proposal {proposal_id} has multiple workflow_proposed events.")
        event = proposed_events[-1]["payload"]
        if event.get("path") != relative_path:
            result.add_error(
                f"Workflow proposal {proposal_id} event path differs: "
                f"event={event.get('path')!r}, file={relative_path!r}."
            )
        if event.get("workflow_id") != data.get("id"):
            result.add_error(
                f"Workflow proposal {proposal_id} event workflow_id differs: "
                f"event={event.get('workflow_id')!r}, file={data.get('id')!r}."
            )
        terminal_events = [
            event for event in events if event["event_type"] in TERMINAL_WORKFLOW_PROPOSAL_EVENT_TYPES
        ]
        if len(terminal_events) > 1:
            result.add_error(f"Workflow proposal {proposal_id} has multiple terminal review events.")
        if terminal_events and terminal_events[-1]["event_type"] == "workflow_proposal_approved":
            _validate_approved_workflow_proposal(paths, proposal_id, data, terminal_events[-1], result)

    for proposal_id in sorted(events_by_id):
        events = events_by_id[proposal_id]
        if not _workflow_proposal_events_of_type(events, "workflow_proposed"):
            result.add_error(f"Workflow proposal {proposal_id} has review event without workflow_proposed event.")

    for proposal_id in sorted(set(events_by_id) - file_ids):
        result.add_error(f"Workflow proposal event {proposal_id} references a missing proposal file.")


def _workflow_proposal_events_of_type(events: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event_type") == event_type]


def _validate_approved_workflow_proposal(
    paths: ProjectPaths,
    proposal_id: str,
    proposal_data: dict[str, Any],
    approved_event: dict[str, Any],
    result: ValidationResult,
) -> None:
    payload = approved_event.get("payload") if isinstance(approved_event.get("payload"), dict) else {}
    workflow_id = str(proposal_data.get("id") or "")
    expected_workflow_path = f".project-loop/workflows/{workflow_id}.yaml"
    if payload.get("workflow_id") != workflow_id:
        result.add_error(
            f"Workflow proposal {proposal_id} approved event workflow_id differs: "
            f"event={payload.get('workflow_id')!r}, file={workflow_id!r}."
        )
    if payload.get("workflow_path") != expected_workflow_path:
        result.add_error(
            f"Workflow proposal {proposal_id} approved event workflow_path differs: "
            f"event={payload.get('workflow_path')!r}, expected={expected_workflow_path!r}."
        )
        return
    workflow_path = paths.root / expected_workflow_path
    if not workflow_path.exists():
        result.add_error(f"Workflow proposal {proposal_id} approved workflow template is missing: {expected_workflow_path}.")
        return
    try:
        workflow_text = workflow_path.read_text(encoding="utf-8")
        workflow_data = validate_workflow_proposal_text(workflow_text, source_label=expected_workflow_path)
    except (InvalidInputError, OSError) as exc:
        result.add_error(f"Workflow proposal {proposal_id} approved workflow template is invalid: {exc}.")
        return
    if workflow_data.get("id") != workflow_id:
        result.add_error(
            f"Workflow proposal {proposal_id} approved workflow template id differs: "
            f"expected={workflow_id!r}, file={workflow_data.get('id')!r}."
        )
    content_sha256 = str(payload.get("content_sha256") or "")
    if not content_sha256:
        result.add_error(f"Workflow proposal {proposal_id} approved event has no content_sha256.")
        return
    actual_sha256 = hashlib.sha256((workflow_text.strip() + "\n").encode("utf-8")).hexdigest()
    if content_sha256 != actual_sha256:
        result.add_error(
            f"Workflow proposal {proposal_id} approved workflow content hash differs: "
            f"event={content_sha256}, file={actual_sha256}."
        )
    verification = verify_workflow_text(
        workflow_text,
        source_label=expected_workflow_path,
        path=expected_workflow_path,
        target_type="workflow_template",
        target_id=workflow_id,
        expected_workflow_id=workflow_id,
    )
    for error in verification["errors"]:
        result.add_error(f"Workflow proposal {proposal_id} approved workflow verifier failed: {error}")


def _validate_audit_log_integrity(paths: ProjectPaths, conn: sqlite3.Connection, result: ValidationResult) -> None:
    if not paths.events_path.exists():
        return
    jsonl_events = _read_jsonl_events(paths, result)
    db_events = _db_events(conn, result)
    jsonl_by_id: dict[str, dict[str, Any]] = {}
    first_lines: dict[str, int] = {}
    for event in jsonl_events:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        line = int(event["_line"])
        if event_id in jsonl_by_id:
            result.add_error(
                f"Duplicate events.jsonl event id {event_id} at lines {first_lines[event_id]} and {line}."
            )
            continue
        jsonl_by_id[event_id] = event
        first_lines[event_id] = line

    db_by_id = {str(event["id"]): event for event in db_events}
    db_ids = set(db_by_id)
    jsonl_ids = set(jsonl_by_id)
    for event_id in sorted(db_ids - jsonl_ids):
        result.add_error(f"DB event {event_id} is missing from events.jsonl.")
    for event_id in sorted(jsonl_ids - db_ids):
        result.add_error(f"events.jsonl event {event_id} is missing from DB events table.")

    if db_ids == jsonl_ids:
        db_order = [str(event["id"]) for event in db_events]
        jsonl_order = [str(event["id"]) for event in jsonl_events if event.get("id") in jsonl_by_id]
        if db_order != jsonl_order:
            for index, (db_id, jsonl_id) in enumerate(zip(db_order, jsonl_order), start=1):
                if db_id != jsonl_id:
                    result.add_error(
                        f"Event order mismatch at position {index}: DB has {db_id}, events.jsonl has {jsonl_id}."
                    )
                    break

    for event_id in sorted(db_ids & jsonl_ids):
        _compare_event_record(event_id, db_by_id[event_id], jsonl_by_id[event_id], result)


def _read_jsonl_events(paths: ProjectPaths, result: ValidationResult) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = paths.events_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        result.add_error(f"Cannot read events.jsonl at {paths.events_path}: {exc}")
        return events
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            result.add_error(f"Invalid events.jsonl line {line_number}: blank lines are not valid events.")
            continue
        try:
            value = json.loads(line)
        except JSONDecodeError as exc:
            result.add_error(f"Invalid events.jsonl line {line_number}: {exc.msg}.")
            continue
        if not isinstance(value, dict):
            result.add_error(f"Invalid events.jsonl line {line_number}: event must be an object.")
            continue
        event = dict(value)
        event["_line"] = line_number
        for field_name in ["id", "event_type", "entity_type", "entity_id", "payload", "created_at"]:
            if field_name not in event:
                result.add_error(f"Invalid events.jsonl line {line_number}: missing field {field_name}.")
        if "payload" in event and not isinstance(event["payload"], dict):
            result.add_error(f"Invalid events.jsonl line {line_number}: payload must be an object.")
        events.append(event)
    return events


def _db_events(conn: sqlite3.Connection, result: ValidationResult) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, event_type, entity_type, entity_id, payload_json, created_at
        FROM events
        ORDER BY rowid
        """
    ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        event = dict(row)
        try:
            payload = json.loads(str(event["payload_json"]))
        except JSONDecodeError as exc:
            result.add_error(f"DB event {event['id']} has invalid payload_json: {exc.msg}.")
            payload = {}
        if not isinstance(payload, dict):
            result.add_error(f"DB event {event['id']} payload_json must be an object.")
            payload = {}
        event["payload"] = payload
        events.append(event)
    return events


def _compare_event_record(
    event_id: str,
    db_event: dict[str, Any],
    jsonl_event: dict[str, Any],
    result: ValidationResult,
) -> None:
    for field_name in ["id", "event_type", "entity_type", "entity_id", "created_at"]:
        if db_event.get(field_name) != jsonl_event.get(field_name):
            result.add_error(
                f"Event {event_id} field {field_name} differs: DB={db_event.get(field_name)!r}, "
                f"events.jsonl={jsonl_event.get(field_name)!r}."
            )
    if db_event.get("payload") != jsonl_event.get("payload"):
        result.add_error(f"Event {event_id} payload differs between DB and events.jsonl.")


def _validate_foreign_keys(conn: sqlite3.Connection, result: ValidationResult) -> None:
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    for row in rows:
        data = dict(row)
        result.add_error(
            "Foreign key violation: "
            f"{data.get('table')} rowid {data.get('rowid')} references {data.get('parent')}."
        )


def _validate_closed_goals(conn: sqlite3.Connection, result: ValidationResult) -> None:
    rows = conn.execute(
        "SELECT id, completion_json FROM goals WHERE status = 'closed' ORDER BY id"
    ).fetchall()
    for row in rows:
        goal_id = str(row["id"])
        completion = _json_object(row["completion_json"])
        closure = completion.get("closure") if isinstance(completion.get("closure"), dict) else {}
        evidence = str(closure.get("evidence") or "").strip()
        verification_id = closure.get("verification_id")
        verification_id = str(verification_id).strip() if verification_id else ""
        if not evidence and not verification_id:
            result.add_error(f"Closed goal {goal_id} has no closure evidence or verification.")
        if verification_id:
            verification = conn.execute(
                """
                SELECT verifications.id, verifications.result, workflow_runs.goal_id
                FROM verifications
                JOIN workflow_runs ON workflow_runs.id = verifications.workflow_run_id
                WHERE verifications.id = ?
                """,
                (verification_id,),
            ).fetchone()
            if verification is None:
                result.add_error(f"Closed goal {goal_id} references missing verification {verification_id}.")
            elif verification["result"] != "approved":
                result.add_error(
                    f"Closed goal {goal_id} references non-approved verification {verification_id}."
                )
            elif verification["goal_id"] != goal_id:
                result.add_error(f"Closed goal {goal_id} references verification {verification_id} from another goal.")


def _validate_passed_workflow_runs(conn: sqlite3.Connection, result: ValidationResult) -> None:
    rows = conn.execute("SELECT id FROM workflow_runs WHERE status = 'passed' ORDER BY id").fetchall()
    for row in rows:
        run_id = str(row["id"])
        bad_jobs = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM agent_jobs
            WHERE workflow_run_id = ? AND status != 'passed'
            GROUP BY status
            ORDER BY status
            """,
            (run_id,),
        ).fetchall()
        if bad_jobs:
            counts = ", ".join(f"{job['status']}={job['count']}" for job in bad_jobs)
            result.add_error(f"Passed workflow run {run_id} has non-passed jobs: {counts}.")
        approved = conn.execute(
            """
            SELECT id FROM verifications
            WHERE workflow_run_id = ? AND result = 'approved'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        if approved is None:
            result.add_error(f"Passed workflow run {run_id} has no approved verification.")


def _validate_verified_or_closed_defects(conn: sqlite3.Connection, result: ValidationResult) -> None:
    rows = conn.execute(
        """
        SELECT id, status, evidence_id
        FROM defects
        WHERE status IN ('verified', 'closed')
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        defect_id = str(row["id"])
        status = str(row["status"])
        evidence_id = str(row["evidence_id"] or "")
        expected_current_type = "defect_close" if status == "closed" else "defect_fix"
        if not evidence_id:
            result.add_error(f"Defect {defect_id} is {status} but has no evidence_id.")
        else:
            evidence_type = _evidence_type(conn, evidence_id)
            if evidence_type is None:
                result.add_error(f"Defect {defect_id} references missing evidence {evidence_id}.")
            elif evidence_type != expected_current_type:
                result.add_error(
                    f"Defect {defect_id} has current evidence {evidence_id} with type "
                    f"{evidence_type}, expected {expected_current_type}."
                )
        _validate_defect_transition_evidence(
            conn,
            result,
            defect_id=defect_id,
            status=status,
            event_type="defect_fixed",
            evidence_type="defect_fix",
        )
        if status == "closed":
            _validate_defect_transition_evidence(
                conn,
                result,
                defect_id=defect_id,
                status=status,
                event_type="defect_closed",
                evidence_type="defect_close",
            )
        if not _has_approved_defect_verification(conn, defect_id):
            result.add_error(f"Defect {defect_id} is {status} but has no approved verification tied to the defect.")


def _validate_terminal_test_cases(conn: sqlite3.Connection, result: ValidationResult) -> None:
    expected_by_status = {
        "passing": ("test_case_pass", "test_case_passed"),
        "failing": ("test_case_fail", "test_case_failed"),
        "waived": ("test_case_waiver", "test_case_waived"),
    }
    rows = conn.execute(
        """
        SELECT id, status, evidence_id
        FROM test_cases
        WHERE status IN ('passing', 'failing', 'waived')
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        test_case_id = str(row["id"])
        status = str(row["status"])
        evidence_id = str(row["evidence_id"] or "")
        expected_evidence_type, event_type = expected_by_status[status]
        if not evidence_id:
            result.add_error(f"Test case {test_case_id} is {status} but has no evidence_id.")
        else:
            evidence_type = _evidence_type(conn, evidence_id)
            if evidence_type is None:
                result.add_error(f"Test case {test_case_id} references missing evidence {evidence_id}.")
            elif evidence_type != expected_evidence_type:
                result.add_error(
                    f"Test case {test_case_id} has current evidence {evidence_id} with type "
                    f"{evidence_type}, expected {expected_evidence_type}."
                )
        _validate_test_case_transition_evidence(
            conn,
            result,
            test_case_id=test_case_id,
            status=status,
            event_type=event_type,
            evidence_type=expected_evidence_type,
        )


def _validate_duplicate_active_runs(conn: sqlite3.Connection, result: ValidationResult) -> None:
    placeholders = ", ".join("?" for _ in ACTIVE_RUN_STATUSES)
    runs = conn.execute(
        f"""
        SELECT id, goal_id, summary
        FROM workflow_runs
        WHERE status IN ({placeholders})
        ORDER BY id
        """,
        ACTIVE_RUN_STATUSES,
    ).fetchall()
    defect_targets = _defect_targets_for_runs(conn, [str(run["id"]) for run in runs])
    grouped: dict[tuple[str, str], list[str]] = {}
    for run in runs:
        run_id = str(run["id"])
        if run["goal_id"]:
            grouped.setdefault(("goal", str(run["goal_id"])), []).append(run_id)
        defect_id = defect_targets.get(run_id) or _defect_target_from_summary(run["summary"])
        if defect_id:
            grouped.setdefault(("defect", defect_id), []).append(run_id)
    for (target_type, target_id), run_ids in sorted(grouped.items()):
        if len(run_ids) > 1:
            result.add_error(
                f"Duplicate active workflow runs for {target_type} {target_id}: {', '.join(run_ids)}."
            )


def _validate_task_invariants(conn: sqlite3.Connection, result: ValidationResult) -> None:
    _validate_task_references(conn, result)
    _validate_task_dependency_cycles(conn, result)
    _validate_done_task_dependencies(conn, result)


def _agent_jobs_has_lease_columns(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA table_info(agent_jobs)").fetchall()
    columns = {str(row["name"]) for row in rows}
    return {
        "assigned_agent_id",
        "lease_expires_at",
        "last_heartbeat_at",
        "attempts",
    } <= columns


def _validate_agent_registry_invariants(conn: sqlite3.Connection, result: ValidationResult) -> None:
    _validate_job_agent_references(conn, result)
    _validate_expired_running_leases(conn, result)
    _validate_retired_agent_active_leases(conn, result)
    _validate_agent_concurrency(conn, result)


def _validate_job_agent_references(conn: sqlite3.Connection, result: ValidationResult) -> None:
    rows = conn.execute(
        """
        SELECT agent_jobs.id, agent_jobs.assigned_agent_id
        FROM agent_jobs
        LEFT JOIN agents ON agents.id = agent_jobs.assigned_agent_id
        WHERE agent_jobs.assigned_agent_id IS NOT NULL
          AND agents.id IS NULL
        ORDER BY agent_jobs.id
        """
    ).fetchall()
    for row in rows:
        result.add_error(
            f"Agent job {row['id']} references missing agent {row['assigned_agent_id']}."
        )


def _validate_expired_running_leases(conn: sqlite3.Connection, result: ValidationResult) -> None:
    now = utc_now_iso()
    rows = conn.execute(
        """
        SELECT id, assigned_agent_id, lease_expires_at
        FROM agent_jobs
        WHERE status = 'running'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at <= ?
        ORDER BY id
        """,
        (now,),
    ).fetchall()
    for row in rows:
        result.add_warning(
            f"Agent job {row['id']} has an expired lease for agent {row['assigned_agent_id']}; "
            "run `pcl jobs reap`."
        )


def _validate_retired_agent_active_leases(conn: sqlite3.Connection, result: ValidationResult) -> None:
    now = utc_now_iso()
    rows = conn.execute(
        """
        SELECT agent_jobs.id AS job_id, agents.id AS agent_id
        FROM agent_jobs
        JOIN agents ON agents.id = agent_jobs.assigned_agent_id
        WHERE agent_jobs.status = 'running'
          AND agent_jobs.lease_expires_at IS NOT NULL
          AND agent_jobs.lease_expires_at > ?
          AND agents.status = 'retired'
        ORDER BY agent_jobs.id
        """,
        (now,),
    ).fetchall()
    for row in rows:
        result.add_error(
            f"Retired agent {row['agent_id']} holds active lease for job {row['job_id']}."
        )


def _validate_agent_concurrency(conn: sqlite3.Connection, result: ValidationResult) -> None:
    now = utc_now_iso()
    rows = conn.execute(
        """
        SELECT
          agents.id,
          agents.max_concurrency,
          COUNT(agent_jobs.id) AS active_lease_count
        FROM agents
        JOIN agent_jobs
          ON agent_jobs.assigned_agent_id = agents.id
         AND agent_jobs.status = 'running'
         AND agent_jobs.lease_expires_at IS NOT NULL
         AND agent_jobs.lease_expires_at > ?
        WHERE agents.status = 'active'
        GROUP BY agents.id, agents.max_concurrency
        HAVING COUNT(agent_jobs.id) > agents.max_concurrency
        ORDER BY agents.id
        """,
        (now,),
    ).fetchall()
    for row in rows:
        result.add_warning(
            f"Active agent {row['id']} has {row['active_lease_count']} active leases, "
            f"exceeding max_concurrency {row['max_concurrency']}."
        )


def _validate_task_references(conn: sqlite3.Connection, result: ValidationResult) -> None:
    reference_checks = [
        ("related_goal_id", "goals", "goal"),
        ("related_feature_id", "features", "feature"),
        ("related_defect_id", "defects", "defect"),
    ]
    for column, table, label in reference_checks:
        rows = conn.execute(
            f"""
            SELECT tasks.id, tasks.{column}
            FROM tasks
            LEFT JOIN {table} ON {table}.id = tasks.{column}
            WHERE tasks.{column} IS NOT NULL
              AND {table}.id IS NULL
            ORDER BY tasks.id
            """
        ).fetchall()
        for row in rows:
            result.add_error(
                f"Task {row['id']} references missing {label} {row[column]} via {column}."
            )

    dependency_checks = [
        ("task_id", "task"),
        ("depends_on_task_id", "dependency task"),
    ]
    for column, label in dependency_checks:
        rows = conn.execute(
            f"""
            SELECT task_dependencies.{column}
            FROM task_dependencies
            LEFT JOIN tasks ON tasks.id = task_dependencies.{column}
            WHERE tasks.id IS NULL
            ORDER BY task_dependencies.{column}
            """
        ).fetchall()
        for row in rows:
            result.add_error(f"Task dependency references missing {label} {row[column]}.")


def _validate_task_dependency_cycles(conn: sqlite3.Connection, result: ValidationResult) -> None:
    graph = _task_dependency_graph(conn)
    reported: set[tuple[str, ...]] = set()
    for task_id in sorted(graph):
        cycle = _find_task_dependency_cycle(graph, task_id, [], set())
        if cycle is None:
            continue
        canonical = tuple(sorted(set(cycle)))
        if canonical in reported:
            continue
        reported.add(canonical)
        result.add_error(f"Task dependency cycle detected: {' -> '.join(cycle)}.")


def _task_dependency_graph(conn: sqlite3.Connection) -> dict[str, list[str]]:
    rows = conn.execute(
        """
        SELECT task_id, depends_on_task_id
        FROM task_dependencies
        ORDER BY task_id, depends_on_task_id
        """
    ).fetchall()
    graph: dict[str, list[str]] = {}
    task_rows = conn.execute("SELECT id FROM tasks ORDER BY id").fetchall()
    for row in task_rows:
        graph[str(row["id"])] = []
    for row in rows:
        graph.setdefault(str(row["task_id"]), []).append(str(row["depends_on_task_id"]))
        graph.setdefault(str(row["depends_on_task_id"]), [])
    return graph


def _find_task_dependency_cycle(
    graph: dict[str, list[str]],
    current_id: str,
    path: list[str],
    visited: set[str],
) -> list[str] | None:
    if current_id in path:
        start = path.index(current_id)
        return path[start:] + [current_id]
    if current_id in visited:
        return None
    visited.add(current_id)
    for dependency_id in graph.get(current_id, []):
        cycle = _find_task_dependency_cycle(graph, dependency_id, path + [current_id], visited)
        if cycle is not None:
            return cycle
    return None


def _validate_done_task_dependencies(conn: sqlite3.Connection, result: ValidationResult) -> None:
    rows = conn.execute(
        """
        SELECT tasks.id AS task_id, dependency.id AS dependency_id, dependency.status AS dependency_status
        FROM tasks
        JOIN task_dependencies ON task_dependencies.task_id = tasks.id
        JOIN tasks AS dependency ON dependency.id = task_dependencies.depends_on_task_id
        WHERE tasks.status = 'done'
          AND dependency.status NOT IN ('done', 'cancelled', 'waived')
        ORDER BY tasks.id, dependency.id
        """
    ).fetchall()
    for row in rows:
        result.add_warning(
            f"Task {row['task_id']} is done but depends on incomplete task "
            f"{row['dependency_id']} ({row['dependency_status']})."
        )


def _validate_defect_transition_evidence(
    conn: sqlite3.Connection,
    result: ValidationResult,
    *,
    defect_id: str,
    status: str,
    event_type: str,
    evidence_type: str,
) -> None:
    rows = conn.execute(
        """
        SELECT payload_json
        FROM events
        WHERE entity_type = 'defect'
          AND entity_id = ?
          AND event_type = ?
        ORDER BY rowid
        """,
        (defect_id, event_type),
    ).fetchall()
    if not rows:
        result.add_error(f"Defect {defect_id} is {status} but has no {event_type} event.")
        return

    evidence_ids: list[str] = []
    for row in rows:
        payload = _json_object(row["payload_json"])
        evidence_id = payload.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id:
            evidence_ids.append(evidence_id)
    if not evidence_ids:
        result.add_error(f"Defect {defect_id} {event_type} event has no evidence_id.")
        return

    mismatches: list[str] = []
    for evidence_id in sorted(set(evidence_ids)):
        actual_type = _evidence_type(conn, evidence_id)
        if actual_type == evidence_type:
            return
        if actual_type is None:
            mismatches.append(f"{evidence_id}=missing")
        else:
            mismatches.append(f"{evidence_id}={actual_type}")
    result.add_error(
        f"Defect {defect_id} is {status} but no {evidence_type} evidence is linked from "
        f"{event_type} event ({', '.join(mismatches)})."
    )


def _validate_test_case_transition_evidence(
    conn: sqlite3.Connection,
    result: ValidationResult,
    *,
    test_case_id: str,
    status: str,
    event_type: str,
    evidence_type: str,
) -> None:
    rows = conn.execute(
        """
        SELECT payload_json
        FROM events
        WHERE entity_type = 'test_case'
          AND entity_id = ?
          AND event_type = ?
        ORDER BY rowid
        """,
        (test_case_id, event_type),
    ).fetchall()
    if not rows:
        result.add_error(f"Test case {test_case_id} is {status} but has no {event_type} event.")
        return

    evidence_ids: list[str] = []
    for row in rows:
        payload = _json_object(row["payload_json"])
        evidence_id = payload.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id:
            evidence_ids.append(evidence_id)
    if not evidence_ids:
        result.add_error(f"Test case {test_case_id} {event_type} event has no evidence_id.")
        return

    mismatches: list[str] = []
    for evidence_id in sorted(set(evidence_ids)):
        actual_type = _evidence_type(conn, evidence_id)
        if actual_type == evidence_type:
            return
        if actual_type is None:
            mismatches.append(f"{evidence_id}=missing")
        else:
            mismatches.append(f"{evidence_id}={actual_type}")
    result.add_error(
        f"Test case {test_case_id} is {status} but no {evidence_type} evidence is linked from "
        f"{event_type} event ({', '.join(mismatches)})."
    )


def _evidence_type(conn: sqlite3.Connection, evidence_id: str) -> str | None:
    row = conn.execute("SELECT type FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
    return None if row is None else str(row["type"])


def _missing_evidence_ids(conn: sqlite3.Connection, evidence_ids: list[str]) -> list[str]:
    if not evidence_ids:
        return []
    placeholders = ", ".join("?" for _ in evidence_ids)
    rows = conn.execute(
        f"SELECT id FROM evidence WHERE id IN ({placeholders})",
        tuple(evidence_ids),
    ).fetchall()
    found = {str(row["id"]) for row in rows}
    return sorted(evidence_id for evidence_id in evidence_ids if evidence_id not in found)


def _has_approved_defect_verification(conn: sqlite3.Connection, defect_id: str) -> bool:
    rows = conn.execute(
        """
        SELECT payload_json
        FROM events
        WHERE entity_type = 'defect'
          AND entity_id = ?
          AND event_type = 'defect_verified'
        ORDER BY rowid
        """,
        (defect_id,),
    ).fetchall()
    verification_ids: list[str] = []
    for row in rows:
        payload = _json_object(row["payload_json"])
        verification_id = payload.get("verification_id")
        if isinstance(verification_id, str) and verification_id:
            verification_ids.append(verification_id)
    for verification_id in sorted(set(verification_ids)):
        verification = conn.execute(
            """
            SELECT verifications.id, verifications.result, workflow_runs.id AS workflow_run_id, workflow_runs.summary
            FROM verifications
            JOIN workflow_runs ON workflow_runs.id = verifications.workflow_run_id
            WHERE verifications.id = ?
            """,
            (verification_id,),
        ).fetchone()
        if verification is None or verification["result"] != "approved":
            continue
        if _workflow_run_created_for_defect(conn, str(verification["workflow_run_id"]), defect_id):
            return True
        if _defect_target_from_summary(verification["summary"]) == defect_id:
            return True
    return False


def _workflow_run_created_for_defect(conn: sqlite3.Connection, workflow_run_id: str, defect_id: str) -> bool:
    rows = conn.execute(
        """
        SELECT payload_json
        FROM events
        WHERE entity_type = 'workflow_run'
          AND entity_id = ?
          AND event_type = 'workflow_run_created'
        ORDER BY rowid
        """,
        (workflow_run_id,),
    ).fetchall()
    for row in rows:
        payload = _json_object(row["payload_json"])
        if payload.get("defect_id") == defect_id:
            return True
    return False


def _defect_targets_for_runs(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, str]:
    if not run_ids:
        return {}
    placeholders = ", ".join("?" for _ in run_ids)
    rows = conn.execute(
        f"""
        SELECT entity_id, payload_json
        FROM events
        WHERE entity_type = 'workflow_run'
          AND event_type = 'workflow_run_created'
          AND entity_id IN ({placeholders})
        ORDER BY rowid
        """,
        tuple(run_ids),
    ).fetchall()
    targets: dict[str, str] = {}
    for row in rows:
        payload = _json_object(row["payload_json"])
        defect_id = payload.get("defect_id")
        if isinstance(defect_id, str) and defect_id:
            targets[str(row["entity_id"])] = defect_id
    return targets


def _defect_target_from_summary(value: Any) -> str | None:
    for token in str(value or "").split():
        if token.startswith("defect=") and len(token) > len("defect="):
            return token.removeprefix("defect=")
    return None


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
