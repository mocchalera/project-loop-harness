from __future__ import annotations

import json

from pcl.code_context.summary import (
    CODE_CONTEXT_SUMMARY_VERSION,
    summarize_code_context_receipt,
)


def test_summary_model_compacts_context_receipt() -> None:
    summary = summarize_code_context_receipt(
        {
            "contract_version": "context-receipt/v0",
            "evidence_id": "E-0001",
            "receipt_path": ".project-loop/evidence/context-receipts/e-0001-impact-v0.json",
            "diff_source": "worktree-vs-HEAD",
            "index_run": {
                "id": "CI-0001",
                "index_version": "code-index/v0",
                "git_head": "abc123",
                "created_at": "2026-07-05T00:00:00Z",
                "unknown": "ignored",
            },
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
            "verification_suggestions": ["python3 -m pytest tests/test_context.py"],
            "extra": {"ignored": True},
        }
    )

    assert summary["contract_version"] == CODE_CONTEXT_SUMMARY_VERSION
    assert summary["receipt_ref"] == {
        "evidence_id": "E-0001",
        "receipt_path": ".project-loop/evidence/context-receipts/e-0001-impact-v0.json",
    }
    assert summary["diff_source"] == "worktree-vs-HEAD"
    assert summary["included_candidate_context_count"] == 1
    assert summary["included_candidate_context"] == [
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
    assert "sha256" not in summary["included_candidate_context"][0]
    assert summary["omitted_count"] == 1
    assert summary["excluded_changed_file_count"] == 1
    assert summary["sensitive_omitted_count"] == 2
    assert summary["staleness_warnings"] == ["Indexed file metadata changed: src/pcl/context.py."]
    assert summary["untracked_omission_warning"]
    assert summary["verification_suggestions"] == ["python3 -m pytest tests/test_context.py"]


def test_summary_model_tolerates_missing_and_unknown_receipt_fields() -> None:
    summary = summarize_code_context_receipt({"unexpected": "field"})

    assert summary == {
        "contract_version": CODE_CONTEXT_SUMMARY_VERSION,
        "status": "from_receipt",
        "receipt_ref": {"evidence_id": None, "receipt_path": None},
        "diff_source": "unknown",
        "index_run": None,
        "included_candidate_context_count": 0,
        "included_candidate_context": [],
        "omitted_count": 0,
        "omitted": [],
        "excluded_changed_file_count": 0,
        "excluded_changed_files": [],
        "sensitive_omitted_count": 0,
        "staleness_warnings": [],
        "untracked_omission_warning": None,
        "verification_suggestions": [],
    }


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
