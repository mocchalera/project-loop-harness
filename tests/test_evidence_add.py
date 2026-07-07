from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pcl.cli import main
from pcl.db import connect
from pcl.evidence import ADHOC_ARTIFACT_TYPE, ADHOC_BUNDLE_TYPE, ADHOC_EVIDENCE_CONTRACT_VERSION


def _json_output(capsys) -> dict[str, Any]:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _db_rows(root: Path, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _event_count(root: Path) -> int:
    return len((root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines())


def _manifest(root: Path, relative_path: str) -> dict[str, Any]:
    return json.loads((root / relative_path).read_text(encoding="utf-8"))


def _adhoc_manifests(root: Path) -> list[Path]:
    return sorted((root / ".project-loop" / "evidence" / "adhoc").glob("*.json"))


def _assert_evidence_add_error(capsys, code: str) -> None:
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == code


def _assert_no_adhoc_traces(root: Path, *, before_events: int, before_manifests: list[Path]) -> None:
    assert _db_rows(root, "SELECT id FROM evidence ORDER BY id") == []
    assert _event_count(root) == before_events
    assert _adhoc_manifests(root) == before_manifests


def _insert_context_receipt(root: Path, *, evidence_id: str = "E-0001") -> None:
    receipt_dir = root / ".project-loop" / "evidence" / "context-receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    relative_path = f".project-loop/evidence/context-receipts/{evidence_id.lower()}-impact-v0.json"
    payload = {
        "contract_version": "context-receipt/v0",
        "evidence_id": evidence_id,
        "receipt_path": relative_path,
        "verification_suggestions": [
            {
                "id": f"{evidence_id}/VS-01",
                "command": "python3 -m pytest tests/test_evidence_add.py",
                "reason": "test_hint:path_token_match",
            }
        ],
    }
    (root / relative_path).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    conn = connect(root / ".project-loop" / "project.db")
    try:
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                "context_receipt",
                relative_path,
                "test setup",
                "Context receipt.",
                "2026-07-07T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_evidence_add_selects_artifact_and_bundle_types(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    first = tmp_path / "pytest-out.txt"
    second = tmp_path / "viewport.json"
    first.write_text("pytest passed\n", encoding="utf-8")
    second.write_text('{"viewport":"mobile"}\n', encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "pytest-out.txt",
        "--summary",
        "pytest run",
        "--command",
        "python3 -m pytest",
        "--json",
    ]) == 0
    payload = _json_output(capsys)
    assert "warnings" not in payload
    artifact = payload["evidence"]
    assert artifact["id"] == "E-0001"
    assert artifact["type"] == ADHOC_ARTIFACT_TYPE
    assert artifact["manifest_path"] == ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json"
    assert artifact["members"] == [
        {
            "path": "pytest-out.txt",
            "path_scope": "in_project",
            "size_bytes": first.stat().st_size,
            "sha256": _sha256(first),
        }
    ]
    manifest = _manifest(tmp_path, artifact["manifest_path"])
    assert manifest["contract_version"] == ADHOC_EVIDENCE_CONTRACT_VERSION
    assert manifest["members"] == artifact["members"]

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "pytest-out.txt",
        "--file",
        "viewport.json",
        "--summary",
        "visual QA bundle",
        "--json",
    ]) == 0
    bundle = _json_output(capsys)["evidence"]
    assert bundle["id"] == "E-0002"
    assert bundle["type"] == ADHOC_BUNDLE_TYPE
    assert [member["path"] for member in bundle["members"]] == ["pytest-out.txt", "viewport.json"]

    rows = _db_rows(tmp_path, "SELECT id, type, path, command, summary FROM evidence ORDER BY id")
    assert rows == [
        {
            "id": "E-0001",
            "type": ADHOC_ARTIFACT_TYPE,
            "path": ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json",
            "command": "python3 -m pytest",
            "summary": "pytest run",
        },
        {
            "id": "E-0002",
            "type": ADHOC_BUNDLE_TYPE,
            "path": ".project-loop/evidence/adhoc/e-0002-adhoc-v0.json",
            "command": None,
            "summary": "visual QA bundle",
        },
    ]


def test_evidence_add_records_outside_project_scope_with_json_warning(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "report.txt"
    outside_file.write_text("outside report\n", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        str(outside_file),
        "--summary",
        "outside report",
        "--json",
    ]) == 0
    payload = _json_output(capsys)
    member = payload["evidence"]["members"][0]
    assert member == {
        "path": member["path"],
        "path_scope": "outside_project",
        "size_bytes": outside_file.stat().st_size,
        "sha256": _sha256(outside_file),
    }
    assert member["path"].startswith("../")
    assert payload["warnings"] == [f"evidence member outside project root: {member['path']}"]

    manifest = _manifest(tmp_path, payload["evidence"]["manifest_path"])
    assert manifest["members"] == [member]

    [event] = _db_rows(
        tmp_path,
        "SELECT payload_json FROM events WHERE event_type = 'adhoc_evidence_recorded'",
    )
    event_payload = json.loads(event["payload_json"])
    assert event_payload["members"] == [member]


def test_evidence_add_prints_outside_project_warning_in_text_mode(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside-text"
    outside_dir.mkdir()
    outside_file = outside_dir / "report.txt"
    outside_file.write_text("outside text report\n", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        str(outside_file),
        "--summary",
        "outside text report",
    ]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("E-0001 adhoc_artifact .project-loop/evidence/adhoc/e-0001-adhoc-v0.json")
    assert "WARNING: evidence member outside project root: ../" in captured.err


def test_evidence_add_blocks_outside_project_when_configured_and_leaves_zero_traces(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    (tmp_path / "pcl.yaml").write_text(
        (tmp_path / "pcl.yaml").read_text(encoding="utf-8")
        + "\nevidence:\n  allow_outside_root: false\n",
        encoding="utf-8",
    )
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside-blocked"
    outside_dir.mkdir()
    outside_file = outside_dir / "report.txt"
    outside_file.write_text("blocked outside report\n", encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        str(outside_file),
        "--summary",
        "blocked outside report",
        "--json",
    ]) == 2
    _assert_evidence_add_error(capsys, "evidence_add_outside_root")
    _assert_no_adhoc_traces(tmp_path, before_events=before_events, before_manifests=before_manifests)

    clean_file = tmp_path / "clean.txt"
    clean_file.write_text("clean\n", encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "clean.txt",
        "--summary",
        "clean",
        "--json",
    ]) == 0
    assert _json_output(capsys)["evidence"]["id"] == "E-0001"


def test_evidence_add_blocks_sensitive_path_without_flag_and_leaves_zero_traces(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    env_file = tmp_path / ".env"
    env_file.write_text("TOKEN=example\n", encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        ".env",
        "--summary",
        "env file",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "evidence_add_sensitive_path"
    assert payload["error"]["details"]["matches"] == [{"path": ".env", "pattern": ".env"}]
    assert payload["error"]["details"]["allow_flag"] == "--allow-sensitive-evidence"
    _assert_no_adhoc_traces(tmp_path, before_events=before_events, before_manifests=before_manifests)

    clean_file = tmp_path / "clean.txt"
    clean_file.write_text("clean\n", encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "clean.txt",
        "--summary",
        "clean",
        "--json",
    ]) == 0
    assert _json_output(capsys)["evidence"]["id"] == "E-0001"


def test_evidence_add_records_sensitive_path_with_flag_and_warning(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    env_file = tmp_path / ".env"
    env_file.write_text("TOKEN=example\n", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        ".env",
        "--summary",
        "explicit env evidence",
        "--allow-sensitive-evidence",
        "--json",
    ]) == 0
    payload = _json_output(capsys)
    member = payload["evidence"]["members"][0]
    assert member == {
        "path": ".env",
        "path_scope": "in_project",
        "size_bytes": env_file.stat().st_size,
        "sha256": _sha256(env_file),
        "sensitive_pattern": ".env",
    }
    assert payload["evidence"]["sensitive_path_warning_count"] == 1
    assert payload["warnings"] == [
        "evidence member matches sensitive filename pattern: .env "
        "(pattern: .env); PLH checks path shapes only and does not scan file contents"
    ]

    manifest = _manifest(tmp_path, payload["evidence"]["manifest_path"])
    assert manifest["members"] == [member]
    assert manifest["sensitive_path_warning_count"] == 1
    [event] = _db_rows(
        tmp_path,
        "SELECT payload_json FROM events WHERE event_type = 'adhoc_evidence_recorded'",
    )
    assert json.loads(event["payload_json"])["sensitive_path_warning_count"] == 1


def test_evidence_add_sensitive_guard_uses_basename_custom_patterns_and_wins_order(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    (tmp_path / "pcl.yaml").write_text(
        (tmp_path / "pcl.yaml").read_text(encoding="utf-8")
        + "\nevidence:\n  allow_outside_root: false\n  sensitive_exclude:\n    - '*.sqlite3'\n",
        encoding="utf-8",
    )
    outside_dir = tmp_path.parent / f"{tmp_path.name}-sensitive-outside"
    outside_dir.mkdir()
    outside_sensitive = outside_dir / "credentials-prod.json"
    outside_sensitive.write_text('{"token":"example"}\n', encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        str(outside_sensitive),
        "--summary",
        "outside sensitive",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "evidence_add_sensitive_path"
    assert payload["error"]["details"]["matches"][0]["pattern"] == "credentials*.json"
    _assert_no_adhoc_traces(tmp_path, before_events=before_events, before_manifests=before_manifests)

    custom_sensitive = tmp_path / "local.sqlite3"
    custom_sensitive.write_text("sqlite shape\n", encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "local.sqlite3",
        "--summary",
        "custom sensitive",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "evidence_add_sensitive_path"
    assert payload["error"]["details"]["matches"] == [{"path": "local.sqlite3", "pattern": "*.sqlite3"}]
    _assert_no_adhoc_traces(tmp_path, before_events=before_events, before_manifests=before_manifests)


def test_evidence_add_sensitive_bundle_blocks_without_partial_manifest(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    clean_file = tmp_path / "clean.txt"
    env_file = tmp_path / ".env"
    clean_file.write_text("clean\n", encoding="utf-8")
    env_file.write_text("TOKEN=example\n", encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "clean.txt",
        "--file",
        ".env",
        "--summary",
        "mixed bundle",
        "--json",
    ]) == 2
    _assert_evidence_add_error(capsys, "evidence_add_sensitive_path")
    _assert_no_adhoc_traces(tmp_path, before_events=before_events, before_manifests=before_manifests)


def test_evidence_add_manifest_is_deterministic_except_id_and_created_at(
    tmp_path: Path,
    capsys,
) -> None:
    manifests: list[dict[str, Any]] = []
    for run_name in ["run-a", "run-b"]:
        root = tmp_path / run_name
        root.mkdir()
        _init(root, capsys)
        work = root / "work"
        work.mkdir()
        (work / "a.txt").write_text("alpha\n", encoding="utf-8")
        (work / "b.txt").write_text("beta\n", encoding="utf-8")
        assert main([
            "--root",
            str(root),
            "evidence",
            "add",
            "--file",
            "work/a.txt",
            "--file",
            "work/b.txt",
            "--summary",
            "same bundle",
            "--command",
            "same command",
            "--json",
        ]) == 0
        evidence = _json_output(capsys)["evidence"]
        manifest = _manifest(root, evidence["manifest_path"])
        manifest.pop("created_at")
        manifest.pop("evidence_id")
        manifests.append(manifest)

    assert manifests[0] == manifests[1]
    assert [member["path"] for member in manifests[0]["members"]] == ["work/a.txt", "work/b.txt"]


def test_evidence_add_typed_errors_leave_no_state(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _init(tmp_path, capsys)
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("captured output\n", encoding="utf-8")
    before_events = _event_count(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "missing.txt",
        "--summary",
        "missing",
        "--json",
    ]) == 2
    _assert_evidence_add_error(capsys, "evidence_add_missing_file")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "artifact.txt",
        "--file",
        "./artifact.txt",
        "--summary",
        "duplicate",
        "--json",
    ]) == 2
    _assert_evidence_add_error(capsys, "evidence_add_duplicate_path")

    original_open = Path.open
    unreadable_resolved = artifact.resolve()

    def unreadable_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if self.resolve() == unreadable_resolved and mode == "rb":
            raise PermissionError("permission denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unreadable_open)
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "artifact.txt",
        "--summary",
        "unreadable",
        "--json",
    ]) == 2
    _assert_evidence_add_error(capsys, "evidence_add_unreadable_file")

    assert _db_rows(tmp_path, "SELECT id FROM evidence ORDER BY id") == []
    assert _event_count(tmp_path) == before_events
    assert _adhoc_manifests(tmp_path) == []


def test_strict_validate_checks_adhoc_manifest_and_warns_on_member_drift(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("original\n", encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "artifact.txt",
        "--summary",
        "recorded artifact",
        "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys) == {"errors": [], "ok": True, "warnings": []}

    artifact.unlink()
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    deleted_member = _json_output(capsys)
    assert deleted_member["ok"] is True
    assert deleted_member["errors"] == []
    assert deleted_member["warnings"] == [
        "Adhoc evidence E-0001 member artifact.txt drifted: missing."
    ]

    artifact.write_text("changed\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    edited_member = _json_output(capsys)
    assert edited_member["ok"] is True
    assert edited_member["errors"] == []
    assert edited_member["warnings"] == [
        "Adhoc evidence E-0001 member artifact.txt drifted: hash mismatch."
    ]

    (tmp_path / evidence["manifest_path"]).unlink()
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    missing_manifest = _json_output(capsys)
    assert missing_manifest["ok"] is False
    assert (
        "Adhoc evidence E-0001 manifest does not exist: "
        ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json."
    ) in missing_manifest["errors"]


def test_strict_validate_accepts_pre_0096_manifest_without_path_guard_fields(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("original\n", encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "artifact.txt",
        "--summary",
        "recorded artifact",
        "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]
    manifest_path = tmp_path / evidence["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for member in manifest["members"]:
        member.pop("path_scope", None)
    manifest.pop("sensitive_path_warning_count", None)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys) == {"errors": [], "ok": True, "warnings": []}


def test_strict_validate_warns_on_outside_project_member_path(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    outside_dir = tmp_path.parent / f"{tmp_path.name}-validate-outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "report.txt"
    outside_file.write_text("outside report\n", encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        str(outside_file),
        "--summary",
        "outside report",
        "--json",
    ]) == 0
    member_path = _json_output(capsys)["evidence"]["members"][0]["path"]

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys) == {
        "errors": [],
        "ok": True,
        "warnings": [f"Adhoc evidence E-0001 member {member_path} is outside the project root."],
    }


def test_strict_validate_rejects_invalid_path_guard_fields(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "first.txt",
        "--file",
        "second.txt",
        "--summary",
        "bundle",
        "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]
    manifest_path = tmp_path / evidence["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sensitive_path_warning_count"] = -1
    manifest["members"][0]["path_scope"] = "workspace"
    manifest["members"][1]["sensitive_pattern"] = 123
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["warnings"] == []
    assert payload["errors"] == [
        "Adhoc evidence E-0001 manifest sensitive_path_warning_count is invalid: -1.",
        "Adhoc evidence E-0001 manifest member first.txt path_scope is invalid.",
        "Adhoc evidence E-0001 manifest member second.txt sensitive_pattern is invalid.",
    ]


def test_evidence_add_supports_verification_feedback_executed_claim(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _insert_context_receipt(tmp_path)
    artifact = tmp_path / "pytest-out.txt"
    artifact.write_text("pytest passed\n", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "pytest-out.txt",
        "--summary",
        "pytest run for E-0001/VS-01",
        "--json",
    ]) == 0
    evidence_id = _json_output(capsys)["evidence"]["id"]
    assert evidence_id == "E-0002"

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "feedback",
        "--suggestion",
        "E-0001/VS-01",
        "--status",
        "executed",
        "--result",
        "passed",
        "--evidence",
        evidence_id,
        "--json",
    ]) == 0
    feedback = _json_output(capsys)["feedback"]
    assert feedback["status"] == "executed"
    assert feedback["result"] == "passed"
    assert feedback["supporting_evidence_id"] == evidence_id


def test_evidence_add_preserves_strict_audit_log_integrity(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("audit evidence\n", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "artifact.txt",
        "--summary",
        "audit evidence",
        "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys) == {"errors": [], "ok": True, "warnings": []}

    db_events = _db_rows(
        tmp_path,
        "SELECT id, event_type, entity_type, entity_id, payload_json FROM events "
        "WHERE event_type = 'adhoc_evidence_recorded'",
    )
    jsonl_events = [
        json.loads(line)
        for line in (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if json.loads(line)["event_type"] == "adhoc_evidence_recorded"
    ]
    assert len(db_events) == 1
    assert len(jsonl_events) == 1
    assert db_events[0]["id"] == jsonl_events[0]["id"]
    assert db_events[0]["entity_type"] == "evidence"
    assert db_events[0]["entity_id"] == evidence["id"]
    assert json.loads(db_events[0]["payload_json"]) == jsonl_events[0]["payload"]
