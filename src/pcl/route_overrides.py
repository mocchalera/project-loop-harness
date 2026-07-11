from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from .adaptive_policy import load_policy, resolve_policy, resolve_policy_for_target
from .contracts.route_override import (
    ROUTE_OVERRIDE_CONTRACT_VERSION,
    load_route_override,
    serialized_route_override,
    validate_route_override,
)
from .contracts.route_recommendation import (
    canonical_route_recommendation_json,
    serialized_route_recommendation,
)
from .db import connect, connect_mutation, table_exists
from .errors import DataStoreError, PclError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .routing import _validate_target
from .timeutil import utc_now_iso


ROUTE_OVERRIDE_EVIDENCE_TYPE = "route_override"
ROUTE_OVERRIDE_LINK_ROLE = "route_override"
POLICY_RESOLUTION_EVIDENCE_TYPE = "adaptive_policy_resolution"
POLICY_RESOLUTION_LINK_ROLE = "adaptive_policy_resolution"
ROUTE_RECOMMENDATION_EVIDENCE_TYPE = "route_recommendation"
ROUTE_RECOMMENDATION_LINK_ROLE = "route_recommendation"

_PROFILES = {"direct", "discover", "assure"}
_PROTECTED_REASONS = {
    "auth_or_permission_change",
    "destructive_operation",
    "human_review_required",
    "migration_change",
}


class RouteOverrideError(PclError):
    pass


def override_route(
    paths: ProjectPaths,
    *,
    target_ref: str,
    requested_profile: str,
    actor: str,
    reason: str,
    brief_file: str | None = None,
    changed_paths: list[str] | None = None,
    policy_file: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    actor = actor.strip()
    reason = reason.strip()
    if not actor:
        raise _error("route_override_actor_required", "Override actor must be non-empty.")
    if not reason:
        raise _error("route_override_reason_required", "Override reason must be non-empty.")
    if requested_profile not in _PROFILES:
        raise _error(
            "route_override_profile_invalid",
            f"Unsupported override profile: {requested_profile}",
            allowed=sorted(_PROFILES),
        )

    resolved = resolve_policy_for_target(
        paths,
        target_ref=target_ref,
        brief_file=brief_file,
        changed_paths=changed_paths,
        policy_file=policy_file,
    )
    original_recommendation = resolved["recommendation"]
    original_resolution = resolved["resolution"]
    if requested_profile == original_recommendation["profile"]:
        raise _error(
            "route_override_no_change",
            "Requested profile already matches the deterministic recommendation.",
            profile=requested_profile,
        )
    _guard_profile_floor(original_recommendation, requested_profile)
    effective_recommendation = _effective_recommendation(
        original_recommendation,
        requested_profile=requested_profile,
        actor=actor,
        reason=reason,
    )
    effective_resolution = resolve_policy(
        effective_recommendation,
        policy=load_policy(policy_file),
    )
    preview = _preview(
        actor=actor,
        reason=reason,
        requested_profile=requested_profile,
        original_recommendation=original_recommendation,
        original_resolution=original_resolution,
        effective_recommendation=effective_recommendation,
        effective_resolution=effective_resolution,
    )
    if dry_run:
        return {
            "ok": True,
            "changed": False,
            "dry_run": True,
            "planned": preview,
        }
    return _record_override(paths, preview)


def current_route(
    paths: ProjectPaths,
    *,
    target_ref: str,
    brief_file: str | None = None,
    changed_paths: list[str] | None = None,
    policy_file: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    target_type, separator, target_id = target_ref.partition(":")
    if not separator or not target_type or not target_id:
        raise _error(
            "route_override_target_invalid",
            "Target must be formatted as <target-type>:<target-id>.",
            target=target_ref,
        )
    target = {"type": target_type, "id": target_id}
    conn = connect(paths.db_path)
    try:
        _validate_target(conn, target)
        row = conn.execute(
            """
            SELECT evidence.id, evidence.path, evidence.summary, evidence.created_at
            FROM evidence_links
            JOIN evidence ON evidence.id = evidence_links.evidence_id
            WHERE evidence_links.target_type = ?
              AND evidence_links.target_id = ?
              AND evidence_links.link_role = ?
            ORDER BY evidence.created_at DESC, evidence.id DESC
            LIMIT 1
            """,
            (target_type, target_id, ROUTE_OVERRIDE_LINK_ROLE),
        ).fetchone()
        if row is not None:
            artifact = _load_checked_override(paths, conn, row)
            return {
                "ok": True,
                "overridden": True,
                "evidence": {
                    "id": str(row["id"]),
                    "path": str(row["path"]),
                    "summary": str(row["summary"]),
                    "created_at": str(row["created_at"]),
                },
                "original": {
                    "recommendation_ref": artifact["original_recommendation_ref"],
                    "recommendation_sha256": artifact["original_recommendation_sha256"],
                    "resolution_ref": artifact["original_resolution_ref"],
                    "resolution_sha256": artifact["original_resolution_sha256"],
                },
                "effective": {
                    "recommendation": artifact["effective_recommendation"],
                    "resolution": artifact["effective_resolution"],
                },
                "override": artifact,
            }
    finally:
        conn.close()
    current = resolve_policy_for_target(
        paths,
        target_ref=target_ref,
        brief_file=brief_file,
        changed_paths=changed_paths,
        policy_file=policy_file,
    )
    return {
        "ok": True,
        "overridden": False,
        "original": current,
        "effective": current,
        "override": None,
    }


def recorded_route_context(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    target_type: str,
    target_id: str,
) -> dict[str, Any] | None:
    """Return hash-bound metadata for the latest recorded override without inlining sources."""

    if not table_exists(conn, "evidence_links"):
        return None

    row = conn.execute(
        """
        SELECT evidence.id, evidence.path, evidence.summary, evidence.created_at
        FROM evidence_links
        JOIN evidence ON evidence.id = evidence_links.evidence_id
        WHERE evidence_links.target_type = ?
          AND evidence_links.target_id = ?
          AND evidence_links.link_role = ?
        ORDER BY evidence.created_at DESC, evidence.id DESC
        LIMIT 1
        """,
        (target_type, target_id, ROUTE_OVERRIDE_LINK_ROLE),
    ).fetchone()
    if row is None:
        return None
    artifact = _load_checked_override(paths, conn, row)
    return {
        "contract_version": "adaptive-route-context/v1",
        "override_ref": f"evidence:{row['id']}",
        "override_sha256": _object_sha(artifact),
        "original_recommendation_ref": artifact["original_recommendation_ref"],
        "original_recommendation_sha256": artifact["original_recommendation_sha256"],
        "original_resolution_ref": artifact["original_resolution_ref"],
        "original_resolution_sha256": artifact["original_resolution_sha256"],
        "effective_profile": artifact["effective_recommendation"]["profile"],
        "risk_level": artifact["effective_recommendation"]["risk_level"],
        "path": str(row["path"]),
        "summary": str(row["summary"]),
        "created_at": str(row["created_at"]),
    }


def _guard_profile_floor(recommendation: dict[str, Any], requested_profile: str) -> None:
    protected = sorted(set(recommendation["reason_codes"]) & _PROTECTED_REASONS)
    if (protected or recommendation["risk_level"] == "R4") and requested_profile != "assure":
        raise _error(
            "route_override_forbidden_downgrade",
            "The requested profile would weaken a non-overridable route floor.",
            requested_profile=requested_profile,
            risk_level=recommendation["risk_level"],
            protected_reason_codes=protected,
            required_profile="assure",
        )


def _effective_recommendation(
    original: dict[str, Any],
    *,
    requested_profile: str,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    result = deepcopy(original)
    result["profile"] = requested_profile
    result["reason_codes"] = sorted(set(result["reason_codes"]) | {"operator_override"})
    digest_input = {
        "original_input_digest": original["input_digest"],
        "requested_profile": requested_profile,
        "actor": actor,
        "reason": reason,
    }
    result["input_digest"] = _sha256(_canonical_json(digest_input))
    return result


def _preview(
    *,
    actor: str,
    reason: str,
    requested_profile: str,
    original_recommendation: dict[str, Any],
    original_resolution: dict[str, Any],
    effective_recommendation: dict[str, Any],
    effective_resolution: dict[str, Any],
) -> dict[str, Any]:
    semantic = {
        "target": original_recommendation["target"],
        "actor": actor,
        "reason": reason,
        "requested_profile": requested_profile,
        "original_recommendation_sha256": _route_sha(original_recommendation),
        "original_resolution_sha256": _object_sha(original_resolution),
        "effective_recommendation_sha256": _route_sha(effective_recommendation),
        "effective_resolution_sha256": _object_sha(effective_resolution),
    }
    return {
        "contract_version": ROUTE_OVERRIDE_CONTRACT_VERSION,
        "override_digest": _sha256(_canonical_json(semantic)),
        **semantic,
        "original_recommendation": original_recommendation,
        "original_resolution": original_resolution,
        "effective_recommendation": effective_recommendation,
        "effective_resolution": effective_resolution,
        "mutation": {
            "evidence_rows": 3,
            "events": 1,
            "outbox_records": 1,
            "evidence_links": 3,
        },
    }


def _record_override(paths: ProjectPaths, preview: dict[str, Any]) -> dict[str, Any]:
    conn = connect_mutation(paths)
    created_paths: list[Path] = []
    try:
        target = preview["target"]
        _validate_target(conn, target)
        existing = _matching_override(conn, paths, target, preview["override_digest"])
        if existing is not None:
            conn.rollback()
            return {
                "ok": True,
                "changed": False,
                "dry_run": False,
                "override": existing["artifact"],
                "evidence": existing["evidence"],
                "event_id": None,
            }
        now = utc_now_iso()
        recommendation_evidence = _insert_artifact_evidence(
            paths,
            conn,
            target=target,
            evidence_type=ROUTE_RECOMMENDATION_EVIDENCE_TYPE,
            link_role=ROUTE_RECOMMENDATION_LINK_ROLE,
            stem="route-recommendation-v1",
            content=serialized_route_recommendation(preview["original_recommendation"]),
            artifact_sha256=preview["original_recommendation_sha256"],
            summary=(
                f"Original {preview['original_recommendation']['profile']} route for "
                f"{target['type']}:{target['id']} before operator override"
            ),
            now=now,
            created_paths=created_paths,
        )
        resolution_content = _serialized_json(preview["original_resolution"])
        resolution_evidence = _insert_artifact_evidence(
            paths,
            conn,
            target=target,
            evidence_type=POLICY_RESOLUTION_EVIDENCE_TYPE,
            link_role=POLICY_RESOLUTION_LINK_ROLE,
            stem="adaptive-policy-resolution-v1",
            content=resolution_content,
            artifact_sha256=preview["original_resolution_sha256"],
            summary=f"Original adaptive policy resolution for {target['type']}:{target['id']}",
            now=now,
            created_paths=created_paths,
        )
        artifact = {
            "contract_version": ROUTE_OVERRIDE_CONTRACT_VERSION,
            "override_digest": preview["override_digest"],
            "target": target,
            "actor": preview["actor"],
            "reason": preview["reason"],
            "requested_profile": preview["requested_profile"],
            "original_recommendation_ref": f"evidence:{recommendation_evidence['id']}",
            "original_recommendation_sha256": preview["original_recommendation_sha256"],
            "original_resolution_ref": f"evidence:{resolution_evidence['id']}",
            "original_resolution_sha256": preview["original_resolution_sha256"],
            "effective_recommendation": preview["effective_recommendation"],
            "effective_recommendation_sha256": preview["effective_recommendation_sha256"],
            "effective_resolution": preview["effective_resolution"],
            "effective_resolution_sha256": preview["effective_resolution_sha256"],
        }
        validation = validate_route_override(artifact)
        if not validation.ok:
            raise DataStoreError(
                "Generated route override failed validation.",
                details={"errors": list(validation.errors)},
            )
        override_evidence = _insert_artifact_evidence(
            paths,
            conn,
            target=target,
            evidence_type=ROUTE_OVERRIDE_EVIDENCE_TYPE,
            link_role=ROUTE_OVERRIDE_LINK_ROLE,
            stem="route-override-v1",
            content=serialized_route_override(artifact),
            artifact_sha256=_object_sha(artifact),
            summary=(
                f"Override {preview['original_recommendation']['profile']} -> "
                f"{preview['requested_profile']} for {target['type']}:{target['id']}"
            ),
            now=now,
            created_paths=created_paths,
        )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="route_override_recorded",
            entity_type="evidence",
            entity_id=override_evidence["id"],
            payload={
                "override_evidence_id": override_evidence["id"],
                "original_recommendation_evidence_id": recommendation_evidence["id"],
                "original_resolution_evidence_id": resolution_evidence["id"],
                "target": target,
                "actor": preview["actor"],
                "reason": preview["reason"],
                "original_profile": preview["original_recommendation"]["profile"],
                "effective_profile": preview["requested_profile"],
                "risk_level": preview["original_recommendation"]["risk_level"],
                "override_digest": preview["override_digest"],
            },
        )
        conn.commit()
        return {
            "ok": True,
            "changed": True,
            "dry_run": False,
            "override": artifact,
            "evidence": {
                "override": override_evidence,
                "original_recommendation": recommendation_evidence,
                "original_resolution": resolution_evidence,
            },
            "event_id": event_id,
        }
    except PclError:
        conn.rollback()
        _remove_uncommitted(conn, created_paths)
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        conn.rollback()
        _remove_uncommitted(conn, created_paths)
        raise DataStoreError(f"Could not record route override: {exc}") from exc
    finally:
        conn.close()


def _insert_artifact_evidence(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    target: dict[str, str],
    evidence_type: str,
    link_role: str,
    stem: str,
    content: str,
    artifact_sha256: str,
    summary: str,
    now: str,
    created_paths: list[Path],
) -> dict[str, Any]:
    evidence_id = next_prefixed_id(conn, "evidence", "E")
    artifact_dir = paths.evidence_dir / "adaptive-route"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    final_path = artifact_dir / f"{evidence_id.lower()}-{stem}.json"
    temp_path = final_path.with_suffix(".json.tmp")
    temp_path.write_text(content, encoding="utf-8")
    created_paths.append(temp_path)
    temp_path.replace(final_path)
    created_paths.append(final_path)
    relative_path = final_path.relative_to(paths.root).as_posix()
    conn.execute(
        "INSERT INTO evidence(id, type, path, command, summary, created_at) "
        "VALUES (?, ?, ?, NULL, ?, ?)",
        (evidence_id, evidence_type, relative_path, summary, now),
    )
    conn.execute(
        "INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (evidence_id, target["type"], target["id"], link_role, now),
    )
    return {
        "id": evidence_id,
        "type": evidence_type,
        "path": relative_path,
        "summary": summary,
        "artifact_sha256": artifact_sha256,
    }


def _matching_override(
    conn: sqlite3.Connection,
    paths: ProjectPaths,
    target: dict[str, str],
    override_digest: str,
) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT evidence.id, evidence.path, evidence.summary, evidence.created_at
        FROM evidence_links
        JOIN evidence ON evidence.id = evidence_links.evidence_id
        WHERE evidence_links.target_type = ?
          AND evidence_links.target_id = ?
          AND evidence_links.link_role = ?
        ORDER BY evidence.created_at DESC, evidence.id DESC
        """,
        (target["type"], target["id"], ROUTE_OVERRIDE_LINK_ROLE),
    ).fetchall()
    for row in rows:
        try:
            artifact = load_route_override(paths.root / str(row["path"]))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(artifact, dict) and artifact.get("override_digest") == override_digest:
            return {
                "artifact": artifact,
                "evidence": {
                    "override": {
                        "id": str(row["id"]),
                        "type": ROUTE_OVERRIDE_EVIDENCE_TYPE,
                        "path": str(row["path"]),
                        "summary": str(row["summary"]),
                    }
                },
            }
    return None


def _load_checked_override(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    try:
        artifact = load_route_override(paths.root / str(row["path"]))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise _error(
            "route_override_artifact_unreadable",
            f"Could not read current route override Evidence {row['id']}.",
            evidence_id=str(row["id"]),
            reason=str(exc),
        ) from exc
    validation = validate_route_override(artifact)
    if not validation.ok:
        raise _error(
            "route_override_artifact_invalid",
            f"Current route override Evidence {row['id']} is invalid.",
            evidence_id=str(row["id"]),
            errors=list(validation.errors),
        )
    for ref_field, hash_field in (
        ("original_recommendation_ref", "original_recommendation_sha256"),
        ("original_resolution_ref", "original_resolution_sha256"),
    ):
        evidence_id = str(artifact[ref_field]).removeprefix("evidence:")
        referenced = conn.execute(
            "SELECT path FROM evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        if referenced is None:
            raise _error(
                "route_override_reference_missing",
                f"Route override references missing Evidence {evidence_id}.",
                evidence_id=evidence_id,
            )
        path = paths.root / str(referenced["path"])
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise _error(
                "route_override_reference_unreadable",
                f"Route override reference {evidence_id} cannot be read.",
                evidence_id=evidence_id,
                reason=str(exc),
            ) from exc
        actual = _object_sha(value)
        if actual != artifact[hash_field]:
            raise _error(
                "route_override_reference_hash_mismatch",
                f"Route override reference {evidence_id} has drifted.",
                evidence_id=evidence_id,
                expected=artifact[hash_field],
                actual=actual,
            )
    return artifact


def _route_sha(value: dict[str, Any]) -> str:
    return _sha256(canonical_route_recommendation_json(value))


def _object_sha(value: dict[str, Any]) -> str:
    return _sha256(_canonical_json(value))


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _serialized_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def _remove_uncommitted(conn: sqlite3.Connection, paths: list[Path]) -> None:
    if getattr(conn, "_authoritative_commit_completed", False):
        return
    for path in reversed(paths):
        if path.exists():
            path.unlink()


def _error(code: str, message: str, **details: Any) -> RouteOverrideError:
    return RouteOverrideError(message=message, code=code, details=details)
