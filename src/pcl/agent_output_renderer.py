from __future__ import annotations

from .agent_output_policy import canonical_agent_output_policy
from .resources import read_text_resource


AGENT_OUTPUT_HOSTS = ("codex", "claude", "gemini", "opencode", "cockpit")
SKILL_RESOURCE = "templates/agent-output-budget/SKILL.md"
GLOBAL_FRAGMENT_RESOURCE = "templates/agent-output-budget/GLOBAL_FRAGMENT.md"

_HOST_LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "gemini": "Gemini CLI",
    "opencode": "OpenCode",
    "cockpit": "AGI Cockpit",
}
_HOST_NOTES = {
    "codex": (
        "Use the shared Skill and this instruction projection. Phase 1 claims no "
        "Codex enforcement hook; compliance remains instruction-based."
    ),
    "claude": (
        "Use the shared Skill for Bash guidance. Any future documented PreToolUse "
        "observation remains audit-only and returns unchanged continuation."
    ),
    "gemini": (
        "Use the shared Skill for tool guidance. Any future documented BeforeTool "
        "observation remains audit-only and leaves tool arguments unchanged."
    ),
    "opencode": (
        "Use the shared Skill and instruction projection. Phase 1 claims no "
        "OpenCode enforcement hook or undocumented plugin."
    ),
    "cockpit": (
        "Workers report typed summaries only: opaque run ID, typed status, child "
        "exit, duration, byte counts, failed-check summary, and diagnostic availability. "
        "Do not project raw stdout/stderr or local paths."
    ),
}


def render_agent_output_host(host: str) -> str:
    """Render one deterministic host projection from the shared assets."""

    if host not in AGENT_OUTPUT_HOSTS:
        raise ValueError(f"Unsupported agent-output host: {host}")
    # Loading the policy here makes a malformed packaged source fail closed before
    # a projection is emitted, while the Markdown assets remain the only prose source.
    canonical_agent_output_policy()
    fragment = read_text_resource(GLOBAL_FRAGMENT_RESOURCE).strip()
    skill = read_text_resource(SKILL_RESOURCE).strip()
    label = _HOST_LABELS[host]
    note = _HOST_NOTES[host]
    return (
        f"# PCL agent output budget — {label}\n\n"
        f"{fragment}\n\n"
        "## Shared agent-output-budget Skill\n\n"
        f"{skill}\n\n"
        f"## {label} projection\n\n"
        f"{note}\n"
    )


def render_agent_output_hosts() -> dict[str, str]:
    return {host: render_agent_output_host(host) for host in AGENT_OUTPUT_HOSTS}
