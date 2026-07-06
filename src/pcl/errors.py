from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EXIT_VALIDATION_FAILED = 1
EXIT_USAGE = 2
EXIT_NOT_INITIALIZED = 3
EXIT_DATA_ERROR = 4


@dataclass
class PclError(Exception):
    message: str
    code: str = "pcl_error"
    exit_code: int = EXIT_VALIDATION_FAILED
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
            },
        }
        if self.details:
            payload["error"]["details"] = self.details
        return payload


class ProjectNotInitializedError(PclError):
    def __init__(self, *, root: str) -> None:
        super().__init__(
            message=f"Project Loop Harness is not initialized at {root}. Run `pcl init --target {root}`.",
            code="not_initialized",
            exit_code=EXIT_NOT_INITIALIZED,
            details={"root": root},
        )


class ProjectValidationError(PclError):
    def __init__(self, *, errors: list[str], warnings: list[str] | None = None) -> None:
        super().__init__(
            message="Project Loop Harness state is invalid.",
            code="validation_failed",
            exit_code=EXIT_VALIDATION_FAILED,
            details={"errors": errors, "warnings": warnings or []},
        )


class InvalidInputError(PclError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="invalid_input",
            exit_code=EXIT_USAGE,
            details=details or {},
        )


class ContextPackBudgetError(PclError):
    def __init__(self, *, details: dict[str, Any]) -> None:
        estimated_min = details.get("estimated_min_max_tokens")
        hint = (
            f" Increase --max-tokens to at least {estimated_min}."
            if isinstance(estimated_min, int)
            else ""
        )
        super().__init__(
            message="Context pack budget is too small for required sections and truncation notice."
            + hint,
            code="context_pack_budget_too_small",
            exit_code=EXIT_USAGE,
            details=details,
        )


class NotImplementedCommandError(PclError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="not_implemented",
            exit_code=EXIT_USAGE,
            details=details or {},
        )


class DataStoreError(PclError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="data_store_error",
            exit_code=EXIT_DATA_ERROR,
            details=details or {},
        )
