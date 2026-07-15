from __future__ import annotations

import json
from typing import TextIO

from .command_guide import command_guide, render_command_guide
from .commands import loop_status, to_pretty_json
from .paths import ProjectPaths


def handle_guide(topic: str | None, *, json_output: bool, output: TextIO) -> int:
    result = command_guide(topic)
    if json_output:
        output.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        output.write(render_command_guide(result))
    return 0


def handle_loop_status(paths: ProjectPaths, *, json_output: bool, output: TextIO) -> int:
    status = loop_status(paths)
    if json_output:
        output.write(json.dumps(status, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        output.write(to_pretty_json(status) + "\n")
    return 0
