from __future__ import annotations

from collections.abc import Mapping, Sequence
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Any

from .contracts.authority_surface import (
    AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION,
    RISK_LEVELS,
    VERIFICATION_DEPTHS,
    authority_document_diff,
    authority_document_sha256,
    merge_authority_canaries,
    merge_authority_catalogs,
    validate_authority_canary,
    validate_authority_catalog,
    validate_authority_surface_resolution,
    validate_bootstrap_authority_profile,
)
from .errors import PclError
from .db import connect_read_only
from .paths import ProjectPaths
from .project_config import trusted_integration_head_oid


_RISK_RANK = {value: index for index, value in enumerate(RISK_LEVELS)}
_DEPTH_RANK = {value: index for index, value in enumerate(VERIFICATION_DEPTHS)}
_RISK_DEPTH = {
    "R0": "basic",
    "R1": "standard",
    "R2": "independent",
    "R3": "independent",
    "R4": "human",
}
_TRUSTED_RESOLVER_SOURCES = {"trusted_base", "pinned_installed", "external_bootstrap"}
_OID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_DIFF_MODE = re.compile(r"^(?:000000|100644|100755|120000|160000)$")
_DIFF_STATUS = re.compile(r"^[ADMTUXB]$")
_EXECUTABLE_SUFFIXES = {
    ".bash",
    ".c",
    ".cc",
    ".cmd",
    ".cpp",
    ".csh",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".mjs",
    ".php",
    ".pl",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
    ".zsh",
}


class AuthoritySurfaceError(PclError):
    pass


def resolve_authority_surface(
    *,
    target: Mapping[str, str],
    candidate: Mapping[str, str],
    base_resolution: Mapping[str, Any],
    actual_diff: Mapping[str, Any],
    existing_route_risk: str,
    existing_adaptive_depth: str,
    trusted_base_floor: str,
    reviewer_escalation: Mapping[str, str],
    packaged_catalog: Mapping[str, Any],
    base_catalog: Mapping[str, Any],
    candidate_catalog: Mapping[str, Any],
    base_canary: Mapping[str, Any],
    candidate_canary: Mapping[str, Any],
    resolver: Mapping[str, str],
    bootstrap_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve C1 authority without lifecycle, Evidence, or persistence authority."""

    _require_target(target)
    _require_candidate(candidate)
    _require_base_resolution(base_resolution)
    _require_actual_diff(actual_diff)
    _require_risk(existing_route_risk, "existing_route_risk")
    _require_depth(existing_adaptive_depth, "existing_adaptive_depth")
    _require_risk(trusted_base_floor, "trusted_base_floor")
    reviewer_risk = str(reviewer_escalation.get("risk_level", ""))
    reviewer_depth = str(reviewer_escalation.get("verification_depth", ""))
    _require_risk(reviewer_risk, "reviewer_escalation.risk_level")
    _require_depth(reviewer_depth, "reviewer_escalation.verification_depth")
    _require_resolver(resolver)

    profile_validation = validate_bootstrap_authority_profile(bootstrap_profile)
    if not profile_validation.ok:
        raise _error(
            "bootstrap_authority_profile_invalid",
            "The external bootstrap authority profile is invalid.",
            errors=list(profile_validation.errors),
        )
    if packaged_catalog != bootstrap_profile["authority_catalog"]:
        raise _error(
            "bootstrap_authority_catalog_mismatch",
            "The packaged minimum catalog does not match the frozen bootstrap profile.",
            expected=authority_document_sha256(bootstrap_profile["authority_catalog"]),
            actual=authority_document_sha256(packaged_catalog),
        )
    for label, catalog in (
        ("packaged", packaged_catalog),
        ("base", base_catalog),
        ("candidate", candidate_catalog),
    ):
        validation = validate_authority_catalog(catalog)
        if not validation.ok:
            raise _error(
                "authority_catalog_invalid",
                f"The {label} authority catalog is invalid.",
                catalog=label,
                errors=list(validation.errors),
            )
    for label, canary in (("base", base_canary), ("candidate", candidate_canary)):
        validation = validate_authority_canary(canary)
        if not validation.ok:
            raise _error(
                "authority_canary_invalid",
                f"The {label} authority canary is invalid.",
                canary=label,
                errors=list(validation.errors),
            )

    try:
        catalog_union = merge_authority_catalogs(
            packaged_catalog,
            base_catalog,
            candidate_catalog,
        )
        trusted_canary = merge_authority_canaries(
            bootstrap_profile["canary_contract"],
            base_canary,
        )
        canary_union = merge_authority_canaries(trusted_canary, candidate_canary)
    except ValueError as exc:
        code = (
            "authority_canary_conflict"
            if "canary" in str(exc)
            else "authority_catalog_conflict"
        )
        raise _error(code, "Candidate authority input weakens a trusted requirement.", reason=str(exc)) from exc

    paths = [str(entry["path"]) for entry in actual_diff["entries"]]
    executable_mode_paths = {
        str(entry["path"])
        for entry in actual_diff["entries"]
        if _mode_is_executable(str(entry["old_mode"]))
        or _mode_is_executable(str(entry["new_mode"]))
    }
    packaged_floor, packaged_matches, packaged_unknown = _catalog_floor(
        packaged_catalog,
        paths,
        classify_unknown=True,
        executable_mode_paths=executable_mode_paths,
    )
    base_floor, base_matches, _ = _catalog_floor(base_catalog, paths)
    candidate_floor, candidate_matches, _ = _catalog_floor(candidate_catalog, paths)
    union_floor, union_matches, union_unknown = _catalog_floor(
        catalog_union,
        paths,
        classify_unknown=True,
        executable_mode_paths=executable_mode_paths,
    )
    base_state_floor = (
        "R0" if base_resolution["status"] == "resolved" else "R2"
    )
    effective_risk = _max_risk(
        existing_route_risk,
        trusted_base_floor,
        packaged_floor,
        base_floor,
        candidate_floor,
        union_floor,
        reviewer_risk,
        base_state_floor,
    )
    effective_depth = _max_depth(
        existing_adaptive_depth,
        reviewer_depth,
        _RISK_DEPTH[effective_risk],
    )
    human_gate_required = effective_risk in {"R3", "R4"} or effective_depth == "human"
    reuse_allowed = (
        bool(base_resolution["reuse_allowed"])
        and effective_risk == "R2"
        and not human_gate_required
    )

    catalog_diff = authority_document_diff(base_catalog, candidate_catalog)
    canary_diff = authority_document_diff(base_canary, candidate_canary)
    reason_codes = set(str(item) for item in base_resolution["reason_codes"])
    reason_codes.update(packaged_unknown)
    reason_codes.update(union_unknown)
    reason_codes.update(f"catalog:{item}" for item in union_matches)
    if effective_risk == "R3":
        reason_codes.add("human_gate_r3")
    elif effective_risk == "R4":
        reason_codes.add("human_gate_r4")
    if effective_depth == "human":
        reason_codes.add("human_verification_preserved")

    resolution = {
        "contract_version": AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION,
        "target": {"type": str(target["type"]), "id": str(target["id"])},
        "base": dict(base_resolution),
        "candidate": {
            "commit_oid": str(candidate["commit_oid"]),
            "tree_oid": str(candidate["tree_oid"]),
        },
        "actual_diff": {
            "sha256": str(actual_diff["sha256"]),
            "entries": [dict(entry) for entry in actual_diff["entries"]],
        },
        "inputs": {
            "existing_route_risk": existing_route_risk,
            "existing_adaptive_depth": existing_adaptive_depth,
            "trusted_base_floor": trusted_base_floor,
            "packaged_catalog_floor": packaged_floor,
            "base_catalog_floor": base_floor,
            "candidate_catalog_floor": candidate_floor,
            "reviewer_escalation": {
                "risk_level": reviewer_risk,
                "verification_depth": reviewer_depth,
            },
            "base_state_floor": base_state_floor,
        },
        "catalog": {
            "packaged_minimum_sha256": authority_document_sha256(packaged_catalog),
            "base_sha256": catalog_diff["base_sha256"],
            "candidate_sha256": catalog_diff["candidate_sha256"],
            "union_sha256": authority_document_sha256(catalog_union),
            "diff_sha256": authority_document_sha256(catalog_diff),
            "base_matched_rule_ids": base_matches,
            "candidate_matched_rule_ids": candidate_matches,
            "packaged_matched_rule_ids": packaged_matches,
            "union_matched_rule_ids": union_matches,
        },
        "canary": {
            "packaged_minimum_sha256": authority_document_sha256(
                bootstrap_profile["canary_contract"]
            ),
            "base_sha256": canary_diff["base_sha256"],
            "candidate_sha256": canary_diff["candidate_sha256"],
            "union_sha256": authority_document_sha256(canary_union),
            "diff_sha256": authority_document_sha256(canary_diff),
        },
        "resolver": {
            "version": str(resolver["version"]),
            "sha256": str(resolver["sha256"]),
            "source": str(resolver["source"]),
            "candidate_controlled": False,
        },
        "bootstrap_profile": {
            "contract_version": str(bootstrap_profile["contract_version"]),
            "profile_id": str(bootstrap_profile["profile_id"]),
            "sha256": authority_document_sha256(bootstrap_profile),
            "exact_candidate_full_regression_required": True,
            "fixed_hash_independent_review_required": True,
            "self_certification_allowed": False,
            "approval_claimed": False,
        },
        "effective": {
            "risk_level": effective_risk,
            "verification_depth": effective_depth,
            "human_gate_required": human_gate_required,
            "reuse_allowed": reuse_allowed,
            "reason_codes": sorted(reason_codes),
        },
        "terminal_authority": False,
        "mandatory_evidence": False,
    }
    validation = validate_authority_surface_resolution(resolution)
    if not validation.ok:
        raise _error(
            "authority_surface_resolution_invalid",
            "Generated authority resolution failed its contract.",
            errors=list(validation.errors),
        )
    return resolution


def load_task_start_events(conn: sqlite3.Connection, task_id: str) -> list[dict[str, str]]:
    """Read every task-scoped work_started anchor; never use a bounded history scan."""

    rows = conn.execute(
        """
        SELECT id, payload_json
        FROM events
        WHERE event_type = 'work_started'
          AND entity_type = 'task'
          AND entity_id = ?
        ORDER BY sequence, id
        """,
        (task_id,),
    ).fetchall()
    return [{"id": str(row["id"]), "payload_json": str(row["payload_json"])} for row in rows]


def derive_trusted_base_for_task(
    paths: ProjectPaths,
    *,
    task_id: str,
    candidate_commit_oid: str,
    caller_base_oid: str | None = None,
) -> dict[str, Any]:
    """Load the append-only task-start authority and optional trusted config read-only."""

    conn = connect_read_only(paths.db_path)
    try:
        events = load_task_start_events(conn, task_id)
    finally:
        conn.close()
    return derive_trusted_base(
        paths.root,
        candidate_commit_oid=candidate_commit_oid,
        work_started_events=events,
        trusted_integration_head_oid=trusted_integration_head_oid(paths.root),
        caller_base_oid=caller_base_oid,
    )


def derive_trusted_base(
    root: Path,
    *,
    candidate_commit_oid: str,
    work_started_events: Sequence[Mapping[str, Any]],
    trusted_integration_head_oid: str | None,
    caller_base_oid: str | None = None,
) -> dict[str, Any]:
    """Derive the comparison base without allowing the caller to select it."""

    candidate = _resolve_full_commit(root, candidate_commit_oid, code="authority_candidate_invalid")
    if work_started_events:
        derived = _base_from_task_start(root, candidate, work_started_events)
    else:
        derived = _base_from_integration_head(root, candidate, trusted_integration_head_oid)

    if caller_base_oid is not None:
        asserted = _resolve_full_commit(
            root,
            caller_base_oid,
            code="authority_base_assertion_invalid",
        )
        if derived["commit_oid"] is None:
            raise _error(
                "authority_base_assertion_unverifiable",
                "Caller base assertion cannot establish an unknown trusted base.",
                asserted=asserted,
            )
        if asserted != derived["commit_oid"]:
            raise _error(
                "authority_base_assertion_mismatch",
                "Caller base assertion does not equal the derived trusted base.",
                asserted=asserted,
                derived=derived["commit_oid"],
            )
    return derived


def canonical_git_diff(
    root: Path,
    *,
    base_commit_oid: str,
    candidate_commit_oid: str,
) -> dict[str, Any]:
    base = _resolve_full_commit(root, base_commit_oid, code="authority_base_invalid")
    candidate = _resolve_full_commit(root, candidate_commit_oid, code="authority_candidate_invalid")
    if not _is_ancestor(root, base, candidate):
        raise _error(
            "authority_base_nonancestor",
            "The authority comparison base is not an ancestor of the candidate.",
            base=base,
            candidate=candidate,
        )
    raw = _git_bytes(
        root,
        "diff",
        "--raw",
        "--no-abbrev",
        "--no-renames",
        "-z",
        base,
        candidate,
        "--",
    )
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise _error(
            "authority_diff_invalid",
            "Git returned an incomplete raw diff record.",
        )
    entries: list[dict[str, str]] = []
    for index in range(0, len(fields), 2):
        try:
            header = fields[index].decode("ascii")
            path = fields[index + 1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _error(
                "authority_diff_path_invalid",
                "Git diff paths must be valid UTF-8 for the C1 contract.",
            ) from exc
        parts = header.removeprefix(":").split()
        if len(parts) != 5 or not header.startswith(":"):
            raise _error(
                "authority_diff_invalid",
                "Git returned an unsupported raw diff record.",
                header=header,
            )
        old_mode, new_mode, old_oid, new_oid, status = parts
        entries.append(
            {
                "old_mode": old_mode,
                "new_mode": new_mode,
                "old_oid": old_oid,
                "new_oid": new_oid,
                "status": status,
                "path": path,
            }
        )
    entries.sort(key=lambda item: (item["path"], item["status"]))
    digest = hashlib.sha256(
        json.dumps(
            entries,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {"sha256": "sha256:" + digest, "entries": entries}


def _base_from_task_start(
    root: Path,
    candidate: str,
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(events) != 1:
        return _unknown_base("task_start_ambiguous")
    event = events[0]
    if not isinstance(event.get("id"), str) or not event["id"]:
        return _unknown_base("task_start_invalid")
    try:
        payload = event.get("payload")
        if payload is None:
            payload = json.loads(str(event["payload_json"]))
        revision = payload["receipt"]["repository_revision"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return _unknown_base("task_start_invalid")
    if not isinstance(revision, str):
        return _unknown_base("task_start_invalid")
    try:
        base = _resolve_full_commit(root, revision, code="authority_task_start_invalid")
    except AuthoritySurfaceError:
        return _unknown_base("task_start_invalid")
    if not _is_ancestor(root, base, candidate):
        return _unknown_base("task_start_nonancestor")
    return _resolved_base(
        base,
        candidate,
        derivation="task_start_event",
        source_ref=str(event.get("id", "")),
        reason="task_start_ancestor",
    )


def _base_from_integration_head(
    root: Path,
    candidate: str,
    integration_head: str | None,
) -> dict[str, Any]:
    if integration_head is None:
        return _unknown_base("trusted_integration_head_missing")
    try:
        integration = _resolve_full_commit(
            root,
            integration_head,
            code="authority_integration_head_invalid",
        )
        output = _git_text(root, "merge-base", "--all", candidate, integration)
    except AuthoritySurfaceError:
        return _unknown_base("trusted_integration_head_invalid")
    bases = [line for line in output.splitlines() if line]
    if len(bases) != 1 or _OID.fullmatch(bases[0]) is None:
        return _unknown_base("integration_merge_base_ambiguous")
    base = bases[0]
    if not _is_ancestor(root, base, candidate):
        return _unknown_base("integration_merge_base_nonancestor")
    return _resolved_base(
        base,
        candidate,
        derivation="integration_merge_base",
        source_ref=integration,
        reason="integration_merge_base_ancestor",
    )


def _resolved_base(
    base: str,
    candidate: str,
    *,
    derivation: str,
    source_ref: str,
    reason: str,
) -> dict[str, Any]:
    if base == candidate:
        return {
            "status": "no_candidate_change",
            "derivation": derivation,
            "commit_oid": base,
            "source_ref": source_ref,
            "ancestry_result": "same_as_candidate",
            "reuse_allowed": False,
            "reason_codes": ["no_candidate_change"],
        }
    return {
        "status": "resolved",
        "derivation": derivation,
        "commit_oid": base,
        "source_ref": source_ref,
        "ancestry_result": "ancestor",
        "reuse_allowed": True,
        "reason_codes": [reason],
    }


def _unknown_base(reason: str) -> dict[str, Any]:
    return {
        "status": "base_unknown",
        "derivation": "base_unknown",
        "commit_oid": None,
        "source_ref": None,
        "ancestry_result": "unknown",
        "reuse_allowed": False,
        "reason_codes": [reason],
    }


def _catalog_floor(
    catalog: Mapping[str, Any],
    paths: Sequence[str],
    *,
    classify_unknown: bool = False,
    executable_mode_paths: set[str] | None = None,
) -> tuple[str, list[str], list[str]]:
    risk = "R0"
    matches: set[str] = set()
    unknown_reasons: set[str] = set()
    for path in paths:
        normalized = _normalize_path(path)
        path_matched = False
        explicitly_non_executable = False
        for rule in catalog["rules"]:
            if any(fnmatch.fnmatchcase(normalized, str(pattern)) for pattern in rule["patterns"]):
                path_matched = True
                matches.add(str(rule["id"]))
                risk = _max_risk(risk, str(rule["minimum_risk"]))
                if rule.get("path_class") == "non_executable":
                    explicitly_non_executable = True
        executable = _looks_executable(normalized) or normalized in (
            executable_mode_paths or set()
        )
        if classify_unknown and not path_matched:
            risk = _max_risk(risk, "R2")
            unknown_reasons.add(
                "unknown_executable_path" if executable else "unknown_path"
            )
        elif classify_unknown and executable and explicitly_non_executable:
            risk = _max_risk(risk, "R2")
            unknown_reasons.add("non_executable_classification_conflict")
    return risk, sorted(matches), sorted(unknown_reasons)


def _looks_executable(path: str) -> bool:
    return Path(path).suffix.casefold() in _EXECUTABLE_SUFFIXES or path.startswith(
        ("bin/", "scripts/", "tools/")
    )


def _mode_is_executable(mode: str) -> bool:
    try:
        return bool(int(mode, 8) & 0o111)
    except ValueError:
        return False


def _normalize_path(value: str) -> str:
    path = value.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return re.sub(r"/+", "/", path).strip("/")


def _max_risk(*values: str) -> str:
    return max(values, key=_RISK_RANK.__getitem__)


def _max_depth(*values: str) -> str:
    return max(values, key=_DEPTH_RANK.__getitem__)


def _require_target(target: Mapping[str, str]) -> None:
    if set(target) != {"type", "id"} or target.get("type") != "task" or not target.get("id"):
        raise _error(
            "authority_target_invalid",
            "C1 authority resolution requires an exact Task target.",
            target=dict(target),
        )


def _require_candidate(candidate: Mapping[str, str]) -> None:
    if set(candidate) != {"commit_oid", "tree_oid"}:
        raise _error(
            "authority_candidate_invalid",
            "Candidate must bind commit_oid and tree_oid.",
        )
    for field in ("commit_oid", "tree_oid"):
        value = candidate.get(field)
        if not isinstance(value, str) or _OID.fullmatch(value) is None:
            raise _error(
                "authority_candidate_invalid",
                f"Candidate {field} must be a full Git OID.",
                field=field,
            )


def _require_base_resolution(base: Mapping[str, Any]) -> None:
    required = {
        "status",
        "derivation",
        "commit_oid",
        "source_ref",
        "ancestry_result",
        "reuse_allowed",
        "reason_codes",
    }
    if set(base) != required:
        raise _error("authority_base_invalid", "Trusted base resolution has an unsupported shape.")
    status = base.get("status")
    if status not in {"resolved", "base_unknown", "no_candidate_change"}:
        raise _error("authority_base_invalid", "Trusted base resolution is invalid.")
    if not isinstance(base.get("reuse_allowed"), bool) or not isinstance(
        base.get("reason_codes"), list
    ):
        raise _error("authority_base_invalid", "Trusted base resolution is incomplete.")
    reason_codes = base["reason_codes"]
    if (
        not reason_codes
        or any(not isinstance(item, str) or not item for item in reason_codes)
        or reason_codes != sorted(set(reason_codes))
    ):
        raise _error("authority_base_invalid", "Trusted base reason codes are invalid.")
    if status == "base_unknown":
        expected = {
            "derivation": "base_unknown",
            "commit_oid": None,
            "source_ref": None,
            "ancestry_result": "unknown",
            "reuse_allowed": False,
        }
    else:
        expected = {
            "derivation": base.get("derivation"),
            "commit_oid": base.get("commit_oid"),
            "source_ref": base.get("source_ref"),
            "ancestry_result": (
                "ancestor" if status == "resolved" else "same_as_candidate"
            ),
            "reuse_allowed": status == "resolved",
        }
        if expected["derivation"] not in {"task_start_event", "integration_merge_base"}:
            raise _error("authority_base_invalid", "Trusted base derivation is invalid.")
        if (
            not isinstance(expected["commit_oid"], str)
            or _OID.fullmatch(expected["commit_oid"]) is None
            or not isinstance(expected["source_ref"], str)
            or not expected["source_ref"]
        ):
            raise _error("authority_base_invalid", "Trusted base identity is invalid.")
    if any(base[field] != value for field, value in expected.items()):
        raise _error("authority_base_invalid", "Trusted base state is internally inconsistent.")


def _require_actual_diff(actual_diff: Mapping[str, Any]) -> None:
    digest = actual_diff.get("sha256")
    entries = actual_diff.get("entries")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise _error("authority_diff_invalid", "Actual diff must bind a sha256 digest.")
    if not isinstance(entries, list):
        raise _error("authority_diff_invalid", "Actual diff entries must be an array.")
    required = {"old_mode", "new_mode", "old_oid", "new_oid", "status", "path"}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != required:
            raise _error(
                "authority_diff_invalid",
                "Actual diff entry has an unsupported shape.",
                index=index,
            )
        if not isinstance(entry["path"], str) or not entry["path"]:
            raise _error(
                "authority_diff_invalid",
                "Actual diff entry path must be non-empty.",
                index=index,
            )
        if entry["path"] != _normalize_path(entry["path"]) or any(
            part in {"", ".", ".."} for part in entry["path"].split("/")
        ):
            raise _error(
                "authority_diff_invalid",
                "Actual diff entry path must be normalized and project-relative.",
                index=index,
            )
        for field in ("old_mode", "new_mode"):
            if not isinstance(entry[field], str) or _DIFF_MODE.fullmatch(entry[field]) is None:
                raise _error(
                    "authority_diff_invalid",
                    "Actual diff entry contains an unsupported Git mode.",
                    index=index,
                    field=field,
                )
        for field in ("old_oid", "new_oid"):
            if not isinstance(entry[field], str) or _OID.fullmatch(entry[field]) is None:
                raise _error(
                    "authority_diff_invalid",
                    "Actual diff entry contains an invalid full Git OID.",
                    index=index,
                    field=field,
                )
        if not isinstance(entry["status"], str) or _DIFF_STATUS.fullmatch(entry["status"]) is None:
            raise _error(
                "authority_diff_invalid",
                "Actual diff entry contains an unsupported Git status.",
                index=index,
            )
    if entries != sorted(entries, key=lambda item: (item["path"], item["status"])):
        raise _error("authority_diff_invalid", "Actual diff entries must be canonically sorted.")
    expected = _diff_entries_sha256(entries)
    if digest != expected:
        raise _error(
            "authority_diff_digest_mismatch",
            "Actual diff entries do not match their bound digest.",
            expected=expected,
            actual=digest,
        )


def _require_resolver(resolver: Mapping[str, str]) -> None:
    if set(resolver) != {"version", "sha256", "source"}:
        raise _error("authority_resolver_invalid", "Resolver identity is incomplete.")
    if resolver["source"] not in _TRUSTED_RESOLVER_SOURCES:
        raise _error(
            "authority_resolver_untrusted",
            "Candidate-controlled resolver code cannot certify authority.",
            source=resolver["source"],
        )
    if not resolver["version"] or _SHA256.fullmatch(resolver["sha256"]) is None:
        raise _error("authority_resolver_invalid", "Resolver identity is invalid.")


def _require_risk(value: str, field: str) -> None:
    if value not in _RISK_RANK:
        raise _error("authority_risk_invalid", f"{field} has an unsupported risk level.")


def _require_depth(value: str, field: str) -> None:
    if value not in _DEPTH_RANK:
        raise _error(
            "authority_verification_depth_invalid",
            f"{field} has an unsupported verification depth.",
        )


def _resolve_full_commit(root: Path, value: str, *, code: str) -> str:
    if _OID.fullmatch(value) is None:
        raise _error(code, "Git commit identity must be a full hexadecimal OID.", value=value)
    try:
        resolved = _git_text(root, "rev-parse", "--verify", f"{value}^{{commit}}")
    except AuthoritySurfaceError as exc:
        raise _error(code, "Git commit identity could not be verified.", value=value) from exc
    if resolved != value:
        raise _error(code, "Git commit identity did not resolve exactly.", value=value, resolved=resolved)
    return resolved


def _is_ancestor(root: Path, base: str, candidate: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, candidate],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    raise _error(
        "authority_git_failure",
        "Git ancestry check failed.",
        stderr=completed.stderr.decode("utf-8", errors="replace").strip(),
    )


def _git_text(root: Path, *args: str) -> str:
    return _git_bytes(root, *args).decode("ascii").strip()


def _diff_entries_sha256(entries: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        entries,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _git_bytes(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise _error(
            "authority_git_failure",
            "Git authority query failed.",
            command=["git", *args],
            returncode=completed.returncode,
            stderr=completed.stderr.decode("utf-8", errors="replace").strip(),
        )
    return completed.stdout


def _error(code: str, message: str, **details: Any) -> AuthoritySurfaceError:
    return AuthoritySurfaceError(message=message, code=code, details=details)
