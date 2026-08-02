from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class GitRunner:
    """One argv-only Git subprocess route with an optional complete environment."""

    environment: Mapping[str, str] | None = None

    def run(
        self,
        cwd: Path,
        *args: str,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        environment = None if self.environment is None else dict(self.environment)
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=environment,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
        )


INHERITED_GIT_RUNNER = GitRunner()


def git_argv(args: Sequence[str]) -> list[str]:
    return ["git", *args]
