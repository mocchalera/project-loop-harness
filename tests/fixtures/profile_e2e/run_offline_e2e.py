from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil

from pcl.cli import main


def call(arguments: list[str], *, expected: int = 0) -> dict:
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = main([*arguments, "--json"])
    if code != expected:
        raise RuntimeError(
            f"command failed: {arguments}; expected={expected} actual={code}; output={stream.getvalue()}"
        )
    return json.loads(stream.getvalue())


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run(root: Path, status: str) -> dict:
    root.mkdir(parents=True)
    call(["init", "--target", str(root)])
    started = call(["--root", str(root), "start", "Offline Council fixture E2E"])
    task_id = started["result"]["created_ids"]["task"]
    fixture_root = Path(__file__).resolve().parents[1]
    brief = json.loads((fixture_root / "work_brief" / "minimal.json").read_text(encoding="utf-8"))
    brief["target"]["id"] = task_id
    brief_path = root.parent / "brief.json"
    brief_path.write_text(json.dumps(brief, sort_keys=True), encoding="utf-8")
    brief_result = call(
        ["--root", str(root), "brief", "add", str(brief_path), "--summary", "Offline E2E Brief"]
    )
    brief_evidence = brief_result["evidence"]["id"]
    call(
        [
            "--root", str(root), "route", "recommend", "--target", f"task:{task_id}",
            "--brief", str(brief_path), "--record",
        ]
    )
    request_path = root.parent / "request.json"
    prepared = call(
        [
            "--root", str(root), "profile", "prepare", "council.discovery",
            "--target", f"task:{task_id}", "--brief", brief_evidence,
            "--output", str(request_path),
        ]
    )
    if prepared["runner_executed"] is not False:
        raise RuntimeError("prepare unexpectedly executed a runner")

    output_one = root.parent / "fixture-one"
    output_two = root.parent / "fixture-two"
    first = call(
        [
            "profile", "fixture-run", "--request", str(request_path), "--status", status,
            "--output-dir", str(output_one),
        ]
    )
    call(
        [
            "profile", "fixture-run", "--request", str(request_path), "--status", status,
            "--output-dir", str(output_two),
        ]
    )
    if tree_hash(output_one) != tree_hash(output_two):
        raise RuntimeError("fixture output is not byte deterministic")
    bundle = output_one / "profile-output-bundle.json"
    before_loop_hash = tree_hash(root / ".project-loop")
    dry_run = call(
        [
            "--root", str(root), "profile", "ingest", "--request", str(request_path),
            "--bundle", str(bundle), "--dry-run",
        ],
        expected=1 if status == "malformed" else 0,
    )
    if tree_hash(root / ".project-loop") != before_loop_hash:
        raise RuntimeError("fixture-run or dry-run mutated Project Loop state")
    if status == "malformed":
        return {
            "ok": True,
            "status": status,
            "malformed_rejected": dry_run["error"]["code"] == "profile_bundle_invalid",
            "deterministic": True,
            "provider_code_present": first["provider_code_present"],
        }
    if dry_run["next_action"]["safe_to_run"] is not False:
        raise RuntimeError("fixture status became execution-ready")
    ingest_args = [
        "--root", str(root), "profile", "ingest", "--request", str(request_path),
        "--bundle", str(bundle),
    ]
    if status == "failed":
        ingest_args.extend(["--accept-failed", "--summary", "Retain offline failure fixture"])
    ingested = call(ingest_args)
    selection = None
    projection_ok = None
    brief_separate = None
    if status == "needs_human":
        decision_id = ingested["decisions"][0]["decision_id"]
        before_gate = tree_hash(root / ".project-loop")
        for legacy in (
            ["decision", "resolve", decision_id, "--selected-option", "OPT-A", "--reason", "bypass"],
            ["decision", "waive", decision_id, "--reason", "bypass"],
        ):
            rejected = call(["--root", str(root), *legacy], expected=2)
            if rejected["error"]["code"] != "decision_proposal_command_required":
                raise RuntimeError("legacy Decision bypass was not rejected")
            if tree_hash(root / ".project-loop") != before_gate:
                raise RuntimeError("legacy Decision bypass mutated state")
        shown = call(["--root", str(root), "decision", "proposal", "show", decision_id])
        projection = json.loads(
            (Path(__file__).parent / "decision-projection.expected.json").read_text(encoding="utf-8")
        )
        projection_ok = all(
            dotted_get(shown, field) is not None for field in projection["required_fields"]
        )
        selection = call(
            [
                "--root", str(root), "decision", "proposal", "select", decision_id,
                "--candidate", "OPT-A", "--actor", "human:fixture-owner",
                "--source-kind", "conversation", "--source-ref", "offline-e2e",
                "--reason", "Explicit fixture selection",
            ]
        )
        original = call(["--root", str(root), "brief", "show", "--evidence", brief_evidence])
        if original["work_brief"]["approved"] is not False:
            raise RuntimeError("Decision selection auto-approved the Work Brief")
        revised = dict(brief)
        revised["brief_id"] = "WB-0002"
        revised["assumptions"][0]["status"] = "supported"
        revised_path = root.parent / "brief-revised.json"
        revised_path.write_text(json.dumps(revised, sort_keys=True), encoding="utf-8")
        revised_result = call(
            ["--root", str(root), "brief", "add", str(revised_path), "--summary", "Explicit revision"]
        )
        revised_id = revised_result["evidence"]["id"]
        call(
            [
                "--root", str(root), "brief", "review", revised_id,
                "--actor", "human:fixture-owner", "--reason", "Explicit review",
            ]
        )
        call(
            [
                "--root", str(root), "brief", "approve", revised_id,
                "--actor", "human:fixture-owner", "--reason", "Explicit approval",
            ]
        )
        approved = call(["--root", str(root), "brief", "show", "--evidence", revised_id])
        brief_separate = approved["work_brief"]["approved"] is True
    return {
        "ok": True,
        "status": status,
        "bundle_status": dry_run["bundle"]["status"],
        "next_action": dry_run["next_action"],
        "deterministic": True,
        "provider_code_present": first["provider_code_present"],
        "network_used": first["network_used"],
        "paid_service_used": first["paid_service_used"],
        "evidence_id": ingested["evidence"]["id"],
        "selection": selection,
        "projection_ok": projection_ok,
        "brief_revision_review_approval_separate": brief_separate,
    }


def dotted_get(value: dict, path: str):
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def main_entry() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--status", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    if root.exists():
        shutil.rmtree(root)
    result = run(root, args.status)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry())
