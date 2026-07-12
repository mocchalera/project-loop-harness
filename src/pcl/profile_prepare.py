from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from . import __version__
from .adaptive_policy import resolve_policy
from .context import pack_context_for_task
from .contracts._profile_contract import canonical_json
from .contracts.profile_run_request import (
    request_basis_digest,
    request_digest,
    validate_profile_run_request,
)
from .contracts.route_override import canonical_route_override_json
from .contracts.route_recommendation import (
    canonical_route_recommendation_json,
    load_route_recommendation,
    validate_route_recommendation,
)
from .contracts.work_brief import load_work_brief
from .db import connect, get_metadata
from .errors import InvalidInputError, PclError
from .guards import require_initialized
from .paths import ProjectPaths
from .profiles import show_profile, validate_profile
from .routing import (
    ROUTE_RECOMMENDATION_LINK_ROLE,
    recommend_route,
)
from .route_overrides import current_route
from .tasks import read_task
from .timeutil import utc_now_iso
from .validators import _simple_yaml_section
from .work_briefs import parse_target_ref, show_work_brief


PROFILE_PREPARE_CONTRACT_VERSION = "profile-prepare-result/v1"


class ProfilePrepareError(PclError):
    pass


def prepare_profile_request(
    paths: ProjectPaths,
    *,
    runner_profile_id: str,
    target_ref: str,
    brief_id: str | None = None,
    output: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    target = parse_target_ref(target_ref)
    if target["type"] != "task":
        raise _error(
            "profile_prepare_target_unsupported",
            "Council Profile v1 preparation currently supports task targets only.",
            target=target,
            supported_target_types=["task"],
        )

    profile_validation = validate_profile(runner_profile_id)
    if not profile_validation["ok"]:
        raise _error(
            "profile_manifest_invalid",
            f"Built-in runner Profile {runner_profile_id} is invalid.",
            errors=profile_validation["errors"],
        )
    profile_entry = show_profile(runner_profile_id)
    manifest = profile_entry["manifest"]
    selected_brief = _select_work_brief(paths, target_ref=target_ref, brief_id=brief_id)
    brief_path = paths.root / str(selected_brief["path"])
    brief_content = load_work_brief(brief_path)
    route_brief_file = None if selected_brief["approved"] else str(brief_path)

    recorded_route = _recorded_route_binding(
        paths,
        target_ref=target_ref,
        route_brief_file=route_brief_file,
    )
    route_profile = recorded_route["route_profile"]
    if route_profile not in manifest["supported_routes"]:
        raise _error(
            "profile_route_mismatch",
            (
                f"Runner Profile {runner_profile_id} does not support effective "
                f"route_profile {route_profile!r}."
            ),
            runner_profile_id=runner_profile_id,
            route_profile=route_profile,
            supported_route_profiles=manifest["supported_routes"],
            suggested_commands=[
                f"pcl route current --target {target_ref} --json",
                (
                    f"pcl route override --target {target_ref} --profile discover "
                    "--actor human:<owner> --reason '<reason>'"
                ),
            ],
        )

    resolution = recorded_route["resolution"]
    axes = resolution["axes"]
    context_budget_bytes = int(axes["context_budget_bytes"])
    context_pack = pack_context_for_task(
        paths,
        task_id=target["id"],
        now=now or utc_now_iso(),
        reader_role="default",
        max_tokens=max(1, context_budget_bytes // 4),
        include_code_context=False,
    )
    context_payload = _context_payload(context_pack)
    linked_evidence = _linked_evidence(paths, target)
    project = _project_identity(paths)
    task = read_task(paths, target["id"])
    generated_at = now or utc_now_iso()

    request: dict[str, Any] = {
        "contract_version": "profile-run-request/v1",
        "request_id": "",
        "generated_at": generated_at,
        "generator": {"name": "pcl", "version": __version__},
        "project": project,
        "profile": {
            "runner_profile_id": runner_profile_id,
            "profile_version": manifest["profile_version"],
            "manifest_sha256": profile_entry["manifest_sha256"],
        },
        "target": target,
        "work_brief": {
            "evidence_id": selected_brief["evidence_id"],
            "artifact_sha256": _without_sha_prefix(
                str(selected_brief["artifact_sha256"])
            ),
            "review_state": (
                "reviewed" if selected_brief.get("reviews") else "unreviewed"
            ),
            "approval_state": (
                "approved" if selected_brief["approved"] else "unapproved"
            ),
            "content": brief_content,
        },
        "route": {
            "route_profile": route_profile,
            "recommendation_evidence_id": recorded_route[
                "recommendation_evidence_id"
            ],
            "recommendation_sha256": recorded_route["recommendation_sha256"],
            "override": recorded_route["override"],
        },
        "resolved_policy": {
            "planning_depth": axes["planning_depth"],
            "verification_depth": axes["verification_depth"],
            "execution_chunk_size": axes["execution_chunk_size"],
            "checkpoint_frequency": axes["checkpoint_frequency"],
            "context_budget_bytes": axes["context_budget_bytes"],
            "tool_call_budget": axes["tool_call_budget"],
            "wall_time_budget_seconds": axes["wall_time_budget_seconds"],
            "strong_model_escalations": axes["escalation_budget"],
        },
        "context": context_payload,
        "linked_evidence": linked_evidence,
        "limits": {
            "max_participants": manifest["policy_defaults"]["max_participants"],
            "max_human_decisions": manifest["policy_defaults"][
                "max_human_decisions"
            ],
            "max_output_bytes": 2_000_000,
            "monetary_budget": None,
            "currency": None,
        },
        "data_policy": {
            "network_access": "forbidden",
            "paid_service_requested": False,
            "allowed_providers": [],
            "repository_content_policy": "selected_snippets",
            "secrets_policy": "never_send",
            "sensitive_paths": [".env", ".env.*", "secrets/"],
        },
        "request_basis_digest": {
            "algorithm": "sha256",
            "canonicalization": "pcl-canonical-json/v1-request-basis",
            "value": "",
        },
        "authorization": None,
        "request_digest": {
            "algorithm": "sha256",
            "canonicalization": "pcl-canonical-json/v1-excluding-request_digest",
            "value": "",
        },
    }
    request["request_id"] = _request_id(task, request)
    request["request_basis_digest"]["value"] = request_basis_digest(request)
    request["request_digest"]["value"] = request_digest(request)
    _assert_no_local_root(paths, request)

    validation = validate_profile_run_request(request)
    if not validation.ok:
        raise _error(
            "profile_request_generation_invalid",
            "Generated Profile request failed validation.",
            errors=list(validation.errors),
        )

    output_path = None
    if output is not None:
        output_path = _write_output(output, request)
    return {
        "contract_version": PROFILE_PREPARE_CONTRACT_VERSION,
        "ok": True,
        "changed": False,
        "read_only": True,
        "runner_executed": False,
        "authorization_status": "not_required_offline",
        "output_path": output_path,
        "request": request,
    }


def _select_work_brief(
    paths: ProjectPaths,
    *,
    target_ref: str,
    brief_id: str | None,
) -> dict[str, Any]:
    if brief_id is not None:
        result = show_work_brief(paths, evidence_id=brief_id)
        brief = result["work_brief"]
        expected = parse_target_ref(target_ref)
        if brief["target"] != expected:
            raise _error(
                "profile_work_brief_target_mismatch",
                f"Work Brief {brief_id} targets another entity.",
                expected=expected,
                actual=brief["target"],
            )
        if brief["health"] != "ok":
            raise _error(
                "profile_work_brief_unhealthy",
                f"Work Brief {brief_id} is not healthy.",
                evidence_id=brief_id,
                findings=brief["findings"],
            )
        return brief

    result = show_work_brief(paths, target_ref=target_ref)
    if result["current"] is not None:
        return result["current"]
    healthy = [
        candidate
        for candidate in result["candidates"]
        if candidate["health"] == "ok"
    ]
    if not healthy:
        raise _error(
            "profile_work_brief_missing",
            f"Target {target_ref} has no healthy Work Brief candidate.",
            target=target_ref,
            suggested_command="pcl brief add --file <work-brief.json> --summary '<summary>'",
        )
    if len(healthy) > 1:
        raise _error(
            "profile_work_brief_ambiguous",
            f"Target {target_ref} has multiple healthy Work Brief candidates.",
            target=target_ref,
            evidence_ids=[item["evidence_id"] for item in healthy],
            suggested_command=(
                f"pcl profile prepare council.discovery --target {target_ref} "
                "--brief <E-ID>"
            ),
        )
    return healthy[0]


def _recorded_route_binding(
    paths: ProjectPaths,
    *,
    target_ref: str,
    route_brief_file: str | None,
) -> dict[str, Any]:
    current = current_route(
        paths,
        target_ref=target_ref,
        brief_file=route_brief_file,
    )
    if current["overridden"]:
        artifact = current["override"]
        recommendation_id = str(
            artifact["original_recommendation_ref"]
        ).removeprefix("evidence:")
        recommendation = _load_route_evidence(paths, recommendation_id)
        changed_paths = recommendation["signals"]["changed_paths"]
        recomputed = recommend_route(
            paths,
            target_ref=target_ref,
            brief_file=route_brief_file,
            changed_paths=changed_paths,
            record=False,
        )["recommendation"]
        expected = _route_hash(recomputed)
        recorded = _without_sha_prefix(
            str(artifact["original_recommendation_sha256"])
        )
        if expected != recorded:
            raise _stale_route_error(target_ref, route_brief_file, changed_paths)
        override_hash = hashlib.sha256(
            canonical_route_override_json(artifact).encode("utf-8")
        ).hexdigest()
        return {
            "route_profile": artifact["effective_recommendation"]["profile"],
            "recommendation_evidence_id": recommendation_id,
            "recommendation_sha256": recorded,
            "override": {
                "evidence_id": current["evidence"]["id"],
                "artifact_sha256": override_hash,
            },
            "resolution": artifact["effective_resolution"],
        }

    rows = _route_rows(paths, parse_target_ref(target_ref))
    if not rows:
        raise _missing_route_error(target_ref, route_brief_file)
    for row in rows:
        recommendation = _load_route_evidence(paths, str(row["id"]))
        changed_paths = recommendation["signals"]["changed_paths"]
        recomputed = recommend_route(
            paths,
            target_ref=target_ref,
            brief_file=route_brief_file,
            changed_paths=changed_paths,
            record=False,
        )["recommendation"]
        if recomputed["input_digest"] != recommendation["input_digest"]:
            continue
        if _route_hash(recomputed) != _route_hash(recommendation):
            continue
        resolution = resolve_policy(recommendation)
        return {
            "route_profile": recommendation["profile"],
            "recommendation_evidence_id": str(row["id"]),
            "recommendation_sha256": _route_hash(recommendation),
            "override": None,
            "resolution": resolution,
        }
    latest = rows[0]
    latest_value = _load_route_evidence(paths, str(latest["id"]))
    raise _stale_route_error(
        target_ref,
        route_brief_file,
        list(latest_value["signals"]["changed_paths"]),
    )


def _route_rows(paths: ProjectPaths, target: dict[str, str]) -> list[dict[str, Any]]:
    conn = connect(paths.db_path)
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT evidence.id, evidence.path
                FROM evidence_links
                JOIN evidence ON evidence.id = evidence_links.evidence_id
                WHERE evidence_links.target_type = ?
                  AND evidence_links.target_id = ?
                  AND evidence_links.link_role = ?
                ORDER BY evidence.created_at DESC, evidence.id DESC
                """,
                (target["type"], target["id"], ROUTE_RECOMMENDATION_LINK_ROLE),
            ).fetchall()
        ]
    finally:
        conn.close()


def _load_route_evidence(paths: ProjectPaths, evidence_id: str) -> dict[str, Any]:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            "SELECT path, type FROM evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        event = conn.execute(
            """
            SELECT payload_json
            FROM events
            WHERE event_type = 'route_recommendation_recorded'
              AND entity_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (evidence_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or str(row["type"]) != "route_recommendation":
        raise _error(
            "profile_route_recommendation_integrity",
            f"Route recommendation Evidence {evidence_id} is missing or has the wrong type.",
            evidence_id=evidence_id,
        )
    path = paths.root / str(row["path"])
    try:
        value = load_route_recommendation(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise _error(
            "profile_route_recommendation_integrity",
            f"Route recommendation Evidence {evidence_id} cannot be read.",
            evidence_id=evidence_id,
            reason=str(exc),
        ) from exc
    validation = validate_route_recommendation(value)
    if not validation.ok or not isinstance(value, dict):
        raise _error(
            "profile_route_recommendation_integrity",
            f"Route recommendation Evidence {evidence_id} is invalid.",
            evidence_id=evidence_id,
            errors=list(validation.errors),
        )
    actual = "sha256:" + _route_hash(value)
    if event is not None:
        try:
            payload = json.loads(str(event["payload_json"]))
        except json.JSONDecodeError as exc:
            raise _error(
                "profile_route_recommendation_integrity",
                f"Route recommendation event for {evidence_id} is invalid.",
                evidence_id=evidence_id,
            ) from exc
        if payload.get("artifact_sha256") != actual:
            raise _error(
                "profile_route_recommendation_integrity",
                f"Route recommendation Evidence {evidence_id} has drifted.",
                evidence_id=evidence_id,
                expected=payload.get("artifact_sha256"),
                actual=actual,
            )
    return value


def _missing_route_error(
    target_ref: str,
    brief_file: str | None,
) -> ProfilePrepareError:
    command = _route_record_command(target_ref, brief_file, [])
    return _error(
        "profile_route_recommendation_missing",
        f"Target {target_ref} has no recorded route recommendation Evidence.",
        target=target_ref,
        suggested_command=command,
    )


def _stale_route_error(
    target_ref: str,
    brief_file: str | None,
    changed_paths: list[str],
) -> ProfilePrepareError:
    return _error(
        "profile_route_recommendation_stale",
        f"Recorded route recommendation for {target_ref} no longer matches current state.",
        target=target_ref,
        suggested_command=_route_record_command(
            target_ref,
            brief_file,
            changed_paths,
        ),
    )


def _route_record_command(
    target_ref: str,
    brief_file: str | None,
    changed_paths: list[str],
) -> str:
    parts = ["pcl", "route", "recommend", "--target", target_ref]
    if brief_file:
        parts.extend(["--brief", brief_file])
    for path in changed_paths:
        parts.extend(["--changed-path", path])
    parts.append("--record")
    return " ".join(parts)


def _context_payload(pack: dict[str, Any]) -> dict[str, Any]:
    omitted = [
        {"section": str(section), "reason": "context budget"}
        for section in pack.get("omitted_sections", [])
    ]
    return {
        "contract_version": "context-pack/v1",
        "role_profile": str(pack["role_profile"]),
        "estimated_token_count": int(pack["estimated_token_count"]),
        "included_sections": [str(item) for item in pack["included_sections"]],
        "omitted_sections": omitted,
        "markdown": str(pack["markdown"]),
    }


def _linked_evidence(
    paths: ProjectPaths,
    target: dict[str, str],
) -> list[dict[str, Any]]:
    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            """
            SELECT evidence.id, evidence.type, evidence.path, evidence.summary
            FROM evidence_links
            JOIN evidence ON evidence.id = evidence_links.evidence_id
            WHERE evidence_links.target_type = ?
              AND evidence_links.target_id = ?
              AND evidence_links.link_role = 'supporting'
            ORDER BY evidence.id
            """,
            (target["type"], target["id"]),
        ).fetchall()
    finally:
        conn.close()
    result: list[dict[str, Any]] = []
    for row in rows:
        path = paths.root / str(row["path"])
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise _error(
                "profile_linked_evidence_unreadable",
                f"Linked Evidence {row['id']} cannot be read.",
                evidence_id=str(row["id"]),
                reason=str(exc),
            ) from exc
        result.append(
            {
                "evidence_id": str(row["id"]),
                "kind": str(row["type"]),
                "artifact_sha256": digest,
                "summary": str(row["summary"]),
            }
        )
    return result


def _project_identity(paths: ProjectPaths) -> dict[str, str]:
    config_path = paths.root / "pcl.yaml"
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise _error(
            "profile_project_config_unreadable",
            f"Could not read project config at {config_path}.",
            reason=str(exc),
        ) from exc
    project = _simple_yaml_section(lines, "project")
    conn = connect(paths.db_path)
    try:
        schema_version = get_metadata(conn, "schema_version")
    finally:
        conn.close()
    fingerprint_input = {
        "resolved_root": str(paths.root.resolve()),
        "project_name": project.get("name") or "",
        "project_type": project.get("type") or "",
        "schema_version": schema_version,
        "git_head": _git_head(paths.root),
    }
    return {
        "root_basename": paths.root.name,
        "root_fingerprint": hashlib.sha256(
            canonical_json(fingerprint_input).encode("utf-8")
        ).hexdigest(),
    }


def _git_head(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _request_id(task: dict[str, Any], request: dict[str, Any]) -> str:
    timestamp = _compact_timestamp(str(task["updated_at"]))
    semantic = dict(request)
    semantic["request_id"] = ""
    semantic.pop("generated_at", None)
    semantic.pop("request_basis_digest", None)
    semantic.pop("request_digest", None)
    suffix = hashlib.sha256(canonical_json(semantic).encode("utf-8")).hexdigest()[:8]
    return f"PRR-{timestamp}-{suffix}"


def _compact_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error(
            "profile_target_timestamp_invalid",
            "Target updated_at is not a real RFC 3339 date-time.",
            updated_at=value,
        ) from exc
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _assert_no_local_root(paths: ProjectPaths, request: dict[str, Any]) -> None:
    serialized = json.dumps(request, ensure_ascii=False, allow_nan=False)
    root = str(paths.root.resolve())
    if root and root in serialized:
        raise _error(
            "profile_request_local_root_exposed",
            "Generated Profile request contains the local absolute project root.",
        )


def _write_output(path_value: str, request: dict[str, Any]) -> str:
    path = Path(path_value)
    if not path.parent.exists():
        raise InvalidInputError(
            f"Profile request output parent does not exist: {path.parent}",
            details={"output": path_value},
        )
    try:
        path.write_text(
            json.dumps(
                request,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise InvalidInputError(
            f"Could not write Profile request output: {path_value}",
            details={"output": path_value, "reason": str(exc)},
        ) from exc
    return str(path)


def _route_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_route_recommendation_json(value).encode("utf-8")
    ).hexdigest()


def _without_sha_prefix(value: str) -> str:
    return value.removeprefix("sha256:")


def _error(code: str, message: str, **details: Any) -> ProfilePrepareError:
    return ProfilePrepareError(message=message, code=code, details=details)
