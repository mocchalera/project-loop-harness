from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect
from pcl.events import append_event
from pcl.paths import ProjectPaths
from pcl.verification_feedback import verification_feedback_stats


FIXTURE = Path(__file__).parent / "fixtures" / "kpi_report_empty_v1.json"


def _json_output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _state_counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("events", "outbox_records", "evidence", "verification_feedback")
        }
    finally:
        conn.close()


def _create_verification_feedback_fixture(root: Path, capsys) -> None:
    receipt_path = root / ".project-loop" / "evidence" / "context-receipts" / "e-0001.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(
            {
                "contract_version": "context-receipt/v0",
                "created_at": "2026-07-10T00:00:00+00:00",
                "evidence_id": "E-0001",
                "receipt_path": ".project-loop/evidence/context-receipts/e-0001.json",
                "verification_suggestions": [
                    {
                        "id": "E-0001/VS-01",
                        "command": "python -m pytest -q tests",
                        "reason": "dogfood verification",
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    conn = connect(root / ".project-loop" / "project.db")
    try:
        conn.executemany(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "E-0001",
                    "context_receipt",
                    ".project-loop/evidence/context-receipts/e-0001.json",
                    "pcl impact --diff",
                    "KPI receipt",
                    "2026-07-10T00:00:00+00:00",
                ),
                (
                    "E-0002",
                    "command_result",
                    "inline:pytest passed",
                    "python -m pytest -q tests",
                    "Passing test evidence",
                    "2026-07-10T00:01:00+00:00",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    assert main([
        "--root",
        str(root),
        "verification",
        "feedback",
        "--suggestion",
        "E-0001/VS-01",
        "--status",
        "executed",
        "--result",
        "passed",
        "--evidence",
        "E-0002",
        "--json",
    ]) == 0
    _json_output(capsys)


def _record_completion_packet_event(root: Path, *, outcome: str) -> None:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        append_event(
            conn=conn,
            events_path=root / ".project-loop" / "events.jsonl",
            event_type="completion_packet_created",
            entity_type="task",
            entity_id="T-0001",
            payload={
                "contract_version": "completion-packet/v1",
                "packet_id": f"CP-{outcome}",
                "outcome": outcome,
            },
        )
        conn.commit()
    finally:
        conn.close()


def test_kpi_report_empty_contract_fixture_and_read_only(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    db_path = tmp_path / ".project-loop" / "project.db"
    events_path = tmp_path / ".project-loop" / "events.jsonl"
    before = (_state_counts(tmp_path), db_path.stat().st_size, events_path.read_bytes())

    assert main(["--root", str(tmp_path), "report", "kpi", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload == json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert (_state_counts(tmp_path), db_path.stat().st_size, events_path.read_bytes()) == before


def test_kpi_verification_metrics_equal_existing_stats_api(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _create_verification_feedback_fixture(tmp_path, capsys)
    expected = verification_feedback_stats(ProjectPaths(root=tmp_path.resolve()))["stats"]

    assert main(["--root", str(tmp_path), "report", "kpi", "--json"]) == 0
    metrics = _json_output(capsys)["sections"]["verification_spend_efficiency"]

    assert metrics["execution_rate"]["value"] == expected["execution_rate"]
    assert metrics["executed_pass_rate"]["value"] == expected["executed_pass_rate"]
    assert metrics["feedback_coverage_rate"]["value"] == expected["feedback_coverage_rate"]
    assert metrics["verification_spend_efficiency"]["value"] == round(
        expected["execution_rate"] * expected["executed_pass_rate"],
        4,
    )


def test_kpi_context_pack_average_replays_recorded_events_and_since_window(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Measured pack",
    ]) == 0
    capsys.readouterr()
    for _ in range(2):
        assert main([
            "--root",
            str(tmp_path),
            "context",
            "pack",
            "--task",
            "T-0001",
            "--record-usage",
            "--json",
        ]) == 0
        _json_output(capsys)

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        rows = conn.execute(
            "SELECT payload_json FROM events WHERE event_type = 'context_pack_generated' ORDER BY sequence"
        ).fetchall()
    finally:
        conn.close()
    event_payloads = [json.loads(row["payload_json"]) for row in rows]

    assert main(["--root", str(tmp_path), "report", "kpi", "--json"]) == 0
    section = _json_output(capsys)["sections"]["context_pack"]
    assert section["generation_count"]["value"] == 2
    assert section["average_context_pack_tokens"]["value"] == round(
        sum(payload["estimated_token_count"] for payload in event_payloads) / 2,
        2,
    )
    assert section["bound_receipt_coverage"]["value"] == 0.0
    assert section["measurement_scope"] == "recorded_opt_in_context_packs_only"

    assert main([
        "--root",
        str(tmp_path),
        "report",
        "kpi",
        "--since",
        "2999-01-01",
        "--json",
    ]) == 0
    empty = _json_output(capsys)["sections"]["context_pack"]
    assert empty["generation_count"]["value"] == 0
    assert empty["average_context_pack_tokens"] == {
        "value": None,
        "reason": "no_data_in_window",
        "data_source": "events:context_pack_generated",
        "window": {"since": "2999-01-01", "until": None},
    }


def test_kpi_finish_metrics_replay_recorded_events_and_explain_unrecorded_operations(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _record_completion_packet_event(tmp_path, outcome="COMPLETED_VERIFIED")
    _record_completion_packet_event(tmp_path, outcome="COMPLETED_WITH_RISK")
    _record_completion_packet_event(tmp_path, outcome="COMPLETED_VERIFIED")
    db_path = tmp_path / ".project-loop" / "project.db"
    events_path = tmp_path / ".project-loop" / "events.jsonl"
    before = (_state_counts(tmp_path), db_path.stat().st_size, events_path.read_bytes())

    assert main(["--root", str(tmp_path), "report", "kpi", "--json"]) == 0
    sections = _json_output(capsys)["sections"]

    assert sections["finish"] == {
        "finish_execution_count": {
            "value": 3,
            "data_source": "events:completion_packet_created",
            "window": {"since": None, "until": None},
        },
        "packet_outcome_distribution": {
            "value": {"COMPLETED_VERIFIED": 2, "COMPLETED_WITH_RISK": 1},
            "data_source": "events:completion_packet_created",
            "window": {"since": None, "until": None},
        },
        "finish_roundtrips_saved": {
            "value": None,
            "reason": "manual_comparison_not_recorded",
            "data_source": "manual:finish_roundtrip_comparison",
            "window": {"since": None, "until": None},
        },
    }
    assert sections["handoff"] == {
        name: {
            "value": None,
            "reason": "read_only_operation_not_recorded",
            "data_source": "read_only_operation:pcl_resume",
            "window": {"since": None, "until": None},
        }
        for name in ("resume_execution_count", "packet_generation_count")
    }
    assert (_state_counts(tmp_path), db_path.stat().st_size, events_path.read_bytes()) == before

    assert main([
        "--root",
        str(tmp_path),
        "report",
        "kpi",
        "--since",
        "2999-01-01",
        "--json",
    ]) == 0
    future = _json_output(capsys)["sections"]["finish"]
    assert future["finish_execution_count"]["value"] == 0
    assert future["packet_outcome_distribution"] == {
        "value": None,
        "reason": "no_data_in_window",
        "data_source": "events:completion_packet_created",
        "window": {"since": "2999-01-01", "until": None},
    }


def test_kpi_report_rejects_non_date_since(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "report",
        "kpi",
        "--since",
        "yesterday",
        "--json",
    ]) == 2
    error = _json_output(capsys)["error"]
    assert error["code"] == "invalid_input"
    assert error["details"] == {"since": "yesterday"}
