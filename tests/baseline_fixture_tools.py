from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


SNAPSHOT_COMMANDS = {
    "pcl-version": ["--version"],
    "pcl-help": ["--help"],
    "validate-help": ["validate", "--help"],
    "render-help": ["render", "--help"],
    "next-help": ["next", "--help"],
    "context-check-help": ["context", "check", "--help"],
}

PROJECT_COMMANDS = {
    "validate-strict-json": ["validate", "--strict", "--json"],
    "render-json": ["render", "--json"],
    "next-json": ["next", "--json"],
    "context-check-json": ["context", "check", "--task", "T-0001", "--json"],
}

SNAPSHOT_ENV = {
    "COLUMNS": "80",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "LINES": "24",
    "NO_COLOR": "1",
    "PYTHONHASHSEED": "0",
    "TZ": "UTC",
}

_ISO_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b"
)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_HASH_RE = re.compile(r"\b(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{40})\b")


def generate_snapshot_fixtures(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pcl-baseline-empty-") as empty_tmp:
        with tempfile.TemporaryDirectory(prefix="pcl-baseline-representative-") as representative_tmp:
            empty_root = Path(empty_tmp)
            representative_root = Path(representative_tmp)
            _initialize_empty_project(empty_root)
            _initialize_representative_project(representative_root)

            for name, argv in SNAPSHOT_COMMANDS.items():
                _write_snapshot(destination / f"{name}.json", argv, project_root=None)
            for project_name, project_root in (
                ("empty", empty_root),
                ("representative", representative_root),
            ):
                for name, argv in PROJECT_COMMANDS.items():
                    _write_snapshot(
                        destination / f"{project_name}-{name}.json",
                        ["--root", str(project_root), *argv],
                        project_root=project_root,
                    )


def snapshot_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*.json"))
    }


def _initialize_empty_project(root: Path) -> None:
    _run_checked(["init", "--target", str(root), "--json"])


def _initialize_representative_project(root: Path) -> None:
    _initialize_empty_project(root)
    commands = [
        ["--root", str(root), "goal", "create", "--title", "Baseline delivery"],
        [
            "--root",
            str(root),
            "feature",
            "add",
            "--name",
            "Snapshot contract",
            "--surface",
            "cli:pcl baseline",
            "--description",
            "Synthetic representative fixture content.",
        ],
        [
            "--root",
            str(root),
            "story",
            "draft",
            "--feature",
            "F-0001",
            "--actor",
            "maintainer",
            "--goal",
            "compare CLI behavior",
            "--expected-behavior",
            "normalized snapshots remain reproducible",
        ],
        [
            "--root",
            str(root),
            "test",
            "plan",
            "--feature",
            "F-0001",
            "--type",
            "acceptance",
            "--scenario",
            "generate the baseline twice",
            "--expected",
            "the generated directories have no diff",
        ],
        [
            "--root",
            str(root),
            "task",
            "create",
            "--title",
            "Inspect baseline context",
            "--description",
            "Synthetic task used only by the public baseline fixture.",
            "--goal",
            "G-0001",
            "--feature",
            "F-0001",
        ],
    ]
    for command in commands:
        _run_checked(command)


def _write_snapshot(path: Path, argv: list[str], *, project_root: Path | None) -> None:
    result = _run(argv)
    display_argv = ["<PROJECT_ROOT>" if project_root and token == str(project_root) else token for token in argv]
    stdout = _normalized_output(result.stdout, project_root=project_root)
    stderr = _normalized_output(result.stderr, project_root=project_root)
    if "--help" in argv:
        # argparse line-wrapping differs across Python versions even with a
        # pinned COLUMNS (observed: pcl --help on 3.13 vs 3.10-3.12). Help
        # snapshots assert content, not version-specific wrapping, so collapse
        # all whitespace runs to a single space.
        if isinstance(stdout, str):
            stdout = " ".join(stdout.split())
        if isinstance(stderr, str):
            stderr = " ".join(stderr.split())
    payload = {
        "argv": ["pcl", *display_argv],
        "exit_code": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalized_output(output: str, *, project_root: Path | None) -> Any:
    normalized = _normalize_string(output, project_root=project_root)
    try:
        return _normalize_value(json.loads(normalized), project_root=project_root)
    except json.JSONDecodeError:
        return normalized


def _normalize_value(value: Any, *, project_root: Path | None) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_value(item, project_root=project_root)
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        return [_normalize_value(item, project_root=project_root) for item in value]
    if isinstance(value, str):
        return _normalize_string(value, project_root=project_root)
    return value


def _normalize_string(value: str, *, project_root: Path | None) -> str:
    if project_root is not None:
        value = value.replace(str(project_root.resolve()), "<PROJECT_ROOT>")
    value = _ISO_TIMESTAMP_RE.sub("<TIMESTAMP>", value)
    value = _UUID_RE.sub("<UUID>", value)
    return _HASH_RE.sub("<HASH>", value)


def _run_checked(argv: list[str]) -> None:
    result = _run(argv)
    if result.returncode != 0:
        raise RuntimeError(
            f"baseline setup command failed ({result.returncode}): pcl {' '.join(argv)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    source_path = str(repo_root / "src")
    env["PYTHONPATH"] = (
        source_path if not existing_pythonpath else os.pathsep.join((source_path, existing_pythonpath))
    )
    env.update(SNAPSHOT_ENV)
    return subprocess.run(
        [sys.executable, "-m", "pcl", *argv],
        cwd=repo_root,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
