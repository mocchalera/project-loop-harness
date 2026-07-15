from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pcl.contracts.handoff_packet import validate_handoff_packet


ROOT = Path(__file__).resolve().parents[1]
COHORT_PATH = ROOT / "docs" / "evaluation" / "v0.5.1-trace-resume-cohort-02.json"
AUTHORIZATION_PATH = (
    ROOT / "docs" / "evaluation" / "v0.5.1-trace-resume-authorization-02.json"
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_authorization_is_hash_bound_and_precedes_frozen_cohort() -> None:
    cohort = _load(COHORT_PATH)
    authorization = _load(AUTHORIZATION_PATH)
    execution = cohort["execution_authorization"]

    assert cohort["cohort_id"] == "TRC-20260715-02"
    assert cohort["status"] == "authorized_frozen"
    assert execution["authorization_ref"] == "evidence:E-0422"
    assert execution["authorization_sha256"] == hashlib.sha256(
        AUTHORIZATION_PATH.read_bytes()
    ).hexdigest()
    assert execution["authorization_precedence"] == (
        "referenced_authorization_evidence_is_authoritative"
    )
    assert execution["authorization_frozen_before_cohort"] is True
    assert execution["independent_agent_sessions"] is True
    assert execution["session_count"] == 2
    assert execution["cases_per_session"] == 5
    assert execution["maximum_attempts_per_session"] == 2
    assert datetime.fromisoformat(authorization["authorized_at"].replace("Z", "+00:00")) < (
        datetime.fromisoformat(cohort["frozen_at"].replace("Z", "+00:00"))
    )


def test_authorized_assignments_cover_all_cases_once() -> None:
    cohort = _load(COHORT_PATH)
    authorization = _load(AUTHORIZATION_PATH)
    cases = cohort["cases"]
    assignments = authorization["session_scope"]["assignments"]

    assert len(cases) == 10
    assert {case["repository_slot"] for case in cases} == {"A", "B"}
    assert {case["resume_session_id"] for case in cases} == {"resume-1", "resume-2"}
    assigned = assignments["codex"] + assignments["claude"]
    assert sorted(assigned) == sorted(case["id"] for case in cases)
    assert len(assigned) == len(set(assigned))
    assert len(assignments["codex"]) == len(assignments["claude"]) == 5
    assert all(case["source_runtime"] != case["resume_runtime"] for case in cases)
    assert cohort["thresholds"] == {
        "resume_success_rate": 0.8,
        "broken_binding_safe_stop_rate": 1.0,
        "critical_trust_boundary_violations": 0,
    }


def test_packets_are_hash_bound_and_smaller_than_representative_traces() -> None:
    cohort = _load(COHORT_PATH)
    slots = cohort["repository_slots"]

    for case in cohort["cases"]:
        packet_path = ROOT / case["packet_path"]
        packet_bytes = packet_path.read_bytes()
        packet = json.loads(packet_bytes)

        assert hashlib.sha256(packet_bytes).hexdigest() == case["packet_sha256"]
        assert validate_handoff_packet(packet).ok is True
        assert packet["target"]["id"] == case["task_id"]
        assert packet["size_bytes"] < slots[case["repository_slot"]][
            "full_trace_size_bytes"
        ]
        assert packet["verified"] == []
        assert "full_transcript" in packet["omitted_sections"]

        if case["expected_outcome"] == "resume":
            assert len(packet["trace_claim_refs"]) == 2
            assert all(ref["trust"] == "unverified" for ref in packet["trace_claim_refs"])
            assert all(ref["source_refs"] for ref in packet["trace_claim_refs"])
        else:
            assert "trace_claim_refs" not in packet
            assert "trace_claim_ref_budget" not in packet
            assert "trace_claim_refs:invalid_binding" in packet["omitted_sections"]


def test_consumer_boundary_matches_authorized_data_and_write_scope() -> None:
    cohort = _load(COHORT_PATH)
    authorization = _load(AUTHORIZATION_PATH)

    assert cohort["consumer_boundary"]["allowed"] == authorization[
        "allowed_data_classes"
    ]
    assert set(authorization["forbidden_data_classes"]).issubset(
        cohort["consumer_boundary"]["forbidden"]
    )
    assert authorization["write_scope"] == [
        "docs/evaluation/v0.5.1-trace-resume-results-02/resume-1-codex.json",
        "docs/evaluation/v0.5.1-trace-resume-results-02/resume-2-claude.json",
    ]


def test_no_index_compatibility_packet_keeps_existing_shape() -> None:
    cohort = _load(COHORT_PATH)
    check = cohort["no_index_compatibility_checks"][0]
    packet_path = ROOT / check["packet_path"]
    packet_bytes = packet_path.read_bytes()
    packet = json.loads(packet_bytes)

    assert hashlib.sha256(packet_bytes).hexdigest() == check["packet_sha256"]
    assert validate_handoff_packet(packet).ok is True
    assert packet["intent_index_ref"] is None
    assert "trace_claim_refs" not in packet
    assert "trace_claim_ref_omissions" not in packet
    assert "trace_claim_ref_budget" not in packet
