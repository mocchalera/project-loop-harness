from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import hashlib
import os
from pathlib import Path
import sys
from typing import Any

from .diff import _git_head, _gitignored_paths
from .symbols import (
    SYMBOL_SUMMARY_VERSION,
    _empty_symbol_summary,
    _javascript_symbols,
    _markdown_symbols,
    _python_symbols,
)
from .test_hints import _empty_test_hint


INDEX_VERSION = "code-index/v0"

LARGE_FILE_BYTES = 1_000_000


DEFAULT_CODE_INDEX_EXCLUDES = (
    ".claude/",
    ".agents/",
    ".codex/",
)


DEFAULT_SENSITIVE_EXCLUDES = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "credentials*.json",
    ".npmrc",
    ".pypirc",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    ".netrc",
    ".aws/",
    "secrets/",
)


DEFAULT_IGNORED_NAMES = {
    ".git": "default_ignore:.git",
    ".project-loop": "default_ignore:.project-loop",
    ".pytest_cache": "default_ignore:.pytest_cache",
    ".ruff_cache": "default_ignore:.ruff_cache",
    ".venv": "default_ignore:.venv",
    "__pycache__": "default_ignore:__pycache__",
    "dist": "default_ignore:dist",
    "node_modules": "default_ignore:node_modules",
}


LANGUAGE_BY_SUFFIX = {
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".markdown": "markdown",
    ".mjs": "javascript",
    ".py": "python",
    ".rst": "text",
    ".sh": "shell",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass
class IgnoredEntry:
    path: str
    ignored_reason: str
    size_bytes: int | None = None
    hash_skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "ignored_reason": self.ignored_reason,
        }
        if self.size_bytes is not None:
            payload["size_bytes"] = self.size_bytes
        if self.hash_skipped_reason:
            payload["sha256"] = None
            payload["hash_skipped_reason"] = self.hash_skipped_reason
        return payload


@dataclass
class IndexedFile:
    path: str
    absolute_path: Path
    language: str
    size_bytes: int
    mtime: int
    sha256: str | None
    line_count: int
    symbol_summary: dict[str, Any]
    test_hint: dict[str, Any]
    text: str = field(repr=False, default="")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "size_bytes": self.size_bytes,
            "mtime": self.mtime,
            "sha256": self.sha256,
            "line_count": self.line_count,
            "indexed_content": self.text,
            "symbol_summary": self.symbol_summary,
            "test_hint": self.test_hint,
        }


@dataclass
class ScanResult:
    files: list[IndexedFile]
    ignored: list[IgnoredEntry]
    git_head: str | None
    sensitive_include_override: tuple[str, ...] = ()

    @property
    def indexed_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)

    @property
    def language_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.files:
            counts[item.language] = counts.get(item.language, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def sensitive_omitted_count(self) -> int:
        return sum(1 for item in self.ignored if item.ignored_reason.startswith("sensitive:"))


@dataclass(frozen=True)
class SensitiveIndexSettings:
    additional_patterns: tuple[str, ...] = ()
    agent_may_not_modify_patterns: tuple[str, ...] = ()
    include_override_patterns: tuple[str, ...] = ()


def _scan_working_tree(
    root: Path,
    *,
    include_text: bool,
    warn_on_sensitive_override: bool = False,
) -> ScanResult:
    root = root.resolve()
    configured_excludes = _code_index_exclude_patterns(root)
    sensitive_settings = _sensitive_index_settings(root)
    if warn_on_sensitive_override and sensitive_settings.include_override_patterns:
        print(_sensitive_override_warning(sensitive_settings.include_override_patterns), file=sys.stderr)
    ignored: list[IgnoredEntry] = []
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current_dir = Path(dirpath)
        dirnames.sort()
        filenames.sort()
        kept_dirnames: list[str] = []
        for dirname in dirnames:
            child = current_dir / dirname
            rel = _relative_path(root, child)
            sensitive_reason = _sensitive_ignore_reason(f"{rel}/", sensitive_settings)
            if sensitive_reason:
                ignored.append(IgnoredEntry(path=f"{rel}/", ignored_reason=sensitive_reason))
                continue
            reason = DEFAULT_IGNORED_NAMES.get(dirname)
            if reason:
                ignored.append(IgnoredEntry(path=f"{rel}/", ignored_reason=reason))
                continue
            configured_reason = _configured_ignore_reason(f"{rel}/", configured_excludes)
            if configured_reason:
                ignored.append(IgnoredEntry(path=f"{rel}/", ignored_reason=configured_reason))
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames
        for filename in filenames:
            path = current_dir / filename
            rel = _relative_path(root, path)
            sensitive_reason = _sensitive_ignore_reason(rel, sensitive_settings)
            if sensitive_reason:
                ignored.append(IgnoredEntry(path=rel, ignored_reason=sensitive_reason))
                continue
            default_reason = _default_ignore_reason(rel)
            if default_reason:
                ignored.append(IgnoredEntry(path=rel, ignored_reason=default_reason))
                continue
            configured_reason = _configured_ignore_reason(rel, configured_excludes)
            if configured_reason:
                ignored.append(IgnoredEntry(path=rel, ignored_reason=configured_reason))
                continue
            candidates.append(path)

    gitignored = _gitignored_paths(root, [_relative_path(root, path) for path in candidates])
    files: list[IndexedFile] = []
    for path in candidates:
        rel = _relative_path(root, path)
        if rel in gitignored:
            ignored.append(IgnoredEntry(path=rel, ignored_reason=gitignored[rel]))
            continue
        try:
            stat = path.stat()
        except OSError as exc:
            ignored.append(IgnoredEntry(path=rel, ignored_reason=f"unreadable:{exc.__class__.__name__}"))
            continue
        if not path.is_file():
            continue
        size = int(stat.st_size)
        if size > LARGE_FILE_BYTES:
            ignored.append(
                IgnoredEntry(
                    path=rel,
                    ignored_reason="large_file",
                    size_bytes=size,
                    hash_skipped_reason=f"size>{LARGE_FILE_BYTES}",
                )
            )
            continue
        try:
            sample = path.read_bytes()[:8192]
        except OSError as exc:
            ignored.append(IgnoredEntry(path=rel, ignored_reason=f"unreadable:{exc.__class__.__name__}"))
            continue
        if _looks_binary(sample):
            ignored.append(
                IgnoredEntry(
                    path=rel,
                    ignored_reason="binary_file",
                    size_bytes=size,
                    hash_skipped_reason="binary_file",
                )
            )
            continue
        text = ""
        if include_text:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                ignored.append(
                    IgnoredEntry(
                        path=rel,
                        ignored_reason=f"text_decode_failed:{exc.__class__.__name__}",
                        size_bytes=size,
                        hash_skipped_reason="text_decode_failed",
                    )
                )
                continue
        files.append(
            IndexedFile(
                path=rel,
                absolute_path=path,
                language=_detect_language(path),
                size_bytes=size,
                mtime=int(stat.st_mtime_ns),
                sha256=_sha256_file(path) if include_text else None,
                line_count=_line_count(text) if include_text else 0,
                symbol_summary=_symbol_summary(rel, text) if include_text else _empty_symbol_summary(),
                test_hint=_empty_test_hint(rel),
                text=text,
            )
        )
    files.sort(key=lambda item: item.path)
    ignored.sort(key=lambda item: item.path)
    return ScanResult(
        files=files,
        ignored=ignored,
        git_head=_git_head(root),
        sensitive_include_override=sensitive_settings.include_override_patterns,
    )


def _default_ignore_reason(relative_path: str) -> str | None:
    for part in relative_path.split("/"):
        reason = DEFAULT_IGNORED_NAMES.get(part)
        if reason:
            return reason
    return None


def _code_index_exclude_patterns(root: Path) -> list[tuple[str, str]]:
    configured = _configured_yaml_list(root, "code_index", "exclude")
    if configured is None:
        return [
            (pattern, f"default_code_index_exclude:{pattern}")
            for pattern in DEFAULT_CODE_INDEX_EXCLUDES
        ]
    return [(pattern, f"code_index.exclude:{pattern}") for pattern in configured]


def _sensitive_index_settings(root: Path) -> SensitiveIndexSettings:
    additional = _configured_yaml_list(root, "code_index", "sensitive_exclude") or []
    agent_may_not_modify = _configured_yaml_list(root, "permissions", "agent_may_not_modify") or []
    include_override = _configured_yaml_list(root, "code_index", "sensitive_include_override") or []
    return SensitiveIndexSettings(
        additional_patterns=tuple(additional),
        agent_may_not_modify_patterns=tuple(agent_may_not_modify),
        include_override_patterns=tuple(include_override),
    )


def _sensitive_ignore_reason(relative_path: str, settings: SensitiveIndexSettings) -> str | None:
    if _matches_any_pattern(relative_path, settings.include_override_patterns):
        return None
    if _matches_any_pattern(relative_path, settings.agent_may_not_modify_patterns):
        return "sensitive:agent_may_not_modify"
    for pattern in (*DEFAULT_SENSITIVE_EXCLUDES, *settings.additional_patterns):
        if _path_pattern_matches(pattern, relative_path):
            return f"sensitive:{pattern}"
    return None


def _sensitive_override_warning(patterns: tuple[str, ...]) -> str:
    joined = ", ".join(patterns)
    return (
        "WARNING: code_index.sensitive_include_override is configured; "
        f"sensitive paths matching these patterns may be indexed: {joined}"
    )


def _configured_yaml_list(root: Path, section: str, key: str) -> list[str] | None:
    config_path = root / "pcl.yaml"
    if not config_path.exists():
        return None
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    in_section = False
    in_list = False
    section_indent = 0
    list_indent = 0
    values: list[str] = []
    saw_key = False
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if indent == 0 and stripped.startswith(f"{section}:"):
            in_section = True
            in_list = False
            section_indent = indent
            continue
        if in_section and indent <= section_indent and not stripped.startswith("-"):
            break
        if not in_section:
            continue
        if stripped.startswith(f"{key}:"):
            saw_key = True
            in_list = True
            list_indent = indent
            raw_value = stripped.split(":", 1)[1].strip()
            if raw_value:
                inline = _parse_inline_yaml_list(raw_value)
                if inline is not None:
                    values.extend(inline)
                    in_list = False
                else:
                    value = _strip_yaml_string(raw_value)
                    if value:
                        values.append(value)
            continue
        if in_list:
            if indent <= list_indent and not stripped.startswith("-"):
                in_list = False
                continue
            if stripped.startswith("-"):
                value = _strip_yaml_string(stripped[1:].strip())
                if value:
                    values.append(value)
    if not saw_key:
        return None
    return _unique_nonempty(values)


def _parse_inline_yaml_list(value: str) -> list[str] | None:
    stripped = value.strip()
    if stripped == "[]":
        return []
    if not stripped.startswith("[") or not stripped.endswith("]"):
        return None
    inner = stripped[1:-1].strip()
    if not inner:
        return []
    return [_strip_yaml_string(part.strip()) for part in inner.split(",") if _strip_yaml_string(part.strip())]


def _strip_yaml_string(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _unique_nonempty(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _configured_ignore_reason(relative_path: str, patterns: list[tuple[str, str]]) -> str | None:
    for pattern, reason in patterns:
        if _path_pattern_matches(pattern, relative_path):
            return reason
    return None


def _matches_any_pattern(relative_path: str, patterns: tuple[str, ...]) -> bool:
    return any(_path_pattern_matches(pattern, relative_path) for pattern in patterns)


def _path_pattern_matches(pattern: str, relative_path: str) -> bool:
    normalized_path = relative_path.strip("/")
    normalized_pattern = pattern.strip()
    if not normalized_path or not normalized_pattern:
        return False
    pattern_without_slashes = normalized_pattern.strip("/")
    if not pattern_without_slashes:
        return False
    if normalized_pattern.endswith("/"):
        return normalized_path == pattern_without_slashes or normalized_path.startswith(
            pattern_without_slashes + "/"
        )
    if "/" not in pattern_without_slashes:
        return any(
            fnmatch.fnmatch(part, pattern_without_slashes)
            for part in normalized_path.split("/")
        )
    return fnmatch.fnmatch(normalized_path, pattern_without_slashes)


def _detect_language(path: Path) -> str:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "text")


def _looks_binary(sample: bytes) -> bool:
    if b"\0" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _symbol_summary(path: str, text: str) -> dict[str, Any]:
    language = _detect_language(Path(path))
    if language == "python":
        symbols = _python_symbols(text)
    elif language in {"javascript", "typescript"}:
        symbols = _javascript_symbols(text)
    elif language == "markdown":
        symbols = _markdown_symbols(text)
    else:
        symbols = []
    return {"contract_version": SYMBOL_SUMMARY_VERSION, "symbols": symbols}


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
