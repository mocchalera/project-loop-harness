from __future__ import annotations

import json

from pcl.code_context.summary import (
    CODE_CONTEXT_SUMMARY_VERSION,
    summarize_code_context_receipt,
)

FORBIDDEN_RECEIPT_SUMMARY_KEYS = {"status", "state", "lifecycle"}


def _forbidden_keys(payload) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_RECEIPT_SUMMARY_KEYS:
                found.add(key)
            found.update(_forbidden_keys(value))
    elif isinstance(payload, list):
        for item in payload:
            found.update(_forbidden_keys(item))
    return found


def test_summary_model_compacts_context_receipt() -> None:
    summary = summarize_code_context_receipt(
        {
            "contract_version": "context-receipt/v0",
            "created_at": "2026-07-05T00:01:00Z",
            "evidence_id": "E-0001",
            "receipt_path": ".project-loop/evidence/context-receipts/e-0001-impact-v0.json",
            "diff_source": "worktree-vs-HEAD",
            "index_run": {
                "id": "CI-0001",
                "index_version": "code-index/v0",
                "git_head": "abc123",
                "created_at": "2026-07-05T00:00:00Z",
                "sensitive_include_override_used": True,
                "unknown": "ignored",
            },
            "changed_files": [
                {"path": "src/pcl/context.py", "status": "M"},
                {"path": ".agents/session.json", "status": "M"},
            ],
            "included_candidate_context": [
                {
                    "path": "src/pcl/context.py",
                    "role": "changed_file",
                    "reason": "changed file is present in the latest index",
                    "confidence": 1.0,
                    "language": "python",
                    "sha256": "not-carried-into-summary",
                    "snapshot_consistency": "modified_since_index",
                    "snapshot_consistency_reason": "current hash differs from indexed hash",
                }
            ],
            "excluded_changed_files": [
                {
                    "path": ".agents/session.json",
                    "status": "M",
                    "reason": "code_index.exclude:.agents/",
                }
            ],
            "omitted": [{"path": "docs/old.md", "reason": "not present in latest index"}],
            "sensitive_omitted_count": "2",
            "staleness_warnings": ["Indexed file metadata changed: src/pcl/context.py."],
            "verification_suggestions": [
                {
                    "id": "E-0001/VS-01",
                    "command": "python3 -m pytest tests/test_context.py",
                    "reason": "test_hint:filename_match",
                }
            ],
            "extra": {"ignored": True},
        }
    )

    assert summary["contract_version"] == CODE_CONTEXT_SUMMARY_VERSION
    assert summary["receipt_ref"] == {
        "evidence_id": "E-0001",
        "receipt_path": ".project-loop/evidence/context-receipts/e-0001-impact-v0.json",
        "created_at": "2026-07-05T00:01:00Z",
    }
    assert summary["diff_source"] == "worktree-vs-HEAD"
    assert summary["index_run"] == {
        "id": "CI-0001",
        "created_at": "2026-07-05T00:00:00Z",
    }
    assert summary["changed_file_count"] == 2
    assert summary["included_total"] == 1
    assert summary["included_candidate_context_top"] == [
        {
            "path": "src/pcl/context.py",
            "role": "changed_file",
            "selection": "included as candidate context",
            "reason": "changed file is present in the latest index",
            "language": "python",
            "snapshot_consistency": "modified_since_index",
            "snapshot_consistency_reason": "current hash differs from indexed hash",
            "confidence": 1.0,
        }
    ]
    assert "sha256" not in summary["included_candidate_context_top"][0]
    assert "included_candidate_context" not in summary
    assert summary["omitted_reason_counts"] == {"not present in latest index": 1}
    assert "omitted" not in summary
    assert summary["excluded_changed_file_count"] == 1
    assert summary["sensitive_omitted_count"] == 2
    assert summary["staleness_warnings"] == ["Indexed file metadata changed: src/pcl/context.py."]
    assert summary["untracked_omission_warning"]
    assert summary["verification_suggestions"] == [
        {
            "id": "E-0001/VS-01",
            "command": "python3 -m pytest tests/test_context.py",
            "reason": "test_hint:filename_match",
        }
    ]
    assert summary["sensitive_include_override_used"] is True
    assert summary["refresh_replay"] == {
        "fidelity": "scope_preserving",
        "commands": [
            "pcl index build --json",
            "pcl impact --diff --json",
        ],
        "reason": [
            "staleness_warnings were present; refresh should rebuild the code index first.",
            "diff_source was worktree-vs-HEAD.",
        ],
    }


def test_summary_model_bounds_candidate_context_top_n() -> None:
    summary = summarize_code_context_receipt(
        {
            "included_candidate_context": [
                {"path": f"src/file_{index}.py", "role": "likely_impacted"}
                for index in range(12)
            ]
        },
        included_candidate_limit=3,
    )

    assert summary["included_total"] == 12
    assert [item["path"] for item in summary["included_candidate_context_top"]] == [
        "src/file_0.py",
        "src/file_1.py",
        "src/file_2.py",
    ]


def test_summary_model_tolerates_missing_and_unknown_receipt_fields() -> None:
    summary = summarize_code_context_receipt({"unexpected": "field"})

    assert summary == {
        "contract_version": CODE_CONTEXT_SUMMARY_VERSION,
        "receipt_ref": {"evidence_id": None, "receipt_path": None, "created_at": None},
        "diff_source": "unknown",
        "index_run": None,
        "changed_file_count": 0,
        "excluded_changed_file_count": 0,
        "sensitive_omitted_count": 0,
        "staleness_warnings": [],
        "untracked_omission_warning": None,
        "included_total": 0,
        "included_candidate_context_top": [],
        "omitted_reason_counts": {},
        "verification_suggestions": [],
        "sensitive_include_override_used": False,
        "refresh_replay": {
            "fidelity": "generic",
            "commands": ["pcl impact --diff --json"],
            "reason": [
                "diff_source was unknown; no scope-preserving replay mapping is available."
            ],
        },
    }


def test_summary_model_accepts_legacy_string_suggestions() -> None:
    summary = summarize_code_context_receipt(
        {
            "contract_version": "context-receipt/v0",
            "verification_suggestions": ["python3 -m pytest tests/test_context.py"],
        }
    )

    assert summary["verification_suggestions"] == [
        {"id": None, "command": "python3 -m pytest tests/test_context.py"}
    ]


def test_receipt_summary_payloads_do_not_carry_lifecycle_keys() -> None:
    receipt = {
        "contract_version": "context-receipt/v0",
        "evidence_id": "E-0001",
        "verification_suggestions": [
            {
                "id": "E-0001/VS-01",
                "command": "python3 -m pytest tests/test_context.py",
                "reason": "test_hint:filename_match",
            }
        ],
    }
    summary = summarize_code_context_receipt(receipt)

    assert _forbidden_keys(receipt) == set()
    assert _forbidden_keys(summary) == set()


def test_summary_wording_stays_epistemically_narrow() -> None:
    summary = summarize_code_context_receipt(
        {
            "included_candidate_context": [
                {"path": "src/app.py", "role": "changed_file", "reason": "changed path"}
            ]
        }
    )

    serialized = json.dumps(summary, sort_keys=True).lower()
    assert "included as candidate context" in serialized
    assert "understood" not in serialized
    assert "analyzed" not in serialized
    assert "agent read" not in serialized
    assert "safe_to_continue" not in serialized
    assert "go/no-go" not in serialized
