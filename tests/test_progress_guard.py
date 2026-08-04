from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from pcl.cli import main
from pcl.db import SCHEMA_VERSION, connect


GOAL_ID = "G-0001"
GATE_ID = "release-ready"


def _json(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init_goal(root: Path, capsys, *, title: str = "Ship behavior") -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main([
        "--root", str(root), "goal", "create", "--title", title,
    ]) == 0
    capsys.readouterr()


def _activate(root: Path, capsys, *, goal_id: str = GOAL_ID, gate: str = GATE_ID) -> dict:
    assert main([
        "--root", str(root), "progress", "guard", "activate",
        "--goal", goal_id,
        "--exit-gate", gate,
        "--json",
    ]) == 0
    return _json(capsys)["progressGuard"]


def _observe(
    root: Path,
    capsys,
    *,
    token: str,
    delta: int,
    classification: str = "mainline_product",
    value_kind: str | None = None,
    goal_id: str = GOAL_ID,
    gate: str = GATE_ID,
    task_label: str = "T-alpha",
    run_label: str = "run-a",
    route_label: str = "Route C",
) -> dict:
    args = [
        "--root", str(root), "progress", "guard", "observe",
        "--goal", goal_id,
        "--exit-gate", gate,
        "--delta", str(delta),
        "--classification", classification,
        "--criterion", "fresh-render",
        "--surface", "video:final-render",
        "--value-token", token,
        "--summary", f"Observation for {token}",
        "--evidence-ref", f"artifact:{token}",
        "--task-label", task_label,
        "--run-label", run_label,
        "--route-label", route_label,
    ]
    if value_kind is not None:
        args.extend(["--value-kind", value_kind])
    args.append("--json")
    assert main(args) == 0
    return _json(capsys)


def _status(root: Path, capsys, *, goal_id: str = GOAL_ID, gate: str = GATE_ID) -> dict:
    assert main([
        "--root", str(root), "progress", "guard", "status",
        "--goal", goal_id,
        "--exit-gate", gate,
        "--json",
    ]) == 0
    return _json(capsys)["progressGuard"]


def _event_outbox_counts(root: Path) -> tuple[int, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        events = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type LIKE 'progress_guard_%'"
        ).fetchone()[0]
        outbox = conn.execute(
            """
            SELECT COUNT(*)
            FROM outbox_records
            JOIN events ON events.id = outbox_records.event_id
            WHERE events.event_type LIKE 'progress_guard_%'
            """
        ).fetchone()[0]
        return int(events), int(outbox)
    finally:
        conn.close()


def test_plh_lineage_survives_aliases_restart_duplicate_replan_and_value(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "project"
    _init_goal(root, capsys)

    activated = _activate(root, capsys)
    assert activated["contractVersion"] == "progress-guard/v1"
    assert activated["goal"] == GOAL_ID
    assert activated["gate"] == GATE_ID
    assert activated["limit"] == 2
    assert activated["lineage"]["projectInstance"]
    assert activated["lineage"]["id"].startswith("pg-sha256:")
    assert _event_outbox_counts(root) == (1, 1)
    replayed_activation = _activate(root, capsys)
    assert replayed_activation == activated
    assert _event_outbox_counts(root) == (1, 1)

    first = _observe(
        root,
        capsys,
        token="zero-route-c",
        delta=0,
        classification="harness_support",
        task_label="T-0054",
        run_label="run-11",
        route_label="Route C",
    )
    assert first["changed"] is True
    assert first["observation"]["effectiveDelta"] == 0
    assert first["progressGuard"]["consecutiveZero"] == 1

    second = _observe(
        root,
        capsys,
        token="zero-route-d",
        delta=0,
        classification="deferred",
        task_label="T-0099",
        run_label="run-42",
        route_label="Route D",
    )
    assert second["progressGuard"]["decision"] == "stop_and_replan"
    assert second["progressGuard"]["stopped"] is True
    assert second["progressGuard"]["consecutiveZero"] == 2
    assert _event_outbox_counts(root) == (3, 3)

    duplicate = _observe(
        root,
        capsys,
        token="zero-route-d",
        delta=0,
        classification="deferred",
        task_label="replacement-task",
        run_label="replacement-run",
        route_label="offline-cache-v9",
    )
    assert duplicate["changed"] is False
    assert duplicate["duplicate"] is True
    assert duplicate["observation"]["effectiveDelta"] == 0
    assert _event_outbox_counts(root) == (3, 3)

    # A new read-only connection reconstructs the same state from Events.
    restarted = _status(root, capsys)
    assert restarted["consecutiveZero"] == 2
    assert restarted["totalObservations"] == 2
    assert restarted["consumedTokens"] == ["zero-route-c", "zero-route-d"]
    assert restarted["lastObservation"]["source"] == {
        "route": "Route D",
        "run": "run-42",
        "task": "T-0099",
    }

    assert main([
        "--root", str(root), "progress", "guard", "replan",
        "--goal", GOAL_ID,
        "--exit-gate", GATE_ID,
        "--revision-token", "plan-revision-2",
        "--reason", "Operator changed the behavior-facing render plan.",
        "--operator", "operator:release-owner",
        "--json",
    ]) == 0
    replanned = _json(capsys)["progressGuard"]
    assert replanned["stopped"] is False
    assert replanned["consecutiveZero"] == 0
    assert replanned["replanRevision"] == "plan-revision-2"
    assert replanned["totalObservations"] == 2
    assert replanned["consumedTokens"] == ["zero-route-c", "zero-route-d"]
    assert _event_outbox_counts(root) == (4, 4)

    assert main([
        "--root", str(root), "progress", "guard", "replan",
        "--goal", GOAL_ID,
        "--exit-gate", GATE_ID,
        "--revision-token", "plan-revision-2",
        "--reason", "Exact revision replay.",
        "--operator", "operator:release-owner",
        "--json",
    ]) == 0
    replan_replay = _json(capsys)
    assert replan_replay["changed"] is False
    assert replan_replay["duplicate"] is True
    assert _event_outbox_counts(root) == (4, 4)

    closed = _observe(
        root,
        capsys,
        token="criterion-fresh-render-v1",
        delta=1,
        value_kind="criterion_closed",
        task_label="T-successor",
        run_label="run-success",
        route_label="Route A",
    )["progressGuard"]
    assert closed["decision"] == "continue"
    assert closed["consecutiveZero"] == 0
    assert closed["totalObservations"] == 3
    assert closed["valueEvents"] == 1
    assert closed["supportCount"] == 1
    assert closed["deferredCount"] == 1
    assert closed["offMainline"] == {
        "denominator": 3,
        "numerator": 2,
        "ratio": 2 / 3,
    }
    duplicate_value = _observe(
        root,
        capsys,
        token="criterion-fresh-render-v1",
        delta=1,
        value_kind="criterion_closed",
        task_label="T-replayed",
        run_label="run-replayed",
        route_label="Route D",
    )
    assert duplicate_value["changed"] is False
    assert duplicate_value["observation"]["effectiveDelta"] == 0
    assert duplicate_value["observation"]["originalEffectiveDelta"] == 1
    assert duplicate_value["progressGuard"] == closed
    assert _event_outbox_counts(root) == (5, 5)

    conn = connect(root / ".project-loop" / "project.db")
    try:
        replan_payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM events WHERE event_type = 'progress_guard_replan_recorded'"
            ).fetchone()["payload_json"]
        )
    finally:
        conn.close()
    assert replan_payload["operator"] == "operator:release-owner"
    assert replan_payload["operator_attestation"] is True
    assert replan_payload["cryptographic_human_authentication"] is False


def _seed_video_os_fixture(root: Path) -> None:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        now = "2026-08-04T00:00:00+00:00"
        conn.execute(
            "INSERT INTO goals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "G-0054",
                "Video OS final render exit gate",
                "open",
                json.dumps(
                    {
                        "fresh_render": False,
                        "human_acceptance": False,
                        "product_red": False,
                        "verdict": "unchanged",
                    },
                    sort_keys=True,
                ),
                "{}",
                "{}",
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO features VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "F-0054", "Fresh final render", "video:final-render", "fixture",
                "needs_test", "medium", now, now,
            ),
        )
        conn.execute(
            "INSERT INTO user_stories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "US-0054", "F-0054", "editor", "fresh final render", None,
                "reviewable render and human acceptance", "approved", now, now,
            ),
        )
        conn.execute(
            """
            INSERT INTO tasks(
              id, title, description, status, priority, owner, risk, effort,
              related_goal_id, related_feature_id, related_defect_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "T-0054", "Produce fresh final render", "fixture", "todo", 100,
                None, None, None, "G-0054", "F-0054", None, now, now,
            ),
        )
        for number in range(165, 169):
            conn.execute(
                "INSERT INTO test_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"TC-{number:04d}", "F-0054", "US-0054", "acceptance",
                    f"Video fixture {number}", "fresh behavior-facing render",
                    "planned", None, None, now, now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _video_product_snapshot(root: Path) -> dict:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            "goal": dict(conn.execute("SELECT * FROM goals WHERE id = 'G-0054'").fetchone()),
            "task": dict(conn.execute("SELECT * FROM tasks WHERE id = 'T-0054'").fetchone()),
            "tests": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM test_cases WHERE id BETWEEN 'TC-0165' AND 'TC-0168' ORDER BY id"
                ).fetchall()
            ],
        }
    finally:
        conn.close()


def test_video_os_stop_blocks_next_successor_and_workflow_pre_effect(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "video-os"
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()
    _seed_video_os_fixture(root)
    _activate(root, capsys, goal_id="G-0054", gate="fresh-final-render")

    _observe(
        root, capsys,
        goal_id="G-0054", gate="fresh-final-render",
        token="vm-cache-plan", delta=0, classification="harness_support",
        task_label="T-0054", run_label="WR-0054", route_label="Route C",
    )
    stopped = _observe(
        root, capsys,
        goal_id="G-0054", gate="fresh-final-render",
        token="artifact-version-v12", delta=0, classification="harness_support",
        task_label="T-replacement", run_label="WR-successor", route_label="Route D",
    )["progressGuard"]
    assert stopped["decision"] == "stop_and_replan"
    product_before = _video_product_snapshot(root)

    assert main([
        "--root", str(root), "next", "--target", "T-0054", "--json",
    ]) == 0
    action = _json(capsys)
    assert action["type"] == "stop_and_replan"
    assert action["command"].startswith("pcl progress guard replan ")
    assert action["safe_to_run"] is False
    assert action["run_policy"] == "human_decision"
    assert action["progressGuard"]["gate"] == "fresh-final-render"

    conn = connect(root / ".project-loop" / "project.db")
    try:
        counts_before = {
            "tasks": conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
            "runs": conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0],
            "jobs": conn.execute("SELECT COUNT(*) FROM agent_jobs").fetchone()[0],
        }
    finally:
        conn.close()

    assert main([
        "--root", str(root), "start", "Create successor/replacement task",
        "--goal", "G-0054", "--json",
    ]) == 2
    assert _json(capsys)["error"]["code"] == "progress_guard_stopped"

    assert main([
        "--root", str(root), "loop", "run", "feature_coverage",
        "--goal", "G-0054", "--json",
    ]) == 2
    assert _json(capsys)["error"]["code"] == "progress_guard_stopped"

    conn = connect(root / ".project-loop" / "project.db")
    try:
        counts_after = {
            "tasks": conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
            "runs": conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0],
            "jobs": conn.execute("SELECT COUNT(*) FROM agent_jobs").fetchone()[0],
        }
    finally:
        conn.close()
    assert counts_after == counts_before
    assert _video_product_snapshot(root) == product_before
    completion = json.loads(product_before["goal"]["completion_json"])
    assert completion == {
        "fresh_render": False,
        "human_acceptance": False,
        "product_red": False,
        "verdict": "unchanged",
    }


def test_authentic_value_permits_continuation_and_support_never_sets_product_red(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "success"
    _init_goal(root, capsys)
    _activate(root, capsys)
    _observe(
        root, capsys, token="harness-diagnosis", delta=0,
        classification="harness_support",
    )
    success = _observe(
        root, capsys, token="fresh-render-sha256-abc", delta=1,
        value_kind="gate_bound_artifact_ready",
        classification="mainline_product",
    )["progressGuard"]

    assert success["stopped"] is False
    assert success["decision"] == "continue"
    assert success["consecutiveZero"] == 0
    assert success["valueEvents"] == 1
    assert success["supportCount"] == 1
    assert success["offMainline"] == {"denominator": 2, "numerator": 1, "ratio": 0.5}

    assert main([
        "--root", str(root), "next", "--target", GOAL_ID, "--json",
    ]) == 0
    assert _json(capsys)["type"] != "stop_and_replan"
    conn = connect(root / ".project-loop" / "project.db")
    try:
        goal = conn.execute("SELECT status FROM goals WHERE id = ?", (GOAL_ID,)).fetchone()
        assert goal["status"] == "open"
    finally:
        conn.close()


def test_guard_mutations_are_event_outbox_atomic_and_rollback_effect_zero(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "atomic"
    _init_goal(root, capsys)
    before = _event_outbox_counts(root)

    import pcl.progress_guard as progress_guard

    original = progress_guard.append_event

    def fail_after_event(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError("injected after event and outbox")

    monkeypatch.setattr(progress_guard, "append_event", fail_after_event)
    with pytest.raises(progress_guard.ProgressGuardDataError):
        progress_guard.activate_progress_guard(
            progress_guard.ProjectPaths(root=root),
            goal_id=GOAL_ID,
            exit_gate=GATE_ID,
        )
    assert _event_outbox_counts(root) == before


def test_guard_input_is_closed_json_is_deterministic_and_unprotected_is_compatible(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "compat"
    _init_goal(root, capsys)

    assert main([
        "--root", str(root), "next", "--target", GOAL_ID, "--json",
    ]) == 0
    unprotected_first = _json(capsys)
    assert main([
        "--root", str(root), "next", "--target", GOAL_ID, "--json",
    ]) == 0
    assert _json(capsys) == unprotected_first

    assert main([
        "--root", str(root), "loop", "run", "feature_coverage",
        "--goal", GOAL_ID, "--json",
    ]) == 0
    unprotected_run = _json(capsys)
    assert unprotected_run["workflow_run"]["id"] == "WR-0001"
    assert len(unprotected_run["jobs"]) == 3

    second = tmp_path / "closed-input"
    _init_goal(second, capsys)
    _activate(second, capsys)
    before = _event_outbox_counts(second)
    assert main([
        "--root", str(second), "progress", "guard", "observe",
        "--goal", GOAL_ID,
        "--exit-gate", GATE_ID,
        "--delta", "1",
        "--classification", "harness_support",
        "--value-kind", "criterion_closed",
        "--criterion", "criterion",
        "--surface", "surface",
        "--value-token", "invalid-support-value",
        "--summary", "Harness work cannot close product criteria.",
        "--evidence-ref", "artifact:harness",
        "--json",
    ]) == 2
    error = _json(capsys)["error"]
    assert error["code"] == "invalid_input"
    assert _event_outbox_counts(second) == before

    with pytest.raises(SystemExit) as invalid_kind:
        main([
            "--root", str(second), "progress", "guard", "observe",
            "--goal", GOAL_ID,
            "--exit-gate", GATE_ID,
            "--delta", "1",
            "--classification", "mainline_product",
            "--value-kind", "review_receipt",
            "--criterion", "criterion",
            "--surface", "surface",
            "--value-token", "closed-kind",
            "--summary", "Closed kind test.",
            "--evidence-ref", "artifact:review",
            "--json",
        ])
    assert invalid_kind.value.code == 2
    capsys.readouterr()
    assert _event_outbox_counts(second) == before

    first_status = _status(second, capsys)
    second_status = _status(second, capsys)
    assert first_status == second_status
    assert first_status["policyOnly"] is True
    assert "not tamper-proof" in first_status["securityBoundary"]


def test_v060_metadata_keeps_schema8_migration0_dependency0_and_documents_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    from pcl import __version__

    assert __version__ == "0.6.0"
    assert SCHEMA_VERSION == 8
    assert sorted((root / "src" / "pcl" / "db" / "migrations").glob("*.sql"))[-1].name == (
        "008_event_outbox.sql"
    )
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.6.0"' in pyproject
    assert "dependencies = []" in pyproject
    docs = (root / "docs" / "mainline-progress-guard-v1.md").read_text(encoding="utf-8")
    normalized_docs = " ".join(docs.split())
    assert "cooperative policy enforcement" in normalized_docs
    assert "not security-grade authorization" in normalized_docs
    assert "external Cockpit task creation" in normalized_docs
    assert "not cryptographic authentication" in normalized_docs
    assert "Delta-1 observations are unverified caller attestations." in normalized_docs
    assert (
        "`--criterion`, `--surface`, `--value-kind`, `--value-token`, and "
        "`--evidence-ref` are syntactically validated and recorded"
    ) in normalized_docs
    assert (
        "does not resolve them against registered criterion, Test, Evidence, or "
        "artifact state"
    ) in normalized_docs
    assert "cannot detect a cooperative but over-optimistic agent" in normalized_docs
    assert "durable audit trail is the detection and review mechanism" in normalized_docs
    assert (
        "operator/agent policy guidance, not an authenticated runtime oracle"
    ) in normalized_docs
    assert "manual `pcl task create`" in normalized_docs

    architecture = (root / "docs" / "architecture.md").read_text(encoding="utf-8")
    normalized_architecture = " ".join(architecture.split())
    task_index = (root / "agent-tasks" / "README.md").read_text(encoding="utf-8")
    normalized_task_index = " ".join(task_index.split())
    for scoped_doc in (normalized_architecture, normalized_task_index):
        assert "`pcl start --goal` successor creation" in scoped_doc
        assert "attached successor" not in scoped_doc
        assert "Manual `pcl task create`" in scoped_doc
        assert "external Cockpit task creation" in scoped_doc
