from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from pcl.db import connect
from pcl.task_accept import (
    accept_task,
    task_accept_envelope_golden_fixtures,
    validate_task_accept_envelope,
)
from pcl.paths import resolve_paths

from task_accept_helpers import prepare_acceptance, state_counts


AUTHORITY_FIXTURE_SHA256 = (
    "07e41045a685aac088ae6323352f8c5d5ecd2173a56fd1e2c23e49c878c64b0b"
)
COMMON_M2_FIELDS = {
    "attempt_generation",
    "plan_digest",
    "pre_accept_prefix_hwm",
    "pre_accept_prefix_sha256",
    "project_instance_id",
    "request_id",
    "request_locator",
}


def _service(root: Path, fixture: dict) -> dict:
    return accept_task(
        resolve_paths(root),
        task_id=fixture["task_id"],
        artifact_path=fixture["artifact"],
        command="pytest -q",
        summary="Acceptance verified",
        copy_files=True,
        test_ids=fixture["test_ids"],
    )


def _authority_fixture() -> dict:
    path = Path(__file__).parent / "fixtures" / "task_accept_m2_record_contents_v1.json"
    raw = path.read_bytes().removesuffix(b"\n")
    assert len(raw) == 27_074
    assert hashlib.sha256(raw).hexdigest() == AUTHORITY_FIXTURE_SHA256
    return json.loads(raw)


def _decode_frame(path: Path) -> tuple[str, dict]:
    raw = path.read_bytes()
    assert raw[:5] == b"PCLF1"
    domain_length = int.from_bytes(raw[5:7], "big")
    domain_end = 7 + domain_length
    payload_length = int.from_bytes(raw[domain_end : domain_end + 8], "big")
    payload_start = domain_end + 8
    assert payload_start + payload_length == len(raw)
    return raw[7:domain_end].decode(), json.loads(raw[payload_start:])


def _role_specific_keysets(records: list[dict]) -> dict[str, list[list[str]]]:
    by_role: dict[str, list[list[str]]] = {}
    for record in records:
        by_role.setdefault(record["role"], []).append(
            sorted(record["specific_content"])
        )
    return {role: sorted(values) for role, values in by_role.items()}


def _value_shape(value: object) -> object:
    if isinstance(value, dict):
        return {key: _value_shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_value_shape(item) for item in value]
    if value is None:
        return "null"
    return type(value).__name__


def _role_shapes(records: list[dict]) -> dict[str, list[str]]:
    by_role: dict[str, list[str]] = {}
    for record in records:
        shape = json.dumps(_value_shape(record["specific_content"]), sort_keys=True)
        by_role.setdefault(record["role"], []).append(shape)
    return {role: sorted(values) for role, values in by_role.items()}


def test_commit_entry_external_tamper_is_still_precommit_failure(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)
    before = state_counts(tmp_path)
    from pcl.db import MutationConnection

    original_commit = MutationConnection.commit

    def tamper_at_commit_entry(connection: MutationConnection) -> None:
        members = list(
            (tmp_path / ".project-loop" / "evidence" / "adhoc-files").glob(
                "e-*/sha256-*.artifact"
            )
        )
        assert len(members) == 1
        subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; import sys; "
                    "Path(sys.argv[1]).write_bytes(b'tampered at commit entry\\n')"
                ),
                str(members[0]),
            ],
            check=True,
        )
        original_commit(connection)

    monkeypatch.setattr(MutationConnection, "commit", tamper_at_commit_entry)

    result = _service(tmp_path, fixture)

    assert result["ok"] is False
    assert result["mutation_committed"] is False
    assert result["error_code"] == "task_accept_current_proof_invalid"
    assert state_counts(tmp_path) == before
    recovery_root = tmp_path / ".project-loop" / "task-accept-recovery" / "v1"
    names = {path.name for path in recovery_root.rglob("*.json")}
    assert not any(name.startswith("accepted-") for name in names)
    assert not any(name.startswith("ledger-sealed-") for name in names)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        assert conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (fixture["task_id"],)
        ).fetchone()["status"] == "in_progress"
        assert conn.execute(
            "SELECT status FROM features WHERE id = ?", (fixture["feature_id"],)
        ).fetchone()["status"] != "done"
        assert conn.execute(
            "SELECT COUNT(*) FROM evidence WHERE linked_task_id = ?",
            (fixture["task_id"],),
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_runtime_m2_records_match_frozen_seq27_role_contents(
    tmp_path: Path,
    capsys,
) -> None:
    authority = _authority_fixture()
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)

    result = _service(tmp_path, fixture)

    recovery_root = tmp_path / ".project-loop" / "task-accept-recovery" / "v1"
    actual_records = []
    for path in recovery_root.rglob("*.json"):
        _, payload = _decode_frame(path)
        role = path.name.rsplit("-", 1)[0]
        actual_records.append(
            {
                "filename": path.name,
                "frame_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "role": role,
                "specific_content": {
                    key: value for key, value in payload.items() if key not in COMMON_M2_FIELDS
                },
            }
        )

    assert len(actual_records) == 31
    assert Counter(record["role"] for record in actual_records) == Counter(
        record["role"] for record in authority["records"]
    )
    assert _role_specific_keysets(actual_records) == _role_specific_keysets(
        authority["records"]
    )
    assert _role_shapes(actual_records) == _role_shapes(authority["records"])
    assert result["receipts"]["record_fixture_sha256"] == AUTHORITY_FIXTURE_SHA256

    records_by_role = {
        record["role"]: record
        for record in actual_records
        if record["role"] != "test-binding"
    }
    by_role = {
        role: record["specific_content"] for role, record in records_by_role.items()
    }
    assert by_role["begin"]["reservation_manifest_frame_sha256"]
    assert by_role["plan-binding"]["plan_canonical_bytes"] > 0
    assert by_role["ledger-reserved"]["temp_directory_name"]
    assert by_role["projection"]["projection_receipt"]["contract_version"] == (
        "task-accept-projection-delivered-receipt/v1"
    )
    assert by_role["task-binding"]["snapshot"]["row_postimage"]["status"] == "done"
    assert by_role["feature-binding"]["snapshot"]["row_postimage"]["status"] == "done"
    assert by_role["begin"]["reservation_manifest_frame_sha256"] == (
        records_by_role["reservation-manifest"]["frame_sha256"]
    )
    assert by_role["accepted"]["commit_marker_frame_sha256"] == (
        records_by_role["sqlite-commit"]["frame_sha256"]
    )
    assert by_role["projection"]["accepted_marker_frame_sha256"] == (
        records_by_role["accepted"]["frame_sha256"]
    )
    assert by_role["render"]["upstream_projection_frame_sha256"] == (
        records_by_role["projection"]["frame_sha256"]
    )
    assert by_role["teardown"]["upstream_render_frame_sha256"] == (
        records_by_role["render"]["frame_sha256"]
    )
    assert by_role["ledger-reserved"]["generation_manifest_frame_sha256"] == (
        records_by_role["generation-manifest"]["frame_sha256"]
    )
    assert by_role["ledger-sealed"]["generation_manifest_frame_sha256"] == (
        records_by_role["generation-manifest"]["frame_sha256"]
    )
    assert by_role["ledger-sealed"]["predecessor_frame_sha256"] == (
        records_by_role["ledger-reserved"]["frame_sha256"]
    )
    test_bindings = [
        record["specific_content"]
        for record in actual_records
        if record["role"] == "test-binding"
    ]
    assert {binding["snapshot"]["row_postimage"]["status"] for binding in test_bindings} == {
        "passing"
    }


@pytest.mark.parametrize(
    ("fixture_index", "path", "invalid"),
    [
        (1, ("authority", "sequence"), []),
        (1, ("authority", "acceptance_receipt_sha256"), "not-a-digest"),
        (1, ("identity", "request_id"), "not-a-digest"),
        (1, ("pending_tail", "render_pending"), "not-a-boolean"),
        (1, ("receipts", "projection_status"), "invented"),
        (1, ("validation", "finding_count"), -99),
        (1, ("phase",), "phase0"),
        (1, ("authority", "prior_authoritative_commit"), True),
        (0, ("identity", "task_id"), "T-0001"),
    ],
)
def test_m5_rejects_frozen_authority_nested_and_cross_field_negatives(
    fixture_index: int,
    path: tuple[str, ...],
    invalid: object,
) -> None:
    payload = deepcopy(task_accept_envelope_golden_fixtures()[fixture_index])
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = invalid

    with pytest.raises(ValueError):
        validate_task_accept_envelope(payload)
