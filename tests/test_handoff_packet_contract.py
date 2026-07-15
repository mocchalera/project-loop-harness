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
    assert "trace_claim_refs" not in packet
    assert "trace_claim_ref_omissions" not in packet
    assert "trace_claim_ref_budget" not in packet


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
    assert "restart_context" not in schema["required"]
    assert "trace_claim_refs" not in schema["required"]
    assert schema["properties"]["trace_claim_refs"]["items"]["properties"]["trust"] == {
        "const": "unverified"
    }
    assert schema["properties"]["restart_context"]["properties"]["changed_paths"]["maxItems"] == 50


def test_handoff_packet_restart_context_is_additive_and_validated() -> None:
    packet = json.loads(FIXTURE.read_text(encoding="utf-8"))
    packet["restart_context"] = {
        "target_intent": "Repair executable resume context",
        "acceptance_status": "intent_only",
        "acceptance_ref": None,
        "target_review_command": "pcl task read T-0001 --json",
        "verification_commands": [{
            "command": "pytest tests/test_resume.py",
            "previous_status": "passed",
            "evidence_refs": ["evidence:E-0001"],
            "proof_source": "completion-packet/v1.checks/CHK-0001",
        }],
        "evidence_resolution_commands": ["pcl evidence show E-0001 --json"],
        "changed_paths": ["src/pcl/resume.py"],
        "documentation_candidates": [],
    }
    packet = finalize_handoff_packet(packet)

    assert validate_handoff_packet(packet).ok is True


def test_handoff_packet_trace_claim_refs_are_additive_and_strict() -> None:
    packet = json.loads(FIXTURE.read_text(encoding="utf-8"))
    claim_ref = {
        "intent_index_ref": "evidence:E-0002",
        "item_id": "I-001",
        "kind": "task_hint",
        "claim": "Inspect the copied source range.",
        "trust": "unverified",
        "source_refs": [{
            "evidence_id": "E-0001",
            "stored_path": ".project-loop/evidence/adhoc-files/e-0001/01-trace.md",
            "line_start": 4,
            "line_end": 5,
        }],
    }
    packet["trace_claim_refs"] = [claim_ref]
    packet["trace_claim_ref_omissions"] = []
    packet["trace_claim_ref_budget"] = {
        "max_items": 8,
        "max_bytes": 4096,
        "included_items": 1,
        "included_bytes": len(
            json.dumps(
                claim_ref,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ),
    }
    packet = finalize_handoff_packet(packet)
    assert validate_handoff_packet(packet).ok is True

    packet["trace_claim_refs"][0]["trust"] = "verified"
    packet = finalize_handoff_packet(packet)
    result = validate_handoff_packet(packet)
    assert result.ok is False
    assert any("trace_claim_refs[0].trust" in error for error in result.errors)
