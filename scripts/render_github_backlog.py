#!/usr/bin/env python3
"""Render the contributor-facing GitHub backlog projection (Issue #4).

Read-only, offline, deterministic. PCL state stays authoritative; this script
only projects repo-verifiable anchors plus optional local PCL state into
issue-ready Markdown/JSON. It never writes to GitHub, never mutates PCL
state, and emits stdout only.

Usage:

    PYTHONPATH=src python scripts/render_github_backlog.py --root . --format markdown

The default mapping is ``scripts/github-issue-map.json`` next to this script;
override it with ``--map`` when projecting a different repository.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without installation.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pcl.github_backlog import main as render_main  # noqa: E402

_DEFAULT_MAP = Path(__file__).resolve().parent / "github-issue-map.json"


def main(argv: list[str] | None = None) -> int:
    forward = list(sys.argv[1:] if argv is None else argv)
    if not any(option == "--map" or option.startswith("--map=") for option in forward):
        forward.extend(["--map", str(_DEFAULT_MAP)])
    return render_main(forward)


if __name__ == "__main__":
    raise SystemExit(main())
