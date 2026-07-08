from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from typing import Any

import pcl.migrations as migrations_module
from pcl import evidence as evidence_module
from pcl.cli import main
from pcl.db import connect
from pcl.evidence import ADHOC_ARTIFACT_TYPE, ADHOC_BUNDLE_TYPE, ADHOC_EVIDENCE_CONTRACT_VERSION
from pcl.paths import ProjectPaths


REPO_ROOT = Path(__file__).resolve().parents[1]


def _json_output(capsys) -> dict[str, Any]:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _create_migrated_db_with_metadata(root: Path, *, schema_version: int, applied_through: int) -> None:
    loop_dir = root / ".project-loop"
    loop_dir.mkdir(parents=True)
    conn = connect(loop_dir / "project.db")
    try:
        for migration in migrations_module.discover_migrations():
            if migration.version > applied_through:
                continue
            conn.executescript(migration.sql)
            conn.execute(
                """
                INSERT INTO schema_migrations(version, name, checksum, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    "2026-07-08T00:00:00+00:00",
                ),
            )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("schema_version", str(schema_version)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("pcl_version", "0.2.2"),
        )
        conn.commit()
    finally:
        conn.close()
    (loop_dir / "events.jsonl").write_text("", encoding="utf-8")
    (root / "pcl.yaml").write_text("project_loop:\n  version: \"0.1.0\"\n", encoding="utf-8")
    (root / ".agents" / "skills" / "project-control-loop").mkdir(parents=True)
    (root / ".agents" / "skills" / "project-control-loop" / "SKILL.md").write_text(
        "# Skill\n", encoding="utf-8"
    )


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


def _adhoc_event_payload(root: Path, evidence_id: str) -> dict[str, Any]:
    [row] = _db_rows(
        root,
        """
        SELECT id, payload_json FROM events
        WHERE event_type = 'adhoc_evidence_recorded' AND entity_id = ?
        """,
        (evidence_id,),
    )
    db_payload = json.loads(row["payload_json"])
    jsonl_payloads = [
        json.loads(line)["payload"]
        for line in (root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if json.loads(line)["id"] == row["id"]
    ]
    assert jsonl_payloads == [db_payload]
    return db_payload


def _manifest(root: Path, relative_path: str) -> dict[str, Any]:
    return json.loads((root / relative_path).read_text(encoding="utf-8"))


def _adhoc_manifests(root: Path) -> list[Path]:
    return sorted((root / ".project-loop" / "evidence" / "adhoc").glob("*.json"))


def _adhoc_copy_dirs(root: Path) -> list[Path]:
    copy_root = root / ".project-loop" / "evidence" / "adhoc-files"
    if not copy_root.exists():
        return []
    return sorted(path for path in copy_root.iterdir() if path.is_dir())


def _assert_evidence_add_error(capsys, code: str) -> None:
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == code


def _assert_no_adhoc_traces(
    root: Path,
    *,
    before_events: int,
    before_manifests: list[Path],
    before_copy_dirs: list[Path] | None = None,
) -> None:
    assert _db_rows(root, "SELECT id FROM evidence ORDER BY id") == []
    assert _event_count(root) == before_events
    assert _adhoc_manifests(root) == before_manifests
    if before_copy_dirs is not None:
        assert _adhoc_copy_dirs(root) == before_copy_dirs


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


def _assess_adhoc_evidence(root: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    return evidence_module.assess_adhoc_evidence(
        ProjectPaths(root),
        evidence_id=evidence["id"],
        evidence_type=evidence["type"],
        manifest_path_value=evidence["manifest_path"],
        validate_optional_fields=True,
    )


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
    event_payload = _adhoc_event_payload(tmp_path, "E-0001")
    assert "copy_duration_ms" not in event_payload
    assert "copied_total_bytes" not in event_payload
    assert "write_transaction_pre_event_duration_ms" not in event_payload


def test_evidence_add_copy_records_single_and_bundle_members(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    single = tmp_path / "pytest-out.txt"
    single.write_text("pytest passed\n", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "pytest-out.txt",
        "--summary",
        "copied pytest output",
        "--copy",
        "--json",
    ]) == 0
    single_payload = _json_output(capsys)
    assert "warnings" not in single_payload
    single_evidence = single_payload["evidence"]
    single_member = single_evidence["members"][0]
    assert single_member == {
        "path": "pytest-out.txt",
        "path_scope": "in_project",
        "size_bytes": single.stat().st_size,
        "sha256": _sha256(single),
        "storage_mode": "copied",
        "stored_path": ".project-loop/evidence/adhoc-files/e-0001/01-pytest-out.txt",
    }
    stored_single = tmp_path / single_member["stored_path"]
    assert stored_single.read_bytes() == single.read_bytes()
    assert _sha256(stored_single) == single_member["sha256"]
    manifest = _manifest(tmp_path, single_evidence["manifest_path"])
    assert manifest["members"] == [single_member]
    event_payload = _adhoc_event_payload(tmp_path, "E-0001")
    assert event_payload["member_count"] == 1
    assert event_payload["copied_total_bytes"] == single.stat().st_size
    assert isinstance(event_payload["copy_duration_ms"], int)
    assert event_payload["copy_duration_ms"] >= 0
    assert isinstance(event_payload["write_transaction_pre_event_duration_ms"], int)
    assert event_payload["write_transaction_pre_event_duration_ms"] >= 0

    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "output.txt"
    second = second_dir / "output.txt"
    first.write_text("first output\n", encoding="utf-8")
    second.write_text("second output\n", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "a/output.txt",
        "--file",
        "b/output.txt",
        "--summary",
        "copied bundle",
        "--copy",
        "--json",
    ]) == 0
    bundle = _json_output(capsys)["evidence"]
    assert bundle["id"] == "E-0002"
    assert [member["stored_path"] for member in bundle["members"]] == [
        ".project-loop/evidence/adhoc-files/e-0002/01-output.txt",
        ".project-loop/evidence/adhoc-files/e-0002/02-output.txt",
    ]
    assert (tmp_path / bundle["members"][0]["stored_path"]).read_text(encoding="utf-8") == "first output\n"
    assert (tmp_path / bundle["members"][1]["stored_path"]).read_text(encoding="utf-8") == "second output\n"
    assert _manifest(tmp_path, bundle["manifest_path"])["members"] == bundle["members"]


def test_evidence_add_task_links_existing_task(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Review linked evidence",
        "--json",
    ]) == 0
    _json_output(capsys)
    artifact = tmp_path / "intent-index.json"
    artifact.write_text('{"claim":"model-derived navigation"}\n', encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "intent-index.json",
        "--summary",
        "Model-derived intent index for worker task",
        "--task",
        "T-0001",
        "--json",
    ]) == 0
    payload = _json_output(capsys)

    evidence = payload["evidence"]
    assert evidence["linked_task_id"] == "T-0001"
    rows = _db_rows(tmp_path, "SELECT id, linked_task_id FROM evidence ORDER BY id")
    assert rows == [{"id": "E-0001", "linked_task_id": "T-0001"}]
    event_payload = json.loads(
        _db_rows(
            tmp_path,
            "SELECT payload_json FROM events WHERE event_type = 'adhoc_evidence_recorded'",
        )[0]["payload_json"]
    )
    assert event_payload["linked_task_id"] == "T-0001"


def test_evidence_add_task_rejects_unknown_task_with_zero_traces(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    artifact = tmp_path / "pytest-out.txt"
    artifact.write_text("pytest passed\n", encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)
    before_copy_dirs = _adhoc_copy_dirs(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "pytest-out.txt",
        "--summary",
        "pytest run",
        "--task",
        "T-9999",
        "--copy",
        "--json",
    ]) == 2

    _assert_evidence_add_error(capsys, "evidence_add_unknown_task")
    _assert_no_adhoc_traces(
        tmp_path,
        before_events=before_events,
        before_manifests=before_manifests,
        before_copy_dirs=before_copy_dirs,
    )


def test_evidence_add_task_rejects_invalid_task_id_with_zero_traces(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    artifact = tmp_path / "pytest-out.txt"
    artifact.write_text("pytest passed\n", encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "pytest-out.txt",
        "--summary",
        "pytest run",
        "--task",
        "not a task",
        "--json",
    ]) == 2

    _assert_evidence_add_error(capsys, "evidence_add_invalid_task")
    _assert_no_adhoc_traces(
        tmp_path,
        before_events=before_events,
        before_manifests=before_manifests,
    )


def test_evidence_add_task_requires_migration_with_zero_traces(
    tmp_path: Path,
    capsys,
) -> None:
    _create_migrated_db_with_metadata(tmp_path, schema_version=5, applied_through=5)
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Review linked evidence",
        "--json",
    ]) == 0
    _json_output(capsys)
    artifact = tmp_path / "pytest-out.txt"
    artifact.write_text("pytest passed\n", encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)
    before_copy_dirs = _adhoc_copy_dirs(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "pytest-out.txt",
        "--summary",
        "pytest run",
        "--task",
        "T-0001",
        "--copy",
        "--json",
    ]) == 2

    payload = _json_output(capsys)
    assert payload["error"]["code"] == "evidence_task_link_requires_migration"
    assert payload["error"]["details"] == {
        "task_id": "T-0001",
        "required_schema_version": 6,
        "migration": "006_evidence_task_link",
        "command": f"pcl migrate --root {tmp_path}",
    }
    _assert_no_adhoc_traces(
        tmp_path,
        before_events=before_events,
        before_manifests=before_manifests,
        before_copy_dirs=before_copy_dirs,
    )


def test_evidence_add_copy_serializes_concurrent_id_allocation(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    artifact = tmp_path / "race-artifact.txt"
    artifact.write_text("parallel copy fixture\n", encoding="utf-8")
    paths = ProjectPaths(root=tmp_path)
    worker_count = 12
    start = Barrier(worker_count)

    def add_copied_evidence(index: int) -> dict[str, Any]:
        start.wait()
        return evidence_module.record_adhoc_evidence(
            paths,
            files=["race-artifact.txt"],
            summary=f"parallel copy {index}",
            copy_files=True,
        )["evidence"]

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        evidence_records = list(executor.map(add_copied_evidence, range(worker_count)))

    expected_ids = [f"E-{index:04d}" for index in range(1, worker_count + 1)]
    assert sorted(record["id"] for record in evidence_records) == expected_ids
    rows = _db_rows(tmp_path, "SELECT id, path FROM evidence ORDER BY id")
    assert [row["id"] for row in rows] == expected_ids
    assert [path.name for path in _adhoc_copy_dirs(tmp_path)] == [evidence_id.lower() for evidence_id in expected_ids]
    assert list((tmp_path / ".project-loop" / "tmp").glob("e-*-adhoc-files-*")) == []

    for record in evidence_records:
        manifest = _manifest(tmp_path, record["manifest_path"])
        member = manifest["members"][0]
        assert member["storage_mode"] == "copied"
        assert member["stored_path"] == f".project-loop/evidence/adhoc-files/{record['id'].lower()}/01-race-artifact.txt"
        stored_path = tmp_path / member["stored_path"]
        assert stored_path.read_text(encoding="utf-8") == "parallel copy fixture\n"
        assert _sha256(stored_path) == member["sha256"]


def test_evidence_add_copy_process_stress_records_unique_ids_and_metrics(
    tmp_path: Path,
    capsys,
) -> None:
    for run_index in range(2):
        root = tmp_path / f"run-{run_index}"
        root.mkdir()
        _init(root, capsys)
        artifact = root / "race-artifact.txt"
        artifact.write_text("parallel process copy fixture\n", encoding="utf-8")
        worker_count = 8
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT / "src") + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "pcl",
                    "--root",
                    str(root),
                    "evidence",
                    "add",
                    "--file",
                    "race-artifact.txt",
                    "--summary",
                    f"parallel process copy {worker_index}",
                    "--copy",
                    "--json",
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for worker_index in range(worker_count)
        ]
        completed = [process.communicate(timeout=30) for process in processes]
        return_codes = [process.returncode for process in processes]
        assert return_codes == [0] * worker_count
        payloads = [json.loads(stdout) for stdout, stderr in completed]
        assert all(stderr == "" for stdout, stderr in completed)

        expected_ids = [f"E-{index:04d}" for index in range(1, worker_count + 1)]
        assert sorted(payload["evidence"]["id"] for payload in payloads) == expected_ids
        rows = _db_rows(root, "SELECT id FROM evidence ORDER BY id")
        assert [row["id"] for row in rows] == expected_ids

        db_events = _db_rows(
            root,
            """
            SELECT entity_id, payload_json FROM events
            WHERE event_type = 'adhoc_evidence_recorded'
            ORDER BY entity_id
            """,
        )
        assert [row["entity_id"] for row in db_events] == expected_ids
        for row in db_events:
            payload = json.loads(row["payload_json"])
            assert payload["member_count"] == 1
            assert payload["copied_total_bytes"] == artifact.stat().st_size
            assert isinstance(payload["copy_duration_ms"], int)
            assert payload["copy_duration_ms"] >= 0
            assert isinstance(payload["write_transaction_pre_event_duration_ms"], int)
            assert payload["write_transaction_pre_event_duration_ms"] >= 0
        assert [path.name for path in _adhoc_copy_dirs(root)] == [evidence_id.lower() for evidence_id in expected_ids]
        assert list((root / ".project-loop" / "tmp").glob("e-*-adhoc-files-*")) == []


def test_evidence_add_copy_failure_leaves_zero_traces(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _init(tmp_path, capsys)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)
    before_copy_dirs = _adhoc_copy_dirs(tmp_path)
    original_copyfile = evidence_module.shutil.copyfile

    def fail_on_second(src: Path, dst: Path, *args: Any, **kwargs: Any) -> str:
        if Path(src).name == "second.txt":
            raise OSError("injected copy failure")
        return str(original_copyfile(src, dst, *args, **kwargs))

    monkeypatch.setattr(evidence_module.shutil, "copyfile", fail_on_second)

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
        "copy failure",
        "--copy",
        "--json",
    ]) == 2
    _assert_evidence_add_error(capsys, "evidence_copy_failed")
    _assert_no_adhoc_traces(
        tmp_path,
        before_events=before_events,
        before_manifests=before_manifests,
        before_copy_dirs=before_copy_dirs,
    )
    assert list((tmp_path / ".project-loop" / "tmp").glob("e-0001-adhoc-files-*")) == []

    clean = tmp_path / "clean.txt"
    clean.write_text("clean\n", encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "clean.txt",
        "--summary",
        "clean",
        "--copy",
        "--json",
    ]) == 0
    assert _json_output(capsys)["evidence"]["id"] == "E-0001"


def test_evidence_add_copy_hash_mismatch_aborts_without_traces(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _init(tmp_path, capsys)
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("original\n", encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)
    before_copy_dirs = _adhoc_copy_dirs(tmp_path)

    def copy_different_bytes(src: Path, dst: Path, *args: Any, **kwargs: Any) -> str:
        Path(dst).write_text("different\n", encoding="utf-8")
        return str(dst)

    monkeypatch.setattr(evidence_module.shutil, "copyfile", copy_different_bytes)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "artifact.txt",
        "--summary",
        "hash mismatch",
        "--copy",
        "--json",
    ]) == 2
    _assert_evidence_add_error(capsys, "evidence_copy_hash_mismatch")
    _assert_no_adhoc_traces(
        tmp_path,
        before_events=before_events,
        before_manifests=before_manifests,
        before_copy_dirs=before_copy_dirs,
    )
    assert list((tmp_path / ".project-loop" / "tmp").glob("e-0001-adhoc-files-*")) == []


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


def test_evidence_add_copy_records_outside_project_source_and_stored_path(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside-copy"
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
        "outside copied report",
        "--copy",
        "--json",
    ]) == 0
    payload = _json_output(capsys)
    member = payload["evidence"]["members"][0]
    assert member["path"].startswith("../")
    assert member["path_scope"] == "outside_project"
    assert member["storage_mode"] == "copied"
    assert member["stored_path"] == ".project-loop/evidence/adhoc-files/e-0001/01-report.txt"
    assert (tmp_path / member["stored_path"]).read_text(encoding="utf-8") == "outside report\n"
    assert payload["warnings"] == [f"evidence member outside project root: {member['path']}"]
    manifest = _manifest(tmp_path, payload["evidence"]["manifest_path"])
    assert manifest["members"] == [member]


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


def test_evidence_add_copy_sensitive_path_requires_flag_and_amplifies_warning(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    env_file = tmp_path / ".env"
    env_file.write_text("TOKEN=example\n", encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)
    before_copy_dirs = _adhoc_copy_dirs(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        ".env",
        "--summary",
        "blocked env copy",
        "--copy",
        "--json",
    ]) == 2
    _assert_evidence_add_error(capsys, "evidence_add_sensitive_path")
    _assert_no_adhoc_traces(
        tmp_path,
        before_events=before_events,
        before_manifests=before_manifests,
        before_copy_dirs=before_copy_dirs,
    )

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        ".env",
        "--summary",
        "explicit env copy",
        "--allow-sensitive-evidence",
        "--copy",
        "--json",
    ]) == 0
    payload = _json_output(capsys)
    member = payload["evidence"]["members"][0]
    assert member["sensitive_pattern"] == ".env"
    assert member["storage_mode"] == "copied"
    assert member["stored_path"] == ".project-loop/evidence/adhoc-files/e-0001/01-.env"
    assert (tmp_path / member["stored_path"]).read_text(encoding="utf-8") == "TOKEN=example\n"
    assert payload["warnings"] == [
        "evidence member matches sensitive filename pattern: .env "
        "(pattern: .env); PLH checks path shapes only and does not scan file contents; "
        "copying amplifies exposure because the file will also live under .project-loop/evidence"
    ]


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


def test_evidence_add_copy_size_cap_blocks_only_copy_mode(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    (tmp_path / "pcl.yaml").write_text(
        (tmp_path / "pcl.yaml").read_text(encoding="utf-8")
        + "\nevidence:\n  copy_max_member_bytes: 5\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("123456\n", encoding="utf-8")
    before_events = _event_count(tmp_path)
    before_manifests = _adhoc_manifests(tmp_path)
    before_copy_dirs = _adhoc_copy_dirs(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "artifact.txt",
        "--summary",
        "too large to copy",
        "--copy",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "evidence_copy_member_too_large"
    assert payload["error"]["details"] == {
        "path": "artifact.txt",
        "size_bytes": artifact.stat().st_size,
        "copy_max_member_bytes": 5,
        "config": "evidence.copy_max_member_bytes",
    }
    _assert_no_adhoc_traces(
        tmp_path,
        before_events=before_events,
        before_manifests=before_manifests,
        before_copy_dirs=before_copy_dirs,
    )

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "artifact.txt",
        "--summary",
        "large reference is allowed",
        "--json",
    ]) == 0
    payload = _json_output(capsys)
    assert payload["evidence"]["id"] == "E-0001"
    assert "storage_mode" not in payload["evidence"]["members"][0]


def test_evidence_add_copy_warns_over_half_size_cap(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    (tmp_path / "pcl.yaml").write_text(
        (tmp_path / "pcl.yaml").read_text(encoding="utf-8")
        + "\nevidence:\n  copy_max_member_bytes: 10\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("123456", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "artifact.txt",
        "--summary",
        "large copied member",
        "--copy",
        "--json",
    ]) == 0
    payload = _json_output(capsys)
    assert payload["warnings"] == [
        "large_evidence_member: artifact.txt is 6 bytes, over half the configured copy cap (10 bytes)"
    ]
    assert payload["evidence"]["members"][0]["storage_mode"] == "copied"


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


def test_strict_validate_checks_copied_member_health_from_copy(
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
        "copied artifact",
        "--copy",
        "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]
    stored_path = evidence["members"][0]["stored_path"]

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys) == {"errors": [], "ok": True, "warnings": []}
    assert _assess_adhoc_evidence(tmp_path, evidence) == {
        "health": "ok",
        "findings": [],
    }

    artifact.unlink()
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    source_missing = _json_output(capsys)
    assert source_missing["ok"] is True
    assert source_missing["errors"] == []
    assert source_missing["warnings"] == [
        "Adhoc evidence E-0001 source member artifact.txt drifted: missing."
    ]
    assert (tmp_path / stored_path).read_text(encoding="utf-8") == "original\n"
    assert _assess_adhoc_evidence(tmp_path, evidence) == {
        "health": "warning",
        "findings": [{"code": "source_drifted", "path": "artifact.txt", "detail": "missing"}],
    }

    (tmp_path / stored_path).write_text("changed copy\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    copy_mismatch = _json_output(capsys)
    assert copy_mismatch["ok"] is True
    assert copy_mismatch["errors"] == []
    assert copy_mismatch["warnings"] == [
        f"Adhoc evidence E-0001 copied member {stored_path} drifted: hash mismatch.",
        "Adhoc evidence E-0001 source member artifact.txt drifted: missing.",
    ]
    assert _assess_adhoc_evidence(tmp_path, evidence) == {
        "health": "warning",
        "findings": [
            {
                "code": "copy_hash_mismatch",
                "path": stored_path,
                "source_path": "artifact.txt",
            },
            {"code": "source_drifted", "path": "artifact.txt", "detail": "missing"},
        ],
    }

    artifact.write_text("original\n", encoding="utf-8")
    (tmp_path / stored_path).unlink()
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    copy_missing = _json_output(capsys)
    assert copy_missing["ok"] is True
    assert copy_missing["errors"] == []
    assert copy_missing["warnings"] == [
        f"Adhoc evidence E-0001 copied member {stored_path} drifted: missing."
    ]


def test_copied_adhoc_source_size_mismatch_warns_without_touching_copy(
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
        "copied artifact",
        "--copy",
        "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]
    stored_path = evidence["members"][0]["stored_path"]

    artifact.write_text("changed source length\n", encoding="utf-8")

    assert _assess_adhoc_evidence(tmp_path, evidence) == {
        "health": "warning",
        "findings": [{"code": "source_drifted", "path": "artifact.txt", "detail": "size_mismatch"}],
    }
    assert (tmp_path / stored_path).read_text(encoding="utf-8") == "original\n"
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys) == {
        "errors": [],
        "ok": True,
        "warnings": ["Adhoc evidence E-0001 source member artifact.txt drifted: size mismatch."],
    }


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
