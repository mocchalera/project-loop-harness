from __future__ import annotations

from copy import deepcopy

import pytest

from pcl.verification_results import (
    build_finish_check_result,
    build_verification_attempt_identity,
    evaluate_stability,
)


def _command(
    *,
    exit_code: int | None = 0,
    timed_out: bool = False,
    failure_kind: str = "",
    spawn_error_kind: str = "",
    artifact_status: str = "collected",
) -> dict:
    return {
        "resolved_command": "python -m pytest",
        "argv": ["python", "-m", "pytest"],
        "executed_argv": ["/usr/bin/python", "-m", "pytest"],
        "scope": "finish_checks",
        "config_key": "test",
        "status": "passed" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": 0.25,
        "failure_kind": failure_kind,
        "spawn_error_kind": spawn_error_kind,
        "termination": {
            "requested": timed_out,
            "method": "terminate_process_group" if timed_out else "",
            "escalated": False,
        },
        "artifact_collection": {
            "status": artifact_status,
            "stdout": artifact_status == "collected",
            "stderr": artifact_status == "collected",
        },
        "stdout_path": ".project-loop/evidence/stdout.txt",
        "stderr_path": ".project-loop/evidence/stderr.txt",
        "stdout": {"path": ".project-loop/evidence/stdout.txt"},
        "stderr": {"path": ".project-loop/evidence/stderr.txt"},
        "output_truncated": False,
        "redacted": False,
        "permission_contract": {
            "backend": "host_subprocess",
            "environment": {
                "inheritance": "allowlist",
                "inherited_names": ["PATH", "PYTHONPATH"],
                "sha256": "sha256:" + "1" * 64,
                "values_recorded": False,
            },
        },
    }


@pytest.mark.parametrize(
    (
        "command",
        "runner_status",
        "assertion_status",
        "failure_phase",
        "failure_kind",
    ),
    [
        (_command(), "completed", "passed", None, None),
        (_command(exit_code=1), "completed", "failed", "assert", "assertion"),
        (
            _command(
                exit_code=None,
                timed_out=True,
                failure_kind="timeout",
            ),
            "timed_out",
            "not_evaluated",
            "execute",
            "timeout",
        ),
        (
            _command(
                exit_code=None,
                failure_kind="spawn_error",
                spawn_error_kind="not_found",
            ),
            "spawn_failed",
            "not_evaluated",
            "spawn",
            "dependency",
        ),
        (
            _command(exit_code=-15),
            "signaled",
            "not_evaluated",
            "execute",
            "crash",
        ),
        (
            _command(artifact_status="failed"),
            "collection_failed",
            "unknown",
            "collect",
            "infrastructure",
        ),
    ],
)
def test_finish_check_result_separates_runner_and_assertion_outcomes(
    command: dict,
    runner_status: str,
    assertion_status: str,
    failure_phase: str | None,
    failure_kind: str | None,
) -> None:
    result = build_finish_check_result(
        command,
        evidence_id="E-0001",
        attempt_identity={"identity_sha256": "sha256:" + "2" * 64},
        stability_evaluation={"reproducible": False},
    )

    assert result["contract_version"] == "finish-check-result/v2"
    assert result["runner_result"]["contract_version"] == "runner-result/v1"
    assert result["runner_result"]["status"] == runner_status
    assert result["assertion_result"]["contract_version"] == "assertion-result/v1"
    assert result["assertion_result"]["status"] == assertion_status
    assert result["failure_phase"] == failure_phase
    assert result["failure_kind"] == failure_kind


def test_signaled_result_records_signal_without_calling_it_an_assertion_failure() -> None:
    result = build_finish_check_result(
        _command(exit_code=-9),
        evidence_id="E-0001",
        attempt_identity={"identity_sha256": "sha256:" + "2" * 64},
        stability_evaluation={"reproducible": False},
    )

    assert result["runner_result"]["signal"] == {"number": 9, "name": "SIGKILL"}
    assert result["assertion_result"]["status"] == "not_evaluated"
    assert result["status"] == "failed"


def _manifest() -> dict:
    return {
        "contract_version": "verification-input-manifest/v1",
        "manifest_sha256": "sha256:" + "3" * 64,
        "entries": [
            {
                "path": "uv.lock",
                "kind": "file",
                "sha256": "sha256:" + "4" * 64,
            },
            {
                "path": "src/pcl/__init__.py",
                "kind": "file",
                "sha256": "sha256:" + "5" * 64,
            },
        ],
    }


def test_attempt_identity_is_deterministic_and_covers_execution_policy() -> None:
    command = _command()
    policy = {
        "commands": [{"argv": command["argv"], "scope": command["scope"]}],
        "declared_output_patterns": [".pytest_cache/**"],
    }

    first = build_verification_attempt_identity(
        input_manifest=_manifest(),
        command=command,
        finish_policy=policy,
        timeout_seconds=120,
        max_output_bytes=1024,
        stability_stratum="cold",
    )
    same = build_verification_attempt_identity(
        input_manifest=deepcopy(_manifest()),
        command=deepcopy(command),
        finish_policy=deepcopy(policy),
        timeout_seconds=120,
        max_output_bytes=1024,
        stability_stratum="cold",
    )
    changed = build_verification_attempt_identity(
        input_manifest=_manifest(),
        command=command,
        finish_policy=policy,
        timeout_seconds=600,
        max_output_bytes=1024,
        stability_stratum="cold",
    )

    assert first == same
    assert first["contract_version"] == "verification-attempt-identity/v1"
    assert first["identity_sha256"].startswith("sha256:")
    assert first["input_manifest_sha256"] == _manifest()["manifest_sha256"]
    assert first["lock_inputs_sha256"].startswith("sha256:")
    assert first["finish_policy_sha256"].startswith("sha256:")
    assert first["execution"]["timeout_seconds"] == 120
    assert first["execution"]["cache"]["mode"] == "cold"
    assert first["platform"]["system"]
    assert first["platform"]["machine"]
    assert first["identity_sha256"] != changed["identity_sha256"]


def _attempt(
    identity: str,
    *,
    status: str,
    stratum: str,
) -> dict:
    return {
        "attempt_identity": {"identity_sha256": identity},
        "assertion_result": {"status": status},
        "stratum": stratum,
    }


def test_stability_requires_compatible_cold_and_warm_passes() -> None:
    identity = "sha256:" + "6" * 64

    one = evaluate_stability(
        [_attempt(identity, status="passed", stratum="cold")],
        minimum_consecutive_passes=2,
        maximum_attempts=3,
    )
    stable = evaluate_stability(
        [
            _attempt(identity, status="passed", stratum="cold"),
            _attempt(identity, status="passed", stratum="warm"),
        ],
        minimum_consecutive_passes=2,
        maximum_attempts=3,
    )

    assert one["contract_version"] == "stability-evaluation/v1"
    assert one["status"] == "stability_required"
    assert one["reproducible"] is False
    assert stable["status"] == "stable"
    assert stable["reproducible"] is True
    assert stable["consecutive_passes"] == 2
    assert stable["strata"]["cold"]["passed"] == 1
    assert stable["strata"]["warm"]["passed"] == 1


def test_stability_classifies_exhausted_mixed_outcomes_as_flaky() -> None:
    identity = "sha256:" + "7" * 64
    result = evaluate_stability(
        [
            _attempt(identity, status="passed", stratum="cold"),
            _attempt(identity, status="failed", stratum="warm"),
            _attempt(identity, status="passed", stratum="warm"),
        ],
        minimum_consecutive_passes=2,
        maximum_attempts=3,
    )

    assert result["status"] == "incomplete_flaky"
    assert result["mixed_outcomes"] is True
    assert result["reproducible"] is False
    assert result["remaining_attempts"] == 0


def test_stability_rejects_incompatible_attempt_identities() -> None:
    result = evaluate_stability(
        [
            _attempt("sha256:" + "8" * 64, status="passed", stratum="cold"),
            _attempt("sha256:" + "9" * 64, status="passed", stratum="warm"),
        ],
        minimum_consecutive_passes=2,
        maximum_attempts=3,
    )

    assert result["status"] == "incompatible_attempts"
    assert result["reproducible"] is False
    assert result["identity_sha256"] is None
    assert result["reasons"] == ["attempt_identity_mismatch"]
