from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pcl.cli import build_parser


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "skills" / "project-control-loop" / "SKILL.md"
SKILL_COPIES = [
    ROOT / ".agents" / "skills" / "project-control-loop" / "SKILL.md",
    ROOT / "skills" / "project-control-loop" / "SKILL.md",
    ROOT / "plugins" / "codex-project-loop" / "skills" / "project-control-loop" / "SKILL.md",
    ROOT / "src" / "pcl" / "templates" / "skills" / "project-control-loop" / "SKILL.md",
]


SKILL_PARSER_CONTRACT_EXAMPLES = [
    'pcl start "<literal user intent>"',
    'pcl feature add --name "..." --surface "..." --description "..."',
    'pcl story draft --feature F-XXXX --actor "..." --goal "..." --expected-behavior "..."',
    'pcl story approve US-XXXX --summary "..."',
    'pcl story waive US-XXXX --reason "..."',
    'pcl test plan --feature F-XXXX --story US-XXXX --type acceptance --scenario "..." --expected "..."',
    'pcl evidence add --file artifacts/acceptance.txt --summary "..." --command "..." --copy',
    'pcl test pass TC-XXXX --summary "..." --evidence-id E-XXXX',
    'pcl feature status F-XXXX --status done --summary "..." --evidence-id E-XXXX',
    'pcl task status T-XXXX done --reason "..."',
    'pcl finish --emit-packet --goal G-XXXX',
    'pcl verification record --run WR-XXXX --result approved --reason "..."',
    'pcl goal close G-XXXX --summary "..." --evidence-id E-PACKET',
    'pcl goal close G-XXXX --summary "..." --verification V-XXXX',
    'pcl --json profile prepare council.discovery --target task:T-XXXX --brief E-XXXX --output /tmp/council-request.json',
    'pcl --json profile fixture-run --request /tmp/council-request.json --status completed --output-dir /tmp/council-output',
    'pcl --json profile ingest --request /tmp/council-request.json --bundle /tmp/council-output/profile-output-bundle.json --dry-run',
    'pcl --json profile ingest --request /tmp/council-request.json --bundle /tmp/council-output/profile-output-bundle.json',
    'pcl --json profile authorize --revoke EV-XXXXXXXXXXXX --actor "human:owner" --source-kind cockpit --source-ref "cockpit:<task-id>" --reason "Withdraw scope"',
]


LEGACY_PARSER_CONTRACT_EXAMPLES = [
    # Compatibility forms remain parseable while the Skill documents the
    # hash-pinned Evidence-ID route as canonical terminal proof.
    'pcl test pass TC-XXXX --summary "..." --evidence "artifacts/acceptance.txt"',
    'pcl feature status F-XXXX --status done --summary "..." --evidence "artifacts/acceptance.txt"',
    'pcl goal close G-XXXX --summary "..." --evidence "artifacts/completion-packet.json"',
]


@pytest.mark.parametrize("command", SKILL_PARSER_CONTRACT_EXAMPLES)
def test_major_skill_command_examples_satisfy_current_parser_contract(command: str) -> None:
    assert command in SKILL_PATH.read_text(encoding="utf-8")
    argv = shlex.split(command)

    assert argv[0] == "pcl"
    build_parser().parse_args(argv[1:])


@pytest.mark.parametrize("command", LEGACY_PARSER_CONTRACT_EXAMPLES)
def test_legacy_terminal_examples_use_only_supported_compatibility_flags(command: str) -> None:
    argv = shlex.split(command)

    assert argv[0] == "pcl"
    build_parser().parse_args(argv[1:])


def test_direct_route_documents_canonical_terminal_contract() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")

    expected_commands = [
        'pcl test pass TC-XXXX --summary "..." --evidence-id E-XXXX',
        'pcl feature status F-XXXX --status done --summary "..." --evidence-id E-XXXX',
        'pcl task status T-XXXX done --reason "..."',
        'pcl goal close G-XXXX --summary "..." --evidence-id E-PACKET',
        'pcl goal close G-XXXX --summary "..." --verification V-XXXX',
    ]
    for command in expected_commands:
        assert command in skill

    feature_done = shlex.split(expected_commands[1])
    assert feature_done[feature_done.index("--summary") + 1]
    assert feature_done[feature_done.index("--evidence-id") + 1] == "E-XXXX"
    assert "`--verification` accepts a Verification entity ID" in skill
    assert "Never pass `E-XXXX` through `--evidence`" in skill
    assert "`--evidence` and `--evidence-id` are mutually exclusive" in skill
    assert "WFR-XXXX" not in skill


def test_direct_route_preserves_handoff_order() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    ordered_commands = [
        'pcl start "<literal user intent>"',
        "pcl story approve US-XXXX",
        "pcl test plan --feature F-XXXX --story US-XXXX",
        "pcl evidence add --file artifacts/acceptance.txt",
        "pcl test pass TC-XXXX",
        "pcl feature status F-XXXX",
        "pcl task status T-XXXX done",
        "pcl finish --emit-packet --goal G-XXXX",
        "pcl goal close G-XXXX --summary \"...\" --evidence-id E-PACKET",
    ]

    positions = [skill.index(command) for command in ordered_commands]
    assert positions == sorted(positions)


def test_skill_copies_require_autonomous_safe_continuation_and_oriented_progress() -> None:
    required = [
        "After every completed slice or meaningful state change, run `pcl next --json`.",
        "`run_policy=agent_safe`, execute",
        "is not automatically a\nhuman gate",
        "**Now:** current milestone and active task",
        "**Done:** the slice just completed and its evidence",
        "**Next:** the concrete next action already being taken",
        "**Human needed:** `none`, or the exact decision required",
        "Do not make the human ask what is happening",
    ]
    for path in SKILL_COPIES:
        skill = path.read_text(encoding="utf-8")
        for text in required:
            assert text in skill, f"{path} is missing: {text}"


def test_all_loaded_and_distributed_skill_copies_are_byte_identical() -> None:
    canonical = SKILL_PATH.read_bytes()

    for path in SKILL_COPIES:
        assert path.read_bytes() == canonical, f"Skill copy drifted: {path}"
