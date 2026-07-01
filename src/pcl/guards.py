from __future__ import annotations

from .errors import ProjectNotInitializedError, ProjectValidationError
from .paths import ProjectPaths
from .validators import validate_project


def require_initialized(paths: ProjectPaths) -> None:
    if not paths.loop_dir.exists() or not paths.db_path.exists():
        raise ProjectNotInitializedError(root=str(paths.root))

    result = validate_project(paths)
    if not result.ok:
        raise ProjectValidationError(errors=result.errors, warnings=result.warnings)
