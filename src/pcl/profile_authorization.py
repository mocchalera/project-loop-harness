from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
import uuid

from .approval_provenance import (
    approval_provenance,
    resolve_actor_kind,
    resolve_recording_provenance,
)
from .contracts._profile_contract import canonical_json, load_strict_json, loads_strict_json
from .contracts.profile_run_request import (
    request_basis_digest,
    request_digest,
    validate_profile_run_request,
)
from .db import connect, connect_mutation
from .errors import DataStoreError, EXIT_USAGE, PclError
from .events import append_event
from .evidence import insert_evidence_link
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .profile_prepare import prepare_profile_request
from .timeutil import utc_now_iso


PROFILE_RUN_CANDIDATE_EVIDENCE_TYPE = "profile_run_candidate"
PROFILE_RUN_AUTHORIZED_EVENT = "profile_run_authorized"
PROFILE_AUTHORIZATION_REQUEST_MAX_BYTES = 2_000_000
_DATA_CLASS = {
    "none": "metadata",
    "selected_snippets": "selected_snippets",
    "full_allowed": "full_repository",
}


class ProfileAuthorizationError(PclError):
    pass


def authorize_profile_request(
    paths: ProjectPaths,
    *,
    request_file: str,
    output: str,
    actor: str,
    actor_kind: str | None,
    recorded_by: str | None,
    recorder_kind: str | None,
    source_kind: str | None,
    source_ref: str | None,
    reason: str,
    max_cost: float | None,
    currency: str | None,
    allowed_providers: list[str],
    data_classes: list[str],
    expires_at: str | None,
    now: str | None = None,
) -> dict[str, Any]:
    candidate_path = Path(request_file)
    if candidate_path.is_symlink() or not candidate_path.is_file():
        raise _error(
            "profile_authorization_candidate_invalid",
            "Candidate request must be a regular non-symlink file.",
        )
    if candidate_path.stat().st_size > PROFILE_AUTHORIZATION_REQUEST_MAX_BYTES:
        raise _error(
            "profile_authorization_candidate_size_limit",
            "Candidate request exceeds the local request size limit.",
        )
    _validate_output_path(paths, output)
    candidate_bytes = candidate_path.read_bytes()
    candidate = loads_strict_json(candidate_bytes)
    if not isinstance(candidate, dict):
        raise _error("profile_authorization_candidate_invalid", "Candidate request must be an object.")
    validation = validate_profile_run_request(candidate)
    if not validation.ok:
        raise _error(
            "profile_authorization_candidate_invalid",
            "Candidate request failed the frozen contract.",
            errors=list(validation.errors),
        )
    if candidate.get("authorization") is not None:
        raise _error(
            "profile_authorization_candidate_already_authorized",
            "Authorize an unapproved candidate request, not an authorized request.",
        )
    policy = candidate["data_policy"]
    if policy["network_access"] != "requested" and not policy["paid_service_requested"]:
        raise _error(
            "profile_authorization_not_required",
            "Offline non-paid requests do not require authorization.",
        )
    cleaned_reason = str(reason or "").strip()
    if not cleaned_reason:
        raise _error("profile_authorization_reason_required", "--reason is required.")
    if not str(source_kind or "").strip() or not str(source_ref or "").strip():
        raise _error(
            "profile_authorization_source_required",
            "--source-kind and --source-ref are required.",
        )
    resolved_actor_kind = resolve_actor_kind(actor=actor, actor_kind=actor_kind)
    if resolved_actor_kind != "human":
        raise _error(
            "profile_authorization_human_required",
            "Only a human actor can authorize network or paid Profile execution.",
        )
    recording = resolve_recording_provenance(
        actor=actor,
        actor_kind=resolved_actor_kind,
        recorded_by=recorded_by,
        recorder_kind=recorder_kind,
        source_kind=source_kind,
        source_ref=source_ref,
        command="pcl profile authorize",
    )
    timestamp = now or utc_now_iso()
    scope = _validated_scope(
        candidate,
        max_cost=max_cost,
        currency=currency,
        allowed_providers=allowed_providers,
        data_classes=data_classes,
        expires_at=expires_at,
        now=timestamp,
    )
    expected_basis = _fresh_candidate_basis(paths, candidate, now=timestamp)
    if expected_basis != candidate["request_basis_digest"]["value"]:
        raise _error(
            "profile_authorization_stale_basis",
            "Candidate request basis is stale against current Project Loop state.",
            candidate_basis=candidate["request_basis_digest"]["value"],
            current_basis=expected_basis,
        )
    candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
    replay = _authorization_replay(
        paths,
        candidate_basis=expected_basis,
        actor=actor,
        scope=scope,
        output=output,
        now=timestamp,
    )
    if replay is not None:
        return replay

    directory = paths.evidence_dir / "profile-authorizations"
    directory.mkdir(parents=True, exist_ok=True)
    conn = connect_mutation(paths)
    final_path: Path | None = None
    tmp_path: Path | None = None
    try:
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        event_id = f"EV-{uuid.uuid4().hex[:12].upper()}"
        receipt = approval_provenance(
            action=PROFILE_RUN_AUTHORIZED_EVENT,
            actor_kind=resolved_actor_kind,
            actor=actor,
            source=recording["source"],
            source_kind=recording["source_kind"],
            source_ref=recording["source_ref"],
            recorder_kind=recording["recorder_kind"],
            recorder=recording["recorder"],
            timestamp=timestamp,
            target=candidate["target"],
            evidence_id=evidence_id,
            artifact_sha256=candidate_sha,
            reason=cleaned_reason,
        )
        receipt.update(
            {
                "event_id": event_id,
                "request_basis_digest": expected_basis,
                "scope": scope,
            }
        )
        authorized = _authorized_request(candidate, receipt)
        final_path = directory / f"{evidence_id.lower()}-profile-run-candidate.json"
        fd, tmp_value = tempfile.mkstemp(prefix=f".{evidence_id}.", suffix=".tmp", dir=directory)
        tmp_path = Path(tmp_value)
        with os.fdopen(fd, "wb") as stream:
            stream.write(candidate_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(tmp_path.read_bytes()).hexdigest() != candidate_sha:
            raise OSError("Candidate Evidence copy hash mismatch")
        os.replace(tmp_path, final_path)
        relative = str(final_path.relative_to(paths.root))
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at, linked_task_id)
            VALUES (?, ?, ?, 'pcl profile authorize', ?, ?, ?)
            """,
            (
                evidence_id,
                PROFILE_RUN_CANDIDATE_EVIDENCE_TYPE,
                relative,
                cleaned_reason,
                timestamp,
                candidate["target"]["id"] if candidate["target"]["type"] == "task" else None,
            ),
        )
        insert_evidence_link(
            conn,
            evidence_id=evidence_id,
            target_type=candidate["target"]["type"],
            target_id=candidate["target"]["id"],
            link_role="profile_authorization_candidate",
            created_at=timestamp,
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=PROFILE_RUN_AUTHORIZED_EVENT,
            entity_type="evidence",
            entity_id=evidence_id,
            event_id=event_id,
            payload={
                "contract_version": "profile-run-authorized/v1",
                "candidate_evidence_id": evidence_id,
                "candidate_path": relative,
                "candidate_sha256": candidate_sha,
                "request_id": candidate["request_id"],
                "request_basis_digest": expected_basis,
                "authorization": receipt,
            },
        )
        conn.commit()
        _write_authorized_output(paths, output, authorized)
        return {
            "ok": True,
            "changed": True,
            "replayed": False,
            "runner_executed": False,
            "evidence_id": evidence_id,
            "event_id": event_id,
            "output_path": str(Path(output)),
            "request": authorized,
        }
    except BaseException as exc:
        committed = bool(getattr(conn, "_authoritative_commit_completed", False))
        if not committed:
            conn.rollback()
            if final_path and final_path.exists():
                final_path.unlink(missing_ok=True)
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        if isinstance(exc, PclError):
            raise
        if isinstance(exc, (OSError, sqlite3.Error)):
            raise DataStoreError(f"Could not authorize Profile request: {exc}") from exc
        raise
    finally:
        conn.close()


def authorization_findings(
    paths: ProjectPaths,
    request: dict[str, Any],
    *,
    now: str | None = None,
) -> list[dict[str, str]]:
    authorization = request.get("authorization")
    if not isinstance(authorization, dict):
        return []
    findings: list[dict[str, str]] = []
    timestamp = now or utc_now_iso()
    expires = authorization.get("scope", {}).get("expires_at")
    if expires is not None and _parse_time(str(expires)) <= _parse_time(timestamp):
        findings.append({"code": "profile_authorization_expired", "message": "Authorization expired."})
    evidence_ref = authorization.get("bound_evidence", {})
    evidence_id = str(evidence_ref.get("id") or "")
    conn = connect(paths.db_path)
    try:
        evidence = conn.execute(
            "SELECT type, path FROM evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        event = conn.execute(
            "SELECT payload_json FROM events WHERE id = ? AND event_type = ?",
            (authorization.get("event_id"), PROFILE_RUN_AUTHORIZED_EVENT),
        ).fetchone()
        revoked = conn.execute(
            """
            SELECT 1 FROM events
            WHERE event_type = 'profile_authorization_revoked'
              AND json_extract(payload_json, '$.authorized_event_id') = ?
            LIMIT 1
            """,
            (authorization.get("event_id"),),
        ).fetchone()
    finally:
        conn.close()
    if evidence is None or evidence["type"] != PROFILE_RUN_CANDIDATE_EVIDENCE_TYPE:
        findings.append({"code": "profile_authorization_evidence_missing", "message": "Candidate Evidence is missing."})
    else:
        path = paths.root / str(evidence["path"])
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            actual = ""
        if actual != evidence_ref.get("artifact_sha256"):
            findings.append({"code": "profile_authorization_evidence_hash_mismatch", "message": "Candidate Evidence hash differs."})
    if event is None:
        findings.append({"code": "profile_authorization_event_missing", "message": "Authorization event is missing."})
    else:
        payload = json.loads(str(event["payload_json"]))
        if payload.get("authorization") != authorization:
            findings.append({"code": "profile_authorization_event_mismatch", "message": "Embedded receipt differs from its event."})
    if revoked is not None:
        findings.append({"code": "profile_authorization_revoked", "message": "Authorization was revoked."})
    try:
        current_basis = _fresh_candidate_basis(paths, _candidate_from_authorized(request), now=timestamp)
    except PclError:
        current_basis = ""
    if current_basis != request.get("request_basis_digest", {}).get("value"):
        findings.append({"code": "profile_authorization_stale_basis", "message": "Authorization basis is stale."})
    return findings


def _fresh_candidate_basis(paths: ProjectPaths, candidate: dict[str, Any], *, now: str) -> str:
    prepared = prepare_profile_request(
        paths,
        runner_profile_id=candidate["profile"]["runner_profile_id"],
        target_ref=f"{candidate['target']['type']}:{candidate['target']['id']}",
        brief_id=candidate["work_brief"]["evidence_id"],
        now=now,
        network_access=candidate["data_policy"]["network_access"],
        paid_service_requested=candidate["data_policy"]["paid_service_requested"],
        allowed_providers=candidate["data_policy"]["allowed_providers"],
        repository_content_policy=candidate["data_policy"]["repository_content_policy"],
        monetary_budget=candidate["limits"]["monetary_budget"],
        currency=candidate["limits"]["currency"],
    )["request"]
    return str(prepared["request_basis_digest"]["value"])


def _validated_scope(
    candidate: dict[str, Any],
    *,
    max_cost: float | None,
    currency: str | None,
    allowed_providers: list[str],
    data_classes: list[str],
    expires_at: str | None,
    now: str,
) -> dict[str, Any]:
    providers = sorted(set(allowed_providers))
    classes = sorted(set(data_classes))
    requested = set(candidate["data_policy"]["allowed_providers"])
    if not requested.issubset(providers):
        raise _error("profile_authorization_provider_scope", "Authorization omits requested providers.")
    required_class = _DATA_CLASS[candidate["data_policy"]["repository_content_policy"]]
    if required_class not in classes:
        raise _error("profile_authorization_data_scope", "Authorization omits the requested data class.")
    budget = candidate["limits"]["monetary_budget"]
    if candidate["data_policy"]["paid_service_requested"]:
        if max_cost is None or budget is None or max_cost < budget:
            raise _error("profile_authorization_cost_scope", "Authorization cost cap is below the request budget.")
        if currency != candidate["limits"]["currency"]:
            raise _error("profile_authorization_currency_scope", "Authorization currency differs from the request.")
    if expires_at is not None and _parse_time(expires_at) <= _parse_time(now):
        raise _error("profile_authorization_expired", "Authorization expiry must be in the future.")
    return {
        "max_cost": max_cost,
        "currency": currency,
        "allowed_providers": providers,
        "data_classes": classes,
        "expires_at": expires_at,
        "revoked_event_id": None,
    }


def _authorized_request(candidate: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(canonical_json(candidate))
    value["authorization"] = receipt
    value["request_digest"]["value"] = request_digest(value)
    validation = validate_profile_run_request(value)
    if not validation.ok:
        raise _error(
            "profile_authorized_request_invalid",
            "Authorized request failed the frozen contract.",
            errors=list(validation.errors),
        )
    if request_basis_digest(value) != candidate["request_basis_digest"]["value"]:
        raise _error("profile_authorization_basis_mismatch", "Authorization changed the request basis.")
    return value


def _candidate_from_authorized(request: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(canonical_json(request))
    value["authorization"] = None
    value["request_digest"]["value"] = request_digest(value)
    return value


def _authorization_replay(
    paths: ProjectPaths,
    *,
    candidate_basis: str,
    actor: str,
    scope: dict[str, Any],
    output: str,
    now: str,
) -> dict[str, Any] | None:
    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            "SELECT id, entity_id, payload_json FROM events WHERE event_type = ? ORDER BY sequence",
            (PROFILE_RUN_AUTHORIZED_EVENT,),
        ).fetchall()
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            receipt = payload.get("authorization")
            if not isinstance(receipt, dict):
                continue
            if (
                receipt.get("request_basis_digest") != candidate_basis
                or receipt.get("actor") != actor
                or receipt.get("scope") != scope
            ):
                continue
            if receipt.get("scope", {}).get("expires_at") is not None and _parse_time(
                receipt["scope"]["expires_at"]
            ) <= _parse_time(now):
                continue
            revoked = conn.execute(
                """
                SELECT 1 FROM events WHERE event_type = 'profile_authorization_revoked'
                  AND json_extract(payload_json, '$.authorized_event_id') = ? LIMIT 1
                """,
                (row["id"],),
            ).fetchone()
            if revoked is not None:
                continue
            evidence = conn.execute(
                "SELECT path FROM evidence WHERE id = ? AND type = ?",
                (row["entity_id"], PROFILE_RUN_CANDIDATE_EVIDENCE_TYPE),
            ).fetchone()
            if evidence is None:
                continue
            candidate = load_strict_json(paths.root / str(evidence["path"]))
            authorized = _authorized_request(candidate, receipt)
            _write_authorized_output(paths, output, authorized)
            return {
                "ok": True,
                "changed": False,
                "replayed": True,
                "runner_executed": False,
                "evidence_id": row["entity_id"],
                "event_id": row["id"],
                "output_path": str(Path(output)),
                "request": authorized,
            }
    finally:
        conn.close()
    return None


def _write_authorized_output(paths: ProjectPaths, output: str, value: dict[str, Any]) -> None:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _validate_output_path(paths, output)
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, temp_value = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temp = Path(temp_value)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def _validate_output_path(paths: ProjectPaths, output: str) -> None:
    destination = Path(output)
    resolved = destination.resolve(strict=False)
    if resolved.is_relative_to(paths.loop_dir.resolve()) or destination.is_symlink():
        raise _error(
            "profile_authorization_output_unsafe",
            "Authorized output cannot target .project-loop or a symlink.",
        )


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error("profile_authorization_time_invalid", f"Invalid date-time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _error(code: str, message: str, **details: Any) -> ProfileAuthorizationError:
    return ProfileAuthorizationError(
        message=message,
        code=code,
        exit_code=EXIT_USAGE,
        details=details,
    )
