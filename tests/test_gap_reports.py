from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from pcl.cli import main
from pcl.contracts.gap_report import (
    GAP_REPORT_CONTRACT_VERSION,
    gap_report_schema,
    validate_gap_report,
)
from pcl.db import connect
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.start import start_work


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "gap_report"


def _initialized_target(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "project"
    root.mkdir()
    paths = resolve_paths(root)
    init_project(paths)
    started = start_work(paths, intent="Diagnose one harness gap")
    return root, str(started["result"]["created_ids"]["task"])


def _report_for_target(
    tmp_path: Path,
    target_id: str,
    *,
    gap_class: str = "context",
    lesson_evidence_refs: list[str] | None = None,
) -> Path:
    value = json.loads((FIXTURE_ROOT / "minimal.json").read_text(encoding="utf-8"))
    value["target"]["id"] = target_id
    value["gap_class"] = gap_class
    if lesson_evidence_refs is not None:
        value["candidate_lessons"][0]["evidence_refs"] = lesson_evidence_refs
    path = tmp_path / f"gap-{gap_class}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            "evidence": int(conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]),
            "events": int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
            "outbox": int(conn.execute("SELECT COUNT(*) FROM outbox_records").fetchone()[0]),
            "links": int(conn.execute("SELECT COUNT(*) FROM evidence_links").fetchone()[0]),
        }
    finally:
        conn.close()


def _json_output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_gap_report_schema_and_validator_accept_minimal_fixture() -> None:
    value = json.loads((FIXTURE_ROOT / "minimal.json").read_text(encoding="utf-8"))

    result = validate_gap_report(value)
    schema = gap_report_schema()

    assert result.ok is True
    assert result.errors == ()
    assert schema["$id"].endswith("gap-report-v1.schema.json")
    assert schema["additionalProperties"] is False


def test_gap_report_validator_fails_closed_on_unknowns_duplicates_and_non_finite() -> None:
    value = json.loads((FIXTURE_ROOT / "minimal.json").read_text(encoding="utf-8"))
    value["unexpected"] = True
    value["gap_class"] = "guess"
    value["target"] = {"type": "agent_job", "id": "T-0001"}
    value["candidate_lessons"].append(deepcopy(value["candidate_lessons"][0]))
    value["candidate_lessons"][0]["confidence"] = float("nan")

    result = validate_gap_report(value)

    assert result.ok is False
    assert any("$.unexpected: additional property" in error for error in result.errors)
    assert any("$.gap_class: must be one of" in error for error in result.errors)
    assert any("$.target.id: has invalid format" in error for error in result.errors)
    assert any("lesson_id: must be unique" in error for error in result.errors)
    assert any("non-finite JSON numbers" in error for error in result.errors)


@pytest.mark.parametrize(
    ("target_type", "target_id"),
    [
        ("goal", "G-0001"),
        ("task", "T-0001"),
        ("feature", "F-0001"),
        ("defect", "D-0001"),
        ("workflow_run", "WR-0001"),
        ("agent_job", "J-0001"),
    ],
)
def test_gap_report_validator_supports_execution_targets(
    target_type: str,
    target_id: str,
) -> None:
    value = json.loads((FIXTURE_ROOT / "minimal.json").read_text(encoding="utf-8"))
    value["target"] = {"type": target_type, "id": target_id}

    assert validate_gap_report(value).ok is True


def test_gap_report_validator_handles_non_string_enums_without_crashing() -> None:
    value = json.loads((FIXTURE_ROOT / "minimal.json").read_text(encoding="utf-8"))
    value["target"] = {"type": {"invalid": True}, "id": "T-0001"}
    value["gap_class"] = ["context"]
    value["candidate_lessons"][0]["durable_owner"] = {"invalid": True}

    result = validate_gap_report(value)

    assert result.ok is False
    assert any("$.target.type: must be one of" in error for error in result.errors)
    assert any("$.gap_class: must be one of" in error for error in result.errors)
    assert any(".durable_owner: must be one of" in error for error in result.errors)


def test_contract_cli_validates_gap_report_without_project_state(capsys, tmp_path: Path) -> None:
    fixture = FIXTURE_ROOT / "minimal.json"

    assert main([
        "--root",
        str(tmp_path),
        "contract",
        "validate",
        "--type",
        GAP_REPORT_CONTRACT_VERSION,
        str(fixture),
        "--json",
    ]) == 0

    assert _json_output(capsys) == {
        "contract_type": GAP_REPORT_CONTRACT_VERSION,
        "errors": [],
        "ok": True,
        "path": str(fixture),
    }
    assert list(tmp_path.iterdir()) == []


def test_contract_cli_rejects_invalid_and_non_finite_gap_reports(
    capsys,
    tmp_path: Path,
) -> None:
    invalid = json.loads((FIXTURE_ROOT / "minimal.json").read_text(encoding="utf-8"))
    invalid["gap_class"] = "guess"
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(invalid), encoding="utf-8")

    assert main([
        "contract", "validate", "--type", GAP_REPORT_CONTRACT_VERSION,
        str(invalid_path), "--json",
    ]) == 1
    invalid_payload = _json_output(capsys)
    assert any("$.gap_class: must be one of" in error for error in invalid_payload["errors"])

    non_finite_path = tmp_path / "non-finite.json"
    non_finite_path.write_text('{"contract_version":"gap-report/v1","value":NaN}', encoding="utf-8")
    assert main([
        "contract", "validate", "--type", GAP_REPORT_CONTRACT_VERSION,
        str(non_finite_path), "--json",
    ]) == 2
    non_finite_payload = _json_output(capsys)
    assert non_finite_payload["error"]["code"] == "invalid_input"


def test_gap_add_dry_run_is_zero_mutation(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    report = _report_for_target(tmp_path, task_id)
    before = _counts(root)

    assert main([
        "--root", str(root), "gap", "add", str(report),
        "--summary", "Observed missing context", "--dry-run", "--json",
    ]) == 0
    payload = _json_output(capsys)

    assert payload["dry_run"] is True
    assert payload["planned"]["target"] == {"type": "task", "id": task_id}
    assert payload["planned"]["gap_class"] == "context"
    assert _counts(root) == before
    assert not (root / ".project-loop" / "evidence" / "gap-reports").exists()


def test_gap_add_show_list_and_duplicate_rejection(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    report = _report_for_target(tmp_path, task_id)
    before = _counts(root)

    assert main([
        "--root", str(root), "gap", "add", str(report),
        "--summary", "Observed missing context", "--json",
    ]) == 0
    added = _json_output(capsys)
    evidence = added["evidence"]

    assert _counts(root) == {
        "evidence": before["evidence"] + 1,
        "events": before["events"] + 1,
        "outbox": before["outbox"] + 1,
        "links": before["links"] + 1,
    }
    assert main([
        "--root", str(root), "gap", "show", "--evidence", evidence["id"], "--json",
    ]) == 0
    shown = _json_output(capsys)["gap_report"]
    assert shown["health"] == "ok"
    assert shown["gap_class"] == "context"
    assert shown["candidate_lessons"][0]["promotion_status"] == "candidate"

    assert main([
        "--root", str(root), "gap", "list", "--target", f"task:{task_id}",
        "--gap-class", "context", "--json",
    ]) == 0
    listed = _json_output(capsys)
    assert [item["evidence_id"] for item in listed["gap_reports"]] == [evidence["id"]]

    before_duplicate = _counts(root)
    assert main([
        "--root", str(root), "gap", "add", str(report),
        "--summary", "Duplicate", "--json",
    ]) == 1
    duplicate = _json_output(capsys)
    assert duplicate["error"]["code"] == "gap_report_duplicate"
    assert _counts(root) == before_duplicate


def test_gap_add_rejects_unknown_target_without_mutation(tmp_path: Path, capsys) -> None:
    root, _ = _initialized_target(tmp_path)
    report = _report_for_target(tmp_path, "T-9999")
    before = _counts(root)

    assert main([
        "--root", str(root), "gap", "add", str(report),
        "--summary", "Unknown target", "--json",
    ]) == 1

    assert _json_output(capsys)["error"]["code"] == "gap_report_unknown_target"
    assert _counts(root) == before


def test_gap_add_rejects_unknown_supporting_evidence_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    report = _report_for_target(
        tmp_path,
        task_id,
        lesson_evidence_refs=["evidence:E-9999"],
    )
    before = _counts(root)

    assert main([
        "--root", str(root), "gap", "add", str(report),
        "--summary", "Unknown Evidence", "--json",
    ]) == 1

    assert _json_output(capsys)["error"]["code"] == "gap_report_unknown_evidence_ref"
    assert _counts(root) == before


def test_gap_promote_requires_human_and_records_pending_application(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    report = _report_for_target(tmp_path, task_id)
    assert main([
        "--root", str(root), "gap", "add", str(report),
        "--summary", "Promotion candidate", "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]
    before = _counts(root)

    assert main([
        "--root", str(root), "gap", "promote", evidence["id"],
        "--lesson", "lesson-release-route", "--actor", "agent:codex",
        "--actor-kind", "agent", "--reason", "Self-approved", "--json",
    ]) == 1
    assert _json_output(capsys)["error"]["code"] == "gap_lesson_human_approval_required"
    assert _counts(root) == before

    promote_args = [
        "--root", str(root), "gap", "promote", evidence["id"],
        "--lesson", "lesson-release-route", "--actor", "human:owner",
        "--actor-kind", "human", "--recorded-by", "agent:codex",
        "--recorder-kind", "agent", "--source-kind", "cockpit",
        "--source-ref", "cockpit:e22916a5", "--reason", "Reviewed supporting Evidence",
        "--json",
    ]
    assert main(promote_args) == 0
    promoted = _json_output(capsys)
    assert promoted["changed"] is True
    approval = promoted["promotion"]
    assert approval["application_status"] == "pending"
    assert approval["lesson_id"] == "lesson-release-route"
    assert approval["durable_owner"] == "agents_md"
    assert approval["approval_provenance"]["source_kind"] == "cockpit"
    assert approval["approval_provenance"]["source_ref"] == "cockpit:e22916a5"
    assert approval["approval_provenance"]["bound_evidence"] == {
        "id": evidence["id"],
        "artifact_sha256": evidence["artifact_sha256"],
    }

    after = _counts(root)
    assert main(promote_args) == 0
    duplicate = _json_output(capsys)
    assert duplicate["changed"] is False
    assert _counts(root) == after

    assert main([
        "--root", str(root), "gap", "show", "--evidence", evidence["id"], "--json",
    ]) == 0
    shown = _json_output(capsys)["gap_report"]
    lesson = shown["candidate_lessons"][0]
    assert lesson["promotion_status"] == "approved_pending_application"
    assert lesson["promotion"]["application_status"] == "pending"


def test_gap_promote_rejects_uncited_or_tampered_lesson(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    uncited = _report_for_target(tmp_path, task_id, lesson_evidence_refs=[])
    assert main([
        "--root", str(root), "gap", "add", str(uncited),
        "--summary", "Uncited candidate", "--json",
    ]) == 0
    uncited_evidence = _json_output(capsys)["evidence"]
    before_uncited = _counts(root)

    assert main([
        "--root", str(root), "gap", "promote", uncited_evidence["id"],
        "--lesson", "lesson-release-route", "--actor", "human:owner",
        "--reason", "No corroboration", "--json",
    ]) == 1
    assert _json_output(capsys)["error"]["code"] == "gap_lesson_evidence_required"
    assert _counts(root) == before_uncited

    cited = _report_for_target(tmp_path, task_id, gap_class="proof")
    assert main([
        "--root", str(root), "gap", "add", str(cited),
        "--summary", "Tamper candidate", "--json",
    ]) == 0
    cited_evidence = _json_output(capsys)["evidence"]
    artifact = root / cited_evidence["path"]
    value = json.loads(artifact.read_text(encoding="utf-8"))
    original = artifact.read_text(encoding="utf-8")
    value["earliest_failed_handoff"]["description"] = value[
        "earliest_failed_handoff"
    ]["description"][:-1] + "!"
    changed = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert len(changed.encode("utf-8")) == len(original.encode("utf-8"))
    artifact.write_text(changed, encoding="utf-8")

    assert main([
        "--root", str(root), "gap", "show", "--evidence", cited_evidence["id"], "--json",
    ]) == 0
    shown = _json_output(capsys)["gap_report"]
    assert shown["health"] == "warning"
    assert "artifact_hash_mismatch" in {item["code"] for item in shown["findings"]}

    before_tampered = _counts(root)
    assert main([
        "--root", str(root), "gap", "promote", cited_evidence["id"],
        "--lesson", "lesson-release-route", "--actor", "human:owner",
        "--reason", "Tampered", "--json",
    ]) == 1
    assert _json_output(capsys)["error"]["code"] == "gap_report_unhealthy"
    assert _counts(root) == before_tampered
