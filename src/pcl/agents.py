from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shlex import quote
from typing import Any

from .db import connect
from .errors import InvalidInputError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso
from .workflows import read_job


@dataclass(frozen=True)
class AgentCommand:
    contract_version: str
    adapter: str
    job_id: str
    prompt_path: str
    output_path: str
    ingest_command: str
    expected_output_format: str
    instructions: str
    command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "adapter": self.adapter,
            "job_id": self.job_id,
            "prompt_path": self.prompt_path,
            "output_path": self.output_path,
            "ingest_command": self.ingest_command,
            "expected_output_format": self.expected_output_format,
            "instructions": self.instructions,
            "command": self.command,
        }


class AgentAdapter:
    name = "manual"

    def generate_command(self, paths: ProjectPaths, job: dict[str, Any]) -> AgentCommand:
        raise NotImplementedError


class ManualAdapter(AgentAdapter):
    name = "manual"

    def generate_command(self, paths: ProjectPaths, job: dict[str, Any]) -> AgentCommand:
        prompt_path = str(job["prompt_path"])
        output_path = _default_output_path(job)
        ingest_command = _ingest_command(output_path)
        instructions = (
            f"Read {prompt_path}, run the requested agent work manually, write the result to "
            f"{output_path}, then run `{ingest_command}`."
        )
        return AgentCommand(
            contract_version=CONTRACT_VERSION,
            adapter=self.name,
            job_id=str(job["id"]),
            prompt_path=prompt_path,
            output_path=output_path,
            ingest_command=ingest_command,
            expected_output_format=EXPECTED_OUTPUT_FORMAT,
            instructions=instructions,
        )


class CodexExecAdapter(AgentAdapter):
    name = "codex_exec"

    def generate_command(self, paths: ProjectPaths, job: dict[str, Any]) -> AgentCommand:
        prompt_path = str(job["prompt_path"])
        output_path = _default_output_path(job)
        ingest_command = _ingest_command(output_path, root=paths.root)
        command = _codex_exec_command(
            paths=paths,
            prompt_path=prompt_path,
            output_path=output_path,
            ingest_command=ingest_command,
        )
        return AgentCommand(
            contract_version=CONTRACT_VERSION,
            adapter=self.name,
            job_id=str(job["id"]),
            prompt_path=prompt_path,
            output_path=output_path,
            ingest_command=ingest_command,
            expected_output_format=EXPECTED_OUTPUT_FORMAT,
            instructions=(
                "Run this command locally only when you intentionally want Codex CLI to execute "
                "the queued prompt. The command reads the prompt from stdin, writes the final "
                "message to the expected output path, then ingests it. pcl does not call it "
                "automatically and does not manage Codex CLI credentials."
            ),
            command=command,
        )


class ClaudeManualAdapter(AgentAdapter):
    name = "claude_manual"

    def generate_command(self, paths: ProjectPaths, job: dict[str, Any]) -> AgentCommand:
        prompt_path = str(job["prompt_path"])
        output_path = _default_output_path(job)
        ingest_command = _ingest_command(output_path)
        instructions = _claude_manual_instructions(
            prompt_path=prompt_path,
            output_path=output_path,
            ingest_command=ingest_command,
        )
        return AgentCommand(
            contract_version=CONTRACT_VERSION,
            adapter=self.name,
            job_id=str(job["id"]),
            prompt_path=prompt_path,
            output_path=output_path,
            ingest_command=ingest_command,
            expected_output_format=EXPECTED_OUTPUT_FORMAT,
            instructions=instructions,
        )


class GenericShellAdapter(AgentAdapter):
    name = "generic_shell"

    def generate_command(self, paths: ProjectPaths, job: dict[str, Any]) -> AgentCommand:
        prompt_path = str(job["prompt_path"])
        output_path = _default_output_path(job)
        ingest_command = _ingest_command(output_path, root=paths.root)
        command = _generic_shell_command(
            paths=paths,
            prompt_path=prompt_path,
            output_path=output_path,
            ingest_command=ingest_command,
        )
        instructions = _generic_shell_instructions(
            prompt_path=prompt_path,
            output_path=output_path,
            ingest_command=ingest_command,
        )
        return AgentCommand(
            contract_version=CONTRACT_VERSION,
            adapter=self.name,
            job_id=str(job["id"]),
            prompt_path=prompt_path,
            output_path=output_path,
            ingest_command=ingest_command,
            expected_output_format=EXPECTED_OUTPUT_FORMAT,
            instructions=instructions,
            command=command,
        )


CONTRACT_VERSION = "agent-adapter-command/v1"
OUTPUT_CONTRACT_VERSION = "agent-output/v1"
REQUIRED_OUTPUT_HEADINGS = ("## Findings", "## Evidence")
EXPECTED_OUTPUT_FORMAT = (
    "Markdown report matching agent-output/v1. First non-empty line must be an H1 summary; "
    "include required headings: ## Findings and ## Evidence. Recommended pcl commands are optional."
)

ADAPTERS: dict[str, AgentAdapter] = {
    "manual": ManualAdapter(),
    "codex_exec": CodexExecAdapter(),
    "claude_manual": ClaudeManualAdapter(),
    "generic_shell": GenericShellAdapter(),
}


def generate_agent_command(paths: ProjectPaths, job_id: str, adapter_name: str) -> AgentCommand:
    require_initialized(paths)
    job = read_job(paths, job_id)
    try:
        adapter = ADAPTERS[adapter_name]
    except KeyError as exc:
        raise InvalidInputError(
            f"Unknown agent adapter: {adapter_name}",
            details={"adapter": adapter_name, "available": sorted(ADAPTERS)},
        ) from exc
    return adapter.generate_command(paths, job)


def read_job_prompt(paths: ProjectPaths, job_id: str) -> str:
    job = read_job(paths, job_id)
    return str(job.get("prompt") or "")


def read_job_prompt_handoff(paths: ProjectPaths, job_id: str) -> dict[str, Any]:
    job = read_job(paths, job_id)
    output_path = _default_output_path(job)
    return {
        "ok": True,
        "job_id": str(job["id"]),
        "workflow_run_id": str(job["workflow_run_id"]),
        "workflow_id": str(job["workflow_id"]),
        "role": str(job["role"]),
        "status": str(job["status"]),
        "prompt_path": str(job["prompt_path"]),
        "output_path": output_path,
        "ingest_command": _ingest_command(output_path),
        "expected_output_format": EXPECTED_OUTPUT_FORMAT,
        "prompt": str(job.get("prompt") or ""),
    }


def ingest_agent_run(paths: ProjectPaths, output_path: str | Path) -> dict[str, Any]:
    require_initialized(paths)
    path = _resolve_output_path(paths, output_path)
    if not path.exists() or not path.is_file():
        raise InvalidInputError(
            f"Agent output file does not exist: {output_path}",
            details={"path": str(output_path)},
        )
    job_id = _infer_job_id(paths, path)
    relative_path = _relative_or_absolute(paths, path)

    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT
              agent_jobs.id,
              agent_jobs.workflow_run_id,
              agent_jobs.status AS job_status,
              workflow_runs.status AS run_status
            FROM agent_jobs
            JOIN workflow_runs ON workflow_runs.id = agent_jobs.workflow_run_id
            WHERE agent_jobs.id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise InvalidInputError(f"Agent job does not exist: {job_id}", details={"job_id": job_id})
        _require_ingest_allowed(
            job_id=job_id,
            job_status=str(row["job_status"]),
            workflow_run_id=str(row["workflow_run_id"]),
            run_status=str(row["run_status"]),
        )

        validation = _validate_output_contract(path=path, display_path=relative_path)
        summary = str(validation["summary"])
        now = utc_now_iso()

        evidence_id = next_prefixed_id(conn, "evidence", "E")
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (evidence_id, "agent_output", relative_path, None, summary, now),
        )
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = ?, output_path = ?, ended_at = ?, summary = ?
            WHERE id = ?
            """,
            ("passed", relative_path, now, summary, job_id),
        )
        conn.execute(
            """
            UPDATE workflow_runs
            SET status = CASE WHEN status = 'queued' THEN 'running' ELSE status END
            WHERE id = ?
            """,
            (row["workflow_run_id"],),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="agent_output_ingested",
            entity_type="agent_job",
            entity_id=job_id,
            payload={
                "contract_version": OUTPUT_CONTRACT_VERSION,
                "workflow_run_id": row["workflow_run_id"],
                "evidence_id": evidence_id,
                "output_path": relative_path,
                "summary": summary,
                "validation": validation,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "contract_version": OUTPUT_CONTRACT_VERSION,
            "job_id": job_id,
            "workflow_run_id": row["workflow_run_id"],
            "evidence_id": evidence_id,
            "output_path": relative_path,
            "summary": summary,
            "status": "passed",
            "validation": validation,
        }
    finally:
        conn.close()


def _default_output_path(job: dict[str, Any]) -> str:
    prompt_path = Path(str(job["prompt_path"]))
    return str(prompt_path.parent / "output.md")


def _ingest_command(output_path: str, *, root: Path | None = None) -> str:
    command = f"pcl ingest-agent-run {quote(output_path)}"
    if root is not None:
        command += f" --root {quote(str(root))}"
    return command


def _codex_exec_command(
    *,
    paths: ProjectPaths,
    prompt_path: str,
    output_path: str,
    ingest_command: str,
) -> str:
    absolute_prompt = paths.root / prompt_path
    absolute_output = paths.root / output_path
    script = "\n".join(
        [
            "set -euo pipefail",
            f"mkdir -p {quote(str(absolute_output.parent))}",
            (
                "codex exec "
                f"--cd {quote(str(paths.root))} "
                f"--output-last-message {quote(str(absolute_output))} "
                f"- < {quote(str(absolute_prompt))}"
            ),
            ingest_command,
        ]
    )
    return f"bash -lc {quote(script)}"


def _generic_shell_command(
    *,
    paths: ProjectPaths,
    prompt_path: str,
    output_path: str,
    ingest_command: str,
) -> str:
    absolute_prompt = paths.root / prompt_path
    absolute_output = paths.root / output_path
    script = "\n".join(
        [
            "set -euo pipefail",
            f"mkdir -p {quote(str(absolute_output.parent))}",
            (
                ': "${PCL_AGENT_COMMAND:?Set PCL_AGENT_COMMAND to a shell command that '
                'reads the prompt from stdin and writes agent-output/v1 Markdown to stdout.}"'
            ),
            f"sh -c \"$PCL_AGENT_COMMAND\" < {quote(str(absolute_prompt))} > {quote(str(absolute_output))}",
            f"test -s {quote(str(absolute_output))}",
            ingest_command,
        ]
    )
    return f"bash -lc {quote(script)}"


def _claude_manual_instructions(*, prompt_path: str, output_path: str, ingest_command: str) -> str:
    return "\n".join(
        [
            "Claude Code manual handoff:",
            f"1. Open or reference the full prompt at `{prompt_path}` in Claude Code.",
            "2. Ask Claude Code to return an `agent-output/v1` Markdown report.",
            f"3. Save Claude Code's final response exactly to `{output_path}`.",
            f"4. Run `{ingest_command}` from the project root.",
            "",
            "Required output shape:",
            "- first non-empty line: `# Short result summary`",
            "- required heading: `## Findings`",
            "- required heading: `## Evidence`",
            "- recommended commands, if any, must be `pcl` commands instead of direct SQLite edits.",
            "",
            "Boundary:",
            "- `pcl` does not execute Claude Code automatically.",
            "- Do not edit `.project-loop/project.db` directly.",
            "- Do not read or parse generated dashboard HTML as project state.",
            "- Use `pcl` JSON commands, reports, evidence paths, or `dashboard-data.json` for machine context.",
            "- Do not edit generated dashboard HTML directly.",
        ]
    )


def _generic_shell_instructions(*, prompt_path: str, output_path: str, ingest_command: str) -> str:
    return "\n".join(
        [
            "Generic shell adapter handoff:",
            "1. Set `PCL_AGENT_COMMAND` to a shell command that reads the prompt from stdin.",
            f"2. The generated wrapper passes `{prompt_path}` to that command through stdin.",
            "3. The command must write an `agent-output/v1` Markdown report to stdout.",
            f"4. The wrapper saves stdout to `{output_path}` and then runs `{ingest_command}`.",
            "",
            "Required output shape:",
            "- first non-empty line: `# Short result summary`",
            "- required heading: `## Findings`",
            "- required heading: `## Evidence`",
            "- recommended commands, if any, must be `pcl` commands instead of direct SQLite edits.",
            "",
            "Boundary:",
            "- `pcl` only prints this wrapper; it does not execute the shell command automatically.",
            "- Do not edit `.project-loop/project.db` directly.",
            "- Do not read or parse generated dashboard HTML as project state.",
            "- Use `pcl` JSON commands, reports, evidence paths, or `dashboard-data.json` for machine context.",
            "- Do not edit generated dashboard HTML directly.",
        ]
    )


def _resolve_output_path(paths: ProjectPaths, output_path: str | Path) -> Path:
    path = Path(output_path)
    if not path.is_absolute():
        path = paths.root / path
    return path.resolve()


def _infer_job_id(paths: ProjectPaths, path: Path) -> str:
    agent_runs_dir = (paths.evidence_dir / "agent-runs").resolve()
    try:
        relative = path.relative_to(agent_runs_dir)
    except ValueError as exc:
        raise InvalidInputError(
            "Cannot infer agent job id from output path. Expected path under "
            ".project-loop/evidence/agent-runs/<job_id>/output.md.",
            details={"path": _relative_or_absolute(paths, path)},
        ) from exc
    if len(relative.parts) != 2 or relative.parts[1] != "output.md":
        raise InvalidInputError(
            "Cannot infer agent job id from output path. Expected path under "
            ".project-loop/evidence/agent-runs/<job_id>/output.md.",
            details={"path": _relative_or_absolute(paths, path)},
        )
    return relative.parts[0]


def _require_ingest_allowed(
    *,
    job_id: str,
    job_status: str,
    workflow_run_id: str,
    run_status: str,
) -> None:
    if job_status in {"cancelled", "failed"}:
        raise InvalidInputError(
            f"Agent job {job_id} cannot ingest output while status is {job_status}.",
            details={"job_id": job_id, "status": job_status},
        )
    if run_status not in {"queued", "running", "blocked"}:
        raise InvalidInputError(
            f"Workflow run {workflow_run_id} cannot ingest agent output while status is {run_status}.",
            details={"workflow_run_id": workflow_run_id, "status": run_status, "job_id": job_id},
        )


def _relative_or_absolute(paths: ProjectPaths, path: Path) -> str:
    try:
        return str(path.relative_to(paths.root))
    except ValueError:
        return str(path)


def _validate_output_contract(*, path: Path, display_path: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    lines = [line.strip() for line in text.splitlines()]
    non_empty = [line for line in lines if line]
    errors: list[str] = []
    summary = ""

    if not non_empty:
        errors.append("Agent output is empty.")
    else:
        summary = non_empty[0][:200]
        if not non_empty[0].startswith("# "):
            errors.append("First non-empty line must be a Markdown H1 summary starting with '# '.")

    line_set = set(lines)
    for heading in REQUIRED_OUTPUT_HEADINGS:
        if heading not in line_set:
            errors.append(f"Missing required heading: {heading}.")

    validation = {
        "ok": not errors,
        "contract_version": OUTPUT_CONTRACT_VERSION,
        "required_headings": list(REQUIRED_OUTPUT_HEADINGS),
        "summary": summary,
    }
    if errors:
        validation["errors"] = errors
        raise InvalidInputError(
            "Agent output does not satisfy contract.",
            details={
                "path": display_path,
                "contract_version": OUTPUT_CONTRACT_VERSION,
                "errors": errors,
            },
        )
    return validation
