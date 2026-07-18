from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/layered_harness_ablation_v0/layered-harness-ablation-fixture.json"
COHORT_PATH = ROOT / "docs/evaluation/layered-harness-ablation-cohort.json"
RUNBOOK_PATH = ROOT / "docs/evaluation/layered-harness-ablation-runbook.md"

FIXTURE_SHA256 = "d90037b4943a9aacb9fe4503c2ff75291e0241a04dc7433c4a0440d2ffc743c1"
COHORT_SHA256 = "2726dc760e0dfcb46494d4c9072601868d9b6edc7d7fe13e15378ffdd7a51080"
RUNBOOK_SHA256 = "9da78bf6c2903ee07adaa855276babdac5f095e056ed2acc2413052f932dcc11"
EVALUATION_CONTRACT = "layered-harness-ablation-evaluation/v1"
ARM_PACKET_CONTRACT = "layered-harness-ablation-arm-packet/v1"
AUTHORIZATION_CONTRACT = "layered-harness-ablation-authorization/v1"

BOOL_METRICS = {
    "acceptance_success",
    "target_route_accuracy",
    "resume_handoff_accuracy",
    "current_proof_classification_accuracy",
    "human_gate_integrity",
}
COUNT_METRICS = {"unintended_mutation_count", "human_intervention_count"}
RUNTIME_COST_METRICS = (
    "tool_command_calls",
    "wall_clock_seconds",
    "input_tokens",
    "output_tokens",
)
SUPPORTING_METRICS = ("loaded_skill_bytes",)


class DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_input_errors() -> list[str]:
    errors: list[str] = []
    expected = {
        FIXTURE_PATH: FIXTURE_SHA256,
        COHORT_PATH: COHORT_SHA256,
        RUNBOOK_PATH: RUNBOOK_SHA256,
    }
    for path, expected_sha in expected.items():
        try:
            observed = _sha256(path)
        except OSError as exc:
            errors.append(f"{path.relative_to(ROOT)}: cannot read frozen input: {exc}")
            continue
        if observed != expected_sha:
            errors.append(
                f"{path.relative_to(ROOT)}: frozen sha256 mismatch: "
                f"expected {expected_sha}, observed {observed}"
            )
    return errors


def _load_frozen() -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = _load_json(FIXTURE_PATH)
    cohort = _load_json(COHORT_PATH)
    if not isinstance(fixture, dict) or not isinstance(cohort, dict):
        raise ValueError("frozen fixture and cohort must be JSON objects")
    return fixture, cohort


def prepare_arm_packets(
    output_dir: Path,
    authorization_path: Path,
) -> tuple[dict[str, Any], int]:
    errors = _frozen_input_errors()
    if errors:
        return _invalid_payload(errors, []), 2
    try:
        fixture, cohort = _load_frozen()
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError, ValueError) as exc:
        return _invalid_payload([f"cannot load frozen inputs: {exc}"], []), 2

    try:
        authorization = _load_json(authorization_path)
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
        return _invalid_payload([f"invalid authorization receipt: {exc}"], []), 2

    arms = fixture.get("prepared_arms")
    cases = fixture.get("cases")
    if not isinstance(arms, list) or not isinstance(cases, list):
        return _invalid_payload(["frozen fixture cases/prepared_arms must be arrays"], []), 2
    case_by_id = {case.get("id"): case for case in cases if isinstance(case, dict)}
    if len(arms) != 16 or len(case_by_id) != 8:
        return _invalid_payload(["frozen fixture must contain exactly 8 cases and 16 arms"], []), 2

    authorization_errors = _validate_authorization(authorization, cohort, arms)
    if authorization_errors:
        return _invalid_payload(authorization_errors, []), 2
    authorization_sha256 = _sha256(authorization_path)

    if output_dir.exists() and any(output_dir.iterdir()):
        return _invalid_payload(["arm packet output directory must be empty"], []), 2

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, str]] = []
    result_fields = fixture["required_result_fields"]
    for arm in sorted(arms, key=lambda item: item["arm_id"]):
        case = case_by_id.get(arm["case_id"])
        if not isinstance(case, dict):
            return _invalid_payload([f"unknown case for arm {arm['arm_id']}"], []), 2
        packet = {
            "contract_version": ARM_PACKET_CONTRACT,
            "cohort_id": cohort["cohort_id"],
            "cohort_sha256": COHORT_SHA256,
            "fixture_sha256": FIXTURE_SHA256,
            "runbook_sha256": RUNBOOK_SHA256,
            "authorization": {
                "authorized": True,
                "receipt_sha256": authorization_sha256,
                "expires_at": authorization["expires_at"],
                "data_class": authorization["data_class"],
                "budget": authorization["budget"],
                "cost_policy": authorization["cost_policy"],
            },
            "arm": arm,
            "case": case,
            "result_contract": {
                "required_fields": result_fields,
                "outcome_enum": fixture["enums"]["outcome"],
                "result_path": f"{arm['arm_id']}.json",
                "input_tokens_policy": "provider-reported nonnegative integer or null",
                "output_tokens_policy": "provider-reported nonnegative integer or null",
            },
            "frozen_preparation_boundary": cohort["execution_authorization"],
        }
        path = output_dir / f"{arm['arm_id']}.json"
        serialized = json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        path.write_text(serialized, encoding="utf-8")
        written.append({"arm_id": arm["arm_id"], "path": path.name, "sha256": _sha256(path)})

    manifest = {
        "contract_version": "layered-harness-ablation-arm-packet-manifest/v1",
        "cohort_id": cohort["cohort_id"],
        "cohort_sha256": COHORT_SHA256,
        "fixture_sha256": FIXTURE_SHA256,
        "runbook_sha256": RUNBOOK_SHA256,
        "authorization_receipt_sha256": authorization_sha256,
        "authorization_expires_at": authorization["expires_at"],
        "packet_count": len(written),
        "packets": written,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest, 0


def _validate_authorization(
    authorization: Any,
    cohort: dict[str, Any],
    arms: list[dict[str, Any]],
) -> list[str]:
    if not isinstance(authorization, dict):
        return ["authorization receipt must be a JSON object"]
    required = {
        "contract_version",
        "cohort_id",
        "cohort_sha256",
        "authorized_arm_ids",
        "independent_cockpit_sessions",
        "network_model_provider_runs",
        "authorized_agent_types",
        "data_class",
        "budget",
        "cost_policy",
        "authorized_by",
        "authorized_at",
        "expires_at",
    }
    fields = set(authorization)
    errors: list[str] = []
    if missing := sorted(required - fields):
        errors.append(f"authorization missing fields: {', '.join(missing)}")
    if unexpected := sorted(fields - required):
        errors.append(f"authorization unexpected fields: {', '.join(unexpected)}")
    if errors:
        return errors
    if authorization["contract_version"] != AUTHORIZATION_CONTRACT:
        errors.append(f"authorization contract_version must be {AUTHORIZATION_CONTRACT}")
    if authorization["cohort_id"] != cohort["cohort_id"]:
        errors.append("authorization cohort_id does not match frozen cohort")
    if authorization["cohort_sha256"] != COHORT_SHA256:
        errors.append("authorization cohort_sha256 does not match frozen cohort")
    expected_arms = sorted(arm["arm_id"] for arm in arms)
    arm_ids = authorization["authorized_arm_ids"]
    if not isinstance(arm_ids, list) or any(not isinstance(item, str) for item in arm_ids):
        errors.append("authorization authorized_arm_ids must be a list of strings")
    elif len(arm_ids) != len(set(arm_ids)) or sorted(arm_ids) != expected_arms:
        errors.append("authorization must name each of the 16 frozen arm IDs exactly once")
    if authorization["independent_cockpit_sessions"] is not True:
        errors.append("authorization must allow independent Cockpit sessions")
    if authorization["network_model_provider_runs"] is not True:
        errors.append("authorization must allow network model provider runs")
    expected_agent_types = sorted({arm["planned_agent_type"] for arm in arms})
    agent_types = authorization["authorized_agent_types"]
    if (
        not isinstance(agent_types, list)
        or any(not isinstance(item, str) for item in agent_types)
        or len(agent_types) != len(set(agent_types))
        or sorted(agent_types) != expected_agent_types
    ):
        errors.append(
            "authorization must name exactly the frozen agent types: "
            + ", ".join(expected_agent_types)
        )
    for field in ("data_class", "cost_policy", "authorized_by"):
        if not isinstance(authorization[field], str) or not authorization[field].strip():
            errors.append(f"authorization {field} must be a nonempty string")
    budget = authorization["budget"]
    if not isinstance(budget, dict) or set(budget) != {
        "currency",
        "max_amount",
        "paid_runs_allowed",
    }:
        errors.append(
            "authorization budget must contain exactly currency, max_amount, paid_runs_allowed"
        )
    else:
        if not isinstance(budget["currency"], str) or not budget["currency"].strip():
            errors.append("authorization budget currency must be a nonempty string")
        if (
            not isinstance(budget["max_amount"], (int, float))
            or isinstance(budget["max_amount"], bool)
            or budget["max_amount"] < 0
        ):
            errors.append("authorization budget max_amount must be a nonnegative number")
        if not isinstance(budget["paid_runs_allowed"], bool):
            errors.append("authorization budget paid_runs_allowed must be a boolean")
    authorized_at = _parse_utc_timestamp(authorization["authorized_at"])
    expires_at = _parse_utc_timestamp(authorization["expires_at"])
    if authorized_at is None:
        errors.append("authorization authorized_at must be an ISO-8601 UTC timestamp")
    elif authorized_at > datetime.now(timezone.utc):
        errors.append("authorization authorized_at must not be in the future")
    if expires_at is None:
        errors.append("authorization expires_at must be an ISO-8601 UTC timestamp")
    elif expires_at <= datetime.now(timezone.utc):
        errors.append("authorization receipt is expired")
    if authorized_at is not None and expires_at is not None and expires_at <= authorized_at:
        errors.append("authorization expires_at must be later than authorized_at")
    return errors


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def evaluate_results_directory(results_dir: Path) -> tuple[dict[str, Any], int]:
    frozen_errors = _frozen_input_errors()
    try:
        fixture, cohort = _load_frozen()
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError, ValueError) as exc:
        return _invalid_payload(frozen_errors + [f"cannot load frozen inputs: {exc}"], []), 2

    source_files = sorted(results_dir.glob("*.json")) if results_dir.is_dir() else []
    records: list[dict[str, Any]] = []
    errors = list(frozen_errors)
    for path in source_files:
        try:
            record = _load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
            errors.append(f"{path.name}: invalid JSON: {exc}")
            continue
        if not isinstance(record, dict):
            errors.append(f"{path.name}: result must be a JSON object")
            continue
        records.append(record)

    arms = {arm["arm_id"]: arm for arm in fixture["prepared_arms"]}
    cases = {case["id"]: case for case in fixture["cases"]}
    seen: dict[str, int] = {}
    valid_records: dict[str, dict[str, Any]] = {}
    for record in records:
        arm_id = record.get("arm_id")
        if isinstance(arm_id, str):
            seen[arm_id] = seen.get(arm_id, 0) + 1
        record_errors = _validate_record(record, fixture, arms, cases)
        label = arm_id if isinstance(arm_id, str) else "<missing arm_id>"
        errors.extend(f"{label}: {message}" for message in record_errors)
        if not record_errors and isinstance(arm_id, str):
            valid_records[arm_id] = record

    for arm_id, count in sorted(seen.items()):
        if count > 1:
            errors.append(f"duplicate arm_id: {arm_id} ({count} records)")
            valid_records.pop(arm_id, None)
    missing_arms = sorted(set(arms) - set(seen))
    unexpected_arms = sorted(set(seen) - set(arms))
    errors.extend(f"missing arm record: {arm_id}" for arm_id in missing_arms)
    errors.extend(f"unexpected arm record: {arm_id}" for arm_id in unexpected_arms)

    session_refs = [record.get("session_ref") for record in records]
    for session_ref in sorted({value for value in session_refs if isinstance(value, str)}):
        if session_refs.count(session_ref) > 1:
            errors.append(f"duplicate session_ref: {session_ref}")

    for case_id in sorted(cases):
        baseline = valid_records.get(f"{case_id}-baseline")
        treatment = valid_records.get(f"{case_id}-treatment")
        if baseline is not None and treatment is not None:
            if baseline["actual_model"] != treatment["actual_model"]:
                errors.append(
                    f"{case_id}: paired actual_model mismatch: "
                    f"{baseline['actual_model']!r} != {treatment['actual_model']!r}"
                )

    aggregate = _aggregate(fixture, cohort, arms, cases, valid_records)
    aggregate["errors"] = sorted(set(errors))
    aggregate["source_files"] = [path.name for path in source_files]
    aggregate["record_integrity"] = {
        "expected_arms": 16,
        "observed_records": len(records),
        "valid_records": len(valid_records),
        "missing_arms": missing_arms,
        "unexpected_arms": unexpected_arms,
        "denominator": 16,
    }
    if errors:
        aggregate["status"] = "invalid"
        aggregate["recommendation"] = {
            "option": "stop",
            "reason_codes": ["record_integrity_failure"],
            "phase5_authorized": False,
        }
        return aggregate, 2
    return aggregate, 0 if aggregate["recommendation"]["option"] == "proceed" else 1


def _validate_record(
    record: dict[str, Any],
    fixture: dict[str, Any],
    arms: dict[str, dict[str, Any]],
    cases: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    required = set(fixture["required_result_fields"])
    fields = set(record)
    missing = sorted(required - fields)
    unexpected = sorted(fields - required)
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if unexpected:
        errors.append(f"unexpected fields: {', '.join(unexpected)}")
    if missing:
        return errors

    arm_id = record["arm_id"]
    arm = arms.get(arm_id) if isinstance(arm_id, str) else None
    if arm is None:
        errors.append("arm_id is not frozen in prepared_arms")
        return errors
    case = cases[arm["case_id"]]
    frozen_equal = {
        "case_id": arm["case_id"],
        "condition": arm["condition"],
        "commit_full": arm["commit_full"],
        "loaded_skill_bytes": arm["loaded_skill_bytes"],
        "actual_agent_type": arm["planned_agent_type"],
        "actual_runtime": arm["planned_runtime"],
    }
    for field, expected in frozen_equal.items():
        if record[field] != expected:
            errors.append(f"{field} mutated: expected {expected!r}, observed {record[field]!r}")

    if not isinstance(record["actual_model"], str) or not record["actual_model"].strip():
        errors.append("actual_model must be a nonempty string")

    if not isinstance(record["session_ref"], str) or not record["session_ref"].strip():
        errors.append("session_ref must be a nonempty string")
    _enum(errors, record, "outcome", set(fixture["enums"]["outcome"]))
    for field in ("acceptance_success", "human_gate_integrity", "critical_gate_violation"):
        _bool(errors, record, field)
    for field in ("target_route_accuracy", "resume_handoff_accuracy", "current_proof_classification_accuracy"):
        applicable = field in case["quality_dimensions"]
        if applicable:
            _bool(errors, record, field)
        elif record[field] is not None:
            errors.append(f"{field} must be null when not applicable to {case['id']}")
    for field in ("unintended_mutation_count", "human_intervention_count", "tool_command_calls"):
        _nonnegative_int(errors, record, field)
    _nonnegative_number(errors, record, "wall_clock_seconds")
    for field in ("input_tokens", "output_tokens"):
        if record[field] is not None:
            _nonnegative_int(errors, record, field)
    if record["safe_stop_observed"] is not None and not isinstance(
        record["safe_stop_observed"], bool
    ):
        errors.append("safe_stop_observed must be a boolean or null")
    _bool(errors, record, "contaminated")
    if not isinstance(record["notes"], str):
        errors.append("notes must be a string")
    paths = record["evidence_paths"]
    if not isinstance(paths, list) or any(not isinstance(path, str) or not path for path in paths):
        errors.append("evidence_paths must be a list of nonempty strings")
    elif len(paths) != len(set(paths)):
        errors.append("evidence_paths must not contain duplicates")

    if record["contaminated"] is True or record["outcome"] == "contaminated":
        errors.append("contaminated result rejected fail-closed")
    if record["outcome"] == "missing":
        errors.append("missing outcome is not an executed arm record")
    if record["critical_gate_violation"] is True and record["human_gate_integrity"] is True:
        errors.append("critical_gate_violation true requires human_gate_integrity false")
    if record["outcome"] == "accepted" and record["acceptance_success"] is not True:
        errors.append("accepted outcome requires acceptance_success true")
    return errors


def _aggregate(
    fixture: dict[str, Any],
    cohort: dict[str, Any],
    arms: dict[str, dict[str, Any]],
    cases: dict[str, dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    pairs: dict[str, dict[str, dict[str, Any]]] = {}
    for arm_id, record in records.items():
        arm = arms[arm_id]
        pairs.setdefault(arm["case_id"], {})[arm["condition"]] = record

    quality: dict[str, Any] = {}
    quality_regressions: list[str] = []
    for metric in sorted(BOOL_METRICS | COUNT_METRICS):
        applicable_cases = [
            case_id for case_id, case in cases.items() if metric in case["quality_dimensions"]
        ]
        observed = [case_id for case_id in applicable_cases if set(pairs.get(case_id, {})) == {"baseline", "treatment"}]
        baseline_values = [pairs[case_id]["baseline"][metric] for case_id in observed]
        treatment_values = [pairs[case_id]["treatment"][metric] for case_id in observed]
        higher_is_better = metric in BOOL_METRICS
        regressed = [
            case_id
            for case_id in observed
            if (pairs[case_id]["treatment"][metric] < pairs[case_id]["baseline"][metric])
            if higher_is_better
        ]
        if not higher_is_better:
            regressed = [
                case_id
                for case_id in observed
                if pairs[case_id]["treatment"][metric] > pairs[case_id]["baseline"][metric]
            ]
        quality_regressions.extend(f"{case_id}:{metric}" for case_id in regressed)
        quality[metric] = {
            "applicable_pairs": len(applicable_cases),
            "observed_pairs": len(observed),
            "baseline_total": sum(baseline_values),
            "treatment_total": sum(treatment_values),
            "delta": sum(treatment_values) - sum(baseline_values),
            "regressed_pairs": regressed,
        }

    cost: dict[str, Any] = {}
    strict_runtime_improvements: list[str] = []
    runtime_worsenings: list[str] = []
    tolerances = fixture["recommendation_rule"]["cost_tolerances"]
    for metric in RUNTIME_COST_METRICS + SUPPORTING_METRICS:
        observed = [
            case_id
            for case_id in sorted(cases)
            if set(pairs.get(case_id, {})) == {"baseline", "treatment"}
            and pairs[case_id]["baseline"][metric] is not None
            and pairs[case_id]["treatment"][metric] is not None
        ]
        complete = len(observed) == len(cases)
        baseline_total = sum(pairs[case_id]["baseline"][metric] for case_id in observed)
        treatment_total = sum(pairs[case_id]["treatment"][metric] for case_id in observed)
        improved = complete and treatment_total < baseline_total
        worsened_pairs = [
            case_id
            for case_id in observed
            if _beyond_tolerance(
                pairs[case_id]["baseline"][metric],
                pairs[case_id]["treatment"][metric],
                tolerances[metric],
            )
        ]
        eligible = metric in RUNTIME_COST_METRICS
        if eligible and improved:
            strict_runtime_improvements.append(metric)
        if eligible and complete and worsened_pairs:
            runtime_worsenings.append(metric)
        cost[metric] = {
            "class": "runtime_cost" if eligible else "supporting_context",
            "observed_pairs": len(observed),
            "required_pairs": len(cases),
            "complete_paired_coverage": complete,
            "baseline_total": baseline_total if observed else None,
            "treatment_total": treatment_total if observed else None,
            "delta": treatment_total - baseline_total if observed else None,
            "strict_improvement": improved,
            "worsened_pairs_beyond_tolerance": worsened_pairs,
            "eligible_for_proceed": eligible,
            "claim_available": complete,
        }

    critical_violations = sum(
        record["critical_gate_violation"] is True for record in records.values()
    )
    safety = {
        "critical_gate_violations": critical_violations,
        "human_gate_integrity_regressions": quality["human_gate_integrity"]["regressed_pairs"],
        "unintended_mutation_regressions": quality["unintended_mutation_count"]["regressed_pairs"],
    }
    reasons: list[str] = []
    if quality_regressions:
        reasons.append("paired_quality_or_safety_regression")
    if critical_violations:
        reasons.append("critical_gate_violation")
    if not strict_runtime_improvements:
        reasons.append("no_strict_fully_observed_runtime_cost_improvement")
    if runtime_worsenings:
        reasons.append("runtime_cost_worsening_beyond_tolerance")
    option = "proceed" if not reasons and len(records) == 16 else "modify"
    if critical_violations:
        option = "stop"
    outcomes = {name: 0 for name in fixture["enums"]["outcome"]}
    for record in records.values():
        outcomes[record["outcome"]] += 1
    return {
        "contract_version": EVALUATION_CONTRACT,
        "cohort_id": cohort["cohort_id"],
        "frozen_inputs": {
            "cohort_sha256": COHORT_SHA256,
            "fixture_sha256": FIXTURE_SHA256,
            "runbook_sha256": RUNBOOK_SHA256,
        },
        "status": "evaluated",
        "denominator": 16,
        "outcomes": outcomes,
        "quality_metrics": quality,
        "safety_metrics": safety,
        "cost_metrics": cost,
        "token_claims": {
            "input_tokens": cost["input_tokens"]["claim_available"],
            "output_tokens": cost["output_tokens"]["claim_available"],
            "null_means_unavailable_not_zero": True,
        },
        "recommendation": {
            "option": option,
            "reason_codes": reasons,
            "strict_runtime_cost_improvements": strict_runtime_improvements,
            "runtime_cost_worsenings": runtime_worsenings,
            "loaded_skill_bytes_cannot_authorize_proceed_alone": True,
            "phase5_authorized": option == "proceed",
        },
    }


def _beyond_tolerance(baseline: float, treatment: float, tolerance: dict[str, Any]) -> bool:
    increase = treatment - baseline
    if increase <= 0:
        return False
    absolute = tolerance.get("max_absolute_increase")
    relative = tolerance.get("relative_increase_limit")
    absolute_exceeded = absolute is not None and increase > absolute
    relative_exceeded = relative is not None and (
        (baseline == 0 and treatment > 0) or (baseline > 0 and increase / baseline > relative)
    )
    if absolute is None:
        return relative_exceeded
    if relative is None:
        return absolute_exceeded
    return absolute_exceeded or relative_exceeded


def _invalid_payload(errors: list[str], source_files: list[str]) -> dict[str, Any]:
    return {
        "contract_version": EVALUATION_CONTRACT,
        "status": "invalid",
        "errors": sorted(errors),
        "source_files": source_files,
        "denominator": 16,
        "recommendation": {
            "option": "stop",
            "reason_codes": ["frozen_input_integrity_failure"],
            "phase5_authorized": False,
        },
    }


def _enum(errors: list[str], record: dict[str, Any], field: str, allowed: set[str]) -> None:
    if not isinstance(record[field], str) or record[field] not in allowed:
        errors.append(f"{field} must be one of: {', '.join(sorted(allowed))}")


def _bool(errors: list[str], record: dict[str, Any], field: str) -> None:
    if not isinstance(record[field], bool):
        errors.append(f"{field} must be a boolean")


def _nonnegative_int(errors: list[str], record: dict[str, Any], field: str) -> None:
    value = record[field]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(f"{field} must be a nonnegative integer")


def _nonnegative_number(errors: list[str], record: dict[str, Any], field: str) -> None:
    value = record[field]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        errors.append(f"{field} must be a nonnegative number")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare or evaluate frozen T-0116 ablation arms.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="Write 16 deterministic offline arm packets.")
    prepare.add_argument("--output-dir", required=True, type=Path)
    prepare.add_argument("--authorization", required=True, type=Path)
    evaluate = subparsers.add_parser("evaluate", help="Evaluate recorded arm result objects.")
    evaluate.add_argument("--results-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "prepare":
        payload, exit_code = prepare_arm_packets(args.output_dir, args.authorization)
    else:
        payload, exit_code = evaluate_results_directory(args.results_dir)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
