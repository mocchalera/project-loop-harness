from __future__ import annotations

import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "scale_baseline_v1" / "manifest.json"


def test_scale_baseline_fixture_is_deterministic_and_non_enforcing() -> None:
    manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert manifest["contract_version"] == "scale-baseline/v1"
    assert manifest["fixture_id"] == "scale-baseline-v1"
    assert manifest["policy"] == {
        "automatic_rotation": False,
        "automatic_compaction": False,
        "runtime_enforcement": False,
        "telemetry": False,
        "authoritative_store": "sqlite",
        "projection": "events.jsonl",
        "future_review_trigger": "S3",
    }

    workloads = manifest["workloads"]
    assert [item["id"] for item in workloads] == [
        "smoke-1k",
        "maintainer-10k",
        "growth-100k",
    ]
    assert [item["event_rows"] for item in workloads] == [1000, 10000, 100000]
    assert [item["expected_band"] for item in workloads] == ["S0", "S1", "S2"]
    assert sum(manifest["event_type_mix"].values()) == manifest["reference_snapshot"]["event_rows"]

    bands = manifest["advisory_bands"]
    assert [item["id"] for item in bands] == ["S0", "S1", "S2", "S3"]
    assert bands[-1]["min_event_rows"] == bands[-2]["max_event_rows"] + 1
    assert bands[-1]["min_jsonl_bytes"] == bands[-2]["max_jsonl_bytes"] + 1
    assert bands[-1]["min_project_loop_bytes"] == bands[-2]["max_project_loop_bytes"] + 1
