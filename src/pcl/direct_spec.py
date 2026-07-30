from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any

from .errors import DirectSpecError
from .paths import ProjectPaths
from .stories import TEST_CASE_TYPES


DIRECT_SPEC_CONTRACT_VERSION = "direct-spec/v1"
DIRECT_SPEC_MAX_BYTES = 65_536
DIRECT_SPEC_MAX_PATH_BYTES = 1_024
DIRECT_SPEC_MAX_COMPONENT_BYTES = 255
DIRECT_SPEC_MAX_DEPTH = 8
DIRECT_SPEC_MAX_NODES = 1_024
DIRECT_SPEC_MAX_STORIES = 16
DIRECT_SPEC_MAX_TESTS = 32
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_REFERENCE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


@dataclass
class DirectSpecRootBinding:
    descriptor: int
    requested_root: Path
    identity: tuple[int, int, int]
    _closed: bool = False

    def current_matches(self, paths: ProjectPaths) -> bool:
        if self._closed or paths.root != self.requested_root:
            return False
        try:
            held = os.fstat(self.descriptor)
            current = os.stat(paths.root, follow_symlinks=False)
        except OSError:
            return False
        return (
            stat.S_ISDIR(held.st_mode)
            and _directory_identity(held) == self.identity
            and _directory_identity(current) == self.identity
        )

    def bound_paths(self) -> ProjectPaths:
        if self._closed:
            raise DirectSpecError(
                "Direct spec project-root binding is closed.",
                code="direct_spec_path_changed",
                details={"reason": "root_binding_closed"},
            )
        if sys.platform == "darwin":
            root = Path("/.vol") / str(self.identity[0]) / str(self.identity[1])
        elif Path("/proc/self/fd").is_dir():
            root = Path(f"/proc/self/fd/{self.descriptor}")
        else:  # pragma: no cover - secure-open platforms currently expose one route
            raise DirectSpecError(
                "A descriptor-bound project-root path is unavailable.",
                code="direct_spec_secure_open_unsupported",
                details={"required": ["Darwin file-ID path or /proc/self/fd"]},
            )
        try:
            current = os.stat(root, follow_symlinks=True)
        except OSError as exc:
            raise DirectSpecError(
                "Direct spec project-root binding cannot be resolved.",
                code="direct_spec_path_changed",
                details={"reason": "root_binding_unresolved"},
            ) from exc
        if _directory_identity(current) != self.identity:
            raise DirectSpecError(
                "Direct spec project-root binding changed.",
                code="direct_spec_path_changed",
                details={"reason": "root_binding_identity_changed"},
            )
        return ProjectPaths(root=root)

    def repository_revision(self) -> str | None:
        if self._closed:
            raise DirectSpecError(
                "Direct spec project-root binding is closed.",
                code="direct_spec_path_changed",
                details={"reason": "root_binding_closed"},
            )
        if os.name != "posix":  # pragma: no cover - secure open is POSIX-only
            raise DirectSpecError(
                "Descriptor-bound repository revision is unsupported.",
                code="direct_spec_secure_open_unsupported",
                details={"required": ["POSIX pass_fds and fchdir"]},
            )
        held = os.fstat(self.descriptor)
        if (
            not stat.S_ISDIR(held.st_mode)
            or _directory_identity(held) != self.identity
        ):
            raise DirectSpecError(
                "Direct spec project-root binding changed.",
                code="direct_spec_path_changed",
                details={"reason": "root_binding_identity_changed"},
            )
        launcher = (
            "import os,sys;"
            "fd=int(sys.argv[1]);"
            "os.fchdir(fd);"
            "os.execvp(sys.argv[2],sys.argv[2:])"
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                launcher,
                str(self.descriptor),
                "git",
                "rev-parse",
                "HEAD",
            ],
            pass_fds=(self.descriptor,),
            capture_output=True,
            check=False,
            text=True,
        )
        if completed.returncode != 0:
            return None
        revision = completed.stdout.strip()
        return revision or None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self.descriptor)
        except OSError:
            pass

    def __del__(self) -> None:  # pragma: no cover - deterministic callers close explicitly
        self.close()


@dataclass(frozen=True)
class DirectSpecDocument:
    relative_path: str
    raw: bytes
    value: dict[str, Any]
    raw_sha256: str
    canonical_sha256: str
    root_binding: DirectSpecRootBinding

    @property
    def request_id(self) -> str:
        return str(self.value["request_id"])

    @property
    def stored_spec(self) -> dict[str, Any]:
        return {
            key: self.value[key]
            for key in ("contract_version", "feature", "stories", "tests")
        }

    def close(self) -> None:
        self.root_binding.close()


class _DuplicateKeyError(ValueError):
    pass


def load_direct_spec(paths: ProjectPaths, relative_path: str) -> DirectSpecDocument:
    raw, root_binding = _secure_read_project_file(paths, relative_path)
    try:
        value = _parse_and_validate(raw)
        canonical = _canonical_bytes(value)
        if len(canonical) > DIRECT_SPEC_MAX_BYTES:
            raise DirectSpecError(
                "Canonical direct spec exceeds the byte limit.",
                code="direct_spec_too_large",
                details={
                    "limit_bytes": DIRECT_SPEC_MAX_BYTES,
                    "representation": "canonical",
                },
            )
        return DirectSpecDocument(
            relative_path=relative_path,
            raw=raw,
            value=value,
            raw_sha256=_sha256(raw),
            canonical_sha256=_sha256(canonical),
            root_binding=root_binding,
        )
    except BaseException:
        root_binding.close()
        raise


def _secure_read_project_file(
    paths: ProjectPaths,
    relative_path: str,
) -> tuple[bytes, DirectSpecRootBinding]:
    parts = _validate_relative_path(relative_path)
    _require_secure_open_capabilities()
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptors: list[int] = []
    links: list[tuple[int, str, tuple[int, int, int]]] = []
    try:
        root_fd = os.open(paths.root, directory_flags)
        descriptors.append(root_fd)
        root_stat = os.fstat(root_fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise DirectSpecError(
                "Project root is not a directory.",
                code="direct_spec_path_invalid",
                details={"reason": "root_not_directory"},
            )
        root_identity = _directory_identity(root_stat)
        parent_fd = root_fd
        for component in parts[:-1]:
            child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            opened = os.fstat(child_fd)
            if not stat.S_ISDIR(opened.st_mode):
                os.close(child_fd)
                raise DirectSpecError(
                    "Direct spec path contains a non-directory component.",
                    code="direct_spec_path_invalid",
                    details={"reason": "component_not_directory"},
                )
            descriptors.append(child_fd)
            links.append((parent_fd, component, _directory_identity(opened)))
            parent_fd = child_fd

        leaf_name = parts[-1]
        leaf_fd = os.open(leaf_name, file_flags, dir_fd=parent_fd)
        descriptors.append(leaf_fd)
        before = os.fstat(leaf_fd)
        if not stat.S_ISREG(before.st_mode):
            raise DirectSpecError(
                "Direct spec path is not a regular file.",
                code="direct_spec_path_invalid",
                details={"reason": "leaf_not_regular"},
            )
        if before.st_nlink != 1:
            raise DirectSpecError(
                "Direct spec file must have exactly one hard link.",
                code="direct_spec_path_invalid",
                details={"reason": "leaf_hardlink_not_allowed"},
            )
        if before.st_mode & 0o444 == 0:
            raise DirectSpecError(
                "Direct spec file has no readable permission bits.",
                code="direct_spec_path_invalid",
                details={"reason": "leaf_unreadable"},
            )
        first = _read_bounded(leaf_fd)
        between = os.fstat(leaf_fd)
        os.lseek(leaf_fd, 0, os.SEEK_SET)
        second = _read_bounded(leaf_fd)
        after = os.fstat(leaf_fd)
        current_leaf = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _file_identity(before) != _file_identity(between)
            or _file_identity(between) != _file_identity(after)
            or _file_identity(after) != _file_identity(current_leaf)
            or first != second
        ):
            raise DirectSpecError(
                "Direct spec changed while it was read.",
                code="direct_spec_path_changed",
                details={"reason": "leaf_identity_or_bytes_changed"},
            )
        for ancestor_fd, component, expected_identity in links:
            current = os.stat(
                component,
                dir_fd=ancestor_fd,
                follow_symlinks=False,
            )
            if _directory_identity(current) != expected_identity:
                raise DirectSpecError(
                    "Direct spec path changed while it was read.",
                    code="direct_spec_path_changed",
                    details={"reason": "directory_component_changed"},
                )
        try:
            current_root = os.stat(paths.root, follow_symlinks=False)
        except OSError as exc:
            raise DirectSpecError(
                "Project root changed while the Direct spec was read.",
                code="direct_spec_path_changed",
                details={"reason": "root_identity_changed"},
            ) from exc
        if _directory_identity(current_root) != root_identity:
            raise DirectSpecError(
                "Project root changed while the Direct spec was read.",
                code="direct_spec_path_changed",
                details={"reason": "root_identity_changed"},
            )
        descriptors.remove(root_fd)
        return first, DirectSpecRootBinding(
            descriptor=root_fd,
            requested_root=paths.root,
            identity=root_identity,
        )
    except DirectSpecError:
        raise
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise DirectSpecError(
            "Direct spec path does not resolve to a project-local regular file.",
            code="direct_spec_path_invalid",
            details={"reason": "component_missing"},
        ) from exc
    except OSError as exc:
        reason = (
            "symlink_not_allowed"
            if exc.errno in {errno.ELOOP, errno.EMLINK}
            else "secure_open_failed"
        )
        raise DirectSpecError(
            "Direct spec path could not be opened safely.",
            code="direct_spec_path_invalid",
            details={"reason": reason, "errno": exc.errno},
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _validate_relative_path(relative_path: str) -> tuple[str, ...]:
    if not isinstance(relative_path, str) or not relative_path:
        raise DirectSpecError(
            "Direct spec path must be a non-empty project-relative path.",
            code="direct_spec_path_invalid",
            details={"reason": "empty"},
        )
    try:
        encoded = relative_path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DirectSpecError(
            "Direct spec path must be valid UTF-8.",
            code="direct_spec_path_invalid",
            details={"reason": "invalid_utf8"},
        ) from exc
    if len(encoded) > DIRECT_SPEC_MAX_PATH_BYTES:
        raise DirectSpecError(
            "Direct spec path exceeds the byte limit.",
            code="direct_spec_path_invalid",
            details={"reason": "path_too_long", "limit_bytes": DIRECT_SPEC_MAX_PATH_BYTES},
        )
    if relative_path == "-" or Path(relative_path).is_absolute():
        raise DirectSpecError(
            "Direct spec path must be project-relative.",
            code="direct_spec_path_invalid",
            details={"reason": "not_project_relative"},
        )
    if "\x00" in relative_path:
        raise DirectSpecError(
            "Direct spec path contains a null byte.",
            code="direct_spec_path_invalid",
            details={"reason": "null_byte"},
        )
    normalized = relative_path.replace("\\", "/") if os.name == "nt" else relative_path
    parts = tuple(normalized.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise DirectSpecError(
            "Direct spec path contains an unsafe component.",
            code="direct_spec_path_invalid",
            details={"reason": "unsafe_component"},
        )
    if any(len(part.encode("utf-8")) > DIRECT_SPEC_MAX_COMPONENT_BYTES for part in parts):
        raise DirectSpecError(
            "Direct spec path component exceeds the byte limit.",
            code="direct_spec_path_invalid",
            details={
                "reason": "component_too_long",
                "limit_bytes": DIRECT_SPEC_MAX_COMPONENT_BYTES,
            },
        )
    return parts


def _require_secure_open_capabilities() -> None:
    required_constants = {
        "O_CLOEXEC": getattr(os, "O_CLOEXEC", 0),
        "O_DIRECTORY": getattr(os, "O_DIRECTORY", 0),
        "O_NOFOLLOW": getattr(os, "O_NOFOLLOW", 0),
        "O_NONBLOCK": getattr(os, "O_NONBLOCK", 0),
    }
    if (
        not all(required_constants.values())
        or os.open not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.stat not in os.supports_follow_symlinks
    ):
        raise DirectSpecError(
            "Secure component-by-component direct spec reads are unsupported.",
            code="direct_spec_secure_open_unsupported",
            details={
                "required": [
                    *required_constants,
                    "open.dir_fd",
                    "stat.dir_fd",
                    "stat.follow_symlinks",
                ]
            },
        )


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = DIRECT_SPEC_MAX_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > DIRECT_SPEC_MAX_BYTES:
        raise DirectSpecError(
            "Direct spec exceeds the byte limit.",
            code="direct_spec_too_large",
            details={"limit_bytes": DIRECT_SPEC_MAX_BYTES, "representation": "raw"},
        )
    return content


def _parse_and_validate(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _DuplicateKeyError,
        RecursionError,
        ValueError,
    ) as exc:
        raise DirectSpecError(
            "Direct spec is not valid strict JSON.",
            details={"reason": _json_error_reason(exc)},
        ) from exc
    _validate_resource_budget(parsed)
    return _normalize_schema(parsed)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError(key)
        value[key] = item
    return value


def _reject_non_finite(value: str) -> None:
    raise _DuplicateKeyError(value)


def _validate_resource_budget(value: Any) -> None:
    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > DIRECT_SPEC_MAX_NODES:
            raise DirectSpecError(
                "Direct spec exceeds the node limit.",
                details={"reason": "node_limit", "limit": DIRECT_SPEC_MAX_NODES},
            )
        if depth > DIRECT_SPEC_MAX_DEPTH:
            raise DirectSpecError(
                "Direct spec exceeds the nesting depth limit.",
                details={"reason": "depth_limit", "limit": DIRECT_SPEC_MAX_DEPTH},
            )
        if isinstance(current, dict):
            for key in current:
                _require_valid_unicode(key)
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            _require_valid_unicode(current)


def _normalize_schema(value: Any) -> dict[str, Any]:
    top = _require_object(value, "$")
    _require_keys(
        top,
        required={"contract_version", "request_id", "feature", "stories", "tests"},
        optional=set(),
        path="$",
    )
    if top["contract_version"] != DIRECT_SPEC_CONTRACT_VERSION:
        _invalid("$.contract_version", "unsupported_contract_version")
    request_id = _require_string(top["request_id"], "$.request_id", 8, 128)
    if not _REQUEST_ID.fullmatch(request_id):
        _invalid("$.request_id", "invalid_format")

    feature_source = _require_object(top["feature"], "$.feature")
    _require_keys(
        feature_source,
        required={"name", "surface"},
        optional={"description"},
        path="$.feature",
    )
    feature = {
        "name": _require_string(feature_source["name"], "$.feature.name", 1, 200),
        "surface": _require_string(
            feature_source["surface"], "$.feature.surface", 1, 200
        ),
        "description": _require_string(
            feature_source.get("description", ""),
            "$.feature.description",
            0,
            2_000,
        ),
    }

    story_values = _require_list(top["stories"], "$.stories")
    if not 1 <= len(story_values) <= DIRECT_SPEC_MAX_STORIES:
        _invalid("$.stories", "count_out_of_range")
    stories: list[dict[str, str]] = []
    story_refs: set[str] = set()
    story_semantics: set[tuple[str, ...]] = set()
    for index, item in enumerate(story_values):
        path = f"$.stories[{index}]"
        source = _require_object(item, path)
        _require_keys(
            source,
            required={"ref", "actor", "goal", "expected_behavior"},
            optional={"benefit"},
            path=path,
        )
        story = {
            "ref": _require_reference(source["ref"], f"{path}.ref"),
            "actor": _require_string(source["actor"], f"{path}.actor", 1, 200),
            "goal": _require_string(source["goal"], f"{path}.goal", 1, 4_000),
            "benefit": _require_string(
                source.get("benefit", ""),
                f"{path}.benefit",
                0,
                4_000,
            ),
            "expected_behavior": _require_string(
                source["expected_behavior"],
                f"{path}.expected_behavior",
                1,
                4_000,
            ),
        }
        if story["ref"] in story_refs:
            _invalid(f"{path}.ref", "duplicate_reference")
        semantics = (
            story["actor"],
            story["goal"],
            story["benefit"],
            story["expected_behavior"],
        )
        if semantics in story_semantics:
            _invalid(path, "duplicate_story")
        story_refs.add(story["ref"])
        story_semantics.add(semantics)
        stories.append(story)

    test_values = _require_list(top["tests"], "$.tests")
    if not 1 <= len(test_values) <= DIRECT_SPEC_MAX_TESTS:
        _invalid("$.tests", "count_out_of_range")
    tests: list[dict[str, str]] = []
    test_refs: set[str] = set()
    test_semantics: set[tuple[str, ...]] = set()
    covered_stories: set[str] = set()
    acceptance_count = 0
    for index, item in enumerate(test_values):
        path = f"$.tests[{index}]"
        source = _require_object(item, path)
        _require_keys(
            source,
            required={"ref", "story_ref", "type", "scenario", "expected"},
            optional=set(),
            path=path,
        )
        test = {
            "ref": _require_reference(source["ref"], f"{path}.ref"),
            "story_ref": _require_reference(
                source["story_ref"],
                f"{path}.story_ref",
            ),
            "type": _require_string(source["type"], f"{path}.type", 1, 32),
            "scenario": _require_string(
                source["scenario"],
                f"{path}.scenario",
                1,
                4_000,
            ),
            "expected": _require_string(
                source["expected"],
                f"{path}.expected",
                1,
                4_000,
            ),
        }
        if test["ref"] in test_refs:
            _invalid(f"{path}.ref", "duplicate_reference")
        if test["story_ref"] not in story_refs:
            _invalid(f"{path}.story_ref", "unknown_story_reference")
        if test["type"] not in TEST_CASE_TYPES:
            _invalid(f"{path}.type", "invalid_enum")
        semantics = (
            test["story_ref"],
            test["type"],
            test["scenario"],
            test["expected"],
        )
        if semantics in test_semantics:
            _invalid(path, "duplicate_test")
        test_refs.add(test["ref"])
        test_semantics.add(semantics)
        covered_stories.add(test["story_ref"])
        acceptance_count += int(test["type"] == "acceptance")
        tests.append(test)
    if covered_stories != story_refs:
        _invalid("$.stories", "story_without_test")
    if acceptance_count == 0:
        _invalid("$.tests", "acceptance_test_required")
    return {
        "contract_version": DIRECT_SPEC_CONTRACT_VERSION,
        "request_id": request_id,
        "feature": feature,
        "stories": stories,
        "tests": tests,
    }


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid(path, "object_required")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if type(value) is not list:
        _invalid(path, "array_required")
    return value


def _require_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str],
    path: str,
) -> None:
    keys = set(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - optional)
    if missing:
        _invalid(path, "required_field_missing", fields=missing)
    if unknown:
        _invalid(path, "unknown_field", fields=unknown)


def _require_string(
    value: Any,
    path: str,
    minimum_bytes: int,
    maximum_bytes: int,
) -> str:
    if type(value) is not str:
        _invalid(path, "string_required")
    cleaned = value.strip()
    try:
        size = len(cleaned.encode("utf-8"))
    except UnicodeEncodeError:
        _invalid(path, "invalid_unicode")
    if not minimum_bytes <= size <= maximum_bytes:
        _invalid(
            path,
            "string_size_out_of_range",
            minimum_bytes=minimum_bytes,
            maximum_bytes=maximum_bytes,
        )
    return cleaned


def _require_reference(value: Any, path: str) -> str:
    cleaned = _require_string(value, path, 1, 64)
    if not _REFERENCE.fullmatch(cleaned):
        _invalid(path, "invalid_reference")
    return cleaned


def _invalid(path: str, reason: str, **details: Any) -> None:
    raise DirectSpecError(
        "Direct spec does not satisfy direct-spec/v1.",
        details={"path": path, "reason": reason, **details},
    )


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode))


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _json_error_reason(error: Exception) -> str:
    if isinstance(error, UnicodeDecodeError):
        return "invalid_utf8"
    if isinstance(error, _DuplicateKeyError):
        return "duplicate_key_or_non_finite_number"
    if isinstance(error, RecursionError):
        return "recursion_limit"
    if isinstance(error, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(error, ValueError):
        return "invalid_number"
    return "invalid_json"


def _require_valid_unicode(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise DirectSpecError(
            "Direct spec contains invalid Unicode.",
            details={"reason": "invalid_unicode"},
        ) from None
