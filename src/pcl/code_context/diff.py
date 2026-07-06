from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from ..errors import InvalidInputError
from ..paths import ProjectPaths


GIT_DIFF_SENTINEL = "__git__"
DEFAULT_DIFF_SOURCE = "worktree-vs-HEAD"
PROVIDED_DIFF_SOURCE = "provided-diff"
AUTO_BASE_REF = "auto"
AUTO_BASE_ATTEMPTS = ("origin/HEAD", "main", "master")


@dataclass(frozen=True)
class LoadedDiff:
    text: str
    diff_source: str
    base_ref: str | None
    provenance: dict[str, Any]
    untracked_paths: tuple[str, ...] = ()
    untracked_included: bool = False
    untracked_excluded_count: int = 0


def _load_diff(
    paths: ProjectPaths,
    diff_source: str,
    *,
    base_ref: str | None = None,
    staged: bool = False,
    unstaged: bool = False,
    include_untracked: bool = False,
    all_changes: bool = False,
) -> LoadedDiff:
    explicit_diff_source = diff_source != GIT_DIFF_SENTINEL
    selected_modes = [
        name
        for name, enabled in {
            "staged": staged,
            "unstaged": unstaged,
            "all-changes": all_changes,
        }.items()
        if enabled
    ]
    if len(selected_modes) > 1:
        raise InvalidInputError(
            "Diff mode flags are mutually exclusive.",
            details={"mode_error": "mutually_exclusive_diff_modes", "modes": selected_modes},
        )
    if explicit_diff_source and (selected_modes or include_untracked):
        raise InvalidInputError(
            "Diff mode flags can only be used with git-based `pcl impact --diff`.",
            details={
                "mode_error": "provided_diff_mode_conflict",
                "diff_source": diff_source,
                "modes": selected_modes,
                "include_untracked": include_untracked,
            },
        )
    if base_ref and explicit_diff_source:
        raise InvalidInputError(
            "--base can only be used with `pcl impact --diff` without an explicit diff source.",
            details={"base_ref": base_ref, "diff_source": diff_source},
        )
    if base_ref and unstaged:
        raise InvalidInputError(
            "--base cannot be used with --unstaged because that mode compares the worktree against the index.",
            details={"mode_error": "base_unstaged_conflict", "base_ref": base_ref},
        )
    if base_ref and all_changes:
        raise InvalidInputError(
            "--base cannot be used with --all-changes; use --include-untracked with --base instead.",
            details={"mode_error": "base_all_changes_conflict", "base_ref": base_ref},
        )
    if base_ref:
        resolved_base_ref, auto_resolution = _resolve_base_ref(paths.root, base_ref)
        return _load_git_diff(
            paths.root,
            base_ref=resolved_base_ref,
            staged=staged,
            include_untracked=include_untracked,
            auto_resolution=auto_resolution,
            record_base_ref=True,
        )
    if diff_source.startswith("inline:"):
        return LoadedDiff(
            text=diff_source.removeprefix("inline:"),
            diff_source=PROVIDED_DIFF_SOURCE,
            base_ref=None,
            provenance=_provided_diff_provenance(source="inline-fixture"),
        )
    if diff_source == GIT_DIFF_SENTINEL:
        return _load_git_diff(
            paths.root,
            base_ref="HEAD",
            staged=staged,
            unstaged=unstaged,
            include_untracked=include_untracked or all_changes,
            all_changes=all_changes,
        )
    if diff_source == "-":
        return LoadedDiff(
            text=sys.stdin.read(),
            diff_source=PROVIDED_DIFF_SOURCE,
            base_ref=None,
            provenance=_provided_diff_provenance(source="stdin"),
        )
    path = Path(diff_source)
    if not path.is_absolute():
        path = paths.root / path
    try:
        return LoadedDiff(
            text=path.read_text(encoding="utf-8"),
            diff_source=PROVIDED_DIFF_SOURCE,
            base_ref=None,
            provenance=_provided_diff_provenance(source=str(path)),
        )
    except OSError as exc:
        raise InvalidInputError(
            f"Could not open diff source: {path}",
            details={"diff_source": str(path)},
        ) from exc


def _inline_diff_source(diff_text: str) -> str:
    return "inline:" + diff_text


def _load_git_diff(
    root: Path,
    *,
    base_ref: str,
    staged: bool = False,
    unstaged: bool = False,
    include_untracked: bool = False,
    all_changes: bool = False,
    auto_resolution: dict[str, Any] | None = None,
    record_base_ref: bool = False,
) -> LoadedDiff:
    text = _git_diff(root, base_ref=base_ref, staged=staged, unstaged=unstaged)
    untracked_paths = _git_untracked_paths(root)
    diff_source = _git_diff_source(
        base_ref=base_ref,
        staged=staged,
        unstaged=unstaged,
        include_untracked=include_untracked,
        all_changes=all_changes,
    )
    provenance = _git_diff_provenance(base_ref=base_ref, staged=staged, unstaged=unstaged)
    if auto_resolution:
        provenance.update(auto_resolution)
    if include_untracked:
        text = _append_untracked_name_status(text, untracked_paths)
        provenance.update(_untracked_provenance(len(untracked_paths)))
    return LoadedDiff(
        text=text,
        diff_source=diff_source,
        base_ref=base_ref if record_base_ref else None,
        provenance=provenance,
        untracked_paths=tuple(untracked_paths) if include_untracked else (),
        untracked_included=include_untracked,
        untracked_excluded_count=0 if include_untracked else len(untracked_paths),
    )


def _git_diff(root: Path, *, base_ref: str = "HEAD", staged: bool = False, unstaged: bool = False) -> str:
    args = ["diff", "--no-ext-diff", "--no-textconv", "--name-status"]
    if staged:
        args.append("--cached")
        args.append(base_ref)
    elif not unstaged:
        args.append(base_ref)
    args.append("--")
    command = _git_command(root, args)
    source = _git_diff_source(base_ref=base_ref, staged=staged, unstaged=unstaged)
    description = _git_diff_description(base_ref=base_ref, staged=staged, unstaged=unstaged)
    completed = subprocess.run(command, capture_output=True, check=False, text=True)
    if completed.returncode == 0:
        return completed.stdout
    raise InvalidInputError(
        f"Could not obtain {description}.",
        details={"root": str(root), "diff_source": source},
    )


def _git_untracked_paths(root: Path) -> list[str]:
    command = _git_command(root, ["ls-files", "--others", "--exclude-standard", "-z", "--"])
    completed = subprocess.run(command, capture_output=True, check=False, text=True)
    if completed.returncode == 0:
        return sorted(path for path in completed.stdout.split("\0") if path)
    raise InvalidInputError(
        "Could not list untracked files for this project.",
        details={"root": str(root), "command_shape": "git ls-files --others --exclude-standard -z --"},
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
        status_tab_match = re.match(r"^([ACDMRTUXB])\d*\t(.+)$", line)
        if status_tab_match:
            status = status_tab_match.group(1)
            fields = status_tab_match.group(2).split("\t")
            path = _normalize_diff_path(fields[-1]) if fields else ""
            if path:
                by_path[path] = status
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
        _git_command(root, ["rev-parse", "HEAD"]),
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
        _git_command(root, ["check-ignore", "--verbose", "-z", "--stdin"]),
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


def _validate_git_ref(root: Path, ref: str) -> None:
    if _git_ref_exists(root, ref):
        return
    raise InvalidInputError(
        f"Unknown git ref for --base: {ref}",
        details={"base_ref": ref},
    )


def _git_ref_exists(root: Path, ref: str) -> bool:
    completed = subprocess.run(
        _git_command(root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]),
        capture_output=True,
        check=False,
        text=True,
    )
    return completed.returncode == 0


def _resolve_base_ref(root: Path, ref: str) -> tuple[str, dict[str, Any] | None]:
    if ref != AUTO_BASE_REF:
        _validate_git_ref(root, ref)
        return ref, None

    attempted = list(AUTO_BASE_ATTEMPTS)
    origin_head = _origin_head_ref(root)
    if origin_head and _git_ref_exists(root, origin_head):
        return origin_head, _auto_base_provenance(origin_head, attempted)
    for candidate in ("main", "master"):
        if _git_ref_exists(root, candidate):
            return candidate, _auto_base_provenance(candidate, attempted)
    raise InvalidInputError(
        "Could not resolve --base auto. Tried origin/HEAD, main, master.",
        details={"base_ref": AUTO_BASE_REF, "attempted_refs": attempted},
    )


def _origin_head_ref(root: Path) -> str | None:
    completed = subprocess.run(
        _git_command(root, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]),
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _git_command(root: Path, args: list[str]) -> list[str]:
    return ["git", "-C", str(root), "-c", "core.pager=cat", "--no-pager", *args]


def _append_untracked_name_status(diff_text: str, untracked_paths: list[str]) -> str:
    additions = [f"A\t{path}" for path in untracked_paths]
    if not additions:
        return diff_text
    prefix = diff_text.rstrip("\n")
    if not prefix:
        return "\n".join(additions) + "\n"
    return prefix + "\n" + "\n".join(additions) + "\n"


def _git_diff_source(
    *,
    base_ref: str,
    staged: bool = False,
    unstaged: bool = False,
    include_untracked: bool = False,
    all_changes: bool = False,
) -> str:
    if all_changes:
        source = "all-changes-vs-HEAD"
    elif staged:
        source = f"staged-vs-{base_ref}"
    elif unstaged:
        source = "worktree-vs-index"
    else:
        source = f"worktree-vs-{base_ref}"
    if include_untracked:
        return source + "+untracked"
    return source


def _git_diff_description(*, base_ref: str, staged: bool = False, unstaged: bool = False) -> str:
    if staged:
        return f"staged diff against {base_ref}"
    if unstaged:
        return "unstaged diff against the index"
    return f"worktree diff against {base_ref}"


def _git_diff_provenance(*, base_ref: str, staged: bool = False, unstaged: bool = False) -> dict[str, Any]:
    if staged:
        command_shape = f"git diff --no-ext-diff --no-textconv --name-status --cached {base_ref} --"
    elif unstaged:
        command_shape = "git diff --no-ext-diff --no-textconv --name-status --"
    else:
        command_shape = f"git diff --no-ext-diff --no-textconv --name-status {base_ref} --"
    return {
        "source": "local-git-worktree",
        "attestation": "local-git",
        "command_shape": command_shape,
    }


def _auto_base_provenance(resolved_ref: str, attempted_refs: list[str]) -> dict[str, Any]:
    return {
        "base_ref": resolved_ref,
        "base_ref_resolution": "auto",
        "base_ref_attempted_refs": attempted_refs,
        "note": "--base auto inferred the comparison ref from local git refs.",
    }


def _untracked_provenance(untracked_count: int) -> dict[str, Any]:
    return {
        "untracked_included": True,
        "untracked_count": untracked_count,
        "untracked_command_shape": "git ls-files --others --exclude-standard -z --",
    }


def _provided_diff_provenance(*, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "attestation": "unattested",
        "note": "PLH used caller-provided diff text and cannot attest that it matches the working tree.",
    }
