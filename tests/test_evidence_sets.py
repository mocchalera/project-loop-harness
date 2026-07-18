from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

import pcl.evidence_sets as evidence_sets_module
from pcl.cli import main
from pcl.contracts.evidence_set import (
    EVIDENCE_SET_CONTRACT_VERSION,
    evidence_set_schema,
    validate_evidence_set,
)
from pcl.db import connect
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.paths import ProjectPaths
from pcl.start import start_work


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "evidence_set"


def _initialized_target(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    paths = resolve_paths(root)
    init_project(paths)
    started = start_work(paths, intent="Test evidence-set completeness")
    return root, str(started["result"]["created_ids"]["task"])


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


def _write_report_manifest(
    root: Path,
    *,
    reports: list[tuple[str, str]],
) -> tuple[Path, Path]:
    work_root = root / "work" / "lp"
    report_dir = work_root / "reports"
    report_dir.mkdir(parents=True)
    items = []
    for kind, status in reports:
        report_path = report_dir / f"{kind}.json"
        report_path.write_text(
            json.dumps({"kind": kind, "status": status}, sort_keys=True),
            encoding="utf-8",
        )
        items.append({"kind": kind, "path": f"reports/{kind}.json", "status": status})
    manifest = report_dir / "report-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "contract_version": "evidence-report-manifest/v1",
                "reports": items,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return work_root, manifest


def _add_evidence(root: Path, report: Path, capsys) -> str:
    assert main([
        "--root", str(root), "evidence", "add", "--file", str(report),
        "--summary", report.stem, "--json",
    ]) == 0
    return str(json.loads(capsys.readouterr().out)["evidence"]["id"])


def test_evidence_set_schema_is_packaged() -> None:
    schema = evidence_set_schema()

    assert schema["$id"].endswith("evidence-set-v1.schema.json")
    assert schema["properties"]["contract_version"]["const"] == EVIDENCE_SET_CONTRACT_VERSION


def test_canonical_evidence_set_fixture_validates(capsys) -> None:
    fixture = FIXTURE_ROOT / "minimal.json"

    assert main([
        "contract", "validate", "--type", EVIDENCE_SET_CONTRACT_VERSION,
        str(fixture), "--json",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "contract_type": EVIDENCE_SET_CONTRACT_VERSION,
        "errors": [],
        "ok": True,
        "path": str(fixture),
    }


def test_validator_rejects_semantically_false_complete_receipt() -> None:
    value = json.loads((FIXTURE_ROOT / "minimal.json").read_text(encoding="utf-8"))
    value["included_reports"][0]["status"] = "fail"

    result = validate_evidence_set(value)

    assert result.ok is False
    assert any("must exactly match required report state" in error for error in result.errors)


def test_plan_is_read_only_and_required_exclusion_is_incomplete(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    work_root, manifest = _write_report_manifest(
        root,
        reports=[
            ("visual_check", "pass"),
            ("box_report", "fail"),
            ("optional_notes", "warning"),
        ],
    )
    visual_id = _add_evidence(root, work_root / "reports" / "visual_check.json", capsys)
    before = _counts(root)

    assert main([
        "--root", str(root), "evidence-set", "plan",
        "--target", f"task:{task_id}",
        "--work-root", str(work_root),
        "--manifest", str(manifest),
        "--required-kind", "visual_check",
        "--required-kind", "box_report",
        "--include", f"visual_check={visual_id}:acceptance",
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["changed"] is False
    assert payload["plan"]["completeness"] == {
        "status": "incomplete",
        "findings": [
            {
                "code": "required_report_excluded",
                "kind": "box_report",
                "path": "reports/box_report.json",
                "severity": "error",
            }
        ],
    }
    assert [item["kind"] for item in payload["plan"]["excluded_reports"]] == [
        "box_report",
        "optional_notes",
    ]
    assert [item["code"] for item in payload["warnings"]] == [
        "evidence_set_report_excluded",
        "evidence_set_report_excluded",
    ]
    assert _counts(root) == before
    assert not (root / ".project-loop" / "evidence" / "evidence-sets").exists()


def test_plan_text_and_warning_output_are_deterministic(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    work_root, manifest = _write_report_manifest(root, reports=[("optional_notes", "warning")])
    args = [
        "--root", str(root), "evidence-set", "plan",
        "--target", f"task:{task_id}", "--work-root", str(work_root),
        "--manifest", str(manifest),
    ]

    assert main(args) == 0
    first = capsys.readouterr()
    assert main(args) == 0
    second = capsys.readouterr()

    assert second.out == first.out
    assert second.err == first.err == (
        "WARNING: Evidence set excluded optional_notes (warning) at "
        "reports/optional_notes.json; required=false.\n"
    )


def test_record_creates_one_evidence_link_and_event_then_show_is_read_only(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    work_root, manifest = _write_report_manifest(
        root,
        reports=[("visual_check", "pass"), ("box_report", "pass")],
    )
    ids = {
        kind: _add_evidence(root, work_root / "reports" / f"{kind}.json", capsys)
        for kind in ("visual_check", "box_report")
    }
    before = _counts(root)
    args = [
        "--root", str(root), "evidence-set", "record",
        "--target", f"task:{task_id}",
        "--work-root", str(work_root),
        "--manifest", str(manifest),
        "--required-kind", "box_report",
        "--required-kind", "visual_check",
        "--include", f"visual_check={ids['visual_check']}:acceptance",
        "--include", f"box_report={ids['box_report']}:supporting",
        "--summary", "Complete LP evidence set",
        "--json",
    ]

    assert main(args) == 0
    recorded = json.loads(capsys.readouterr().out)
    evidence_id = recorded["evidence"]["id"]
    after = _counts(root)

    assert recorded["evidence"]["type"] == "evidence_set"
    assert recorded["evidence"]["completeness_status"] == "complete"
    assert after == {
        "evidence": before["evidence"] + 1,
        "events": before["events"] + 1,
        "outbox": before["outbox"] + 1,
        "links": before["links"] + 1,
    }
    conn = connect(root / ".project-loop" / "project.db")
    try:
        link = conn.execute(
            "SELECT target_type, target_id, link_role FROM evidence_links "
            "WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        event = conn.execute(
            "SELECT event_type FROM events WHERE entity_type = 'evidence' "
            "AND entity_id = ? ORDER BY sequence DESC LIMIT 1",
            (evidence_id,),
        ).fetchone()
    finally:
        conn.close()
    assert tuple(link) == ("task", task_id, "evidence_set")
    assert event["event_type"] == "evidence_set_recorded"

    before_show = _counts(root)
    assert main([
        "--root", str(root), "evidence-set", "show", "--evidence", evidence_id, "--json",
    ]) == 0
    shown = json.loads(capsys.readouterr().out)["evidence_set"]
    assert shown["health"] == "ok"
    assert shown["artifact"]["completeness"]["status"] == "complete"
    assert _counts(root) == before_show


def test_contract_validate_accepts_recorded_artifact(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    work_root, manifest = _write_report_manifest(root, reports=[("visual_check", "pass")])
    evidence_id = _add_evidence(root, work_root / "reports" / "visual_check.json", capsys)
    assert main([
        "--root", str(root), "evidence-set", "record",
        "--target", f"task:{task_id}", "--work-root", str(work_root),
        "--manifest", str(manifest), "--required-kind", "visual_check",
        "--include", f"visual_check={evidence_id}:acceptance",
        "--summary", "One report", "--json",
    ]) == 0
    artifact = root / json.loads(capsys.readouterr().out)["evidence"]["path"]

    assert main([
        "contract", "validate", "--type", EVIDENCE_SET_CONTRACT_VERSION,
        str(artifact), "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_missing_required_kind_is_a_deterministic_incomplete_finding(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    work_root, manifest = _write_report_manifest(root, reports=[("visual_check", "pass")])

    assert main([
        "--root", str(root), "evidence-set", "plan",
        "--target", f"task:{task_id}", "--work-root", str(work_root),
        "--manifest", str(manifest), "--required-kind", "completion_verdict", "--json",
    ]) == 0
    plan = json.loads(capsys.readouterr().out)["plan"]

    assert plan["completeness"]["findings"] == [
        {
            "code": "required_report_missing",
            "kind": "completion_verdict",
            "path": None,
            "severity": "error",
        }
    ]


def test_invalid_inputs_leave_zero_traces(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    work_root, manifest = _write_report_manifest(root, reports=[("visual_check", "pass")])
    evidence_id = _add_evidence(root, work_root / "reports" / "visual_check.json", capsys)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    cases = [
        (str(work_root / "missing.json"), []),
        (str(manifest), ["../escape=E-0001:supporting"]),
        (str(manifest), [f"visual_check={evidence_id}:supporting", f"visual_check={evidence_id}:supporting"]),
    ]
    for manifest_value, includes in cases:
        before = _counts(root)
        args = [
            "--root", str(root), "evidence-set", "record",
            "--target", f"task:{task_id}", "--work-root", str(work_root),
            "--manifest", manifest_value, "--summary", "invalid", "--json",
        ]
        for include in includes:
            args.extend(["--include", include])
        assert main(args) != 0
        capsys.readouterr()
        assert _counts(root) == before

    manifest.write_text("{", encoding="utf-8")
    before = _counts(root)
    assert main([
        "--root", str(root), "evidence-set", "record",
        "--target", f"task:{task_id}", "--work-root", str(work_root),
        "--manifest", str(manifest), "--summary", "malformed", "--json",
    ]) != 0
    capsys.readouterr()
    assert _counts(root) == before

    for report_path in ("reports/missing.json", "../outside.json"):
        manifest.write_text(json.dumps({
            "contract_version": "evidence-report-manifest/v1",
            "reports": [{"kind": "escape", "path": report_path, "status": "pass"}],
        }), encoding="utf-8")
        before = _counts(root)
        assert main([
            "--root", str(root), "evidence-set", "record",
            "--target", f"task:{task_id}", "--work-root", str(work_root),
            "--manifest", str(manifest), "--summary", "invalid report path", "--json",
        ]) != 0
        capsys.readouterr()
        assert _counts(root) == before

    symlink = work_root / "reports" / "escape.json"
    symlink.symlink_to(outside)
    manifest.write_text(json.dumps({
        "contract_version": "evidence-report-manifest/v1",
        "reports": [{"kind": "escape", "path": "reports/escape.json", "status": "pass"}],
    }), encoding="utf-8")
    before = _counts(root)
    assert main([
        "--root", str(root), "evidence-set", "record",
        "--target", f"task:{task_id}", "--work-root", str(work_root),
        "--manifest", str(manifest), "--summary", "symlink escape", "--json",
    ]) != 0
    capsys.readouterr()
    assert _counts(root) == before


def test_show_order_is_stable_with_reverse_unordered_selects(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    work_root, manifest = _write_report_manifest(
        root,
        reports=[("z_report", "pass"), ("a_report", "pass")],
    )
    ids = {
        kind: _add_evidence(root, work_root / "reports" / f"{kind}.json", capsys)
        for kind in ("z_report", "a_report")
    }
    assert main([
        "--root", str(root), "evidence-set", "record",
        "--target", f"task:{task_id}", "--work-root", str(work_root),
        "--manifest", str(manifest),
        "--include", f"z_report={ids['z_report']}:supporting",
        "--include", f"a_report={ids['a_report']}:acceptance",
        "--summary", "ordering", "--json",
    ]) == 0
    evidence_id = json.loads(capsys.readouterr().out)["evidence"]["id"]
    assert main([
        "--root", str(root), "evidence-set", "show", "--evidence", evidence_id, "--json",
    ]) == 0
    normal = capsys.readouterr().out

    conn = sqlite3.connect(root / ".project-loop" / "project.db")
    try:
        conn.execute("PRAGMA reverse_unordered_selects = ON")
    finally:
        conn.close()
    assert main([
        "--root", str(root), "evidence-set", "show", "--evidence", evidence_id, "--json",
    ]) == 0
    assert capsys.readouterr().out == normal


def test_validator_rejects_corrupt_evidence_set_artifact(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    work_root, manifest = _write_report_manifest(root, reports=[])
    assert main([
        "--root", str(root), "evidence-set", "record",
        "--target", f"task:{task_id}", "--work-root", str(work_root),
        "--manifest", str(manifest), "--summary", "empty honest set", "--json",
    ]) == 0
    path = root / json.loads(capsys.readouterr().out)["evidence"]["path"]
    value = json.loads(path.read_text(encoding="utf-8"))
    value["contract_version"] = "evidence-set/v999"
    path.write_text(json.dumps(value), encoding="utf-8")

    assert main(["--root", str(root), "validate", "--strict", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert any("Evidence set" in error and "contract" in error for error in payload["errors"])


def _record_strict_evidence_set_fixture(tmp_path: Path, capsys) -> tuple[Path, dict]:
    root, task_id = _initialized_target(tmp_path)
    work_root, manifest = _write_report_manifest(root, reports=[])
    assert main([
        "--root", str(root), "evidence-set", "record",
        "--target", f"task:{task_id}",
        "--work-root", str(work_root),
        "--manifest", str(manifest),
        "--summary", "strict Evidence Set fixture",
        "--json",
    ]) == 0
    return root, json.loads(capsys.readouterr().out)["evidence"]


def test_strict_evidence_set_resolver_uses_one_open_and_is_read_only(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    root, evidence = _record_strict_evidence_set_fixture(tmp_path, capsys)
    artifact_path = root / evidence["path"]
    artifact_bytes = artifact_path.read_bytes()
    opens = 0
    real_open = os.open

    def counted_open(path, flags, *args, **kwargs):
        nonlocal opens
        if Path(path) == artifact_path:
            opens += 1
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("pcl.strict_evidence.os.open", counted_open)
    before = _counts(root)

    result = evidence_sets_module.resolve_strict_evidence_set(
        ProjectPaths(root), evidence_id=evidence["id"]
    )

    assert result["ok"] is True
    assert result["health"] == "ok"
    assert result["findings"] == []
    assert result["artifact_bytes"] == artifact_bytes
    assert result["artifact"] == json.loads(artifact_bytes)
    assert opens == 1
    assert _counts(root) == before
    assert artifact_path.read_bytes() == artifact_bytes


def test_strict_evidence_set_resolver_rejects_missing_and_duplicate_anchors(
    tmp_path: Path,
    capsys,
) -> None:
    missing_root, missing = _record_strict_evidence_set_fixture(tmp_path / "missing", capsys)
    conn = connect(missing_root / ".project-loop" / "project.db")
    try:
        conn.execute(
            "UPDATE events SET event_type = 'corrupt_evidence_set_record' "
            "WHERE event_type = 'evidence_set_recorded' "
            "AND entity_type = 'evidence' AND entity_id = ?",
            (missing["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    missing_result = evidence_sets_module.resolve_strict_evidence_set(
        ProjectPaths(missing_root), evidence_id=missing["id"]
    )
    assert [item["code"] for item in missing_result["findings"]] == [
        "strict_event_anchor_missing"
    ]

    duplicate_root, duplicate = _record_strict_evidence_set_fixture(
        tmp_path / "duplicate", capsys
    )
    conn = connect(duplicate_root / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT payload_json, created_at FROM events "
            "WHERE event_type = 'evidence_set_recorded' AND entity_type = 'evidence' "
            "AND entity_id = ?",
            (duplicate["id"],),
        ).fetchone()
        sequence = int(conn.execute("SELECT MAX(sequence) + 1 FROM events").fetchone()[0])
        conn.execute(
            "INSERT INTO events(id, sequence, event_type, entity_type, entity_id, payload_json, created_at) "
            "VALUES (?, ?, 'evidence_set_recorded', 'evidence', ?, ?, ?)",
            ("EV-DUPLICATESET", sequence, duplicate["id"], row["payload_json"], row["created_at"]),
        )
        conn.commit()
    finally:
        conn.close()

    duplicate_result = evidence_sets_module.resolve_strict_evidence_set(
        ProjectPaths(duplicate_root), evidence_id=duplicate["id"]
    )
    assert [item["code"] for item in duplicate_result["findings"]] == [
        "strict_event_anchor_ambiguous"
    ]


def test_strict_evidence_set_resolver_rejects_rewrite_but_legacy_show_stays_ok(
    tmp_path: Path,
    capsys,
) -> None:
    root, evidence = _record_strict_evidence_set_fixture(tmp_path, capsys)
    artifact_path = root / evidence["path"]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["work_root"] = "work/rewritten"
    artifact_path.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")

    strict = evidence_sets_module.resolve_strict_evidence_set(
        ProjectPaths(root), evidence_id=evidence["id"]
    )
    assert [item["code"] for item in strict["findings"]] == [
        "strict_evidence_set_hash_mismatch"
    ]

    assert main([
        "--root", str(root), "evidence-set", "show", "--evidence", evidence["id"], "--json",
    ]) == 0
    legacy = json.loads(capsys.readouterr().out)["evidence_set"]
    assert legacy["health"] == "ok"
    assert legacy["artifact"]["work_root"] == "work/rewritten"


def test_strict_evidence_set_resolver_rejects_event_metadata_mismatch(
    tmp_path: Path,
    capsys,
) -> None:
    root, evidence = _record_strict_evidence_set_fixture(tmp_path, capsys)
    conn = connect(root / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT id, payload_json FROM events WHERE event_type = 'evidence_set_recorded' "
            "AND entity_type = 'evidence' AND entity_id = ?",
            (evidence["id"],),
        ).fetchone()
        payload = json.loads(row["payload_json"])
        payload["included_report_count"] += 1
        conn.execute(
            "UPDATE events SET payload_json = ? WHERE id = ?",
            (json.dumps(payload), row["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    result = evidence_sets_module.resolve_strict_evidence_set(
        ProjectPaths(root), evidence_id=evidence["id"]
    )
    assert [item["code"] for item in result["findings"]] == [
        "strict_evidence_set_event_mismatch"
    ]


def test_strict_evidence_set_resolver_rejects_malformed_anchor(
    tmp_path: Path,
    capsys,
) -> None:
    root, evidence = _record_strict_evidence_set_fixture(tmp_path, capsys)
    conn = connect(root / ".project-loop" / "project.db")
    try:
        conn.execute(
            "UPDATE events SET payload_json = '{' "
            "WHERE event_type = 'evidence_set_recorded' "
            "AND entity_type = 'evidence' AND entity_id = ?",
            (evidence["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    result = evidence_sets_module.resolve_strict_evidence_set(
        ProjectPaths(root), evidence_id=evidence["id"]
    )
    assert [item["code"] for item in result["findings"]] == [
        "strict_event_anchor_invalid"
    ]
