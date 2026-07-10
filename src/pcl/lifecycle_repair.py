from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from urllib.parse import quote

from .db import SQLITE_BUSY_TIMEOUT_MS
from .errors import DataStoreError, EXIT_USAGE, PclError
from .paths import ProjectPaths
from .validators import (
    LifecycleFinding,
    collect_lifecycle_findings,
    completion_packet_is_valid_for_goal,
)


CONTRACT_VERSION = "lifecycle-repair-plan/v1"
CLASSIFICATIONS = ("structural", "semantic", "human_review", "unsupported")
CLASSIFICATION_RANKS = {name: rank for rank, name in enumerate(CLASSIFICATIONS)}
ACTION_CLASSIFICATIONS = {
    "add_missing_evidence_link": "structural",
    "add_missing_completion_packet_link": "structural",
    "inspect_story_candidate": "semantic",
    "choose_story_relationship": "semantic",
    "inspect_feature_stories": "semantic",
    "inspect_feature_tests": "semantic",
    "inspect_feature_evidence": "semantic",
    "review_story_status": "human_review",
    "record_goal_verification": "human_review",
    "review_open_feature_defects": "human_review",
    "report_invalid_goal_verification": "unsupported",
    "report_invalid_goal_proof": "unsupported",
    "report_unsupported_lifecycle_finding": "unsupported",
    "report_conflicting_evidence_link": "unsupported",
    "report_invalid_test_evidence": "unsupported",
}


class LifecycleRepairPlanError(PclError):
    def __init__(self, message: str, *, code: str, details: dict[str, object]) -> None:
        super().__init__(message=message, code=code, exit_code=EXIT_USAGE, details=details)


def validate_lifecycle_repair_actions(actions: list[dict[str, object]]) -> None:
    for action in actions:
        action_id = str(action.get("action_id", ""))
        classification = action.get("classification")
        action_kind = action.get("action_kind")
        if classification not in CLASSIFICATIONS:
            raise LifecycleRepairPlanError(
                "Lifecycle repair plan contains an unknown classification.",
                code="repair_unknown_classification",
                details={"action_id": action_id, "classification": classification},
            )
        expected = ACTION_CLASSIFICATIONS.get(str(action_kind))
        if expected is None:
            raise LifecycleRepairPlanError(
                "Lifecycle repair plan contains an unknown action kind.",
                code="repair_unknown_action_kind",
                details={"action_id": action_id, "action_kind": action_kind},
            )
        if classification != expected:
            raise LifecycleRepairPlanError(
                "Lifecycle repair action classification does not match its action kind.",
                code="repair_action_classification_mismatch",
                details={
                    "action_id": action_id,
                    "action_kind": action_kind,
                    "classification": classification,
                    "expected_classification": expected,
                },
            )
        if action.get("safe_to_apply") is True and classification != "structural":
            raise LifecycleRepairPlanError(
                "Only structural lifecycle repair actions may be safe to apply.",
                code="repair_non_structural_safe_action",
                details={"action_id": action_id, "action_kind": action_kind},
            )


@dataclass(frozen=True)
class LifecycleRepairAction:
    finding_code: str
    classification: str
    action_kind: str
    entity: dict[str, str]
    related: list[dict[str, str]]
    safe_to_apply: bool
    requires_human: bool
    command: str
    reason: str

    def __post_init__(self) -> None:
        if self.classification not in CLASSIFICATION_RANKS:
            raise ValueError(
                f"classification must be one of {', '.join(CLASSIFICATIONS)}: "
                f"{self.classification}"
            )

    @property
    def sort_key(self) -> list[object]:
        return [
            CLASSIFICATION_RANKS[self.classification],
            self.entity.get("type", ""),
            self.entity.get("id", ""),
            self.action_kind,
            self.finding_code,
        ]

    def to_dict(self, *, action_id: str) -> dict[str, object]:
        return {
            "action_id": action_id,
            "finding_code": self.finding_code,
            "classification": self.classification,
            "action_kind": self.action_kind,
            "sort_key": self.sort_key,
            "entity": self.entity,
            "related": self.related,
            "safe_to_apply": self.safe_to_apply,
            "requires_human": self.requires_human,
            "command": self.command,
            "reason": self.reason,
        }


def build_lifecycle_repair_plan(paths: ProjectPaths) -> dict[str, object]:
    conn = _connect_read_only(paths.db_path)
    try:
        findings = collect_lifecycle_findings(paths, conn)
        actions = [_action_for_finding(paths, conn, finding) for finding in findings]
    except sqlite3.Error as exc:
        raise DataStoreError(f"Could not plan lifecycle repair: {exc}") from exc
    finally:
        conn.close()

    ordered = sorted(actions, key=lambda action: tuple(action.sort_key))
    summary = {classification: 0 for classification in CLASSIFICATIONS}
    serialized = []
    for index, action in enumerate(ordered, start=1):
        summary[action.classification] += 1
        serialized.append(action.to_dict(action_id=f"LR-{index:04d}"))
    return {
        "contract_version": CONTRACT_VERSION,
        "mode": "plan",
        "mutated": False,
        "summary": summary,
        "actions": serialized,
    }


def apply_structural_lifecycle_repair(paths: ProjectPaths) -> dict[str, object]:
    from .relationship_repair import apply_structural_actions

    plan = build_lifecycle_repair_plan(paths)
    actions = plan["actions"]
    assert isinstance(actions, list)
    result = apply_structural_actions(paths, actions)
    return {**result, "contract_version": CONTRACT_VERSION, "mode": "apply_structural"}


def render_lifecycle_repair_plan(plan: dict[str, object]) -> str:
    summary = plan["summary"]
    assert isinstance(summary, dict)
    lines = [
        f"Lifecycle repair plan ({plan['contract_version']})",
        "Mode: plan; mutated=false",
        "Summary: " + " ".join(f"{name}={summary[name]}" for name in CLASSIFICATIONS),
    ]
    actions = plan["actions"]
    assert isinstance(actions, list)
    if not actions:
        lines.append("Actions: none")
        return "\n".join(lines)
    lines.append("Actions:")
    for action in actions:
        assert isinstance(action, dict)
        entity = action["entity"]
        assert isinstance(entity, dict)
        related = action["related"]
        assert isinstance(related, list)
        related_text = ", ".join(
            f"{item.get('type', '')}:{item.get('id', '')}"
            for item in related
            if isinstance(item, dict)
        )
        lines.extend(
            [
                (
                    f"[{str(action['classification']).upper()}] {action['action_id']} "
                    f"{action['action_kind']} {entity.get('type', '')}:{entity.get('id', '')}"
                ),
                f"  Finding: {action['finding_code']}",
                f"  Related: {related_text or 'none'}",
                f"  Command: {action['command']}",
                f"  Reason: {action['reason']}",
            ]
        )
    return "\n".join(lines)


def _connect_read_only(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise DataStoreError(f"Missing project database: {db_path}")
    uri = f"file:{quote(str(db_path.resolve()), safe='/')}?mode=ro"
    try:
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
        )
    except sqlite3.Error as exc:
        raise DataStoreError(f"Could not open project database read-only: {exc}") from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def _action_for_finding(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    finding: LifecycleFinding,
) -> LifecycleRepairAction:
    if finding.code == "test_story_required":
        return _story_action(finding)
    if finding.code == "test_story_not_terminal":
        story_id = str(finding.details.get("story_id", ""))
        return _action(
            finding,
            classification="human_review",
            action_kind="review_story_status",
            related=[_entity("user_story", story_id)],
            command=f"pcl story read {story_id} --json",
            reason="Story review, approval, or waiver requires an explicit human decision.",
        )
    if finding.code == "test_acceptance_evidence_required":
        return _test_evidence_action(finding)
    if finding.code == "goal_close_verification_required":
        structural = _goal_packet_link_action(paths, conn, finding)
        if structural is not None:
            return structural
        verification_id = str(finding.details.get("verification_id", ""))
        if verification_id:
            return _action(
                finding,
                classification="unsupported",
                action_kind="report_invalid_goal_verification",
                related=[_entity("verification", verification_id)],
                command=f"pcl verification read {verification_id} --json",
                reason=(
                    "The referenced Verification is missing, non-approved, or belongs to "
                    "another Goal; the planner cannot reinterpret it."
                ),
            )
        evidence_id = str(finding.details.get("evidence_id", ""))
        if evidence_id:
            return _action(
                finding,
                classification="unsupported",
                action_kind="report_invalid_goal_proof",
                related=[_entity("evidence", evidence_id)],
                command=f"pcl evidence show {evidence_id} --json",
                reason=(
                    "The stored goal proof is missing, drifted, cross-target, wrong-role, or "
                    "otherwise invalid; the planner cannot reinterpret it."
                ),
            )
        return _action(
            finding,
            classification="human_review",
            action_kind="record_goal_verification",
            command="pcl verification list --json",
            reason=(
                "Goal closure requires a human-reviewed Verification or a valid same-goal "
                "completion packet."
            ),
        )
    feature_actions = {
        "feature_done_story_incomplete": (
            "semantic",
            "inspect_feature_stories",
            "A done Feature cannot infer Story review, approval, or waiver.",
        ),
        "feature_done_tests_incomplete": (
            "semantic",
            "inspect_feature_tests",
            "A done Feature cannot infer Test status changes or waivers.",
        ),
        "feature_done_open_defects": (
            "human_review",
            "review_open_feature_defects",
            "Closing, waiving, or reinterpreting an active Defect requires human review.",
        ),
        "feature_done_evidence_required": (
            "semantic",
            "inspect_feature_evidence",
            "Choosing, creating, copying, or replacing Feature Evidence is a semantic action.",
        ),
    }
    if finding.code in feature_actions:
        classification, action_kind, reason = feature_actions[finding.code]
        related = []
        for detail_key, entity_type in (
            ("story_ids", "user_story"),
            ("test_ids", "test_case"),
            ("defect_ids", "defect"),
        ):
            related.extend(
                _entity(entity_type, str(entity_id))
                for entity_id in finding.details.get(detail_key, [])
            )
        return _action(
            finding,
            classification=classification,
            action_kind=action_kind,
            related=related,
            command=f"pcl feature read {finding.entity_id} --json",
            reason=reason,
        )
    return _action(
        finding,
        classification="unsupported",
        action_kind="report_unsupported_lifecycle_finding",
        command="pcl validate --strict --json",
        reason="This lifecycle finding has no supported repair-plan mapping.",
    )


def _story_action(finding: LifecycleFinding) -> LifecycleRepairAction:
    candidates = [str(value) for value in finding.details.get("story_candidates", [])]
    feature_id = str(finding.details.get("feature_id", ""))
    if len(candidates) == 1:
        return _action(
            finding,
            classification="semantic",
            action_kind="inspect_story_candidate",
            related=[_entity("user_story", candidates[0])],
            command=f"pcl story read {candidates[0]} --json",
            reason="A Story link requires an explicit operator choice.",
        )
    return _action(
        finding,
        classification="semantic",
        action_kind="choose_story_relationship",
        related=[_entity("user_story", candidate) for candidate in candidates],
        command=f"pcl story list --feature {feature_id} --json",
        reason=(
            "A Test-to-Story relationship requires an explicit operator choice; candidate "
            "count cannot establish semantics."
        ),
    )


def _test_evidence_action(finding: LifecycleFinding) -> LifecycleRepairAction:
    evidence_id = str(finding.details.get("evidence_id", ""))
    evidence_type = finding.details.get("evidence_type")
    evidence_health = finding.details.get("evidence_health")
    links = finding.details.get("links", [])
    expected_target = finding.entity_id
    conflicting = [
        link
        for link in links
        if not (
            link.get("target_type") == "test_case"
            and link.get("target_id") == expected_target
            and link.get("link_role") == "acceptance"
        )
    ]
    if evidence_id and evidence_health == "ok" and evidence_type and not links:
        return _action(
            finding,
            classification="structural",
            action_kind="add_missing_evidence_link",
            related=[_entity("evidence", evidence_id)],
            safe_to_apply=True,
            requires_human=False,
            command=f"pcl evidence show {evidence_id} --json",
            reason=(
                "The Test already stores this healthy Evidence ID and only its unambiguous "
                "acceptance link is missing."
            ),
        )
    if conflicting:
        related = [_entity("evidence", evidence_id)] if evidence_id else []
        related.extend(
            _entity(str(link.get("target_type", "")), str(link.get("target_id", "")))
            for link in conflicting
        )
        return _action(
            finding,
            classification="unsupported",
            action_kind="report_conflicting_evidence_link",
            related=related,
            command=(
                f"pcl evidence show {evidence_id} --json"
                if evidence_id
                else f"pcl test read {finding.entity_id} --json"
            ),
            reason=(
                "The stored Evidence has a conflicting acceptance target or role; the planner "
                "cannot reinterpret or normalize it."
            ),
        )
    return _action(
        finding,
        classification="unsupported",
        action_kind="report_invalid_test_evidence",
        related=[_entity("evidence", evidence_id)] if evidence_id else [],
        command=(
            f"pcl evidence show {evidence_id} --json"
            if evidence_id
            else f"pcl test read {finding.entity_id} --json"
        ),
        reason=(
            "The stored Test Evidence is missing, drifted, cross-target, wrong-role, or "
            "otherwise invalid; the planner cannot choose a replacement."
        ),
    )


def _goal_packet_link_action(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    finding: LifecycleFinding,
) -> LifecycleRepairAction | None:
    evidence_id = str(finding.details.get("evidence_id", ""))
    if not evidence_id or finding.details.get("proof_type") != "completion_packet":
        return None
    evidence = conn.execute(
        "SELECT type, path FROM evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if evidence is None or evidence["type"] != "completion_packet":
        return None
    if not completion_packet_is_valid_for_goal(
        paths,
        str(evidence["path"]),
        finding.entity_id,
    ):
        return None
    links = conn.execute(
        "SELECT target_type, target_id, link_role FROM evidence_links WHERE evidence_id = ? "
        "ORDER BY target_type, target_id, link_role",
        (evidence_id,),
    ).fetchall()
    if links:
        return None
    return _action(
        finding,
        classification="structural",
        action_kind="add_missing_completion_packet_link",
        related=[_entity("evidence", evidence_id)],
        safe_to_apply=True,
        requires_human=False,
        command=f"pcl evidence show {evidence_id} --json",
        reason=(
            "The validated completion packet already targets this Goal and only its "
            "unambiguous completion-packet link is missing."
        ),
    )


def _action(
    finding: LifecycleFinding,
    *,
    classification: str,
    action_kind: str,
    command: str,
    reason: str,
    related: list[dict[str, str]] | None = None,
    safe_to_apply: bool = False,
    requires_human: bool = True,
) -> LifecycleRepairAction:
    return LifecycleRepairAction(
        finding_code=finding.code,
        classification=classification,
        action_kind=action_kind,
        entity=_entity(finding.entity_type, finding.entity_id),
        related=sorted(
            related or [],
            key=lambda item: (item.get("type", ""), item.get("id", "")),
        ),
        safe_to_apply=safe_to_apply,
        requires_human=requires_human,
        command=command,
        reason=reason,
    )


def _entity(entity_type: str, entity_id: str) -> dict[str, str]:
    return {"type": entity_type, "id": entity_id}
