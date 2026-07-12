from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pcl.cli import main
from pcl.audit import audit_check
from pcl.contracts.profile_output_bundle import bundle_digest
from pcl.contracts.profile_run_request import request_basis_digest, request_digest
from pcl.contracts.profile_run_request import validate_profile_run_request
from pcl.db import connect, connect_mutation
from pcl.events import append_event
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.profile_prepare import prepare_profile_request
from pcl.profile_decisions import ProfileDecisionError, select_profile_proposal
from pcl.profile_authorization import (
    ProfileAuthorizationError,
    authorization_findings,
    authorize_profile_request,
)
from pcl.start import start_work


FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = (
    Path(__file__).parents[1]
    / "docs"
    / "proposals"
    / "council-profile"
    / "contracts"
    / "examples"
)
CORPUS = json.loads(
    (FIXTURES / "profile_bundle" / "cases.json").read_text(encoding="utf-8")
)["cases"]
STATUSES = ["completed", "needs_human", "partial", "budget_exhausted", "failed", "skipped"]


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _snapshot(root: Path) -> dict:
    loop = root / ".project-loop"
    conn = connect(loop / "project.db")
    try:
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("evidence", "evidence_links", "decisions", "events", "outbox_records")
        }
    finally:
        conn.close()
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in ("evidence", "reports", "dashboard", "exports")
        for path in sorted((loop / directory).rglob("*"))
        if path.is_file()
    }
    return {
        "counts": counts,
        "events_jsonl": hashlib.sha256((loop / "events.jsonl").read_bytes()).hexdigest(),
        "files": files,
    }


def _prepared(tmp_path: Path, capsys) -> tuple[Path, str, Path, dict]:
    root = tmp_path / "project"
    root.mkdir()
    paths = resolve_paths(root)
    init_project(paths)
    task_id = str(start_work(paths, intent="Validate Council bundle")["result"]["created_ids"]["task"])
    brief = _json(FIXTURES / "work_brief" / "minimal.json")
    brief["target"]["id"] = task_id
    brief_path = tmp_path / "brief.json"
    _write(brief_path, brief)
    assert main(["--root", str(root), "brief", "add", str(brief_path), "--summary", "Council brief", "--json"]) == 0
    brief_evidence = json.loads(capsys.readouterr().out)["evidence"]["id"]
    assert main(["--root", str(root), "route", "recommend", "--target", f"task:{task_id}", "--brief", str(brief_path), "--record", "--json"]) == 0
    capsys.readouterr()
    prepared = prepare_profile_request(
        paths,
        runner_profile_id="council.discovery",
        target_ref=f"task:{task_id}",
        brief_id=brief_evidence,
        now="2026-07-12T04:00:00Z",
    )["request"]
    request_path = tmp_path / "request.json"
    _write(request_path, prepared)
    return root, task_id, request_path, prepared


def _bundle(tmp_path: Path, request: dict, task_id: str, status: str = "needs_human") -> Path:
    root = tmp_path / f"bundle-{status}"
    root.mkdir(exist_ok=True)
    run = _json(EXAMPLES / "council-run.json")
    claims = _json(EXAMPLES / "claim-set.json")
    verification = _json(EXAMPLES / "verification-plan.json")
    proposal = _json(EXAMPLES / "decision-proposal.json")
    request_ref = {
        "request_id": request["request_id"],
        "request_digest": request["request_digest"]["value"],
    }
    run["request_ref"] = request_ref
    run["status"] = status
    proposal["target"]["id"] = task_id
    sentinel = tmp_path / "verification-command-ran"
    verification["items"][0]["proposed_commands"] = [f"touch {sentinel}"]
    role_values = [
        ("A-001", "run_manifest", "council-run/v0", "council-run.json", run),
        ("A-002", "claims", "claim-set/v0", "claim-set.json", claims),
        ("A-003", "verification_plan", "verification-plan/v0", "verification-plan.json", verification),
    ]
    if status in {"needs_human", "partial", "budget_exhausted"}:
        role_values.append(("A-004", "decision_proposal", "decision-proposal/v0", "decision-proposal.json", proposal))
    artifacts = []
    for artifact_id, role, contract, name, value in role_values:
        path = root / name
        _write(path, value)
        data = path.read_bytes()
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "role": role,
                "contract_version": contract,
                "path": name,
                "media_type": "application/json",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    kinds = {
        "completed": "none",
        "needs_human": "human_decision",
        "partial": "revise_work_brief",
        "budget_exhausted": "revise_work_brief",
        "failed": "inspect_failure",
        "skipped": "none",
    }
    bundle = {
        "contract_version": "profile-output-bundle/v1",
        "bundle_id": "POB-20260712T040100Z-acde1234",
        "generated_at": "2026-07-12T04:01:00Z",
        "request_ref": request_ref,
        "profile": request["profile"],
        "status": status,
        "summary": f"Fixture status {status}",
        "artifacts": artifacts,
        "decision_proposal_artifact_ids": ["A-004"] if len(artifacts) == 4 else [],
        "next_action": {
            "kind": kinds[status],
            "requires_human": status in {"needs_human", "partial", "budget_exhausted", "failed"},
            "safe_to_run": False,
            "summary": f"Next action for {status}",
        },
    }
    bundle["bundle_digest"] = {
        "algorithm": "sha256",
        "canonicalization": "pcl-canonical-json/v1-excluding-bundle_digest",
        "value": bundle_digest(bundle),
    }
    manifest = root / "bundle.json"
    _write(manifest, bundle)
    return manifest


def _refresh_artifact(bundle_path: Path, artifact_id: str) -> None:
    bundle = _json(bundle_path)
    artifact = next(item for item in bundle["artifacts"] if item["artifact_id"] == artifact_id)
    data = (bundle_path.parent / artifact["path"]).read_bytes()
    artifact["sha256"] = hashlib.sha256(data).hexdigest()
    artifact["size_bytes"] = len(data)
    bundle["bundle_digest"]["value"] = bundle_digest(bundle)
    _write(bundle_path, bundle)


def _refresh_bundle(bundle_path: Path) -> None:
    bundle = _json(bundle_path)
    bundle["bundle_digest"]["value"] = bundle_digest(bundle)
    _write(bundle_path, bundle)


def _refresh_request(request_path: Path) -> None:
    request = _json(request_path)
    request["request_basis_digest"]["value"] = request_basis_digest(request)
    request["request_digest"]["value"] = request_digest(request)
    _write(request_path, request)


@pytest.mark.parametrize("status", STATUSES)
def test_valid_status_plans_are_stable_and_read_only(tmp_path: Path, capsys, status: str) -> None:
    root, task_id, request_path, request = _prepared(tmp_path, capsys)
    bundle_path = _bundle(tmp_path, request, task_id, status)
    (bundle_path.parent / "unlisted-neighbor.txt").write_text("ignored", encoding="utf-8")
    before = _snapshot(root)
    command = ["--root", str(root), "profile", "ingest", "--request", str(request_path), "--bundle", str(bundle_path), "--dry-run", "--json"]
    assert main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(command) == 0
    second = json.loads(capsys.readouterr().out)
    assert first == second
    assert first["read_only"] is True
    assert first["runner_executed"] is False
    assert first["next_action"]["safe_to_run"] is False
    assert first["persistable_without_extra_flag"] is (status != "failed")
    assert first["requires_accept_failed"] is (status == "failed")
    expected_decisions = 1 if status == "needs_human" else 0
    expected_evidence = 0 if status == "failed" else 1
    assert first["mutation"] == {
        "evidence_rows": expected_evidence,
        "evidence_links": expected_evidence + expected_decisions,
        "decision_rows": expected_decisions,
        "events": expected_evidence + expected_decisions,
        "outbox_records": expected_evidence + expected_decisions,
        "filesystem_bundle_directories": expected_evidence,
    }
    assert not (tmp_path / "verification-command-ran").exists()
    assert _snapshot(root) == before


def _mutate_case(case_id: str, root: Path, task_id: str, request_path: Path, bundle_path: Path) -> None:
    request = _json(request_path)
    bundle = _json(bundle_path)
    artifact = bundle["artifacts"][0]
    if case_id == "bad_project":
        request["project"]["root_fingerprint"] = "a" * 64
        _write(request_path, request)
        _refresh_request(request_path)
    elif case_id == "missing_target":
        request["target"]["id"] = "T-9999"
        _write(request_path, request)
        _refresh_request(request_path)
    elif case_id == "manifest_mismatch":
        request["profile"]["manifest_sha256"] = "f" * 64
        _write(request_path, request)
        _refresh_request(request_path)
    elif case_id == "authorization_required":
        request["data_policy"]["network_access"] = "requested"
        request["authorization"] = None
        _write(request_path, request)
        _refresh_request(request_path)
    elif case_id == "output_limit_unsupported":
        request["limits"]["max_output_bytes"] = 2_000_001
        _write(request_path, request)
        _refresh_request(request_path)
    elif case_id == "bundle_request_mismatch":
        bundle["request_ref"]["request_id"] = "PRR-20000101T000000Z-deadbeef"
        bundle["bundle_digest"]["value"] = bundle_digest(bundle)
        _write(bundle_path, bundle)
    elif case_id == "bundle_profile_mismatch":
        bundle["profile"]["manifest_sha256"] = "e" * 64
        bundle["bundle_digest"]["value"] = bundle_digest(bundle)
        _write(bundle_path, bundle)
    elif case_id in {"path_parent", "path_absolute", "path_unc", "path_drive"}:
        artifact["path"] = {"path_parent": "../council-run.json", "path_absolute": "/tmp/council-run.json", "path_unc": "\\\\server\\run.json", "path_drive": "C:/run.json"}[case_id]
        bundle["bundle_digest"]["value"] = bundle_digest(bundle)
        _write(bundle_path, bundle)
    elif case_id == "case_collision":
        duplicate = copy.deepcopy(artifact)
        duplicate["artifact_id"] = "A-099"
        duplicate["path"] = artifact["path"].upper()
        bundle["artifacts"].append(duplicate)
        bundle["bundle_digest"]["value"] = bundle_digest(bundle)
        _write(bundle_path, bundle)
    elif case_id == "hash_mismatch":
        artifact_path = bundle_path.parent / artifact["path"]
        data = artifact_path.read_bytes()
        artifact_path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    elif case_id == "size_mismatch":
        artifact["size_bytes"] += 1
        bundle["bundle_digest"]["value"] = bundle_digest(bundle)
        _write(bundle_path, bundle)
    elif case_id == "declared_size_limit":
        artifact["size_bytes"] = request["limits"]["max_output_bytes"] + 1
        bundle["bundle_digest"]["value"] = bundle_digest(bundle)
        _write(bundle_path, bundle)
    elif case_id == "bad_status":
        bundle["status"] = "unsafe"
        bundle["bundle_digest"]["value"] = bundle_digest(bundle)
        _write(bundle_path, bundle)
    elif case_id == "bad_digest":
        bundle["bundle_digest"]["value"] = "0" * 64
        _write(bundle_path, bundle)
    elif case_id == "required_role_missing":
        bundle["artifacts"] = [item for item in bundle["artifacts"] if item["role"] != "claims"]
        bundle["bundle_digest"]["value"] = bundle_digest(bundle)
        _write(bundle_path, bundle)
    else:
        file_by_case = {
            "run_request_mismatch": ("A-001", "council-run.json"),
            "run_status_mismatch": ("A-001", "council-run.json"),
            "claim_participant_missing": ("A-002", "claim-set.json"),
            "verification_claim_missing": ("A-003", "verification-plan.json"),
            "proposal_participant_missing": ("A-004", "decision-proposal.json"),
            "proposal_evidence_missing": ("A-004", "decision-proposal.json"),
        }
        artifact_id, name = file_by_case[case_id]
        path = bundle_path.parent / name
        value = _json(path)
        if case_id == "run_request_mismatch":
            value["request_ref"]["request_id"] = "PRR-20000101T000000Z-deadbeef"
        elif case_id == "run_status_mismatch":
            value["status"] = "completed"
        elif case_id == "claim_participant_missing":
            value["claims"][0]["source_participant_ids"] = ["P-99"]
        elif case_id == "verification_claim_missing":
            value["items"][0]["claim_refs"] = ["C-999"]
        elif case_id == "proposal_participant_missing":
            value["generated_by"]["participant_ids"] = ["P-99"]
        else:
            value["candidates"][0]["evidence_refs"] = ["C-999"]
        _write(path, value)
        _refresh_artifact(bundle_path, artifact_id)


@pytest.mark.parametrize("case", CORPUS, ids=lambda item: item["id"])
def test_invalid_corpus_is_zero_mutation(tmp_path: Path, capsys, case: dict) -> None:
    root, task_id, request_path, request = _prepared(tmp_path, capsys)
    bundle_path = _bundle(tmp_path, request, task_id)
    _mutate_case(case["id"], root, task_id, request_path, bundle_path)
    before = _snapshot(root)
    assert main(["--root", str(root), "profile", "ingest", "--request", str(request_path), "--bundle", str(bundle_path), "--dry-run", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "profile_bundle_invalid"
    codes = [item["code"] for item in payload["error"]["details"]["findings"]]
    assert case["expected_code"] in codes
    assert payload["error"]["details"]["findings"] == sorted(
        payload["error"]["details"]["findings"],
        key=lambda item: (item["path"], item["code"], item["message"]),
    )
    assert _snapshot(root) == before


def test_manifest_limits_and_duplicate_keys_fail_before_mutation(tmp_path: Path, capsys) -> None:
    root, task_id, request_path, request = _prepared(tmp_path, capsys)
    bundle_path = _bundle(tmp_path, request, task_id)
    before = _snapshot(root)
    request_path.write_bytes(b" " * 2_000_001)
    assert main(["--root", str(root), "profile", "ingest", "--request", str(request_path), "--bundle", str(bundle_path), "--dry-run", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["details"]["findings"][0]["code"] == "request_size_limit"
    assert _snapshot(root) == before

    _write(request_path, request)
    bundle_path.write_text('{"contract_version":"profile-output-bundle/v1","contract_version":"duplicate"}', encoding="utf-8")
    assert main(["--root", str(root), "profile", "ingest", "--request", str(request_path), "--bundle", str(bundle_path), "--dry-run", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["details"]["findings"][0]["code"] == "bundle_json_invalid"
    assert _snapshot(root) == before


def test_symlink_artifact_is_rejected_read_only(tmp_path: Path, capsys) -> None:
    root, task_id, request_path, request = _prepared(tmp_path, capsys)
    bundle_path = _bundle(tmp_path, request, task_id)
    bundle = _json(bundle_path)
    source = bundle_path.parent / "council-run.json"
    link = bundle_path.parent / "linked-run.json"
    link.symlink_to(source.name)
    bundle["artifacts"][0]["path"] = link.name
    bundle["bundle_digest"]["value"] = bundle_digest(bundle)
    _write(bundle_path, bundle)
    before = _snapshot(root)
    assert main(["--root", str(root), "profile", "ingest", "--request", str(request_path), "--bundle", str(bundle_path), "--dry-run", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert "bundle_artifact_symlink" in [item["code"] for item in payload["error"]["details"]["findings"]]
    assert _snapshot(root) == before


@pytest.mark.parametrize("status", ["completed", "partial", "budget_exhausted", "skipped"])
def test_atomic_ingest_adds_exact_rows_and_exact_replay_is_idempotent(
    tmp_path: Path,
    capsys,
    status: str,
) -> None:
    root, task_id, request_path, request = _prepared(tmp_path, capsys)
    bundle_path = _bundle(tmp_path, request, task_id, status)
    (bundle_path.parent / "unlisted-neighbor.txt").write_text("ignored", encoding="utf-8")
    before = _snapshot(root)
    command = [
        "--root",
        str(root),
        "profile",
        "ingest",
        "--request",
        str(request_path),
        "--bundle",
        str(bundle_path),
        "--json",
    ]
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["changed"] is True
    assert result["idempotent"] is False
    after = _snapshot(root)
    for table in ("evidence", "evidence_links", "events", "outbox_records"):
        assert after["counts"][table] == before["counts"][table] + 1
    assert after["counts"]["decisions"] == before["counts"]["decisions"]
    manifest_path = root / result["evidence"]["manifest_path"]
    manifest = _json(manifest_path)
    assert manifest["bundle"]["status"] == status
    assert manifest["request"]["request_id"] == request["request_id"]
    assert len(manifest["members"]) == len(_json(bundle_path)["artifacts"])
    assert not any("unlisted-neighbor" in str(path) for path in manifest_path.parent.rglob("*"))

    stored_hashes = {
        item["logical_path"]: hashlib.sha256(
            (manifest_path.parent / item["storage_path"]).read_bytes()
        ).hexdigest()
        for item in manifest["members"]
    }
    (bundle_path.parent / "council-run.json").write_text("source changed", encoding="utf-8")
    assert {
        item["logical_path"]: hashlib.sha256(
            (manifest_path.parent / item["storage_path"]).read_bytes()
        ).hexdigest()
        for item in manifest["members"]
    } == stored_hashes

    replay_before = _snapshot(root)
    (bundle_path.parent / "council-run.json").write_bytes(
        (manifest_path.parent / manifest["members"][0]["storage_path"]).read_bytes()
    )
    assert main(command) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["changed"] is False
    assert replay["idempotent"] is True
    assert replay["evidence"]["id"] == result["evidence"]["id"]
    assert replay["event_id"] == result["event_id"]
    assert _snapshot(root) == replay_before
    if status == "completed":
        assert audit_check(resolve_paths(root))["ok"] is True
        stored = manifest_path.parent / manifest["members"][0]["storage_path"]
        data = stored.read_bytes()
        stored.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        audit = audit_check(resolve_paths(root))
        assert "evidence_metadata_file_mismatch" in {
            item["type"]
            for classification in audit["anomalies"].values()
            for item in classification
        }


def test_atomic_ingest_replay_conflict_and_human_gate_are_zero_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id, request_path, request = _prepared(tmp_path, capsys)
    bundle_path = _bundle(tmp_path, request, task_id, "completed")
    base = [
        "--root",
        str(root),
        "profile",
        "ingest",
        "--request",
        str(request_path),
        "--bundle",
        str(bundle_path),
        "--json",
    ]
    assert main(base) == 0
    capsys.readouterr()
    bundle = _json(bundle_path)
    bundle["summary"] = "same ID, different digest"
    bundle["bundle_digest"]["value"] = bundle_digest(bundle)
    _write(bundle_path, bundle)
    before = _snapshot(root)
    assert main(base) == 2
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["error"]["code"] == "profile_bundle_replay_conflict"
    assert _snapshot(root) == before

def test_failed_bundle_requires_explicit_acceptance_and_summary(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id, request_path, request = _prepared(tmp_path, capsys)
    bundle_path = _bundle(tmp_path, request, task_id, "failed")
    command = [
        "--root",
        str(root),
        "profile",
        "ingest",
        "--request",
        str(request_path),
        "--bundle",
        str(bundle_path),
        "--json",
    ]
    before = _snapshot(root)
    assert main(command) == 2
    refused = json.loads(capsys.readouterr().out)
    assert refused["error"]["code"] == "profile_failed_bundle_acceptance_required"
    assert _snapshot(root) == before

    assert main([*command[:-1], "--accept-failed", "--summary", "Retain runner failure for audit", "--json"]) == 0
    accepted = json.loads(capsys.readouterr().out)
    assert accepted["mutation"] == {
        "evidence_rows": 1,
        "evidence_links": 1,
        "decision_rows": 0,
        "events": 1,
        "outbox_records": 1,
        "filesystem_bundle_directories": 1,
    }
    after = _snapshot(root)
    for table in ("evidence", "evidence_links", "events", "outbox_records"):
        assert after["counts"][table] == before["counts"][table] + 1
    assert after["counts"]["decisions"] == before["counts"]["decisions"]
    manifest = _json(root / accepted["evidence"]["manifest_path"])
    assert manifest["failed_acceptance"] == {
        "accepted": True,
        "summary": "Retain runner failure for audit",
    }


@pytest.mark.parametrize(
    ("fault_point", "anomaly_type"),
    [
        ("profile_ingest_after_copy", "orphan_profile_bundle_staging"),
        ("profile_ingest_before_rename", "orphan_profile_bundle_staging"),
        ("profile_ingest_after_rename_before_commit", "orphan_profile_bundle_directory"),
        ("profile_ingest_after_outbox_before_commit", "orphan_profile_bundle_directory"),
    ],
)
def test_atomic_ingest_crash_points_leave_no_rows_and_are_auditable(
    tmp_path: Path,
    capsys,
    fault_point: str,
    anomaly_type: str,
) -> None:
    root, task_id, request_path, request = _prepared(tmp_path, capsys)
    bundle_path = _bundle(tmp_path, request, task_id, "completed")
    before = _snapshot(root)
    marker = tmp_path / f"{fault_point}.json"
    env = {
        **os.environ,
        "PYTHONPATH": str(Path("src").resolve()),
        "PCL_ENABLE_TEST_FAULTS": "1",
        "PCL_TEST_FAULT_POINT": fault_point,
        "PCL_TEST_FAULT_MARKER": str(marker),
    }
    crashed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pcl",
            "--root",
            str(root),
            "profile",
            "ingest",
            "--request",
            str(request_path),
            "--bundle",
            str(bundle_path),
            "--json",
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert crashed.returncode != 0
    assert json.loads(marker.read_text(encoding="utf-8"))["point"] == fault_point
    after_crash = _snapshot(root)
    assert after_crash["counts"] == before["counts"]
    assert after_crash["events_jsonl"] == before["events_jsonl"]
    assert {
        path: digest
        for path, digest in after_crash["files"].items()
        if "/profile-output-bundles/" not in path
    } == before["files"]
    report = audit_check(resolve_paths(root))
    anomaly_types = {
        item["type"]
        for classification in report["anomalies"].values()
        for item in classification
    }
    assert anomaly_type in anomaly_types
    matching = [
        item
        for classification in report["anomalies"].values()
        for item in classification
        if item["type"] == anomaly_type
    ]
    assert all(item["supported_action"] == "quarantine_or_report" for item in matching)


def _expand_proposals(bundle_path: Path, count: int) -> None:
    if count == 1:
        return
    bundle = _json(bundle_path)
    source_artifact = next(item for item in bundle["artifacts"] if item["role"] == "decision_proposal")
    source_value = _json(bundle_path.parent / source_artifact["path"])
    for index in range(2, count + 1):
        artifact = copy.deepcopy(source_artifact)
        artifact["artifact_id"] = f"A-{index + 3:03d}"
        artifact["path"] = f"decision-proposal-{index}.json"
        value = copy.deepcopy(source_value)
        value["proposal_id"] = f"DP-{index:04d}"
        path = bundle_path.parent / artifact["path"]
        _write(path, value)
        data = path.read_bytes()
        artifact["sha256"] = hashlib.sha256(data).hexdigest()
        artifact["size_bytes"] = len(data)
        bundle["artifacts"].append(artifact)
        bundle["decision_proposal_artifact_ids"].append(artifact["artifact_id"])
    bundle["bundle_digest"]["value"] = bundle_digest(bundle)
    _write(bundle_path, bundle)


@pytest.mark.parametrize("proposal_count", [1, 3])
def test_needs_human_ingest_atomically_creates_bound_decisions(
    tmp_path: Path,
    capsys,
    proposal_count: int,
) -> None:
    root, task_id, request_path, request = _prepared(tmp_path, capsys)
    bundle_path = _bundle(tmp_path, request, task_id, "needs_human")
    _expand_proposals(bundle_path, proposal_count)
    before = _snapshot(root)
    command = [
        "--root",
        str(root),
        "profile",
        "ingest",
        "--request",
        str(request_path),
        "--bundle",
        str(bundle_path),
        "--json",
    ]
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["decisions"]) == proposal_count
    after = _snapshot(root)
    assert after["counts"]["evidence"] == before["counts"]["evidence"] + 1
    assert after["counts"]["evidence_links"] == before["counts"]["evidence_links"] + 1 + proposal_count
    assert after["counts"]["decisions"] == before["counts"]["decisions"] + proposal_count
    assert after["counts"]["events"] == before["counts"]["events"] + 1 + proposal_count
    assert after["counts"]["outbox_records"] == before["counts"]["outbox_records"] + 1 + proposal_count
    assert result["mutation"] == {
        "evidence_rows": 1,
        "evidence_links": 1 + proposal_count,
        "decision_rows": proposal_count,
        "events": 1 + proposal_count,
        "outbox_records": 1 + proposal_count,
        "filesystem_bundle_directories": 1,
    }
    decision_id = result["decisions"][0]["decision_id"]
    assert main(["--root", str(root), "decision", "proposal", "show", decision_id, "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["proposal"]["proposal_id"] == "DP-0001"
    assert main(["--root", str(root), "next", "--json"]) == 0
    next_action = json.loads(capsys.readouterr().out)
    assert any(item["decision_id"] in next_action["command"] for item in result["decisions"])
    assert "decision proposal show" in next_action["command"]
    replay_before = _snapshot(root)
    assert main(command) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["idempotent"] is True
    assert [item["decision_id"] for item in replay["decisions"]] == [
        item["decision_id"] for item in result["decisions"]
    ]
    assert _snapshot(root) == replay_before


def test_profile_proposal_selection_is_human_gated_and_idempotent(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id, request_path, request = _prepared(tmp_path, capsys)
    bundle_path = _bundle(tmp_path, request, task_id, "needs_human")
    ingest = [
        "--root", str(root), "profile", "ingest", "--request", str(request_path),
        "--bundle", str(bundle_path), "--json",
    ]
    assert main(ingest) == 0
    ingested = json.loads(capsys.readouterr().out)
    decision_id = ingested["decisions"][0]["decision_id"]
    before = _snapshot(root)

    for legacy in (
        ["decision", "resolve", decision_id, "--selected-option", "OPT-A", "--reason", "legacy"],
        ["decision", "waive", decision_id, "--reason", "legacy"],
    ):
        assert main(["--root", str(root), *legacy, "--json"]) == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["error"]["code"] == "decision_proposal_command_required"
        assert _snapshot(root) == before

    with pytest.raises(ProfileDecisionError) as agent_error:
        select_profile_proposal(
            resolve_paths(root), decision_id=decision_id, candidate_id="OPT-A", decline=False,
            actor="agent:bot", actor_kind=None, recorded_by=None, recorder_kind=None,
            source_kind="cockpit", source_ref="task-agent", reason="agent choice",
            override_reason=None,
        )
    assert getattr(agent_error.value, "code", None) == "profile_decision_human_required"
    assert _snapshot(root) == before

    base_select = [
        "--root", str(root), "decision", "proposal", "select", decision_id,
        "--actor", "human:owner", "--recorded-by", "agent:codex",
        "--source-kind", "cockpit", "--source-ref", "cockpit-task-0159",
        "--reason", "Owner selected the bounded candidate", "--json",
    ]
    assert main([*base_select[:-1], "--candidate", "OPT-B", "--json"]) == 2
    missing_override = json.loads(capsys.readouterr().out)
    assert missing_override["error"]["code"] == "profile_decision_override_reason_required"
    assert _snapshot(root) == before

    select_a = [*base_select[:-1], "--candidate", "OPT-A", "--json"]
    assert main(select_a) == 0
    selected = json.loads(capsys.readouterr().out)
    assert selected["selected_option"] == "OPT-A"
    selected_state = _snapshot(root)
    assert selected_state["counts"]["events"] == before["counts"]["events"] + 1
    assert selected_state["counts"]["outbox_records"] == before["counts"]["outbox_records"] + 1
    for table in ("evidence", "evidence_links", "decisions"):
        assert selected_state["counts"][table] == before["counts"][table]
    conn = connect(resolve_paths(root).db_path)
    try:
        decision = conn.execute(
            "SELECT status, selected_option FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        event_types = {
            row["event_type"]
            for row in conn.execute("SELECT event_type FROM events WHERE entity_id = ?", (decision_id,))
        }
    finally:
        conn.close()
    assert dict(decision) == {"status": "resolved", "selected_option": "OPT-A"}
    assert "profile_decision_selected" in event_types
    assert "decision_resolved" not in event_types
    assert main(select_a) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["replayed"] is True
    assert replay["event_id"] == selected["event_id"]
    assert _snapshot(root) == selected_state
    assert main([*base_select[:-1], "--candidate", "OPT-B", "--override-reason", "Owner accepts risk", "--json"]) == 2
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["error"]["code"] == "profile_decision_selection_conflict"
    assert _snapshot(root) == selected_state


def test_profile_proposal_hash_drift_missing_source_and_decline(
    tmp_path: Path,
    capsys,
) -> None:
    drift_parent = tmp_path / "drift"
    drift_parent.mkdir()
    root, task_id, request_path, request = _prepared(drift_parent, capsys)
    bundle_path = _bundle(drift_parent, request, task_id, "needs_human")
    command = [
        "--root", str(root), "profile", "ingest", "--request", str(request_path),
        "--bundle", str(bundle_path), "--json",
    ]
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    decision_id = result["decisions"][0]["decision_id"]
    manifest = _json(root / result["evidence"]["manifest_path"])
    proposal_member = next(item for item in manifest["members"] if item["role"] == "decision_proposal")
    stored = root / result["evidence"]["manifest_path"]
    stored = stored.parent / proposal_member["storage_path"]
    data = stored.read_bytes()
    stored.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    before = _snapshot(root)
    with pytest.raises(ProfileDecisionError) as drifted:
        select_profile_proposal(
            resolve_paths(root), decision_id=decision_id, candidate_id="OPT-A", decline=False,
            actor="human:owner", actor_kind=None, recorded_by="agent:codex",
            recorder_kind=None, source_kind="cockpit", source_ref="cockpit-task-0159",
            reason="Select", override_reason=None,
        )
    assert drifted.value.code == "profile_decision_evidence_drifted"
    assert _snapshot(root) == before

    decline_parent = tmp_path / "decline"
    decline_parent.mkdir()
    root, task_id, request_path, request = _prepared(decline_parent, capsys)
    bundle_path = _bundle(decline_parent, request, task_id, "needs_human")
    assert main([
        "--root", str(root), "profile", "ingest", "--request", str(request_path),
        "--bundle", str(bundle_path), "--json",
    ]) == 0
    decision_id = json.loads(capsys.readouterr().out)["decisions"][0]["decision_id"]
    before = _snapshot(root)
    with pytest.raises(ProfileDecisionError) as missing_source:
        select_profile_proposal(
            resolve_paths(root), decision_id=decision_id, candidate_id=None, decline=True,
            actor="human:owner", actor_kind=None, recorded_by=None, recorder_kind=None,
            source_kind=None, source_ref=None, reason="Decline all", override_reason=None,
        )
    assert missing_source.value.code == "profile_decision_source_required"
    assert _snapshot(root) == before
    assert main([
        "--root", str(root), "decision", "proposal", "select", decision_id,
        "--decline", "--actor", "human:owner", "--source-kind", "conversation",
        "--source-ref", "conversation-0159", "--reason", "No candidate is acceptable",
        "--json",
    ]) == 0
    declined = json.loads(capsys.readouterr().out)
    assert declined["selected_option"] == "declined_all_candidates"


def _network_candidate(root: Path, request: dict, *, now: str = "2026-07-12T05:00:00Z") -> dict:
    return prepare_profile_request(
        resolve_paths(root),
        runner_profile_id="council.discovery",
        target_ref=f"task:{request['target']['id']}",
        brief_id=request["work_brief"]["evidence_id"],
        now=now,
        network_access="requested",
        paid_service_requested=True,
        allowed_providers=["provider-a"],
        repository_content_policy="selected_snippets",
        monetary_budget=10.0,
        currency="USD",
    )["request"]


def test_profile_authorize_is_human_gated_bound_and_idempotent(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id, _, offline = _prepared(tmp_path, capsys)
    candidate = _network_candidate(root, offline)
    candidate_path = tmp_path / "candidate.json"
    output = tmp_path / "authorized.json"
    _write(candidate_path, candidate)
    before = _snapshot(root)
    command = [
        "--root", str(root), "profile", "authorize", "--request", str(candidate_path),
        "--output", str(output), "--actor", "human:owner", "--recorded-by", "agent:codex",
        "--source-kind", "cockpit", "--source-ref", "cockpit-task-0159",
        "--reason", "Authorize bounded paid Council discovery", "--max-cost", "12",
        "--currency", "USD", "--provider", "provider-a", "--data-class",
        "selected_snippets", "--expires-at", "2026-07-13T00:00:00Z", "--json",
    ]
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    authorized = _json(output)
    assert result["runner_executed"] is False
    assert authorized["request_id"] == candidate["request_id"]
    assert authorized["request_basis_digest"] == candidate["request_basis_digest"]
    assert authorized["request_digest"] != candidate["request_digest"]
    assert authorized["authorization"]["actor"] == "human:owner"
    assert authorized["authorization"]["event_id"] == result["event_id"]
    assert validate_profile_run_request(authorized).ok
    after = _snapshot(root)
    for table in ("evidence", "evidence_links", "events", "outbox_records"):
        assert after["counts"][table] == before["counts"][table] + 1
    assert after["counts"]["decisions"] == before["counts"]["decisions"]

    replay_before = _snapshot(root)
    assert main(command) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["changed"] is False
    assert replay["replayed"] is True
    assert replay["evidence_id"] == result["evidence_id"]
    assert replay["event_id"] == result["event_id"]
    assert _snapshot(root) == replay_before

    bundle_path = _bundle(tmp_path, authorized, task_id, "completed")
    assert main([
        "--root", str(root), "profile", "ingest", "--request", str(output),
        "--bundle", str(bundle_path), "--dry-run", "--json",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert "profile_authorization_expired" in {
        item["code"]
        for item in authorization_findings(
            resolve_paths(root), authorized, now="2100-01-01T00:00:00Z"
        )
    }

    expanded = copy.deepcopy(authorized)
    expanded["data_policy"]["allowed_providers"].append("provider-b")
    expanded["request_basis_digest"]["value"] = request_basis_digest(expanded)
    expanded["request_digest"]["value"] = request_digest(expanded)
    expanded_validation = validate_profile_run_request(expanded)
    assert not expanded_validation.ok
    assert any("profile_authorization_basis_mismatch" in error for error in expanded_validation.errors)

    conn = connect_mutation(resolve_paths(root))
    try:
        append_event(
            conn=conn,
            events_path=resolve_paths(root).events_path,
            event_type="profile_authorization_revoked",
            entity_type="evidence",
            entity_id=result["evidence_id"],
            payload={"authorized_event_id": result["event_id"], "reason": "Owner revoked scope"},
        )
        conn.commit()
    finally:
        conn.close()
    revoked_before = _snapshot(root)
    assert main([
        "--root", str(root), "profile", "ingest", "--request", str(output),
        "--bundle", str(bundle_path), "--dry-run", "--json",
    ]) == 1
    revoked = json.loads(capsys.readouterr().out)
    assert "profile_authorization_revoked" in {
        item["code"] for item in revoked["error"]["details"]["findings"]
    }
    assert _snapshot(root) == revoked_before
    conn = connect(resolve_paths(root).db_path)
    try:
        candidate_evidence_path = conn.execute(
            "SELECT path FROM evidence WHERE id = ?",
            (result["evidence_id"],),
        ).fetchone()["path"]
    finally:
        conn.close()
    stored_candidate = root / str(candidate_evidence_path)
    candidate_bytes = stored_candidate.read_bytes()
    stored_candidate.write_bytes(bytes([candidate_bytes[0] ^ 1]) + candidate_bytes[1:])
    audit = audit_check(resolve_paths(root))
    assert "evidence_metadata_file_mismatch" in {
        item["type"]
        for classification in audit["anomalies"].values()
        for item in classification
    }


def test_profile_authorize_rejects_agent_scope_expiry_source_and_stale_basis(
    tmp_path: Path,
    capsys,
) -> None:
    root, _, _, offline = _prepared(tmp_path, capsys)
    candidate = _network_candidate(root, offline)
    candidate_path = tmp_path / "candidate.json"
    _write(candidate_path, candidate)
    base = dict(
        request_file=str(candidate_path),
        output=str(tmp_path / "authorized.json"),
        actor_kind=None,
        recorded_by=None,
        recorder_kind=None,
        source_kind="cockpit",
        source_ref="cockpit-task-0159",
        reason="Bound authorization",
        max_cost=12.0,
        currency="USD",
        allowed_providers=["provider-a"],
        data_classes=["selected_snippets"],
        expires_at=None,
        now="2026-07-12T05:05:00Z",
    )
    before = _snapshot(root)
    with pytest.raises(ProfileAuthorizationError) as agent_only:
        authorize_profile_request(resolve_paths(root), actor="agent:bot", **base)
    assert agent_only.value.code == "profile_authorization_human_required"
    assert _snapshot(root) == before

    with pytest.raises(ProfileAuthorizationError) as missing_source:
        authorize_profile_request(
            resolve_paths(root), actor="human:owner", **{**base, "source_ref": None}
        )
    assert missing_source.value.code == "profile_authorization_source_required"
    assert _snapshot(root) == before

    with pytest.raises(ProfileAuthorizationError) as provider_scope:
        authorize_profile_request(
            resolve_paths(root), actor="human:owner", **{**base, "allowed_providers": []}
        )
    assert provider_scope.value.code == "profile_authorization_provider_scope"
    assert _snapshot(root) == before

    with pytest.raises(ProfileAuthorizationError) as expired:
        authorize_profile_request(
            resolve_paths(root), actor="human:owner", **{**base, "expires_at": "2026-07-12T05:00:00Z"}
        )
    assert expired.value.code == "profile_authorization_expired"
    assert _snapshot(root) == before

    extra = tmp_path / "extra.txt"
    extra.write_text("semantic linked Evidence", encoding="utf-8")
    assert main([
        "--root", str(root), "evidence", "add", "--file", str(extra),
        "--summary", "Changes candidate linked Evidence", "--task", candidate["target"]["id"],
        "--json",
    ]) == 0
    capsys.readouterr()
    stale_before = _snapshot(root)
    with pytest.raises(ProfileAuthorizationError) as stale:
        authorize_profile_request(resolve_paths(root), actor="human:owner", **base)
    assert stale.value.code == "profile_authorization_stale_basis"
    assert _snapshot(root) == stale_before
