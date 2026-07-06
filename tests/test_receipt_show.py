from __future__ import annotations

import json
from pathlib import Path
import subprocess

from pcl.cli import main
from pcl.code_context.summary import (
    render_receipt_summary,
    summarize_code_context_receipt,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


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


def _create_code_receipt(root: Path, capsys) -> dict:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)
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
    assert main(["--root", str(root), "index", "build", "--json"]) == 0
    _json_output(capsys)
    app_path = root / "src" / "app.py"
    app_path.write_text(
        app_path.read_text(encoding="utf-8")
        + "\n\ndef parting() -> str:\n    return 'bye'\n",
        encoding="utf-8",
    )
    assert main(["--root", str(root), "impact", "--diff", "--json"]) == 0
    return _json_output(capsys)["impact"]


def test_receipt_show_json_matches_golden_summary_fixture(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    receipt_path = FIXTURES / "context_receipt_v0.json"
    expected = json.loads((FIXTURES / "code_context_summary_v0.json").read_text())

    assert main([
        "--root",
        str(tmp_path),
        "receipt",
        "show",
        str(receipt_path),
        "--json",
    ]) == 0

    assert _json_output(capsys) == expected


def test_receipt_show_evidence_path_and_latest_refs_use_shared_model(
    tmp_path: Path,
    capsys,
) -> None:
    impact = _create_code_receipt(tmp_path, capsys)
    receipt_payload = json.loads((tmp_path / impact["receipt_path"]).read_text())
    expected = summarize_code_context_receipt(receipt_payload)

    assert main([
        "--root",
        str(tmp_path),
        "receipt",
        "show",
        impact["evidence_id"],
        "--json",
    ]) == 0
    assert _json_output(capsys) == expected

    assert main([
        "--root",
        str(tmp_path),
        "receipt",
        "show",
        impact["receipt_path"],
        "--json",
    ]) == 0
    assert _json_output(capsys) == expected

    assert main(["--root", str(tmp_path), "receipt", "show", "--latest"]) == 0
    human = capsys.readouterr().out
    assert human.startswith("# Context Receipt Summary")
    assert f"- evidence_id: {impact['evidence_id']}" in human
    assert f"- receipt_path: {impact['receipt_path']}" in human
    assert "- diff_source: worktree-vs-HEAD" in human


def test_receipt_summary_human_rendering_order_and_wording() -> None:
    summary = json.loads((FIXTURES / "code_context_summary_v0.json").read_text())

    rendered = render_receipt_summary(summary)

    headings = [
        "## Receipt",
        "## Counts",
        "## Staleness Warnings",
        "## Untracked Omission Warning",
        "## Included Candidate Context",
        "## Omitted Reason Counts",
        "## Verification Suggestions",
        "## Next Recommended Command",
    ]
    positions = [rendered.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "included as candidate context" in rendered
    lower = rendered.lower()
    assert "understood" not in lower
    assert "analyzed" not in lower
    assert "safe_to_continue" not in lower
    assert "verdict" not in lower


def test_receipt_show_bad_id_returns_typed_guidance(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)

    assert main([
        "--root",
        str(tmp_path),
        "receipt",
        "show",
        "E-9999",
        "--json",
    ]) == 2

    _assert_receipt_error(capsys, "unknown_evidence_id")


def test_receipt_show_non_receipt_id_returns_typed_guidance(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "add",
        "--name",
        "Receipt errors",
        "--surface",
        "cli:receipt",
        "--json",
    ]) == 0
    _json_output(capsys)
    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "status",
        "F-0001",
        "--status",
        "specified",
        "--summary",
        "Create non-receipt evidence",
        "--evidence",
        "Feature status evidence",
        "--json",
    ]) == 0
    evidence_id = _json_output(capsys)["evidence_id"]

    assert main([
        "--root",
        str(tmp_path),
        "receipt",
        "show",
        evidence_id,
        "--json",
    ]) == 2

    _assert_receipt_error(capsys, "non_receipt_evidence_id")


def test_receipt_show_bad_path_returns_typed_guidance(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)

    assert main([
        "--root",
        str(tmp_path),
        "receipt",
        "show",
        ".project-loop/evidence/context-receipts/missing.json",
        "--json",
    ]) == 2

    _assert_receipt_error(capsys, "missing_receipt_file")


def test_receipt_show_invalid_json_returns_typed_guidance(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    receipt_path = tmp_path / "broken-receipt.json"
    receipt_path.write_text("{not json", encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "receipt",
        "show",
        str(receipt_path),
        "--json",
    ]) == 2

    _assert_receipt_error(capsys, "invalid_receipt_json")


def test_receipt_show_wrong_contract_returns_typed_guidance(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    receipt_path = tmp_path / "wrong-contract.json"
    receipt_path.write_text(
        json.dumps({"contract_version": "context-receipt/v9"}),
        encoding="utf-8",
    )

    assert main([
        "--root",
        str(tmp_path),
        "receipt",
        "show",
        str(receipt_path),
        "--json",
    ]) == 2

    _assert_receipt_error(capsys, "wrong_receipt_contract_version")


def test_receipt_show_latest_without_receipts_returns_typed_guidance(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)

    assert main([
        "--root",
        str(tmp_path),
        "receipt",
        "show",
        "--latest",
        "--json",
    ]) == 2

    payload = _assert_receipt_error(capsys, "missing_receipt")
    assert payload["error"]["details"]["next_actions"] == [
        "pcl index build --json",
        "pcl impact --diff --json",
    ]


def _assert_receipt_error(capsys, receipt_error: str) -> dict:
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
    assert "Next action:" in payload["error"]["message"]
    assert payload["error"]["details"]["receipt_error"] == receipt_error
    assert payload["error"]["details"]["next_actions"]
    return payload
