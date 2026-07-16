from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
from statistics import median
from typing import Any


OBSERVATION_CONTRACT = "adoption-observation/v1"
EVALUATION_CONTRACT = "adoption-proof-evaluation/v1"
REQUIRED_COHORT_SIZE = 5
REQUIRED_REPOSITORY_FAMILIES = 3
MAX_HEALTHY_SETUP_SECONDS = 300
REQUIRED_VERIFIED_COMPLETIONS = 4
MAX_COMPLETION_SECONDS = 1800
MAX_SAFETY_VIOLATIONS = 0
MAX_INTERVENTIONS_PER_PARTICIPANT = 1
REQUIRED_VOLUNTARY_REUSE = 2

REQUIRED_FIELDS = {
    "contract_version",
    "participant_id",
    "observed_on",
    "candidate_id",
    "candidate_sha256",
    "repository_family",
    "install_method",
    "first_time_user",
    "install_to_healthy_seconds",
    "verified_completion",
    "completion_seconds",
    "completion_outcome",
    "maintainer_interventions",
    "safety_violations",
    "voluntary_reuse_day_7",
    "stop_reason",
    "confusion_codes",
}
REPOSITORY_FAMILIES = {"python", "node", "mixed", "go", "rust", "other"}
INSTALL_METHODS = {"pipx", "uv-tool", "venv-pip", "other"}
COMPLETED_OUTCOMES = {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"}
INCOMPLETE_OUTCOMES = {
    "not_reached",
    "blocked_human",
    "setup_failed",
    "completion_failed",
    "participant_stopped",
}
STOP_REASONS = {
    "none",
    "timeout",
    "human_decision",
    "setup_failure",
    "completion_failure",
    "participant_stop",
}
CONFUSION_CODES = {
    "install",
    "dry_run",
    "config",
    "agent_prompt",
    "pcl_command",
    "evidence",
    "finish",
    "human_gate",
    "dashboard",
    "other",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate sanitized v0.5.2 Adoption Proof observation records."
    )
    parser.add_argument("--records-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    payload, exit_code = evaluate_records_directory(args.records_dir)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return exit_code


def evaluate_records_directory(records_dir: Path) -> tuple[dict[str, Any], int]:
    source_files = sorted(records_dir.glob("*.json")) if records_dir.is_dir() else []
    records: list[dict[str, Any]] = []
    errors: list[str] = []

    for path in source_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: invalid JSON: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{path.name}: record must be a JSON object")
            continue
        records.append(payload)
        errors.extend(f"{path.name}: {message}" for message in _validate_record(payload))

    errors.extend(_cohort_identity_errors(records))
    if errors:
        return (
            {
                "contract_version": EVALUATION_CONTRACT,
                "errors": sorted(errors),
                "ready_to_claim": False,
                "record_count": len(records),
                "source_files": [path.name for path in source_files],
                "status": "invalid",
            },
            2,
        )

    evaluation = _evaluate_valid_records(records, [path.name for path in source_files])
    if evaluation["ready_to_claim"]:
        return evaluation, 0
    if _is_incomplete(evaluation, records):
        return evaluation, 1
    return evaluation, 1


def _validate_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(record)
    missing = sorted(REQUIRED_FIELDS - fields)
    unexpected = sorted(fields - REQUIRED_FIELDS)
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if unexpected:
        errors.append(f"unexpected fields: {', '.join(unexpected)}")
    if missing:
        return errors

    if record["contract_version"] != OBSERVATION_CONTRACT:
        errors.append(f"contract_version must be {OBSERVATION_CONTRACT}")
    if not _matches(record["participant_id"], r"AP-[0-9]{3}"):
        errors.append("participant_id must match AP-000")
    if not _valid_date(record["observed_on"]):
        errors.append("observed_on must be an ISO date")
    if not _matches(record["candidate_id"], r"[A-Za-z0-9._-]{1,80}"):
        errors.append("candidate_id must use 1-80 safe identifier characters")
    if not _matches(record["candidate_sha256"], r"[0-9a-f]{64}"):
        errors.append("candidate_sha256 must be 64 lowercase hexadecimal characters")
    _require_enum(errors, record, "repository_family", REPOSITORY_FAMILIES)
    _require_enum(errors, record, "install_method", INSTALL_METHODS)
    _require_bool(errors, record, "first_time_user")
    _require_nullable_nonnegative_int(errors, record, "install_to_healthy_seconds")
    _require_bool(errors, record, "verified_completion")
    _require_nullable_nonnegative_int(errors, record, "completion_seconds")
    _require_enum(
        errors,
        record,
        "completion_outcome",
        COMPLETED_OUTCOMES | INCOMPLETE_OUTCOMES,
    )
    _require_nonnegative_int(errors, record, "maintainer_interventions")
    _require_nonnegative_int(errors, record, "safety_violations")
    reuse = record["voluntary_reuse_day_7"]
    if reuse is not None and not isinstance(reuse, bool):
        errors.append("voluntary_reuse_day_7 must be true, false, or null")
    _require_enum(errors, record, "stop_reason", STOP_REASONS)
    _require_confusion_codes(errors, record["confusion_codes"])

    completed = record["verified_completion"]
    completion_seconds = record["completion_seconds"]
    outcome = record["completion_outcome"]
    healthy_seconds = record["install_to_healthy_seconds"]
    if completed is True:
        if not isinstance(outcome, str) or outcome not in COMPLETED_OUTCOMES or completion_seconds is None:
            errors.append(
                "verified completion requires a completed outcome and completion_seconds"
            )
        if healthy_seconds is None:
            errors.append("verified completion requires install_to_healthy_seconds")
        if record["stop_reason"] != "none":
            errors.append("verified completion requires stop_reason none")
    elif completed is False:
        if not isinstance(outcome, str) or outcome not in INCOMPLETE_OUTCOMES or completion_seconds is not None:
            errors.append(
                "unverified completion requires an incomplete outcome and null completion_seconds"
            )
        if record["stop_reason"] == "none":
            errors.append("unverified completion requires a non-none stop_reason")
    if (
        isinstance(healthy_seconds, int)
        and not isinstance(healthy_seconds, bool)
        and isinstance(completion_seconds, int)
        and not isinstance(completion_seconds, bool)
        and completion_seconds < healthy_seconds
    ):
        errors.append("completion_seconds cannot precede healthy setup")
    return errors


def _cohort_identity_errors(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    participant_ids = [record.get("participant_id") for record in records]
    for participant_id in sorted({value for value in participant_ids if isinstance(value, str)}):
        if participant_ids.count(participant_id) > 1:
            errors.append(f"duplicate participant_id: {participant_id}")

    candidates = {
        (candidate_id, candidate_sha256)
        for record in records
        if isinstance((candidate_id := record.get("candidate_id")), str)
        and isinstance((candidate_sha256 := record.get("candidate_sha256")), str)
    }
    if len(candidates) > 1:
        errors.append("all records must use the same candidate_id and candidate_sha256")
    return errors


def _evaluate_valid_records(
    records: list[dict[str, Any]],
    source_files: list[str],
) -> dict[str, Any]:
    repository_families = sorted({record["repository_family"] for record in records})
    healthy_times = [record["install_to_healthy_seconds"] for record in records]
    healthy_median = (
        median(healthy_times)
        if healthy_times and all(isinstance(value, int) for value in healthy_times)
        else None
    )
    verified_within_30m = sum(
        1
        for record in records
        if record["verified_completion"]
        and record["completion_outcome"] in COMPLETED_OUTCOMES
        and record["completion_seconds"] <= MAX_COMPLETION_SECONDS
    )
    safety_violations = sum(record["safety_violations"] for record in records)
    max_interventions = max(
        (record["maintainer_interventions"] for record in records),
        default=0,
    )
    voluntary_reuse = sum(record["voluntary_reuse_day_7"] is True for record in records)
    first_time_users = sum(record["first_time_user"] is True for record in records)
    candidates = {
        (record["candidate_id"], record["candidate_sha256"]) for record in records
    }
    candidate = None
    if len(candidates) == 1:
        candidate_id, candidate_sha256 = next(iter(candidates))
        candidate = {"id": candidate_id, "sha256": candidate_sha256}

    gates = {
        "candidate_consistency": {
            "observed": len(candidates),
            "passed": len(candidates) == 1,
            "required": 1,
        },
        "cohort_size": {
            "observed": len(records),
            "passed": len(records) == REQUIRED_COHORT_SIZE,
            "required": REQUIRED_COHORT_SIZE,
        },
        "first_time_users": {
            "observed": first_time_users,
            "passed": first_time_users == REQUIRED_COHORT_SIZE,
            "required": REQUIRED_COHORT_SIZE,
        },
        "healthy_setup_median": {
            "observed_seconds": healthy_median,
            "passed": healthy_median is not None
            and len(healthy_times) == REQUIRED_COHORT_SIZE
            and healthy_median <= MAX_HEALTHY_SETUP_SECONDS,
            "required_max_seconds": MAX_HEALTHY_SETUP_SECONDS,
            "requires_all_participants_reached": True,
        },
        "maintainer_intervention": {
            "observed_max_per_participant": max_interventions,
            "passed": len(records) == REQUIRED_COHORT_SIZE
            and max_interventions <= MAX_INTERVENTIONS_PER_PARTICIPANT,
            "required_max_per_participant": MAX_INTERVENTIONS_PER_PARTICIPANT,
        },
        "repository_diversity": {
            "observed": len(repository_families),
            "passed": len(records) == REQUIRED_COHORT_SIZE
            and len(repository_families) >= REQUIRED_REPOSITORY_FAMILIES,
            "required_min": REQUIRED_REPOSITORY_FAMILIES,
        },
        "safety": {
            "observed_violations": safety_violations,
            "passed": len(records) == REQUIRED_COHORT_SIZE
            and safety_violations == MAX_SAFETY_VIOLATIONS,
            "required_max_violations": MAX_SAFETY_VIOLATIONS,
        },
        "verified_completion": {
            "observed_within_30m": verified_within_30m,
            "passed": len(records) == REQUIRED_COHORT_SIZE
            and verified_within_30m >= REQUIRED_VERIFIED_COMPLETIONS,
            "required_min_within_30m": REQUIRED_VERIFIED_COMPLETIONS,
        },
        "voluntary_reuse": {
            "observed": voluntary_reuse,
            "passed": len(records) == REQUIRED_COHORT_SIZE
            and voluntary_reuse >= REQUIRED_VOLUNTARY_REUSE,
            "required_min": REQUIRED_VOLUNTARY_REUSE,
        },
    }
    ready_to_claim = all(gate["passed"] for gate in gates.values())
    status = "passed" if ready_to_claim else "failed"
    payload = {
        "candidate": candidate,
        "cohort": {
            "first_time_user_count": first_time_users,
            "record_count": len(records),
            "repository_families": repository_families,
            "repository_family_count": len(repository_families),
        },
        "contract_version": EVALUATION_CONTRACT,
        "errors": [],
        "gates": gates,
        "metrics": {
            "max_maintainer_interventions_per_participant": max_interventions,
            "median_install_to_healthy_seconds": healthy_median,
            "safety_violation_count": safety_violations,
            "verified_completion_within_30m_count": verified_within_30m,
            "voluntary_reuse_count": voluntary_reuse,
        },
        "ready_to_claim": ready_to_claim,
        "source_files": source_files,
        "status": status,
    }
    if _is_incomplete(payload, records):
        payload["status"] = "incomplete"
    return payload


def _is_incomplete(evaluation: dict[str, Any], records: list[dict[str, Any]]) -> bool:
    if len(records) != REQUIRED_COHORT_SIZE:
        return True
    if any(record["install_to_healthy_seconds"] is None for record in records):
        return True
    if (
        evaluation["metrics"]["voluntary_reuse_count"] < REQUIRED_VOLUNTARY_REUSE
        and any(record["voluntary_reuse_day_7"] is None for record in records)
    ):
        return True
    return False


def _matches(value: Any, pattern: str) -> bool:
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _require_enum(
    errors: list[str],
    record: dict[str, Any],
    field: str,
    allowed: set[str],
) -> None:
    value = record[field]
    if not isinstance(value, str) or value not in allowed:
        errors.append(f"{field} must be one of: {', '.join(sorted(allowed))}")


def _require_bool(errors: list[str], record: dict[str, Any], field: str) -> None:
    if not isinstance(record[field], bool):
        errors.append(f"{field} must be a boolean")


def _require_nonnegative_int(
    errors: list[str],
    record: dict[str, Any],
    field: str,
) -> None:
    value = record[field]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(f"{field} must be a nonnegative integer")


def _require_nullable_nonnegative_int(
    errors: list[str],
    record: dict[str, Any],
    field: str,
) -> None:
    value = record[field]
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        errors.append(f"{field} must be a nonnegative integer or null")


def _require_confusion_codes(errors: list[str], value: Any) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append("confusion_codes must be a list of strings")
        return
    invalid = sorted(set(value) - CONFUSION_CODES)
    if invalid:
        errors.append(f"confusion_codes contains unsupported values: {', '.join(invalid)}")
    if len(value) != len(set(value)):
        errors.append("confusion_codes must not contain duplicates")


if __name__ == "__main__":
    raise SystemExit(main())
