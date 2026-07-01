from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import InvalidInputError, ProjectNotInitializedError
from .paths import ProjectPaths
from .workflow_proposal_validation import PROPOSAL_ID_RE, validate_workflow_proposal_text

CONTRACT_VERSION = "workflow-verification/v1"
ALLOWED_WORKFLOW_TYPES = {"closed_loop"}
ALLOWED_AGENT_MODES = {"read_only", "workspace_write", "command"}
FORBIDDEN_KEYS = {"env", "environment", "exec", "script", "secrets", "shell", "subprocess"}
FORBIDDEN_COMMAND_FRAGMENTS = (
    ".project-loop/events.jsonl",
    ".project-loop/project.db",
    ".env",
    "$(",
    "&&",
    "||",
    ";",
    "<",
    ">",
    "`",
    "chmod ",
    "curl ",
    "rm -rf",
    "scp ",
    "secrets/",
    "ssh ",
    "sudo ",
    "wget ",
    "|",
)


def verify_workflow_file(paths: ProjectPaths, *, source_path: str) -> dict[str, Any]:
    _require_initialized(paths)
    path = Path(source_path)
    source = path if path.is_absolute() else paths.root / path
    if not source.exists() or not source.is_file():
        raise InvalidInputError(
            f"Workflow verification source does not exist: {source_path}",
            details={"source_path": source_path},
        )
    return verify_workflow_text(
        source.read_text(encoding="utf-8"),
        source_label=_display_path(paths, source),
        path=_display_path(paths, source),
        target_type="file",
        target_id=_display_path(paths, source),
    )


def verify_workflow_proposal(paths: ProjectPaths, *, proposal_id: str) -> dict[str, Any]:
    _require_initialized(paths)
    _validate_proposal_id(proposal_id)
    path = paths.workflow_proposals_dir / f"{proposal_id}.yaml"
    if not path.exists():
        raise InvalidInputError(
            f"Workflow proposal does not exist: {proposal_id}",
            details={"proposal_id": proposal_id, "path": str(path)},
        )
    return verify_workflow_text(
        path.read_text(encoding="utf-8"),
        source_label=str(path.relative_to(paths.root)),
        path=str(path.relative_to(paths.root)),
        target_type="workflow_proposal",
        target_id=proposal_id,
    )


def verify_workflow_template(paths: ProjectPaths, *, workflow_id: str) -> dict[str, Any]:
    _require_initialized(paths)
    if not _is_identifier(workflow_id):
        raise InvalidInputError(
            f"Invalid workflow id: {workflow_id}",
            details={"workflow_id": workflow_id},
        )
    path = paths.workflows_dir / f"{workflow_id}.yaml"
    if not path.exists():
        raise InvalidInputError(
            f"Workflow template does not exist: {workflow_id}",
            details={"workflow_id": workflow_id, "path": str(path)},
        )
    return verify_workflow_text(
        path.read_text(encoding="utf-8"),
        source_label=str(path.relative_to(paths.root)),
        path=str(path.relative_to(paths.root)),
        target_type="workflow_template",
        target_id=workflow_id,
        expected_workflow_id=workflow_id,
    )


def verify_workflow_text(
    text: str,
    *,
    source_label: str,
    path: str,
    target_type: str,
    target_id: str,
    expected_workflow_id: str | None = None,
) -> dict[str, Any]:
    verifier = _Verifier(
        source_label=source_label,
        path=path,
        target_type=target_type,
        target_id=target_id,
        expected_workflow_id=expected_workflow_id,
    )
    return verifier.verify(text)


class _Verifier:
    def __init__(
        self,
        *,
        source_label: str,
        path: str,
        target_type: str,
        target_id: str,
        expected_workflow_id: str | None,
    ) -> None:
        self.source_label = source_label
        self.path = path
        self.target_type = target_type
        self.target_id = target_id
        self.expected_workflow_id = expected_workflow_id
        self.workflow_id = ""
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checks: list[dict[str, str]] = []

    def verify(self, text: str) -> dict[str, Any]:
        try:
            data = validate_workflow_proposal_text(text, source_label=self.source_label)
        except InvalidInputError as exc:
            self._error("required_fields", f"Workflow YAML is invalid: {exc}")
            return self._result()

        self.workflow_id = str(data.get("id") or "")
        self._check("required_fields", "passed", "Workflow has required top-level fields.")
        self._verify_identity(data)
        self._verify_goal(data)
        self._verify_agents(data)
        self._verify_steps(data)
        self._verify_budget(data)
        self._verify_stop_conditions(data)
        self._verify_forbidden_keys(data)
        return self._result()

    def _verify_identity(self, data: dict[str, Any]) -> None:
        workflow_type = str(data.get("type") or "")
        if workflow_type not in ALLOWED_WORKFLOW_TYPES:
            self._error("workflow_type", f"Workflow type must be one of {sorted(ALLOWED_WORKFLOW_TYPES)}.")
        else:
            self._check("workflow_type", "passed", f"Workflow type is {workflow_type}.")
        version = data.get("version")
        if not isinstance(version, str) or not version.strip():
            self._error("version", "Workflow version must be a non-empty string.")
        if self.expected_workflow_id and self.workflow_id != self.expected_workflow_id:
            self._error(
                "workflow_id",
                f"Workflow id mismatch: expected {self.expected_workflow_id}, found {self.workflow_id}.",
            )

    def _verify_goal(self, data: dict[str, Any]) -> None:
        goal = data.get("goal")
        if not isinstance(goal, dict):
            self._error("goal", "Workflow goal must be a mapping.")
            return
        description = goal.get("description")
        if not isinstance(description, str) or not description.strip():
            self._warning("goal", "Workflow goal.description is empty.")
        completion = goal.get("completion")
        if not isinstance(completion, list):
            self._error("goal", "Workflow goal.completion must be a list.")

    def _verify_agents(self, data: dict[str, Any]) -> None:
        agents = data.get("agents")
        if not isinstance(agents, dict):
            self._error("agents", "Workflow agents must be a mapping.")
            return
        for agent_id, agent in sorted(agents.items()):
            if not _is_identifier(str(agent_id)):
                self._error("agents", f"Agent id is invalid: {agent_id}.")
            if not isinstance(agent, dict):
                self._error("agents", f"Agent {agent_id} must be a mapping.")
                continue
            mode = str(agent.get("mode") or "")
            if mode not in ALLOWED_AGENT_MODES:
                self._error("agents", f"Agent {agent_id} has unsupported mode: {mode}.")
            if not str(agent.get("purpose") or "").strip():
                self._warning("agents", f"Agent {agent_id} has no purpose.")

    def _verify_steps(self, data: dict[str, Any]) -> None:
        steps = data.get("steps")
        agents = data.get("agents") if isinstance(data.get("agents"), dict) else {}
        if not isinstance(steps, list):
            self._error("steps", "Workflow steps must be a list.")
            return
        if not steps:
            self._error("steps", "Workflow must define at least one step.")
            return
        seen: set[str] = set()
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                self._error("steps", f"Step {index} must be a mapping.")
                continue
            step_id = str(step.get("id") or "")
            if not _is_identifier(step_id):
                self._error("steps", f"Step {index} has invalid id: {step_id}.")
            elif step_id in seen:
                self._error("steps", f"Step id is duplicated: {step_id}.")
            seen.add(step_id)
            if "agent" in step:
                agent_id = str(step["agent"])
                if agent_id not in agents:
                    self._error("steps", f"Step {step_id} references unknown agent: {agent_id}.")
            if "command" in step:
                self._verify_command(str(step["command"]), step_id=step_id)
            if "commands" in step:
                commands = step["commands"]
                if not isinstance(commands, list) or not commands:
                    self._error("steps", f"Step {step_id} commands must be a non-empty list.")
                else:
                    for command in commands:
                        self._verify_command(str(command), step_id=step_id)
            if not any(key in step for key in ["agent", "command", "commands", "rules"]):
                self._error("steps", f"Step {step_id or index} has no agent, command, commands, or rules.")

    def _verify_command(self, command: str, *, step_id: str) -> None:
        if not command.strip():
            self._error("commands", f"Step {step_id} command is empty.")
            return
        lowered = command.lower()
        for fragment in FORBIDDEN_COMMAND_FRAGMENTS:
            if fragment in lowered:
                self._error("commands", f"Step {step_id} command contains forbidden fragment: {fragment}.")
        if not (command.startswith("pcl ") or command.startswith("project.commands.")):
            self._warning("commands", f"Step {step_id} command is not a pcl command or project.commands reference.")

    def _verify_budget(self, data: dict[str, Any]) -> None:
        budget = data.get("budget")
        if not isinstance(budget, dict):
            self._error("budget", "Workflow budget must be a mapping.")
            return
        self._verify_positive_int_budget(budget, "max_iterations", maximum=10)
        self._verify_positive_int_budget(budget, "max_parallel_jobs", maximum=10, required=False)

    def _verify_positive_int_budget(
        self,
        budget: dict[str, Any],
        field: str,
        *,
        maximum: int,
        required: bool = True,
    ) -> None:
        value = budget.get(field)
        if value is None:
            if required:
                self._warning("budget", f"Workflow budget.{field} is not set.")
            return
        if not isinstance(value, int) or value < 1:
            self._error("budget", f"Workflow budget.{field} must be a positive integer.")
            return
        if value > maximum:
            self._error("budget", f"Workflow budget.{field} must be <= {maximum}.")

    def _verify_stop_conditions(self, data: dict[str, Any]) -> None:
        stop_conditions = data.get("stop_conditions")
        if not isinstance(stop_conditions, list) or not stop_conditions:
            self._error("stop_conditions", "Workflow stop_conditions must be a non-empty list.")

    def _verify_forbidden_keys(self, value: Any, *, path: str = "workflow") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                if key_text in FORBIDDEN_KEYS:
                    self._error("forbidden_keys", f"Workflow uses forbidden key at {path}.{key_text}.")
                self._verify_forbidden_keys(child, path=f"{path}.{key_text}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._verify_forbidden_keys(child, path=f"{path}[{index}]")

    def _error(self, name: str, message: str) -> None:
        self.errors.append(message)
        self._check(name, "failed", message)

    def _warning(self, name: str, message: str) -> None:
        self.warnings.append(message)
        self._check(name, "warning", message)

    def _check(self, name: str, status: str, message: str) -> None:
        self.checks.append({"name": name, "status": status, "message": message})

    def _result(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "ok": not self.errors,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "workflow_id": self.workflow_id,
            "path": self.path,
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks,
        }


def _validate_proposal_id(proposal_id: str) -> None:
    if not PROPOSAL_ID_RE.match(proposal_id):
        raise InvalidInputError(
            f"Invalid workflow proposal id: {proposal_id}",
            details={"proposal_id": proposal_id},
        )


def _is_identifier(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"_", "-"} for char in value)


def _display_path(paths: ProjectPaths, path: Path) -> str:
    try:
        return str(path.relative_to(paths.root))
    except ValueError:
        return str(path)


def _require_initialized(paths: ProjectPaths) -> None:
    if not paths.loop_dir.exists() or not paths.db_path.exists():
        raise ProjectNotInitializedError(root=str(paths.root))
