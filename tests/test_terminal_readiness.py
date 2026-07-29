from __future__ import annotations

from copy import deepcopy

from pcl.terminal_readiness import (
    canonical_terminal_readiness_input_sha256,
    evaluate_terminal_readiness,
    feature_terminal_readiness,
    finish_terminal_readiness,
    task_terminal_readiness,
)
from pcl.target_resolver import ResolvedRoutingTarget
from pcl.tasks import _readiness_requirement_for_finding
from pcl.validators import ValidationFinding


def test_terminal_readiness_is_deterministic_and_side_effect_free() -> None:
    requirements = [
        {
            "code": "validation_failed",
            "state": "incomplete",
            "message": "Validation must pass.",
            "next_command": "pcl validate --strict --json",
            "details": {"errors": ["broken"]},
        },
        {
            "code": "human_gate",
            "state": "blocked",
            "message": "A human decision is required.",
            "next_command": "pcl decision list --status open",
            "requires_human": True,
            "details": {"decision_ids": ["DEC-0001"]},
        },
        {
            "code": "strict_warning",
            "state": "risk",
            "message": "Strict validation reported a warning.",
            "details": {"warnings": ["review"]},
        },
        {
            "code": "stability_observation",
            "state": "advisory",
            "message": "Stability is record-only.",
            "next_command": "pcl validate --strict --json",
        },
    ]
    original = deepcopy(requirements)

    first = evaluate_terminal_readiness(
        target_type="task",
        target_id="T-0001",
        requirements=requirements,
    )
    second = evaluate_terminal_readiness(
        target_type="task",
        target_id="T-0001",
        requirements=reversed(requirements),
    )

    assert requirements == original
    assert first == second
    assert first["contract_version"] == "terminal-readiness/v1"
    assert first["status"] == "blocked"
    assert first["terminal_allowed"] is False
    assert first["requires_human"] is True
    assert [reason["code"] for reason in first["reasons"]] == [
        "human_gate",
        "validation_failed",
        "strict_warning",
        "stability_observation",
    ]
    assert first["next_commands"] == [
        "pcl decision list --status open",
        "pcl validate --strict --json",
    ]


def test_terminal_readiness_dedupes_exact_reasons_and_hashes_canonical_input() -> None:
    requirement = {
        "code": "duplicate",
        "state": "blocked",
        "message": "One exact blocker.",
        "details": {"b": 2, "a": 1},
    }

    readiness = evaluate_terminal_readiness(
        target_type="task",
        target_id="T-0001",
        requirements=[requirement, deepcopy(requirement)],
    )

    assert readiness["reasons"] == [
        {
            "code": "duplicate",
            "state": "blocked",
            "message": "One exact blocker.",
            "requires_human": False,
            "details": {"b": 2, "a": 1},
        }
    ]
    assert canonical_terminal_readiness_input_sha256(
        {"task": {"id": "T-0001"}, "dependencies": []}
    ) == canonical_terminal_readiness_input_sha256(
        {"dependencies": [], "task": {"id": "T-0001"}}
    )
    assert canonical_terminal_readiness_input_sha256(
        {"task": {"id": "T-0001"}}
    ) != canonical_terminal_readiness_input_sha256(
        {"task": {"id": "T-0002"}}
    )


def test_unknown_global_finding_fails_closed() -> None:
    finding = ValidationFinding(
        code="new_unclassified_contract",
        severity="warning",
        message="A new finding family has no projection policy.",
        entity=None,
        repair_class="unsupported",
        requires_human=False,
    )
    resolved = ResolvedRoutingTarget(
        type="task",
        row={"id": "T-0001", "status": "in_progress"},
        goal_row=None,
        scope_refs=frozenset({("task", "T-0001")}),
    )

    requirement = _readiness_requirement_for_finding(
        finding,
        resolved=resolved,
        current_proof_refs=set(resolved.scope_refs),
    )

    assert requirement is not None
    assert requirement["state"] == "blocked"
    assert requirement["code"] == "new_unclassified_contract"


def test_feature_readiness_preserves_lifecycle_reason_details() -> None:
    readiness = feature_terminal_readiness(
        feature_id="F-0001",
        stories=[{"id": "US-0001", "status": "approved"}],
        tests=[{"id": "TC-0001", "status": "planned"}],
        defects=[],
    )

    assert readiness["status"] == "incomplete"
    assert readiness["reasons"] == [
        {
            "code": "feature_done_tests_incomplete",
            "state": "incomplete",
            "message": "Feature F-0001 has missing or incomplete non-waived Tests.",
            "requires_human": False,
            "next_command": "pcl test read TC-0001 --json",
            "details": {
                "feature_id": "F-0001",
                "tests": [{"id": "TC-0001", "status": "planned"}],
                "test_count": 1,
            },
        }
    ]


def test_finish_readiness_keeps_record_only_stability_advisory() -> None:
    readiness = finish_terminal_readiness(
        target_type="task",
        target_id="T-0001",
        commands=[
            {
                "status": "passed",
                "command": "python -m pytest",
                "stability_evaluation": {
                    "status": "stability_required",
                    "reproducible": False,
                },
            }
        ],
        strict_ok=True,
        strict_errors=[],
        strict_warnings=[],
        race_detected=False,
        blockers={"budget_exhausted": False, "decisions": [], "human_steps": []},
        stability_mode="record_only",
    )

    assert readiness["status"] == "ready"
    assert readiness["terminal_allowed"] is True
    assert [reason["code"] for reason in readiness["reasons"]] == [
        "finish_stability_record_only"
    ]


def test_finish_readiness_treats_target_goal_escalation_as_human_blocker() -> None:
    readiness = finish_terminal_readiness(
        target_type="task",
        target_id="T-0001",
        commands=[{"status": "passed", "command": "python -m pytest"}],
        strict_ok=True,
        strict_errors=[],
        strict_warnings=[],
        race_detected=False,
        blockers={
            "budget_exhausted": False,
            "decisions": [],
            "escalations": [
                {
                    "id": "ESC-0001",
                    "question": "Can this Goal proceed?",
                    "severity": "high",
                }
            ],
            "human_steps": [],
        },
        stability_mode="record_only",
    )

    assert readiness["status"] == "blocked"
    assert readiness["requires_human"] is True
    assert readiness["reasons"][0]["code"] == "finish_human_decision_required"
    assert readiness["reasons"][0]["details"]["escalations"][0]["id"] == "ESC-0001"


def test_finish_readiness_allows_low_strict_warning_as_ready_with_risk() -> None:
    readiness = finish_terminal_readiness(
        target_type="task",
        target_id="T-0001",
        commands=[{"status": "passed", "command": "python -m pytest"}],
        strict_ok=True,
        strict_errors=[],
        strict_warnings=["Historical advisory finding."],
        race_detected=False,
        blockers={
            "budget_exhausted": False,
            "decisions": [],
            "escalations": [],
            "human_steps": [],
        },
        stability_mode="record_only",
    )

    assert readiness["status"] == "ready_with_risk"
    assert readiness["terminal_allowed"] is True
    assert readiness["reasons"][0]["code"] == "finish_strict_validation_warning"


def test_task_readiness_projects_ready_to_close_from_linked_feature_state() -> None:
    readiness = task_terminal_readiness(
        task_id="T-0001",
        task_status="in_progress",
        feature_id="F-0001",
        stories=[{"id": "US-0001", "status": "approved"}],
        tests=[{"id": "TC-0001", "status": "passing"}],
        defects=[],
    )

    assert readiness["status"] == "ready"
    assert readiness["terminal_allowed"] is True
    assert readiness["derived_task_status"] == "ready_to_close"
    assert readiness["source_feature_id"] == "F-0001"
