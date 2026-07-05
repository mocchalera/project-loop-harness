from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from .symbols import _symbol_names

if TYPE_CHECKING:
    from .scan import IndexedFile


TEST_HINT_VERSION = "test-hint/v0"


def _attach_test_hints(files: list[IndexedFile]) -> None:
    for item in files:
        item.test_hint = _test_hint_for_file(item, files)


def _empty_test_hint(path: str) -> dict[str, Any]:
    return {
        "contract_version": TEST_HINT_VERSION,
        "is_test": _is_test_path(path),
        "candidate_tests": [],
    }


def _test_hint_for_file(item: IndexedFile, files: list[IndexedFile]) -> dict[str, Any]:
    hint = _empty_test_hint(item.path)
    if hint["is_test"]:
        return hint
    candidates: dict[str, dict[str, Any]] = {}
    source_stem = _stem_key(item.path)
    for possible_test in files:
        if not _is_test_path(possible_test.path):
            continue
        reasons: list[str] = []
        confidence = 0.0
        if _stem_key(possible_test.path) == source_stem:
            reasons.append("filename_match")
            confidence = max(confidence, 0.72)
        if item.language == "python":
            import_reasons = _python_test_import_reasons(possible_test.text, possible_test.path, item)
            if import_reasons:
                reasons.extend(import_reasons)
                confidence = max(confidence, 0.88 if "python_import" in import_reasons else 0.76)
        if reasons:
            candidates[possible_test.path] = {
                "path": possible_test.path,
                "reason": "+".join(sorted(reasons)),
                "confidence": confidence,
            }
    hint["candidate_tests"] = [candidates[path] for path in sorted(candidates)]
    return hint


def _python_test_import_reasons(test_text: str, test_path: str, source: IndexedFile) -> list[str]:
    module = _python_module_name(source.path)
    if not module:
        return []
    imported = _python_imported_modules(test_text)
    reasons: list[str] = []
    if any(imported_module == module or imported_module.startswith(module + ".") for imported_module in imported):
        reasons.append("python_import")
    if (
        "python_import" not in reasons
        and module.startswith("pcl.")
        and "pcl.cli" in imported
        and _test_path_matches_source_surface(test_path, source)
    ):
        reasons.append("python_import:pcl_cli_surface")
    return reasons


def _python_imported_modules(test_text: str) -> set[str]:
    try:
        tree = ast.parse(test_text)
    except SyntaxError:
        return set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
                for alias in node.names:
                    imported.add(f"{node.module}.{alias.name}")
            else:
                for alias in node.names:
                    imported.add(alias.name)
    return imported


def _test_path_matches_source_surface(test_path: str, source: IndexedFile) -> bool:
    test_tokens = _identifier_tokens(Path(test_path).stem)
    source_tokens = _identifier_tokens(Path(source.path).stem)
    for symbol_name in _symbol_names(source.to_public_dict()):
        source_tokens.update(_identifier_tokens(symbol_name))
    source_tokens.discard("test")
    test_tokens.discard("test")
    return bool(test_tokens & source_tokens)


def _test_path_matches_changed_path(test_path: str, changed_path: str) -> bool:
    if not _is_test_path(test_path):
        return False
    test_tokens = _identifier_tokens(Path(test_path).stem)
    changed_tokens: set[str] = set()
    for part in Path(changed_path).parts:
        changed_tokens.update(_identifier_tokens(Path(part).stem))
    for noisy in {"src", "pcl", "test", "tests", "py"}:
        test_tokens.discard(noisy)
        changed_tokens.discard(noisy)
    return bool(test_tokens and changed_tokens and test_tokens & changed_tokens)


def _python_module_name(path: str) -> str:
    if not path.endswith(".py"):
        return ""
    without_suffix = path[:-3]
    if without_suffix.startswith("src/"):
        without_suffix = without_suffix[4:]
    if without_suffix.endswith("/__init__"):
        without_suffix = without_suffix[: -len("/__init__")]
    return without_suffix.replace("/", ".")


def _is_test_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return (
        "tests" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def _stem_key(path: str) -> str:
    name = Path(path).name
    for suffix in [".test", ".spec"]:
        if suffix in name:
            name = name.split(suffix, 1)[0]
    stem = Path(name).stem
    if stem.startswith("test_"):
        stem = stem[5:]
    if stem.endswith("_test"):
        stem = stem[:-5]
    return stem


def _identifier_tokens(value: str) -> set[str]:
    tokens = {
        token.casefold()
        for token in re.split(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])", value)
        if token
    }
    expanded: set[str] = set(tokens)
    if "renderer" in expanded:
        expanded.add("dashboard")
        expanded.add("render")
    return expanded
