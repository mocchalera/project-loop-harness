from __future__ import annotations

from pathlib import Path

from pcl.cli import main
from pcl.db import connect
from pcl.paths import resolve_paths
from pcl.validators import (
    ValidationFinding,
    ValidationResult,
    _classify_finding_proof_scopes,
    validate_project,
)


def _classify(root: Path, *findings: ValidationFinding) -> ValidationResult:
    result = ValidationResult(findings=list(findings))
    conn = connect(root / ".project-loop" / "project.db")
    try:
        _classify_finding_proof_scopes(conn, result)
    finally:
        conn.close()
    return result


def test_unknown_finding_defaults_active_without_changing_legacy_fields(tmp_path: Path) -> None:
    message = "Unknown terminal concern"
    command = "pcl --json feature read F-0001"
    finding = ValidationFinding(
        code="future_terminal_concern",
        severity="warning",
        message=message,
        entity={"type": "feature", "id": "F-0001"},
        related=[{"type": "test_case", "id": "TC-0001"}],
        repair_class="inspect",
        suggested_commands=[command],
    )

    payload = finding.to_dict()

    assert payload == {
        "code": "future_terminal_concern",
        "severity": "warning",
        "message": message,
        "entity": {"type": "feature", "id": "F-0001"},
        "related": [{"type": "test_case", "id": "TC-0001"}],
        "repair_class": "inspect",
        "requires_human": False,
        "suggested_commands": [command],
        "proof_scope": "active",
    }


def test_terminal_state_classifies_only_allowlisted_historical_family(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(
        [
            "--root",
            str(tmp_path),
            "feature",
            "add",
            "--name",
            "Legacy",
            "--surface",
            "cli:legacy",
        ]
    ) == 0
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute("UPDATE features SET status = 'done' WHERE id = 'F-0001'")
        conn.commit()
    finally:
        conn.close()

    historical = ValidationFinding(
        code="feature_done_evidence_required",
        severity="warning",
        message="ignored by classifier",
        entity={"type": "feature", "id": "F-0001"},
    )
    active_unknown = ValidationFinding(
        code="future_feature_finding",
        severity="warning",
        message="also ignored by classifier",
        entity={"type": "feature", "id": "F-0001"},
    )
    active_contradiction = ValidationFinding(
        code="feature_done_open_defects",
        severity="error",
        message="not historical while active children exist",
        entity={"type": "feature", "id": "F-0001"},
    )

    result = _classify(tmp_path, historical, active_unknown, active_contradiction)

    assert [finding.proof_scope for finding in result.findings] == [
        "historical",
        "active",
        "active",
    ]
    assert result.finding_counts() == {"active": 2, "historical": 1}


def test_test_finding_requires_durable_terminal_parent(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            """
            INSERT INTO features(id, name, surface, status, confidence, created_at, updated_at)
            VALUES ('F-0001', 'Current', 'cli:test', 'passing', 'medium', 'now', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO test_cases(
                id, feature_id, type, scenario, expected, status, created_at, updated_at
            ) VALUES ('TC-0001', 'F-0001', 'acceptance', 'run', 'pass', 'passing', 'now', 'now')
            """
        )
        conn.commit()
    finally:
        conn.close()
    finding = ValidationFinding(
        code="test_acceptance_evidence_required",
        severity="warning",
        message="proof missing",
        entity={"type": "test_case", "id": "TC-0001"},
    )

    assert _classify(tmp_path, finding).findings[0].proof_scope == "active"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute("UPDATE features SET status = 'done' WHERE id = 'F-0001'")
        conn.commit()
    finally:
        conn.close()
    finding.proof_scope = "active"

    assert _classify(tmp_path, finding).findings[0].proof_scope == "historical"


def test_superseded_evidence_finding_uses_durable_link(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, summary, created_at)
            VALUES ('E-0001', 'adhoc_artifact', 'old.json', 'old', '2026-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, summary, created_at)
            VALUES ('E-0002', 'adhoc_artifact', 'new.json', 'new', '2026-01-02T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
            VALUES ('E-0002', 'evidence', 'E-0001', 'supersedes', '2026-01-02T00:00:00Z')
            """
        )
        conn.commit()
    finally:
        conn.close()
    finding = ValidationFinding(
        code="artifact_missing",
        severity="error",
        message="old artifact missing",
        entity={"type": "evidence", "id": "E-0001"},
    )

    result = _classify(tmp_path, finding)

    assert result.findings[0].proof_scope == "historical"
    assert result.finding_counts() == {"active": 0, "historical": 1}


def test_unknown_code_on_superseded_evidence_defaults_active(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, summary, created_at)
            VALUES ('E-0001', 'adhoc_artifact', 'old.json', 'old', '2026-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, summary, created_at)
            VALUES ('E-0002', 'adhoc_artifact', 'new.json', 'new', '2026-01-02T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
            VALUES ('E-0002', 'evidence', 'E-0001', 'supersedes', '2026-01-02T00:00:00Z')
            """
        )
        conn.commit()
    finally:
        conn.close()
    finding = ValidationFinding(
        code="future_evidence_relationship_contradiction",
        severity="error",
        message="unknown evidence finding",
        entity={"type": "evidence", "id": "E-0001"},
    )

    result = _classify(tmp_path, finding)

    assert result.findings[0].proof_scope == "active"
    assert result.finding_counts() == {"active": 1, "historical": 0}


def test_early_validation_json_includes_deterministic_counts(tmp_path: Path) -> None:
    result = validate_project(resolve_paths(tmp_path))

    assert result.to_dict()["finding_counts"] == {"active": 1, "historical": 0}
