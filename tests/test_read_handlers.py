from __future__ import annotations

from io import StringIO
import json

import pytest

from pcl.command_guide import command_guide, render_command_guide
from pcl.errors import InvalidInputError
from pcl.read_handlers import handle_guide


def test_guide_handler_json_matches_existing_contract_bytes() -> None:
    output = StringIO()

    assert handle_guide("finish", json_output=True, output=output) == 0

    expected = json.dumps(command_guide("finish"), ensure_ascii=False, sort_keys=True) + "\n"
    assert output.getvalue() == expected


def test_guide_handler_text_matches_existing_renderer_bytes() -> None:
    output = StringIO()

    assert handle_guide(None, json_output=False, output=output) == 0

    assert output.getvalue() == render_command_guide(command_guide())


def test_guide_handler_preserves_typed_error_and_writes_nothing() -> None:
    output = StringIO()

    with pytest.raises(InvalidInputError) as caught:
        handle_guide("unknown", json_output=True, output=output)

    assert caught.value.details == {
        "topic": "unknown",
        "supported_topics": ["start", "direct", "finish", "dashboard", "recover"],
    }
    assert output.getvalue() == ""
