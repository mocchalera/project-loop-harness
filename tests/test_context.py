from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess

import pytest

from pcl.context_binding import _receipt_target_binding_agrees
import pcl.cli as cli_module
import pcl.context_usage as context_usage_module
from pcl.cli import main
from pcl.context import TOKEN_ESTIMATOR, TRUNCATION_NOTE, estimate_token_count
from pcl.db import connect


FIXED_NOW = "2026-07-06T01:30:00Z"
FRESH_RECEIPT_CREATED_AT = "2026-07-06T01:00:00Z"
STALE_RECEIPT_CREATED_AT = "2026-07-06T00:00:00Z"
FIXTURES = Path(__file__).parent / "fixtures"
CONTEXT_PACK_CONTRACT_FIXTURES = json.loads(
    (FIXTURES / "context_pack_code_context_contract_v0.json").read_text(encoding="utf-8")
)
MASTER_TRACE_CONTEXT_FIXTURES = json.loads(
    (FIXTURES / "master_trace_context_contract_v0.json").read_text(encoding="utf-8")
)


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_job(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(root),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    capsys.readouterr()


def _create_task_context(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Task context"]) == 0
    assert main([
        "--root",
        str(root),
        "feature",
        "add",
        "--name",
        "Context packs",
        "--surface",
        "cli:context",
        "--description",
        "Focused handoffs",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "defect",
        "open",
        "--feature",
        "F-0001",
        "--severity",
        "high",
        "--expected",
        "Task pack includes linked data",
        "--actual",
        "Task pack omits linked data",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Done dependency",
        "--priority",
        "20",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "status",
        "T-0001",
        "done",
        "--reason",
        "Dependency already finished",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Target task",
        "--description",
        "Implement context pack for task work.",
        "--priority",
        "10",
        "--owner",
        "codex",
        "--risk",
        "high",
        "--effort",
        "medium",
        "--goal",
        "G-0001",
        "--feature",
        "F-0001",
        "--defect",
        "D-0001",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Unmet dependency",
        "--priority",
        "30",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Dependent task",
        "--priority",
        "40",
        "--goal",
        "G-0001",
    ]) == 0
    assert main(["--root", str(root), "task", "depend", "T-0002", "--on", "T-0001"]) == 0
    assert main(["--root", str(root), "task", "depend", "T-0002", "--on", "T-0003"]) == 0
    assert main(["--root", str(root), "task", "depend", "T-0004", "--on", "T-0002"]) == 0
    capsys.readouterr()


def _create_master_trace_task(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Pull master trace context",
        "--description",
        "Resolve copied evidence references.",
        "--json",
    ]) == 0
    _json_output(capsys)


def _record_master_trace_fixture_evidence(
    root: Path,
    capsys,
    *,
    master_trace_count: int,
    intent_index_count: int,
) -> list[dict]:
    recorded = []
    for index in range(1, master_trace_count + 1):
        path = root / f"master-trace-{index}.md"
        path.write_text(
            "---\n"
            "contract_version: master-trace/v0\n"
            f"trace_id: mt-fixture-{index}\n"
            "source_kind: operator_notes\n"
            "captured_at: 2026-07-10T00:00:00Z\n"
            "---\n"
            f"RAW_TRACE_SENTINEL_{index}\n",
            encoding="utf-8",
        )
        recorded.append(_record_task_evidence(root, capsys, path.name, f"Master trace {index}"))
    for index in range(1, intent_index_count + 1):
        path = root / f"intent-index-{index}.json"
        path.write_text(
            json.dumps(
                {
                    "contract_version": "intent-index/v0",
                    "index_id": f"ii-fixture-{index}",
                    "items": [{"claim": f"INDEX_CLAIM_SENTINEL_{index}"}],
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        recorded.append(_record_task_evidence(root, capsys, path.name, f"Intent index {index}"))
    return recorded


def _record_task_evidence(root: Path, capsys, path: str, summary: str) -> dict:
    assert main([
        "--root",
        str(root),
        "evidence",
        "add",
        "--file",
        path,
        "--summary",
        summary,
        "--copy",
        "--task",
        "T-0001",
        "--json",
    ]) == 0
    return _json_output(capsys)["evidence"]


def _context_mutation_snapshot(root: Path) -> dict:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        table_counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("evidence", "evidence_links", "events")
        }
    finally:
        conn.close()
    events_path = root / ".project-loop" / "events.jsonl"
    outbox = root / ".project-loop" / "outbox"
    return {
        "table_counts": table_counts,
        "events": events_path.read_bytes() if events_path.exists() else b"",
        "outbox": {
            path.relative_to(outbox).as_posix(): path.read_bytes()
            for path in sorted(outbox.rglob("*"))
            if path.is_file()
        } if outbox.exists() else {},
    }


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "core.pager=cat",
            "-c",
            "user.name=PCL Test",
            "-c",
            "user.email=pcl@example.test",
            "--no-pager",
            *args,
        ],
        capture_output=True,
        check=True,
        text=True,
    )


def _create_task_code_project(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)
    assert main(["--root", str(root), "goal", "create", "--title", "Code context"]) == 0
    assert main([
        "--root",
        str(root),
        "task",
        "create",
        "--title",
        "Bridge code context",
        "--description",
        "Pass code receipt summaries through context packs.",
        "--goal",
        "G-0001",
    ]) == 0
    capsys.readouterr()
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'Hello {name}'\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "from src import app\n\n\ndef test_greet():\n    assert app.greet('PCL') == 'Hello PCL'\n",
        encoding="utf-8",
    )
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")


def _create_job_code_project(root: Path, capsys) -> None:
    _create_job(root, capsys)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'Hello {name}'\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "from src import app\n\n\ndef test_greet():\n    assert app.greet('PCL') == 'Hello PCL'\n",
        encoding="utf-8",
    )
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")


def _write_code_context_receipt(root: Path, capsys, *, impact_args: list[str] | None = None) -> dict:
    assert main(["--root", str(root), "index", "build", "--json"]) == 0
    _json_output(capsys)
    app_path = root / "src" / "app.py"
    app_path.write_text(
        app_path.read_text(encoding="utf-8") + "\n\ndef parting() -> str:\n    return 'bye'\n",
        encoding="utf-8",
    )
    assert main(["--root", str(root), "impact", "--diff", *(impact_args or []), "--json"]) == 0
    return _json_output(capsys)["impact"]


def _set_receipt_created_at(root: Path, impact: dict, created_at: str) -> None:
    receipt_path = root / impact["receipt_path"]
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["created_at"] = created_at
    receipt_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _rewrite_receipt_target_binding(root: Path, impact: dict, target: dict) -> None:
    receipt_path = root / impact["receipt_path"]
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    binding = payload["target_binding"]
    payload["target_binding"] = {
        **binding,
        "target_type": str(target["type"]),
        "target_id": str(target["id"]),
    }
    receipt_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _write_fresh_code_context_receipt(root: Path, capsys, *, impact_args: list[str] | None = None) -> dict:
    app_path = root / "src" / "app.py"
    app_path.write_text(
        app_path.read_text(encoding="utf-8")
        + "\n\ndef parting() -> str:\n    return 'bye'\n",
        encoding="utf-8",
    )
    assert main(["--root", str(root), "index", "build", "--json"]) == 0
    _json_output(capsys)
    assert main(["--root", str(root), "impact", "--diff", *(impact_args or []), "--json"]) == 0
    return _json_output(capsys)["impact"]


def _receipt_show_latest_recommended_commands(root: Path, capsys) -> list[str]:
    assert main(["--root", str(root), "receipt", "show", "--latest"]) == 0
    rendered = capsys.readouterr().out
    lines = rendered.splitlines()
    recommendation = lines[lines.index("## Next Recommended Command") + 1]
    return [part.strip().strip("`") for part in recommendation.split(", then ")]


def _receipt_show_latest_error_next_actions(root: Path, capsys) -> list[str]:
    assert main([
        "--root",
        str(root),
        "receipt",
        "show",
        "--latest",
        "--json",
    ]) == 2
    return _json_output(capsys)["error"]["details"]["next_actions"]


def _markdown_next_action_line(markdown: str) -> str:
    return next(line for line in markdown.splitlines() if line.startswith("Next action: "))


def _markdown_next_action_commands(markdown: str) -> list[str]:
    parts = _markdown_next_action_line(markdown).split("`")
    return [part for index, part in enumerate(parts) if index % 2 == 1]


def _context_pack_contract_cases(*, ok: bool) -> list[dict]:
    return [
        case
        for case in CONTEXT_PACK_CONTRACT_FIXTURES["fixtures"]
        if bool(case["expected"]["ok"]) is ok
    ]


def _freeze_context_pack_contract_clocks(monkeypatch, now: str) -> None:
    module_names = [
        "pcl.cli",
        "pcl.commands",
        "pcl.tasks",
        "pcl.events",
        "pcl.workflows",
        "pcl.agents",
        "pcl.migrations",
        "pcl.code_context.store",
        "pcl.code_context.receipts",
    ]
    for module_name in module_names:
        module = importlib.import_module(module_name)
        if hasattr(module, "utc_now_iso"):
            monkeypatch.setattr(module, "utc_now_iso", lambda now=now: now)


def _setup_context_pack_contract_fixture(root: Path, capsys, case: dict) -> dict[str, dict]:
    setup = case["setup"]
    project = setup["project"]
    if project == "task_code":
        _create_task_code_project(root, capsys)
    elif project == "job_code":
        _create_job_code_project(root, capsys)
    else:
        raise AssertionError(f"Unknown contract fixture project: {project}")

    receipts: dict[str, dict] = {}
    for receipt_spec in setup["receipts"]:
        impact_args = _contract_receipt_target_args(receipt_spec.get("target"))
        if receipt_spec.get("fresh"):
            impact = _write_fresh_code_context_receipt(
                root,
                capsys,
                impact_args=impact_args,
            )
        else:
            impact = _write_code_context_receipt(
                root,
                capsys,
                impact_args=impact_args,
            )
        if receipt_spec.get("created_at"):
            _set_receipt_created_at(root, impact, str(receipt_spec["created_at"]))
        if receipt_spec.get("artifact_target"):
            _rewrite_receipt_target_binding(root, impact, receipt_spec["artifact_target"])
        receipts[str(receipt_spec["alias"])] = impact
    return receipts


def _contract_receipt_target_args(target: dict | None) -> list[str] | None:
    if not target:
        return None
    if target["type"] == "task":
        return ["--for-task", str(target["id"])]
    if target["type"] == "agent_job":
        return ["--for-job", str(target["id"])]
    raise AssertionError(f"Unknown receipt target type: {target['type']}")


def _context_pack_contract_args(
    root: Path,
    case: dict,
    *,
    max_tokens: int | None = None,
) -> list[str]:
    pack = case["pack"]
    target_flag = "--job" if pack["target_type"] == "agent_job" else "--task"
    args = [
        "--root",
        str(root),
        "context",
        "pack",
        target_flag,
        str(pack["target_id"]),
        "--include-code-context",
    ]
    if pack.get("require_bound_receipt"):
        args.append("--require-bound-receipt")
    if max_tokens is not None:
        args.extend(["--max-tokens", str(max_tokens)])
    args.append("--json")
    return args


def _resolve_contract_fixture_values(values: list[str], receipts: dict[str, dict]) -> list[str]:
    return [_resolve_contract_fixture_value(value, receipts) for value in values]


def _resolve_contract_fixture_value(value: object, receipts: dict[str, dict]) -> object:
    if isinstance(value, list):
        return [_resolve_contract_fixture_value(item, receipts) for item in value]
    if isinstance(value, dict):
        return {
            key: _resolve_contract_fixture_value(item, receipts)
            for key, item in value.items()
        }
    if not isinstance(value, str):
        return value
    prefix = "$receipt:"
    if not value.startswith(prefix):
        return value
    alias, field = value[len(prefix):].split(".", 1)
    return str(receipts[alias][field])


def _run_contract_json(args: list[str], capsys, *, expected_rc: int) -> tuple[str, dict]:
    assert main(args) == expected_rc
    output = capsys.readouterr().out
    return output, json.loads(output)


@pytest.mark.parametrize(
    ("receipt_payload", "expected"),
    [
        (
            {
                "target_binding": {
                    "target_type": "task",
                    "target_id": "T-0001",
                }
            },
            True,
        ),
        (
            {
                "target_binding": {
                    "target_type": "task",
                    "target_id": "T-9999",
                }
            },
            False,
        ),
        ({}, False),
        ({"target_binding": ""}, False),
        (["not", "a", "dict"], False),
    ],
)
def test_receipt_target_binding_agreement_predicate(
    receipt_payload: object,
    expected: bool,
) -> None:
    assert (
        _receipt_target_binding_agrees(
            receipt_payload,
            target_type="task",
            target_id="T-0001",
        )
        is expected
    )


@pytest.mark.parametrize(
    "case",
    _context_pack_contract_cases(ok=True),
    ids=lambda case: case["id"],
)
def test_context_pack_code_context_contract_fixture_states(
    tmp_path: Path,
    capsys,
    monkeypatch,
    case: dict,
) -> None:
    _freeze_context_pack_contract_clocks(monkeypatch, CONTEXT_PACK_CONTRACT_FIXTURES["now"])
    receipts = _setup_context_pack_contract_fixture(tmp_path, capsys, case)
    expected = case["expected"]

    max_tokens = None
    if case["pack"].get("budget") == "tight_required_retry":
        _, too_small_payload = _run_contract_json(
            _context_pack_contract_args(tmp_path, case, max_tokens=1),
            capsys,
            expected_rc=2,
        )
        assert too_small_payload["error"]["code"] == "context_pack_budget_too_small"
        details = too_small_payload["error"]["details"]
        assert details["required_sections"] == expected["required_sections"]
        max_tokens = details["estimated_min_max_tokens"]

    args = _context_pack_contract_args(tmp_path, case, max_tokens=max_tokens)
    first_output, payload = _run_contract_json(args, capsys, expected_rc=0)
    second_output, repeated_payload = _run_contract_json(args, capsys, expected_rc=0)
    assert second_output == first_output
    assert repeated_payload == payload

    pack = payload["context_pack"]
    code_context = pack["code_context"]
    assert pack["target"] == {
        "type": case["pack"]["target_type"],
        "id": case["pack"]["target_id"],
    }
    assert pack["included_sections"] == expected["included_sections"]
    assert pack["omitted_sections"] == expected["omitted_sections"]
    assert pack["required_sections"] == expected["required_sections"]
    assert pack["required_sections_omitted"] == expected["required_sections_omitted"]
    assert pack["source_paths"] == _resolve_contract_fixture_values(
        expected["source_paths"],
        receipts,
    )
    assert pack["suggested_refresh_commands"] == expected["suggested_refresh_commands"]
    assert code_context["relevance"] == expected["code_context"]["relevance"]
    assert "code_context_safety" in pack["included_sections"]
    assert "## Code Context Safety" in pack["markdown"]

    if case["pack"].get("budget") == "tight_required_retry":
        assert pack["truncated"] is True
        assert "code_context_detail" not in pack["included_sections"]
        assert "## Code Context Detail" not in pack["markdown"]
        assert pack["estimated_token_count"] <= pack["budget"]["max_tokens"]

    expected_age_warning = expected["code_context"].get("age_warning")
    if expected_age_warning:
        assert code_context["age_warning"] == expected_age_warning

    _assert_contract_receipt_ref_boundary(
        code_context,
        expected["code_context"].get("selected_receipt"),
        receipts,
    )
    for alias in expected["code_context"].get("unselected_receipts", []):
        assert receipts[alias]["receipt_path"] not in pack["source_paths"]
        assert code_context["receipt_ref"]["evidence_id"] != receipts[alias]["evidence_id"]


@pytest.mark.parametrize(
    "case",
    _context_pack_contract_cases(ok=False),
    ids=lambda case: case["id"],
)
def test_context_pack_code_context_contract_error_fixtures(
    tmp_path: Path,
    capsys,
    monkeypatch,
    case: dict,
) -> None:
    _freeze_context_pack_contract_clocks(monkeypatch, CONTEXT_PACK_CONTRACT_FIXTURES["now"])
    receipts = _setup_context_pack_contract_fixture(tmp_path, capsys, case)

    output, payload = _run_contract_json(
        _context_pack_contract_args(tmp_path, case),
        capsys,
        expected_rc=2,
    )

    expected_error = case["expected"]["error"]
    assert payload["ok"] is False
    assert "context_pack" not in payload
    assert payload["error"]["code"] == expected_error["code"]
    assert payload["error"]["details"] == _resolve_contract_fixture_value(
        expected_error["details"],
        receipts,
    )
    for alias in case["expected"].get("unselected_receipts", []):
        assert receipts[alias]["evidence_id"] not in output
        assert receipts[alias]["receipt_path"] not in output


def _assert_contract_receipt_ref_boundary(
    code_context: dict,
    selected_receipt: str | None,
    receipts: dict[str, dict],
) -> None:
    receipt_ref = code_context["receipt_ref"]
    assert {"evidence_id", "receipt_path"}.issubset(receipt_ref)
    forbidden_receipt_body_fields = {
        "changed_files",
        "included_candidate_context",
        "omitted",
        "excluded_changed_files",
    }
    assert not forbidden_receipt_body_fields.intersection(receipt_ref)
    assert not forbidden_receipt_body_fields.intersection(code_context)

    if selected_receipt is None:
        assert receipt_ref["evidence_id"] is None
        assert receipt_ref["receipt_path"] is None
        return

    selected = receipts[selected_receipt]
    assert receipt_ref["evidence_id"] == selected["evidence_id"]
    assert receipt_ref["receipt_path"] == selected["receipt_path"]


def _rubric_v1() -> str:
    return json.dumps(
        {
            "contract_version": "rubric/v1",
            "acceptance_criteria": [
                {"criterion": "Context pack reviewed", "met": "yes", "evidence_id": None}
            ],
            "regression_risk": {"level": "low", "notes": None},
            "test_evidence": [],
            "security_ux_checks": [],
            "confidence_score": 0.8,
            "evidence_completeness": "partial",
        },
        sort_keys=True,
    )


def test_context_pack_for_job_returns_machine_handoff(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--role",
        "implementer",
        "--max-tokens",
        "12000",
        "--json",
    ]) == 0

    payload = _json_output(capsys)
    assert payload["ok"] is True
    pack = payload["context_pack"]
    assert pack["contract_version"] == "context-pack/v1"
    assert pack["target"] == {"type": "agent_job", "id": "J-0001"}
    assert pack["reader_role"] == "implementer"
    assert pack["role_profile"] == "implementer"
    assert pack["token_estimator"] == TOKEN_ESTIMATOR
    assert pack["budget"]["max_tokens"] == 12000
    assert pack["budget"]["approx_char_limit"] == 48000
    assert pack["budget"]["token_estimator"] == TOKEN_ESTIMATOR
    assert pack["estimated_token_count"] == estimate_token_count(pack["markdown"])
    assert pack["truncated"] is False
    assert "target_job" in pack["included_sections"]
    assert "agent_prompt" in pack["included_sections"]
    assert pack["required_sections"] == ["machine_context_rules"]
    assert pack["required_sections_omitted"] == []
    assert pack["source_commands"] == [
        "pcl jobs read J-0001 --json",
        "pcl prompt job J-0001 --json",
        "pcl validate --json",
    ]
    assert "suggested_refresh_commands" not in pack
    assert ".project-loop/evidence/agent-runs/J-0001/prompt.md" in pack["source_paths"]

    markdown = pack["markdown"]
    assert markdown.startswith("# Context Pack: J-0001")
    assert "## Machine Context Rules" in markdown
    assert "Do not read or parse `.project-loop/dashboard/dashboard.html`" in markdown
    assert ".project-loop/dashboard/dashboard-data.json" in markdown
    assert "## Target Job" in markdown
    assert "| id | J-0001 |" in markdown
    assert "| assigned_agent_id |  |" in markdown
    assert "| attempts | 0 |" in markdown
    assert "| lease_expires_at |  |" in markdown
    assert "| last_heartbeat_at |  |" in markdown
    assert "## Workflow Run" in markdown
    assert "## Agent Prompt" in markdown
    assert "# Agent Job J-0001" in markdown


def test_context_pack_record_usage_emits_exactly_one_outbox_event(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
    before = _context_mutation_snapshot(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--record-usage",
        "--json",
    ]) == 0
    pack = _json_output(capsys)["context_pack"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        rows = conn.execute(
            """
            SELECT events.event_type, events.entity_type, events.entity_id,
                   events.payload_json, outbox_records.status
            FROM events
            JOIN outbox_records ON outbox_records.event_id = events.id
            WHERE events.event_type = 'context_pack_generated'
            """
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "context_pack"
    assert rows[0]["entity_id"] == "J-0001"
    assert rows[0]["status"] == "delivered"
    assert json.loads(rows[0]["payload_json"]) == {
        "estimated_token_count": pack["estimated_token_count"],
        "token_estimator": pack["token_estimator"],
        "target": pack["target"],
        "bound_receipt": False,
        "truncated": pack["truncated"],
    }
    after = _context_mutation_snapshot(tmp_path)
    assert after["table_counts"]["events"] == before["table_counts"]["events"] + 1


def test_context_pack_without_record_usage_remains_zero_mutation(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)
    before = _context_mutation_snapshot(tmp_path)
    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--json",
    ]) == 0
    _json_output(capsys)
    assert _context_mutation_snapshot(tmp_path) == before


def test_context_pack_record_usage_failure_is_explicit_and_rolls_back(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_job(tmp_path, capsys)
    before = _context_mutation_snapshot(tmp_path)

    def fail_append_event(**kwargs):
        raise __import__("sqlite3").OperationalError("injected usage event failure")

    monkeypatch.setattr(context_usage_module, "append_event", fail_append_event)
    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--record-usage",
        "--json",
    ]) == 4
    error = _json_output(capsys)["error"]
    assert error["code"] == "data_store_error"
    assert "injected usage event failure" in error["message"]
    assert _context_mutation_snapshot(tmp_path) == before


def test_context_pack_non_json_prints_markdown(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "context", "pack", "--job", "J-0001"]) == 0

    captured = capsys.readouterr()
    assert captured.out.startswith("# Context Pack: J-0001")
    assert '"context_pack"' not in captured.out


def test_context_pack_reports_truncation_metadata(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--max-tokens",
        "260",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["truncated"] is True
    assert pack["omitted_sections"]
    assert pack["estimated_token_count"] <= pack["budget"]["max_tokens"]
    assert pack["markdown"].startswith("# Context Pack: J-0001")


def test_context_pack_for_task_returns_task_handoff_with_dependencies(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--json",
    ]) == 0

    payload = _json_output(capsys)
    pack = payload["context_pack"]
    assert pack["contract_version"] == "context-pack/v1"
    assert pack["target"] == {"type": "task", "id": "T-0002"}
    assert pack["reader_role"] == "default"
    assert pack["role_profile"] == "default"
    assert pack["token_estimator"] == TOKEN_ESTIMATOR
    assert pack["budget"]["token_estimator"] == TOKEN_ESTIMATOR
    assert pack["estimated_token_count"] == estimate_token_count(pack["markdown"])
    assert pack["required_sections"] == ["machine_context_rules"]
    assert pack["required_sections_omitted"] == []
    assert pack["source_commands"] == [
        "pcl task read T-0002 --json",
        "pcl task list --json",
        "pcl validate --json",
    ]
    assert "suggested_refresh_commands" not in pack
    assert pack["source_paths"] == []
    assert pack["included_sections"] == [
        "machine_context_rules",
        "target_task",
        "dependencies",
        "dependents",
        "goal",
        "related_feature",
        "related_defect",
        "sibling_tasks",
        "recent_events",
    ]

    markdown = pack["markdown"]
    assert markdown.startswith("# Context Pack: T-0002")
    assert "## Target Task" in markdown
    assert "| owner | codex |" in markdown
    assert "````markdown\nImplement context pack for task work.\n````" in markdown
    assert "## Dependencies" in markdown
    assert "| T-0001 | Done dependency | done | yes |" in markdown
    assert "| T-0003 | Unmet dependency | todo | no |" in markdown
    assert "## Dependents" in markdown
    assert "| T-0004 | Dependent task | todo |" in markdown
    assert "## Goal" in markdown
    assert "| title | Task context |" in markdown
    assert "## Related Feature" in markdown
    assert "| name | Context packs |" in markdown
    assert "## Related Defect" in markdown
    assert "| severity | high |" in markdown
    assert "## Sibling Tasks" in markdown
    assert "| T-0003 | Unmet dependency | todo | 30 |" in markdown
    assert "| T-0004 | Dependent task | todo | 40 |" in markdown


def test_context_pack_for_task_includes_linked_evidence_without_inlining_contents(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)
    artifact = tmp_path / "intent-index.json"
    artifact.write_text(
        '{"claim":"DO_NOT_INLINE_MODEL_OUTPUT","source_ref":{"line_start":1}}\n',
        encoding="utf-8",
    )

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "intent-index.json",
        "--summary",
        "Model-derived intent index for target task",
        "--command",
        "external model indexing",
        "--copy",
        "--task",
        "T-0002",
        "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--json",
    ]) == 0
    pack = _json_output(capsys)["context_pack"]

    assert "linked_evidence" in pack["included_sections"]
    assert pack["source_paths"] == [
        evidence["manifest_path"],
        evidence["members"][0]["stored_path"],
        "intent-index.json",
    ]
    assert pack["linked_evidence"] == [
        {
            "id": "E-0001",
            "type": "adhoc_artifact",
            "summary": "Model-derived intent index for target task",
            "manifest_path": ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json",
            "member_paths": ["intent-index.json"],
            "stored_paths": [".project-loop/evidence/adhoc-files/e-0001/01-intent-index.json"],
            "created_at": evidence["created_at"],
        }
    ]
    markdown = pack["markdown"]
    assert "## Linked Evidence" in markdown
    assert "claims, not verified facts" in markdown
    assert "Model-derived intent index for target task" in markdown
    assert ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json" in markdown
    assert ".project-loop/evidence/adhoc-files/e-0001/01-intent-index.json" in markdown
    assert "DO_NOT_INLINE_MODEL_OUTPUT" not in markdown


@pytest.mark.parametrize(
    "case",
    MASTER_TRACE_CONTEXT_FIXTURES["fixtures"],
    ids=lambda case: case["id"],
)
def test_master_trace_context_contract_fixtures(
    tmp_path: Path,
    capsys,
    case: dict,
) -> None:
    _create_master_trace_task(tmp_path, capsys)
    setup = case["setup"]
    evidence = _record_master_trace_fixture_evidence(
        tmp_path,
        capsys,
        master_trace_count=setup["master_trace_count"],
        intent_index_count=setup["intent_index_count"],
    )
    args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--json",
    ]
    if case["include"]:
        args.insert(-1, "--master-trace-context")

    before = _context_mutation_snapshot(tmp_path)
    assert main(args) == 0
    output = capsys.readouterr().out
    assert _context_mutation_snapshot(tmp_path) == before
    pack = json.loads(output)["context_pack"]
    expected = case["expected"]

    assert "RAW_TRACE_SENTINEL" not in output
    assert "INDEX_CLAIM_SENTINEL" not in output
    if expected["status"] == "omitted":
        assert "master_trace_context" not in pack
        assert "master_trace_context" not in pack["included_sections"]
        assert "## Master Trace Context" not in pack["markdown"]
        return

    context = pack["master_trace_context"]
    assert "master_trace_context" in pack["included_sections"]
    assert "## Master Trace Context" in pack["markdown"]
    assert context["contract_version"] == "master-trace-context/v0"
    assert context["target"] == {"type": "task", "id": "T-0001"}
    assert context["raw_transcript_inlined"] is False

    if expected["status"] == "present":
        assert set(context) == {
            "contract_version",
            "target",
            "master_trace",
            "intent_index",
            "trust_model",
            "source_ref_discipline",
            "raw_transcript_inlined",
        }
        assert context["master_trace"] == {
            "evidence_id": evidence[0]["id"],
            "manifest_path": evidence[0]["manifest_path"],
            "member_paths": ["master-trace-1.md"],
            "stored_paths": [evidence[0]["members"][0]["stored_path"]],
        }
        assert context["intent_index"] == {
            "evidence_id": evidence[1]["id"],
            "manifest_path": evidence[1]["manifest_path"],
            "member_paths": ["intent-index-1.json"],
            "stored_paths": [evidence[1]["members"][0]["stored_path"]],
        }
        assert context["trust_model"] == "claims-not-facts"
        assert context["source_ref_discipline"] == {
            "line_numbering": "one-based-inclusive",
            "read_target": "copied-master-trace-stored-path",
            "worker_must_compare_claim_to_trace_lines": True,
        }
        return

    assert context["status"] == expected["status"]
    assert context.get("missing", []) == expected.get("missing", [])
    assert context.get("ambiguous", []) == expected.get("ambiguous", [])
    if expected["status"] == "selection_required":
        trace_candidates = context["candidates"]["master_trace"]
        assert [item["evidence_id"] for item in trace_candidates] == ["E-0001", "E-0002"]
        assert context["candidates"]["intent_index"][0]["evidence_id"] == "E-0003"


def test_master_trace_context_flag_is_task_only(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--master-trace-context",
        "--json",
    ]) == 2
    error = _json_output(capsys)["error"]
    assert error["code"] == "invalid_input"


def test_context_pack_for_task_falls_back_to_linked_task_column_without_evidence_links(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)
    artifact = tmp_path / "intent-index.json"
    artifact.write_text(
        '{"claim":"legacy linked evidence"}\n',
        encoding="utf-8",
    )

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "intent-index.json",
        "--summary",
        "Legacy linked evidence",
        "--task",
        "T-0002",
        "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute("DROP TABLE evidence_links")
        conn.execute("DELETE FROM schema_migrations WHERE version = 7")
        conn.execute("UPDATE metadata SET value = '6' WHERE key = 'schema_version'")
        conn.commit()
    finally:
        conn.close()

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--json",
    ]) == 0
    pack = _json_output(capsys)["context_pack"]

    assert pack["linked_evidence"] == [
        {
            "id": "E-0001",
            "type": "adhoc_artifact",
            "summary": "Legacy linked evidence",
            "manifest_path": ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json",
            "member_paths": ["intent-index.json"],
            "stored_paths": [],
            "created_at": evidence["created_at"],
        }
    ]


def test_context_pack_for_task_without_linked_evidence_unchanged_by_unlinked_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--json",
    ]
    assert main(args) == 0
    before = _json_output(capsys)["context_pack"]
    artifact = tmp_path / "unlinked-evidence.txt"
    artifact.write_text("unlinked evidence content\n", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "unlinked-evidence.txt",
        "--summary",
        "Unlinked evidence",
        "--json",
    ]) == 0
    _json_output(capsys)
    assert main(args) == 0
    after = _json_output(capsys)["context_pack"]

    assert after == before


def test_context_pack_for_task_without_goal_omits_goal_only_sections(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Unlinked task",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    markdown = pack["markdown"]
    assert "No goal is linked to this task." in markdown
    assert "sibling_tasks" not in pack["included_sections"]
    assert "## Sibling Tasks" not in markdown
    assert "## Related Feature" not in markdown
    assert "## Related Defect" not in markdown


def test_context_pack_for_task_unknown_id_returns_typed_error(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-9999",
        "--json",
    ]) == 2

    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["message"] == "Task does not exist: T-9999"


def test_context_pack_for_task_reports_truncation_metadata(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--max-tokens",
        "260",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["truncated"] is True
    assert pack["omitted_sections"]
    assert pack["estimated_token_count"] <= pack["budget"]["max_tokens"]
    assert pack["markdown"].startswith("# Context Pack: T-0002")


def test_context_pack_tiny_budget_without_code_context_returns_typed_budget_error(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--max-tokens",
        "1",
        "--json",
    ]) == 2

    error = _assert_context_pack_budget_error(_json_output(capsys), max_tokens=1)
    details = error["details"]
    assert details["required_sections"] == ["machine_context_rules"]
    assert set(details["required_section_token_counts"]) == {"machine_context_rules"}
    assert details["estimated_min_max_tokens"] > details["max_tokens"]


def test_context_pack_budget_fitting_required_section_but_not_note_errors(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--max-tokens",
        "1",
        "--json",
    ]) == 2
    details = _assert_context_pack_budget_error(_json_output(capsys), max_tokens=1)[
        "details"
    ]
    required_only_budget = (
        details["estimated_min_max_tokens"]
        - details["truncation_note_token_count"]
    )

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--max-tokens",
        str(required_only_budget),
        "--json",
    ]) == 2

    error = _assert_context_pack_budget_error(
        _json_output(capsys),
        max_tokens=required_only_budget,
    )
    assert error["details"]["estimated_min_max_tokens"] == details["estimated_min_max_tokens"]


def test_context_pack_old_required_priority_tie_budget_errors_and_retry_succeeds(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Needs receipt",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--max-tokens",
        "1",
        "--json",
    ]) == 2
    details = _assert_context_pack_budget_error(_json_output(capsys), max_tokens=1)[
        "details"
    ]
    assert details["required_sections"] == [
        "machine_context_rules",
        "code_context_safety",
    ]

    tie_budget = (
        details["estimated_min_max_tokens"]
        - details["required_section_token_counts"]["code_context_safety"]
    )
    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--max-tokens",
        str(tie_budget),
        "--json",
    ]) == 2
    tie_error = _assert_context_pack_budget_error(
        _json_output(capsys),
        max_tokens=tie_budget,
    )
    retry_budget = tie_error["details"]["estimated_min_max_tokens"]

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--max-tokens",
        str(retry_budget),
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["required_sections"] == [
        "machine_context_rules",
        "code_context_safety",
    ]
    assert pack["required_sections_omitted"] == []
    assert "machine_context_rules" in pack["included_sections"]
    assert "code_context_safety" in pack["included_sections"]
    assert "## Machine Context Rules" in pack["markdown"]
    assert "## Code Context Safety" in pack["markdown"]
    assert pack["omitted_sections"]
    assert TRUNCATION_NOTE.strip() in pack["markdown"]
    assert pack["estimated_token_count"] <= retry_budget


def test_context_pack_truncation_note_present_for_successful_omissions(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--max-tokens",
        "1",
        "--json",
    ]) == 2
    details = _assert_context_pack_budget_error(_json_output(capsys), max_tokens=1)[
        "details"
    ]
    minimum_budget = details["estimated_min_max_tokens"]

    for budget in range(minimum_budget, minimum_budget + 200, 25):
        assert main([
            "--root",
            str(tmp_path),
            "context",
            "pack",
            "--task",
            "T-0002",
            "--max-tokens",
            str(budget),
            "--json",
        ]) == 0
        pack = _json_output(capsys)["context_pack"]
        if pack["omitted_sections"]:
            assert pack["truncated"] is True
            assert TRUNCATION_NOTE.strip() in pack["markdown"]
            assert pack["estimated_token_count"] <= budget


def test_context_pack_ample_budget_adds_only_required_metadata_fields(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--json",
    ]
    assert main(args) == 0
    first = _json_output(capsys)["context_pack"]
    assert main(args) == 0
    second = _json_output(capsys)["context_pack"]

    legacy_keys = {
        "contract_version",
        "target",
        "reader_role",
        "role_profile",
        "token_estimator",
        "budget",
        "approx_char_count",
        "estimated_token_count",
        "truncated",
        "included_sections",
        "omitted_sections",
        "source_commands",
        "source_paths",
        "markdown",
    }
    assert set(first) == legacy_keys | {
        "required_sections",
        "required_sections_omitted",
    }
    assert _without_required_metadata(first) == _without_required_metadata(second)
    assert first["required_sections"] == ["machine_context_rules"]
    assert first["required_sections_omitted"] == []


def test_charclass_token_estimator_counts_stable_character_classes() -> None:
    assert estimate_token_count("abcd") == 1
    assert estimate_token_count("abcde") == 2
    assert estimate_token_count("hello world") == 5
    assert estimate_token_count("漢字") == 2
    assert estimate_token_count("a, b") == 4
    assert estimate_token_count("a\n\nb") == 3


def test_context_pack_for_job_tight_budget_omissions_match_markdown(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)

    args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--max-tokens",
        "260",
        "--json",
    ]
    assert main(args) == 0
    first = _json_output(capsys)["context_pack"]
    assert main(args) == 0
    second = _json_output(capsys)["context_pack"]

    assert first["included_sections"] == second["included_sections"]
    assert first["omitted_sections"] == second["omitted_sections"]
    assert first["estimated_token_count"] == estimate_token_count(first["markdown"])
    assert first["estimated_token_count"] <= first["budget"]["max_tokens"]
    for section_id in first["included_sections"]:
        assert _section_heading(section_id) in first["markdown"]
    for section_id in first["omitted_sections"]:
        assert _section_heading(section_id) not in first["markdown"]


def test_context_pack_for_task_tight_budget_omissions_match_markdown(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--max-tokens",
        "260",
        "--json",
    ]
    assert main(args) == 0
    first = _json_output(capsys)["context_pack"]
    assert main(args) == 0
    second = _json_output(capsys)["context_pack"]

    assert first["included_sections"] == second["included_sections"]
    assert first["omitted_sections"] == second["omitted_sections"]
    assert first["estimated_token_count"] == estimate_token_count(first["markdown"])
    assert first["estimated_token_count"] <= first["budget"]["max_tokens"]
    for section_id in first["included_sections"]:
        assert _section_heading(section_id) in first["markdown"]
    for section_id in first["omitted_sections"]:
        assert _section_heading(section_id) not in first["markdown"]


def test_context_pack_for_task_tight_budget_prioritizes_linked_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)
    artifact = tmp_path / "linked-report.txt"
    artifact.write_text("linked report details that must not be inlined\n", encoding="utf-8")
    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        "linked-report.txt",
        "--summary",
        "Linked task evidence with enough metadata to exercise budget selection",
        "--task",
        "T-0002",
        "--json",
    ]) == 0
    _json_output(capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--max-tokens",
        "733",
        "--json",
    ]) == 0
    selected_pack = _json_output(capsys)["context_pack"]
    assert "target_task" in selected_pack["included_sections"]
    assert "linked_evidence" in selected_pack["included_sections"]
    assert "dependencies" in selected_pack["omitted_sections"]
    assert "## Linked Evidence" in selected_pack["markdown"]
    assert "## Dependencies" not in selected_pack["markdown"]
    assert selected_pack["estimated_token_count"] <= selected_pack["budget"]["max_tokens"]


def test_context_pack_for_task_markdown_is_deterministic(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_context(tmp_path, capsys)

    args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0002",
        "--json",
    ]
    assert main(args) == 0
    first = _json_output(capsys)["context_pack"]
    assert main(args) == 0
    second = _json_output(capsys)["context_pack"]

    assert first["markdown"] == second["markdown"]
    assert first["included_sections"] == second["included_sections"]
    assert first["omitted_sections"] == second["omitted_sections"]


def test_context_pack_role_profiles_prioritize_sections_under_budget(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--target-job",
        "J-0001",
        "--result",
        "approved",
        "--reason",
        "Reviewed handoff",
    ]) == 0
    capsys.readouterr()

    base_args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--max-tokens",
        "400",
    ]
    assert main([*base_args, "--json"]) == 0
    default_pack = _json_output(capsys)["context_pack"]
    assert main([*base_args, "--role", "verifier", "--json"]) == 0
    verifier_pack = _json_output(capsys)["context_pack"]
    assert main([*base_args, "--role", "astronaut", "--json"]) == 0
    unknown_pack = _json_output(capsys)["context_pack"]

    assert default_pack["role_profile"] == "implementer"
    assert "verifications" not in default_pack["included_sections"]
    assert verifier_pack["reader_role"] == "verifier"
    assert verifier_pack["role_profile"] == "verifier"
    assert "verifications" in verifier_pack["included_sections"]
    assert "## Verifications" in verifier_pack["markdown"]
    assert unknown_pack["reader_role"] == "astronaut"
    assert unknown_pack["role_profile"] == "implementer"


def test_context_pack_for_job_renders_active_lease_fields(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "register",
        "--name",
        "local-runner",
        "--role",
        "implementer",
        "--adapter",
        "manual",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "lease",
        "J-0001",
        "--agent",
        "A-0001",
        "--ttl-seconds",
        "600",
        "--json",
    ]) == 0
    lease = _json_output(capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--json",
    ]) == 0

    markdown = _json_output(capsys)["context_pack"]["markdown"]
    assert "| assigned_agent_id | A-0001 |" in markdown
    assert "| attempts | 0 |" in markdown
    assert f"| lease_expires_at | {lease['lease_expires_at']} |" in markdown
    assert f"| last_heartbeat_at | {lease['last_heartbeat_at']} |" in markdown


def test_context_pack_verifications_render_rubric_columns(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--target-job",
        "J-0001",
        "--result",
        "inconclusive",
        "--reason",
        "Free-form verification",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--target-job",
        "J-0001",
        "--result",
        "approved",
        "--rubric-json",
        _rubric_v1(),
        "--reason",
        "Structured verification",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--json",
    ]) == 0

    markdown = _json_output(capsys)["context_pack"]["markdown"]
    assert "confidence_score" in markdown
    assert "evidence_completeness" in markdown
    assert "| V-0001 | J-0001 | human | inconclusive |  |  |" in markdown
    assert "| V-0002 | J-0001 | human | approved | 0.8 | partial |" in markdown


def test_context_pack_for_job_include_code_context_embeds_bounded_summary(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_job_code_project(tmp_path, capsys)
    impact = _write_code_context_receipt(tmp_path, capsys)
    _set_receipt_created_at(tmp_path, impact, FRESH_RECEIPT_CREATED_AT)
    monkeypatch.setattr(cli_module, "utc_now_iso", lambda: FIXED_NOW)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    code_context = pack["code_context"]
    assert code_context["contract_version"] == "code-context-summary/v0"
    assert code_context["receipt_ref"] == {
        "evidence_id": impact["evidence_id"],
        "receipt_path": impact["receipt_path"],
        "created_at": FRESH_RECEIPT_CREATED_AT,
    }
    assert code_context["relevance"] == {
        "target_type": "agent_job",
        "target_id": "J-0001",
        "scope": "unscoped_latest",
        "binding_strength": "none",
        "warning": "No target-bound code context receipt was found; using the latest unscoped receipt.",
        "reason": (
            "The most recent context receipt was selected by recency; it was not "
            "created for this target."
        ),
    }
    assert code_context["receipt_age"] == {
        "created_at": FRESH_RECEIPT_CREATED_AT,
        "age_seconds": 1800,
    }
    assert "age_warning" not in code_context
    assert code_context["diff_source"] == "worktree-vs-HEAD"
    assert code_context["changed_file_count"] == 1
    assert code_context["included_total"] >= 1
    assert any(
        item["path"] == "src/app.py"
        and item["selection"] == "included as candidate context"
        for item in code_context["included_candidate_context_top"]
    )
    assert "included_candidate_context" not in code_context
    assert "omitted" not in code_context
    assert "excluded_changed_files" not in code_context
    assert isinstance(code_context["omitted_reason_counts"], dict)
    assert code_context["sensitive_omitted_count"] == 0
    assert code_context["excluded_changed_file_count"] == 0
    assert code_context["untracked_omission_warning"]
    assert code_context["sensitive_include_override_used"] is False
    assert code_context["status"] == "from_receipt"
    assert "safe_to_continue" not in json.dumps(code_context, sort_keys=True)
    assert pack["required_sections"] == ["machine_context_rules", "code_context_safety"]
    assert pack["required_sections_omitted"] == []
    assert "code_context_safety" in pack["included_sections"]
    assert impact["receipt_path"] in pack["source_paths"]
    assert "pcl impact --diff --json" not in pack["source_commands"]
    assert "suggested_refresh_commands" in pack
    assert "## Code Context Safety" in pack["markdown"]
    assert "Files included as candidate context:" in pack["markdown"]
    assert "understood" not in pack["markdown"].lower()
    assert "analyzed" not in pack["markdown"].lower()
    assert "agent read" not in pack["markdown"].lower()


def test_context_pack_for_task_include_code_context_embeds_summary(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_code_context_receipt(tmp_path, capsys)
    _set_receipt_created_at(tmp_path, impact, FRESH_RECEIPT_CREATED_AT)
    monkeypatch.setattr(cli_module, "utc_now_iso", lambda: FIXED_NOW)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["code_context"]["contract_version"] == "code-context-summary/v0"
    assert pack["code_context"]["status"] == "from_receipt"
    assert pack["code_context"]["relevance"] == {
        "target_type": "task",
        "target_id": "T-0001",
        "scope": "unscoped_latest",
        "binding_strength": "none",
        "warning": "No target-bound code context receipt was found; using the latest unscoped receipt.",
        "reason": (
            "The most recent context receipt was selected by recency; it was not "
            "created for this target."
        ),
    }
    assert pack["code_context"]["receipt_age"] == {
        "created_at": FRESH_RECEIPT_CREATED_AT,
        "age_seconds": 1800,
    }
    suggestions = pack["code_context"]["verification_suggestions"]
    assert suggestions
    assert suggestions[0]["id"].startswith(f"{impact['evidence_id']}/VS-")
    assert suggestions[0]["command"] in pack["markdown"]
    assert f"[{suggestions[0]['id']}]" in pack["markdown"]
    assert pack["required_sections"] == ["machine_context_rules", "code_context_safety"]
    assert pack["required_sections_omitted"] == []
    assert "code_context_safety" in pack["included_sections"]
    assert "code_context_detail" in pack["included_sections"]
    assert "pcl impact --diff --json" not in pack["source_commands"]
    assert "suggested_refresh_commands" in pack


def test_context_pack_prefers_matching_task_bound_receipt_over_newer_unbound(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    bound = _write_code_context_receipt(
        tmp_path,
        capsys,
        impact_args=["--for-task", "T-0001"],
    )
    unbound = _write_code_context_receipt(tmp_path, capsys)
    assert bound["evidence_id"] != unbound["evidence_id"]
    monkeypatch.setattr(cli_module, "utc_now_iso", lambda: FIXED_NOW)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    code_context = pack["code_context"]
    assert code_context["receipt_ref"]["evidence_id"] == bound["evidence_id"]
    assert code_context["relevance"] == {
        "target_type": "task",
        "target_id": "T-0001",
        "scope": "target_bound",
        "binding_strength": "caller_asserted",
        "reason": (
            "A context receipt linked to this target was selected through evidence_links; "
            "the binding is a caller assertion, not semantic proof."
        ),
    }
    assert pack["suggested_refresh_commands"][-1] == "pcl impact --diff --for-task T-0001 --json"
    assert all("pcl impact" not in command for command in pack["source_commands"])
    assert "- relevance: target_bound (binding: caller_asserted)" in pack["markdown"]


def test_context_pack_record_usage_marks_target_bound_receipt(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    bound = _write_code_context_receipt(
        tmp_path,
        capsys,
        impact_args=["--for-task", "T-0001"],
    )

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--record-usage",
        "--json",
    ]) == 0
    pack = _json_output(capsys)["context_pack"]
    assert pack["code_context"]["receipt_ref"]["evidence_id"] == bound["evidence_id"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT payload_json FROM events WHERE event_type = 'context_pack_generated'"
        ).fetchone()
    finally:
        conn.close()
    assert json.loads(row["payload_json"])["bound_receipt"] is True


def test_context_pack_prefers_matching_job_bound_receipt_over_newer_unbound(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job_code_project(tmp_path, capsys)
    bound = _write_code_context_receipt(
        tmp_path,
        capsys,
        impact_args=["--for-job", "J-0001"],
    )
    unbound = _write_code_context_receipt(tmp_path, capsys)
    assert bound["evidence_id"] != unbound["evidence_id"]

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["code_context"]["receipt_ref"]["evidence_id"] == bound["evidence_id"]
    assert pack["code_context"]["relevance"]["scope"] == "target_bound"
    assert pack["code_context"]["relevance"]["target_type"] == "agent_job"
    assert pack["code_context"]["relevance"]["target_id"] == "J-0001"
    assert pack["suggested_refresh_commands"][-1] == "pcl impact --diff --for-job J-0001 --json"
    assert all("pcl impact" not in command for command in pack["source_commands"])


def test_context_pack_require_bound_receipt_errors_without_fallback(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    unbound = _write_code_context_receipt(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--require-bound-receipt",
        "--json",
    ]) == 2

    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "context_pack_bound_receipt_required"
    assert payload["error"]["details"]["target_type"] == "task"
    assert payload["error"]["details"]["target_id"] == "T-0001"
    assert payload["error"]["details"]["suggested_refresh_commands"] == [
        "pcl impact --diff --for-task T-0001 --json"
    ]
    assert unbound["evidence_id"] not in json.dumps(payload, sort_keys=True)


def test_context_pack_unscoped_fallback_has_target_specific_refresh_command(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    _write_fresh_code_context_receipt(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["code_context"]["relevance"]["scope"] == "unscoped_latest"
    assert pack["code_context"]["relevance"]["binding_strength"] == "none"
    assert pack["code_context"]["relevance"]["warning"]
    assert pack["suggested_refresh_commands"] == [
        "pcl impact --diff --for-task T-0001 --json"
    ]
    assert all("pcl impact" not in command for command in pack["source_commands"])


def test_context_pack_missing_receipt_markdown_next_action_matches_json_for_job(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["code_context"]["status"] == "missing_receipt"
    assert pack["suggested_refresh_commands"] == [
        "pcl index build --json",
        "pcl impact --diff --for-job J-0001 --json",
    ]
    assert _markdown_next_action_commands(pack["markdown"]) == pack["suggested_refresh_commands"]
    assert _markdown_next_action_line(pack["markdown"]) == (
        "Next action: `pcl index build --json`, then "
        "`pcl impact --diff --for-job J-0001 --json`."
    )
    assert "Next action: `pcl index build --json`, then `pcl impact --diff --json`." not in pack["markdown"]


def test_context_pack_code_context_receipt_age_fresh_in_json_and_safety_section(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_code_context_receipt(tmp_path, capsys)
    _set_receipt_created_at(tmp_path, impact, FRESH_RECEIPT_CREATED_AT)
    monkeypatch.setattr(cli_module, "utc_now_iso", lambda: FIXED_NOW)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    code_context = pack["code_context"]
    assert code_context["receipt_age"] == {
        "created_at": FRESH_RECEIPT_CREATED_AT,
        "age_seconds": 1800,
    }
    assert "age_warning" not in code_context
    assert f"- receipt age: 1800s (created_at {FRESH_RECEIPT_CREATED_AT})" in pack["markdown"]
    assert "- age warning:" not in pack["markdown"]


def test_context_pack_code_context_receipt_age_stale_warns_in_json_and_safety_section(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_code_context_receipt(tmp_path, capsys)
    _set_receipt_created_at(tmp_path, impact, STALE_RECEIPT_CREATED_AT)
    monkeypatch.setattr(cli_module, "utc_now_iso", lambda: FIXED_NOW)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    code_context = pack["code_context"]
    assert code_context["receipt_age"] == {
        "created_at": STALE_RECEIPT_CREATED_AT,
        "age_seconds": 5400,
    }
    assert code_context["age_warning"] == (
        "Receipt age is 5400s, above the provisional 3600s threshold."
    )
    assert f"- receipt age: 5400s (created_at {STALE_RECEIPT_CREATED_AT})" in pack["markdown"]
    assert "- age warning: Receipt age is 5400s, above the provisional 3600s threshold." in pack["markdown"]


def test_context_pack_code_context_receipt_age_unparsable_warns_in_json_and_safety_section(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_code_context_receipt(tmp_path, capsys)
    _set_receipt_created_at(tmp_path, impact, "not-a-timestamp")
    monkeypatch.setattr(cli_module, "utc_now_iso", lambda: FIXED_NOW)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    code_context = pack["code_context"]
    assert code_context["receipt_age"] == {"created_at": "not-a-timestamp"}
    assert "age_seconds" not in code_context["receipt_age"]
    assert code_context["age_warning"] == (
        "Receipt age could not be computed because created_at is missing or unparsable."
    )
    assert "- receipt age: unknown (created_at not-a-timestamp)" in pack["markdown"]
    assert "- age warning: Receipt age could not be computed" in pack["markdown"]


def test_context_pack_unavailable_code_context_keeps_unscoped_latest_relevance(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_code_context_receipt(tmp_path, capsys)
    _set_receipt_created_at(tmp_path, impact, STALE_RECEIPT_CREATED_AT)
    (tmp_path / impact["receipt_path"]).write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(cli_module, "utc_now_iso", lambda: FIXED_NOW)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    code_context = pack["code_context"]
    assert code_context["status"] == "receipt_unavailable"
    assert code_context["relevance"]["scope"] == "unscoped_latest"
    assert code_context["relevance"]["binding_strength"] == "none"
    assert "receipt_age" in code_context
    assert pack["suggested_refresh_commands"] == [
        "pcl index build --json",
        "pcl impact --diff --for-task T-0001 --json",
    ]
    assert _markdown_next_action_commands(pack["markdown"]) == pack["suggested_refresh_commands"]
    assert _markdown_next_action_line(pack["markdown"]) == (
        "Next action: `pcl index build --json`, then "
        "`pcl impact --diff --for-task T-0001 --json`."
    )
    assert "Next action: `pcl index build --json`, then `pcl impact --diff --json`." not in pack["markdown"]
    assert "Latest context receipt could not be loaded: JSONDecodeError." in pack["markdown"]
    assert "- relevance: unscoped_latest (binding: none)" in pack["markdown"]


def test_context_pack_code_context_safety_survives_tight_budget(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_code_context_receipt(tmp_path, capsys)
    _set_receipt_created_at(tmp_path, impact, STALE_RECEIPT_CREATED_AT)
    monkeypatch.setattr(cli_module, "utc_now_iso", lambda: FIXED_NOW)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--max-tokens",
        "1",
        "--json",
    ]) == 2
    retry_budget = _assert_context_pack_budget_error(
        _json_output(capsys),
        max_tokens=1,
    )["details"]["estimated_min_max_tokens"]

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--max-tokens",
        str(retry_budget),
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert "code_context_safety" in pack["included_sections"]
    assert "code_context_detail" not in pack["included_sections"]
    assert "code_context_detail" in pack["omitted_sections"]
    assert "## Code Context Safety" in pack["markdown"]
    assert "## Code Context Detail" not in pack["markdown"]
    assert "- relevance: unscoped_latest (binding: none)" in pack["markdown"]
    assert f"- receipt age: 5400s (created_at {STALE_RECEIPT_CREATED_AT})" in pack["markdown"]
    assert "diff_source=worktree-vs-HEAD" in pack["markdown"]
    assert "sensitive_omitted_count=0" in pack["markdown"]
    assert "excluded_changed_file_count=0" in pack["markdown"]
    assert "Untracked omission warning:" in pack["markdown"]
    assert pack["code_context"]["receipt_ref"]["evidence_id"]
    assert pack["estimated_token_count"] <= pack["budget"]["max_tokens"]
    assert pack["budget"]["max_tokens"] == retry_budget


def test_context_pack_without_code_context_flag_is_unchanged_by_receipts(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)

    args = [
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--json",
    ]
    assert main(args) == 0
    before = json.dumps(_json_output(capsys), ensure_ascii=False, sort_keys=True)

    _write_code_context_receipt(tmp_path, capsys)

    assert main(args) == 0
    after_payload = _json_output(capsys)
    after = json.dumps(after_payload, ensure_ascii=False, sort_keys=True)

    assert after == before
    pack = after_payload["context_pack"]
    assert "code_context" not in pack
    assert "suggested_refresh_commands" not in pack
    assert "pcl impact --diff --json" not in pack["source_commands"]
    assert "code_context_safety" not in pack["included_sections"]
    assert "code_context_detail" not in pack["included_sections"]
    assert "## Code Context" not in pack["markdown"]


def test_context_pack_include_code_context_without_receipt_suggests_next_action(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Needs receipt",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    code_context = pack["code_context"]
    assert code_context["status"] == "missing_receipt"
    assert code_context["next_actions"] == [
        "pcl index build --json",
        "pcl impact --diff --for-task T-0001 --json",
    ]
    assert code_context["refresh_replay"] == {
        "fidelity": "unavailable",
        "commands": code_context["next_actions"],
        "reason": [
            "No replayable context receipt scope is available; follow the next actions to create fresh code-context evidence."
        ],
    }
    assert pack["suggested_refresh_commands"] == code_context["next_actions"]
    assert _receipt_show_latest_error_next_actions(tmp_path, capsys) == [
        "pcl index build --json",
        "pcl impact --diff --json",
    ]
    assert "pcl impact --diff --json" not in pack["source_commands"]
    assert _markdown_next_action_commands(pack["markdown"]) == pack["suggested_refresh_commands"]
    assert _markdown_next_action_line(pack["markdown"]) == (
        "Next action: `pcl index build --json`, then "
        "`pcl impact --diff --for-task T-0001 --json`."
    )
    assert "Next action: `pcl index build --json`, then `pcl impact --diff --json`." not in pack["markdown"]
    assert code_context["receipt_ref"] == {
        "evidence_id": None,
        "receipt_path": None,
        "created_at": None,
    }
    assert code_context["relevance"] == {
        "target_type": "task",
        "target_id": "T-0001",
        "scope": "missing_receipt",
        "binding_strength": "none",
        "reason": "No context receipt was available for this pack target.",
    }
    assert code_context["receipt_age"] == {"created_at": None}
    assert "could not be computed" in code_context["age_warning"]
    assert "code_context_safety" in pack["included_sections"]
    assert "No context receipt evidence was found." in pack["markdown"]
    assert "- relevance: missing_receipt (binding: none)" in pack["markdown"]
    assert "- receipt age: unknown (created_at none)" in pack["markdown"]


def test_context_pack_include_code_context_accepts_legacy_string_suggestion_receipt(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_code_context_receipt(tmp_path, capsys)
    legacy_receipt = json.loads(
        (FIXTURES / "context_receipt_v0_legacy_string_suggestions.json").read_text(
            encoding="utf-8"
        )
    )
    legacy_receipt["evidence_id"] = impact["evidence_id"]
    legacy_receipt["receipt_path"] = impact["receipt_path"]
    (tmp_path / impact["receipt_path"]).write_text(
        json.dumps(legacy_receipt, sort_keys=True),
        encoding="utf-8",
    )

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["code_context"]["verification_suggestions"] == [
        {"id": None, "command": "python3 -m pytest tests/test_cli.py"}
    ]
    assert "- python3 -m pytest tests/test_cli.py" in pack["markdown"]
    assert "VS-01" not in pack["markdown"]


def test_context_pack_source_commands_are_read_only_allowlisted_for_all_pack_kinds(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Task handoff",
    ]) == 0
    capsys.readouterr()

    pack_args = [
        ["context", "pack", "--job", "J-0001", "--json"],
        ["context", "pack", "--job", "J-0001", "--include-code-context", "--json"],
        ["context", "pack", "--task", "T-0001", "--json"],
        ["context", "pack", "--task", "T-0001", "--include-code-context", "--json"],
    ]
    allowed_read_only_commands = {
        "pcl jobs read J-0001 --json",
        "pcl prompt job J-0001 --json",
        "pcl task read T-0001 --json",
        "pcl task list --json",
        "pcl validate --json",
    }

    observed_commands = []
    for args in pack_args:
        assert main(["--root", str(tmp_path), *args]) == 0
        observed_commands.extend(_json_output(capsys)["context_pack"]["source_commands"])

    assert observed_commands
    assert set(observed_commands) == allowed_read_only_commands
    for command in observed_commands:
        assert command in allowed_read_only_commands
        assert "pcl impact" not in command
        assert "pcl index build" not in command


def test_context_pack_suggested_refresh_commands_match_receipt_show_for_stale_receipt(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_code_context_receipt(tmp_path, capsys)
    assert impact["staleness_warnings"]

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    commands = _json_output(capsys)["context_pack"]["suggested_refresh_commands"]
    assert commands == ["pcl index build --json", "pcl impact --diff --for-task T-0001 --json"]
    assert _receipt_show_latest_recommended_commands(tmp_path, capsys) == [
        "pcl index build --json",
        "pcl impact --diff --json",
    ]


def test_context_pack_suggested_refresh_commands_match_receipt_show_for_fresh_receipt(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_fresh_code_context_receipt(tmp_path, capsys)
    assert impact["staleness_warnings"] == []

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    commands = _json_output(capsys)["context_pack"]["suggested_refresh_commands"]
    assert commands == ["pcl impact --diff --for-task T-0001 --json"]
    assert _receipt_show_latest_recommended_commands(tmp_path, capsys) == [
        "pcl impact --diff --json",
    ]


def test_context_pack_refresh_replay_preserves_receipt_diff_scope(
    tmp_path: Path,
    capsys,
) -> None:
    _create_task_code_project(tmp_path, capsys)
    impact = _write_fresh_code_context_receipt(tmp_path, capsys)
    receipt_path = tmp_path / impact["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["diff_source"] = "worktree-vs-main+untracked"
    receipt["base_ref"] = "main"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--task",
        "T-0001",
        "--include-code-context",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    replay = pack["code_context"]["refresh_replay"]
    assert replay == {
        "fidelity": "scope_preserving",
        "commands": ["pcl impact --diff --base main --include-untracked --for-task T-0001 --json"],
        "reason": ["diff_source was worktree-vs-main+untracked."],
    }
    assert pack["suggested_refresh_commands"] == replay["commands"]
    assert _receipt_show_latest_recommended_commands(tmp_path, capsys) == [
        "pcl impact --diff --base main --include-untracked --json",
    ]


def _section_heading(section_id: str) -> str:
    return {
        "machine_context_rules": "## Machine Context Rules",
        "code_context_safety": "## Code Context Safety",
        "code_context_detail": "## Code Context Detail",
        "code_context_verification_suggestions": "## Code Context Verification Suggestions",
        "target_job": "## Target Job",
        "workflow_run": "## Workflow Run",
        "goal": "## Goal",
        "run_jobs": "## Jobs In This Run",
        "verifications": "## Verifications",
        "human_queue": "## Human Queue",
        "evidence": "## Evidence",
        "recent_events": "## Recent Events",
        "agent_prompt": "## Agent Prompt",
        "target_task": "## Target Task",
        "master_trace_context": "## Master Trace Context",
        "linked_evidence": "## Linked Evidence",
        "dependencies": "## Dependencies",
        "dependents": "## Dependents",
        "related_feature": "## Related Feature",
        "related_defect": "## Related Defect",
        "sibling_tasks": "## Sibling Tasks",
    }[section_id]


def _assert_context_pack_budget_error(payload: dict, *, max_tokens: int) -> dict:
    assert payload["ok"] is False
    error = payload["error"]
    assert error["code"] == "context_pack_budget_too_small"
    assert "Context pack budget is too small" in error["message"]
    details = error["details"]
    assert details["max_tokens"] == max_tokens
    assert isinstance(details["estimated_min_max_tokens"], int)
    assert details["estimated_min_max_tokens"] > max_tokens
    assert isinstance(details["required_sections"], list)
    assert isinstance(details["required_section_token_counts"], dict)
    assert isinstance(details["title_token_count"], int)
    assert isinstance(details["truncation_note_token_count"], int)
    return error


def _without_required_metadata(pack: dict) -> dict:
    return {
        key: value
        for key, value in pack.items()
        if key not in {"required_sections", "required_sections_omitted"}
    }
