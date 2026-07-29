from __future__ import annotations

from .errors import ProjectNotInitializedError, ProjectValidationError
from .paths import ProjectPaths
from .validators import validate_project


def require_initialized(
    paths: ProjectPaths,
    *,
    allowed_error_codes: frozenset[str] = frozenset(),
) -> None:
    if not paths.loop_dir.exists() or not paths.db_path.exists():
        raise ProjectNotInitializedError(root=str(paths.root))

    result = validate_project(paths)
    blocking_errors = [
        finding.message
        for finding in result.findings
        if finding.severity == "error" and finding.code not in allowed_error_codes
    ]
    classified_errors = {
        finding.message
        for finding in result.findings
        if finding.severity == "error"
    }
    blocking_errors.extend(
        error for error in result.errors if error not in classified_errors
    )
    if blocking_errors:
        raise ProjectValidationError(
            errors=blocking_errors,
            warnings=result.warnings,
        )
