from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pcl.cli import main
from pcl.db import connect
from pcl.errors import DirectSpecError, ProjectionPendingError
from pcl.paths import ProjectPaths


VALID_SPEC = {
    "contract_version": "direct-spec/v1",
    "request_id": "ds-test-direct-0001",
    "feature": {
        "name": "Direct setup",
        "surface": "pcl start --direct-spec",
        "description": "Create lifecycle setup atomically.",
    },
    "stories": [
        {
            "ref": "story_atomic",
            "actor": "coding agent",
            "goal": "register setup in one call",
            "benefit": "avoid partial ceremony",
            "expected_behavior": "The full setup commits or nothing commits.",
        }
    ],
    "tests": [
        {
            "ref": "test_atomic",
            "story_ref": "story_atomic",
            "type": "acceptance",
            "scenario": "A valid direct spec is submitted",
            "expected": "All setup entities are created atomically.",
        }
    ],
}


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def _write_spec(
    root: Path,
    spec: dict | None = None,
    *,
    name: str = "direct-spec.json",
) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(VALID_SPEC if spec is None else spec, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _invoke(root: Path, capsys, *, name: str = "direct-spec.json", intent: str = "Ship it"):
    status = main(
        [
            "--root",
            str(root),
            "start",
            intent,
            "--direct-spec",
            name,
            "--json",
        ]
    )
    captured = capsys.readouterr()
    return status, json.loads(captured.out), captured.err


def _counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "goals",
                "tasks",
                "features",
                "user_stories",
                "test_cases",
                "evidence",
                "events",
                "outbox_records",
            )
        }
    finally:
        conn.close()


def _binding_sha256(direct_setup: dict) -> str:
    content = dict(direct_setup)
    content.pop("binding")
    raw = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _subprocess_direct(
    root: Path,
    *,
    spec_name: str = "direct-spec.json",
    intent: str = "Concurrent setup",
    new: bool = False,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments = [
        sys.executable,
        "-m",
        "pcl",
        "--root",
        str(root),
        "start",
        intent,
        "--direct-spec",
        spec_name,
    ]
    if new:
        arguments.append("--new")
    arguments.append("--json")
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    if extra_env:
        environment.update(extra_env)
    return subprocess.run(
        arguments,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _git_repository(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "pcl-test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "PCL Test"],
        check=True,
    )
    (root / "tracked.txt").write_text("root capability\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "root capability"],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_start_help_exposes_direct_spec_without_changing_legacy_flags(capsys) -> None:
    with pytest.raises(SystemExit) as help_exit:
        main(["start", "--help"])
    assert help_exit.value.code == 0
    output = capsys.readouterr().out
    assert "--direct-spec DIRECT_SPEC" in output
    assert "--goal GOAL" in output
    assert "--task TASK" in output
    assert "--skill SKILL" in output


def test_direct_setup_requires_an_initialized_project(tmp_path: Path, capsys) -> None:
    status = main(
        [
            "--root",
            str(tmp_path),
            "start",
            "Cannot initialize implicitly",
            "--direct-spec",
            "direct-spec.json",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status == 3
    assert payload["error"]["code"] == "not_initialized"
    assert not (tmp_path / ".project-loop").exists()


def test_direct_setup_dry_run_and_option_conflict_are_zero_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    before = _counts(tmp_path)

    status = main(
        [
            "--root",
            str(tmp_path),
            "start",
            "Preview direct setup",
            "--direct-spec",
            "direct-spec.json",
            "--dry-run",
            "--json",
        ]
    )
    planned = json.loads(capsys.readouterr().out)
    assert status == 0
    assert planned["status"] == "planned"
    assert planned["mutated"] is False
    assert planned["result"]["direct_spec"]["request_id"] == VALID_SPEC["request_id"]
    assert "mutation_tail" not in planned
    assert _counts(tmp_path) == before

    status = main(
        [
            "--root",
            str(tmp_path),
            "start",
            "Invalid attach",
            "--direct-spec",
            "direct-spec.json",
            "--task",
            "T-0001",
            "--json",
        ]
    )
    conflict = json.loads(capsys.readouterr().out)
    assert status == 2
    assert conflict["error"]["code"] == "direct_setup_option_conflict"
    assert _counts(tmp_path) == before


def test_direct_setup_commits_exact_bundle_event_order_and_receipt_binding(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    before = _counts(tmp_path)

    status, payload, error = _invoke(tmp_path, capsys, intent="Atomic setup")

    assert status == 0
    assert error == ""
    assert payload["status"] == "started"
    assert payload["mutated"] is True
    receipt = payload["result"]["receipt"]
    assert receipt["created_ids"] == {"goal": "G-0001", "task": "T-0001"}
    assert all(isinstance(value, str) for value in receipt["created_ids"].values())
    direct = receipt["direct_setup"]
    assert direct["contract_version"] == "direct-setup-receipt/v1"
    assert direct["binding"] == {
        "algorithm": "sha256",
        "canonical_sha256": _binding_sha256(direct),
        "contract_version": "direct-setup-binding/v1",
    }
    bundle = direct["bundle_created_ids"]
    assert bundle["goal"] == "G-0001"
    assert bundle["task"] == "T-0001"
    assert bundle["feature"] == "F-0001"
    assert bundle["stories"] == ["US-0001"]
    assert bundle["tests"] == ["TC-0001"]
    assert payload["result"]["created_ids"] == {
        "event": payload["result"]["receipt"]["event_id"],
        "evidence": payload["result"]["receipt"]["evidence_id"],
        "goal": "G-0001",
        "task": "T-0001",
    }
    assert payload["result"]["requires_human"] is True
    assert payload["result"]["human_actions"] == [
        {
            "action_kind": "review_story",
            "command": None,
            "expected_after": (
                "A human separately decides whether the Story should be approved or waived."
            ),
            "reason": (
                "Story approval was not supplied by an authenticated human decision "
                "channel and is not inferred."
            ),
            "requires_human": True,
            "target": {"id": "US-0001", "type": "user_story"},
        }
    ]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        start_sequence = int(direct["event_range"]["start_sequence"])
        rows = conn.execute(
            """
            SELECT id, sequence, event_type, entity_type, entity_id, payload_json
            FROM events
            WHERE sequence >= ?
            ORDER BY sequence
            """,
            (start_sequence,),
        ).fetchall()
        assert [str(row["event_type"]) for row in rows] == [
            "goal_created",
            "task_created",
            "work_started",
            "feature_added",
            "task_feature_linked",
            "user_story_drafted",
            "feature_status_updated",
            "test_case_planned",
        ]
        assert len(rows) == 8
        assert str(rows[2]["id"]) == payload["result"]["receipt"]["event_id"]
        event_receipt = json.loads(str(rows[2]["payload_json"]))["receipt"]
        evidence = conn.execute(
            "SELECT type, path, command, summary FROM evidence WHERE id = ?",
            (payload["result"]["receipt"]["evidence_id"],),
        ).fetchone()
        assert json.loads(str(evidence["summary"])) == event_receipt
        assert event_receipt == {
            key: value
            for key, value in receipt.items()
            if key not in {"evidence_id", "event_id"}
        }
        assert str(evidence["type"]) == "start-receipt/v1"
        assert str(evidence["path"]) == "inline:start:T-0001"
        assert str(evidence["command"]) == "pcl start"
        assert (
            conn.execute(
                "SELECT status FROM features WHERE id = 'F-0001'"
            ).fetchone()["status"]
            == "needs_test"
        )
        assert (
            conn.execute(
                "SELECT status FROM user_stories WHERE id = 'US-0001'"
            ).fetchone()["status"]
            == "draft"
        )
        assert (
            conn.execute(
                "SELECT status FROM test_cases WHERE id = 'TC-0001'"
            ).fetchone()["status"]
            == "planned"
        )
        outbox = conn.execute(
            """
            SELECT event_id, COUNT(*) AS count
            FROM outbox_records
            WHERE event_id IN (
              SELECT id FROM events WHERE sequence >= ?
            )
            GROUP BY event_id
            """,
            (start_sequence,),
        ).fetchall()
        assert len(outbox) == 8
        assert {int(row["count"]) for row in outbox} == {1}
    finally:
        conn.close()

    after = _counts(tmp_path)
    assert after["goals"] - before["goals"] == 1
    assert after["tasks"] - before["tasks"] == 1
    assert after["features"] - before["features"] == 1
    assert after["user_stories"] - before["user_stories"] == 1
    assert after["test_cases"] - before["test_cases"] == 1
    assert after["evidence"] - before["evidence"] == 1
    assert after["events"] - before["events"] == 8
    assert after["outbox_records"] - before["outbox_records"] == 8


def test_direct_setup_multiple_stories_and_tests_preserve_array_order(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    spec = json.loads(json.dumps(VALID_SPEC))
    spec["stories"].append(
        {
            "ref": "story_retry",
            "actor": "coding agent",
            "goal": "retry the exact request safely",
            "benefit": "avoid duplicate setup",
            "expected_behavior": "The stored setup is reused.",
        }
    )
    spec["tests"].extend(
        [
            {
                "ref": "test_retry",
                "story_ref": "story_retry",
                "type": "acceptance",
                "scenario": "The exact request is retried",
                "expected": "No additional bundle is created.",
            },
            {
                "ref": "test_atomic_unit",
                "story_ref": "story_atomic",
                "type": "unit",
                "scenario": "The event plan is constructed",
                "expected": "Its order is deterministic.",
            },
        ]
    )
    _write_spec(tmp_path, spec)

    status, payload, error = _invoke(tmp_path, capsys)

    assert (status, error) == (0, "")
    direct = payload["result"]["receipt"]["direct_setup"]
    assert direct["bundle_created_ids"]["stories"] == ["US-0001", "US-0002"]
    assert direct["bundle_created_ids"]["tests"] == [
        "TC-0001",
        "TC-0002",
        "TC-0003",
    ]
    assert direct["event_range"]["count"] == 11
    assert [
        item["event_type"] for item in direct["event_range"]["ordered"]
    ] == [
        "goal_created",
        "task_created",
        "work_started",
        "feature_added",
        "task_feature_linked",
        "user_story_drafted",
        "user_story_drafted",
        "feature_status_updated",
        "test_case_planned",
        "test_case_planned",
        "test_case_planned",
    ]
    assert len(payload["result"]["human_actions"]) == 2
    assert all(
        action["command"] is None
        for action in payload["result"]["human_actions"]
    )


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda spec: spec | {"approval": True},
            "direct_spec_invalid",
        ),
        (
            lambda spec: spec
            | {
                "tests": [
                    {
                        **spec["tests"][0],
                        "type": "unsupported",
                    }
                ]
            },
            "direct_spec_invalid",
        ),
        (
            lambda spec: spec
            | {
                "tests": [
                    {
                        **spec["tests"][0],
                        "story_ref": "missing_story",
                    }
                ]
            },
            "direct_spec_invalid",
        ),
        (
            lambda spec: spec | {"request_id": "short"},
            "direct_spec_invalid",
        ),
        (
            lambda spec: spec
            | {"feature": {**spec["feature"], "name": "x" * 201}},
            "direct_spec_invalid",
        ),
        (
            lambda spec: spec
            | {
                "feature": {
                    **spec["feature"],
                    "name": True,
                }
            },
            "direct_spec_invalid",
        ),
        (
            lambda spec: spec
            | {
                "stories": [
                    *spec["stories"],
                    {
                        **spec["stories"][0],
                        "ref": "uncovered_story",
                        "goal": "remain uncovered",
                    },
                ]
            },
            "direct_spec_invalid",
        ),
        (
            lambda spec: spec
            | {
                "tests": [
                    {
                        **spec["tests"][0],
                        "type": "unit",
                    }
                ]
            },
            "direct_spec_invalid",
        ),
    ],
)
def test_direct_spec_schema_failures_are_typed_and_zero_mutation(
    tmp_path: Path,
    capsys,
    mutate,
    expected_code: str,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path, mutate(json.loads(json.dumps(VALID_SPEC))))
    before = _counts(tmp_path)

    status, payload, _ = _invoke(tmp_path, capsys)

    assert status == 2
    assert payload["error"]["code"] == expected_code
    assert _counts(tmp_path) == before


@pytest.mark.parametrize(
    "raw",
    [
        b'{"contract_version":"direct-spec/v1","request_id":"ds-12345678",'
        b'"feature":{"name":"one","name":"two","surface":"cli"},'
        b'"stories":[],"tests":[]}',
        b'{"contract_version":"direct-spec/v1","request_id":"ds-12345678",'
        b'"feature":{"name":"one","surface":"cli"},'
        b'"stories":[],"tests":[],"extra":NaN}',
        b"\xef\xbb\xbf{}",
        b"{",
    ],
)
def test_direct_spec_rejects_duplicate_nonfinite_bom_and_invalid_json(
    tmp_path: Path,
    capsys,
    raw: bytes,
) -> None:
    _init(tmp_path, capsys)
    (tmp_path / "direct-spec.json").write_bytes(raw)
    before = _counts(tmp_path)

    status, payload, _ = _invoke(tmp_path, capsys)

    assert status == 2
    assert payload["error"]["code"] == "direct_spec_invalid"
    assert _counts(tmp_path) == before


def test_direct_spec_cli_normalizes_surrogate_and_huge_integer_errors(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    before = _counts(tmp_path)

    surrogate = json.loads(json.dumps(VALID_SPEC))
    surrogate["feature"]["name"] = "\ud800"
    (tmp_path / "direct-spec.json").write_text(
        json.dumps(surrogate, ensure_ascii=True),
        encoding="utf-8",
    )
    rejected_surrogate = _subprocess_direct(tmp_path)
    assert rejected_surrogate.returncode == 2
    assert rejected_surrogate.stderr == ""
    surrogate_error = json.loads(rejected_surrogate.stdout)
    assert surrogate_error["error"]["code"] == "direct_spec_invalid"
    assert surrogate_error["error"]["details"]["reason"] == "invalid_unicode"

    raw = json.dumps(VALID_SPEC).replace(
        json.dumps(VALID_SPEC["request_id"]),
        "9" * 4_301,
        1,
    )
    (tmp_path / "direct-spec.json").write_bytes(raw.encode("utf-8"))
    rejected_integer = _subprocess_direct(tmp_path)
    assert rejected_integer.returncode == 2
    assert rejected_integer.stderr == ""
    integer_error = json.loads(rejected_integer.stdout)
    assert integer_error["error"]["code"] == "direct_spec_invalid"
    assert integer_error["error"]["details"]["reason"] == "invalid_number"
    assert _counts(tmp_path) == before


def test_direct_spec_rejects_resource_bombs_and_unsafe_paths_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    before = _counts(tmp_path)

    (tmp_path / "direct-spec.json").write_bytes(b" " * 65_537)
    status, oversized, _ = _invoke(tmp_path, capsys)
    assert status == 2
    assert oversized["error"]["code"] == "direct_spec_too_large"
    assert _counts(tmp_path) == before

    outside = tmp_path.parent / "outside-direct-spec.json"
    outside.write_text(json.dumps(VALID_SPEC), encoding="utf-8")
    status, outside_error, _ = _invoke(
        tmp_path,
        capsys,
        name="../outside-direct-spec.json",
    )
    assert status == 2
    assert outside_error["error"]["code"] == "direct_spec_path_invalid"
    assert _counts(tmp_path) == before

    target = tmp_path / "real-direct-spec.json"
    target.write_text(json.dumps(VALID_SPEC), encoding="utf-8")
    link = tmp_path / "direct-spec.json"
    link.unlink(missing_ok=True)
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    status, symlink_error, _ = _invoke(tmp_path, capsys)
    assert status == 2
    assert symlink_error["error"]["code"] == "direct_spec_path_invalid"
    assert _counts(tmp_path) == before


def test_direct_spec_rejects_hardlinked_leaf_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    spec_path = _write_spec(tmp_path)
    before = _counts(tmp_path)
    try:
        os.link(spec_path, tmp_path / "direct-spec-hardlink.json")
    except OSError:
        pytest.skip("hardlinks are unavailable on this platform")

    status, rejected, stderr = _invoke(tmp_path, capsys)

    assert status == 2
    assert stderr == ""
    assert rejected["error"]["code"] == "direct_spec_path_invalid"
    assert rejected["error"]["details"]["reason"] == "leaf_hardlink_not_allowed"
    assert _counts(tmp_path) == before


def test_direct_spec_rejects_fifo_and_null_byte_paths_without_blocking(
    tmp_path: Path,
    capsys,
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    _init(tmp_path, capsys)
    before = _counts(tmp_path)
    fifo = tmp_path / "direct-spec.json"
    os.mkfifo(fifo)

    status, special, _ = _invoke(tmp_path, capsys)
    assert status == 2
    assert special["error"]["code"] == "direct_spec_path_invalid"

    status, null_path, _ = _invoke(
        tmp_path,
        capsys,
        name="direct-spec.json\x00ignored",
    )
    assert status == 2
    assert null_path["error"]["details"]["reason"] == "null_byte"
    assert _counts(tmp_path) == before


def test_direct_spec_detects_parent_swap_and_same_inode_overwrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import pcl.direct_spec as direct_spec_module

    root = tmp_path.resolve()
    safe = root / "safe"
    safe.mkdir()
    original_path = _write_spec(root, name="safe/direct-spec.json")
    original_read = direct_spec_module.os.read
    swapped = False

    def read_then_swap(descriptor: int, size: int) -> bytes:
        nonlocal swapped
        content = original_read(descriptor, size)
        if content and not swapped:
            swapped = True
            safe.rename(root / "safe-original")
            safe.mkdir()
            _write_spec(root, name="safe/direct-spec.json")
        return content

    monkeypatch.setattr(direct_spec_module.os, "read", read_then_swap)
    with pytest.raises(DirectSpecError) as parent_swap:
        direct_spec_module.load_direct_spec(
            ProjectPaths(root=root),
            "safe/direct-spec.json",
        )
    assert parent_swap.value.code == "direct_spec_path_changed"
    assert parent_swap.value.details["reason"] == "directory_component_changed"

    monkeypatch.setattr(direct_spec_module.os, "read", original_read)
    original_path = root / "safe-original" / "direct-spec.json"
    raw = original_path.read_bytes()
    alternate = raw.replace(b"Direct setup", b"Direct setuq", 1)
    assert len(alternate) == len(raw) and alternate != raw
    overwritten = False

    def read_then_overwrite(descriptor: int, size: int) -> bytes:
        nonlocal overwritten
        content = original_read(descriptor, size)
        if content and not overwritten:
            overwritten = True
            original_path.write_bytes(alternate)
        return content

    monkeypatch.setattr(direct_spec_module.os, "read", read_then_overwrite)
    with pytest.raises(DirectSpecError) as overwrite:
        direct_spec_module.load_direct_spec(
            ProjectPaths(root=root),
            "safe-original/direct-spec.json",
        )
    assert overwrite.value.code == "direct_spec_path_changed"
    assert overwrite.value.details["reason"] == "leaf_identity_or_bytes_changed"


def test_retained_root_reader_reopens_components_from_descriptor(
    tmp_path: Path,
) -> None:
    from pcl.direct_spec import load_direct_spec, secure_read_project_artifact

    target = tmp_path / "target"
    displaced = tmp_path / "displaced"
    artifact = target / "artifacts" / "acceptance.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("verified acceptance\n", encoding="utf-8")
    _write_spec(target)
    document = load_direct_spec(ProjectPaths(root=target), "direct-spec.json")
    try:
        bound_paths = document.root_binding.bound_paths()
        assert (
            bound_paths.retained_root_descriptor
            == document.root_binding.descriptor
        )
        assert bound_paths.retained_root_identity == document.root_binding.identity
        target.rename(displaced)

        content, second_binding = secure_read_project_artifact(
            bound_paths,
            "artifacts/acceptance.txt",
            max_bytes=65_536,
        )
        try:
            assert content == b"verified acceptance\n"
            assert second_binding.identity == document.root_binding.identity
        finally:
            second_binding.close()
    finally:
        document.close()


def test_direct_spec_enforces_exact_depth_and_node_boundaries(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    before = _counts(tmp_path)

    def nested_value(maximum_depth: int) -> object:
        value: object = "leaf"
        for _ in range(maximum_depth - 2):
            value = [value]
        return value

    depth_eight = json.loads(json.dumps(VALID_SPEC))
    depth_eight["padding"] = nested_value(8)
    _write_spec(tmp_path, depth_eight)
    status, accepted_budget, _ = _invoke(tmp_path, capsys)
    assert status == 2
    assert accepted_budget["error"]["details"]["reason"] == "unknown_field"

    depth_nine = json.loads(json.dumps(VALID_SPEC))
    depth_nine["padding"] = nested_value(9)
    _write_spec(tmp_path, depth_nine)
    status, rejected_depth, _ = _invoke(tmp_path, capsys)
    assert status == 2
    assert rejected_depth["error"]["details"]["reason"] == "depth_limit"

    def node_count(value: object) -> int:
        if isinstance(value, dict):
            return 1 + sum(node_count(item) for item in value.values())
        if isinstance(value, list):
            return 1 + sum(node_count(item) for item in value)
        return 1

    baseline = node_count(VALID_SPEC)
    nodes_1024 = json.loads(json.dumps(VALID_SPEC))
    nodes_1024["padding"] = [0] * (1_024 - baseline - 1)
    assert node_count(nodes_1024) == 1_024
    _write_spec(tmp_path, nodes_1024)
    status, accepted_nodes, _ = _invoke(tmp_path, capsys)
    assert status == 2
    assert accepted_nodes["error"]["details"]["reason"] == "unknown_field"

    nodes_1025 = json.loads(json.dumps(VALID_SPEC))
    nodes_1025["padding"] = [0] * (1_025 - baseline - 1)
    assert node_count(nodes_1025) == 1_025
    _write_spec(tmp_path, nodes_1025)
    status, rejected_nodes, _ = _invoke(tmp_path, capsys)
    assert status == 2
    assert rejected_nodes["error"]["details"]["reason"] == "node_limit"
    assert _counts(tmp_path) == before


def test_direct_setup_root_swap_cannot_commit_old_spec_to_replacement_project(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pcl.start as start_module

    target = tmp_path / "target"
    replacement = tmp_path / "replacement"
    displaced = tmp_path / "displaced"
    _init(target, capsys)
    _init(replacement, capsys)
    old_spec = json.loads(json.dumps(VALID_SPEC))
    old_spec["request_id"] = "ds-old-root-request"
    _write_spec(target, old_spec)
    replacement_spec = json.loads(json.dumps(VALID_SPEC))
    replacement_spec["request_id"] = "ds-new-root-request"
    _write_spec(replacement, replacement_spec)
    replacement_before = _counts(replacement)
    original_validate = start_module.validate_project
    swapped = False

    def swap_root_then_validate(paths, *args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            target.rename(displaced)
            replacement.rename(target)
        return original_validate(paths, *args, **kwargs)

    monkeypatch.setattr(start_module, "validate_project", swap_root_then_validate)

    status, rejected, stderr = _invoke(target, capsys)

    assert status == 1
    assert stderr == ""
    assert rejected["error"]["code"] == "direct_setup_root_changed"
    assert _counts(target) == replacement_before
    assert _counts(displaced)["goals"] == 0


@pytest.mark.parametrize(
    "barrier",
    (
        "before_db_connect",
        "after_db_connect",
        "after_precommit_check",
        "after_sqlite_commit_before_projector",
        "after_projection_before_tail",
    ),
)
def test_direct_setup_root_capability_spans_commit_projection_and_tail(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    barrier: str,
) -> None:
    import pcl.direct_setup as direct_setup_module
    import pcl.outbox as outbox_module
    import pcl.start as start_module

    target = tmp_path / "target"
    replacement = tmp_path / "replacement"
    displaced = tmp_path / "displaced"
    _init(target, capsys)
    _init(replacement, capsys)
    spec = json.loads(json.dumps(VALID_SPEC))
    spec["request_id"] = f"ds-root-capability-{barrier}"
    _write_spec(target, spec)
    _write_spec(replacement, spec)
    target_before = _counts(target)
    replacement_before = _counts(replacement)
    swapped = False

    def swap_roots() -> None:
        nonlocal swapped
        if swapped:
            return
        swapped = True
        target.rename(displaced)
        replacement.rename(target)

    original_connect = direct_setup_module.connect_mutation
    if barrier == "before_db_connect":

        def connect_after_swap(paths, *args, **kwargs):
            swap_roots()
            return original_connect(paths, *args, **kwargs)

        monkeypatch.setattr(
            direct_setup_module,
            "connect_mutation",
            connect_after_swap,
        )
    elif barrier == "after_db_connect":

        def connect_then_swap(paths, *args, **kwargs):
            conn = original_connect(paths, *args, **kwargs)
            swap_roots()
            return conn

        monkeypatch.setattr(
            direct_setup_module,
            "connect_mutation",
            connect_then_swap,
        )
    elif barrier == "after_precommit_check":
        original_require = direct_setup_module._require_bound_root

        monkeypatch.setattr(
            direct_setup_module,
            "_requires_original_path_binding_at_commit",
            lambda paths: True,
        )

        def require_then_swap(spec_document, paths, *, phase):
            original_require(spec_document, paths, phase=phase)
            if phase == "before_authoritative_commit":
                swap_roots()

        monkeypatch.setattr(
            direct_setup_module,
            "_require_bound_root",
            require_then_swap,
        )
    elif barrier == "after_sqlite_commit_before_projector":
        original_project = outbox_module.project_pending_events

        def swap_then_project(paths, *args, **kwargs):
            swap_roots()
            return original_project(paths, *args, **kwargs)

        monkeypatch.setattr(
            outbox_module,
            "project_pending_events",
            swap_then_project,
        )
    else:
        original_tail = start_module.apply_direct_setup_tail

        def swap_then_tail(paths, payload, *args, **kwargs):
            swap_roots()
            return original_tail(paths, payload, *args, **kwargs)

        monkeypatch.setattr(
            start_module,
            "apply_direct_setup_tail",
            swap_then_tail,
        )

    status, result, stderr = _invoke(target, capsys)

    assert stderr == ""
    assert swapped is True
    if barrier in {"before_db_connect", "after_db_connect", "after_precommit_check"}:
        assert status == 1
        assert result["error"]["code"] == "direct_setup_root_changed"
        if barrier == "after_precommit_check":
            assert result["error"]["details"]["phase"] == "physical_commit"
        assert _counts(displaced) == target_before
        assert _counts(target) == replacement_before
        return

    assert status == 0
    assert result["status"] == "started"
    assert result["mutated"] is True
    assert _counts(displaced)["goals"] - target_before["goals"] == 1
    assert _counts(displaced)["tasks"] - target_before["tasks"] == 1
    assert _counts(displaced)["events"] - target_before["events"] == 8
    assert _counts(displaced)["outbox_records"] - target_before["outbox_records"] == 8
    assert _counts(target) == replacement_before

    retry_status, retry, retry_stderr = _invoke(displaced, capsys)
    assert retry_status == 0
    assert retry_stderr == ""
    assert retry["status"] == "already_started"
    assert retry["mutated"] is False
    assert _counts(target) == replacement_before


@pytest.mark.parametrize(
    "barrier",
    (
        "tail_hwm_before",
        "tail_hwm_after",
        "tail_validation",
        "tail_validation_projection",
        "tail_routing",
        "tail_render",
        "tail_recovery_target",
        "tail_partial_result",
    ),
)
def test_direct_setup_root_capability_spans_tail_production_boundaries(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    barrier: str,
) -> None:
    import pcl.mutation_tail as tail_module
    from pcl.validators import ValidationResult

    target = tmp_path / "target"
    replacement = tmp_path / "replacement"
    displaced = tmp_path / "displaced"
    _init(target, capsys)
    _init(replacement, capsys)
    spec = json.loads(json.dumps(VALID_SPEC))
    spec["request_id"] = f"ds-tail-production-{barrier}"
    _write_spec(target, spec)
    _write_spec(replacement, spec)
    target_before = _counts(target)
    replacement_before = _counts(replacement)
    swapped = False

    def swap_roots() -> None:
        nonlocal swapped
        if swapped:
            return
        swapped = True
        target.rename(displaced)
        replacement.rename(target)

    if barrier in {"tail_hwm_before", "tail_hwm_after"}:
        original = tail_module._state_high_watermark

        def high_watermark(paths):
            if barrier == "tail_hwm_before":
                swap_roots()
            result = original(paths)
            if barrier == "tail_hwm_after":
                swap_roots()
            return result

        monkeypatch.setattr(tail_module, "_state_high_watermark", high_watermark)
    elif barrier == "tail_validation":
        original = tail_module.validate_project

        def validate(paths, *args, **kwargs):
            swap_roots()
            return original(paths, *args, **kwargs)

        monkeypatch.setattr(tail_module, "validate_project", validate)
    elif barrier == "tail_validation_projection":
        original = tail_module.project_validation_result

        def project(*args, **kwargs):
            swap_roots()
            return original(*args, **kwargs)

        monkeypatch.setattr(tail_module, "project_validation_result", project)
    elif barrier == "tail_routing":
        original = tail_module.next_action

        def route(*args, **kwargs):
            swap_roots()
            return original(*args, **kwargs)

        monkeypatch.setattr(tail_module, "next_action", route)
    elif barrier == "tail_render":
        original = tail_module._render_dashboard_with_lock

        def render(*args, **kwargs):
            swap_roots()
            return original(*args, **kwargs)

        monkeypatch.setattr(tail_module, "_render_dashboard_with_lock", render)
    elif barrier == "tail_recovery_target":
        original = tail_module._read_only_recovery

        def recovery(*args, **kwargs):
            swap_roots()
            return original(*args, **kwargs)

        monkeypatch.setattr(tail_module, "_read_only_recovery", recovery)
    else:
        failed_validation = ValidationResult()
        failed_validation.add_error(
            "Injected post-commit validation failure.",
            code="injected_post_commit_validation_failure",
            entity={"type": "task", "id": "T-0001"},
        )
        monkeypatch.setattr(
            tail_module,
            "validate_project",
            lambda *args, **kwargs: failed_validation,
        )
        original = tail_module._result_with_tail

        def partial_result(*args, **kwargs):
            swap_roots()
            return original(*args, **kwargs)

        monkeypatch.setattr(tail_module, "_result_with_tail", partial_result)

    status, result, stderr = _invoke(target, capsys)

    assert swapped is True
    assert result["status"] == "started"
    assert result["mutated"] is True
    assert result["mutation_tail"]["mutation_committed"] is True
    assert result["mutation_tail"]["safe_to_retry_original"] is False
    assert _counts(displaced)["goals"] - target_before["goals"] == 1
    assert _counts(displaced)["tasks"] - target_before["tasks"] == 1
    assert _counts(target) == replacement_before
    if barrier == "tail_partial_result":
        assert status == 6
        assert result["post_commit_status"] == "partial"
        assert result["mutation_committed"] is True
        assert result["safe_to_retry_original"] is False
        assert "mutation_committed=true" in stderr
    else:
        assert status == 0
        assert stderr == ""


@pytest.mark.parametrize("swap_timing", ("before_open", "after_open"))
def test_direct_setup_tail_read_only_db_open_cannot_rebind_resolved_path(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    swap_timing: str,
) -> None:
    import pcl.db as db_module
    import pcl.mutation_tail as tail_module
    from pcl.validators import ValidationResult

    target = tmp_path / "target"
    replacement = tmp_path / "replacement"
    displaced = tmp_path / "displaced"
    _init(target, capsys)
    _init(replacement, capsys)
    spec = json.loads(json.dumps(VALID_SPEC))
    spec["request_id"] = "ds-tail-read-only-db-root-swap"
    _write_spec(target, spec)
    _write_spec(replacement, spec)
    target_before = _counts(target)
    replacement_before = _counts(replacement)
    failed_validation = ValidationResult()
    failed_validation.add_error(
        "Injected post-commit validation failure.",
        code="injected_post_commit_validation_failure",
        entity={"type": "task", "id": "T-0001"},
    )
    monkeypatch.setattr(
        tail_module,
        "validate_project",
        lambda *args, **kwargs: failed_validation,
    )
    original_connect = db_module.sqlite3.connect
    swapped = False

    def connect_after_uri_construction(database, *args, **kwargs):
        nonlocal swapped
        should_swap = (
            not swapped
            and isinstance(database, str)
            and database.startswith("file:")
            and "mode=ro" in database
        )
        if should_swap and swap_timing == "before_open":
            swapped = True
            target.rename(displaced)
            replacement.rename(target)
        connection = original_connect(database, *args, **kwargs)
        if should_swap and swap_timing == "after_open":
            swapped = True
            target.rename(displaced)
            replacement.rename(target)
        return connection

    monkeypatch.setattr(db_module.sqlite3, "connect", connect_after_uri_construction)

    status, result, stderr = _invoke(target, capsys)

    assert swapped is True
    assert status == 6
    assert result["status"] == "started"
    assert result["mutated"] is True
    assert result["post_commit_status"] == "partial"
    assert result["mutation_committed"] is True
    assert result["safe_to_retry_original"] is False
    recovery = result["recovery"]
    displaced_stat = os.stat(displaced, follow_symlinks=False)
    assert recovery == {
        "contract_version": "direct-tail-recovery/v1",
        "authority": "retained_root_file_identity",
        "command": None,
        "operation": {
            "arguments": {
                "active_only": False,
                "summary": True,
                "target": "T-0001",
            },
            "kind": "validate_exact_target",
        },
        "retry_original": False,
        "root_identity": {
            "device": displaced_stat.st_dev,
            "file_type": "directory",
            "inode": displaced_stat.st_ino,
        },
        "target": {"id": "T-0001", "type": "task"},
    }
    assert "mutation_committed=true" in stderr
    assert _counts(displaced)["goals"] - target_before["goals"] == 1
    assert _counts(displaced)["tasks"] - target_before["tasks"] == 1
    assert _counts(target) == replacement_before


def test_direct_setup_changed_false_tail_exception_is_exit6_bound_partial(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pcl.mutation_tail as tail_module

    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    status, started, stderr = _invoke(tmp_path, capsys)
    assert status == 0
    assert started["mutated"] is True
    assert stderr == ""
    before = _counts(tmp_path)

    monkeypatch.setattr(
        tail_module,
        "_state_high_watermark",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("injected idempotent tail failure")
        ),
    )

    status, partial, stderr = _invoke(tmp_path, capsys)

    assert status == 6
    assert partial["status"] == "already_started"
    assert partial["mutated"] is False
    assert partial["post_commit_status"] == "partial"
    assert partial["mutation_committed"] is False
    assert partial["safe_to_retry_original"] is False
    assert partial["mutation_tail"]["errors"] == [
        {
            "code": "post_commit_failed",
            "message": "injected idempotent tail failure",
            "phase": "direct_setup_tail",
        }
    ]
    assert partial["recovery"]["authority"] == "retained_root_file_identity"
    assert partial["recovery"]["command"] is None
    assert partial["recovery"]["target"] == {"id": "T-0001", "type": "task"}
    assert "mutation_committed=false" in stderr
    assert "safe_to_retry_original=false" in stderr
    assert _counts(tmp_path) == before


def test_direct_setup_changed_true_tail_exception_is_exit6_bound_partial(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pcl.mutation_tail as tail_module

    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    before = _counts(tmp_path)
    monkeypatch.setattr(
        tail_module,
        "_state_high_watermark",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("injected committed tail failure")
        ),
    )

    status, partial, stderr = _invoke(tmp_path, capsys)

    assert status == 6
    assert partial["status"] == "started"
    assert partial["mutated"] is True
    assert partial["post_commit_status"] == "partial"
    assert partial["mutation_committed"] is True
    assert partial["safe_to_retry_original"] is False
    assert partial["mutation_tail"]["errors"] == [
        {
            "code": "post_commit_failed",
            "message": "injected committed tail failure",
            "phase": "direct_setup_tail",
        }
    ]
    assert partial["recovery"]["authority"] == "retained_root_file_identity"
    assert partial["recovery"]["command"] is None
    assert "mutation_committed=true" in stderr
    assert "safe_to_retry_original=false" in stderr
    assert _counts(tmp_path)["goals"] - before["goals"] == 1
    assert _counts(tmp_path)["tasks"] - before["tasks"] == 1


def test_direct_spec_root_fd_resolves_git_revision_after_rename(
    tmp_path: Path,
) -> None:
    from pcl.direct_spec import load_direct_spec

    target = tmp_path / "target"
    displaced = tmp_path / "displaced"
    replacement = tmp_path / "replacement"
    revision = _git_repository(target)
    _write_spec(target)
    document = load_direct_spec(ProjectPaths(root=target), "direct-spec.json")
    try:
        target.rename(displaced)
        replacement.mkdir()

        assert document.root_binding.repository_revision() == revision
    finally:
        document.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Linux-only /proc root-capability Direct Setup E2E",
)
def test_direct_setup_git_revision_linux_e2e(tmp_path: Path, capsys) -> None:
    revision = _git_repository(tmp_path)
    _init(tmp_path, capsys)
    _write_spec(tmp_path)

    status, started, stderr = _invoke(tmp_path, capsys)

    assert status == 0
    assert stderr == ""
    assert started["result"]["receipt"]["repository_revision"] == revision
    assert started["result"]["repository_revision"]["initial"] == revision


def test_direct_setup_rolls_back_at_every_event_insertion(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    import pcl.direct_setup as direct_setup_module
    from pcl.direct_spec import load_direct_spec

    original_append_event = direct_setup_module.append_event
    for failure_position in range(1, 9):
        root = tmp_path / f"event-{failure_position}"
        _init(root, capsys)
        _write_spec(root)
        paths = ProjectPaths(root=root.resolve())
        spec = load_direct_spec(paths, "direct-spec.json")
        before = _counts(root)
        jsonl_before = paths.events_path.read_bytes()
        dashboard_before = (
            paths.dashboard_html.read_bytes(),
            paths.dashboard_data.read_bytes(),
        )
        calls = 0

        def fail_at_event(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == failure_position:
                raise RuntimeError(f"injected event failure {failure_position}")
            return original_append_event(*args, **kwargs)

        monkeypatch.setattr(direct_setup_module, "append_event", fail_at_event)
        with pytest.raises(RuntimeError, match="injected event failure"):
            direct_setup_module.commit_direct_setup(
                paths,
                intent="Rollback bundle",
                spec=spec,
                new=False,
                preflight_repository_revision=None,
            )
        assert _counts(root) == before
        assert paths.events_path.read_bytes() == jsonl_before
        assert (
            paths.dashboard_html.read_bytes(),
            paths.dashboard_data.read_bytes(),
        ) == dashboard_before


def test_direct_setup_generated_id_collision_is_typed_and_rolls_back(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    before = _counts(tmp_path)
    import pcl.direct_setup as direct_setup_module

    monkeypatch.setattr(
        direct_setup_module,
        "_random_id",
        lambda prefix: f"{prefix}-000000000000",
    )

    status, payload, _ = _invoke(tmp_path, capsys)

    assert status == 1
    assert payload["error"]["code"] == "direct_setup_id_collision"
    assert _counts(tmp_path) == before


def test_direct_setup_crash_boundary_is_zero_or_full_bundle_with_flush_recovery(
    tmp_path: Path,
    capsys,
) -> None:
    precommit_root = tmp_path / "precommit"
    _init(precommit_root, capsys)
    _write_spec(precommit_root)
    precommit_before = _counts(precommit_root)
    precommit_marker = tmp_path / "precommit-marker.json"
    crashed = _subprocess_direct(
        precommit_root,
        extra_env={
            "PCL_ENABLE_TEST_FAULTS": "1",
            "PCL_TEST_FAULT_POINT": "before_sqlite_commit",
            "PCL_TEST_FAULT_MARKER": str(precommit_marker),
        },
    )
    assert crashed.returncode != 0
    assert precommit_marker.exists()
    assert _counts(precommit_root) == precommit_before
    recovered = _subprocess_direct(precommit_root)
    assert recovered.returncode == 0, recovered.stderr or recovered.stdout
    assert json.loads(recovered.stdout)["status"] == "started"

    postcommit_root = tmp_path / "postcommit"
    _init(postcommit_root, capsys)
    _write_spec(postcommit_root)
    postcommit_before = _counts(postcommit_root)
    postcommit_marker = tmp_path / "postcommit-marker.json"
    crashed = _subprocess_direct(
        postcommit_root,
        extra_env={
            "PCL_ENABLE_TEST_FAULTS": "1",
            "PCL_TEST_FAULT_POINT": "after_sqlite_commit_before_projector",
            "PCL_TEST_FAULT_MARKER": str(postcommit_marker),
        },
    )
    assert crashed.returncode != 0
    assert postcommit_marker.exists()
    postcommit_after = _counts(postcommit_root)
    assert postcommit_after["goals"] - postcommit_before["goals"] == 1
    assert postcommit_after["tasks"] - postcommit_before["tasks"] == 1
    assert postcommit_after["features"] - postcommit_before["features"] == 1
    assert postcommit_after["user_stories"] - postcommit_before["user_stories"] == 1
    assert postcommit_after["test_cases"] - postcommit_before["test_cases"] == 1
    assert postcommit_after["evidence"] - postcommit_before["evidence"] == 1
    assert postcommit_after["events"] - postcommit_before["events"] == 8
    assert postcommit_after["outbox_records"] - postcommit_before["outbox_records"] == 8

    pending = _subprocess_direct(postcommit_root)
    assert pending.returncode == 6
    assert json.loads(pending.stdout)["error"]["code"] == "audit_projection_pending"
    flushed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pcl",
            "--root",
            str(postcommit_root),
            "audit",
            "flush",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert flushed.returncode == 0, flushed.stderr or flushed.stdout
    retry = _subprocess_direct(postcommit_root)
    assert retry.returncode == 0, retry.stderr or retry.stdout
    assert json.loads(retry.stdout)["status"] == "already_started"
    assert _counts(postcommit_root) == postcommit_after


def test_direct_setup_postcommit_projection_failure_is_typed_committed(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pcl.outbox as outbox_module

    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    before = _counts(tmp_path)

    def fail_projection(*args, **kwargs):
        raise OSError("projection root capability unavailable")

    monkeypatch.setattr(outbox_module, "project_pending_events", fail_projection)

    status, pending, stderr = _invoke(tmp_path, capsys)

    assert status == 6
    assert stderr == ""
    assert pending["error"]["code"] == "audit_projection_pending"
    details = pending["error"]["details"]
    assert details["mutation_committed"] is True
    assert details["safe_to_retry_original"] is False
    assert _counts(tmp_path)["goals"] - before["goals"] == 1


def test_direct_setup_postcommit_binding_and_diagnostic_loss_is_typed_committed(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pcl.outbox as outbox_module

    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    before = _counts(tmp_path)

    def fail_projection(*args, **kwargs):
        raise OSError("projection root capability unavailable")

    def fail_diagnostic(*args, **kwargs):
        raise OSError("pending diagnostic root capability unavailable")

    monkeypatch.setattr(outbox_module, "project_pending_events", fail_projection)
    monkeypatch.setattr(outbox_module, "pending_projection_result", fail_diagnostic)

    status, pending, stderr = _invoke(tmp_path, capsys)

    assert status == 6
    assert stderr == ""
    assert pending["error"]["code"] == "audit_projection_pending"
    details = pending["error"]["details"]
    assert details["mutation_committed"] is True
    assert details["safe_to_retry_original"] is False
    assert details["projection"] == "unknown"
    assert "pending diagnostic root capability unavailable" in details["diagnostic_error"]
    assert _counts(tmp_path)["goals"] - before["goals"] == 1


def test_direct_setup_retry_is_noop_and_changed_input_is_conflict(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    status, first, _ = _invoke(tmp_path, capsys, intent="Retry identity")
    assert status == 0
    before_retry = _counts(tmp_path)
    html = tmp_path / ".project-loop" / "dashboard" / "dashboard.html"
    data = tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json"
    artifact_before = (
        html.read_bytes() if html.exists() else None,
        data.read_bytes() if data.exists() else None,
    )

    status, retry, _ = _invoke(tmp_path, capsys, intent="Retry identity")
    assert status == 0
    assert retry["status"] == "already_started"
    assert retry["mutated"] is False
    assert retry["result"]["receipt"] == first["result"]["receipt"]
    assert _counts(tmp_path) == before_retry
    assert (
        html.read_bytes() if html.exists() else None,
        data.read_bytes() if data.exists() else None,
    ) == artifact_before

    changed = json.loads(json.dumps(VALID_SPEC))
    changed["feature"]["description"] = "changed"
    _write_spec(tmp_path, changed)
    status, conflict, _ = _invoke(tmp_path, capsys, intent="Retry identity")
    assert status == 1
    assert conflict["error"]["code"] == "direct_setup_idempotency_conflict"
    assert _counts(tmp_path) == before_retry


def test_direct_setup_retry_after_head_change_uses_stored_initial_revision(
    tmp_path: Path,
    capsys,
) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "PCL Test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "pcl@example.invalid"],
        check=True,
    )
    marker = tmp_path / "marker.txt"
    marker.write_text("one\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "marker.txt"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    initial = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    status, first, _ = _invoke(tmp_path, capsys, intent="Revision retry")
    assert status == 0

    marker.write_text("two\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "marker.txt"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "later"],
        check=True,
        capture_output=True,
    )
    current = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert current != initial
    before = _counts(tmp_path)

    status, retry, _ = _invoke(tmp_path, capsys, intent="Revision retry")

    assert status == 0
    assert retry["status"] == "already_started"
    assert retry["result"]["receipt"] == first["result"]["receipt"]
    assert retry["result"]["repository_revision"] == {
        "initial": initial,
        "current": current,
        "changed_since_initial": True,
    }
    assert _counts(tmp_path) == before


def test_direct_setup_retry_detects_evidence_receipt_tamper(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    status, first, _ = _invoke(tmp_path, capsys, intent="Tamper receipt")
    assert status == 0
    evidence_id = first["result"]["receipt"]["evidence_id"]
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            "UPDATE evidence SET summary = '{}' WHERE id = ?",
            (evidence_id,),
        )
        conn.commit()
    finally:
        conn.close()
    before = _counts(tmp_path)

    status, conflict, _ = _invoke(tmp_path, capsys, intent="Tamper receipt")

    assert status == 1
    assert conflict["error"]["code"] == "direct_setup_anchor_corrupt"
    assert conflict["error"]["details"]["reason"] == "evidence_receipt_mismatch"
    assert _counts(tmp_path) == before


def test_direct_setup_pending_outbox_requires_flush_before_admission(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    before = _counts(tmp_path)
    import pcl.start as start_module

    original_validate = start_module.validate_project
    injected = False

    def validate_then_inject(*args, **kwargs):
        nonlocal injected
        result = original_validate(*args, **kwargs)
        if not injected:
            injected = True
            conn = connect(tmp_path / ".project-loop" / "project.db")
            try:
                conn.execute(
                    """
                    UPDATE outbox_records
                    SET status = 'retry_wait',
                        next_attempt_at = '2099-01-01T00:00:00+00:00'
                    WHERE id = (
                      SELECT id FROM outbox_records ORDER BY created_at LIMIT 1
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()
        return result

    monkeypatch.setattr(start_module, "validate_project", validate_then_inject)

    status, pending, _ = _invoke(tmp_path, capsys)

    assert injected is True
    assert status == 6
    assert pending["error"]["code"] == "audit_projection_pending"
    assert pending["error"]["details"]["mutation_committed"] is False
    assert pending["error"]["details"]["recovery_command"] == "pcl audit flush --json"
    assert "pre-existing" in pending["error"]["message"]
    assert "mutation_tail" not in pending
    assert _counts(tmp_path) == before


def test_direct_setup_rechecks_global_integrity_after_preflight(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    before = _counts(tmp_path)
    import pcl.start as start_module

    original_validate = start_module.validate_project
    injected = False

    def validate_then_corrupt(*args, **kwargs):
        nonlocal injected
        result = original_validate(*args, **kwargs)
        if not injected:
            injected = True
            conn = connect(tmp_path / ".project-loop" / "project.db")
            try:
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute(
                    """
                    INSERT INTO agent_jobs(
                      id, workflow_run_id, role, status, assigned_agent_id, attempts
                    ) VALUES (
                      'AJ-INJECTED', 'WR-MISSING', 'test', 'queued',
                      'A-MISSING', 0
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()
        return result

    monkeypatch.setattr(start_module, "validate_project", validate_then_corrupt)

    status, blocked, _ = _invoke(tmp_path, capsys)

    assert status == 1
    assert blocked["error"]["code"] == "direct_setup_admission_failed"
    assert {
        *blocked["error"]["details"]["finding_codes"]
    } >= {
        "relationship_foreign_key_violation",
        "relationship_job_agent_missing",
    }
    assert _counts(tmp_path) == before


def test_direct_setup_schema8_required_columns_fail_closed(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            "ALTER TABLE outbox_records RENAME COLUMN idempotency_key TO broken_key"
        )
        conn.commit()
    finally:
        conn.close()
    before = _counts(tmp_path)

    status, blocked, _ = _invoke(tmp_path, capsys)

    assert status == 1
    assert blocked["error"]["code"] == "direct_setup_admission_failed"
    assert "schema_required_column_missing" in blocked["error"]["details"][
        "finding_codes"
    ]
    assert _counts(tmp_path) == before


def test_direct_setup_deterministic_anchor_collision_never_falls_back(
    tmp_path: Path,
    capsys,
) -> None:
    from pcl.db import connect_mutation
    from pcl.direct_setup import direct_setup_anchor_id
    from pcl.events import append_event

    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    paths = ProjectPaths(root=tmp_path.resolve())
    conn = connect_mutation(paths)
    try:
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="unrelated_event",
            entity_type="test",
            entity_id="collision",
            payload={},
            event_id=direct_setup_anchor_id(VALID_SPEC["request_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    before = _counts(tmp_path)

    status, conflict, _ = _invoke(tmp_path, capsys)

    assert status == 1
    assert conflict["error"]["code"] == "direct_setup_anchor_collision"
    assert _counts(tmp_path) == before


def test_direct_setup_anchor_uses_full_sha256() -> None:
    from pcl.direct_setup import direct_setup_anchor_id

    request_id = VALID_SPEC["request_id"]
    expected = hashlib.sha256(
        b"pcl:direct-setup-anchor:v1\0" + request_id.encode("utf-8")
    ).hexdigest()

    assert direct_setup_anchor_id(request_id) == f"EV-{expected.upper()}"


def test_direct_setup_legacy_anchor_retry_does_not_block_new_prefix_collision(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pcl.direct_setup as direct_setup_module

    _init(tmp_path, capsys)
    legacy_anchor = "EV-A1B2C3D4E5F6"
    original_anchor = direct_setup_module.direct_setup_anchor_id
    monkeypatch.setattr(
        direct_setup_module,
        "direct_setup_anchor_id",
        lambda request_id: legacy_anchor,
    )
    first_spec = json.loads(json.dumps(VALID_SPEC))
    first_spec["request_id"] = "ds-legacy-prefix-a"
    _write_spec(tmp_path, first_spec)
    first_status, first, _ = _invoke(tmp_path, capsys)
    assert first_status == 0
    assert first["result"]["receipt"]["event_id"] == legacy_anchor

    monkeypatch.setattr(direct_setup_module, "direct_setup_anchor_id", original_anchor)
    monkeypatch.setattr(
        direct_setup_module,
        "_legacy_direct_setup_anchor_id",
        lambda request_id: legacy_anchor,
    )
    retry_status, retry, _ = _invoke(tmp_path, capsys)
    assert retry_status == 0
    assert retry["status"] == "already_started"
    assert retry["result"]["reused_ids"]["event"] == legacy_anchor

    second_spec = json.loads(json.dumps(VALID_SPEC))
    second_spec["request_id"] = "ds-legacy-prefix-b"
    _write_spec(tmp_path, second_spec)
    second_status, second, _ = _invoke(tmp_path, capsys, intent="Ship another")
    assert second_status == 1
    assert second["error"]["code"] == "direct_setup_active_work_exists"

    second_status = main(
        [
            "--root",
            str(tmp_path),
            "start",
            "Ship another",
            "--direct-spec",
            "direct-spec.json",
            "--new",
            "--json",
        ]
    )
    second = json.loads(capsys.readouterr().out)
    assert second_status == 0
    assert second["status"] == "started"
    assert second["result"]["receipt"]["event_id"] == (
        original_anchor(second_spec["request_id"])
    )
    assert original_anchor(second_spec["request_id"]) != legacy_anchor


def test_direct_setup_legacy_retry_rejects_same_request_ambiguity(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pcl.direct_setup as direct_setup_module
    from pcl.db import connect_mutation
    from pcl.events import append_event

    _init(tmp_path, capsys)
    legacy_anchor = "EV-112233445566"
    original_anchor = direct_setup_module.direct_setup_anchor_id
    monkeypatch.setattr(
        direct_setup_module,
        "direct_setup_anchor_id",
        lambda request_id: legacy_anchor,
    )
    spec = json.loads(json.dumps(VALID_SPEC))
    spec["request_id"] = "ds-legacy-real-ambiguity"
    _write_spec(tmp_path, spec)
    first_status, first, _ = _invoke(tmp_path, capsys)
    assert first_status == 0

    monkeypatch.setattr(direct_setup_module, "direct_setup_anchor_id", original_anchor)
    monkeypatch.setattr(
        direct_setup_module,
        "_legacy_direct_setup_anchor_id",
        lambda request_id: legacy_anchor,
    )
    stored_receipt = dict(first["result"]["receipt"])
    evidence_id = stored_receipt.pop("evidence_id")
    stored_receipt.pop("event_id")
    paths = ProjectPaths(root=tmp_path.resolve())
    conn = connect_mutation(paths)
    try:
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="work_started",
            entity_type="task",
            entity_id=first["result"]["target"]["id"],
            payload={
                "evidence_id": evidence_id,
                "receipt": stored_receipt,
            },
            event_id="EV-LEGACYAMBIG",
        )
        conn.commit()
    finally:
        conn.close()
    before_retry = _counts(tmp_path)

    retry_status, conflict, stderr = _invoke(tmp_path, capsys)

    assert retry_status == 1
    assert stderr == ""
    assert conflict["error"]["code"] == "direct_setup_anchor_collision"
    assert _counts(tmp_path) == before_retry


def test_authoritative_admission_uses_one_clock_snapshot(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    import pcl.validators as validators_module

    _init(tmp_path, capsys)
    fixed = "2026-07-30T12:34:56+00:00"
    observed: list[str | None] = []
    helper_names = (
        "_validate_expired_running_leases",
        "_validate_retired_agent_active_leases",
        "_validate_agent_concurrency",
    )
    for helper_name in helper_names:
        original = getattr(validators_module, helper_name)

        def wrapper(conn, result, *, now=None, _original=original):
            observed.append(now)
            return _original(conn, result, now=now)

        monkeypatch.setattr(validators_module, helper_name, wrapper)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        result = validators_module.collect_authoritative_admission_findings(
            conn,
            now=fixed,
        )
    finally:
        conn.close()

    assert result.ok is True
    assert observed == [fixed, fixed, fixed]


def test_direct_setup_same_and_different_request_concurrency(
    tmp_path: Path,
    capsys,
) -> None:
    same_root = tmp_path / "same"
    _init(same_root, capsys)
    _write_spec(same_root)
    same_before = _counts(same_root)
    with ThreadPoolExecutor(max_workers=2) as executor:
        same_results = list(
            executor.map(
                lambda _: _subprocess_direct(same_root),
                range(2),
            )
        )
    assert all(result.returncode == 0 for result in same_results), [
        (result.stdout, result.stderr) for result in same_results
    ]
    same_payloads = [json.loads(result.stdout) for result in same_results]
    assert sorted(payload["status"] for payload in same_payloads) == [
        "already_started",
        "started",
    ]
    counts = _counts(same_root)
    assert counts["goals"] == counts["tasks"] == counts["features"] == 1
    assert counts["user_stories"] == counts["test_cases"] == counts["evidence"] == 1
    assert counts["events"] - same_before["events"] == 8
    assert counts["outbox_records"] - same_before["outbox_records"] == 8

    guarded_root = tmp_path / "guarded"
    _init(guarded_root, capsys)
    first_spec = json.loads(json.dumps(VALID_SPEC))
    second_spec = json.loads(json.dumps(VALID_SPEC))
    second_spec["request_id"] = "ds-test-direct-0002"
    _write_spec(guarded_root, first_spec, name="one.json")
    _write_spec(guarded_root, second_spec, name="two.json")
    guarded_before = _counts(guarded_root)
    with ThreadPoolExecutor(max_workers=2) as executor:
        guarded_results = list(
            executor.map(
                lambda name: _subprocess_direct(guarded_root, spec_name=name),
                ("one.json", "two.json"),
            )
        )
    assert sorted(result.returncode for result in guarded_results) == [0, 1]
    guarded_payloads = [json.loads(result.stdout) for result in guarded_results]
    assert {payload.get("status") for payload in guarded_payloads} >= {"started"}
    assert {
        payload.get("error", {}).get("code") for payload in guarded_payloads
    } >= {"direct_setup_active_work_exists"}
    counts = _counts(guarded_root)
    assert counts["goals"] == counts["tasks"] == counts["features"] == 1
    assert counts["events"] - guarded_before["events"] == 8
    assert counts["outbox_records"] - guarded_before["outbox_records"] == 8

    new_root = tmp_path / "new"
    _init(new_root, capsys)
    _write_spec(new_root, first_spec, name="one.json")
    _write_spec(new_root, second_spec, name="two.json")
    new_before = _counts(new_root)
    with ThreadPoolExecutor(max_workers=2) as executor:
        new_results = list(
            executor.map(
                lambda name: _subprocess_direct(
                    new_root,
                    spec_name=name,
                    new=True,
                ),
                ("one.json", "two.json"),
            )
        )
    assert all(result.returncode == 0 for result in new_results), [
        (result.stdout, result.stderr) for result in new_results
    ]
    counts = _counts(new_root)
    assert counts["goals"] == counts["tasks"] == counts["features"] == 2
    assert counts["user_stories"] == counts["test_cases"] == counts["evidence"] == 2
    assert counts["events"] - new_before["events"] == 16
    assert counts["outbox_records"] - new_before["outbox_records"] == 16


def test_direct_setup_preserves_legacy_start_and_lifecycle_event_semantics(
    tmp_path: Path,
    capsys,
) -> None:
    legacy_root = tmp_path / "legacy"
    direct_root = tmp_path / "direct"
    _init(legacy_root, capsys)
    _init(direct_root, capsys)
    _write_spec(direct_root)

    def run(root: Path, *arguments: str) -> dict:
        assert main(["--root", str(root), *arguments, "--json"]) == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        return json.loads(captured.out)

    legacy_start = run(legacy_root, "start", "Atomic setup")
    run(
        legacy_root,
        "feature",
        "add",
        "--name",
        VALID_SPEC["feature"]["name"],
        "--surface",
        VALID_SPEC["feature"]["surface"],
        "--description",
        VALID_SPEC["feature"]["description"],
        "--task",
        "T-0001",
    )
    story = VALID_SPEC["stories"][0]
    run(
        legacy_root,
        "story",
        "draft",
        "--feature",
        "F-0001",
        "--actor",
        story["actor"],
        "--goal",
        story["goal"],
        "--benefit",
        story["benefit"],
        "--expected-behavior",
        story["expected_behavior"],
    )
    test = VALID_SPEC["tests"][0]
    run(
        legacy_root,
        "test",
        "plan",
        "--feature",
        "F-0001",
        "--story",
        "US-0001",
        "--type",
        test["type"],
        "--scenario",
        test["scenario"],
        "--expected",
        test["expected"],
    )
    direct_start = run(
        direct_root,
        "start",
        "Atomic setup",
        "--direct-spec",
        "direct-spec.json",
    )

    assert set(legacy_start["result"]["receipt"]["created_ids"]) == {
        "goal",
        "task",
    }
    assert set(direct_start["result"]["receipt"]["created_ids"]) == {
        "goal",
        "task",
    }

    def domain_snapshot(root: Path) -> dict[str, list[dict]]:
        conn = connect(root / ".project-loop" / "project.db")
        try:
            return {
                "goals": [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT id, title, status, completion_json,
                               stop_conditions_json, budget_json
                        FROM goals ORDER BY id
                        """
                    )
                ],
                "tasks": [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT id, title, description, status, priority, owner, risk,
                               effort, related_goal_id, related_feature_id,
                               related_defect_id
                        FROM tasks ORDER BY id
                        """
                    )
                ],
                "features": [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT id, name, surface, description, status, confidence
                        FROM features ORDER BY id
                        """
                    )
                ],
                "stories": [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT id, feature_id, actor, goal, benefit,
                               expected_behavior, status
                        FROM user_stories ORDER BY id
                        """
                    )
                ],
                "tests": [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT id, feature_id, story_id, type, scenario, expected,
                               status, last_run_id, evidence_id
                        FROM test_cases ORDER BY id
                        """
                    )
                ],
            }
        finally:
            conn.close()

    assert domain_snapshot(direct_root) == domain_snapshot(legacy_root)

    def event_semantics(root: Path) -> list[dict]:
        conn = connect(root / ".project-loop" / "project.db")
        try:
            rows = conn.execute(
                """
                SELECT event_type, entity_type, entity_id, payload_json
                FROM events
                WHERE event_type != 'project_initialized'
                ORDER BY sequence
                """
            ).fetchall()
        finally:
            conn.close()
        result = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            if row["event_type"] == "work_started":
                receipt = payload["receipt"]
                receipt.pop("direct_setup", None)
                receipt["generated_at"] = "<timestamp>"
            result.append(
                {
                    "event_type": str(row["event_type"]),
                    "entity_type": str(row["entity_type"]),
                    "entity_id": str(row["entity_id"]),
                    "payload": payload,
                }
            )
        return result

    assert event_semantics(direct_root) == event_semantics(legacy_root)


def test_direct_setup_does_not_bypass_terminal_readiness(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    status, _, _ = _invoke(tmp_path, capsys)
    assert status == 0
    before = _counts(tmp_path)

    status = main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            "T-0001",
            "done",
            "--reason",
            "Direct setup is not acceptance",
            "--json",
        ]
    )
    terminal = json.loads(capsys.readouterr().out)

    assert status == 1
    assert terminal["error"]["code"] == "task_terminal_readiness_failed"
    assert {
        reason["code"]
        for reason in terminal["error"]["details"]["terminal_readiness"]["reasons"]
    } >= {
        "task_done_feature_not_terminal",
        "feature_done_story_incomplete",
        "feature_done_tests_incomplete",
    }
    assert _counts(tmp_path) == before


def test_direct_setup_projection_pending_returns_exit6_without_tail(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _init(tmp_path, capsys)
    _write_spec(tmp_path)
    import pcl.start as start_module

    tail_calls = 0

    def pending(*args, **kwargs):
        raise ProjectionPendingError(
            details={
                "projection": "pending",
                "recovery_command": "pcl audit flush --json",
            }
        )

    def tail(*args, **kwargs):
        nonlocal tail_calls
        tail_calls += 1
        raise AssertionError("tail must not run")

    monkeypatch.setattr(start_module, "commit_direct_setup", pending)
    monkeypatch.setattr(start_module, "apply_direct_setup_tail", tail)

    status, payload, _ = _invoke(tmp_path, capsys)

    assert status == 6
    assert payload["error"]["code"] == "audit_projection_pending"
    assert tail_calls == 0


def test_direct_tail_stable_validation_failure_skips_routing_and_render(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _init_without_capture(tmp_path)
    import pcl.mutation_tail as tail_module
    canonical_paths = (
        tmp_path / ".project-loop" / "dashboard" / "dashboard.html",
        tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json",
    )
    canonical_before = [
        (path.read_bytes(), path.stat().st_mtime_ns) for path in canonical_paths
    ]

    class FailedValidation:
        ok = False

        def to_dict(self):
            return {
                "ok": False,
                "errors": ["injected"],
                "warnings": [],
                "findings": [],
                "finding_counts": {"active": 1, "historical": 0},
            }

    monkeypatch.setattr(tail_module, "validate_project", lambda *args, **kwargs: FailedValidation())
    monkeypatch.setattr(
        tail_module,
        "project_validation_result",
        lambda *args, **kwargs: {
            "ok": False,
            "full_validation": {
                "ok": False,
                "finding_counts": {"active": 1, "historical": 0},
            },
            "validation_projection": {
                "target": {"target_type": "task", "target_id": "T-0001"}
            },
        },
    )
    monkeypatch.setattr(
        tail_module,
        "next_action",
        lambda *args, **kwargs: pytest.fail("routing must be skipped"),
    )
    monkeypatch.setattr(
        tail_module,
        "render_dashboard",
        lambda *args, **kwargs: pytest.fail("render must be skipped"),
    )

    result = tail_module.apply_direct_setup_tail(
        tail_module.ProjectPaths(root=tmp_path.resolve()),
        {"ok": True},
        target_id="T-0001",
        changed=True,
    )
    tail = result["mutation_tail"]

    assert tail["post_commit_status"] == "partial"
    assert tail["safe_to_retry_original"] is False
    assert tail["retry_recommended"] is False
    assert tail["validation"]["status"] == "failed"
    assert tail["next_action"] is None
    assert tail["render"]["status"] == "skipped_validation_failed"
    assert tail["render"]["artifact"] is None
    assert tail["render"]["data_artifact"] is None
    assert [
        (path.read_bytes(), path.stat().st_mtime_ns) for path in canonical_paths
    ] == canonical_before


def _init_without_capture(root: Path) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0


def test_direct_tail_retries_drift_then_stops_on_stable_validation_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _init_without_capture(tmp_path)
    import pcl.mutation_tail as tail_module

    class Validation:
        def __init__(self, ok: bool) -> None:
            self.ok = ok

        def to_dict(self):
            return {
                "ok": self.ok,
                "errors": [] if self.ok else ["injected"],
                "warnings": [],
                "findings": [],
                "finding_counts": {
                    "active": 0 if self.ok else 1,
                    "historical": 0,
                },
            }

    canonical_paths = (
        tmp_path / ".project-loop" / "dashboard" / "dashboard.html",
        tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json",
    )
    canonical_before = [
        (path.read_bytes(), path.stat().st_mtime_ns) for path in canonical_paths
    ]
    a = {"event_id": "EV-A", "sequence": 1}
    b = {"event_id": "EV-B", "sequence": 2}
    watermarks = iter([a, a, b, b, b])
    validations = iter([Validation(True), Validation(False)])
    route_calls = 0
    render_calls = 0

    monkeypatch.setattr(
        tail_module,
        "_state_high_watermark",
        lambda paths: next(watermarks),
    )
    monkeypatch.setattr(
        tail_module,
        "validate_project",
        lambda *args, **kwargs: next(validations),
    )
    monkeypatch.setattr(
        tail_module,
        "project_validation_result",
        lambda paths, result, **kwargs: {
            "ok": result.ok,
            "full_validation": result.to_dict(),
            "validation_projection": {"target": {"target_id": "T-0001"}},
        },
    )

    def route(*args, **kwargs):
        nonlocal route_calls
        route_calls += 1
        return {"target_binding": {"target_id": "T-0001"}}

    def render(*args, **kwargs):
        nonlocal render_calls
        render_calls += 1

    monkeypatch.setattr(tail_module, "next_action", route)
    monkeypatch.setattr(tail_module, "render_dashboard", render)

    result = tail_module.apply_direct_setup_tail(
        ProjectPaths(root=tmp_path.resolve()),
        {"ok": True},
        target_id="T-0001",
        changed=True,
    )

    tail = result["mutation_tail"]
    assert route_calls == 1
    assert render_calls == 0
    assert tail["post_commit_status"] == "partial"
    assert tail["validation"]["status"] == "failed"
    assert tail["validation"]["consistency"]["attempts"] == 2
    assert tail["next_action"] is None
    assert tail["render"]["status"] == "skipped_validation_failed"
    assert [
        (path.read_bytes(), path.stat().st_mtime_ns) for path in canonical_paths
    ] == canonical_before


def test_direct_tail_two_validation_drifts_never_routes_or_renders(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _init_without_capture(tmp_path)
    import pcl.mutation_tail as tail_module

    class PassedValidation:
        ok = True

    a = {"event_id": "EV-A", "sequence": 1}
    b = {"event_id": "EV-B", "sequence": 2}
    c = {"event_id": "EV-C", "sequence": 3}
    watermarks = iter([a, b, b, c])
    monkeypatch.setattr(
        tail_module,
        "_state_high_watermark",
        lambda paths: next(watermarks),
    )
    monkeypatch.setattr(
        tail_module,
        "validate_project",
        lambda *args, **kwargs: PassedValidation(),
    )
    monkeypatch.setattr(
        tail_module,
        "project_validation_result",
        lambda *args, **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        tail_module,
        "next_action",
        lambda *args, **kwargs: pytest.fail("routing must be skipped"),
    )
    monkeypatch.setattr(
        tail_module,
        "render_dashboard",
        lambda *args, **kwargs: pytest.fail("render must be skipped"),
    )

    result = tail_module.apply_direct_setup_tail(
        ProjectPaths(root=tmp_path.resolve()),
        {"ok": True},
        target_id="T-0001",
        changed=True,
    )

    tail = result["mutation_tail"]
    assert tail["post_commit_status"] == "partial"
    assert tail["validation"]["status"] == "unstable"
    assert tail["validation"]["consistency"]["attempts"] == 2
    assert tail["next_action"] is None
    assert tail["render"]["status"] == "skipped_state_changed"
    assert tail["render"]["artifact"] is None
    assert tail["render"]["data_artifact"] is None


def test_direct_tail_render_failure_has_no_success_hashes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _init_without_capture(tmp_path)
    import pcl.mutation_tail as tail_module

    class PassedValidation:
        ok = True

    watermark = {"event_id": "EV-A", "sequence": 1}
    monkeypatch.setattr(
        tail_module,
        "_state_high_watermark",
        lambda paths: watermark,
    )
    monkeypatch.setattr(
        tail_module,
        "validate_project",
        lambda *args, **kwargs: PassedValidation(),
    )
    monkeypatch.setattr(
        tail_module,
        "project_validation_result",
        lambda *args, **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        tail_module,
        "next_action",
        lambda *args, **kwargs: {"target_binding": {"target_id": "T-0001"}},
    )
    monkeypatch.setattr(
        tail_module,
        "_render_dashboard_with_lock",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("injected render")),
    )

    result = tail_module.apply_direct_setup_tail(
        ProjectPaths(root=tmp_path.resolve()),
        {"ok": True},
        target_id="T-0001",
        changed=True,
    )

    tail = result["mutation_tail"]
    assert tail["post_commit_status"] == "partial"
    assert tail["render"]["status"] == "failed"
    assert tail["render"]["artifact"] is None
    assert tail["render"]["data_artifact"] is None
    assert tail["render"]["error"] == "injected render"
    assert tail["recovery"]["contract_version"] == "direct-tail-recovery/v1"
    assert tail["recovery"]["authority"] == "retained_root_file_identity"
    assert tail["recovery"]["target"] == {"id": "T-0001", "type": "task"}
    assert tail["recovery"]["operation"] == {
        "arguments": {
            "active_only": False,
            "summary": True,
            "target": "T-0001",
        },
        "kind": "validate_exact_target",
    }
    assert tail["recovery"]["command"] is None
    assert tail["recovery"]["retry_original"] is False


def test_direct_tail_lock_hwm_mismatch_retries_before_single_render(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _init_without_capture(tmp_path)
    import pcl.mutation_tail as tail_module

    class PassedValidation:
        ok = True

        def to_dict(self):
            return {
                "ok": True,
                "errors": [],
                "warnings": [],
                "findings": [],
                "finding_counts": {"active": 0, "historical": 0},
            }

    watermarks = iter(
        [
            {"event_id": "EV-A", "sequence": 1},
            {"event_id": "EV-A", "sequence": 1},
            {"event_id": "EV-A", "sequence": 1},
            {"event_id": "EV-B", "sequence": 2},
            {"event_id": "EV-B", "sequence": 2},
            {"event_id": "EV-B", "sequence": 2},
            {"event_id": "EV-B", "sequence": 2},
            {"event_id": "EV-B", "sequence": 2},
            {"event_id": "EV-B", "sequence": 2},
        ]
    )
    render_calls = 0

    monkeypatch.setattr(tail_module, "_state_high_watermark", lambda paths: next(watermarks))
    monkeypatch.setattr(tail_module, "validate_project", lambda *args, **kwargs: PassedValidation())
    monkeypatch.setattr(
        tail_module,
        "project_validation_result",
        lambda paths, result, **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        tail_module,
        "next_action",
        lambda *args, **kwargs: {"target_binding": {"target_id": "T-0001"}},
    )
    monkeypatch.setattr(tail_module, "_artifact_receipt", lambda path: {"path": str(path), "sha256": "0" * 64, "size_bytes": 0})

    def render(paths, **kwargs):
        nonlocal render_calls
        render_calls += 1
        assert set(kwargs) == {"capability"}
        assert kwargs["capability"] is not None

    monkeypatch.setattr(tail_module, "_render_dashboard_with_lock", render)

    result = tail_module.apply_direct_setup_tail(
        tail_module.ProjectPaths(root=tmp_path.resolve()),
        {"ok": True},
        target_id="T-0001",
        changed=True,
    )

    assert render_calls == 1
    assert result["mutation_tail"]["post_commit_status"] == "complete"
    assert result["mutation_tail"]["render"]["consistency"]["attempts"] == 2
