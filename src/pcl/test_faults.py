from __future__ import annotations

import json
import os
from pathlib import Path
import signal


_ENABLE_ENV = "PCL_ENABLE_TEST_FAULTS"
_POINT_ENV = "PCL_TEST_FAULT_POINT"
_OCCURRENCE_ENV = "PCL_TEST_FAULT_OCCURRENCE"
_MARKER_ENV = "PCL_TEST_FAULT_MARKER"
_seen: dict[str, int] = {}


def fault_requested(point: str) -> bool:
    return os.environ.get(_ENABLE_ENV) == "1" and os.environ.get(_POINT_ENV) == point


def crash_if_requested(point: str) -> None:
    """Abruptly terminate at an explicitly enabled test-only fault point.

    Two environment variables are required so an accidentally inherited fault
    point cannot affect normal CLI execution. The optional marker is written
    before termination to make subprocess orchestration deterministic.
    """

    if not fault_requested(point):
        return
    occurrence = _seen.get(point, 0) + 1
    _seen[point] = occurrence
    try:
        target = int(os.environ.get(_OCCURRENCE_ENV, "1"))
    except ValueError:
        return
    if occurrence != target:
        return

    marker_value = os.environ.get(_MARKER_ENV)
    if marker_value:
        marker = Path(marker_value)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({"pid": os.getpid(), "point": point, "occurrence": occurrence}) + "\n",
            encoding="utf-8",
        )
    if os.name == "posix":
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(137)
