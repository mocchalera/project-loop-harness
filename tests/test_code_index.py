from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import subprocess

from pcl.cli import main
from pcl.db import connect

FAKE_SECRET_TOKEN = "PCL_FAKE_TOKEN_0072_DO_NOT_LEAK"
SENSITIVE_FIXTURE_FILES = {
    ".env": f"API_TOKEN={FAKE_SECRET_TOKEN}\n",
    "server.pem": f"-----BEGIN PRIVATE KEY-----\n{FAKE_SECRET_TOKEN}\n-----END PRIVATE KEY-----\n",
    "id_rsa": f"-----BEGIN OPENSSH PRIVATE KEY-----\n{FAKE_SECRET_TOKEN}\n",
    "credentials.json": json.dumps({"token": FAKE_SECRET_TOKEN}, sort_keys=True) + "\n",
    ".npmrc": f"//registry.npmjs.org/:_authToken={FAKE_SECRET_TOKEN}\n",
}


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
    (root / ".claude" / "state").mkdir(parents=True)
    (root / ".agents" / "skills" / "project-control-loop").mkdir(parents=True, exist_ok=True)
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
    (root / ".claude" / "state" / "session.json").write_text('{"noise": true}\n', encoding="utf-8")
    (root / ".agents" / "skills" / "project-control-loop" / "SKILL.md").write_text(
        "# Project Control Loop Skill\n",
        encoding="utf-8",
    )
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


def _init_git_code_project(root: Path, capsys) -> None:
    _init_code_project(root, capsys)
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")
    _build_index(root, capsys)


def _append_text(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _assert_diff_source_in_impact_and_receipt(
    root: Path,
    impact: dict,
    *,
    diff_source: str,
    base_ref: str | None = None,
) -> dict:
    assert impact["diff_source"] == diff_source
    if base_ref is None:
        assert "base_ref" not in impact
    else:
        assert impact["base_ref"] == base_ref
    receipt = json.loads((root / impact["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["diff_source"] == diff_source
    if base_ref is None:
        assert "base_ref" not in receipt
    else:
        assert receipt["base_ref"] == base_ref
    return receipt


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


def _write_sensitive_fixture_files(root: Path) -> None:
    for relative_path, content in SENSITIVE_FIXTURE_FILES.items():
        (root / relative_path).write_text(content, encoding="utf-8")


def _historical_multifile_diff_with_pathlike_body_lines(root: Path) -> Path:
    diff_path = root / "historical.diff"
    diff_path.write_text(
        "\n".join(
            [
                "diff --git a/README.md b/README.md",
                "--- a/README.md",
                "+++ b/README.md",
                "@@ -1,3 +1,3 @@",
                " The JSON contract is `context-pack/v1`. It includes included/omitted section",
                " See [docs/context-pack.md](docs/context-pack.md) for the contract shape and",
                "diff --git a/src/pcl/context.py b/src/pcl/context.py",
                "--- a/src/pcl/context.py",
                "+++ b/src/pcl/context.py",
                "@@ -1,3 +1,3 @@",
                " CONTEXT_PACK_CONTRACT_VERSION = \"context-pack/v1\"",
                "+TOKEN_ESTIMATOR = \"charclass/v1\"",
            ]
        ),
        encoding="utf-8",
    )
    return diff_path


def _latest_index_rows_blob(root: Path) -> str:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        runs = [
            dict(row)
            for row in conn.execute(
                "SELECT id, summary_json FROM code_index_runs ORDER BY id"
            ).fetchall()
        ]
        files = [
            dict(row)
            for row in conn.execute(
                """
                SELECT path, language, sha256, symbol_summary_json, test_hint_json
                FROM code_index_files
                ORDER BY index_run_id, path
                """
            ).fetchall()
        ]
    finally:
        conn.close()
    return json.dumps({"files": files, "runs": runs}, sort_keys=True)


def _diff_with_changed_test(root: Path) -> Path:
    diff_path = root / "changed-test.diff"
    diff_path.write_text(
        "\n".join(
            [
                "diff --git a/src/pkg/calc.py b/src/pkg/calc.py",
                "--- a/src/pkg/calc.py",
                "+++ b/src/pkg/calc.py",
                "@@ -1,3 +1,3 @@",
                "+def helper(value: int) -> int:",
                "diff --git a/tests/test_calc.py b/tests/test_calc.py",
                "--- a/tests/test_calc.py",
                "+++ b/tests/test_calc.py",
                "@@ -1,3 +1,3 @@",
                "+def test_helper():",
                "+    assert calc.helper(2) == 4",
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
    assert ".agents/" in ignored
    assert ".claude/" in ignored
    assert ignored[".agents/"]["ignored_reason"] == "code_index.exclude:.agents/"
    assert ignored[".claude/"]["ignored_reason"] == "code_index.exclude:.claude/"
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


def test_sensitive_files_are_omitted_from_index_search_and_receipts(
    tmp_path: Path,
    capsys,
) -> None:
    _init_code_project(tmp_path, capsys)
    _write_sensitive_fixture_files(tmp_path)

    index = _build_index(tmp_path, capsys)["index"]

    assert index["sensitive_omitted_count"] == len(SENSITIVE_FIXTURE_FILES)
    files = {item["path"] for item in index["files"]}
    assert not (set(SENSITIVE_FIXTURE_FILES) & files)
    ignored = {item["path"]: item for item in index["ignored"]}
    assert set(SENSITIVE_FIXTURE_FILES) <= set(ignored)
    assert ignored[".env"]["ignored_reason"] == "sensitive:agent_may_not_modify"
    assert ignored["server.pem"]["ignored_reason"] == "sensitive:*.pem"
    assert ignored["id_rsa"]["ignored_reason"] == "sensitive:id_rsa"
    assert ignored["credentials.json"]["ignored_reason"] == "sensitive:credentials*.json"
    assert ignored[".npmrc"]["ignored_reason"] == "sensitive:.npmrc"

    serialized_symbols = json.dumps(
        [item["symbol_summary"] for item in index["files"]],
        sort_keys=True,
    )
    assert FAKE_SECRET_TOKEN not in serialized_symbols

    assert main(["--root", str(tmp_path), "index", "build"]) == 0
    build_text = capsys.readouterr().out
    assert f"({len(SENSITIVE_FIXTURE_FILES)} sensitive)" in build_text

    assert main(["--root", str(tmp_path), "index", "status", "--json"]) == 0
    status = _json_output(capsys)["index"]
    assert status["sensitive_omitted_count"] == len(SENSITIVE_FIXTURE_FILES)

    assert main(["--root", str(tmp_path), "index", "status"]) == 0
    status_text = capsys.readouterr().out
    assert f'"sensitive_omitted_count": {len(SENSITIVE_FIXTURE_FILES)}' in status_text

    assert FAKE_SECRET_TOKEN not in _latest_index_rows_blob(tmp_path)

    assert main(["--root", str(tmp_path), "code", "search", FAKE_SECRET_TOKEN]) == 0
    search_text = capsys.readouterr().out
    assert search_text == ""
    assert FAKE_SECRET_TOKEN not in search_text

    diff_path = _synthetic_diff(tmp_path)
    assert main(["--root", str(tmp_path), "impact", "--diff", str(diff_path), "--json"]) == 0
    impact = _json_output(capsys)["impact"]
    receipt = json.loads((tmp_path / impact["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["sensitive_omitted_count"] == len(SENSITIVE_FIXTURE_FILES)
    receipt_blob = json.dumps(receipt, sort_keys=True)
    assert FAKE_SECRET_TOKEN not in receipt_blob
    assert not any(path in receipt_blob for path in SENSITIVE_FIXTURE_FILES)


def test_agent_may_not_modify_patterns_are_sensitive_excludes(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    (tmp_path / "private-config.yml").write_text(
        f"token: {FAKE_SECRET_TOKEN}\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "pcl.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "  agent_may_not_modify:\n",
            "  agent_may_not_modify:\n    - private-config.yml\n",
        ),
        encoding="utf-8",
    )

    index = _build_index(tmp_path, capsys)["index"]
    ignored = {item["path"]: item for item in index["ignored"]}

    assert ignored["private-config.yml"]["ignored_reason"] == "sensitive:agent_may_not_modify"
    assert "private-config.yml" not in {item["path"] for item in index["files"]}
    assert index["sensitive_omitted_count"] == 1


def test_code_index_sensitive_exclude_adds_project_patterns(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    (tmp_path / "fixture.secret").write_text(
        f"token: {FAKE_SECRET_TOKEN}\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "pcl.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "  sensitive_exclude: []\n",
            "  sensitive_exclude:\n    - *.secret\n",
        ),
        encoding="utf-8",
    )

    index = _build_index(tmp_path, capsys)["index"]
    ignored = {item["path"]: item for item in index["ignored"]}

    assert ignored["fixture.secret"]["ignored_reason"] == "sensitive:*.secret"
    assert "fixture.secret" not in {item["path"] for item in index["files"]}
    assert index["sensitive_omitted_count"] == 1


def test_sensitive_include_override_warns_records_and_search_still_guards_stale_rows(
    tmp_path: Path,
    capsys,
) -> None:
    _init_code_project(tmp_path, capsys)
    (tmp_path / "server.pem").write_text(
        f"fixture key material {FAKE_SECRET_TOKEN}\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "pcl.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "  sensitive_include_override: []\n",
            "  sensitive_include_override:\n    - server.pem\n",
        ),
        encoding="utf-8",
    )

    assert main(["--root", str(tmp_path), "index", "build", "--json"]) == 0
    captured = capsys.readouterr()
    index = json.loads(captured.out)["index"]
    assert "WARNING: code_index.sensitive_include_override is configured" in captured.err
    assert "server.pem" in {item["path"] for item in index["files"]}
    assert index["sensitive_omitted_count"] == 0

    assert main(["--root", str(tmp_path), "index", "build", "--json"]) == 0
    second_build = capsys.readouterr()
    assert "WARNING: code_index.sensitive_include_override is configured" in second_build.err

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        summary = json.loads(
            conn.execute(
                "SELECT summary_json FROM code_index_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()["summary_json"]
        )
    finally:
        conn.close()
    assert summary["sensitive_include_override"] == ["server.pem"]
    assert summary["sensitive_include_override_used"] is True

    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "  sensitive_include_override:\n    - server.pem\n",
            "  sensitive_include_override: []\n",
        ),
        encoding="utf-8",
    )

    assert main(["--root", str(tmp_path), "code", "search", FAKE_SECRET_TOKEN]) == 0
    search_text = capsys.readouterr().out
    assert search_text == ""
    assert FAKE_SECRET_TOKEN not in search_text


def test_code_index_excludes_can_be_overridden_from_pcl_yaml(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    config_path = tmp_path / "pcl.yaml"
    config_text = config_path.read_text(encoding="utf-8").replace(
        "code_index:\n  exclude:\n    - .claude/\n    - .agents/\n    - .codex/\n",
        "code_index:\n  exclude: []\n",
    )
    config_path.write_text(config_text, encoding="utf-8")

    index = _build_index(tmp_path, capsys)["index"]
    files = {item["path"] for item in index["files"]}
    ignored = {item["path"] for item in index["ignored"]}

    assert ".agents/skills/project-control-loop/SKILL.md" in files
    assert ".claude/state/session.json" in files
    assert ".agents/" not in ignored
    assert ".claude/" not in ignored


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


def test_code_search_returns_ranked_file_level_matches(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "code", "search", "Calculator add", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["search"]["contract_version"] == "code-search/v0"
    assert payload["search"]["results"][0]["path"] == "src/pkg/calc.py"
    assert {1, 2} <= set(payload["search"]["results"][0]["lines"])
    assert "definition-like hit" in payload["search"]["results"][0]["reason"]
    assert payload["search"]["results"][1]["path"] == "tests/test_calc.py"


def test_impact_default_diff_source_covers_staged_only_change(
    tmp_path: Path,
    capsys,
) -> None:
    _init_git_code_project(tmp_path, capsys)
    _append_text(tmp_path / "src" / "pkg" / "calc.py", "\ndef staged_only():\n    return 1\n")
    _git(tmp_path, "add", "src/pkg/calc.py")

    assert main(["--root", str(tmp_path), "impact", "--diff", "--json"]) == 0
    impact = _json_output(capsys)["impact"]

    assert [item["path"] for item in impact["changed_files"]] == ["src/pkg/calc.py"]
    _assert_diff_source_in_impact_and_receipt(
        tmp_path,
        impact,
        diff_source="worktree-vs-HEAD",
    )


def test_impact_default_diff_source_covers_unstaged_only_change(
    tmp_path: Path,
    capsys,
) -> None:
    _init_git_code_project(tmp_path, capsys)
    _append_text(tmp_path / "src" / "pkg" / "calc.py", "\ndef unstaged_only():\n    return 1\n")

    assert main(["--root", str(tmp_path), "impact", "--diff", "--json"]) == 0
    impact = _json_output(capsys)["impact"]

    assert [item["path"] for item in impact["changed_files"]] == ["src/pkg/calc.py"]
    _assert_diff_source_in_impact_and_receipt(
        tmp_path,
        impact,
        diff_source="worktree-vs-HEAD",
    )


def test_impact_default_diff_source_covers_staged_and_unstaged_changes(
    tmp_path: Path,
    capsys,
) -> None:
    _init_git_code_project(tmp_path, capsys)
    _append_text(tmp_path / "src" / "pkg" / "calc.py", "\ndef staged_change():\n    return 1\n")
    _git(tmp_path, "add", "src/pkg/calc.py")
    _append_text(tmp_path / "docs" / "calc.md", "\nMore usage notes.\n")

    assert main(["--root", str(tmp_path), "impact", "--diff", "--json"]) == 0
    impact = _json_output(capsys)["impact"]

    assert {item["path"] for item in impact["changed_files"]} == {
        "docs/calc.md",
        "src/pkg/calc.py",
    }
    _assert_diff_source_in_impact_and_receipt(
        tmp_path,
        impact,
        diff_source="worktree-vs-HEAD",
    )


def test_impact_base_ref_diff_source_records_base_ref(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    _git(tmp_path, "init")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    _append_text(tmp_path / "src" / "pkg" / "calc.py", "\ndef committed_change():\n    return 1\n")
    _git(tmp_path, "add", "src/pkg/calc.py")
    _git(tmp_path, "commit", "-m", "update calc")
    _build_index(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "impact", "--diff", "--base", "HEAD~1", "--json"]) == 0
    impact = _json_output(capsys)["impact"]

    assert [item["path"] for item in impact["changed_files"]] == ["src/pkg/calc.py"]
    _assert_diff_source_in_impact_and_receipt(
        tmp_path,
        impact,
        diff_source="worktree-vs-HEAD~1",
        base_ref="HEAD~1",
    )


def test_impact_piped_diff_source_is_provided_diff(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)
    monkeypatch.setattr("sys.stdin", io.StringIO(_synthetic_diff(tmp_path).read_text(encoding="utf-8")))

    assert main(["--root", str(tmp_path), "impact", "--diff", "-", "--json"]) == 0
    impact = _json_output(capsys)["impact"]
    receipt = _assert_diff_source_in_impact_and_receipt(
        tmp_path,
        impact,
        diff_source="provided-diff",
    )

    assert impact["diff_provenance"]["source"] == "stdin"
    assert impact["diff_provenance"]["attestation"] == "unattested"
    assert receipt["diff_provenance"]["source"] == "stdin"


def test_impact_unknown_base_ref_returns_typed_error(tmp_path: Path, capsys) -> None:
    _init_git_code_project(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "impact", "--diff", "--base", "missing-ref", "--json"]) == 2
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"]["base_ref"] == "missing-ref"
    assert "Unknown git ref for --base: missing-ref" in payload["error"]["message"]
    assert "fatal:" not in json.dumps(payload).lower()


def test_impact_empty_default_diff_gives_guidance_without_receipt(
    tmp_path: Path,
    capsys,
) -> None:
    _init_git_code_project(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "impact", "--diff", "--json"]) == 0
    impact = _json_output(capsys)["impact"]

    assert impact["diff_source"] == "worktree-vs-HEAD"
    assert impact["changed_files"] == []
    assert impact["receipt_path"] is None
    assert "evidence_id" not in impact
    assert "nothing to analyze" in impact["empty_diff_guidance"]["message"].lower()
    assert any("--base <default-branch>" in step for step in impact["empty_diff_guidance"]["next_steps"])
    receipt_dir = tmp_path / ".project-loop" / "evidence" / "context-receipts"
    assert not list(receipt_dir.glob("*.json"))


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
    assert impact["diff_source"] == "provided-diff"

    receipt_path = tmp_path / impact["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["contract_version"] == "context-receipt/v0"
    assert receipt["diff_source"] == "provided-diff"
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


def test_impact_diff_parser_ignores_pathlike_body_lines(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)
    diff_path = _historical_multifile_diff_with_pathlike_body_lines(tmp_path)

    assert main(["--root", str(tmp_path), "impact", "--diff", str(diff_path), "--json"]) == 0
    impact = _json_output(capsys)["impact"]

    assert [item["path"] for item in impact["changed_files"]] == [
        "README.md",
        "src/pcl/context.py",
    ]
    assert not any("context-pack/v1" in item["path"] for item in impact["changed_files"])
    assert not any("docs/context-pack.md" in item["path"] for item in impact["changed_files"])


def test_impact_suggests_changed_test_files_first(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)
    diff_path = _diff_with_changed_test(tmp_path)

    assert main(["--root", str(tmp_path), "impact", "--diff", str(diff_path), "--json"]) == 0
    impact = _json_output(capsys)["impact"]

    assert [item["path"] for item in impact["changed_files"]] == [
        "src/pkg/calc.py",
        "tests/test_calc.py",
    ]
    assert impact["verification_suggestions"][0] == "python3 -m pytest tests/test_calc.py"


def test_impact_caps_candidates_and_records_omissions(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    for index in range(25):
        (tmp_path / "tests" / f"test_calc_extra_{index:02d}.py").write_text(
            "from pkg import calc\n\n"
            f"def test_extra_{index:02d}():\n"
            "    assert calc.helper(2) == 4\n",
            encoding="utf-8",
        )
    for index in range(12):
        (tmp_path / "docs" / f"calculator-noise-{index:02d}.md").write_text(
            "# Calculator\n\nCalculator appears throughout common project prose.\n",
            encoding="utf-8",
        )
    _build_index(tmp_path, capsys)
    diff_path = _synthetic_diff(tmp_path)

    assert main(["--root", str(tmp_path), "impact", "--diff", str(diff_path), "--json"]) == 0
    impact = _json_output(capsys)["impact"]

    assert len(impact["likely_impacted"]) == 20
    assert any(item.get("omitted_type") == "likely_impacted_candidate" for item in impact["omitted"])
    assert any(
        item.get("omitted_type") == "lexical_symbol_reference" and item.get("symbol") == "Calculator"
        for item in impact["omitted"]
    )
    assert impact["verification_suggestions"][0] == "python3 -m pytest"
    assert all("test_calc_extra_00.py tests/test_calc_extra_01.py" not in item for item in impact["verification_suggestions"])


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


def test_real_history_retrieval_fixture_beats_recorded_baseline(tmp_path: Path, capsys) -> None:
    _copy_repo_subset_for_retrieval_eval(tmp_path)

    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    _build_index(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "eval",
        "retrieval",
        "--fixture",
        "tests/fixtures/retrieval_real_history_v0.json",
        "--json",
    ]) == 0
    evaluation = _json_output(capsys)["evaluation"]

    assert evaluation["metrics"]["precision"] >= 0.2
    assert evaluation["metrics"]["recall"] >= 0.8
    assert evaluation["metrics"]["precision"] > 0.1429
    assert evaluation["metrics"]["recall"] > 0.6667
    assert evaluation["metrics"]["missing_critical_context"] == []


def test_code_search_requires_existing_index(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)

    assert main(["--root", str(tmp_path), "code", "search", "anything", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "No code index run exists" in payload["error"]["message"]


def _copy_repo_subset_for_retrieval_eval(target: Path) -> None:
    source = Path(__file__).resolve().parents[1]
    for relative in [
        ".gitignore",
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "pcl.yaml",
        "pyproject.toml",
        "agent-tasks",
        "docs",
        "src",
        "tests",
    ]:
        source_path = source / relative
        target_path = target / relative
        if source_path.is_dir():
            shutil.copytree(
                source_path,
                target_path,
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache"),
            )
        else:
            shutil.copy2(source_path, target_path)
