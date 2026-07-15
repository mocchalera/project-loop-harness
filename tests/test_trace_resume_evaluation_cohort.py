from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pcl.contracts.handoff_packet import validate_handoff_packet


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "trace_binding_v0" / "trace-resume-evaluation-fixture.json"
)
COHORT_PATH = ROOT / "docs" / "evaluation" / "v0.5.1-trace-resume-cohort.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_trace_resume_cohort_is_frozen_before_independent_execution() -> None:
    fixture = _load(FIXTURE_PATH)
    cohort = _load(COHORT_PATH)

    assert cohort["contract_version"] == "trace-resume-evaluation-cohort/v1"
    assert cohort["status"] == "prepared_pending_independent_session_authorization"
    assert cohort["fixture"]["sha256"] == hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    assert cohort["thresholds"] == fixture["promotion_thresholds"]
    assert cohort["execution_authorization"] == {
        "independent_agent_sessions": False,
        "network_model_provider_runs": False,
        "paid_runs": False,
        "cross_runtime_or_model_cases_planned": 5,
        "note": (
            "Preparation and local CLI packet generation are authorized. Independent "
            "model-backed consumer sessions require a separate scope, data-class, budget, "
            "and expiry decision."
        ),
    }

    cases = cohort["cases"]
    fixture_cases = fixture["cases"]
    assert [case["id"] for case in cases] == [case["id"] for case in fixture_cases]
    assert {case["repository_slot"] for case in cases} == {"A", "B"}
    assert len({case["resume_session_id"] for case in cases}) == 2
    cross_runtime_or_model = sum(
        case["source_runtime"] != case["resume_runtime"]
        or case["source_model"] != case["resume_model"]
        for case in cases
    )
    assert cross_runtime_or_model == 5
    for concrete, frozen in zip(cases, fixture_cases, strict=True):
        for field in fixture["required_case_fields"]:
            assert concrete[field] == frozen[field]


def test_frozen_packets_are_hash_bound_valid_and_preserve_trust_boundary() -> None:
    cohort = _load(COHORT_PATH)
    for case in cohort["cases"]:
        packet_path = ROOT / case["packet_path"]
        packet_bytes = packet_path.read_bytes()
        packet = json.loads(packet_bytes)

        assert hashlib.sha256(packet_bytes).hexdigest() == case["packet_sha256"]
        result = validate_handoff_packet(packet)
        assert result.ok is True, (case["id"], result.errors)
        assert packet["target"]["id"] == case["task_id"]
        assert "full_transcript" in packet["omitted_sections"]
        assert packet["verified"] == []

        if case["expected_outcome"] == "resume":
            assert packet["trace_claim_refs"]
            assert packet["trace_claim_ref_budget"]["included_items"] == len(
                packet["trace_claim_refs"]
            )
            assert all(item["trust"] == "unverified" for item in packet["trace_claim_refs"])
            assert all(item["source_refs"] for item in packet["trace_claim_refs"])
        else:
            assert "trace_claim_refs" not in packet
            assert "trace_claim_ref_budget" not in packet
            assert "trace_claim_ref_omissions" not in packet
            assert "trace_claim_refs:invalid_binding" in packet["omitted_sections"]


def test_no_index_compatibility_packet_keeps_existing_shape() -> None:
    cohort = _load(COHORT_PATH)
    check = cohort["no_index_compatibility_checks"][0]
    packet_path = ROOT / check["packet_path"]
    packet_bytes = packet_path.read_bytes()
    packet = json.loads(packet_bytes)

    assert hashlib.sha256(packet_bytes).hexdigest() == check["packet_sha256"]
    result = validate_handoff_packet(packet)
    assert result.ok is True, result.errors
    assert packet["intent_index_ref"] is None
    assert "trace_claim_refs" not in packet
    assert "trace_claim_ref_omissions" not in packet
    assert "trace_claim_ref_budget" not in packet


def test_repository_trace_sizes_and_consumer_boundary_are_explicit() -> None:
    cohort = _load(COHORT_PATH)
    boundary = cohort["consumer_boundary"]
    assert boundary["allowed"] == [
        "frozen handoff packet",
        "packet-referenced copied Evidence artifacts",
        "repository state",
    ]
    assert boundary["forbidden"] == [
        "full transcript",
        "originating-session explanation",
        "unrecorded operator hint",
    ]
    assert boundary["claim_trust"] == "unverified_until_source_lines_are_checked"

    trace_paths = {
        "A": ROOT / "docs" / "evaluation" / "v0.5.1-trace-source-a.md",
        "B": ROOT / "docs" / "evaluation" / "v0.5.1-trace-source-b.md",
    }
    for slot, path in trace_paths.items():
        assert len(path.read_bytes()) == cohort["repository_slots"][slot][
            "full_trace_size_bytes"
        ]
