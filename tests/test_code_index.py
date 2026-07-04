from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init_code_project(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "assets").mkdir()
    (root / "node_modules").mkdir()
    (root / "src" / "pkg" / "calc.py").write_text(
        "\n".join(
            [
                "class Calculator:",
                "    def add(self, left: int, right: int) -> int:",
                "        return left + right",
                "",
                "def helper(value: int) -> int:",
                "    return value * 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "tests" / "test_calc.py").write_text(
        "\n".join(
            [
                "from pkg import calc",
                "",
                "def test_add():",
                "    assert calc.Calculator().add(1, 2) == 3",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "src" / "pkg" / "ui.ts").write_text(
        "\n".join(
            [
                "export function renderCalc() {",
                "  return 'Calculator';",
                "}",
                "export class CalcView {}",
            ]
        ),
        encoding="utf-8",
    )
    (root / "docs" / "calc.md").write_text("# Calculator\n\n## Usage\n", encoding="utf-8")
    (root / "ignored.txt").write_text("ignored by gitignore\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        (root / ".gitignore").read_text(encoding="utf-8") + "\nignored.txt\n",
        encoding="utf-8",
    )
    (root / "assets" / "logo.bin").write_bytes(b"\x00\x01binary")
    (root / "node_modules" / "dep.js").write_text("export const dep = 1;\n", encoding="utf-8")


def _build_index(root: Path, capsys) -> dict:
    assert main(["--root", str(root), "index", "build", "--json"]) == 0
    return _json_output(capsys)


def _synthetic_diff(root: Path) -> Path:
    diff_path = root / "change.diff"
    diff_path.write_text(
        "\n".join(
            [
                "diff --git a/src/pkg/calc.py b/src/pkg/calc.py",
                "--- a/src/pkg/calc.py",
                "+++ b/src/pkg/calc.py",
                "@@ -1,3 +1,3 @@",
                "+def helper(value: int) -> int:",
            ]
        ),
        encoding="utf-8",
    )
    return diff_path


def test_index_build_records_gitignore_aware_snapshot_and_is_deterministic(
    tmp_path: Path,
    capsys,
) -> None:
    _init_code_project(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "index", "build", "--json"]) == 0
    first_output = capsys.readouterr().out
    assert main(["--root", str(tmp_path), "index", "build", "--json"]) == 0
    second_output = capsys.readouterr().out
    assert first_output == second_output

    payload = json.loads(first_output)
    index = payload["index"]
    assert index["contract_version"] == "code-index/v0"
    assert index["event_appended"] is True

    files = {item["path"]: item for item in index["files"]}
    assert "src/pkg/calc.py" in files
    assert files["src/pkg/calc.py"]["language"] == "python"
    assert len(files["src/pkg/calc.py"]["sha256"]) == 64
    symbol_names = {
        symbol["name"]
        for symbol in files["src/pkg/calc.py"]["symbol_summary"]["symbols"]
    }
    assert {"Calculator", "add", "helper"} <= symbol_names
    assert files["src/pkg/calc.py"]["test_hint"]["candidate_tests"] == [
        {
            "path": "tests/test_calc.py",
            "reason": "filename_match+python_import",
            "confidence": 0.88,
        }
    ]
    ts_symbols = {
        symbol["name"]
        for symbol in files["src/pkg/ui.ts"]["symbol_summary"]["symbols"]
    }
    assert {"renderCalc", "CalcView"} <= ts_symbols
    md_symbols = files["docs/calc.md"]["symbol_summary"]["symbols"]
    assert md_symbols[0]["name"] == "Calculator"

    ignored = {item["path"]: item for item in index["ignored"]}
    assert ".project-loop/" in ignored
    assert "node_modules/" in ignored
    assert ignored["ignored.txt"]["ignored_reason"].startswith("gitignore:")
    assert ignored["assets/logo.bin"]["ignored_reason"] == "binary_file"
    assert ignored["assets/logo.bin"]["hash_skipped_reason"] == "binary_file"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        run_count = conn.execute("SELECT COUNT(*) AS n FROM code_index_runs").fetchone()["n"]
        file_count = conn.execute("SELECT COUNT(*) AS n FROM code_index_files").fetchone()["n"]
        event_count = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'code_index_built'"
        ).fetchone()["n"]
        assert run_count == 2
        assert file_count == index["file_count"] * 2
        assert event_count == 2
    finally:
        conn.close()


def test_index_status_reports_staleness_after_file_change(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "index", "status", "--json"]) == 0
    fresh = _json_output(capsys)["index"]
    assert fresh["stale"] is False

    (tmp_path / "src" / "pkg" / "calc.py").write_text("def changed():\n    return 1\n", encoding="utf-8")

    assert main(["--root", str(tmp_path), "index", "status", "--json"]) == 0
    stale = _json_output(capsys)["index"]
    assert stale["stale"] is True
    assert any("Indexed file metadata changed" in warning for warning in stale["staleness_warnings"])


def test_code_search_returns_lexical_matches(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "code", "search", "Calculator add", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["search"]["contract_version"] == "code-search/v0"
    assert payload["search"]["results"][0]["path"] == "tests/test_calc.py"
    assert payload["search"]["results"][0]["lines"] == [4]
    assert payload["search"]["results"][0]["reason"] == "line contains all query terms"


def test_impact_writes_epistemically_honest_receipt_and_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)
    diff_path = _synthetic_diff(tmp_path)

    assert main(["--root", str(tmp_path), "impact", "--diff", str(diff_path), "--json"]) == 0
    payload = _json_output(capsys)
    impact = payload["impact"]

    assert impact["contract_version"] == "impact/v0"
    assert impact["changed_files"] == [
        {
            "path": "src/pkg/calc.py",
            "status": "M",
            "indexed": True,
            "language": "python",
            "reason": "changed file is present in the latest index",
        }
    ]
    assert any(item["path"] == "tests/test_calc.py" for item in impact["likely_impacted"])
    assert any("python3 -m pytest tests/test_calc.py" in item for item in impact["verification_suggestions"])
    assert impact["receipt_path"].startswith(".project-loop/evidence/context-receipts/")

    receipt_path = tmp_path / impact["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["contract_version"] == "context-receipt/v0"
    assert "included_candidate_context" in receipt
    assert "omitted" in receipt
    assert "staleness_warnings" in receipt
    serialized = json.dumps(receipt, sort_keys=True).lower()
    assert "understood" not in serialized
    assert "agent read" not in serialized

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        evidence = conn.execute(
            "SELECT id, type, path FROM evidence WHERE id = ?",
            (impact["evidence_id"],),
        ).fetchone()
        assert dict(evidence) == {
            "id": impact["evidence_id"],
            "type": "context_receipt",
            "path": impact["receipt_path"],
        }
        event = conn.execute(
            "SELECT event_type FROM events WHERE entity_id = ?",
            (impact["evidence_id"],),
        ).fetchone()
        assert event["event_type"] == "context_receipt_recorded"
    finally:
        conn.close()


def test_eval_retrieval_reports_precision_recall_and_missing_context(
    tmp_path: Path,
    capsys,
) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)
    fixture_path = tmp_path / "retrieval_fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "contract_version": "retrieval-fixture/v0",
                "tasks": [
                    {
                        "id": "calc-impact",
                        "diff": _synthetic_diff(tmp_path).read_text(encoding="utf-8"),
                        "expected_files": ["src/pkg/calc.py"],
                        "expected_tests": ["tests/test_calc.py"],
                        "critical_context": ["src/pkg/calc.py", "tests/test_calc.py"],
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    assert main(["--root", str(tmp_path), "eval", "retrieval", "--fixture", str(fixture_path), "--json"]) == 0
    payload = _json_output(capsys)
    evaluation = payload["evaluation"]

    assert evaluation["contract_version"] == "retrieval-eval/v0"
    assert evaluation["metrics"]["precision"] > 0
    assert evaluation["metrics"]["recall"] == 1.0
    assert evaluation["metrics"]["missing_critical_context"] == []


def test_code_search_requires_existing_index(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)

    assert main(["--root", str(tmp_path), "code", "search", "anything", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "No code index run exists" in payload["error"]["message"]
