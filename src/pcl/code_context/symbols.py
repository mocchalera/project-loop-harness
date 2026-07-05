from __future__ import annotations

from pathlib import Path
import re
from typing import Any


SYMBOL_SUMMARY_VERSION = "symbol-summary/v0"


PYTHON_DEF_RE = re.compile(r"^\s*(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")


PYTHON_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b")


JS_FUNCTION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("
)


JS_CLASS_RE = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b"
)


JS_EXPORT_BINDING_RE = re.compile(r"^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")


JS_EXPORT_LIST_RE = re.compile(r"^\s*export\s+\{([^}]+)\}")


MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _empty_symbol_summary() -> dict[str, Any]:
    return {"contract_version": SYMBOL_SUMMARY_VERSION, "symbols": []}


def _python_symbols(text: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        function_match = PYTHON_DEF_RE.match(line)
        if function_match:
            symbols.append(
                {
                    "type": "function",
                    "name": function_match.group(1),
                    "line": line_number,
                    "reason": "python_def",
                }
            )
            continue
        class_match = PYTHON_CLASS_RE.match(line)
        if class_match:
            symbols.append(
                {
                    "type": "class",
                    "name": class_match.group(1),
                    "line": line_number,
                    "reason": "python_class",
                }
            )
    return symbols


def _javascript_symbols(text: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for symbol_type, pattern, reason in [
            ("function", JS_FUNCTION_RE, "js_function"),
            ("class", JS_CLASS_RE, "js_class"),
            ("export", JS_EXPORT_BINDING_RE, "js_export_binding"),
        ]:
            match = pattern.match(line)
            if match:
                symbols.append(
                    {
                        "type": symbol_type,
                        "name": match.group(1),
                        "line": line_number,
                        "reason": reason,
                    }
                )
                break
        export_list = JS_EXPORT_LIST_RE.match(line)
        if export_list:
            for raw_name in export_list.group(1).split(","):
                name = raw_name.strip().split(" as ", 1)[0].strip()
                if name:
                    symbols.append(
                        {
                            "type": "export",
                            "name": name,
                            "line": line_number,
                            "reason": "js_export_list",
                        }
                    )
    return symbols


def _markdown_symbols(text: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = MD_HEADING_RE.match(line)
        if match:
            symbols.append(
                {
                    "type": "heading",
                    "name": match.group(2).strip(),
                    "level": len(match.group(1)),
                    "line": line_number,
                    "reason": "markdown_heading",
                }
            )
    return symbols


def _symbol_names(row: dict[str, Any]) -> list[str]:
    summary = row.get("symbol_summary") if isinstance(row.get("symbol_summary"), dict) else {}
    symbols = summary.get("symbols") if isinstance(summary.get("symbols"), list) else []
    names: list[str] = []
    for symbol in symbols:
        if isinstance(symbol, dict):
            name = str(symbol.get("name") or "")
            if len(name) >= 3 and name not in names:
                names.append(name)
    return names


def _file_mentions(path: Path, symbol_name: str) -> bool:
    try:
        return symbol_name in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
