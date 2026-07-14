from __future__ import annotations

from typing import Any

from .errors import InvalidInputError


COMMAND_GUIDE_CONTRACT_VERSION = "command-guide/v1"
COMMAND_GUIDE_TOPICS = ("start", "direct", "finish", "dashboard", "recover")


def command_guide(topic: str | None = None) -> dict[str, Any]:
    if topic is not None and topic not in COMMAND_GUIDE_TOPICS:
        raise InvalidInputError(
            "Unknown command guide topic.",
            details={"topic": topic, "supported_topics": list(COMMAND_GUIDE_TOPICS)},
        )
    topics = _topics()
    if topic is not None:
        topics = [item for item in topics if item["topic"] == topic]
    return {
        "ok": True,
        "contract_version": COMMAND_GUIDE_CONTRACT_VERSION,
        "requested_topic": topic,
        "topics": topics,
    }


def render_command_guide(payload: dict[str, Any]) -> str:
    requested = payload.get("requested_topic") or "all"
    lines = [f"Command guide: {requested}"]
    for topic in payload["topics"]:
        lines.extend(["", f"{topic['topic']}: {topic['purpose']}"])
        for step in topic["steps"]:
            state = "writes state" if step["mutates_state"] else "read only"
            lines.append(
                f"  {step['order']}. {step['command']} "
                f"[{step['run_policy']}; {state}]"
            )
            lines.append(f"     {step['expected_after']}")
    return "\n".join(lines) + "\n"


def _step(
    command: str,
    *,
    mutates_state: bool,
    run_policy: str,
    requires: list[str],
    purpose: str,
    expected_after: str,
) -> dict[str, Any]:
    return {
        "command": command,
        "mutates_state": mutates_state,
        "run_policy": run_policy,
        "requires": requires,
        "purpose": purpose,
        "expected_after": expected_after,
    }


def _topic(topic: str, purpose: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "topic": topic,
        "purpose": purpose,
        "steps": [dict(step, order=index) for index, step in enumerate(steps, start=1)],
    }


def _topics() -> list[dict[str, Any]]:
    return [
        _topic(
            "start",
            "Inspect adoption safely and register one literal intent as active work.",
            [
                _step(
                    "pcl init --dry-run --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Inspect initialization changes before adopting PCL.",
                    expected_after="The initialization plan lists created, updated, and skipped files.",
                ),
                _step(
                    "pcl init --json",
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Apply the reviewed non-destructive initialization plan.",
                    expected_after="Project-local configuration and state storage are initialized.",
                ),
                _step(
                    'pcl start "<literal intent>" --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["literal intent"],
                    purpose="Create the minimal Goal and Task for the user's exact request.",
                    expected_after="The response supplies goal_id and task_id for subsequent steps.",
                ),
                _step(
                    "pcl next --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Read the current state-machine recommendation.",
                    expected_after="One guided next action is available without dashboard parsing.",
                ),
            ],
        ),
        _topic(
            "direct",
            "Deliver one well-scoped behavior change with Story, Test, and hash-pinned Evidence.",
            [
                _step(
                    'pcl start "<literal intent>" --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["literal intent"],
                    purpose="Register the user's exact implementation intent.",
                    expected_after="The response supplies goal_id and task_id.",
                ),
                _step(
                    'pcl feature add --name "<name>" --surface "<surface>" '
                    '--description "<description>" --task <task_id> --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["name", "surface", "description", "task_id"],
                    purpose="Create and atomically link the behavior surface to the active Task.",
                    expected_after="The response supplies feature_id.",
                ),
                _step(
                    'pcl story draft --feature <feature_id> --actor "<actor>" '
                    '--goal "<goal>" --expected-behavior "<behavior>" --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["feature_id", "actor", "goal", "behavior"],
                    purpose="Capture the user-visible behavior before implementation.",
                    expected_after="The response supplies story_id in draft status.",
                ),
                _step(
                    'pcl story approve <story_id> --summary "<human approval receipt>" --json',
                    mutates_state=True,
                    run_policy="human_required",
                    requires=["story_id", "human approval receipt"],
                    purpose="Record explicit human approval; an agent must not infer it.",
                    expected_after="The Story is approved and implementation may proceed.",
                ),
                _step(
                    'pcl test plan --feature <feature_id> --story <story_id> --type acceptance '
                    '--scenario "<scenario>" --expected "<expected>" --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["feature_id", "story_id", "scenario", "expected"],
                    purpose="Register a behavior-facing acceptance test.",
                    expected_after="The response supplies test_case_id in planned status.",
                ),
                _step(
                    'pcl evidence add --file <artifact_path> --summary "<summary>" '
                    '--command "<verification command>" --copy --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["artifact_path", "summary", "verification command"],
                    purpose="Pin the verification artifact bytes and SHA-256.",
                    expected_after="The response supplies evidence_id for terminal transitions.",
                ),
                _step(
                    'pcl test pass <test_case_id> --summary "<summary>" '
                    '--evidence-id <evidence_id> --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["test_case_id", "summary", "evidence_id"],
                    purpose="Bind passing acceptance Evidence to the Test.",
                    expected_after="The Test is passing with canonical Evidence.",
                ),
                _step(
                    'pcl feature status <feature_id> --status done --summary "<summary>" '
                    '--evidence-id <evidence_id> --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["feature_id", "summary", "evidence_id"],
                    purpose="Mark the completed Feature terminal with the same reviewable proof.",
                    expected_after="The Feature is done.",
                ),
                _step(
                    'pcl task status <task_id> done --reason "<reason>" --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["task_id", "reason"],
                    purpose="Close the active child Task before closing its Goal.",
                    expected_after="The Task is done.",
                ),
                _step(
                    "pcl finish --emit-packet --goal <goal_id> --json",
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["goal_id"],
                    purpose="Run configured guarded finish checks and pin a completion packet.",
                    expected_after="A COMPLETED_VERIFIED or COMPLETED_WITH_RISK packet supplies packet_evidence_id.",
                ),
                _step(
                    'pcl goal close <goal_id> --summary "<summary>" '
                    '--evidence-id <packet_evidence_id> --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["goal_id", "summary", "packet_evidence_id"],
                    purpose="Close the direct-route Goal with its completed packet.",
                    expected_after="The Goal is closed with terminal proof.",
                ),
                _step(
                    "pcl validate --strict --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Verify lifecycle integrity after terminal mutations.",
                    expected_after="Validation returns ok=true with no errors.",
                ),
                _step(
                    "pcl render --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Regenerate human review artifacts from authoritative state.",
                    expected_after="The response supplies dashboard HTML and data paths.",
                ),
            ],
        ),
        _topic(
            "finish",
            "Inspect and complete terminal direct-route work without bypassing Evidence gates.",
            [
                _step(
                    "pcl next --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Confirm the highest-priority remaining lifecycle action.",
                    expected_after="The response identifies any unfinished child state or human decision.",
                ),
                _step(
                    "pcl finish --emit-packet --goal <goal_id> --dry-run --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=["goal_id"],
                    purpose="Preview the target, repository snapshot, and configured checks.",
                    expected_after="The finish plan is reviewable without executing checks or writing Evidence.",
                ),
                _step(
                    "pcl finish --emit-packet --goal <goal_id> --json",
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["goal_id"],
                    purpose="Execute guarded checks and record the completion packet.",
                    expected_after="A terminal packet supplies packet_evidence_id.",
                ),
                _step(
                    'pcl goal close <goal_id> --summary "<summary>" '
                    '--evidence-id <packet_evidence_id> --json',
                    mutates_state=True,
                    run_policy="agent_safe",
                    requires=["goal_id", "summary", "packet_evidence_id"],
                    purpose="Close the Goal with hash-pinned terminal proof.",
                    expected_after="The Goal is closed.",
                ),
                _step(
                    "pcl validate --strict --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Verify final lifecycle integrity.",
                    expected_after="Validation returns ok=true with no errors.",
                ),
                _step(
                    "pcl render --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Refresh the goal-closure dashboard.",
                    expected_after="The dashboard artifacts reflect the closed Goal.",
                ),
            ],
        ),
        _topic(
            "dashboard",
            "Prepare trustworthy dashboard artifacts at a human review moment.",
            [
                _step(
                    "pcl validate --strict --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Validate source state before generating the view.",
                    expected_after="Validation findings are available independently of HTML.",
                ),
                _step(
                    "pcl render --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Generate deterministic HTML and dashboard-data JSON.",
                    expected_after="The response supplies the artifacts a host can open in a side panel.",
                ),
                _step(
                    "pcl next --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Prepare Now, Done, Next, Human needed, and Risks orientation from machine state.",
                    expected_after="The agent can explain exactly what the human should review.",
                ),
            ],
        ),
        _topic(
            "recover",
            "Diagnose a stopped or resumed loop using read-only machine context first.",
            [
                _step(
                    "pcl next --strict --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Route strict validation failures before normal next actions.",
                    expected_after="The highest-priority blocker is explicit.",
                ),
                _step(
                    "pcl report validation --strict --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Generate a reviewable validation report without changing domain state.",
                    expected_after="The response supplies the validation report path.",
                ),
                _step(
                    "pcl resume --target <task_or_goal_id> --format json --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=["task_or_goal_id"],
                    purpose="Build a focused handoff packet for the active target.",
                    expected_after="The packet summarizes current state, evidence, and next actions.",
                ),
                _step(
                    "pcl audit check --json",
                    mutates_state=False,
                    run_policy="agent_safe",
                    requires=[],
                    purpose="Inspect audit projection and Evidence integrity when state looks inconsistent.",
                    expected_after="Audit diagnostics distinguish projection issues from domain failures.",
                ),
            ],
        ),
    ]
