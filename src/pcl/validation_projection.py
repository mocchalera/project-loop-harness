from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any

from .db import connect
from .errors import InvalidInputError
from .paths import ProjectPaths
from .target_resolver import (
    ResolvedRoutingTarget,
    TaskGoalTargetNotFoundError,
    resolve_routing_target,
)
from .validators import ValidationFinding, ValidationResult


VALIDATION_PROJECTION_CONTRACT_VERSION = "validation-projection/v1"
GLOBAL_ENTITY_TYPES = {
    "migration",
    "project",
    "schema_metadata",
    "schema_table",
    "skill",
}
GLOBAL_CODE_PREFIXES = (
    "audit_",
    "installation_",
    "relationship_",
    "schema_",
    "validation_",
)
TARGET_PROJECTABLE_CODE_PREFIXES = (
    "agent_",
    "defect_",
    "feature_",
    "goal_",
    "story_",
    "task_",
    "test_",
    "verification_",
    "workflow_run_",
)


def project_validation_result(
    paths: ProjectPaths,
    result: ValidationResult,
    *,
    target_id: str | None,
    active_only: bool,
    summary: bool,
) -> dict[str, Any]:
    """Project a completed full-project validation without changing its verdict."""

    resolved = _resolve_target(paths, target_id) if target_id is not None else None
    full_payload = result.to_dict()
    detailed: list[ValidationFinding] = []
    omitted: list[ValidationFinding] = []
    historical: list[ValidationFinding] = []

    for finding in result.findings:
        if finding.proof_scope == "historical":
            historical.append(finding)
            omitted.append(finding)
            continue
        if resolved is None or _finding_is_in_scope(finding, resolved):
            detailed.append(finding)
            continue
        if _finding_must_remain_visible(finding):
            detailed.append(finding)
            continue
        omitted.append(finding)

    payload = {
        "ok": result.ok,
        "errors": [
            finding.message for finding in detailed if finding.severity == "error"
        ],
        "warnings": [
            finding.message for finding in detailed if finding.severity == "warning"
        ],
        "findings": [finding.to_dict() for finding in detailed],
        # Preserve the legacy full-project totals even though detail is projected.
        "finding_counts": result.finding_counts(),
        "validation_projection": {
            "contract_version": VALIDATION_PROJECTION_CONTRACT_VERSION,
            "active_only": active_only,
            "summary": summary,
            "target": (
                {
                    "target_type": resolved.type,
                    "target_id": resolved.id,
                }
                if resolved is not None
                else None
            ),
            "detailed_count": len(detailed),
            "historical": _aggregate_findings(historical),
            "omitted": _aggregate_findings(omitted),
        },
        "full_validation": {
            "digest": _validation_digest(full_payload),
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "finding_count": len(result.findings),
            "finding_counts": result.finding_counts(),
        },
    }
    return payload


def _resolve_target(
    paths: ProjectPaths,
    target_id: str,
) -> ResolvedRoutingTarget:
    conn = connect(paths.db_path)
    try:
        try:
            return resolve_routing_target(conn, target_id)
        except TaskGoalTargetNotFoundError as exc:
            raise InvalidInputError(
                f"Validation target does not exist: {target_id}",
                details={"target": target_id, "target_type": exc.target_type},
            ) from exc
    finally:
        conn.close()


def _finding_is_in_scope(
    finding: ValidationFinding,
    resolved: ResolvedRoutingTarget,
) -> bool:
    refs: list[dict[str, str]] = []
    if isinstance(finding.entity, dict):
        refs.append(finding.entity)
    refs.extend(item for item in finding.related if isinstance(item, dict))
    return any(
        resolved.blocks_ref(item.get("type"), item.get("id"))
        for item in refs
    )


def _finding_must_remain_visible(finding: ValidationFinding) -> bool:
    if finding.severity == "error" or finding.requires_human:
        return True
    if finding.repair_class == "unsupported" or finding.entity is None:
        return True
    if finding.code.startswith(GLOBAL_CODE_PREFIXES):
        return True
    if not finding.code.startswith(TARGET_PROJECTABLE_CODE_PREFIXES):
        return True
    entity_type = str(finding.entity.get("type") or "")
    return entity_type in GLOBAL_ENTITY_TYPES


def _aggregate_findings(findings: list[ValidationFinding]) -> dict[str, Any]:
    codes = Counter(finding.code for finding in findings)
    return {
        "count": len(findings),
        "codes": {code: codes[code] for code in sorted(codes)},
    }


def _validation_digest(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"
