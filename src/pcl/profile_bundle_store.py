from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any
import uuid

from .contracts._profile_contract import load_strict_json
from .db import connect, connect_mutation
from .errors import DataStoreError, EXIT_USAGE, PclError
from .events import append_event
from .evidence import insert_evidence_link
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .profile_ingest import plan_profile_ingest
from .test_faults import crash_if_requested
from .timeutil import utc_now_iso


PROFILE_OUTPUT_EVIDENCE_CONTRACT_VERSION = "profile-output-evidence/v1"
PROFILE_OUTPUT_EVIDENCE_TYPE = "profile_output_bundle"
PROFILE_BUNDLE_DIRECTORY = "profile-output-bundles"


class ProfileIngestError(PclError):
    pass


def ingest_profile_bundle(
    paths: ProjectPaths,
    *,
    request_file: str,
    bundle_file: str,
    accept_failed: bool = False,
    summary: str | None = None,
) -> dict[str, Any]:
    cleaned_summary = str(summary or "").strip()
    plan = plan_profile_ingest(
        paths,
        request_file=request_file,
        bundle_file=bundle_file,
        accept_failed=accept_failed,
        summary=cleaned_summary,
    )
    status = str(plan["bundle"]["status"])
    if status == "failed" and plan["requires_accept_failed"]:
        raise ProfileIngestError(
            message="Failed bundles require --accept-failed and a non-empty --summary.",
            code="profile_failed_bundle_acceptance_required",
            exit_code=EXIT_USAGE,
            details={
                "status": status,
                "required_flags": ["--accept-failed", "--summary"],
            },
        )

    request = load_strict_json(request_file)
    bundle = load_strict_json(bundle_file)
    if not isinstance(request, dict) or not isinstance(bundle, dict):
        raise ProfileIngestError(
            message="Validated Profile inputs must be JSON objects.",
            code="profile_ingest_input_invalid",
            exit_code=EXIT_USAGE,
            details={},
        )
    replay = _find_replay(paths, bundle)
    if replay is not None:
        return replay

    storage_root = paths.evidence_dir / PROFILE_BUNDLE_DIRECTORY
    storage_root.mkdir(parents=True, exist_ok=True)
    final_dir = storage_root / str(bundle["bundle_id"]).lower()
    if os.path.lexists(final_dir):
        raise ProfileIngestError(
            message="A finalized directory exists without matching durable Evidence.",
            code="profile_bundle_orphan_conflict",
            exit_code=EXIT_USAGE,
            details={
                "bundle_id": bundle["bundle_id"],
                "path": str(final_dir.relative_to(paths.root)),
                "repair": "Run pcl audit check and explicitly quarantine or report the orphan.",
            },
        )

    staging = Path(
        tempfile.mkdtemp(prefix=".staging-", dir=storage_root)
    )
    renamed = False
    conn = None
    try:
        request_copy = staging / "request.json"
        payload_dir = staging / "payload"
        payload_dir.mkdir()
        control_name = f".pcl-bundle-{uuid.uuid4().hex}.json"
        artifact_paths = {str(item["path"]) for item in bundle["artifacts"]}
        while control_name in artifact_paths:
            control_name = f".pcl-bundle-{uuid.uuid4().hex}.json"
        bundle_copy = payload_dir / control_name
        _copy_regular(Path(request_file), request_copy)
        _copy_regular(Path(bundle_file), bundle_copy)
        members: list[dict[str, Any]] = []
        source_root = Path(bundle_file).parent
        for artifact in bundle["artifacts"]:
            logical_path = str(artifact["path"])
            destination = payload_dir / logical_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_regular(source_root / logical_path, destination)
            members.append(
                {
                    "artifact_id": artifact["artifact_id"],
                    "role": artifact["role"],
                    "contract_version": artifact["contract_version"],
                    "logical_path": logical_path,
                    "storage_path": f"payload/{logical_path}",
                    "sha256": artifact["sha256"],
                    "size_bytes": artifact["size_bytes"],
                }
            )
        crash_if_requested("profile_ingest_after_copy")
        staged_plan = plan_profile_ingest(
            paths,
            request_file=str(request_copy),
            bundle_file=str(bundle_copy),
            accept_failed=accept_failed,
            summary=cleaned_summary,
        )
        if staged_plan["request"] != plan["request"] or staged_plan["bundle"] != plan["bundle"]:
            raise ProfileIngestError(
                message="Staged bundle differs from the validated source.",
                code="profile_bundle_staging_mismatch",
                exit_code=EXIT_USAGE,
                details={"bundle_id": bundle["bundle_id"]},
            )
        proposals = _staged_proposals(bundle, payload_dir)
        crash_if_requested("profile_ingest_before_rename")

        conn = connect_mutation(paths)
        replay = _find_replay_with_conn(paths, conn, bundle)
        if replay is not None:
            shutil.rmtree(staging)
            conn.rollback()
            return replay
        if os.path.lexists(final_dir):
            raise ProfileIngestError(
                message="Bundle finalization raced with another ingest.",
                code="profile_bundle_orphan_conflict",
                exit_code=EXIT_USAGE,
                details={"bundle_id": bundle["bundle_id"]},
            )
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        now = utc_now_iso()
        decision_bindings: list[dict[str, Any]] = []
        for item in proposals:
            proposal = item["proposal"]
            decision_id = next_prefixed_id(conn, "decisions", "DEC")
            recommendation = (
                f"{proposal['recommended_candidate_id']}: "
                f"{proposal['recommendation_reason']}"
            )
            blocks_json = json.dumps(
                [request["target"], {"type": "evidence", "id": evidence_id}],
                ensure_ascii=False,
                sort_keys=True,
            )
            conn.execute(
                """
                INSERT INTO decisions(id, status, question, recommendation, blocks_json, created_at)
                VALUES (?, 'open', ?, ?, ?, ?)
                """,
                (decision_id, proposal["question"], recommendation, blocks_json, now),
            )
            decision_bindings.append(
                {
                    "decision_id": decision_id,
                    "artifact_id": item["artifact"]["artifact_id"],
                    "proposal_id": proposal["proposal_id"],
                }
            )
        evidence_manifest = {
            "contract_version": PROFILE_OUTPUT_EVIDENCE_CONTRACT_VERSION,
            "evidence_id": evidence_id,
            "evidence_type": PROFILE_OUTPUT_EVIDENCE_TYPE,
            "created_at": now,
            "target": request["target"],
            "profile": request["profile"],
            "request": {
                "request_id": request["request_id"],
                "request_digest": request["request_digest"]["value"],
                "stored_path": "request.json",
                "stored_sha256": _sha256_file(request_copy),
                "stored_size_bytes": request_copy.stat().st_size,
            },
            "bundle": {
                "bundle_id": bundle["bundle_id"],
                "bundle_digest": bundle["bundle_digest"]["value"],
                "status": status,
                "stored_manifest_path": f"payload/{control_name}",
                "stored_manifest_sha256": _sha256_file(bundle_copy),
                "stored_manifest_size_bytes": bundle_copy.stat().st_size,
            },
            "members": members,
            "decisions": decision_bindings,
            "failed_acceptance": (
                {"accepted": True, "summary": cleaned_summary}
                if status == "failed"
                else None
            ),
        }
        manifest_path = staging / "evidence-manifest.json"
        _write_fsynced_json(manifest_path, evidence_manifest)
        _fsync_directory(staging)
        os.replace(staging, final_dir)
        renamed = True
        _fsync_directory(storage_root)
        crash_if_requested("profile_ingest_after_rename_before_commit")

        relative_manifest = str((final_dir / manifest_path.name).relative_to(paths.root))
        target = request["target"]
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at, linked_task_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                PROFILE_OUTPUT_EVIDENCE_TYPE,
                relative_manifest,
                "pcl profile ingest",
                cleaned_summary or str(bundle["summary"]),
                now,
                target["id"] if target["type"] == "task" else None,
            ),
        )
        insert_evidence_link(
            conn,
            evidence_id=evidence_id,
            target_type=str(target["type"]),
            target_id=str(target["id"]),
            link_role="supporting",
            created_at=now,
        )
        created_decisions: list[dict[str, Any]] = []
        for item, binding in zip(proposals, decision_bindings, strict=True):
            proposal = item["proposal"]
            artifact = item["artifact"]
            decision_id = str(binding["decision_id"])
            insert_evidence_link(
                conn,
                evidence_id=evidence_id,
                target_type="decision",
                target_id=decision_id,
                link_role="decision_proposal_source",
                created_at=now,
            )
            proposal_payload = {
                "contract_version": "profile-decision-proposed/v1",
                "decision_id": decision_id,
                "target": request["target"],
                "bundle_evidence_id": evidence_id,
                "bundle_id": bundle["bundle_id"],
                "bundle_digest": bundle["bundle_digest"]["value"],
                "artifact_id": artifact["artifact_id"],
                "artifact_path": artifact["path"],
                "artifact_sha256": artifact["sha256"],
                "proposal_id": proposal["proposal_id"],
                "candidate_ids": [candidate["candidate_id"] for candidate in proposal["candidates"]],
                "recommended_candidate_id": proposal["recommended_candidate_id"],
            }
            proposal_event_id = append_event(
                conn=conn,
                events_path=paths.events_path,
                event_type="profile_decision_proposed",
                entity_type="decision",
                entity_id=decision_id,
                payload=proposal_payload,
            )
            created_decisions.append(
                {
                    **binding,
                    "event_id": proposal_event_id,
                    "status": "open",
                }
            )
        event_payload = {
            "contract_version": PROFILE_OUTPUT_EVIDENCE_CONTRACT_VERSION,
            "evidence_id": evidence_id,
            "manifest_path": relative_manifest,
            "target": target,
            "profile": request["profile"],
            "request_id": request["request_id"],
            "request_digest": request["request_digest"]["value"],
            "bundle_id": bundle["bundle_id"],
            "bundle_digest": bundle["bundle_digest"]["value"],
            "bundle_status": status,
            "artifact_count": len(members),
            "failed_acceptance_summary": cleaned_summary if status == "failed" else None,
            "decision_ids": [item["decision_id"] for item in created_decisions],
        }
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="profile_output_ingested",
            entity_type="evidence",
            entity_id=evidence_id,
            payload=event_payload,
        )
        crash_if_requested("profile_ingest_after_outbox_before_commit")
        conn.commit()
        return {
            "ok": True,
            "changed": True,
            "idempotent": False,
            "evidence": {
                "id": evidence_id,
                "type": PROFILE_OUTPUT_EVIDENCE_TYPE,
                "manifest_path": relative_manifest,
            },
            "event_id": event_id,
            "request": plan["request"],
            "bundle": plan["bundle"],
            "mutation": plan["mutation"],
            "decisions": created_decisions,
        }
    except BaseException as exc:
        committed = bool(
            conn is not None and getattr(conn, "_authoritative_commit_completed", False)
        )
        if conn is not None and not committed:
            conn.rollback()
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if renamed and not committed and final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        if isinstance(exc, PclError):
            raise
        if isinstance(exc, (OSError, sqlite3.Error)):
            raise DataStoreError(f"Could not ingest Profile bundle: {exc}") from exc
        raise
    finally:
        if conn is not None:
            conn.close()


def _find_replay(paths: ProjectPaths, bundle: dict[str, Any]) -> dict[str, Any] | None:
    conn = connect(paths.db_path)
    try:
        return _find_replay_with_conn(paths, conn, bundle)
    finally:
        conn.close()


def _find_replay_with_conn(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    bundle: dict[str, Any],
) -> dict[str, Any] | None:
    rows = conn.execute(
        "SELECT id, path FROM evidence WHERE type = ? ORDER BY id",
        (PROFILE_OUTPUT_EVIDENCE_TYPE,),
    ).fetchall()
    for row in rows:
        path = paths.root / str(row["path"])
        try:
            manifest = load_strict_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        stored = manifest.get("bundle") if isinstance(manifest, dict) else None
        if not isinstance(stored, dict) or stored.get("bundle_id") != bundle.get("bundle_id"):
            continue
        if stored.get("bundle_digest") != bundle.get("bundle_digest", {}).get("value"):
            raise ProfileIngestError(
                message="Bundle ID already exists with a different digest.",
                code="profile_bundle_replay_conflict",
                exit_code=EXIT_USAGE,
                details={
                    "bundle_id": bundle.get("bundle_id"),
                    "evidence_id": row["id"],
                    "stored_digest": stored.get("bundle_digest"),
                    "supplied_digest": bundle.get("bundle_digest", {}).get("value"),
                },
            )
        event = conn.execute(
            """
            SELECT id FROM events
            WHERE event_type = 'profile_output_ingested'
              AND entity_type = 'evidence' AND entity_id = ?
            ORDER BY sequence LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        return {
            "ok": True,
            "changed": False,
            "idempotent": True,
            "evidence": {
                "id": row["id"],
                "type": PROFILE_OUTPUT_EVIDENCE_TYPE,
                "manifest_path": row["path"],
            },
            "event_id": None if event is None else event["id"],
            "bundle": stored,
            "decisions": manifest.get("decisions", []),
        }
    return None


def _staged_proposals(
    bundle: dict[str, Any],
    payload_dir: Path,
) -> list[dict[str, Any]]:
    if bundle.get("status") != "needs_human":
        return []
    by_id = {str(item["artifact_id"]): item for item in bundle["artifacts"]}
    result: list[dict[str, Any]] = []
    for artifact_id in bundle["decision_proposal_artifact_ids"]:
        artifact = by_id[str(artifact_id)]
        proposal = load_strict_json(payload_dir / str(artifact["path"]))
        if not isinstance(proposal, dict):
            raise ProfileIngestError(
                message="Decision proposal artifact is not an object.",
                code="profile_decision_proposal_invalid",
                exit_code=EXIT_USAGE,
                details={"artifact_id": artifact_id},
            )
        result.append({"artifact": artifact, "proposal": proposal})
    return result


def _copy_regular(source: Path, destination: Path) -> None:
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
        output_stream.flush()
        os.fsync(output_stream.fileno())


def assess_profile_output_evidence(
    paths: ProjectPaths,
    *,
    evidence_id: str,
    manifest_path_value: str,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    manifest_path = paths.root / manifest_path_value
    try:
        manifest = load_strict_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "health": "error",
            "findings": [{"code": "manifest_unreadable", "message": str(exc)}],
        }
    if not isinstance(manifest, dict):
        return {
            "health": "error",
            "findings": [{"code": "manifest_invalid", "message": "Manifest is not an object."}],
        }
    if manifest.get("contract_version") != PROFILE_OUTPUT_EVIDENCE_CONTRACT_VERSION:
        findings.append({"code": "contract_version_unsupported", "message": "Unexpected contract version."})
    if manifest.get("evidence_id") != evidence_id:
        findings.append({"code": "evidence_id_mismatch", "message": "Manifest Evidence ID differs."})
    if manifest.get("evidence_type") != PROFILE_OUTPUT_EVIDENCE_TYPE:
        findings.append({"code": "evidence_type_mismatch", "message": "Manifest Evidence type differs."})
    base = manifest_path.parent
    controls = []
    request = manifest.get("request")
    bundle = manifest.get("bundle")
    if isinstance(request, dict):
        controls.append(
            (
                str(request.get("stored_path") or ""),
                request.get("stored_size_bytes"),
                request.get("stored_sha256"),
                "request",
            )
        )
    if isinstance(bundle, dict):
        controls.append(
            (
                str(bundle.get("stored_manifest_path") or ""),
                bundle.get("stored_manifest_size_bytes"),
                bundle.get("stored_manifest_sha256"),
                "bundle_manifest",
            )
        )
    members = manifest.get("members")
    if not isinstance(members, list):
        findings.append({"code": "members_invalid", "message": "Members must be an array."})
        members = []
    for item in members:
        if not isinstance(item, dict):
            findings.append({"code": "member_invalid", "message": "Member is not an object."})
            continue
        controls.append(
            (
                str(item.get("storage_path") or ""),
                item.get("size_bytes"),
                item.get("sha256"),
                str(item.get("artifact_id") or "member"),
            )
        )
    for relative, expected_size, expected_hash, label in controls:
        path = base / relative
        try:
            safe = bool(relative) and not path.is_symlink() and path.resolve().is_relative_to(base.resolve())
            if not safe or not path.is_file():
                raise OSError("path is missing, non-regular, symlinked, or outside Evidence directory")
            if path.stat().st_size != expected_size:
                findings.append({"code": "stored_size_mismatch", "message": f"{label} size differs."})
                continue
            if _sha256_file(path) != expected_hash:
                findings.append({"code": "stored_hash_mismatch", "message": f"{label} hash differs."})
        except OSError as exc:
            findings.append({"code": "stored_file_unhealthy", "message": f"{label}: {exc}"})
    return {"health": "ok" if not findings else "error", "findings": findings}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_fsynced_json(path: Path, value: dict[str, Any]) -> None:
    data = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(data).digest():
        raise OSError("Evidence manifest verification failed")


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
