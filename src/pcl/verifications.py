from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any

from .db import connect
from .errors import InvalidInputError
from .guards import require_initialized
from .paths import ProjectPaths
from .rubric import rubric_contract_version


VERIFICATION_RESULTS = {"approved", "rejected", "needs_human", "inconclusive"}


def list_verifications(
    paths: ProjectPaths,
    *,
    workflow_run_id: str | None = None,
    result: str | None = None,
) -> list[dict[str, Any]]:
    require_initialized(paths)
    if workflow_run_id:
        _validate_identifier(workflow_run_id, "workflow_run_id")
    if result:
        _require_result(result)

    where: list[str] = []
    params: list[str] = []
    if workflow_run_id:
        where.append("workflow_run_id = ?")
        params.append(workflow_run_id)
    if result:
        where.append("result = ?")
        params.append(result)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT id, workflow_run_id, target_job_id, verifier_role, rubric_json, result,
                   reasons_json, created_at
            FROM verifications
            {where_sql}
            ORDER BY created_at, id
            """,
            tuple(params),
        ).fetchall()
        return [_verification_from_row(row) for row in rows]
    finally:
        conn.close()


def read_verification(paths: ProjectPaths, verification_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(verification_id, "verification_id")
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, workflow_run_id, target_job_id, verifier_role, rubric_json, result,
                   reasons_json, created_at
            FROM verifications
            WHERE id = ?
            """,
            (verification_id,),
        ).fetchone()
        if row is None:
            raise InvalidInputError(
                f"Verification does not exist: {verification_id}",
                details={"verification_id": verification_id},
            )
        return _verification_from_row(row)
    finally:
        conn.close()


def _verification_from_row(row) -> dict[str, Any]:
    verification = dict(row)
    rubric = _json_object(verification.get("rubric_json"))
    verification["rubric"] = rubric
    verification["rubric_contract_version"] = rubric_contract_version(rubric)
    verification["reasons"] = _json_array(verification.get("reasons_json"))
    return verification


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _json_array(raw: Any) -> list[Any]:
    try:
        value = json.loads(str(raw or "[]"))
    except JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _require_result(result: str) -> None:
    if result not in VERIFICATION_RESULTS:
        raise InvalidInputError(
            f"Invalid verification result: {result}",
            details={"result": result, "allowed": sorted(VERIFICATION_RESULTS)},
        )


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or not all(c.isalnum() or c in {"_", "-"} for c in value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={"field": field_name, "value": value},
        )
