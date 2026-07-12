from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pcl.cli import main
from pcl.contracts.profile_run_request import validate_profile_run_request
from pcl.db import connect
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.profile_prepare import prepare_profile_request
from pcl.start import start_work


BRIEF_FIXTURE = Path(__file__).parent / "fixtures" / "work_brief" / "minimal.json"


def _initialized_target(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    paths = resolve_paths(root)
    init_project(paths)
    started = start_work(paths, intent="Prepare a Council Profile request")
    return root, str(started["result"]["created_ids"]["task"])


def _brief_file(
    tmp_path: Path,
    task_id: str,
    *,
    brief_id: str = "WB-0001",
    assumption_status: str = "unverified",
) -> Path:
    value = json.loads(BRIEF_FIXTURE.read_text(encoding="utf-8"))
    value["brief_id"] = brief_id
    value["target"]["id"] = task_id
    value["assumptions"][0]["status"] = assumption_status
    path = tmp_path / f"{brief_id.lower()}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _add_brief(root: Path, brief: Path, capsys) -> str:
    assert (
        main(
            [
                "--root",
                str(root),
                "brief",
                "add",
                str(brief),
                "--summary",
                "Council candidate brief",
                "--json",
            ]
        )
        == 0
    )
    return str(json.loads(capsys.readouterr().out)["evidence"]["id"])


def _record_route(
    root: Path,
    task_id: str,
    capsys,
    *,
    brief: Path | None,
    changed_paths: list[str] | None = None,
) -> dict:
    command = [
        "--root",
        str(root),
        "route",
        "recommend",
        "--target",
        f"task:{task_id}",
    ]
    if brief is not None:
        command.extend(["--brief", str(brief)])
    for path in changed_paths or []:
        command.extend(["--changed-path", path])
    command.extend(["--record", "--json"])
    assert main(command) == 0
    return json.loads(capsys.readouterr().out)


def _state_snapshot(root: Path) -> dict:
    loop = root / ".project-loop"
    conn = connect(loop / "project.db")
    try:
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("evidence", "evidence_links", "events", "outbox_records")
        }
    finally:
        conn.close()
    files = {}
    for directory in (
        loop / "evidence",
        loop / "reports",
        loop / "dashboard",
        loop / "exports",
    ):
        if not directory.exists():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            files[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return {
        "counts": counts,
        "events_jsonl": hashlib.sha256(
            (loop / "events.jsonl").read_bytes()
        ).hexdigest(),
        "files": files,
    }


def test_prepare_requires_recorded_route_and_is_zero_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    brief = _brief_file(tmp_path, task_id)
    evidence_id = _add_brief(root, brief, capsys)
    before = _state_snapshot(root)

    assert (
        main(
            [
                "--root",
                str(root),
                "profile",
                "prepare",
                "council.discovery",
                "--target",
                f"task:{task_id}",
                "--brief",
                evidence_id,
                "--json",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "profile_route_recommendation_missing"
    assert "--record" in payload["error"]["details"]["suggested_command"]
    assert _state_snapshot(root) == before


def test_prepare_is_deterministic_read_only_and_writes_only_explicit_output(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    brief = _brief_file(tmp_path, task_id)
    evidence_id = _add_brief(root, brief, capsys)
    route = _record_route(root, task_id, capsys, brief=brief)
    (root / ".env").write_text(
        "PROFILE_PREPARE_SECRET_SENTINEL=must-not-leak\n",
        encoding="utf-8",
    )
    before = _state_snapshot(root)
    paths = resolve_paths(root)

    first = prepare_profile_request(
        paths,
        runner_profile_id="council.discovery",
        target_ref=f"task:{task_id}",
        brief_id=evidence_id,
        now="2026-07-12T01:00:00Z",
    )
    second = prepare_profile_request(
        paths,
        runner_profile_id="council.discovery",
        target_ref=f"task:{task_id}",
        brief_id=evidence_id,
        now="2026-07-12T03:00:00Z",
    )
    assert first["request"]["generated_at"] != second["request"]["generated_at"]
    assert (
        first["request"]["request_basis_digest"]
        == second["request"]["request_basis_digest"]
    )
    assert first["request"]["request_id"] == second["request"]["request_id"]
    assert first["request"]["route"] == second["request"]["route"]
    assert (
        first["request"]["route"]["recommendation_evidence_id"]
        == route["evidence"]["id"]
    )
    assert validate_profile_run_request(first["request"]).ok
    serialized_request = json.dumps(first["request"], ensure_ascii=False)
    assert str(root.resolve()) not in serialized_request
    assert "PROFILE_PREPARE_SECRET_SENTINEL" not in serialized_request
    assert first["runner_executed"] is False
    assert first["authorization_status"] == "not_required_offline"
    assert first["request"]["authorization"] is None
    assert first["request"]["data_policy"]["network_access"] == "forbidden"
    assert first["request"]["data_policy"]["paid_service_requested"] is False
    assert _state_snapshot(root) == before

    output = tmp_path / "request.json"
    assert (
        main(
            [
                "--root",
                str(root),
                "profile",
                "prepare",
                "council.discovery",
                "--target",
                f"task:{task_id}",
                "--brief",
                evidence_id,
                "--output",
                str(output),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["output_path"] == str(output)
    assert json.loads(output.read_text(encoding="utf-8")) == payload["request"]
    assert _state_snapshot(root) == before
    assert sorted(path.name for path in tmp_path.iterdir() if path.is_file()) == [
        "request.json",
        "wb-0001.json",
    ]


def test_prepare_rejects_ambiguous_work_briefs(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    first = _brief_file(tmp_path, task_id, brief_id="WB-0001")
    second = _brief_file(tmp_path, task_id, brief_id="WB-0002")
    _add_brief(root, first, capsys)
    _add_brief(root, second, capsys)
    before = _state_snapshot(root)

    assert (
        main(
            [
                "--root",
                str(root),
                "profile",
                "prepare",
                "council.discovery",
                "--target",
                f"task:{task_id}",
                "--json",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "profile_work_brief_ambiguous"
    assert payload["error"]["details"]["evidence_ids"] == ["E-0002", "E-0003"]
    assert _state_snapshot(root) == before


def test_prepare_detects_stale_and_tampered_route_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    brief = _brief_file(tmp_path, task_id)
    evidence_id = _add_brief(root, brief, capsys)
    _record_route(
        root,
        task_id,
        capsys,
        brief=brief,
        changed_paths=["src/security/session.py"],
    )

    approve = [
        "--root",
        str(root),
        "brief",
        "approve",
        evidence_id,
        "--actor",
        "human:owner",
        "--reason",
        "Approve for stale route test",
        "--json",
    ]
    assert main(approve) == 0
    capsys.readouterr()
    before = _state_snapshot(root)
    assert (
        main(
            [
                "--root",
                str(root),
                "profile",
                "prepare",
                "council.discovery",
                "--target",
                f"task:{task_id}",
                "--json",
            ]
        )
        == 1
    )
    stale = json.loads(capsys.readouterr().out)
    assert stale["error"]["code"] == "profile_route_recommendation_stale"
    assert "src/security/session.py" in stale["error"]["details"]["suggested_command"]
    assert _state_snapshot(root) == before

    second_root, second_task = _initialized_target(tmp_path / "tamper")
    second_brief = _brief_file(tmp_path, second_task, brief_id="WB-0003")
    second_evidence = _add_brief(second_root, second_brief, capsys)
    second_route = _record_route(second_root, second_task, capsys, brief=second_brief)
    artifact = second_root / second_route["evidence"]["path"]
    value = json.loads(artifact.read_text(encoding="utf-8"))
    value["reason_codes"].append("tampered")
    artifact.write_text(json.dumps(value), encoding="utf-8")
    assert (
        main(
            [
                "--root",
                str(second_root),
                "profile",
                "prepare",
                "council.discovery",
                "--target",
                f"task:{second_task}",
                "--brief",
                second_evidence,
                "--json",
            ]
        )
        == 1
    )
    tampered = json.loads(capsys.readouterr().out)
    assert tampered["error"]["code"] == "profile_route_recommendation_integrity"


def test_prepare_rejects_direct_route_with_audited_override_guidance(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    brief = _brief_file(
        tmp_path,
        task_id,
        assumption_status="supported",
    )
    evidence_id = _add_brief(root, brief, capsys)
    config = root / "pcl.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            '  lint: ""',
            '  lint: "ruff check ."',
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--root",
                str(root),
                "brief",
                "approve",
                evidence_id,
                "--actor",
                "human:owner",
                "--reason",
                "Clear brief",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    route = _record_route(root, task_id, capsys, brief=None)
    assert route["recommendation"]["profile"] == "direct"
    before = _state_snapshot(root)

    assert (
        main(
            [
                "--root",
                str(root),
                "profile",
                "prepare",
                "council.discovery",
                "--target",
                f"task:{task_id}",
                "--json",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "profile_route_mismatch"
    assert "pcl route override" in " ".join(
        payload["error"]["details"]["suggested_commands"]
    )
    assert _state_snapshot(root) == before


def test_prepare_binds_audited_override_and_original_recommendation(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    brief = _brief_file(tmp_path, task_id)
    evidence_id = _add_brief(root, brief, capsys)
    original = _record_route(root, task_id, capsys, brief=brief)
    assert original["recommendation"]["profile"] == "discover"

    assert (
        main(
            [
                "--root",
                str(root),
                "route",
                "override",
                "--target",
                f"task:{task_id}",
                "--profile",
                "assure",
                "--actor",
                "human:owner",
                "--reason",
                "Use an independent assurance pass",
                "--brief",
                str(brief),
                "--json",
            ]
        )
        == 0
    )
    override = json.loads(capsys.readouterr().out)
    before = _state_snapshot(root)

    assert (
        main(
            [
                "--root",
                str(root),
                "profile",
                "prepare",
                "council.discovery",
                "--target",
                f"task:{task_id}",
                "--brief",
                evidence_id,
                "--json",
            ]
        )
        == 0
    )
    request = json.loads(capsys.readouterr().out)["request"]
    assert request["route"]["route_profile"] == "assure"
    assert (
        request["route"]["recommendation_evidence_id"]
        == override["evidence"]["original_recommendation"]["id"]
    )
    assert (
        request["route"]["override"]["evidence_id"]
        == override["evidence"]["override"]["id"]
    )
    assert len(request["route"]["recommendation_sha256"]) == 64
    assert len(request["route"]["override"]["artifact_sha256"]) == 64
    assert validate_profile_run_request(request).ok
    assert _state_snapshot(root) == before
