from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from pcl.cli import main
from pcl.db import connect


FORBIDDEN_CONTEXT_CHECK_KEYS = {
    "ready_for_handoff",
    "safe_to_continue",
    "safe_to_run",
    "verified_relevant",
    "agent_read",
    "semantic_match",
}


def _json_output(capsys) -> dict[str, Any]:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "core.pager=cat",
            "-c",
            "user.name=PCL Test",
            "-c",
            "user.email=pcl@example.test",
            "--no-pager",
            *args,
        ],
        capture_output=True,
        check=True,
        text=True,
    )


def _create_task_code_project(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)
    assert main(["--root", str(root), "goal", "create", "--title", "Code context"]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Check code context",
        "--description",
        "Report target-bound receipt facts.",
        "--goal",
        "G-0001",
    ]) == 0
    capsys.readouterr()
    _write_code_files(root)
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")


def _create_job_code_project(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(root),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    capsys.readouterr()
    _write_code_files(root)
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")


def _write_code_files(root: Path) -> None:
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'Hello {name}'\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "from src import app\n\n\ndef test_greet():\n    assert app.greet('PCL') == 'Hello PCL'\n",
        encoding="utf-8",
    )


def _write_bound_receipt(root: Path, capsys, *, target_args: list[str]) -> dict[str, Any]:
    assert main(["--root", str(root), "index", "build", "--json"]) == 0
    _json_output(capsys)
    app_path = root / "src" / "app.py"
    app_path.write_text(
        app_path.read_text(encoding="utf-8") + "\n\ndef parting() -> str:\n    return 'bye'\n",
        encoding="utf-8",
    )
    assert main(["--root", str(root), "impact", "--diff", *target_args, "--json"]) == 0
    return _json_output(capsys)["impact"]


def _receipt_payload(root: Path, impact: dict[str, Any]) -> dict[str, Any]:
    return json.loads((root / impact["receipt_path"]).read_text(encoding="utf-8"))


def _rewrite_receipt_target_binding(
    root: Path,
    impact: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
) -> dict[str, Any]:
    receipt_path = root / impact["receipt_path"]
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["target_binding"] = {
        **payload["target_binding"],
        "target_type": target_type,
        "target_id": target_id,
    }
    receipt_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload["target_binding"]


def _add_supporting_evidence(root: Path, capsys) -> None:
    artifact = root / "supporting.txt"
    artifact.write_text("supporting fact\n", encoding="utf-8")
    assert main([
        "--root",
        str(root),
        "evidence",
        "add",
        "--file",
        "supporting.txt",
        "--summary",
        "Supporting fact",
        "--copy",
        "--task",
        "T-0001",
        "--json",
    ]) == 0
    _json_output(capsys)


def _add_master_trace_pair(root: Path, capsys) -> list[dict[str, Any]]:
    trace_path = root / "master-trace.md"
    trace_path.write_text(
        "---\n"
        "contract_version: master-trace/v0\n"
        "trace_id: mt-check-fixture\n"
        "source_kind: operator_notes\n"
        "captured_at: 2026-07-10T00:00:00Z\n"
        "---\n"
        "Preflight source line.\n",
        encoding="utf-8",
    )
    assert main([
        "--root", str(root), "evidence", "add", "--file", trace_path.name,
        "--summary", "Master trace", "--copy", "--task", "T-0001", "--json",
    ]) == 0
    evidence = [_json_output(capsys)["evidence"]]
    trace_evidence = evidence[0]
    trace_member = trace_evidence["members"][0]
    index_path = root / "intent-index.json"
    index_path.write_text(
        json.dumps({
            "contract_version": "intent-index/v0",
            "index_id": "ii-check-fixture",
            "generated_at": "2026-07-10T00:01:00Z",
            "generator": "test-fixture",
            "source_trace": {
                "evidence_id": trace_evidence["id"],
                "manifest_path": trace_evidence["manifest_path"],
                "member_path": trace_member["path"],
                "stored_path": trace_member["stored_path"],
                "sha256": trace_member["sha256"],
            },
            "items": [{
                "id": "I-001", "kind": "task_hint",
                "claim": "Use the preflight source line.",
                "source_refs": [{
                    "evidence_id": trace_evidence["id"],
                    "stored_path": trace_member["stored_path"],
                    "line_start": 7, "line_end": 7,
                }],
            }],
        }, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert main([
        "--root", str(root), "evidence", "add", "--file", index_path.name,
        "--summary", "Intent index", "--copy", "--task", "T-0001", "--json",
    ]) == 0
    evidence.append(_json_output(capsys)["evidence"])
    return evidence


def _state_counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        counts = {
            "evidence_rows": _table_count(conn, "evidence"),
            "event_rows": _table_count(conn, "events"),
            "evidence_link_rows": _table_count(conn, "evidence_links"),
        }
    finally:
        conn.close()
    events_path = root / ".project-loop" / "events.jsonl"
    counts["event_jsonl_lines"] = (
        len(events_path.read_text(encoding="utf-8").splitlines())
        if events_path.exists()
        else 0
    )
    counts["adhoc_files"] = _file_count(root / ".project-loop" / "evidence" / "adhoc-files")
    counts["context_receipts"] = _file_count(
        root / ".project-loop" / "evidence" / "context-receipts"
    )
    return counts


def _table_count(conn, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def _file_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def _payload_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for item in value.values():
            keys.update(_payload_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_payload_keys(item))
    return keys


def test_context_check_task_present_reports_receipt_and_supporting_count(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    _add_supporting_evidence(tmp_path, capsys)
    impact = _write_bound_receipt(tmp_path, capsys, target_args=["--for-task", "T-0001"])
    receipt = _receipt_payload(tmp_path, impact)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--json",
    ]) == 0

    payload = _json_output(capsys)
    assert payload["ok"] is True
    check = payload["context_check"]
    assert set(check) == {
        "target",
        "supporting_evidence_count",
        "target_bound_code_context",
        "canonical_context_pack_command",
        "warnings",
        "master_trace_context",
    }
    assert check["target"] == {"type": "task", "id": "T-0001"}
    assert check["supporting_evidence_count"] == 1
    assert check["target_bound_code_context"] == {
        "status": "present",
        "receipt_ref": {
            "evidence_id": impact["evidence_id"],
            "created_at": receipt["created_at"],
        },
    }
    assert (
        check["canonical_context_pack_command"]
        == "pcl context pack --task T-0001 --include-code-context --require-bound-receipt --json"
    )
    assert check["warnings"] == []
    assert check["master_trace_context"]["status"] == "absent"
    assert check["master_trace_context"]["missing"] == ["master_trace", "intent_index"]


def test_context_check_reports_master_trace_preflight_and_remains_read_only(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    evidence = _add_master_trace_pair(tmp_path, capsys)
    before = _state_counts(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--json",
    ]) == 0
    check = _json_output(capsys)["context_check"]

    preflight = check["master_trace_context"]
    assert preflight["status"] == "present"
    assert preflight["missing"] == []
    assert preflight["ambiguous"] == []
    assert preflight["unresolved_stored_paths"] == []
    assert preflight["raw_transcript_inlined"] is False
    assert preflight["binding"]["status"] == "valid"
    assert preflight["binding"]["semantic_validation"] is False
    assert preflight["binding"]["trace"]["evidence_id"] == evidence[0]["id"]
    assert preflight["binding"]["intent_index"]["evidence_id"] == evidence[1]["id"]
    assert preflight["candidates"]["master_trace"] == [
        {
            "evidence_id": evidence[0]["id"],
            "manifest_path": evidence[0]["manifest_path"],
            "member_paths": ["master-trace.md"],
            "stored_paths": [evidence[0]["members"][0]["stored_path"]],
        }
    ]
    assert preflight["candidates"]["intent_index"][0]["evidence_id"] == evidence[1]["id"]
    assert _state_counts(tmp_path) == before

    (tmp_path / evidence[0]["members"][0]["stored_path"]).unlink()
    before_unavailable = _state_counts(tmp_path)
    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--json",
    ]) == 0
    unavailable = _json_output(capsys)["context_check"]["master_trace_context"]
    assert unavailable["status"] == "unavailable"
    assert unavailable["unresolved_stored_paths"] == [
        {
            "kind": "master_trace",
            "evidence_id": evidence[0]["id"],
            "member_paths": ["master-trace.md"],
        }
    ]
    assert _state_counts(tmp_path) == before_unavailable


def test_context_check_missing_receipt_reports_refresh_and_required_error(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--json",
    ]) == 0
    check = _json_output(capsys)["context_check"]

    assert check["target_bound_code_context"] == {"status": "missing"}
    assert (
        check["recommended_refresh_command"]
        == "pcl impact --diff --for-task T-0001 --json"
    )
    assert check["warnings"] == [
        "No target-bound code context receipt exists for this task."
    ]

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--require-bound-receipt",
        "--json",
    ]) == 2
    error = _json_output(capsys)["error"]
    assert error["code"] == "context_pack_bound_receipt_required"
    assert error["details"]["target_type"] == "task"
    assert error["details"]["target_id"] == "T-0001"


def test_context_check_mismatched_receipt_reports_claim_and_mismatch_error(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Other task",
        "--goal",
        "G-0001",
    ]) == 0
    capsys.readouterr()
    impact = _write_bound_receipt(tmp_path, capsys, target_args=["--for-task", "T-0001"])
    claimed_binding = _rewrite_receipt_target_binding(
        tmp_path,
        impact,
        target_type="task",
        target_id="T-0002",
    )
    receipt = _receipt_payload(tmp_path, impact)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--json",
    ]) == 0
    check = _json_output(capsys)["context_check"]

    assert check["target_bound_code_context"] == {
        "status": "mismatched",
        "receipt_ref": {
            "evidence_id": impact["evidence_id"],
            "created_at": receipt["created_at"],
        },
        "claimed_target_binding": claimed_binding,
    }
    assert (
        check["recommended_refresh_command"]
        == "pcl impact --diff --for-task T-0001 --json"
    )
    assert check["warnings"] == [
        "A code_context link disagrees with its artifact binding."
    ]

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--require-bound-receipt",
        "--json",
    ]) == 2
    error = _json_output(capsys)["error"]
    assert error["code"] == "context_pack_bound_receipt_mismatch"
    assert error["details"]["evidence_id"] == impact["evidence_id"]
    assert error["details"]["claimed_target_binding"] == claimed_binding


def test_context_check_unavailable_receipt_does_not_claim_present(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_bound_receipt(tmp_path, capsys, target_args=["--for-task", "T-0001"])
    receipt = _receipt_payload(tmp_path, impact)
    (tmp_path / impact["receipt_path"]).write_text("{not-json", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--json",
    ]) == 0
    check = _json_output(capsys)["context_check"]

    assert check["target_bound_code_context"] == {
        "status": "unavailable",
        "receipt_ref": {
            "evidence_id": impact["evidence_id"],
            "created_at": receipt["created_at"],
        },
    }
    assert check["recommended_refresh_command"] == "pcl impact --diff --for-task T-0001 --json"

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--require-bound-receipt",
        "--json",
    ]) == 2
    assert _json_output(capsys)["error"]["code"] == "context_pack_bound_receipt_required"


def test_context_check_job_variant_reports_present_bound_receipt(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job_code_project(tmp_path, capsys)
    impact = _write_bound_receipt(tmp_path, capsys, target_args=["--for-job", "J-0001"])
    receipt = _receipt_payload(tmp_path, impact)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--job",
        "J-0001",
        "--json",
    ]) == 0
    check = _json_output(capsys)["context_check"]

    assert check["target"] == {"type": "agent_job", "id": "J-0001"}
    assert check["target_bound_code_context"] == {
        "status": "present",
        "receipt_ref": {
            "evidence_id": impact["evidence_id"],
            "created_at": receipt["created_at"],
        },
    }
    assert (
        check["canonical_context_pack_command"]
        == "pcl context pack --job J-0001 --include-code-context --require-bound-receipt --json"
    )


def test_context_check_bad_and_absent_targets_use_impact_target_errors(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "not-a-task-id",
        "--json",
    ]) == 2
    assert _json_output(capsys)["error"]["code"] == "impact_target_invalid"

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-9999",
        "--json",
    ]) == 2
    assert _json_output(capsys)["error"]["code"] == "impact_target_not_found"


def test_context_check_is_read_only_for_rows_events_and_artifacts(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    _add_supporting_evidence(tmp_path, capsys)
    _write_bound_receipt(tmp_path, capsys, target_args=["--for-task", "T-0001"])
    before = _state_counts(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--json",
    ]) == 0
    _json_output(capsys)

    assert _state_counts(tmp_path) == before


def test_context_check_invalid_binding_fails_closed_and_remains_read_only(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    evidence = _add_master_trace_pair(tmp_path, capsys)
    copied_index = tmp_path / evidence[1]["members"][0]["stored_path"]
    payload = json.loads(copied_index.read_text(encoding="utf-8"))
    payload["items"][0]["claim"] = "Changed after Evidence capture"
    copied_index.write_text(json.dumps(payload), encoding="utf-8")
    before = _state_counts(tmp_path)

    assert main([
        "--root", str(tmp_path), "context", "check", "--task", "T-0001", "--json",
    ]) == 0
    preflight = _json_output(capsys)["context_check"]["master_trace_context"]

    assert preflight["status"] == "invalid_binding"
    assert preflight["binding"]["status"] == "invalid"
    assert [item["code"] for item in preflight["binding"]["diagnostics"]] == [
        "recorded_intent_index_hash_mismatch"
    ]
    assert preflight["binding"]["semantic_validation"] is False
    assert "trace_claim_refs" not in preflight
    assert _state_counts(tmp_path) == before


def test_context_check_payload_omits_forbidden_epistemic_keys(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "check",
        "--task",
        "T-0001",
        "--json",
    ]) == 0
    payload = _json_output(capsys)["context_check"]

    assert not (FORBIDDEN_CONTEXT_CHECK_KEYS & _payload_keys(payload))


def test_context_check_non_json_prints_short_factual_summary(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "context", "check", "--task", "T-0001"]) == 0
    rendered = capsys.readouterr().out

    assert "Context check: task T-0001" in rendered
    assert "Target-bound code context: missing" in rendered
    assert "Canonical pack command: pcl context pack --task T-0001" in rendered
    assert "safe_to_run" not in rendered
