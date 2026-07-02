from __future__ import annotations

from copy import deepcopy

import pytest

from pcl.rubric import claims_rubric_v1, evidence_ids_in_rubric, validate_rubric


def _valid_rubric() -> dict:
    return {
        "contract_version": "rubric/v1",
        "acceptance_criteria": [
            {"criterion": "Records structured verification", "met": "yes", "evidence_id": "E-0001"}
        ],
        "regression_risk": {"level": "low", "notes": None},
        "test_evidence": [
            {"evidence_id": "E-0001", "command": "pytest", "summary": "All tests passed"}
        ],
        "security_ux_checks": [{"check": "No secrets in output", "result": "pass", "notes": None}],
        "confidence_score": 0.9,
        "evidence_completeness": "complete",
    }


def test_validate_rubric_accepts_valid_contract() -> None:
    rubric = _valid_rubric()

    assert claims_rubric_v1(rubric) is True
    assert validate_rubric(rubric) == []
    assert evidence_ids_in_rubric(rubric) == ["E-0001"]


@pytest.mark.parametrize(
    "missing_key",
    [
        "contract_version",
        "acceptance_criteria",
        "regression_risk",
        "test_evidence",
        "security_ux_checks",
        "confidence_score",
        "evidence_completeness",
    ],
)
def test_validate_rubric_rejects_missing_top_level_fields(missing_key: str) -> None:
    rubric = _valid_rubric()
    del rubric[missing_key]

    problems = validate_rubric(rubric)

    assert any(missing_key in problem and "required" in problem for problem in problems)


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda rubric: rubric.update({"contract_version": "other/v1"}), "contract_version must"),
        (lambda rubric: rubric.update({"acceptance_criteria": []}), "at least one item"),
        (lambda rubric: rubric.update({"acceptance_criteria": {}}), "acceptance_criteria must be a list"),
        (
            lambda rubric: rubric["acceptance_criteria"][0].update({"criterion": ""}),
            "criterion must be a non-empty string",
        ),
        (
            lambda rubric: rubric["acceptance_criteria"][0].update({"met": "maybe"}),
            "met must be one of",
        ),
        (
            lambda rubric: rubric["acceptance_criteria"][0].update({"evidence_id": ""}),
            "evidence_id must be a non-empty string or null",
        ),
        (lambda rubric: rubric.update({"regression_risk": []}), "regression_risk must be an object"),
        (
            lambda rubric: rubric["regression_risk"].update({"level": "critical"}),
            "regression_risk.level must be one of",
        ),
        (
            lambda rubric: rubric["regression_risk"].update({"notes": 123}),
            "regression_risk.notes must be a string or null",
        ),
        (lambda rubric: rubric.update({"test_evidence": {}}), "test_evidence must be a list"),
        (
            lambda rubric: rubric["test_evidence"][0].update({"command": 123}),
            "test_evidence[0].command must be a string or null",
        ),
        (
            lambda rubric: rubric["test_evidence"][0].update({"summary": 123}),
            "test_evidence[0].summary must be a string or null",
        ),
        (
            lambda rubric: rubric["test_evidence"][0].update({"evidence_id": ""}),
            "test_evidence[0].evidence_id must be a non-empty string or null",
        ),
        (
            lambda rubric: rubric.update({"security_ux_checks": {}}),
            "security_ux_checks must be a list",
        ),
        (
            lambda rubric: rubric["security_ux_checks"][0].update({"check": ""}),
            "security_ux_checks[0].check must be a non-empty string",
        ),
        (
            lambda rubric: rubric["security_ux_checks"][0].update({"result": "warn"}),
            "security_ux_checks[0].result must be one of",
        ),
        (
            lambda rubric: rubric["security_ux_checks"][0].update({"notes": 123}),
            "security_ux_checks[0].notes must be a string or null",
        ),
        (
            lambda rubric: rubric.update({"confidence_score": "high"}),
            "confidence_score must be a number",
        ),
        (
            lambda rubric: rubric.update({"evidence_completeness": "full"}),
            "evidence_completeness must be one of",
        ),
    ],
)
def test_validate_rubric_rejects_invalid_fields(mutator, expected: str) -> None:
    rubric = deepcopy(_valid_rubric())
    mutator(rubric)

    problems = validate_rubric(rubric)

    assert any(expected in problem for problem in problems)


def test_validate_rubric_rejects_unknown_top_level_keys() -> None:
    rubric = _valid_rubric()
    rubric["extra"] = True

    assert "unknown top-level key: extra." in validate_rubric(rubric)


@pytest.mark.parametrize("score", [0.0, 1.0])
def test_validate_rubric_accepts_confidence_boundaries(score: float) -> None:
    rubric = _valid_rubric()
    rubric["confidence_score"] = score

    assert validate_rubric(rubric) == []


@pytest.mark.parametrize("score", [-0.1, 1.1])
def test_validate_rubric_rejects_out_of_range_confidence(score: float) -> None:
    rubric = _valid_rubric()
    rubric["confidence_score"] = score

    assert "confidence_score must be between 0.0 and 1.0 inclusive." in validate_rubric(rubric)


def test_claims_rubric_v1_is_exact() -> None:
    assert claims_rubric_v1({"contract_version": "rubric/v1"}) is True
    assert claims_rubric_v1({"contract_version": "other/v1"}) is False
    assert claims_rubric_v1({}) is False
