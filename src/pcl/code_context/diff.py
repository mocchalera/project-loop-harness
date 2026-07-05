from __future__ import annotations

import fnmatch
from pathlib import Path
import re
import subprocess
import sys

from ..errors import InvalidInputError
from ..paths import ProjectPaths


GIT_DIFF_SENTINEL = "__git__"


def _load_diff(paths: ProjectPaths, diff_source: str) -> tuple[str, str]:
    if diff_source.startswith("inline:"):
        return diff_source.removeprefix("inline:"), "fixture:inline"
    if diff_source == GIT_DIFF_SENTINEL:
        return _git_diff(paths.root), "git:diff"
    if diff_source == "-":
        return sys.stdin.read(), "stdin"
    path = Path(diff_source)
    if not path.is_absolute():
        path = paths.root / path
    try:
        return path.read_text(encoding="utf-8"), str(path)
    except OSError as exc:
        raise InvalidInputError(
            f"Could not open diff source: {path}",
            details={"diff_source": str(path)},
        ) from exc


def _inline_diff_source(diff_text: str) -> str:
    return "inline:" + diff_text


def _git_diff(root: Path) -> str:
    commands = [
        ["git", "-C", str(root), "diff", "--name-status", "HEAD", "--"],
        ["git", "-C", str(root), "diff", "--name-status", "--"],
    ]
    for command in commands:
        completed = subprocess.run(command, capture_output=True, check=False, text=True)
        if completed.returncode == 0:
            return completed.stdout
    raise InvalidInputError(
        "Could not obtain git diff for this project. Pass --diff <path> with a synthetic diff file.",
        details={"root": str(root)},
    )


def _parse_changed_files(diff_text: str) -> list[dict[str, str]]:
    by_path: dict[str, str] = {}
    current_old_path = ""
    current_new_path = ""
    pending_source_path = ""
    in_hunk = False
    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("diff --git "):
            parts = stripped.split()
            if len(parts) >= 4:
                current_old_path = _normalize_diff_path(parts[2])
                current_new_path = _normalize_diff_path(parts[3])
                pending_source_path = ""
                in_hunk = False
                path = current_new_path or current_old_path
                if path:
                    by_path.setdefault(path, "M")
            continue
        if stripped.startswith("@@"):
            in_hunk = True
            continue
        if stripped.startswith("rename from "):
            pending_source_path = _normalize_diff_path(stripped.removeprefix("rename from ").strip())
            continue
        if stripped.startswith("rename to "):
            path = _normalize_diff_path(stripped.removeprefix("rename to ").strip())
            if path:
                by_path[path] = "R"
            elif pending_source_path:
                by_path[pending_source_path] = "R"
            pending_source_path = ""
            continue
        if stripped.startswith("copy from "):
            pending_source_path = _normalize_diff_path(stripped.removeprefix("copy from ").strip())
            continue
        if stripped.startswith("copy to "):
            path = _normalize_diff_path(stripped.removeprefix("copy to ").strip())
            if path:
                by_path[path] = "C"
            elif pending_source_path:
                by_path[pending_source_path] = "C"
            pending_source_path = ""
            continue
        if stripped.startswith("new file mode"):
            path = current_new_path or current_old_path
            if path:
                by_path[path] = "A"
            continue
        if stripped.startswith("deleted file mode"):
            path = current_old_path or current_new_path
            if path:
                by_path[path] = "D"
            continue
        if not in_hunk and stripped.startswith("--- "):
            path = _normalize_diff_path(stripped[4:].strip())
            if path:
                by_path.setdefault(path, "M")
                current_old_path = path
            continue
        if not in_hunk and stripped.startswith("+++ "):
            path = _normalize_diff_path(stripped[4:].strip())
            if path:
                by_path[path] = by_path.get(path, "M")
                current_new_path = path
            elif current_old_path:
                by_path[current_old_path] = "D"
            continue
        status_match = re.match(r"^([ACDMRTUXB])\d*\s+(.+)$", stripped)
        if status_match:
            status = status_match.group(1)
            fields = status_match.group(2).split()
            path = _normalize_diff_path(fields[-1]) if fields else ""
            if path:
                by_path[path] = status
            continue
    return [{"path": path, "status": by_path[path]} for path in sorted(by_path)]


def _normalize_diff_path(value: str) -> str:
    path = value.strip().strip('"')
    if path == "/dev/null":
        return ""
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def _git_head(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _gitignored_paths(root: Path, relative_paths: list[str]) -> dict[str, str]:
    if not relative_paths:
        return {}
    input_text = "\0".join(relative_paths) + "\0"
    completed = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--verbose", "-z", "--stdin"],
        capture_output=True,
        check=False,
        input=input_text,
        text=True,
    )
    if completed.returncode in {0, 1}:
        return _parse_git_check_ignore_output(completed.stdout)
    return _fallback_gitignore_matches(root, relative_paths)


def _parse_git_check_ignore_output(output: str) -> dict[str, str]:
    ignored: dict[str, str] = {}
    parts = [part for part in output.split("\0") if part]
    for index in range(0, len(parts) - 3, 4):
        source, line_number, pattern, path = parts[index : index + 4]
        ignored[path] = f"gitignore:{source}:{line_number}:{pattern}"
    return ignored


def _fallback_gitignore_matches(root: Path, relative_paths: list[str]) -> dict[str, str]:
    patterns = _root_gitignore_patterns(root)
    ignored: dict[str, str] = {}
    for path in relative_paths:
        for pattern in patterns:
            if _gitignore_pattern_matches(pattern, path):
                ignored[path] = f"gitignore:{pattern}"
                break
    return ignored


def _root_gitignore_patterns(root: Path) -> list[str]:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return []
    patterns: list[str] = []
    for raw_line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        patterns.append(line)
    return patterns


def _gitignore_pattern_matches(pattern: str, path: str) -> bool:
    normalized = pattern.strip("/")
    if not normalized:
        return False
    if pattern.endswith("/"):
        return path == normalized or path.startswith(normalized + "/")
    if "/" not in normalized:
        return any(part == normalized or fnmatch.fnmatch(part, normalized) for part in path.split("/"))
    return fnmatch.fnmatch(path, normalized)
