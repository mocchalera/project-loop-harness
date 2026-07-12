from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable

from .contracts._profile_contract import load_strict_json
from .contracts.claim_set import validate_claim_set
from .contracts.council_run import validate_council_run
from .contracts.decision_proposal import validate_decision_proposal
from .contracts.profile_output_bundle import validate_profile_output_bundle
from .contracts.profile_run_request import validate_profile_run_request
from .contracts.route_override import canonical_route_override_json
from .contracts.route_recommendation import canonical_route_recommendation_json
from .contracts.verification_plan import validate_verification_plan
from .contracts.work_brief import (
    canonical_work_brief_json,
    validate_work_brief,
)
from .db import connect
from .errors import PclError
from .guards import require_initialized
from .paths import ProjectPaths
from .profile_prepare import _project_identity
from .profile_authorization import authorization_findings
from .profiles import show_profile


PROFILE_INGEST_PLAN_CONTRACT_VERSION = "profile-ingest-plan/v1"
REQUEST_FILE_MAX_BYTES = 2_000_000
BUNDLE_MANIFEST_MAX_BYTES = 262_144
MAX_ACCEPTED_OUTPUT_BYTES = 2_000_000

_ARTIFACT_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "council-run/v0": validate_council_run,
    "claim-set/v0": validate_claim_set,
    "verification-plan/v0": validate_verification_plan,
    "decision-proposal/v0": validate_decision_proposal,
    "work-brief/v1": validate_work_brief,
}
_REQUIRED_ROLES = {"run_manifest", "claims", "verification_plan"}
_DRIVE_PATH = re.compile(r"^[A-Za-z]:")


class ProfileBundleValidationError(PclError):
    pass


def plan_profile_ingest(
    paths: ProjectPaths,
    *,
    request_file: str,
    bundle_file: str,
    accept_failed: bool = False,
    summary: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    request_path = Path(request_file)
    bundle_path = Path(bundle_file)
    findings: list[dict[str, Any]] = []

    request = _load_limited_json(
        request_path,
        limit=REQUEST_FILE_MAX_BYTES,
        kind="request",
        findings=findings,
    )
    bundle = _load_limited_json(
        bundle_path,
        limit=BUNDLE_MANIFEST_MAX_BYTES,
        kind="bundle",
        findings=findings,
    )
    if findings:
        _raise_findings(findings, request_file, bundle_file)
    assert isinstance(request, dict)
    assert isinstance(bundle, dict)

    _contract_findings(
        validate_profile_run_request(request).errors,
        prefix="request",
        findings=findings,
    )
    _contract_findings(
        validate_profile_output_bundle(bundle).errors,
        prefix="bundle",
        findings=findings,
    )
    if findings:
        _raise_findings(findings, request_file, bundle_file)

    _validate_request_binding(paths, request, findings)
    _validate_bundle_binding(request, bundle, findings)
    artifact_values = _validate_artifact_files(
        request,
        bundle,
        bundle_path=bundle_path,
        findings=findings,
    )
    _validate_cross_references(request, bundle, artifact_values, findings)
    if findings:
        _raise_findings(findings, request_file, bundle_file)

    proposal_count = len(bundle["decision_proposal_artifact_ids"])
    persistable_without_extra_flag = bundle["status"] != "failed"
    failed_accepted = bundle["status"] == "failed" and accept_failed and bool(
        str(summary or "").strip()
    )
    persistable = persistable_without_extra_flag or failed_accepted
    decision_count = proposal_count if bundle["status"] == "needs_human" else 0
    mutation = {
        "evidence_rows": 1 if persistable else 0,
        "evidence_links": (1 + decision_count) if persistable else 0,
        "decision_rows": decision_count if persistable else 0,
        "events": (1 + decision_count) if persistable else 0,
        "outbox_records": (1 + decision_count) if persistable else 0,
        "filesystem_bundle_directories": 1 if persistable else 0,
    }
    return {
        "contract_version": PROFILE_INGEST_PLAN_CONTRACT_VERSION,
        "ok": True,
        "valid": True,
        "changed": False,
        "dry_run": True,
        "read_only": True,
        "runner_executed": False,
        "request": {
            "request_id": request["request_id"],
            "request_digest": request["request_digest"]["value"],
            "target": request["target"],
            "runner_profile_id": request["profile"]["runner_profile_id"],
        },
        "bundle": {
            "bundle_id": bundle["bundle_id"],
            "bundle_digest": bundle["bundle_digest"]["value"],
            "status": bundle["status"],
            "artifact_count": len(bundle["artifacts"]),
            "decision_proposal_count": proposal_count,
        },
        "persistable_without_extra_flag": persistable_without_extra_flag,
        "failed_acceptance_satisfied": failed_accepted,
        "requires_accept_failed": bundle["status"] == "failed" and not failed_accepted,
        "mutation": mutation,
        "next_action": {
            **bundle["next_action"],
            "safe_to_run": False,
        },
        "findings": [],
    }


def _load_limited_json(
    path: Path,
    *,
    limit: int,
    kind: str,
    findings: list[dict[str, Any]],
) -> Any:
    try:
        stat = path.lstat()
    except OSError as exc:
        _finding(
            findings,
            f"{kind}_unreadable",
            str(path),
            f"Could not stat {kind} file: {exc}",
            "Provide one readable regular JSON file.",
        )
        return None
    if path.is_symlink() or not path.is_file():
        _finding(
            findings,
            f"{kind}_not_regular_file",
            str(path),
            f"{kind.title()} must be a regular non-symlink file.",
            "Replace the path with a regular file.",
        )
        return None
    if stat.st_size > limit:
        _finding(
            findings,
            f"{kind}_size_limit",
            str(path),
            f"{kind.title()} size {stat.st_size} exceeds limit {limit}.",
            "Reduce the file before validation.",
        )
        return None
    try:
        value = load_strict_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _finding(
            findings,
            f"{kind}_json_invalid",
            str(path),
            f"{kind.title()} is not strict JSON: {exc}",
            "Fix JSON syntax, duplicate keys, or non-finite numbers.",
        )
        return None
    if not isinstance(value, dict):
        _finding(
            findings,
            f"{kind}_object_required",
            str(path),
            f"{kind.title()} must be a JSON object.",
            "Use the documented object contract.",
        )
        return None
    return value


def _validate_request_binding(
    paths: ProjectPaths,
    request: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    target = request.get("target")
    if not isinstance(target, dict) or target.get("type") != "task":
        _finding(
            findings,
            "request_target_unsupported",
            "$.target",
            "Profile ingest currently supports task targets only.",
            "Prepare a task-bound request.",
        )
        return
    conn = connect(paths.db_path)
    try:
        task = conn.execute(
            "SELECT id FROM tasks WHERE id = ?",
            (target.get("id"),),
        ).fetchone()
    finally:
        conn.close()
    if task is None:
        _finding(
            findings,
            "request_target_missing",
            "$.target",
            "Request target does not exist in the current project.",
            "Prepare a new request for an existing target.",
        )

    if request.get("project") != _project_identity(paths):
        _finding(
            findings,
            "request_project_fingerprint_mismatch",
            "$.project",
            "Request was prepared for another project identity or revision.",
            "Run pcl profile prepare again in this project.",
        )

    profile = request.get("profile")
    if isinstance(profile, dict):
        runner_profile_id = str(profile.get("runner_profile_id") or "")
        try:
            entry = show_profile(runner_profile_id)
        except PclError:
            _finding(
                findings,
                "request_profile_unknown",
                "$.profile.runner_profile_id",
                f"Unknown built-in runner Profile {runner_profile_id!r}.",
                "Use pcl profile list.",
            )
        else:
            if (
                profile.get("profile_version")
                != entry["manifest"]["profile_version"]
                or profile.get("manifest_sha256") != entry["manifest_sha256"]
            ):
                _finding(
                    findings,
                    "request_profile_manifest_mismatch",
                    "$.profile",
                    "Request runner Profile version/hash does not match the built-in manifest.",
                    "Prepare a new request with the current pcl binary.",
                )

    policy = request.get("data_policy")
    if isinstance(policy, dict) and (
        policy.get("network_access") == "requested"
        or policy.get("paid_service_requested") is True
    ) and not isinstance(request.get("authorization"), dict):
        _finding(
            findings,
            "profile_authorization_required",
            "$.authorization",
            "Network or paid output cannot be accepted without human authorization.",
            "Authorize the exact request basis before running a provider.",
        )
    for authorization_finding in authorization_findings(paths, request):
        _finding(
            findings,
            authorization_finding["code"],
            "$.authorization",
            authorization_finding["message"],
            "Re-authorize the current candidate request with valid human provenance.",
        )

    work_brief = request.get("work_brief")
    if isinstance(work_brief, dict):
        _validate_bound_evidence(
            paths,
            evidence_id=str(work_brief.get("evidence_id") or ""),
            expected_type="work_brief",
            expected_hash=str(work_brief.get("artifact_sha256") or ""),
            canonicalizer=lambda value: canonical_work_brief_json(value),
            finding_prefix="request_work_brief",
            findings=findings,
        )
    route = request.get("route")
    if isinstance(route, dict):
        _validate_bound_evidence(
            paths,
            evidence_id=str(route.get("recommendation_evidence_id") or ""),
            expected_type="route_recommendation",
            expected_hash=str(route.get("recommendation_sha256") or ""),
            canonicalizer=lambda value: canonical_route_recommendation_json(value),
            finding_prefix="request_route_recommendation",
            findings=findings,
        )
        override = route.get("override")
        if isinstance(override, dict):
            _validate_bound_evidence(
                paths,
                evidence_id=str(override.get("evidence_id") or ""),
                expected_type="route_override",
                expected_hash=str(override.get("artifact_sha256") or ""),
                canonicalizer=lambda value: canonical_route_override_json(value),
                finding_prefix="request_route_override",
                findings=findings,
            )


def _validate_bound_evidence(
    paths: ProjectPaths,
    *,
    evidence_id: str,
    expected_type: str,
    expected_hash: str,
    canonicalizer: Callable[[dict[str, Any]], str],
    finding_prefix: str,
    findings: list[dict[str, Any]],
) -> None:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            "SELECT type, path FROM evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or str(row["type"]) != expected_type:
        _finding(
            findings,
            f"{finding_prefix}_missing",
            evidence_id,
            f"Bound {expected_type} Evidence is missing.",
            "Prepare a new request from current Evidence.",
        )
        return
    path = paths.root / str(row["path"])
    try:
        value = load_strict_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _finding(
            findings,
            f"{finding_prefix}_unreadable",
            str(row["path"]),
            f"Bound Evidence cannot be read as strict JSON: {exc}",
            "Repair Evidence or prepare a new request.",
        )
        return
    if not isinstance(value, dict):
        _finding(
            findings,
            f"{finding_prefix}_invalid",
            str(row["path"]),
            "Bound Evidence is not a JSON object.",
            "Repair Evidence or prepare a new request.",
        )
        return
    actual = hashlib.sha256(canonicalizer(value).encode("utf-8")).hexdigest()
    if actual != expected_hash:
        _finding(
            findings,
            f"{finding_prefix}_hash_mismatch",
            str(row["path"]),
            "Bound Evidence hash differs from the request.",
            "Prepare a new request from current Evidence.",
        )


def _validate_bundle_binding(
    request: dict[str, Any],
    bundle: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    expected_request = {
        "request_id": request.get("request_id"),
        "request_digest": (
            request.get("request_digest", {}).get("value")
            if isinstance(request.get("request_digest"), dict)
            else None
        ),
    }
    if bundle.get("request_ref") != expected_request:
        _finding(
            findings,
            "bundle_request_mismatch",
            "$.request_ref",
            "Bundle does not bind the supplied request ID and digest.",
            "Use the exact request that produced this bundle.",
        )
    profile = request.get("profile")
    expected_profile = (
        {
            "runner_profile_id": profile.get("runner_profile_id"),
            "profile_version": profile.get("profile_version"),
            "manifest_sha256": profile.get("manifest_sha256"),
        }
        if isinstance(profile, dict)
        else None
    )
    if bundle.get("profile") != expected_profile:
        _finding(
            findings,
            "bundle_profile_mismatch",
            "$.profile",
            "Bundle runner Profile binding differs from the request.",
            "Regenerate the bundle with the requested manifest.",
        )


def _validate_artifact_files(
    request: dict[str, Any],
    bundle: dict[str, Any],
    *,
    bundle_path: Path,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    root = bundle_path.parent
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, list):
        return {}
    max_bytes = request.get("limits", {}).get("max_output_bytes")
    max_bytes = max_bytes if isinstance(max_bytes, int) else 0
    if max_bytes > MAX_ACCEPTED_OUTPUT_BYTES:
        _finding(
            findings,
            "request_output_size_limit_unsupported",
            "$.limits.max_output_bytes",
            (
                f"Requested output limit {max_bytes} exceeds runtime ceiling "
                f"{MAX_ACCEPTED_OUTPUT_BYTES}."
            ),
            "Prepare a request within the local runtime output ceiling.",
        )
        return {}
    declared_total = sum(
        int(item.get("size_bytes") or 0)
        for item in artifacts
        if isinstance(item, dict)
    )
    if declared_total > max_bytes:
        _finding(
            findings,
            "bundle_declared_size_limit",
            "$.artifacts",
            f"Declared artifact bytes {declared_total} exceed request limit {max_bytes}.",
            "Reduce output before validation.",
        )
        return {}

    values: dict[str, Any] = {}
    actual_total = 0
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            continue
        path_value = str(artifact.get("path") or "")
        artifact_path = f"$.artifacts[{index}].path"
        if not _safe_relative_path(path_value):
            _finding(
                findings,
                "bundle_artifact_path_invalid",
                artifact_path,
                f"Artifact path {path_value!r} is not a normalized relative POSIX path.",
                "Use a relative path without drive, UNC, empty, dot, or parent segments.",
            )
            continue
        local = root / path_value
        if _has_symlink_component(root, local):
            _finding(
                findings,
                "bundle_artifact_symlink",
                path_value,
                "Artifact path or one of its parents is a symlink.",
                "Replace symlinks with regular files inside the bundle root.",
            )
            continue
        try:
            stat = local.stat()
        except OSError as exc:
            _finding(
                findings,
                "bundle_artifact_missing",
                path_value,
                f"Listed artifact cannot be stat'ed: {exc}",
                "Provide every listed artifact.",
            )
            continue
        if not local.is_file():
            _finding(
                findings,
                "bundle_artifact_not_regular",
                path_value,
                "Listed artifact is not a regular file.",
                "Provide a regular file.",
            )
            continue
        declared_size = artifact.get("size_bytes")
        if stat.st_size != declared_size:
            _finding(
                findings,
                "bundle_artifact_size_mismatch",
                path_value,
                f"Actual size {stat.st_size} differs from declared {declared_size}.",
                "Rebuild the bundle manifest from exact artifact bytes.",
            )
            continue
        actual_total += stat.st_size
        if actual_total > max_bytes:
            _finding(
                findings,
                "bundle_actual_size_limit",
                path_value,
                f"Actual artifact bytes exceed request limit {max_bytes}.",
                "Reduce output before validation.",
            )
            break
        try:
            data = local.read_bytes()
        except OSError as exc:
            _finding(
                findings,
                "bundle_artifact_unreadable",
                path_value,
                f"Could not read listed artifact: {exc}",
                "Provide one readable regular file.",
            )
            continue
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != artifact.get("sha256"):
            _finding(
                findings,
                "bundle_artifact_hash_mismatch",
                path_value,
                "Actual artifact hash differs from the manifest.",
                "Rebuild the bundle manifest from exact artifact bytes.",
            )
            continue
        contract_version = str(artifact.get("contract_version") or "")
        validator = _ARTIFACT_VALIDATORS.get(contract_version)
        if validator is not None:
            try:
                value = json.loads(
                    data.decode("utf-8"),
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_non_finite,
                )
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                _finding(
                    findings,
                    "bundle_artifact_json_invalid",
                    path_value,
                    f"Artifact is not strict UTF-8 JSON: {exc}",
                    "Emit strict JSON matching the declared contract.",
                )
                continue
            result = validator(value)
            if not result.ok:
                for error in result.errors:
                    _finding(
                        findings,
                        "bundle_artifact_contract_invalid",
                        path_value,
                        error,
                        "Fix the declared artifact contract.",
                    )
                continue
            values[str(artifact["artifact_id"])] = value
        else:
            values[str(artifact["artifact_id"])] = data
    return values


def _validate_cross_references(
    request: dict[str, Any],
    bundle: dict[str, Any],
    values: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, list):
        return
    by_role: dict[str, list[tuple[str, Any]]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("artifact_id") or "")
        by_role.setdefault(str(artifact.get("role") or ""), []).append(
            (artifact_id, values.get(artifact_id))
        )
    for role in sorted(_REQUIRED_ROLES):
        if len(by_role.get(role, [])) != 1:
            _finding(
                findings,
                "bundle_required_role_count",
                "$.artifacts",
                f"Bundle requires exactly one {role} artifact.",
                "Emit one run manifest, claim set, and verification plan.",
            )
    if findings:
        return

    run = by_role["run_manifest"][0][1]
    claims = by_role["claims"][0][1]
    verification = by_role["verification_plan"][0][1]
    if not all(isinstance(item, dict) for item in (run, claims, verification)):
        return
    request_ref = {
        "request_id": request["request_id"],
        "request_digest": request["request_digest"]["value"],
    }
    if run.get("request_ref") != request_ref:
        _finding(
            findings,
            "run_request_mismatch",
            "council-run.request_ref",
            "Council run does not bind the supplied request.",
            "Regenerate the run manifest.",
        )
    if run.get("status") != bundle.get("status"):
        _finding(
            findings,
            "run_status_mismatch",
            "council-run.status",
            "Council run status differs from bundle status.",
            "Use one factual status across artifacts.",
        )
    run_id = run.get("run_id")
    if claims.get("run_ref") != run_id or verification.get("run_ref") != run_id:
        _finding(
            findings,
            "artifact_run_ref_mismatch",
            "$.artifacts",
            "Claim set or verification plan references another Council run.",
            "Use the bundle Council run ID in every artifact.",
        )

    participant_ids = {
        item.get("participant_id")
        for item in run.get("participants", [])
        if isinstance(item, dict)
    }
    claim_ids = {
        item.get("claim_id")
        for item in claims.get("claims", [])
        if isinstance(item, dict)
    }
    verification_ids = {
        item.get("verification_item_id")
        for item in verification.get("items", [])
        if isinstance(item, dict)
    }
    for claim in claims.get("claims", []):
        if not isinstance(claim, dict):
            continue
        unknown_participants = sorted(
            set(claim.get("source_participant_ids", [])) - participant_ids
        )
        unknown_verification = sorted(
            set(claim.get("verification_item_refs", [])) - verification_ids
        )
        if unknown_participants:
            _finding(
                findings,
                "claim_participant_ref_missing",
                str(claim.get("claim_id")),
                "Claim references unknown participants: "
                + ", ".join(unknown_participants),
                "Use participant IDs from the Council run.",
            )
        if unknown_verification:
            _finding(
                findings,
                "claim_verification_ref_missing",
                str(claim.get("claim_id")),
                "Claim references unknown verification items: "
                + ", ".join(unknown_verification),
                "Use verification IDs from the verification plan.",
            )
    for item in verification.get("items", []):
        if not isinstance(item, dict):
            continue
        unknown_claims = sorted(set(item.get("claim_refs", [])) - claim_ids)
        if unknown_claims:
            _finding(
                findings,
                "verification_claim_ref_missing",
                str(item.get("verification_item_id")),
                "Verification item references unknown claims: "
                + ", ".join(unknown_claims),
                "Use claim IDs from the claim set.",
            )

    proposals = by_role.get("decision_proposal", [])
    proposal_ids = {artifact_id for artifact_id, _ in proposals}
    listed = set(bundle.get("decision_proposal_artifact_ids", []))
    if listed != proposal_ids:
        _finding(
            findings,
            "decision_proposal_list_mismatch",
            "$.decision_proposal_artifact_ids",
            "Decision proposal list must name every and only proposal artifact.",
            "Synchronize proposal artifact IDs.",
        )
    valid_evidence_refs = claim_ids | verification_ids
    for artifact_id, proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        if proposal.get("run_ref") != run_id or proposal.get("target") != request.get(
            "target"
        ):
            _finding(
                findings,
                "decision_proposal_binding_mismatch",
                artifact_id,
                "Decision proposal run/target differs from the request.",
                "Bind proposals to this run and target.",
            )
        generated = proposal.get("generated_by")
        if isinstance(generated, dict):
            if generated.get("run_ref") != run_id:
                _finding(
                    findings,
                    "decision_proposal_generator_run_mismatch",
                    artifact_id,
                    "Proposal generator references another run.",
                    "Use the bundle Council run ID.",
                )
            unknown = sorted(
                set(generated.get("participant_ids", [])) - participant_ids
            )
            if unknown:
                _finding(
                    findings,
                    "decision_proposal_participant_ref_missing",
                    artifact_id,
                    "Proposal references unknown participants: " + ", ".join(unknown),
                    "Use participant IDs from the Council run.",
                )
        for candidate in proposal.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            unknown_refs = sorted(
                set(candidate.get("evidence_refs", [])) - valid_evidence_refs
            )
            if unknown_refs:
                _finding(
                    findings,
                    "decision_proposal_evidence_ref_missing",
                    f"{artifact_id}:{candidate.get('candidate_id')}",
                    "Candidate references unknown claims/checks: "
                    + ", ".join(unknown_refs),
                    "Use claim or verification IDs from this bundle.",
                )


def _safe_relative_path(value: str) -> bool:
    if not value or "\\" in value or value.startswith(("/", "\\")):
        return False
    if _DRIVE_PATH.match(value):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and not value.endswith("/")
        and "//" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _has_symlink_component(root: Path, path: Path) -> bool:
    if root.is_symlink():
        return True
    current = root
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _contract_findings(
    errors: tuple[str, ...],
    *,
    prefix: str,
    findings: list[dict[str, Any]],
) -> None:
    for error in errors:
        _finding(
            findings,
            f"{prefix}_contract_invalid",
            prefix,
            error,
            f"Fix the frozen {prefix} contract.",
        )


def _finding(
    findings: list[dict[str, Any]],
    code: str,
    path: str,
    message: str,
    repair: str,
) -> None:
    findings.append(
        {
            "code": code,
            "path": path,
            "message": message,
            "repair": repair,
        }
    )


def _raise_findings(
    findings: list[dict[str, Any]],
    request_file: str,
    bundle_file: str,
) -> None:
    ordered = sorted(
        findings,
        key=lambda item: (item["path"], item["code"], item["message"]),
    )
    raise ProfileBundleValidationError(
        message=f"Profile bundle validation failed with {len(ordered)} finding(s).",
        code="profile_bundle_invalid",
        details={
            "request_file": request_file,
            "bundle_file": bundle_file,
            "finding_count": len(ordered),
            "findings": ordered,
        },
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key {key!r} is not allowed")
        value[key] = item
    return value


def _reject_non_finite(value: str) -> Any:
    raise ValueError(f"non-finite JSON number {value} is not allowed")
