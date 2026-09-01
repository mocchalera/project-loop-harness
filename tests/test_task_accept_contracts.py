from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from pcl.mcp_server import (
    APPROVAL_LOCAL_RENDER,
    APPROVAL_READ_ONLY,
    APPROVAL_TASK_ACCEPT_WRITE,
    ProjectLoopMcpServer,
)
from pcl.paths import resolve_paths
from pcl.task_accept import (
    TASK_ACCEPT_ENVELOPE_SCHEMA,
    canonical_task_accept_json,
    task_accept_envelope_golden_fixtures,
    task_accept_human_line,
    validate_task_accept_envelope,
)

from task_accept_helpers import accept_args, prepare_acceptance, run_json


def _request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def _initialize(server: ProjectLoopMcpServer, params: dict | None = None) -> dict:
    response = server.handle(_request("initialize", params or {"protocolVersion": "2025-06-18"}))
    assert response is not None
    if "result" in response:
        assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    return response


def _tool_names(server: ProjectLoopMcpServer) -> list[str]:
    return [tool["name"] for tool in server.handle(_request("tools/list"))["result"]["tools"]]


@pytest.mark.parametrize("mode", [APPROVAL_READ_ONLY, APPROVAL_LOCAL_RENDER])
def test_mcp_default_modes_deny_task_accept_listing_and_dispatch(
    tmp_path: Path,
    capsys,
    mode: str,
) -> None:
    prepare_acceptance(tmp_path, capsys, test_count=1)
    server = ProjectLoopMcpServer(resolve_paths(tmp_path), approval_mode=mode)
    _initialize(server)

    assert "task_accept" not in _tool_names(server)
    denied = server.handle(
        _request(
            "tools/call",
            {"name": "task_accept", "arguments": {"root": "/tmp/other"}},
        )
    )
    assert denied["error"]["code"] == -32003
    assert denied["error"]["data"] == {
        "active_capability": mode,
        "required_capability": APPROVAL_TASK_ACCEPT_WRITE,
        "tool": "task_accept",
    }


def test_mcp_write_mode_uses_cli_service_and_canonical_envelope_bytes(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=1)
    server = ProjectLoopMcpServer(
        resolve_paths(tmp_path), approval_mode=APPROVAL_TASK_ACCEPT_WRITE
    )
    init = _initialize(server)
    assert init["result"]["capabilities"]["experimental"]["pcl"]["taskAcceptWrite"] is True
    assert _tool_names(server) == [
        "get_status",
        "list_features",
        "list_defects",
        "list_escalations",
        "task_accept",
    ]

    response = server.handle(
        _request(
            "tools/call",
            {
                "name": "task_accept",
                "arguments": {
                    "task_id": fixture["task_id"],
                    "artifact": fixture["artifact"],
                    "command": "pytest -q",
                    "summary": "Acceptance verified",
                    "copy": True,
                    "test_ids": fixture["test_ids"],
                },
            },
        )
    )
    result = response["result"]
    canonical = json.dumps(
        result["structuredContent"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert result["content"] == [{"type": "text", "text": canonical}]
    assert result["structuredContent"]["schema_version"] == TASK_ACCEPT_ENVELOPE_SCHEMA["$id"]
    assert TASK_ACCEPT_ENVELOPE_SCHEMA["$id"] in canonical
    assert "[REDACTED_SECRET]" not in canonical
    assert result["isError"] is False


@pytest.mark.parametrize(
    ("segments", "pointer"),
    [
        (("approvalMode",), "/params/approvalMode"),
        (("approval_mode",), "/params/approval_mode"),
        (("capabilities", "pclTaskAcceptWrite"), "/params/capabilities/pclTaskAcceptWrite"),
        (("capabilities", "pcl_task_accept_write"), "/params/capabilities/pcl_task_accept_write"),
        (("capabilities", "taskAccept"), "/params/capabilities/taskAccept"),
        (("capabilities", "task_accept"), "/params/capabilities/task_accept"),
    ],
)
@pytest.mark.parametrize(
    ("pointer_value", "value_type"),
    [
        ("task-accept-write", "string"),
        (True, "boolean"),
        (None, "null"),
        (1, "number"),
        ([], "array"),
        ({}, "object"),
    ],
)
def test_mcp_initialize_cannot_promote_startup_authority(
    tmp_path: Path,
    segments: tuple[str, ...],
    pointer: str,
    pointer_value,
    value_type: str,
) -> None:
    server = ProjectLoopMcpServer(resolve_paths(tmp_path), approval_mode=APPROVAL_READ_ONLY)
    params: dict = {"protocolVersion": "2025-06-18"}
    target = params
    for segment in segments[:-1]:
        target = target.setdefault(segment, {})
    target[segments[-1]] = pointer_value

    response = _initialize(server, params)

    assert response["error"]["code"] == -32003
    assert response["error"]["data"]["attempted_pointers"] == [
        {"pointer": pointer, "value_type": value_type}
    ]


def test_cli_request_hash_is_stable_for_test_order_and_full_length(tmp_path: Path, capsys) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)
    reversed_fixture = {**fixture, "test_ids": list(reversed(fixture["test_ids"]))}

    accepted = run_json(tmp_path, capsys, *accept_args(reversed_fixture))

    request_id = accepted["identity"]["request_id"]
    assert len(request_id) == 64
    assert set(request_id) <= set("0123456789abcdef")
    assert accepted["identity"]["test_ids"] == sorted(fixture["test_ids"])


def test_fresh_and_replay_run_full_strict_exactly_once_and_p0b_is_strict_free(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=1)
    from pcl import task_accept

    original = task_accept.validate_project
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(task_accept, "validate_project", counted)
    accepted = run_json(tmp_path, capsys, *accept_args(fixture))
    assert accepted["ok"] is True
    assert calls == 1
    calls = 0
    replay = run_json(tmp_path, capsys, *accept_args(fixture))
    assert replay["status"] == "no_op"
    assert calls == 1


def test_m5_eight_canonical_json_goldens_are_byte_exact() -> None:
    assert set(TASK_ACCEPT_ENVELOPE_SCHEMA["properties"]) == set(
        TASK_ACCEPT_ENVELOPE_SCHEMA["required"]
    )
    expected = [
        (2836, "c8f3f4e9cd3cfb9a3df0db8e13af901120e5b6cf4d31e8ba2b7b5686070babf8"),
        (3599, "f0f1b3d43554e783610b8068f8db19ae8015a8fde055c1445df87177ac576ca1"),
        (3670, "fe4b7c981deff731bcb7435da9c0be72dd30cee9227e4bf49ce745e978d33c8e"),
        (3492, "e98bc304adac11750ebbf7bb643429ab90678df03d46d7b2d62b6aab98d2ed2f"),
        (3655, "c42d251e8607fd415e299449d1e85836609043242b20c5b41e8299f4db8370b9"),
        (3310, "2f1b4ecccea587bebb30686bc63112888beeb508bb99a07fffe4e319fb2d41a3"),
        (3287, "c4fe686965fe3cbfc02b98ed3402384cf0f268de959979c141d478d85304c64e"),
        (3522, "c2175f627e45fdac1c4c38ea7d184b8dbdeda2ae1d06d7332f0391c4c9159539"),
    ]
    actual = []
    for payload in task_accept_envelope_golden_fixtures():
        validate_task_accept_envelope(payload)
        raw = canonical_task_accept_json(payload).encode("utf-8")
        actual.append((len(raw), hashlib.sha256(raw).hexdigest()))
    assert actual == expected

    assert [
        task_accept_human_line(payload)
        for payload in task_accept_envelope_golden_fixtures()
    ] == [
        "ERROR task_accept task_accept_usage_error: task accept requires at least one --test [action=correct_input_then_retry]",
        "OK task_accept fresh_success: Task T-0042 accepted atomically [authority=EV-A00000000006@106]",
        "OK task_accept exact_replay_success: Task T-0042 acceptance already verified; no changes [authority=EV-A00000000006@106]",
        "ERROR task_accept task_accept_projection_pending: Task T-0042 was accepted, but projection is pending [action=pcl audit flush --json]",
        "OK task_accept accepted_authority_tail_recovery_success: Accepted Task T-0042 tail recovered [authority=EV-A00000000006@106]",
        "ERROR task_accept task_accept_business_attempt_generation_advanced: A new business attempt generation was reserved; repeat the exact request [action=repeat_exact_task_accept_request]",
        "ERROR task_accept task_accept_recovery_identity_corrupt: Task Accept recovery identity is corrupt [action=manual_integrity_review]",
        "ERROR task_accept task_accept_projection_pending: Accepted Task T-0042 remains pending projection [action=pcl audit flush --json]",
    ]


def test_m5_semantic_validation_rejects_unknown_and_bad_accounting() -> None:
    payload = task_accept_envelope_golden_fixtures()[0]
    payload["unknown"] = True
    with pytest.raises(ValueError):
        validate_task_accept_envelope(payload)
    payload.pop("unknown")
    payload["effects"]["db_mutations_total"] += 1
    with pytest.raises(ValueError):
        validate_task_accept_envelope(payload)
