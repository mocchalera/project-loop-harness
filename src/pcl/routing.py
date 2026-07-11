from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .contracts.route_recommendation import (
    ROUTE_POLICY_VERSION,
    ROUTE_RECOMMENDATION_CONTRACT_VERSION,
    canonical_route_recommendation_json,
    serialized_route_recommendation,
    validate_route_recommendation,
)
from .contracts.work_brief import load_work_brief, validate_work_brief, work_brief_sha256
from .db import connect, connect_mutation
from .errors import DataStoreError, InvalidInputError, PclError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso
from .validators import _simple_yaml_section
from .work_briefs import current_approved_work_brief, parse_target_ref


ROUTE_RECOMMENDATION_EVIDENCE_TYPE = "route_recommendation"
ROUTE_RECOMMENDATION_LINK_ROLE = "route_recommendation"

_TARGET_TABLES = {
    "goal": "goals",
    "task": "tasks",
    "feature": "features",
    "story": "user_stories",
    "defect": "defects",
    "workflow_run": "workflow_runs",
}
_AUTH_SEGMENTS = {"auth", "authentication", "permission", "permissions", "security"}
_MIGRATION_SEGMENTS = {"migration", "migrations", "schema", "schemas"}
_DEPENDENCY_FILES = {
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "uv.lock",
}


class RouteRecommendationError(PclError):
    pass


def recommend_route(
    paths: ProjectPaths,
    *,
    target_ref: str,
    brief_file: str | None = None,
    changed_paths: list[str] | None = None,
    record: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    target = parse_target_ref(target_ref)
    normalized_paths = sorted({_normalize_path(item) for item in (changed_paths or []) if item.strip()})
    conn = connect(paths.db_path)
    try:
        _validate_target(conn, target)
        approved = current_approved_work_brief(
            paths,
            conn,
            target_type=target["type"],
            target_id=target["id"],
        )
    finally:
        conn.close()

    brief, work_brief_ref, work_brief_hash, brief_source = _brief_input(
        paths,
        target=target,
        approved=approved,
        brief_file=brief_file,
    )
    signals = _signals(
        paths,
        brief=brief,
        brief_source=brief_source,
        changed_paths=normalized_paths,
    )
    profile, risk_level, reason_codes = _resolve(signals)
    digest_input = {
        "policy_version": ROUTE_POLICY_VERSION,
        "target": target,
        "signals": signals,
        "work_brief_content_sha256": work_brief_sha256(brief) if brief is not None else None,
    }
    input_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            digest_input,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    recommendation = {
        "contract_version": ROUTE_RECOMMENDATION_CONTRACT_VERSION,
        "policy_version": ROUTE_POLICY_VERSION,
        "target": target,
        "input_digest": input_digest,
        "profile": profile,
        "risk_level": risk_level,
        "signals": signals,
        "reason_codes": reason_codes,
        "work_brief_ref": work_brief_ref,
        "work_brief_sha256": work_brief_hash,
    }
    validation = validate_route_recommendation(recommendation)
    if not validation.ok:
        raise DataStoreError(
            "Generated route recommendation failed validation.",
            details={"errors": list(validation.errors)},
        )
    if not record:
        return {"ok": True, "changed": False, "recorded": False, "recommendation": recommendation}
    return _record_recommendation(paths, recommendation)


def _brief_input(
    paths: ProjectPaths,
    *,
    target: dict[str, str],
    approved: dict[str, Any] | None,
    brief_file: str | None,
) -> tuple[dict[str, Any] | None, str | None, str | None, str]:
    if brief_file:
        try:
            value = load_work_brief(brief_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidInputError(
                f"Could not load route Work Brief: {brief_file}",
                details={"brief_file": brief_file, "reason": str(exc)},
            ) from exc
        validation = validate_work_brief(value)
        if not validation.ok:
            raise _error(
                "route_work_brief_invalid",
                "The explicit Work Brief is invalid.",
                brief_file=brief_file,
                errors=list(validation.errors),
            )
        if value["target"] != target:
            raise _error(
                "route_work_brief_target_mismatch",
                "The explicit Work Brief targets another entity.",
                expected=target,
                actual=value["target"],
            )
        return value, None, None, "explicit_file"
    if approved is None:
        return None, None, None, "missing"
    path = paths.root / str(approved["path"])
    value = load_work_brief(path)
    return (
        value,
        f"evidence:{approved['evidence_id']}",
        str(approved["artifact_sha256"]),
        "approved_evidence",
    )


def _signals(
    paths: ProjectPaths,
    *,
    brief: dict[str, Any] | None,
    brief_source: str,
    changed_paths: list[str],
) -> dict[str, Any]:
    acceptance = brief.get("acceptance_criteria", []) if brief else []
    assumptions = brief.get("assumptions", []) if brief else []
    path_parts = {part for path in changed_paths for part in path.split("/") if part}
    filenames = {path.rsplit("/", 1)[-1] for path in changed_paths}
    commands = _configured_commands(paths)
    return {
        "brief_present": brief is not None,
        "brief_source": brief_source,
        "acceptance_criteria_count": len(acceptance),
        "critical_acceptance_count": sum(
            1 for item in acceptance if isinstance(item, dict) and item.get("critical") is True
        ),
        "unverified_assumption_count": sum(
            1
            for item in assumptions
            if isinstance(item, dict) and item.get("status") == "unverified"
        ),
        "contradicted_assumption_count": sum(
            1
            for item in assumptions
            if isinstance(item, dict) and item.get("status") == "contradicted"
        ),
        "changed_paths": changed_paths,
        "auth_or_permission_change": bool(path_parts & _AUTH_SEGMENTS),
        "migration_change": bool(path_parts & _MIGRATION_SEGMENTS),
        "dependency_change": bool(filenames & _DEPENDENCY_FILES),
        "configured_deterministic_checks": commands,
        "deterministic_check_available": bool(commands),
        "model_self_assessment_used": False,
    }


def _resolve(signals: dict[str, Any]) -> tuple[str, str, list[str]]:
    reasons: set[str] = set()
    if signals["brief_present"]:
        if signals["acceptance_criteria_count"]:
            reasons.add("clear_acceptance")
        else:
            reasons.add("missing_acceptance")
        if signals["brief_source"] == "explicit_file":
            reasons.add("unapproved_brief_input")
    else:
        reasons.update({"missing_acceptance", "missing_work_brief"})
    if signals["unverified_assumption_count"]:
        reasons.add("unverified_assumption")
    if signals["contradicted_assumption_count"]:
        reasons.add("contradicted_assumption")
    if not signals["deterministic_check_available"]:
        reasons.add("no_deterministic_check")
    if signals["auth_or_permission_change"]:
        reasons.add("auth_or_permission_change")
    if signals["migration_change"]:
        reasons.add("migration_change")
    if signals["dependency_change"]:
        reasons.add("dependency_change")

    if reasons & {"auth_or_permission_change", "migration_change", "dependency_change"}:
        profile = "assure"
    elif reasons & {
        "contradicted_assumption",
        "missing_acceptance",
        "missing_work_brief",
        "no_deterministic_check",
        "unapproved_brief_input",
        "unverified_assumption",
    }:
        profile = "discover"
    else:
        profile = "direct"
    if reasons & {"auth_or_permission_change", "migration_change"}:
        risk_level = "R3"
    elif "dependency_change" in reasons:
        risk_level = "R2"
    elif profile == "discover":
        risk_level = "R1"
    else:
        risk_level = "R0"
    return profile, risk_level, sorted(reasons)


def _configured_commands(paths: ProjectPaths) -> list[str]:
    config = paths.root / "pcl.yaml"
    if not config.is_file():
        return []
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    commands = _simple_yaml_section(lines, "commands")
    return sorted(key for key, value in commands.items() if value and key != "install")


def _record_recommendation(
    paths: ProjectPaths,
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    conn = connect_mutation(paths)
    final_path: Path | None = None
    temp_path: Path | None = None
    try:
        target = recommendation["target"]
        _validate_target(conn, target)
        existing = _matching_recorded_recommendation(conn, paths, recommendation)
        if existing is not None:
            conn.rollback()
            return {
                "ok": True,
                "changed": False,
                "recorded": True,
                "recommendation": recommendation,
                "evidence": existing,
                "event_id": None,
            }
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        artifact_dir = paths.evidence_dir / "route-recommendations"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        final_path = artifact_dir / f"{evidence_id.lower()}-route-recommendation-v1.json"
        temp_path = final_path.with_suffix(".json.tmp")
        temp_path.write_text(serialized_route_recommendation(recommendation), encoding="utf-8")
        temp_path.replace(final_path)
        relative_path = final_path.relative_to(paths.root).as_posix()
        now = utc_now_iso()
        summary = (
            f"{recommendation['profile']} route for {target['type']}:{target['id']} "
            f"({', '.join(recommendation['reason_codes'])})"
        )
        conn.execute(
            "INSERT INTO evidence(id, type, path, command, summary, created_at) VALUES (?, ?, ?, NULL, ?, ?)",
            (evidence_id, ROUTE_RECOMMENDATION_EVIDENCE_TYPE, relative_path, summary, now),
        )
        conn.execute(
            """
            INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                target["type"],
                target["id"],
                ROUTE_RECOMMENDATION_LINK_ROLE,
                now,
            ),
        )
        artifact_sha256 = "sha256:" + hashlib.sha256(
            canonical_route_recommendation_json(recommendation).encode("utf-8")
        ).hexdigest()
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="route_recommendation_recorded",
            entity_type="evidence",
            entity_id=evidence_id,
            payload={
                "evidence_id": evidence_id,
                "target": target,
                "profile": recommendation["profile"],
                "risk_level": recommendation["risk_level"],
                "input_digest": recommendation["input_digest"],
                "policy_version": recommendation["policy_version"],
                "artifact_sha256": artifact_sha256,
                "path": relative_path,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "changed": True,
            "recorded": True,
            "recommendation": recommendation,
            "evidence": {
                "id": evidence_id,
                "type": ROUTE_RECOMMENDATION_EVIDENCE_TYPE,
                "path": relative_path,
                "summary": summary,
                "artifact_sha256": artifact_sha256,
            },
            "event_id": event_id,
        }
    except PclError:
        conn.rollback()
        _remove_uncommitted(conn, temp_path, final_path)
        raise
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        _remove_uncommitted(conn, temp_path, final_path)
        raise DataStoreError(f"Could not record route recommendation: {exc}") from exc
    finally:
        conn.close()


def _matching_recorded_recommendation(
    conn: sqlite3.Connection,
    paths: ProjectPaths,
    recommendation: dict[str, Any],
) -> dict[str, Any] | None:
    target = recommendation["target"]
    rows = conn.execute(
        """
        SELECT evidence.id, evidence.path, evidence.summary
        FROM evidence_links
        JOIN evidence ON evidence.id = evidence_links.evidence_id
        WHERE evidence_links.target_type = ?
          AND evidence_links.target_id = ?
          AND evidence_links.link_role = ?
        ORDER BY evidence.created_at DESC, evidence.id DESC
        """,
        (target["type"], target["id"], ROUTE_RECOMMENDATION_LINK_ROLE),
    ).fetchall()
    for row in rows:
        try:
            value = json.loads((paths.root / str(row["path"])).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, dict)
            and value.get("input_digest") == recommendation["input_digest"]
            and value.get("policy_version") == recommendation["policy_version"]
        ):
            return {
                "id": str(row["id"]),
                "type": ROUTE_RECOMMENDATION_EVIDENCE_TYPE,
                "path": str(row["path"]),
                "summary": str(row["summary"]),
            }
    return None


def _validate_target(conn: sqlite3.Connection, target: dict[str, str]) -> None:
    table = _TARGET_TABLES.get(target["type"])
    if table is None:
        raise _error(
            "route_unknown_target_type",
            f"Unsupported route target type: {target['type']}",
            target=target,
        )
    if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (target["id"],)).fetchone() is None:
        raise _error(
            "route_unknown_target",
            f"Route target does not exist: {target['type']}:{target['id']}",
            target=target,
        )


def _normalize_path(value: str) -> str:
    path = re.sub(r"/+", "/", str(value).strip().replace("\\", "/"))
    while path.startswith("./"):
        path = path[2:]
    return path.strip("/").casefold()


def _remove_uncommitted(
    conn: sqlite3.Connection,
    temp_path: Path | None,
    final_path: Path | None,
) -> None:
    if getattr(conn, "_authoritative_commit_completed", False):
        return
    for path in (temp_path, final_path):
        if path is not None and path.exists():
            path.unlink()


def _error(code: str, message: str, **details: Any) -> RouteRecommendationError:
    return RouteRecommendationError(message=message, code=code, details=details)
