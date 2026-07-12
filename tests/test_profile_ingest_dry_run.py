from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from pcl.cli import main
from pcl.contracts.profile_output_bundle import bundle_digest
from pcl.contracts.profile_run_request import request_basis_digest, request_digest
from pcl.db import connect
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.profile_prepare import prepare_profile_request
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
