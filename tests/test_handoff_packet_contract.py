from __future__ import annotations

import json
from pathlib import Path

from pcl.contracts.handoff_packet import (
    finalize_handoff_packet,
    handoff_packet_schema,
    validate_handoff_packet,
)


FIXTURE = Path(__file__).parent / "fixtures" / "handoff_packet" / "minimal.json"


def test_minimal_handoff_packet_fixture_is_valid() -> None:
    packet = json.loads(FIXTURE.read_text(encoding="utf-8"))

    result = validate_handoff_packet(packet)

    assert result.ok is True, result.errors
    assert packet["omitted_sections"] == ["evidence_bodies", "full_transcript"]
    assert packet["size_bytes"] > 0
    assert packet["estimated_token_count"] > 0


def test_handoff_packet_rejects_verified_claim_without_evidence() -> None:
    packet = json.loads(FIXTURE.read_text(encoding="utf-8"))
    packet["verified"][0]["evidence_refs"] = []
    packet = finalize_handoff_packet(packet)

    result = validate_handoff_packet(packet)

    assert result.ok is False
    assert any("verified claims require Evidence refs" in error for error in result.errors)


def test_handoff_packet_rejects_tampered_metrics_and_content_id() -> None:
    packet = json.loads(FIXTURE.read_text(encoding="utf-8"))
    packet["summary"] = "tampered"

    result = validate_handoff_packet(packet)

    assert result.ok is False
    assert any("packet content hash" in error for error in result.errors)
    assert any("canonical JSON" in error for error in result.errors)


def test_packaged_handoff_schema_exposes_authoritative_contract() -> None:
    schema = handoff_packet_schema()

    assert schema["properties"]["contract_version"]["const"] == "handoff-packet/v1"
    assert "omitted_sections" in schema["required"]
    assert schema["properties"]["token_estimator"]["const"] == "charclass/v1"
