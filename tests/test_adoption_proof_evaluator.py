from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_adoption_proof.py"
FROZEN_CANDIDATE_ID = "v0.6.0-pypi"
FROZEN_CANDIDATE_SHA256 = (
    "4857355d108f720feb93497dc17ae53bb9b7502f4549a0f26c1a97cfa655137d"
)


def _record(
    participant_id: str,
    repository_family: str,
    *,
    healthy_seconds: int | None = 180,
    completed: bool = True,
    completion_seconds: int | None = 900,
    outcome: str = "COMPLETED_VERIFIED",
    interventions: int = 0,
    safety_violations: int = 0,
    reuse: bool | None = False,
    candidate_id: str = FROZEN_CANDIDATE_ID,
    candidate_sha256: str = FROZEN_CANDIDATE_SHA256,
    stop_reason: str | None = None,
) -> dict[str, object]:
    return {
        "contract_version": "adoption-observation/v1",
        "participant_id": participant_id,
        "observed_on": "2026-07-20",
        "candidate_id": candidate_id,
        "candidate_sha256": candidate_sha256,
        "repository_family": repository_family,
        "install_method": "pipx",
        "first_time_user": True,
        "install_to_healthy_seconds": healthy_seconds,
        "verified_completion": completed,
        "completion_seconds": completion_seconds,
        "completion_outcome": outcome,
        "maintainer_interventions": interventions,
        "safety_violations": safety_violations,
        "voluntary_reuse_day_7": reuse,
        "stop_reason": stop_reason or ("none" if completed else "timeout"),
        "confusion_codes": [],
    }


def _write_records(directory: Path, records: list[dict[str, object]]) -> None:
    directory.mkdir()
    for index, record in enumerate(records, start=1):
        (directory / f"ap-{index:03d}.json").write_text(
            json.dumps(record, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _run(records_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--records-dir", str(records_dir)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_adoption_proof_evaluator_passes_only_the_frozen_complete_cohort(
    tmp_path: Path,
) -> None:
    records = [
        _record("AP-001", "python", healthy_seconds=120, reuse=True),
        _record("AP-002", "node", healthy_seconds=180, interventions=1, reuse=True),
        _record("AP-003", "mixed", healthy_seconds=240),
        _record("AP-004", "go", healthy_seconds=300, outcome="COMPLETED_WITH_RISK"),
        _record(
            "AP-005",
            "rust",
            healthy_seconds=280,
            completed=False,
            completion_seconds=None,
            outcome="not_reached",
        ),
    ]
    records_dir = tmp_path / "records"
    _write_records(records_dir, records)

    first = _run(records_dir)
    second = _run(records_dir)

    assert first.returncode == 0
    assert first.stderr == ""
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["contract_version"] == "adoption-proof-evaluation/v1"
    assert payload["status"] == "passed"
    assert payload["ready_to_claim"] is True
    assert payload["candidate"] == {
        "id": FROZEN_CANDIDATE_ID,
        "sha256": FROZEN_CANDIDATE_SHA256,
    }
    assert payload["cohort"]["record_count"] == 5
    assert payload["cohort"]["repository_family_count"] == 5
    assert payload["metrics"]["median_install_to_healthy_seconds"] == 240
    assert payload["metrics"]["verified_completion_within_30m_count"] == 4
    assert payload["metrics"]["voluntary_reuse_count"] == 2
    assert all(gate["passed"] for gate in payload["gates"].values())


@pytest.mark.parametrize(
    ("candidate_id", "candidate_sha256"),
    [
        ("other-candidate", "b" * 64),
        ("other-candidate", FROZEN_CANDIDATE_SHA256),
        (FROZEN_CANDIDATE_ID, "b" * 64),
    ],
)
def test_adoption_proof_evaluator_rejects_consistent_nonfrozen_candidate(
    tmp_path: Path,
    candidate_id: str,
    candidate_sha256: str,
) -> None:
    records = [
        _record(
            f"AP-{index:03d}",
            family,
            reuse=index <= 2,
            candidate_id=candidate_id,
            candidate_sha256=candidate_sha256,
        )
        for index, family in enumerate(
            ("python", "node", "mixed", "go", "rust"),
            start=1,
        )
    ]
    records_dir = tmp_path / "records"
    _write_records(records_dir, records)

    result = _run(records_dir)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "invalid"
    assert payload["ready_to_claim"] is False
    assert payload["errors"] == [
        "candidate_id and candidate_sha256 must match the frozen "
        f"{FROZEN_CANDIDATE_ID} candidate"
    ]


def test_adoption_proof_evaluator_rejects_participants_outside_five_slots(
    tmp_path: Path,
) -> None:
    records = [
        _record(f"AP-{index:03d}", family, reuse=index <= 7)
        for index, family in enumerate(
            ("python", "node", "mixed", "go", "rust"),
            start=6,
        )
    ]
    records_dir = tmp_path / "records"
    _write_records(records_dir, records)

    result = _run(records_dir)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "invalid"
    assert payload["ready_to_claim"] is False
    assert len(payload["errors"]) == 5
    assert all(
        "participant_id must be one of: AP-001, AP-002, AP-003, AP-004, AP-005"
        in error
        for error in payload["errors"]
    )


def test_adoption_proof_evaluator_keeps_unknown_day_7_results_incomplete(
    tmp_path: Path,
) -> None:
    records = [
        _record(
            f"AP-{index:03d}",
            family,
            reuse=True if index <= 2 else None,
        )
        for index, family in enumerate(
            ("python", "node", "mixed", "go", "rust"),
            start=1,
        )
    ]
    records_dir = tmp_path / "records"
    _write_records(records_dir, records)

    result = _run(records_dir)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "incomplete"
    assert payload["ready_to_claim"] is False
    assert payload["gates"]["voluntary_reuse"] == {
        "observed": 2,
        "observed_responses": 2,
        "passed": False,
        "required_min": 2,
        "required_responses": 5,
    }


def test_adoption_proof_evaluator_counts_terminal_setup_failure_as_observed_miss(
    tmp_path: Path,
) -> None:
    records = [
        _record(
            "AP-001",
            "python",
            healthy_seconds=None,
            completed=False,
            completion_seconds=None,
            outcome="setup_failed",
            stop_reason="setup_failure",
            reuse=False,
        ),
        _record("AP-002", "node", reuse=True),
        _record("AP-003", "mixed", reuse=True),
        _record("AP-004", "go"),
        _record("AP-005", "rust"),
    ]
    records_dir = tmp_path / "records"
    _write_records(records_dir, records)

    result = _run(records_dir)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["ready_to_claim"] is False
    assert payload["gates"]["healthy_setup_median"]["passed"] is False


def test_adoption_proof_evaluator_keeps_incomplete_cohort_nonclaimable(
    tmp_path: Path,
) -> None:
    records_dir = tmp_path / "records"
    _write_records(
        records_dir,
        [
            _record("AP-001", "python", reuse=True),
            _record("AP-002", "node", reuse=True),
            _record("AP-003", "mixed"),
            _record("AP-004", "go"),
        ],
    )

    result = _run(records_dir)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "incomplete"
    assert payload["ready_to_claim"] is False
    assert payload["gates"]["cohort_size"] == {
        "observed": 4,
        "passed": False,
        "required": 5,
    }


def test_adoption_proof_evaluator_reports_each_failed_threshold(
    tmp_path: Path,
) -> None:
    records = [
        _record("AP-001", "python", healthy_seconds=301, safety_violations=1),
        _record("AP-002", "node", healthy_seconds=320, interventions=2),
        _record(
            "AP-003",
            "mixed",
            healthy_seconds=330,
            completed=False,
            completion_seconds=None,
            outcome="not_reached",
        ),
        _record(
            "AP-004",
            "python",
            healthy_seconds=340,
            completed=False,
            completion_seconds=None,
            outcome="not_reached",
        ),
        _record(
            "AP-005",
            "node",
            healthy_seconds=350,
            completed=False,
            completion_seconds=None,
            outcome="not_reached",
        ),
    ]
    records_dir = tmp_path / "records"
    _write_records(records_dir, records)

    result = _run(records_dir)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["ready_to_claim"] is False
    assert payload["gates"]["repository_diversity"]["passed"] is True
    assert payload["gates"]["healthy_setup_median"]["passed"] is False
    assert payload["gates"]["verified_completion"]["passed"] is False
    assert payload["gates"]["safety"]["passed"] is False
    assert payload["gates"]["maintainer_intervention"]["passed"] is False
    assert payload["gates"]["voluntary_reuse"]["passed"] is False


def test_adoption_proof_evaluator_rejects_malformed_and_duplicate_records(
    tmp_path: Path,
) -> None:
    malformed = _record("AP-001", "python")
    malformed["repository_url"] = "https://example.invalid/private"
    duplicate = _record("AP-001", "node")
    records_dir = tmp_path / "records"
    _write_records(records_dir, [malformed, duplicate])

    result = _run(records_dir)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "invalid"
    assert payload["ready_to_claim"] is False
    assert any("unexpected fields: repository_url" in error for error in payload["errors"])
    assert any("duplicate participant_id: AP-001" in error for error in payload["errors"])


def test_adoption_proof_evaluator_rejects_inconsistent_completion_claim(
    tmp_path: Path,
) -> None:
    record = _record(
        "AP-001",
        "python",
        completed=True,
        completion_seconds=None,
        outcome="not_reached",
    )
    records_dir = tmp_path / "records"
    _write_records(records_dir, [record])

    result = _run(records_dir)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert any("verified completion requires" in error for error in payload["errors"])


def test_adoption_proof_evaluator_returns_json_for_wrong_field_types(
    tmp_path: Path,
) -> None:
    record = _record("AP-001", "python")
    record["candidate_id"] = ["not", "a", "string"]
    record["repository_family"] = ["python"]
    record["completion_outcome"] = ["COMPLETED_VERIFIED"]
    records_dir = tmp_path / "records"
    _write_records(records_dir, [record])

    result = _run(records_dir)

    assert result.returncode == 2
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["status"] == "invalid"
    assert payload["ready_to_claim"] is False
