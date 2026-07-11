from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from json import JSONDecodeError
from pathlib import Path
import shlex
import sqlite3
from typing import Any

from .context_binding import _receipt_target_binding_agrees
from .contracts.completion_packet import load_completion_packet, validate_completion_packet
from .contracts.evidence_set import load_evidence_set, validate_evidence_set
from .db import connect, table_exists
from .evidence import ADHOC_EVIDENCE_TYPES, assess_adhoc_evidence
from .errors import DataStoreError, InvalidInputError
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
    4: [
        "code_index_runs",
        "code_index_files",
    ],
    5: [
        "verification_feedback",
    ],
    7: [
        "evidence_links",
    ],
}

ACTIVE_RUN_STATUSES = ("blocked", "queued", "running")
TERMINAL_GOAL_STATUSES = ("cancelled", "closed")
TERMINAL_RUN_STATUSES = ("cancelled", "failed", "passed")
ACTIVE_JOB_STATUSES = ("blocked", "queued", "running")
TERMINAL_TASK_STATUSES = ("cancelled", "done", "waived")
TERMINAL_WORKFLOW_PROPOSAL_EVENT_TYPES = {
    "workflow_proposal_approved",
    "workflow_proposal_cancelled",
}
DECISION_BLOCK_TARGET_TABLES = {
    "agent_job": "agent_jobs",
    "defect": "defects",
    "escalation": "escalations",
    "evidence": "evidence",
    "feature": "features",
    "goal": "goals",
    "task": "tasks",
    "test_case": "test_cases",
    "user_story": "user_stories",
    "verification": "verifications",
    "workflow_run": "workflow_runs",
}
ADHOC_DRIFT_WARNING_PREFIX = "Adhoc evidence "
LIFECYCLE_ADVISORY_PREFIX = "Lifecycle integrity advisory: "


def _pcl_json_command(*args: str, root: str | None = None) -> str:
    argv = ["pcl"]
    if root is not None:
        argv.extend(["--root", root])
    argv.append("--json")
    argv.extend(args)
    return shlex.join(argv)


def _pcl_root_command(root: str, *args: str) -> str:
    return shlex.join(["pcl", "--root", root, *args])


@dataclass
class ValidationFinding:
    code: str
    severity: str
    message: str
    entity: dict[str, str] | None = None
    related: list[dict[str, str]] = field(default_factory=list)
    repair_class: str = "unsupported"
    requires_human: bool = False
    suggested_commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "entity": self.entity,
            "related": self.related,
            "repair_class": self.repair_class,
            "requires_human": self.requires_human,
            "suggested_commands": self.suggested_commands,
        }


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    findings: list[ValidationFinding] = field(default_factory=list)

    def add_error(
        self,
        message: str,
        *,
        code: str,
        entity: dict[str, str] | None = None,
        related: list[dict[str, str]] | None = None,
        repair_class: str = "unsupported",
        requires_human: bool = False,
        suggested_commands: list[str] | None = None,
    ) -> None:
        self.ok = False
        self.errors.append(message)
        self.findings.append(
            ValidationFinding(
                code=code,
                severity="error",
                message=message,
                entity=entity,
                related=list(related or []),
                repair_class=repair_class,
                requires_human=requires_human,
                suggested_commands=list(suggested_commands or []),
            )
        )

    def add_warning(
        self,
        message: str,
        *,
        code: str,
        entity: dict[str, str] | None = None,
        related: list[dict[str, str]] | None = None,
        repair_class: str = "unsupported",
        requires_human: bool = False,
        suggested_commands: list[str] | None = None,
    ) -> None:
        self.warnings.append(message)
        self.findings.append(
            ValidationFinding(
                code=code,
                severity="warning",
                message=message,
                entity=entity,
                related=list(related or []),
                repair_class=repair_class,
                requires_human=requires_human,
                suggested_commands=list(suggested_commands or []),
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class LifecycleFinding:
    code: str
    message: str
    entity_type: str
    entity_id: str
    details: dict[str, Any] = field(default_factory=dict)


def _strict_warning_remains_warning(warning: str) -> bool:
    if warning.startswith(LIFECYCLE_ADVISORY_PREFIX):
        return True
    return warning.startswith(ADHOC_DRIFT_WARNING_PREFIX) and (
        " drifted: " in warning or warning.endswith(" is outside the project root.")
    )


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
            f"Run `pcl init --target {paths.root}`.",
            code="installation_directory_missing",
            entity={"type": "project", "id": str(paths.root)},
            repair_class="structural",
            suggested_commands=[shlex.join(["pcl", "init", "--target", str(paths.root)])],
        )
        return result
    if not paths.db_path.exists():
        result.add_error(
            f"Missing .project-loop/project.db at {paths.db_path}. "
            f"Run `pcl init --target {paths.root}`.",
            code="installation_database_missing",
            entity={"type": "project", "id": str(paths.root)},
            repair_class="structural",
            suggested_commands=[shlex.join(["pcl", "init", "--target", str(paths.root)])],
        )
        return result
    if not paths.events_path.exists():
        if strict:
            result.add_error(
                f"Missing events.jsonl at {paths.events_path}.",
                code="installation_events_missing",
                entity={"type": "project", "id": str(paths.root)},
                repair_class="inspect",
                suggested_commands=[_pcl_json_command("audit", "check")],
            )
        else:
            result.add_warning(
                f"Missing events.jsonl at {paths.events_path}.",
                code="installation_events_missing",
                entity={"type": "project", "id": str(paths.root)},
                repair_class="inspect",
                suggested_commands=[_pcl_json_command("audit", "check")],
            )

    try:
        conn = connect(paths.db_path)
    except sqlite3.Error as exc:
        result.add_error(
            f"Cannot open SQLite database at {paths.db_path}: {exc}",
            code="installation_database_unreadable",
            entity={"type": "project", "id": str(paths.root)},
            repair_class="unsupported",
            requires_human=True,
        )
        return result

    try:
        missing_tables: list[str] = []
        for table in REQUIRED_TABLES:
            if not table_exists(conn, table):
                missing_tables.append(table)
                result.add_error(
                    f"Missing table: {table}",
                    code="schema_required_table_missing",
                    entity={"type": "schema_table", "id": table},
                    repair_class="unsupported",
                    requires_human=True,
                )
        try:
            status = migration_status(paths)
        except DataStoreError as exc:
            result.add_error(
                str(exc),
                code="schema_migration_status_unavailable",
                entity={"type": "project", "id": str(paths.root)},
                repair_class="unsupported",
                requires_human=True,
            )
            status = None
        status_available = status is not None
        schema_version = None if status is None else status.metadata_schema_version
        current_version: int | None = None
        if status_available and schema_version is None:
            result.add_error(
                "Missing metadata.schema_version",
                code="schema_metadata_version_missing",
                entity={"type": "schema_metadata", "id": "schema_version"},
                repair_class="structural",
                suggested_commands=[_pcl_root_command(str(paths.root), "migrate")],
            )
        if status is not None:
            for warning in status.warnings:
                if warning == "Missing metadata.schema_version.":
                    continue
                if status.is_ahead_of_binary:
                    result.add_error(
                        warning,
                        code="schema_ahead_of_binary",
                        entity={"type": "project", "id": str(paths.root)},
                        repair_class="unsupported",
                        requires_human=True,
                    )
                else:
                    result.add_warning(
                        warning,
                        code="schema_migration_metadata_inconsistent",
                        entity={"type": "project", "id": str(paths.root)},
                        repair_class="inspect",
                        suggested_commands=[_pcl_json_command("migrate", "status")],
                    )
        if schema_version is not None:
            current_version = schema_version
            if status is not None and not status.is_ahead_of_binary:
                for version, tables in sorted(VERSIONED_REQUIRED_TABLES.items()):
                    if current_version >= version:
                        for table in tables:
                            if not table_exists(conn, table):
                                missing_tables.append(table)
                                result.add_error(
                                    f"Missing table: {table}",
                                    code="schema_versioned_table_missing",
                                    entity={"type": "schema_table", "id": table},
                                    repair_class="unsupported",
                                    requires_human=True,
                                )
        if status is not None and status.pending:
            pending = ", ".join(migration.id for migration in status.pending)
            result.add_warning(
                f"Pending migrations: {pending}. Run `pcl migrate --root {paths.root}`.",
                code="schema_migrations_pending",
                entity={"type": "project", "id": str(paths.root)},
                related=[{"type": "migration", "id": migration.id} for migration in status.pending],
                repair_class="structural",
                suggested_commands=[_pcl_root_command(str(paths.root), "migrate")],
            )
        if not paths.root.joinpath("pcl.yaml").exists():
            result.add_warning(
                f"Missing pcl.yaml at {paths.root / 'pcl.yaml'}.",
                code="installation_config_missing",
                entity={"type": "project", "id": str(paths.root)},
                repair_class="unsupported",
            )
        elif include_config_advice:
            _validate_pcl_yaml_advice(paths, result)
        skill_path = paths.agents_skill_dir.joinpath("SKILL.md")
        if not skill_path.exists():
            result.add_warning(
                f"Missing project-control-loop Skill at {skill_path}.",
                code="installation_skill_missing",
                entity={"type": "project", "id": str(paths.root)},
                repair_class="unsupported",
            )
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
            kept_warnings: list[str] = []
            for warning in result.warnings:
                if _strict_warning_remains_warning(warning):
                    kept_warnings.append(warning)
                else:
                    source = next(
                        finding
                        for finding in result.findings
                        if finding.severity == "warning" and finding.message == warning
                    )
                    result.findings.remove(source)
                    result.add_error(
                        f"Strict mode treats warning as error: {warning}",
                        code=source.code,
                        entity=source.entity,
                        related=source.related,
                        repair_class=source.repair_class,
                        requires_human=source.requires_human,
                        suggested_commands=source.suggested_commands,
                    )
            result.warnings = kept_warnings
    except sqlite3.Error as exc:
        result.add_error(
            f"Cannot validate SQLite database at {paths.db_path}: {exc}",
            code="validation_database_query_failed",
            entity={"type": "project", "id": str(paths.root)},
            repair_class="unsupported",
            requires_human=True,
        )
    finally:
        conn.close()
    return result


def _validate_pcl_yaml_advice(paths: ProjectPaths, result: ValidationResult) -> None:
    config_path = paths.root / "pcl.yaml"
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        result.add_warning(
            f"Could not read pcl.yaml at {config_path}: {exc}.",
            code="config_unreadable",
            entity={"type": "project", "id": str(paths.root)},
            repair_class="unsupported",
        )
        return

    project = _simple_yaml_section(lines, "project")
    project_name = project.get("name", "")
    if project_name == "CHANGE_ME":
        result.add_warning(
            "pcl.yaml project.name is CHANGE_ME; set it to the real project name.",
            code="config_project_name_placeholder",
            entity={"type": "project", "id": str(paths.root)},
            repair_class="human_review",
            requires_human=True,
        )
    elif not project_name:
        result.add_warning(
            "pcl.yaml project.name is empty; set it to the real project name.",
            code="config_project_name_empty",
            entity={"type": "project", "id": str(paths.root)},
            repair_class="human_review",
            requires_human=True,
        )

    commands = _simple_yaml_section(lines, "commands")
    if commands:
        empty_commands = sorted(key for key, value in commands.items() if not value)
        if empty_commands:
            result.add_warning(
                "pcl.yaml commands are empty: "
                f"{', '.join(empty_commands)}. Fill them in or leave intentionally unused commands documented.",
                code="config_commands_empty",
                entity={"type": "project", "id": str(paths.root)},
                related=[{"type": "config_command", "id": key} for key in empty_commands],
                repair_class="human_review",
                requires_human=True,
            )
    else:
        result.add_warning(
            "pcl.yaml has no commands section; configured checks cannot be discovered.",
            code="config_commands_section_missing",
            entity={"type": "project", "id": str(paths.root)},
            repair_class="human_review",
            requires_human=True,
        )


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


def _validate_strict_invariants(
    paths: ProjectPaths, conn: sqlite3.Connection, result: ValidationResult
) -> None:
    _validate_audit_log_integrity(paths, conn, result)
    _validate_workflow_proposals(paths, conn, result)
    _validate_foreign_keys(conn, result)
    _validate_verification_feedback_references(conn, result)
    _validate_evidence_links(paths, conn, result)
    _validate_closed_goals(paths, conn, result)
    _validate_passed_workflow_runs(conn, result)
    _validate_verified_or_closed_defects(conn, result)
    _validate_terminal_test_cases(conn, result)
    _validate_story_test_traceability(paths, conn, result)
    _validate_done_features(paths, conn, result)
    _validate_direct_test_evidence(paths, conn, result)
    _validate_duplicate_active_runs(conn, result)
    _validate_terminal_parent_children(conn, result)
    _validate_decision_block_links(conn, result)
    _validate_evidence_set_artifacts(paths, conn, result)
    _validate_adhoc_evidence_manifests(paths, conn, result)
    _validate_local_artifact_paths(paths, conn, result)


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
                verification_id=verification_id,
            )
        if strict and check_evidence:
            for evidence_id in _missing_evidence_ids(conn, evidence_ids_in_rubric(rubric)):
                result.add_error(
                    f"Verification {verification_id} rubric/v1 references missing evidence {evidence_id}.",
                    code="verification_rubric_evidence_missing",
                    entity={"type": "verification", "id": verification_id},
                    related=[{"type": "evidence", "id": evidence_id}],
                    repair_class="semantic",
                    requires_human=True,
                    suggested_commands=[_pcl_json_command("verification", "read", verification_id)],
                )


def _add_rubric_validation_problem(
    result: ValidationResult,
    *,
    strict: bool,
    message: str,
    verification_id: str,
) -> None:
    kwargs = {
        "code": "verification_rubric_invalid",
        "entity": {"type": "verification", "id": verification_id},
        "repair_class": "semantic",
        "requires_human": True,
        "suggested_commands": [_pcl_json_command("verification", "read", verification_id)],
    }
    if strict:
        result.add_error(message, **kwargs)
    else:
        result.add_warning(message, **kwargs)


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
            result.add_error(
                f"Workflow proposal event has invalid id: {proposal_id}.",
                code="workflow_proposal_event_id_invalid",
                entity={"type": "workflow_proposal", "id": proposal_id},
                repair_class="unsupported",
                requires_human=True,
            )
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
            result.add_error(
                f"Workflow proposal file has invalid name: {relative_path}.",
                code="workflow_proposal_filename_invalid",
                entity={"type": "workflow_proposal_file", "id": relative_path},
                repair_class="unsupported",
                requires_human=True,
            )
            continue
        file_ids.add(proposal_id)
        try:
            data = validate_workflow_proposal_text(
                path.read_text(encoding="utf-8"),
                source_label=relative_path,
            )
        except (InvalidInputError, OSError) as exc:
            result.add_error(
                f"Workflow proposal {proposal_id} is invalid: {exc}.",
                code="workflow_proposal_content_invalid",
                entity={"type": "workflow_proposal", "id": proposal_id},
                repair_class="human_review",
                requires_human=True,
            )
            continue
        events = events_by_id.get(proposal_id, [])
        proposed_events = _workflow_proposal_events_of_type(events, "workflow_proposed")
        if not proposed_events:
            result.add_error(
                f"Workflow proposal {proposal_id} has no workflow_proposed event.",
                code="workflow_proposal_created_event_missing",
                entity={"type": "workflow_proposal", "id": proposal_id},
                repair_class="unsupported",
                requires_human=True,
            )
            continue
        if len(proposed_events) > 1:
            result.add_error(
                f"Workflow proposal {proposal_id} has multiple workflow_proposed events.",
                code="workflow_proposal_created_event_duplicate",
                entity={"type": "workflow_proposal", "id": proposal_id},
                repair_class="unsupported",
                requires_human=True,
            )
        event = proposed_events[-1]["payload"]
        if event.get("path") != relative_path:
            result.add_error(
                f"Workflow proposal {proposal_id} event path differs: "
                f"event={event.get('path')!r}, file={relative_path!r}.",
                code="workflow_proposal_event_path_mismatch",
                entity={"type": "workflow_proposal", "id": proposal_id},
                repair_class="unsupported",
                requires_human=True,
            )
        if event.get("workflow_id") != data.get("id"):
            result.add_error(
                f"Workflow proposal {proposal_id} event workflow_id differs: "
                f"event={event.get('workflow_id')!r}, file={data.get('id')!r}.",
                code="workflow_proposal_event_workflow_id_mismatch",
                entity={"type": "workflow_proposal", "id": proposal_id},
                repair_class="unsupported",
                requires_human=True,
            )
        terminal_events = [
            event
            for event in events
            if event["event_type"] in TERMINAL_WORKFLOW_PROPOSAL_EVENT_TYPES
        ]
        if len(terminal_events) > 1:
            result.add_error(
                f"Workflow proposal {proposal_id} has multiple terminal review events.",
                code="workflow_proposal_terminal_event_duplicate",
                entity={"type": "workflow_proposal", "id": proposal_id},
                repair_class="unsupported",
                requires_human=True,
            )
        if terminal_events and terminal_events[-1]["event_type"] == "workflow_proposal_approved":
            _validate_approved_workflow_proposal(
                paths, proposal_id, data, terminal_events[-1], result
            )

    for proposal_id in sorted(events_by_id):
        events = events_by_id[proposal_id]
        if not _workflow_proposal_events_of_type(events, "workflow_proposed"):
            result.add_error(
                f"Workflow proposal {proposal_id} has review event without workflow_proposed event.",
                code="workflow_proposal_review_without_created_event",
                entity={"type": "workflow_proposal", "id": proposal_id},
                repair_class="unsupported",
                requires_human=True,
            )

    for proposal_id in sorted(set(events_by_id) - file_ids):
        result.add_error(
            f"Workflow proposal event {proposal_id} references a missing proposal file.",
            code="workflow_proposal_file_missing",
            entity={"type": "workflow_proposal", "id": proposal_id},
            repair_class="inspect",
            suggested_commands=[_pcl_json_command("workflow", "proposals", "list")],
        )


def _workflow_proposal_events_of_type(
    events: list[dict[str, Any]], event_type: str
) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event_type") == event_type]


def _validate_approved_workflow_proposal(
    paths: ProjectPaths,
    proposal_id: str,
    proposal_data: dict[str, Any],
    approved_event: dict[str, Any],
    result: ValidationResult,
) -> None:
    payload = (
        approved_event.get("payload") if isinstance(approved_event.get("payload"), dict) else {}
    )
    workflow_id = str(proposal_data.get("id") or "")
    expected_workflow_path = f".project-loop/workflows/{workflow_id}.yaml"
    if payload.get("workflow_id") != workflow_id:
        result.add_error(
            f"Workflow proposal {proposal_id} approved event workflow_id differs: "
            f"event={payload.get('workflow_id')!r}, file={workflow_id!r}.",
            code="workflow_proposal_approved_workflow_id_mismatch",
            entity={"type": "workflow_proposal", "id": proposal_id},
            repair_class="unsupported",
            requires_human=True,
        )
    if payload.get("workflow_path") != expected_workflow_path:
        result.add_error(
            f"Workflow proposal {proposal_id} approved event workflow_path differs: "
            f"event={payload.get('workflow_path')!r}, expected={expected_workflow_path!r}.",
            code="workflow_proposal_approved_path_mismatch",
            entity={"type": "workflow_proposal", "id": proposal_id},
            repair_class="unsupported",
            requires_human=True,
        )
        return
    workflow_path = paths.root / expected_workflow_path
    if not workflow_path.exists():
        result.add_error(
            f"Workflow proposal {proposal_id} approved workflow template is missing: {expected_workflow_path}.",
            code="workflow_proposal_approved_template_missing",
            entity={"type": "workflow_proposal", "id": proposal_id},
            repair_class="inspect",
            suggested_commands=[_pcl_json_command("workflow", "proposals", "read", proposal_id)],
        )
        return
    try:
        workflow_text = workflow_path.read_text(encoding="utf-8")
        workflow_data = validate_workflow_proposal_text(
            workflow_text, source_label=expected_workflow_path
        )
    except (InvalidInputError, OSError) as exc:
        result.add_error(
            f"Workflow proposal {proposal_id} approved workflow template is invalid: {exc}.",
            code="workflow_proposal_approved_template_invalid",
            entity={"type": "workflow_proposal", "id": proposal_id},
            repair_class="human_review",
            requires_human=True,
            suggested_commands=[_pcl_json_command("workflow", "proposals", "read", proposal_id)],
        )
        return
    if workflow_data.get("id") != workflow_id:
        result.add_error(
            f"Workflow proposal {proposal_id} approved workflow template id differs: "
            f"expected={workflow_id!r}, file={workflow_data.get('id')!r}.",
            code="workflow_proposal_approved_template_id_mismatch",
            entity={"type": "workflow_proposal", "id": proposal_id},
            repair_class="unsupported",
            requires_human=True,
        )
    content_sha256 = str(payload.get("content_sha256") or "")
    if not content_sha256:
        result.add_error(
            f"Workflow proposal {proposal_id} approved event has no content_sha256.",
            code="workflow_proposal_approved_hash_missing",
            entity={"type": "workflow_proposal", "id": proposal_id},
            repair_class="unsupported",
            requires_human=True,
        )
        return
    actual_sha256 = hashlib.sha256((workflow_text.strip() + "\n").encode("utf-8")).hexdigest()
    if content_sha256 != actual_sha256:
        result.add_error(
            f"Workflow proposal {proposal_id} approved workflow content hash differs: "
            f"event={content_sha256}, file={actual_sha256}.",
            code="workflow_proposal_approved_hash_mismatch",
            entity={"type": "workflow_proposal", "id": proposal_id},
            repair_class="human_review",
            requires_human=True,
            suggested_commands=[_pcl_json_command("workflow", "proposals", "read", proposal_id)],
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
        result.add_error(
            f"Workflow proposal {proposal_id} approved workflow verifier failed: {error}",
            code="workflow_proposal_approved_verifier_failed",
            entity={"type": "workflow_proposal", "id": proposal_id},
            repair_class="human_review",
            requires_human=True,
            suggested_commands=[_pcl_json_command("workflow", "proposals", "read", proposal_id)],
        )


def _validate_audit_log_integrity(
    paths: ProjectPaths, conn: sqlite3.Connection, result: ValidationResult
) -> None:
    if not paths.events_path.exists():
        return
    jsonl_events = _read_jsonl_events(paths, result)
    db_events = _db_events(conn, result)
    sequences = [int(event["sequence"]) for event in db_events if event.get("sequence") is not None]
    if sequences and sequences != list(range(1, len(sequences) + 1)):
        _add_audit_error(
            result,
            "DB event sequence must be contiguous and start at 1; "
            f"found {sequences[:10]}{'...' if len(sequences) > 10 else ''}.",
            code="audit_sequence_noncontiguous",
        )
    jsonl_by_id: dict[str, dict[str, Any]] = {}
    first_lines: dict[str, int] = {}
    for event in jsonl_events:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        line = int(event["_line"])
        if event_id in jsonl_by_id:
            _add_audit_error(
                result,
                f"Duplicate events.jsonl event id {event_id} at lines {first_lines[event_id]} and {line}.",
                code="audit_jsonl_duplicate_event",
                event_id=event_id,
            )
            continue
        jsonl_by_id[event_id] = event
        first_lines[event_id] = line

    db_by_id = {str(event["id"]): event for event in db_events}
    db_ids = set(db_by_id)
    jsonl_ids = set(jsonl_by_id)
    for event_id in sorted(db_ids - jsonl_ids):
        _add_audit_error(
            result,
            f"DB event {event_id} is missing from events.jsonl.",
            code="audit_projection_event_missing",
            event_id=event_id,
        )
    for event_id in sorted(jsonl_ids - db_ids):
        _add_audit_error(
            result,
            f"events.jsonl event {event_id} is missing from DB events table.",
            code="audit_database_event_missing",
            event_id=event_id,
        )

    if db_ids == jsonl_ids:
        db_order = [str(event["id"]) for event in db_events]
        jsonl_order = [str(event["id"]) for event in jsonl_events if event.get("id") in jsonl_by_id]
        if db_order != jsonl_order:
            for index, (db_id, jsonl_id) in enumerate(zip(db_order, jsonl_order), start=1):
                if db_id != jsonl_id:
                    _add_audit_error(
                        result,
                        f"Event order mismatch at position {index}: DB has {db_id}, events.jsonl has {jsonl_id}.",
                        code="audit_event_order_mismatch",
                    )
                    break

    for event_id in sorted(db_ids & jsonl_ids):
        _compare_event_record(event_id, db_by_id[event_id], jsonl_by_id[event_id], result)


def _read_jsonl_events(paths: ProjectPaths, result: ValidationResult) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = paths.events_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        _add_audit_error(
            result,
            f"Cannot read events.jsonl at {paths.events_path}: {exc}",
            code="audit_jsonl_unreadable",
        )
        return events
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            _add_audit_error(
                result,
                f"Invalid events.jsonl line {line_number}: blank lines are not valid events.",
                code="audit_jsonl_invalid_line",
            )
            continue
        try:
            value = json.loads(line)
        except JSONDecodeError as exc:
            _add_audit_error(
                result,
                f"Invalid events.jsonl line {line_number}: {exc.msg}.",
                code="audit_jsonl_invalid_line",
            )
            continue
        if not isinstance(value, dict):
            _add_audit_error(
                result,
                f"Invalid events.jsonl line {line_number}: event must be an object.",
                code="audit_jsonl_invalid_event",
            )
            continue
        event = dict(value)
        event["_line"] = line_number
        for field_name in ["id", "event_type", "entity_type", "entity_id", "payload", "created_at"]:
            if field_name not in event:
                _add_audit_error(
                    result,
                    f"Invalid events.jsonl line {line_number}: missing field {field_name}.",
                    code="audit_jsonl_event_field_missing",
                )
        if "payload" in event and not isinstance(event["payload"], dict):
            _add_audit_error(
                result,
                f"Invalid events.jsonl line {line_number}: payload must be an object.",
                code="audit_jsonl_payload_invalid",
            )
        events.append(event)
    return events


def _db_events(conn: sqlite3.Connection, result: ValidationResult) -> list[dict[str, Any]]:
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    if "sequence" in columns:
        rows = conn.execute(
            """
            SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
            FROM events
            ORDER BY sequence
            """
        ).fetchall()
    else:
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
            _add_audit_error(
                result,
                f"DB event {event['id']} has invalid payload_json: {exc.msg}.",
                code="audit_database_payload_invalid",
                event_id=str(event["id"]),
            )
            payload = {}
        if not isinstance(payload, dict):
            _add_audit_error(
                result,
                f"DB event {event['id']} payload_json must be an object.",
                code="audit_database_payload_invalid",
                event_id=str(event["id"]),
            )
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
            _add_audit_error(
                result,
                f"Event {event_id} field {field_name} differs: DB={db_event.get(field_name)!r}, "
                f"events.jsonl={jsonl_event.get(field_name)!r}.",
                code="audit_event_field_mismatch",
                event_id=event_id,
            )
    if db_event.get("payload") != jsonl_event.get("payload"):
        _add_audit_error(
            result,
            f"Event {event_id} payload differs between DB and events.jsonl.",
            code="audit_event_payload_mismatch",
            event_id=event_id,
        )
    if "sequence" in db_event and "sequence" in jsonl_event:
        if db_event["sequence"] != jsonl_event["sequence"]:
            _add_audit_error(
                result,
                f"Event {event_id} sequence differs: DB={db_event['sequence']!r}, "
                f"events.jsonl={jsonl_event['sequence']!r}.",
                code="audit_event_sequence_mismatch",
                event_id=event_id,
            )


def _add_audit_error(
    result: ValidationResult,
    message: str,
    *,
    code: str,
    event_id: str | None = None,
) -> None:
    result.add_error(
        message,
        code=code,
        entity=None if event_id is None else {"type": "event", "id": event_id},
        repair_class="inspect",
        suggested_commands=[_pcl_json_command("audit", "check")],
    )


def _validate_foreign_keys(conn: sqlite3.Connection, result: ValidationResult) -> None:
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    for row in rows:
        data = dict(row)
        result.add_error(
            "Foreign key violation: "
            f"{data.get('table')} rowid {data.get('rowid')} references {data.get('parent')}.",
            code="relationship_foreign_key_violation",
            entity={"type": "schema_table", "id": str(data.get("table"))},
            related=[{"type": "schema_table", "id": str(data.get("parent"))}],
            repair_class="unsupported",
            requires_human=True,
        )


def _validate_verification_feedback_references(
    conn: sqlite3.Connection,
    result: ValidationResult,
) -> None:
    if not table_exists(conn, "verification_feedback"):
        return
    rows = conn.execute(
        """
        SELECT id, receipt_evidence_id, supporting_evidence_id
        FROM verification_feedback
        ORDER BY created_at, id
        """
    ).fetchall()
    for row in rows:
        feedback_id = str(row["id"])
        receipt_evidence_id = str(row["receipt_evidence_id"] or "")
        if not receipt_evidence_id or _evidence_type(conn, receipt_evidence_id) is None:
            result.add_error(
                f"Verification feedback {feedback_id} references missing receipt evidence "
                f"{receipt_evidence_id or '<empty>'}.",
                code="verification_feedback_receipt_evidence_missing",
                entity={"type": "verification_feedback", "id": feedback_id},
                related=[{"type": "evidence", "id": receipt_evidence_id or "<empty>"}],
                repair_class="semantic",
                requires_human=True,
            )
        supporting_evidence_id = row["supporting_evidence_id"]
        if supporting_evidence_id and _evidence_type(conn, str(supporting_evidence_id)) is None:
            result.add_error(
                f"Verification feedback {feedback_id} references missing supporting evidence "
                f"{supporting_evidence_id}.",
                code="verification_feedback_supporting_evidence_missing",
                entity={"type": "verification_feedback", "id": feedback_id},
                related=[{"type": "evidence", "id": str(supporting_evidence_id)}],
                repair_class="semantic",
                requires_human=True,
            )


def _validate_evidence_links(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    result: ValidationResult,
) -> None:
    if not table_exists(conn, "evidence_links"):
        return
    rows = conn.execute(
        """
        SELECT evidence_id, target_type, target_id, link_role, created_at
        FROM evidence_links
        ORDER BY created_at, evidence_id, target_type, target_id, link_role
        """
    ).fetchall()
    known_targets = {
        "task": "tasks",
        "agent_job": "agent_jobs",
    }
    for row in rows:
        evidence_id = str(row["evidence_id"] or "")
        target_type = str(row["target_type"] or "")
        target_id = str(row["target_id"] or "")
        link_role = str(row["link_role"] or "")
        if not evidence_id or _evidence_type(conn, evidence_id) is None:
            result.add_error(
                f"Evidence link {evidence_id or '<empty>'} to {target_type}:{target_id} "
                f"as {link_role or '<empty>'} references missing evidence.",
                code="relationship_evidence_link_evidence_missing",
                entity={
                    "type": "evidence_link",
                    "id": f"{evidence_id}:{target_type}:{target_id}:{link_role}",
                },
                related=[
                    {"type": "evidence", "id": evidence_id or "<empty>"},
                    {"type": target_type or "unknown", "id": target_id or "<empty>"},
                ],
                repair_class="semantic",
                requires_human=True,
            )
        target_table = known_targets.get(target_type)
        if target_table is None:
            continue
        target = conn.execute(
            f"SELECT id FROM {target_table} WHERE id = ?",
            (target_id,),
        ).fetchone()
        if target is None:
            result.add_error(
                f"Evidence link {evidence_id or '<empty>'} references missing "
                f"{target_type} {target_id or '<empty>'}.",
                code="relationship_evidence_link_target_missing",
                entity={"type": "evidence", "id": evidence_id or "<empty>"},
                related=[{"type": target_type, "id": target_id or "<empty>"}],
                repair_class="semantic",
                requires_human=True,
            )
        _validate_code_context_link_binding(
            paths,
            evidence_id=evidence_id,
            target_type=target_type,
            target_id=target_id,
            link_role=link_role,
            result=result,
        )


def _validate_code_context_link_binding(
    paths: ProjectPaths,
    *,
    evidence_id: str,
    target_type: str,
    target_id: str,
    link_role: str,
    result: ValidationResult,
) -> None:
    if link_role != "code_context":
        return
    from .code_context.receipts import (
        CONTEXT_RECEIPT_EVIDENCE_TYPE,
        evidence_ref_by_id,
        resolve_context_receipt_path,
    )

    receipt_ref = evidence_ref_by_id(paths, evidence_id)
    if receipt_ref is None or receipt_ref.get("evidence_type") != CONTEXT_RECEIPT_EVIDENCE_TYPE:
        return
    receipt_path = resolve_context_receipt_path(paths, str(receipt_ref["receipt_path"]))
    try:
        receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError):
        return
    if not isinstance(receipt_payload, dict):
        return
    if _receipt_target_binding_agrees(
        receipt_payload,
        target_type=target_type,
        target_id=target_id,
    ):
        return
    result.add_error(
        "Evidence link "
        f"{evidence_id} to {target_type}:{target_id} as code_context has an artifact "
        "target_binding that disagrees with the evidence link routing row: "
        f"{receipt_payload.get('target_binding')!r}.",
        code="provenance_target_binding_mismatch",
        entity={"type": "evidence", "id": evidence_id},
        related=[{"type": target_type, "id": target_id}],
        repair_class="inspect",
        suggested_commands=[
            _pcl_json_command("evidence", "show", evidence_id),
            _pcl_json_command("audit", "check"),
        ],
    )


def _validate_closed_goals(
    paths: ProjectPaths, conn: sqlite3.Connection, result: ValidationResult
) -> None:
    for finding in _closed_goal_lifecycle_findings(paths, conn, result=result):
        _add_lifecycle_finding(paths, result, finding)


def _closed_goal_lifecycle_findings(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    result: ValidationResult | None = None,
) -> list[LifecycleFinding]:
    findings: list[LifecycleFinding] = []
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
        evidence_id = str(closure.get("evidence_id") or "").strip()
        proof_type = str(closure.get("proof_type") or "").strip()
        has_approved_verification = False
        if result is not None and not evidence and not evidence_id and not verification_id:
            result.add_error(
                f"Closed goal {goal_id} has no closure evidence or verification.",
                code="goal_closed_proof_missing",
                entity={"type": "goal", "id": goal_id},
                repair_class="human_review",
                requires_human=True,
                suggested_commands=[_pcl_json_command("repair", "lifecycle", "--dry-run")],
            )
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
            if result is not None and verification is None:
                result.add_error(
                    f"Closed goal {goal_id} references missing verification {verification_id}.",
                    code="goal_closed_verification_missing",
                    entity={"type": "goal", "id": goal_id},
                    related=[{"type": "verification", "id": verification_id}],
                    repair_class="human_review",
                    requires_human=True,
                    suggested_commands=[_pcl_json_command("repair", "lifecycle", "--dry-run")],
                )
            elif result is not None and verification["result"] != "approved":
                result.add_error(
                    f"Closed goal {goal_id} references non-approved verification {verification_id}.",
                    code="goal_closed_verification_not_approved",
                    entity={"type": "goal", "id": goal_id},
                    related=[{"type": "verification", "id": verification_id}],
                    repair_class="human_review",
                    requires_human=True,
                    suggested_commands=[
                        _pcl_json_command("verification", "read", verification_id),
                        _pcl_json_command("repair", "lifecycle", "--dry-run"),
                    ],
                )
            elif result is not None and verification["goal_id"] != goal_id:
                result.add_error(
                    f"Closed goal {goal_id} references verification {verification_id} from another goal.",
                    code="goal_closed_verification_target_mismatch",
                    entity={"type": "goal", "id": goal_id},
                    related=[{"type": "verification", "id": verification_id}],
                    repair_class="human_review",
                    requires_human=True,
                    suggested_commands=[
                        _pcl_json_command("verification", "read", verification_id),
                        _pcl_json_command("repair", "lifecycle", "--dry-run"),
                    ],
                )
            has_approved_verification = (
                verification is not None
                and verification["result"] == "approved"
                and verification["goal_id"] == goal_id
            )
        has_packet_proof = False
        if evidence_id and proof_type == "completion_packet":
            link = conn.execute(
                "SELECT 1 FROM evidence_links WHERE evidence_id = ? AND target_type = 'goal' AND target_id = ? AND link_role = 'completion_packet'",
                (evidence_id, goal_id),
            ).fetchone()
            row_evidence = conn.execute(
                "SELECT type, path FROM evidence WHERE id = ?", (evidence_id,)
            ).fetchone()
            has_packet_proof = (
                link is not None
                and row_evidence is not None
                and row_evidence["type"] == "completion_packet"
            )
            if has_packet_proof:
                has_packet_proof = completion_packet_is_valid_for_goal(
                    paths, str(row_evidence["path"]), goal_id
                )
        needs_lifecycle_finding = (
            not has_approved_verification if result is None else not verification_id
        )
        if needs_lifecycle_finding and not has_packet_proof:
            findings.append(
                LifecycleFinding(
                    code="goal_close_verification_required",
                    message=(
                        "goal_close_verification_required: Closed goal "
                        f"{goal_id} has neither approved same-goal Verification nor valid "
                        "completed packet Evidence."
                    ),
                    entity_type="goal",
                    entity_id=goal_id,
                    details={
                        "evidence_id": evidence_id,
                        "proof_type": proof_type,
                        "verification_id": verification_id,
                    },
                )
            )
    return findings


def completion_packet_is_valid_for_goal(
    paths: ProjectPaths,
    path_value: str,
    goal_id: str,
) -> bool:
    path = Path(path_value)
    packet_path = path if path.is_absolute() else paths.root / path
    try:
        packet = load_completion_packet(packet_path)
    except (OSError, json.JSONDecodeError):
        return False
    if not validate_completion_packet(packet).ok or not isinstance(packet, dict):
        return False
    target = packet.get("target")
    if not isinstance(target, dict) or target.get("type") != "goal" or target.get("id") != goal_id:
        return False
    if packet.get("outcome") not in {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"}:
        return False
    risks = packet.get("risks", [])
    return isinstance(risks, list) and all(
        isinstance(risk, dict) and risk.get("severity") == "low" for risk in risks
    )


def _validate_passed_workflow_runs(conn: sqlite3.Connection, result: ValidationResult) -> None:
    rows = conn.execute(
        "SELECT id FROM workflow_runs WHERE status = 'passed' ORDER BY id"
    ).fetchall()
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
            result.add_error(
                f"Passed workflow run {run_id} has non-passed jobs: {counts}.",
                code="workflow_run_passed_jobs_incomplete",
                entity={"type": "workflow_run", "id": run_id},
                related=[
                    {
                        "type": "agent_job_status",
                        "id": str(job["status"]),
                        "status": str(job["count"]),
                    }
                    for job in bad_jobs
                ],
                repair_class="unsupported",
                requires_human=True,
            )
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
            result.add_error(
                f"Passed workflow run {run_id} has no approved verification.",
                code="workflow_run_passed_verification_missing",
                entity={"type": "workflow_run", "id": run_id},
                repair_class="human_review",
                requires_human=True,
            )


def _validate_verified_or_closed_defects(
    conn: sqlite3.Connection, result: ValidationResult
) -> None:
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
            result.add_error(
                f"Defect {defect_id} is {status} but has no evidence_id.",
                code="defect_terminal_evidence_missing",
                entity={"type": "defect", "id": defect_id},
                repair_class="semantic",
                requires_human=True,
            )
        else:
            evidence_type = _evidence_type(conn, evidence_id)
            if evidence_type is None:
                result.add_error(
                    f"Defect {defect_id} references missing evidence {evidence_id}.",
                    code="defect_terminal_evidence_reference_missing",
                    entity={"type": "defect", "id": defect_id},
                    related=[{"type": "evidence", "id": evidence_id}],
                    repair_class="semantic",
                    requires_human=True,
                )
            elif evidence_type != expected_current_type:
                result.add_error(
                    f"Defect {defect_id} has current evidence {evidence_id} with type "
                    f"{evidence_type}, expected {expected_current_type}.",
                    code="defect_terminal_evidence_type_mismatch",
                    entity={"type": "defect", "id": defect_id},
                    related=[{"type": "evidence", "id": evidence_id}],
                    repair_class="semantic",
                    requires_human=True,
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
            result.add_error(
                f"Defect {defect_id} is {status} but has no approved verification tied to the defect.",
                code="defect_terminal_verification_missing",
                entity={"type": "defect", "id": defect_id},
                repair_class="human_review",
                requires_human=True,
            )


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
            result.add_error(
                f"Test case {test_case_id} is {status} but has no evidence_id.",
                code="test_terminal_evidence_missing",
                entity={"type": "test_case", "id": test_case_id},
                repair_class="semantic",
                requires_human=True,
                suggested_commands=[_pcl_json_command("test", "read", test_case_id)],
            )
        else:
            evidence_type = _evidence_type(conn, evidence_id)
            if evidence_type is None:
                result.add_error(
                    f"Test case {test_case_id} references missing evidence {evidence_id}.",
                    code="test_terminal_evidence_reference_missing",
                    entity={"type": "test_case", "id": test_case_id},
                    related=[{"type": "evidence", "id": evidence_id}],
                    repair_class="semantic",
                    requires_human=True,
                    suggested_commands=[_pcl_json_command("test", "read", test_case_id)],
                )
            elif evidence_type != expected_evidence_type and not (
                status == "passing"
                and evidence_type in (ADHOC_EVIDENCE_TYPES | {"evidence_set"})
            ):
                result.add_error(
                    f"Test case {test_case_id} has current evidence {evidence_id} with type "
                    f"{evidence_type}, expected {expected_evidence_type}.",
                    code="test_terminal_evidence_type_mismatch",
                    entity={"type": "test_case", "id": test_case_id},
                    related=[{"type": "evidence", "id": evidence_id}],
                    repair_class="semantic",
                    requires_human=True,
                    suggested_commands=[_pcl_json_command("test", "read", test_case_id)],
                )
        _validate_test_case_transition_evidence(
            conn,
            result,
            test_case_id=test_case_id,
            status=status,
            event_type=event_type,
            evidence_type=expected_evidence_type,
            alternative_types=(ADHOC_EVIDENCE_TYPES | {"evidence_set"})
            if status == "passing"
            else set(),
        )


def _add_lifecycle_finding(
    paths: ProjectPaths, result: ValidationResult, finding: LifecycleFinding
) -> None:
    policy = _simple_yaml_section(
        (paths.root / "pcl.yaml").read_text(encoding="utf-8").splitlines()
        if (paths.root / "pcl.yaml").exists()
        else [],
        "validation",
    ).get("lifecycle_integrity", "advisory")
    related = _lifecycle_related(finding)
    commands = _lifecycle_commands(finding, related)
    kwargs = {
        "code": finding.code,
        "entity": {"type": finding.entity_type, "id": finding.entity_id},
        "related": related,
        "repair_class": "semantic",
        "requires_human": True,
        "suggested_commands": commands,
    }
    if policy == "enforced":
        result.add_error(finding.message, **kwargs)
    else:
        result.add_warning(f"{LIFECYCLE_ADVISORY_PREFIX}{finding.message}", **kwargs)


def _lifecycle_related(finding: LifecycleFinding) -> list[dict[str, str]]:
    related: list[dict[str, str]] = []
    mappings = (
        ("story_ids", "user_story", None),
        ("test_ids", "test_case", None),
        ("defect_ids", "defect", None),
    )
    for key, entity_type, status in mappings:
        for entity_id in finding.details.get(key, []):
            item = {"type": entity_type, "id": str(entity_id)}
            if status:
                item["status"] = status
            related.append(item)
    story_id = finding.details.get("story_id")
    if story_id:
        item = {"type": "user_story", "id": str(story_id)}
        if finding.details.get("story_status"):
            item["status"] = str(finding.details["story_status"])
        related.append(item)
    if finding.code == "feature_done_story_incomplete":
        statuses = finding.details.get("story_statuses", {})
        for item in related:
            if item["type"] == "user_story" and item["id"] in statuses:
                item["status"] = str(statuses[item["id"]])
    return related


def _lifecycle_commands(
    finding: LifecycleFinding,
    related: list[dict[str, str]],
) -> list[str]:
    commands: list[str] = []
    for item in related:
        noun = {"user_story": "story", "test_case": "test"}.get(item["type"])
        if noun:
            commands.append(_pcl_json_command(noun, "read", item["id"]))
    commands.append(_pcl_json_command("repair", "lifecycle", "--dry-run"))
    return list(dict.fromkeys(commands))


def _validate_story_test_traceability(
    paths: ProjectPaths, conn: sqlite3.Connection, result: ValidationResult
) -> None:
    for finding in _story_test_traceability_findings(conn):
        _add_lifecycle_finding(paths, result, finding)


def _story_test_traceability_findings(conn: sqlite3.Connection) -> list[LifecycleFinding]:
    findings: list[LifecycleFinding] = []
    rows = conn.execute(
        """
        SELECT tc.id, tc.feature_id, tc.story_id, us.feature_id AS story_feature_id, us.status AS story_status
        FROM test_cases AS tc
        LEFT JOIN user_stories AS us ON us.id = tc.story_id
        WHERE tc.status = 'passing'
        ORDER BY tc.id
        """
    ).fetchall()
    for row in rows:
        test_id = str(row["id"])
        story_id = str(row["story_id"] or "")
        if not story_id or row["story_feature_id"] != row["feature_id"]:
            candidates = [
                str(candidate["id"])
                for candidate in conn.execute(
                    "SELECT id FROM user_stories WHERE feature_id = ? ORDER BY id",
                    (row["feature_id"],),
                ).fetchall()
            ]
            findings.append(
                LifecycleFinding(
                    code="test_story_required",
                    message=(
                        f"test_story_required: Passing test {test_id} has no same-Feature "
                        "Story link."
                    ),
                    entity_type="test_case",
                    entity_id=test_id,
                    details={
                        "feature_id": str(row["feature_id"]),
                        "story_id": story_id,
                        "story_candidates": candidates,
                    },
                )
            )
        elif row["story_status"] not in {"approved", "waived"}:
            findings.append(
                LifecycleFinding(
                    code="test_story_not_terminal",
                    message=(
                        f"test_story_not_terminal: Passing test {test_id} links Story "
                        f"{story_id} in {row['story_status']} status."
                    ),
                    entity_type="test_case",
                    entity_id=test_id,
                    details={
                        "feature_id": str(row["feature_id"]),
                        "story_id": story_id,
                        "story_status": str(row["story_status"]),
                    },
                )
            )
    return findings


def _validate_done_features(
    paths: ProjectPaths, conn: sqlite3.Connection, result: ValidationResult
) -> None:
    for finding in _done_feature_lifecycle_findings(conn):
        _add_lifecycle_finding(paths, result, finding)


def _done_feature_lifecycle_findings(conn: sqlite3.Connection) -> list[LifecycleFinding]:
    findings: list[LifecycleFinding] = []
    for feature in conn.execute(
        "SELECT id FROM features WHERE status = 'done' ORDER BY id"
    ).fetchall():
        feature_id = str(feature["id"])
        stories = conn.execute(
            "SELECT id, status FROM user_stories WHERE feature_id = ? ORDER BY id",
            (feature_id,),
        ).fetchall()
        if not stories or any(row["status"] not in {"approved", "waived"} for row in stories):
            ids = (
                ",".join(
                    str(row["id"]) for row in stories if row["status"] not in {"approved", "waived"}
                )
                or "none"
            )
            findings.append(
                LifecycleFinding(
                    code="feature_done_story_incomplete",
                    message=(
                        f"feature_done_story_incomplete: Done feature {feature_id} has "
                        f"incomplete Stories: {ids}."
                    ),
                    entity_type="feature",
                    entity_id=feature_id,
                    details={
                        "story_ids": [
                            str(row["id"])
                            for row in stories
                            if row["status"] not in {"approved", "waived"}
                        ],
                        "story_statuses": {
                            str(row["id"]): str(row["status"])
                            for row in stories
                            if row["status"] not in {"approved", "waived"}
                        },
                    },
                )
            )
        tests = conn.execute(
            "SELECT id, status FROM test_cases "
            "WHERE feature_id = ? AND status != 'waived' ORDER BY id",
            (feature_id,),
        ).fetchall()
        if not tests or any(row["status"] != "passing" for row in tests):
            findings.append(
                LifecycleFinding(
                    code="feature_done_tests_incomplete",
                    message=(
                        f"feature_done_tests_incomplete: Done feature {feature_id} lacks "
                        "complete passing Tests."
                    ),
                    entity_type="feature",
                    entity_id=feature_id,
                    details={
                        "test_ids": [str(row["id"]) for row in tests if row["status"] != "passing"]
                    },
                )
            )
        defects = conn.execute(
            "SELECT id FROM defects "
            "WHERE feature_id = ? AND status NOT IN ('closed', 'waived') ORDER BY id",
            (feature_id,),
        ).fetchall()
        if defects:
            findings.append(
                LifecycleFinding(
                    code="feature_done_open_defects",
                    message=(
                        f"feature_done_open_defects: Done feature {feature_id} has active Defects."
                    ),
                    entity_type="feature",
                    entity_id=feature_id,
                    details={"defect_ids": [str(row["id"]) for row in defects]},
                )
            )
        linked = conn.execute(
            "SELECT 1 FROM evidence_links WHERE target_type = 'feature' AND target_id = ? AND link_role IN ('acceptance', 'completion_packet')",
            (feature_id,),
        ).fetchone()
        if linked is None:
            findings.append(
                LifecycleFinding(
                    code="feature_done_evidence_required",
                    message=(
                        f"feature_done_evidence_required: Done feature {feature_id} lacks "
                        "target-bound completion Evidence."
                    ),
                    entity_type="feature",
                    entity_id=feature_id,
                )
            )
    return findings


def _validate_direct_test_evidence(
    paths: ProjectPaths, conn: sqlite3.Connection, result: ValidationResult
) -> None:
    for finding in _direct_test_evidence_findings(paths, conn):
        _add_lifecycle_finding(paths, result, finding)


def _direct_test_evidence_findings(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
) -> list[LifecycleFinding]:
    findings: list[LifecycleFinding] = []
    rows = conn.execute(
        "SELECT id, last_run_id, evidence_id FROM test_cases WHERE status = 'passing' ORDER BY id"
    ).fetchall()
    for row in rows:
        if row["last_run_id"]:
            continue
        evidence_id = str(row["evidence_id"] or "")
        evidence = conn.execute(
            "SELECT type, path FROM evidence WHERE id = ?", (evidence_id,)
        ).fetchone()
        link = conn.execute(
            "SELECT 1 FROM evidence_links WHERE evidence_id = ? AND target_type = 'test_case' AND target_id = ? AND link_role = 'acceptance'",
            (evidence_id, row["id"]),
        ).fetchone()
        evidence_health = None
        if evidence is not None and evidence["type"] in ADHOC_EVIDENCE_TYPES:
            evidence_health = assess_adhoc_evidence(
                paths,
                evidence_id=evidence_id,
                evidence_type=str(evidence["type"]),
                manifest_path_value=str(evidence["path"]),
                validate_optional_fields=True,
            )["health"]
        elif evidence is not None and evidence["type"] == "evidence_set":
            evidence_health = _terminal_evidence_set_health(
                paths,
                conn,
                test_case_id=str(row["id"]),
                evidence_id=evidence_id,
                artifact_path_value=str(evidence["path"]),
            )
        healthy = evidence_health == "ok" and link is not None
        if not healthy:
            acceptance_links = [
                {
                    "target_type": str(link_row["target_type"]),
                    "target_id": str(link_row["target_id"]),
                    "link_role": str(link_row["link_role"]),
                }
                for link_row in conn.execute(
                    "SELECT target_type, target_id, link_role FROM evidence_links "
                    "WHERE evidence_id = ? ORDER BY target_type, target_id, link_role",
                    (evidence_id,),
                ).fetchall()
            ]
            findings.append(
                LifecycleFinding(
                    code="test_acceptance_evidence_required",
                    message=(
                        f"test_acceptance_evidence_required: Direct passing test {row['id']} "
                        "lacks healthy target-bound acceptance Evidence."
                    ),
                    entity_type="test_case",
                    entity_id=str(row["id"]),
                    details={
                        "evidence_id": evidence_id,
                        "evidence_type": None if evidence is None else str(evidence["type"]),
                        "evidence_health": evidence_health,
                        "links": acceptance_links,
                    },
                )
            )
    return findings


def _terminal_evidence_set_health(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    test_case_id: str,
    evidence_id: str,
    artifact_path_value: str,
) -> str:
    try:
        artifact = load_evidence_set(paths.root / artifact_path_value)
    except (OSError, ValueError, json.JSONDecodeError):
        return "error"
    validation = validate_evidence_set(artifact)
    if not validation.ok or not isinstance(artifact, dict):
        return "error"
    if artifact["target"] != {"type": "test_case", "id": test_case_id}:
        return "error"
    if artifact["completeness"]["status"] != "complete":
        return "error"
    row = conn.execute(
        """
        SELECT payload_json
        FROM events
        WHERE event_type = 'test_case_passed'
          AND entity_type = 'test_case'
          AND entity_id = ?
        ORDER BY sequence DESC, id DESC
        LIMIT 1
        """,
        (test_case_id,),
    ).fetchone()
    if row is None:
        return "error"
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        return "error"
    evaluation = payload.get("completion_evaluation") if isinstance(payload, dict) else None
    if not isinstance(evaluation, dict):
        return "error"
    if evaluation.get("status") != "passed" or evaluation.get("evidence_set_id") != evidence_id:
        return "error"
    return "ok"


def collect_lifecycle_findings(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
) -> list[LifecycleFinding]:
    """Return structured lifecycle findings without parsing rendered validation prose."""
    return [
        *_closed_goal_lifecycle_findings(paths, conn),
        *_story_test_traceability_findings(conn),
        *_done_feature_lifecycle_findings(conn),
        *_direct_test_evidence_findings(paths, conn),
    ]


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
                f"Duplicate active workflow runs for {target_type} {target_id}: {', '.join(run_ids)}.",
                code="duplicate_active_workflow_runs",
                entity={"type": target_type, "id": target_id},
                related=[{"type": "workflow_run", "id": run_id} for run_id in run_ids],
                repair_class="human_review",
                requires_human=True,
                suggested_commands=[
                    _pcl_json_command("loop", "status"),
                    shlex.join(["pcl", "report", "validation", "--strict"]),
                ],
            )


def _validate_terminal_parent_children(conn: sqlite3.Connection, result: ValidationResult) -> None:
    run_placeholders = ", ".join("?" for _ in ACTIVE_RUN_STATUSES)
    terminal_goal_placeholders = ", ".join("?" for _ in TERMINAL_GOAL_STATUSES)
    rows = conn.execute(
        f"""
        SELECT goals.id AS goal_id, goals.status AS goal_status,
               workflow_runs.id AS workflow_run_id, workflow_runs.status AS workflow_run_status
        FROM goals
        JOIN workflow_runs ON workflow_runs.goal_id = goals.id
        WHERE goals.status IN ({terminal_goal_placeholders})
          AND workflow_runs.status IN ({run_placeholders})
        ORDER BY goals.id, workflow_runs.id
        """,
        (*TERMINAL_GOAL_STATUSES, *ACTIVE_RUN_STATUSES),
    ).fetchall()
    for row in rows:
        result.add_error(
            f"Terminal goal {row['goal_id']} is {row['goal_status']} but has active "
            f"workflow run {row['workflow_run_id']} ({row['workflow_run_status']}).",
            code="relationship_terminal_goal_active_workflow",
            entity={"type": "goal", "id": str(row["goal_id"])},
            related=[
                {
                    "type": "workflow_run",
                    "id": str(row["workflow_run_id"]),
                    "status": str(row["workflow_run_status"]),
                }
            ],
            repair_class="human_review",
            requires_human=True,
            suggested_commands=[_pcl_json_command("loop", "status")],
        )

    if table_exists(conn, "tasks"):
        task_placeholders = ", ".join("?" for _ in TERMINAL_TASK_STATUSES)
        rows = conn.execute(
            f"""
            SELECT goals.id AS goal_id, goals.status AS goal_status,
                   tasks.id AS task_id, tasks.status AS task_status
            FROM goals
            JOIN tasks ON tasks.related_goal_id = goals.id
            WHERE goals.status IN ({terminal_goal_placeholders})
              AND tasks.status NOT IN ({task_placeholders})
            ORDER BY goals.id, tasks.id
            """,
            (*TERMINAL_GOAL_STATUSES, *TERMINAL_TASK_STATUSES),
        ).fetchall()
        for row in rows:
            result.add_error(
                f"Terminal goal {row['goal_id']} is {row['goal_status']} but has non-terminal "
                f"task {row['task_id']} ({row['task_status']}).",
                code="relationship_terminal_goal_active_task",
                entity={"type": "goal", "id": str(row["goal_id"])},
                related=[
                    {"type": "task", "id": str(row["task_id"]), "status": str(row["task_status"])}
                ],
                repair_class="human_review",
                requires_human=True,
                suggested_commands=[_pcl_json_command("task", "read", str(row["task_id"]))],
            )

    terminal_run_placeholders = ", ".join("?" for _ in TERMINAL_RUN_STATUSES)
    active_job_placeholders = ", ".join("?" for _ in ACTIVE_JOB_STATUSES)
    rows = conn.execute(
        f"""
        SELECT workflow_runs.id AS workflow_run_id, workflow_runs.status AS workflow_run_status,
               agent_jobs.id AS agent_job_id, agent_jobs.status AS agent_job_status
        FROM workflow_runs
        JOIN agent_jobs ON agent_jobs.workflow_run_id = workflow_runs.id
        WHERE workflow_runs.status IN ({terminal_run_placeholders})
          AND agent_jobs.status IN ({active_job_placeholders})
        ORDER BY workflow_runs.id, agent_jobs.id
        """,
        (*TERMINAL_RUN_STATUSES, *ACTIVE_JOB_STATUSES),
    ).fetchall()
    for row in rows:
        result.add_error(
            f"Terminal workflow run {row['workflow_run_id']} is {row['workflow_run_status']} "
            f"but has active agent job {row['agent_job_id']} ({row['agent_job_status']}).",
            code="relationship_terminal_workflow_active_job",
            entity={"type": "workflow_run", "id": str(row["workflow_run_id"])},
            related=[
                {
                    "type": "agent_job",
                    "id": str(row["agent_job_id"]),
                    "status": str(row["agent_job_status"]),
                }
            ],
            repair_class="human_review",
            requires_human=True,
            suggested_commands=[_pcl_json_command("jobs", "read", str(row["agent_job_id"]))],
        )


def _validate_decision_block_links(conn: sqlite3.Connection, result: ValidationResult) -> None:
    rows = conn.execute(
        """
        SELECT id, blocks_json
        FROM decisions
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        decision_id = str(row["id"])
        try:
            blocks = json.loads(str(row["blocks_json"] or "[]"))
        except JSONDecodeError as exc:
            result.add_error(
                f"Decision {decision_id} blocks_json is invalid JSON: {exc.msg}.",
                code="decision_blocks_json_invalid",
                entity={"type": "decision", "id": decision_id},
                repair_class="unsupported",
                requires_human=True,
            )
            continue
        if not isinstance(blocks, list):
            result.add_error(
                f"Decision {decision_id} blocks_json must be a JSON array.",
                code="decision_blocks_not_array",
                entity={"type": "decision", "id": decision_id},
                repair_class="unsupported",
                requires_human=True,
            )
            continue
        for index, item in enumerate(blocks, start=1):
            if not isinstance(item, dict):
                result.add_error(
                    f"Decision {decision_id} blocks_json item {index} must be an object.",
                    code="decision_block_item_not_object",
                    entity={"type": "decision", "id": decision_id},
                    related=[{"type": "decision_block_item", "id": str(index)}],
                    repair_class="unsupported",
                    requires_human=True,
                )
                continue
            target_type = item.get("type")
            target_id = item.get("id")
            if (
                not isinstance(target_type, str)
                or not target_type
                or not isinstance(target_id, str)
                or not target_id
            ):
                result.add_error(
                    f"Decision {decision_id} blocks_json item {index} must include string type and id.",
                    code="decision_block_target_invalid",
                    entity={"type": "decision", "id": decision_id},
                    related=[{"type": "decision_block_item", "id": str(index)}],
                    repair_class="unsupported",
                    requires_human=True,
                )
                continue
            table_name = DECISION_BLOCK_TARGET_TABLES.get(target_type)
            if table_name is None:
                result.add_error(
                    f"Decision {decision_id} blocks_json item {index} has unsupported type {target_type!r}.",
                    code="decision_block_target_type_unsupported",
                    entity={"type": "decision", "id": decision_id},
                    related=[{"type": str(target_type), "id": str(target_id)}],
                    repair_class="unsupported",
                    requires_human=True,
                )
                continue
            if not table_exists(conn, table_name):
                result.add_error(
                    f"Decision {decision_id} blocks_json item {index} uses unavailable type {target_type!r}.",
                    code="decision_block_target_type_unavailable",
                    entity={"type": "decision", "id": decision_id},
                    related=[{"type": target_type, "id": target_id}],
                    repair_class="unsupported",
                    requires_human=True,
                )
                continue
            if (
                conn.execute(f"SELECT 1 FROM {table_name} WHERE id = ?", (target_id,)).fetchone()
                is None
            ):
                result.add_error(
                    f"Decision {decision_id} blocks_json references missing {target_type} {target_id}.",
                    code="decision_block_target_missing",
                    entity={"type": "decision", "id": decision_id},
                    related=[{"type": target_type, "id": target_id}],
                    repair_class="human_review",
                    requires_human=True,
                )


def _validate_evidence_set_artifacts(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    result: ValidationResult,
) -> None:
    rows = conn.execute(
        "SELECT id, path FROM evidence WHERE type = 'evidence_set' ORDER BY id",
    ).fetchall()
    for row in rows:
        evidence_id = str(row["id"])
        findings: list[dict[str, Any]] = []
        artifact_path = paths.root / str(row["path"])
        artifact: dict[str, Any] | None = None
        try:
            value = load_evidence_set(artifact_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append({"code": "artifact_unreadable", "reason": str(exc)})
        else:
            validation = validate_evidence_set(value)
            if not validation.ok:
                findings.append({"code": "contract_invalid", "errors": list(validation.errors)})
            elif isinstance(value, dict):
                artifact = value
        links = conn.execute(
            """
            SELECT target_type, target_id
            FROM evidence_links
            WHERE evidence_id = ? AND link_role = 'evidence_set'
            ORDER BY target_type, target_id
            """,
            (evidence_id,),
        ).fetchall()
        if len(links) != 1:
            findings.append({"code": "target_link_count", "actual": len(links), "expected": 1})
        elif artifact is not None:
            linked_target = {"type": str(links[0]["target_type"]), "id": str(links[0]["target_id"])}
            if artifact["target"] != linked_target:
                findings.append({"code": "target_mismatch"})
        for finding in findings:
            code = str(finding.get("code") or "unknown")
            if code == "contract_invalid":
                message = (
                    f"Evidence set {evidence_id} contract is invalid: "
                    + "; ".join(str(item) for item in finding.get("errors", []))
                )
            else:
                message = f"Evidence set {evidence_id} failed integrity check: {code}."
            result.add_error(
                message,
                code=f"evidence_set_{code}",
                entity={"type": "evidence", "id": evidence_id},
                repair_class="inspect",
                suggested_commands=[
                    _pcl_json_command("evidence-set", "show", "--evidence", evidence_id)
                ],
            )


def _validate_adhoc_evidence_manifests(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    result: ValidationResult,
) -> None:
    evidence_rows = conn.execute(
        """
        SELECT id, type, path
        FROM evidence
        WHERE type IN ('adhoc_artifact', 'adhoc_bundle')
        ORDER BY id
        """
    ).fetchall()
    for row in evidence_rows:
        evidence_id = str(row["id"])
        manifest_path_value = str(row["path"] or "").strip()
        assessment = assess_adhoc_evidence(
            paths,
            evidence_id=evidence_id,
            evidence_type=str(row["type"]),
            manifest_path_value=manifest_path_value,
            validate_optional_fields=True,
        )
        _add_adhoc_assessment_findings(result, evidence_id=evidence_id, assessment=assessment)


def _add_adhoc_assessment_findings(
    result: ValidationResult,
    *,
    evidence_id: str,
    assessment: dict[str, Any],
) -> None:
    for finding in assessment.get("findings", []):
        if not isinstance(finding, dict):
            result.add_error(
                f"Adhoc evidence {evidence_id} assessment finding is not an object.",
                code="evidence_adhoc_assessment_finding_invalid",
                entity={"type": "evidence", "id": evidence_id},
                repair_class="unsupported",
                requires_human=True,
            )
            continue
        code = str(finding.get("code") or "")
        path = str(finding.get("path") or "")
        detail = str(finding.get("detail") or "")
        index = finding.get("index")
        emitter = _AdhocFindingEmitter(result, evidence_id=evidence_id, code=code, path=path)
        if code == "manifest_not_local":
            emitter.error(f"Adhoc evidence {evidence_id} manifest path is not local: {path}.")
        elif code == "manifest_missing":
            emitter.error(f"Adhoc evidence {evidence_id} manifest does not exist: {path}.")
        elif code == "manifest_not_file":
            emitter.error(f"Adhoc evidence {evidence_id} manifest is not a file: {path}.")
        elif code == "manifest_corrupt" and detail == "root must be an object":
            emitter.error(
                f"Adhoc evidence {evidence_id} manifest is corrupt: root must be an object."
            )
        elif code == "manifest_corrupt":
            emitter.error(f"Adhoc evidence {evidence_id} manifest is corrupt: {path}: {detail}.")
        elif code == "contract_version_unsupported":
            emitter.error(
                f"Adhoc evidence {evidence_id} manifest has unsupported contract_version: {detail}."
            )
        elif code == "evidence_id_mismatch":
            emitter.error(f"Adhoc evidence {evidence_id} manifest evidence_id mismatch: {detail}.")
        elif code == "evidence_type_mismatch":
            emitter.error(
                f"Adhoc evidence {evidence_id} manifest evidence_type mismatch: {detail}."
            )
        elif code == "members_invalid":
            emitter.error(
                f"Adhoc evidence {evidence_id} manifest members must be a non-empty list."
            )
        elif code == "sensitive_path_warning_count_invalid":
            emitter.error(
                f"Adhoc evidence {evidence_id} manifest sensitive_path_warning_count is invalid: {detail}."
            )
        elif code == "member_entry_invalid":
            _add_adhoc_member_entry_finding(
                result, evidence_id=evidence_id, index=index, path=path, detail=detail
            )
        elif code == "member_missing":
            emitter.warning(f"Adhoc evidence {evidence_id} member {path} drifted: missing.")
        elif code == "member_hash_mismatch":
            emitter.warning(f"Adhoc evidence {evidence_id} member {path} drifted: hash mismatch.")
        elif code == "copy_missing":
            emitter.warning(f"Adhoc evidence {evidence_id} copied member {path} drifted: missing.")
        elif code == "copy_hash_mismatch":
            emitter.warning(
                f"Adhoc evidence {evidence_id} copied member {path} drifted: hash mismatch."
            )
        elif code == "member_outside_project_root":
            emitter.warning(
                f"Adhoc evidence {evidence_id} member {path} is outside the project root."
            )
        elif code == "source_drifted":
            rendered_detail = {
                "hash_mismatch": "hash mismatch",
                "size_mismatch": "size mismatch",
            }.get(detail, detail)
            emitter.warning(
                f"Adhoc evidence {evidence_id} source member {path} drifted: {rendered_detail}."
            )
        else:
            emitter.error(f"Adhoc evidence {evidence_id} has unsupported health finding: {code}.")


@dataclass(frozen=True)
class _AdhocFindingEmitter:
    result: ValidationResult
    evidence_id: str
    code: str
    path: str

    def _kwargs(self) -> dict[str, Any]:
        return {
            "code": f"evidence_adhoc_{self.code or 'unknown'}",
            "entity": {"type": "evidence", "id": self.evidence_id},
            "related": [] if not self.path else [{"type": "artifact", "id": self.path}],
            "repair_class": "inspect",
            "suggested_commands": [_pcl_json_command("evidence", "show", self.evidence_id)],
        }

    def error(self, message: str) -> None:
        self.result.add_error(message, requires_human=True, **self._kwargs())

    def warning(self, message: str) -> None:
        self.result.add_warning(message, requires_human=False, **self._kwargs())


def _add_adhoc_member_entry_finding(
    result: ValidationResult,
    *,
    evidence_id: str,
    index: Any,
    path: str,
    detail: str,
) -> None:
    emitter = _AdhocFindingEmitter(
        result, evidence_id=evidence_id, code=f"member_entry_{detail}", path=path
    )
    if detail == "must_be_object":
        emitter.error(f"Adhoc evidence {evidence_id} manifest member {index} must be an object.")
    elif detail == "path_invalid":
        emitter.error(f"Adhoc evidence {evidence_id} manifest member {index} path is invalid.")
    elif detail == "path_absolute":
        emitter.error(f"Adhoc evidence {evidence_id} manifest member {path} path must be relative.")
    elif detail == "path_duplicated":
        emitter.error(f"Adhoc evidence {evidence_id} manifest member path is duplicated: {path}.")
    elif detail == "size_bytes_invalid":
        emitter.error(f"Adhoc evidence {evidence_id} manifest member {path} size_bytes is invalid.")
    elif detail == "sha256_invalid":
        emitter.error(f"Adhoc evidence {evidence_id} manifest member {path} sha256 is invalid.")
    elif detail == "path_scope_invalid":
        emitter.error(f"Adhoc evidence {evidence_id} manifest member {path} path_scope is invalid.")
    elif detail == "sensitive_pattern_invalid":
        emitter.error(
            f"Adhoc evidence {evidence_id} manifest member {path} sensitive_pattern is invalid."
        )
    elif detail == "storage_mode_invalid":
        emitter.error(
            f"Adhoc evidence {evidence_id} manifest member {path} storage_mode is invalid."
        )
    elif detail == "stored_path_invalid":
        emitter.error(
            f"Adhoc evidence {evidence_id} manifest member {path} stored_path is invalid."
        )
    else:
        emitter.error(
            f"Adhoc evidence {evidence_id} manifest member {index} has unsupported finding: {detail}."
        )


def _validate_local_artifact_paths(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    result: ValidationResult,
) -> None:
    evidence_rows = conn.execute(
        """
        SELECT id, type, path
        FROM evidence
        ORDER BY id
        """
    ).fetchall()
    for row in evidence_rows:
        if str(row["type"]) in ADHOC_EVIDENCE_TYPES:
            continue
        _validate_local_artifact_path(
            paths,
            result,
            owner=f"Evidence {row['id']}",
            field_name="path",
            path_value=str(row["path"] or ""),
            entity={"type": "evidence", "id": str(row["id"])},
        )

    job_rows = conn.execute(
        """
        SELECT id, prompt_path, output_path
        FROM agent_jobs
        ORDER BY id
        """
    ).fetchall()
    for row in job_rows:
        _validate_local_artifact_path(
            paths,
            result,
            owner=f"Agent job {row['id']}",
            field_name="prompt_path",
            path_value=str(row["prompt_path"] or ""),
            entity={"type": "agent_job", "id": str(row["id"])},
        )
        output_path = str(row["output_path"] or "")
        if output_path:
            _validate_local_artifact_path(
                paths,
                result,
                owner=f"Agent job {row['id']}",
                field_name="output_path",
                path_value=output_path,
                entity={"type": "agent_job", "id": str(row["id"])},
            )


def _validate_local_artifact_path(
    paths: ProjectPaths,
    result: ValidationResult,
    *,
    owner: str,
    field_name: str,
    path_value: str,
    entity: dict[str, str],
) -> None:
    normalized = path_value.strip()
    if not normalized:
        result.add_error(
            f"{owner} {field_name} is empty.",
            code="artifact_path_empty",
            entity=entity,
            repair_class="unsupported",
        )
        return
    if _is_virtual_or_external_path(normalized):
        return
    path = Path(normalized)
    absolute_path = path if path.is_absolute() else paths.root / path
    if not absolute_path.exists():
        result.add_error(
            f"{owner} {field_name} does not exist: {normalized}.",
            code="artifact_missing",
            entity=entity,
            repair_class="inspect",
            suggested_commands=_artifact_inspection_commands(entity),
        )
    elif not absolute_path.is_file():
        result.add_error(
            f"{owner} {field_name} is not a file: {normalized}.",
            code="artifact_not_file",
            entity=entity,
            repair_class="inspect",
            suggested_commands=_artifact_inspection_commands(entity),
        )


def _artifact_inspection_commands(entity: dict[str, str]) -> list[str]:
    command = {
        "evidence": ("evidence", "show", entity["id"]),
        "agent_job": ("jobs", "read", entity["id"]),
    }.get(entity["type"])
    if command is None:
        return []
    return [_pcl_json_command(*command)]


def _absolute_local_path(paths: ProjectPaths, path_value: str) -> Path | None:
    normalized = path_value.strip()
    if not normalized or _is_virtual_or_external_path(normalized):
        return None
    path = Path(normalized)
    return path if path.is_absolute() else paths.root / path


def _is_virtual_or_external_path(value: str) -> bool:
    if value.startswith("inline:"):
        return True
    if ":" not in value:
        return False
    scheme = value.split(":", 1)[0]
    return (
        bool(scheme)
        and scheme[0].isalpha()
        and all(char.isalnum() or char in {"+", "-", "."} for char in scheme)
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
            f"Agent job {row['id']} references missing agent {row['assigned_agent_id']}.",
            code="relationship_job_agent_missing",
            entity={"type": "agent_job", "id": str(row["id"])},
            related=[{"type": "agent", "id": str(row["assigned_agent_id"])}],
            repair_class="unsupported",
            requires_human=True,
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
            "run `pcl jobs reap`.",
            code="agent_lease_expired",
            entity={"type": "agent_job", "id": str(row["id"])},
            related=[{"type": "agent", "id": str(row["assigned_agent_id"])}],
            repair_class="structural",
            suggested_commands=[_pcl_json_command("jobs", "reap")],
        )


def _validate_retired_agent_active_leases(
    conn: sqlite3.Connection, result: ValidationResult
) -> None:
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
            f"Retired agent {row['agent_id']} holds active lease for job {row['job_id']}.",
            code="agent_retired_active_lease",
            entity={"type": "agent", "id": str(row["agent_id"])},
            related=[{"type": "agent_job", "id": str(row["job_id"])}],
            repair_class="human_review",
            requires_human=True,
            suggested_commands=[_pcl_json_command("jobs", "read", str(row["job_id"]))],
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
            f"exceeding max_concurrency {row['max_concurrency']}.",
            code="agent_concurrency_exceeded",
            entity={"type": "agent", "id": str(row["id"])},
            repair_class="inspect",
            suggested_commands=[_pcl_json_command("agent", "list")],
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
                f"Task {row['id']} references missing {label} {row[column]} via {column}.",
                code=f"relationship_task_{label}_missing",
                entity={"type": "task", "id": str(row["id"])},
                related=[{"type": label, "id": str(row[column])}],
                repair_class="unsupported",
                requires_human=True,
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
            result.add_error(
                f"Task dependency references missing {label} {row[column]}.",
                code=f"relationship_task_dependency_{column}_missing",
                entity={"type": "task_dependency", "id": str(row[column])},
                repair_class="unsupported",
                requires_human=True,
            )


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
        result.add_error(
            f"Task dependency cycle detected: {' -> '.join(cycle)}.",
            code="task_dependency_cycle",
            entity={"type": "task", "id": cycle[0]},
            related=[{"type": "task", "id": item} for item in cycle[1:]],
            repair_class="human_review",
            requires_human=True,
            suggested_commands=[_pcl_json_command("task", "read", cycle[0])],
        )


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
            f"{row['dependency_id']} ({row['dependency_status']}).",
            code="task_done_dependency_incomplete",
            entity={"type": "task", "id": str(row["task_id"])},
            related=[
                {
                    "type": "task",
                    "id": str(row["dependency_id"]),
                    "status": str(row["dependency_status"]),
                }
            ],
            repair_class="human_review",
            requires_human=True,
            suggested_commands=[
                _pcl_json_command("task", "read", str(row["task_id"])),
                _pcl_json_command("task", "read", str(row["dependency_id"])),
            ],
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
        result.add_error(
            f"Defect {defect_id} is {status} but has no {event_type} event.",
            code="defect_transition_event_missing",
            entity={"type": "defect", "id": defect_id},
            related=[{"type": "event_type", "id": event_type}],
            repair_class="unsupported",
            requires_human=True,
        )
        return

    evidence_ids: list[str] = []
    for row in rows:
        payload = _json_object(row["payload_json"])
        evidence_id = payload.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id:
            evidence_ids.append(evidence_id)
    if not evidence_ids:
        result.add_error(
            f"Defect {defect_id} {event_type} event has no evidence_id.",
            code="defect_transition_event_evidence_missing",
            entity={"type": "defect", "id": defect_id},
            related=[{"type": "event_type", "id": event_type}],
            repair_class="semantic",
            requires_human=True,
        )
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
        f"{event_type} event ({', '.join(mismatches)}).",
        code="defect_transition_evidence_invalid",
        entity={"type": "defect", "id": defect_id},
        related=[{"type": "evidence", "id": item.split("=", 1)[0]} for item in mismatches],
        repair_class="semantic",
        requires_human=True,
    )


def _validate_test_case_transition_evidence(
    conn: sqlite3.Connection,
    result: ValidationResult,
    *,
    test_case_id: str,
    status: str,
    event_type: str,
    evidence_type: str,
    alternative_types: set[str] | None = None,
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
        result.add_error(
            f"Test case {test_case_id} is {status} but has no {event_type} event.",
            code="test_transition_event_missing",
            entity={"type": "test_case", "id": test_case_id},
            related=[{"type": "event_type", "id": event_type}],
            repair_class="unsupported",
            requires_human=True,
            suggested_commands=[_pcl_json_command("test", "read", test_case_id)],
        )
        return

    evidence_ids: list[str] = []
    for row in rows:
        payload = _json_object(row["payload_json"])
        evidence_id = payload.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id:
            evidence_ids.append(evidence_id)
    if not evidence_ids:
        result.add_error(
            f"Test case {test_case_id} {event_type} event has no evidence_id.",
            code="test_transition_event_evidence_missing",
            entity={"type": "test_case", "id": test_case_id},
            related=[{"type": "event_type", "id": event_type}],
            repair_class="semantic",
            requires_human=True,
            suggested_commands=[_pcl_json_command("test", "read", test_case_id)],
        )
        return

    mismatches: list[str] = []
    for evidence_id in sorted(set(evidence_ids)):
        actual_type = _evidence_type(conn, evidence_id)
        if actual_type == evidence_type or actual_type in (alternative_types or set()):
            return
        if actual_type is None:
            mismatches.append(f"{evidence_id}=missing")
        else:
            mismatches.append(f"{evidence_id}={actual_type}")
    result.add_error(
        f"Test case {test_case_id} is {status} but no {evidence_type} evidence is linked from "
        f"{event_type} event ({', '.join(mismatches)}).",
        code="test_transition_evidence_invalid",
        entity={"type": "test_case", "id": test_case_id},
        related=[{"type": "evidence", "id": item.split("=", 1)[0]} for item in mismatches],
        repair_class="semantic",
        requires_human=True,
        suggested_commands=[_pcl_json_command("test", "read", test_case_id)],
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


def _workflow_run_created_for_defect(
    conn: sqlite3.Connection, workflow_run_id: str, defect_id: str
) -> bool:
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
