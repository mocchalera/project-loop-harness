from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcl.contracts.completion_packet import (
    COMPLETION_PACKET_CONTRACT_VERSION,
    calculate_proof_level,
    canonical_json,
    completion_packet_schema,
    compute_packet_id,
    validate_completion_packet,
    with_computed_packet_id,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "completion_packet"
POSITIVE_FIXTURES = [FIXTURE_ROOT / "minimal.json", FIXTURE_ROOT / "full.json"]
NEGATIVE_CASES = json.loads((FIXTURE_ROOT / "negative-cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda path: path.stem)
def test_positive_fixtures_validate(fixture_path: Path) -> None:
    packet = json.loads(fixture_path.read_text(encoding="utf-8"))

    result = validate_completion_packet(packet)

    assert result.ok, result.errors
    assert packet["packet_id"] == compute_packet_id(packet)


@pytest.mark.parametrize(
    "case",
    NEGATIVE_CASES["fixtures"],
    ids=lambda case: case["path"],
)
def test_negative_fixtures_fail_for_expected_reason(case: dict) -> None:
    packet = json.loads((FIXTURE_ROOT / case["path"]).read_text(encoding="utf-8"))

    result = validate_completion_packet(packet)

    assert not result.ok
    assert any(case["expected_reason"] in error for error in result.errors), result.errors


def test_canonical_serializer_and_content_id_are_deterministic() -> None:
    packet = json.loads((FIXTURE_ROOT / "full.json").read_text(encoding="utf-8"))
    reordered = dict(reversed(list(packet.items())))

    assert canonical_json(reordered) == canonical_json(packet)
    assert compute_packet_id(reordered) == compute_packet_id(packet)
    assert canonical_json(packet).encode("utf-8").decode("utf-8") == canonical_json(packet)

    without_id = dict(packet)
    without_id.pop("packet_id")
    assert with_computed_packet_id(without_id) == packet


def test_packet_id_detects_content_changes() -> None:
    packet = json.loads((FIXTURE_ROOT / "minimal.json").read_text(encoding="utf-8"))
    packet["target"]["intent"] = "A different intent"

    result = validate_completion_packet(packet)

    assert "$.packet_id: does not match the canonical packet content hash" in result.errors


@pytest.mark.parametrize(
    ("evidence_classes", "expected"),
    [
        ([], "L0"),
        (["unknown"], "L0"),
        (["artifact_ref"], "L1"),
        (["model_review"], "L1"),
        (["model_review", "artifact_ref"], "L1"),
        (["executed_check"], "L2"),
        (["executed_check", "model_review"], "L2"),
        (["independent_reproduction"], "L3"),
        (["production_observation"], "L4"),
    ],
)
def test_proof_level_table(evidence_classes: list[str], expected: str) -> None:
    assert calculate_proof_level(evidence_classes) == expected
    assert calculate_proof_level(reversed(evidence_classes)) == expected


def test_packaged_schema_describes_the_runtime_contract() -> None:
    schema = completion_packet_schema()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["contract_version"]["const"] == COMPLETION_PACKET_CONTRACT_VERSION
    assert schema["additionalProperties"] is False
    assert "verifier_provenance" not in schema["required"]
