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
    artifact = _json_output(capsys)["evidence"]
    assert artifact["id"] == "E-0001"
    assert artifact["type"] == ADHOC_ARTIFACT_TYPE
    assert artifact["manifest_path"] == ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json"
    assert artifact["members"] == [
        {"path": "pytest-out.txt", "size_bytes": first.stat().st_size, "sha256": _sha256(first)}
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
