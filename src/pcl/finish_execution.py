from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from typing import Any

from . import __version__
from .commands import finish_plan
from .contracts.completion_packet import (
    COMPLETION_PACKET_CONTRACT_VERSION,
    canonical_json,
    validate_completion_packet,
    with_computed_packet_id,
)
from .db import connect, connect_mutation
from .errors import DataStoreError, InvalidInputError
from .events import append_event
from .evidence import insert_evidence_link
from .guarded_process import DEFAULT_MAX_OUTPUT_BYTES
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso
from .validators import validate_project
from .workflow_sandbox import execute_planned_guarded_command, plan_guarded_project_checks


COMPLETION_PACKET_EVIDENCE_TYPE = "completion_packet"
COMPLETION_CHECK_EVIDENCE_TYPE = "completion_check"
COMPLETION_PACKET_LINK_ROLE = "completion_packet"
COMPLETION_CHECK_LINK_ROLE = "verification_check"


def plan_finish_packet(
    paths: ProjectPaths,
    *,
    run_id: str | None = None,
    goal_id: str | None = None,
    task_id: str | None = None,
    base_revision: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    target = _resolve_target(paths, run_id=run_id, goal_id=goal_id, task_id=task_id)
    repository = _repository_snapshot(paths, base_revision=base_revision)
    commands = plan_guarded_project_checks(paths)
    return {
        "mode": "emit_packet",
        "dry_run": True,
        "target": target,
        "repository": repository["packet_repository"],
        "changes": repository["changes"],
        "check_plan": [_public_check_plan(command) for command in commands],
        "safe_to_execute": bool(commands) and all(command["safe_to_run"] for command in commands),
        "blocked_checks": [
            _public_check_plan(command) for command in commands if not command["safe_to_run"]
        ],
    }


def emit_finish_packet(
    paths: ProjectPaths,
    *,
    run_id: str | None = None,
    goal_id: str | None = None,
    task_id: str | None = None,
    base_revision: str | None = None,
    timeout_seconds: int = 120,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> dict[str, Any]:
    if timeout_seconds < 1:
        raise InvalidInputError("--timeout must be at least 1 second.")
    if max_output_bytes < 1:
        raise InvalidInputError("--max-output-bytes must be at least 1.")
    plan = plan_finish_packet(
        paths,
        run_id=run_id,
        goal_id=goal_id,
        task_id=task_id,
        base_revision=base_revision,
    )
    target = plan["target"]
    existing = _matching_completion_packet(paths, target=target, repository=plan["repository"])
    if (
        existing is not None
        and existing["outcome"] in {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"}
        and _target_is_terminal(paths, target)
    ):
        return {
            **plan,
            "dry_run": False,
            "changed": False,
            "idempotent": True,
            "packet": existing,
            "checks": [],
            "exit_code": 0,
        }

    commands = plan_guarded_project_checks(paths)
    if not commands:
        raise InvalidInputError(
            "No finish checks are configured.",
            details={"configured_keys": [], "required_any_of": ["lint", "typecheck", "test", "e2e", "build"]},
        )
    blocked = [command for command in commands if not command["safe_to_run"]]
    if blocked:
        raise InvalidInputError(
            "A configured finish check is not guarded-executor allowlisted.",
            details={"blocked_checks": [_public_check_plan(command) for command in blocked]},
        )

    stage_dir = _stage_check_dir(paths)
    try:
        for command in commands:
            execute_planned_guarded_command(
                paths,
                command,
                run_dir=stage_dir,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            )
        after = _repository_snapshot(paths, base_revision=plan["repository"]["base_revision"])
        race_detected = _snapshot_identity(plan) != _snapshot_identity(after)
        strict = validate_project(paths, strict=True)
        blockers = _target_blockers(paths, target)
        outcome = _completion_outcome(
            changes=after["changes"],
            commands=commands,
            strict_ok=strict.ok,
            strict_warnings=list(strict.warnings),
            race_detected=race_detected,
            blockers=blockers,
        )
        committed = _commit_completion_packet(
            paths,
            target=target,
            repository=after,
            commands=commands,
            stage_dir=stage_dir,
            strict_errors=list(strict.errors),
            strict_warnings=list(strict.warnings),
            race_detected=race_detected,
            blockers=blockers,
            outcome=outcome,
        )
    finally:
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
    return {
        **plan,
        "dry_run": False,
        "repository": after["packet_repository"],
        "changes": after["changes"],
        "changed": True,
        "idempotent": False,
        "race_detected": race_detected,
        "strict_validation": {
            "ok": strict.ok,
            "errors": list(strict.errors),
            "warnings": list(strict.warnings),
        },
        "checks": committed["checks"],
        "packet": committed["packet"],
        "target_transition": committed["target_transition"],
        "exit_code": 1 if outcome == "INCOMPLETE_VALIDATION" else 0,
    }


def _resolve_target(
    paths: ProjectPaths,
    *,
    run_id: str | None,
    goal_id: str | None,
    task_id: str | None,
) -> dict[str, Any]:
    explicit = [value for value in (run_id, goal_id, task_id) if value]
    if len(explicit) > 1:
        raise InvalidInputError("Choose only one of --run, --goal, or --task.")
    conn = connect(paths.db_path)
    try:
        if task_id:
            return _task_target(conn, task_id)
        planner = finish_plan(paths, run_id=run_id, goal_id=goal_id)
        selected_goal = planner["target"]["goal"]
        if selected_goal:
            return _goal_target(conn, str(selected_goal), planner=planner)
        if run_id:
            raise InvalidInputError(
                f"Workflow run {run_id} is not linked to a goal that completion-packet/v1 can target.",
                details={"workflow_run_id": run_id},
            )
        row = conn.execute(
            """
            SELECT id FROM tasks
            WHERE status IN ('in_progress', 'ready', 'todo')
            ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'ready' THEN 1 ELSE 2 END,
                     priority, id
            LIMIT 1
            """
        ).fetchone()
        if row is not None:
            return _task_target(conn, str(row["id"]))
    finally:
        conn.close()
    raise InvalidInputError(
        "No active goal or task is available for completion packet emission.",
        details={"run": run_id, "goal": goal_id, "task": task_id},
    )


def _task_target(conn: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, title, description, status, related_goal_id FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(f"Task does not exist: {task_id}", details={"task_id": task_id})
    return {
        "type": "task",
        "id": str(row["id"]),
        "intent": str(row["description"] or row["title"]),
        "status": str(row["status"]),
        "goal_id": row["related_goal_id"],
        "work_brief_ref": None,
        "finish_plan": None,
    }


def _goal_target(conn: sqlite3.Connection, goal_id: str, *, planner: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT id, title, status FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if row is None:
        raise InvalidInputError(f"Goal does not exist: {goal_id}", details={"goal_id": goal_id})
    return {
        "type": "goal",
        "id": str(row["id"]),
        "intent": str(row["title"]),
        "status": str(row["status"]),
        "goal_id": str(row["id"]),
        "work_brief_ref": None,
        "finish_plan": planner,
    }


def _repository_snapshot(paths: ProjectPaths, *, base_revision: str | None) -> dict[str, Any]:
    root = paths.root
    head = _git(root, ["rev-parse", "HEAD"]).strip()
    base = _git(root, ["rev-parse", base_revision or "HEAD"]).strip()
    tracked_diff = _git_bytes(root, ["diff", "--binary", "--no-ext-diff", base, "--"])
    untracked = [
        line for line in _git(root, ["ls-files", "--others", "--exclude-standard", "-z"]).split("\0") if line
    ]
    untracked_bytes = bytearray()
    for path_value in sorted(untracked):
        try:
            data = (root / path_value).read_bytes()
        except OSError as exc:
            raise InvalidInputError(
                "Repository changed while the Git snapshot was being captured.",
                details={"path": path_value, "reason": str(exc)},
            ) from exc
        name = path_value.encode("utf-8", errors="surrogateescape")
        untracked_bytes.extend(b"\0PCL-UNTRACKED\0" + str(len(name)).encode() + b":" + name)
        untracked_bytes.extend(b"\0" + str(len(data)).encode() + b":" + data)
    diff_bytes = tracked_diff + bytes(untracked_bytes)
    changes = _changed_paths(root, base=base, untracked=untracked)
    status = _git(root, ["status", "--porcelain=v1", "-z"])
    return {
        "packet_repository": {
            "base_revision": base,
            "head_revision": head,
            "diff_sha256": f"sha256:{hashlib.sha256(diff_bytes).hexdigest()}",
            "dirty": bool(status),
        },
        "changes": changes,
        "status": status,
    }


def _changed_paths(root: Path, *, base: str, untracked: list[str]) -> list[dict[str, Any]]:
    output = _git(root, ["diff", "--name-status", "--find-renames", base, "--"])
    changes: list[dict[str, Any]] = []
    mapping = {"A": "added", "M": "modified", "D": "deleted"}
    for line in output.splitlines():
        parts = line.split("\t")
        code = parts[0][0]
        if code == "R" and len(parts) == 3:
            changes.append({"path": parts[2], "change_type": "renamed", "previous_path": parts[1]})
        elif code in mapping and len(parts) >= 2:
            changes.append({"path": parts[-1], "change_type": mapping[code], "previous_path": None})
    changes.extend(
        {"path": path_value, "change_type": "untracked", "previous_path": None}
        for path_value in sorted(untracked)
    )
    return sorted(changes, key=lambda item: (item["path"], item["change_type"]))


def _git(root: Path, args: list[str]) -> str:
    return _git_bytes(root, args).decode("utf-8", errors="surrogateescape")


def _git_bytes(root: Path, args: list[str]) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, shell=False
    )
    if result.returncode != 0:
        raise InvalidInputError(
            "Could not resolve the Git repository snapshot.",
            details={"argv": ["git", *args], "exit_code": result.returncode, "stderr": result.stderr.decode(errors="replace")},
        )
    return result.stdout


def _target_blockers(paths: ProjectPaths, target: dict[str, Any]) -> dict[str, Any]:
    conn = connect(paths.db_path)
    try:
        decisions = []
        for row in conn.execute(
            "SELECT id, question, blocks_json FROM decisions WHERE status = 'open' ORDER BY id"
        ).fetchall():
            try:
                blocks = json.loads(str(row["blocks_json"] or "[]"))
            except json.JSONDecodeError:
                blocks = []
            if any(
                isinstance(item, dict)
                and item.get("type") == target["type"]
                and item.get("id") == target["id"]
                for item in blocks
            ):
                decisions.append({"id": str(row["id"]), "question": str(row["question"])})
        budget_exhausted = False
        goal_id = target.get("goal_id")
        if goal_id:
            row = conn.execute("SELECT budget_json FROM goals WHERE id = ?", (goal_id,)).fetchone()
            if row is not None:
                try:
                    budget = json.loads(str(row["budget_json"] or "{}"))
                except json.JSONDecodeError:
                    budget = {}
                budget_exhausted = budget.get("exhausted") is True
    finally:
        conn.close()
    planner = target.get("finish_plan") or {}
    human_steps = [step for step in planner.get("remaining_steps", []) if step.get("requires_human")]
    return {"decisions": decisions, "human_steps": human_steps, "budget_exhausted": budget_exhausted}


def _completion_outcome(
    *, changes: list[dict[str, Any]], commands: list[dict[str, Any]], strict_ok: bool,
    strict_warnings: list[str],
    race_detected: bool, blockers: dict[str, Any],
) -> str:
    if blockers["budget_exhausted"]:
        return "INCOMPLETE_BUDGET_EXHAUSTED"
    if blockers["decisions"] or blockers["human_steps"]:
        return "INCOMPLETE_HUMAN_DECISION_REQUIRED"
    if race_detected or not strict_ok or any(command["status"] != "passed" for command in commands):
        return "INCOMPLETE_VALIDATION"
    if not changes:
        return "NO_CHANGES"
    return "COMPLETED_WITH_RISK" if strict_warnings else "COMPLETED_VERIFIED"


def _commit_completion_packet(
    paths: ProjectPaths, *, target: dict[str, Any], repository: dict[str, Any],
    commands: list[dict[str, Any]], stage_dir: Path, strict_errors: list[str],
    strict_warnings: list[str], race_detected: bool, blockers: dict[str, Any], outcome: str,
) -> dict[str, Any]:
    conn = connect_mutation(paths)
    now = utc_now_iso().replace("+00:00", "Z")
    try:
        check_rows = []
        for command in commands:
            evidence_id = next_prefixed_id(conn, "evidence", "E")
            final_dir = paths.evidence_dir / "completion-checks" / evidence_id
            final_dir.mkdir(parents=True, exist_ok=False)
            for key in ("stdout_path", "stderr_path"):
                source = paths.root / str(command[key])
                destination = final_dir / source.name
                source.replace(destination)
                command[key] = str(destination.relative_to(paths.root))
                if isinstance(command.get(key.removesuffix("_path")), dict):
                    command[key.removesuffix("_path")]["path"] = command[key]
            result_path = final_dir / "result.json"
            check_payload = _check_result(command, evidence_id=evidence_id)
            result_path.write_text(json.dumps(check_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            relative = str(result_path.relative_to(paths.root))
            conn.execute(
                "INSERT INTO evidence(id, type, path, command, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (evidence_id, COMPLETION_CHECK_EVIDENCE_TYPE, relative, command["resolved_command"], f"Finish check {command['status']}: {command['resolved_command']}", now),
            )
            insert_evidence_link(conn, evidence_id=evidence_id, target_type=target["type"], target_id=target["id"], link_role=COMPLETION_CHECK_LINK_ROLE, created_at=now)
            check_rows.append(check_payload)

        packet = _build_packet(
            target=target, repository=repository, check_rows=check_rows, outcome=outcome,
            strict_errors=strict_errors, strict_warnings=strict_warnings,
            race_detected=race_detected, blockers=blockers, generated_at=now,
        )
        validation = validate_completion_packet(packet)
        if not validation.ok:
            raise DataStoreError("Generated completion packet failed validation.", details={"errors": list(validation.errors)})
        packet_hash = packet["packet_id"].removeprefix("cp-sha256:")
        packet_path = paths.evidence_dir / "completion-packets" / f"{packet_hash}.json"
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        if not packet_path.exists():
            packet_path.write_text(canonical_json(packet) + "\n", encoding="utf-8")
        packet_evidence_id = next_prefixed_id(conn, "evidence", "E")
        relative_packet_path = str(packet_path.relative_to(paths.root))
        conn.execute(
            "INSERT INTO evidence(id, type, path, command, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (packet_evidence_id, COMPLETION_PACKET_EVIDENCE_TYPE, relative_packet_path, "pcl finish --emit-packet", f"Completion packet {outcome} for {target['type']} {target['id']}", now),
        )
        insert_evidence_link(conn, evidence_id=packet_evidence_id, target_type=target["type"], target_id=target["id"], link_role=COMPLETION_PACKET_LINK_ROLE, created_at=now)
        transition = _apply_terminal_transition(conn, paths, target=target, outcome=outcome, packet_evidence_id=packet_evidence_id, now=now)
        append_event(
            conn=conn, events_path=paths.events_path, event_type="completion_packet_created",
            entity_type=target["type"], entity_id=target["id"],
            payload={
                "contract_version": COMPLETION_PACKET_CONTRACT_VERSION,
                "packet_id": packet["packet_id"], "evidence_id": packet_evidence_id,
                "path": relative_packet_path, "outcome": outcome,
                "diff_sha256": packet["repository"]["diff_sha256"],
                "check_evidence_ids": [row["evidence_id"] for row in check_rows],
                "target_transition": transition,
            },
        )
        conn.commit()
        return {
            "checks": check_rows,
            "packet": {"packet_id": packet["packet_id"], "evidence_id": packet_evidence_id, "path": relative_packet_path, "outcome": outcome},
            "target_transition": transition,
        }
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        raise DataStoreError(f"Could not commit completion packet: {exc}") from exc
    finally:
        conn.close()


def _build_packet(
    *, target: dict[str, Any], repository: dict[str, Any], check_rows: list[dict[str, Any]],
    outcome: str, strict_errors: list[str], strict_warnings: list[str], race_detected: bool,
    blockers: dict[str, Any], generated_at: str,
) -> dict[str, Any]:
    checks = [
        {
            "id": f"CHK-{index:04d}", "command": row["command"], "status": row["status"],
            "exit_code": row["exit_code"], "artifact_ref": f"evidence:{row['evidence_id']}",
            "reproducible": True, "reason": row["reason"],
        }
        for index, row in enumerate(check_rows, start=1)
    ]
    evidence_refs = [check["artifact_ref"] for check in checks if check["status"] == "passed"]
    completed = outcome in {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"}
    claims = ([{
        "id": "CL-0001", "text": "All configured finish checks passed for the captured repository snapshot.",
        "critical": True, "proof_level": "L2", "evidence_refs": evidence_refs,
    }] if completed else [])
    reasons = list(strict_errors)
    if race_detected:
        reasons.append("Repository changed while finish checks were running.")
    failed = [check["command"] for check in checks if check["status"] != "passed"]
    if failed:
        reasons.append("Configured checks did not pass: " + ", ".join(failed))
    human_decisions = [item["question"] for item in blockers["decisions"]]
    human_decisions.extend(str(step["reason"]) for step in blockers["human_steps"])
    next_action = _next_action(outcome, target)
    packet = {
        "contract_version": COMPLETION_PACKET_CONTRACT_VERSION,
        "packet_id": "cp-sha256:" + "0" * 64,
        "producer": {"name": "project-loop-harness", "version": __version__},
        "generated_at": generated_at,
        "outcome": outcome,
        "target": {"type": target["type"], "id": target["id"], "intent": target["intent"], "work_brief_ref": target["work_brief_ref"]},
        "repository": repository["packet_repository"], "changes": repository["changes"],
        "checks": checks, "claims": claims,
        "unverified_claims": [
            {"text": reason, "reason": "Finish did not establish a completed outcome.", "critical": False}
            for reason in reasons
        ],
        "risks": [], "human_decisions": human_decisions, "next_action": next_action,
        "verifier_provenance": {"kind": "tool", "name": "pcl finish", "version": __version__, "evidence_ref": evidence_refs[-1] if evidence_refs else None},
    }
    if strict_warnings and outcome == "COMPLETED_WITH_RISK":
        packet["risks"] = [{"severity": "low", "text": warning, "mitigation": "Review strict validation warning."} for warning in strict_warnings]
    return with_computed_packet_id(packet)


def _next_action(outcome: str, target: dict[str, Any]) -> dict[str, Any] | None:
    command = f"pcl finish --emit-packet --{target['type']} {target['id']}"
    if outcome == "INCOMPLETE_VALIDATION":
        return {"text": "Fix failed checks or repository drift, then rerun finish.", "command": command}
    if outcome == "INCOMPLETE_BUDGET_EXHAUSTED":
        return {"text": "Review and explicitly extend or close the exhausted budget.", "command": None}
    if outcome == "INCOMPLETE_HUMAN_DECISION_REQUIRED":
        return {"text": "Resolve the recorded human decision before completing the target.", "command": "pcl decision list --status open"}
    if outcome == "NO_CHANGES":
        return {"text": "Provide acceptance Evidence or make the intended repository change.", "command": command}
    return None


def _apply_terminal_transition(
    conn: sqlite3.Connection, paths: ProjectPaths, *, target: dict[str, Any], outcome: str,
    packet_evidence_id: str, now: str,
) -> dict[str, Any]:
    if outcome not in {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"} or target["type"] != "task":
        return {"changed": False, "from_status": target["status"], "to_status": target["status"]}
    if target["status"] == "done":
        return {"changed": False, "from_status": "done", "to_status": "done"}
    conn.execute("UPDATE tasks SET status = 'done', updated_at = ? WHERE id = ?", (now, target["id"]))
    append_event(
        conn=conn, events_path=paths.events_path, event_type="task_status_changed",
        entity_type="task", entity_id=target["id"],
        payload={"from_status": target["status"], "to_status": "done", "reason": "Completion packet checks passed.", "evidence_id": packet_evidence_id},
    )
    return {"changed": True, "from_status": target["status"], "to_status": "done"}


def _check_result(command: dict[str, Any], *, evidence_id: str) -> dict[str, Any]:
    timed_out = bool(command.get("timed_out"))
    status = "timed_out" if timed_out else str(command["status"])
    return {
        "evidence_id": evidence_id, "command": str(command["resolved_command"]),
        "status": status, "exit_code": command.get("exit_code"),
        "reason": "Timed out during guarded execution." if timed_out else (None if status == "passed" else "Guarded command returned a non-zero exit code."),
        "stdout_path": command.get("stdout_path"), "stderr_path": command.get("stderr_path"),
        "stdout": command.get("stdout"), "stderr": command.get("stderr"),
        "output_truncated": bool(command.get("output_truncated")), "redacted": bool(command.get("redacted")),
        "permission_contract": command.get("permission_contract"),
        "termination": command.get("termination"),
        "failure_kind": command.get("failure_kind"),
    }


def _matching_completion_packet(paths: ProjectPaths, *, target: dict[str, Any], repository: dict[str, Any]) -> dict[str, Any] | None:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT evidence.id, evidence.path FROM evidence
            JOIN evidence_links ON evidence_links.evidence_id = evidence.id
            WHERE evidence.type = ? AND evidence_links.target_type = ?
              AND evidence_links.target_id = ? AND evidence_links.link_role = ?
            ORDER BY evidence.created_at DESC, evidence.id DESC LIMIT 1
            """,
            (COMPLETION_PACKET_EVIDENCE_TYPE, target["type"], target["id"], COMPLETION_PACKET_LINK_ROLE),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    path = paths.root / str(row["path"])
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if packet.get("repository") != repository:
        return None
    return {"packet_id": packet["packet_id"], "evidence_id": str(row["id"]), "path": str(row["path"]), "outcome": packet["outcome"]}


def _target_is_terminal(paths: ProjectPaths, target: dict[str, Any]) -> bool:
    conn = connect(paths.db_path)
    try:
        table = "tasks" if target["type"] == "task" else "goals"
        row = conn.execute(f"SELECT status FROM {table} WHERE id = ?", (target["id"],)).fetchone()
    finally:
        conn.close()
    return row is not None and str(row["status"]) in {"done", "closed", "cancelled", "waived"}


def _stage_check_dir(paths: ProjectPaths) -> Path:
    tmp_dir = paths.loop_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="finish-checks-", dir=tmp_dir))


def _snapshot_identity(value: dict[str, Any]) -> tuple[Any, ...]:
    repository = value.get("repository") or value["packet_repository"]
    changes = value.get("changes", [])
    return (repository["base_revision"], repository["head_revision"], repository["diff_sha256"], repository["dirty"], json.dumps(changes, sort_keys=True))


def _public_check_plan(command: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": command["id"], "config_key": str(command["raw_command"]).removeprefix("project.commands."),
        "command": command["resolved_command"], "safe_to_run": bool(command["safe_to_run"]),
        "blocked_reason": command["blocked_reason"],
    }
