from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import subprocess

from pcl.cli import main
from pcl.code_context.scan import LARGE_FILE_BYTES
from pcl.code_context.summary import summarize_code_context_receipt
from pcl.code_context import store as code_context_store
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
    assert main(["--root", str(root), "index", "build", "--json", "--include-files"]) == 0
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


def _impact_json(root: Path, capsys, *args: str) -> dict:
    assert main(["--root", str(root), "impact", *args, "--json"]) == 0
    return _json_output(capsys)["impact"]


def _impact_error(root: Path, capsys, *args: str) -> dict:
    assert main(["--root", str(root), "impact", *args, "--json"]) == 2
    return _json_output(capsys)


def _receipt_payload(root: Path, impact: dict) -> dict:
    return json.loads((root / impact["receipt_path"]).read_text(encoding="utf-8"))


def _impact_equivalence_payload(root: Path, impact: dict) -> dict:
    receipt = _receipt_payload(root, impact)
    return {
        "changed_files": impact["changed_files"],
        "excluded_changed_files": impact["excluded_changed_files"],
        "omitted": impact["omitted"],
        "untracked_included_count": impact.get("untracked_included_count"),
        "untracked_included_paths": impact.get("untracked_included_paths"),
        "included_candidate_context": receipt["included_candidate_context"],
    }


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


def _diff_with_excluded_session_noise(root: Path) -> Path:
    diff_path = root / "excluded-session-noise.diff"
    diff_path.write_text(
        "\n".join(
            [
                "diff --git a/.claude/session-001.json b/.claude/session-001.json",
                "--- a/.claude/session-001.json",
                "+++ b/.claude/session-001.json",
                "@@ -1 +1 @@",
                '+{"session": 1}',
                "diff --git a/.claude/session-002.json b/.claude/session-002.json",
                "--- a/.claude/session-002.json",
                "+++ b/.claude/session-002.json",
                "@@ -1 +1 @@",
                '+{"session": 2}',
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
    assert "files" not in index
    assert "ignored" not in index
    assert "hash_skipped" not in index
    assert index["hash_skipped_count"] == 1
    assert index["staleness_warnings"] == []
    assert index["detail_path"] == ".project-loop/cache/code-index-detail.json"

    detail_path = tmp_path / index["detail_path"]
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    assert detail["detail_path"] == index["detail_path"]

    assert main(["--root", str(tmp_path), "index", "build", "--json", "--include-files"]) == 0
    include_files_output = capsys.readouterr().out
    include_index = json.loads(include_files_output)["index"]
    assert len(first_output) < len(include_files_output)
    assert include_index == json.loads(detail_path.read_text(encoding="utf-8"))

    files = {item["path"]: item for item in include_index["files"]}
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

    ignored = {item["path"]: item for item in include_index["ignored"]}
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
        assert run_count == 3
        assert file_count == index["file_count"] * 3
        assert event_count == 3
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

    assert main(["--root", str(tmp_path), "index", "build", "--json", "--include-files"]) == 0
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
    assert "files" not in fresh
    assert "ignored" not in fresh
    assert fresh["hash_skipped_count"] == 1
    assert fresh["detail_path"] == ".project-loop/cache/code-index-detail.json"
    status_detail = json.loads((tmp_path / fresh["detail_path"]).read_text(encoding="utf-8"))
    assert "files" in status_detail
    assert "ignored" in status_detail
    assert status_detail["file_count"] == fresh["file_count"]

    assert main(["--root", str(tmp_path), "index", "status", "--json", "--include-files"]) == 0
    full_status = _json_output(capsys)["index"]
    assert "files" in full_status
    assert "ignored" in full_status
    assert full_status == json.loads((tmp_path / full_status["detail_path"]).read_text(encoding="utf-8"))

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
    assert payload["search"]["results"][0]["snapshot_consistency"] == "fresh"
    assert payload["search"]["staleness_warnings"] == {"count": 0, "affected_paths": []}
    assert payload["search"]["git_head_warning"] is None
    assert payload["search"]["results"][1]["path"] == "tests/test_calc.py"


def test_code_search_reports_snapshot_consistency_for_returned_results(
    tmp_path: Path,
    capsys,
) -> None:
    _init_code_project(tmp_path, capsys)
    (tmp_path / "src" / "pkg" / "fresh_consistency.py").write_text(
        "class SnapshotConsistencyFresh:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "pkg" / "modified_consistency.py").write_text(
        "class SnapshotConsistencyModified:\n    pass\n",
        encoding="utf-8",
    )
    missing_path = tmp_path / "src" / "pkg" / "missing_consistency.py"
    missing_path.write_text(
        "class SnapshotConsistencyMissing:\n    pass\n",
        encoding="utf-8",
    )
    large_path = tmp_path / "assets" / "large-consistency.txt"
    large_path.write_text(
        "SnapshotConsistencyLarge\n" + ("x" * LARGE_FILE_BYTES),
        encoding="utf-8",
    )
    _build_index(tmp_path, capsys)

    (tmp_path / "src" / "pkg" / "modified_consistency.py").write_text(
        "class SnapshotConsistencyModified:\n    changed = True\n",
        encoding="utf-8",
    )
    missing_path.unlink()

    assert main(["--root", str(tmp_path), "code", "search", "SnapshotConsistency", "--json"]) == 0
    payload = _json_output(capsys)
    results = {item["path"]: item for item in payload["search"]["results"]}

    assert results["src/pkg/fresh_consistency.py"]["snapshot_consistency"] == "fresh"
    assert results["src/pkg/modified_consistency.py"]["snapshot_consistency"] == "modified_since_index"
    assert results["src/pkg/missing_consistency.py"]["snapshot_consistency"] == "missing_from_worktree"
    assert results["assets/large-consistency.txt"]["snapshot_consistency"] == "not_hashed"
    assert results["assets/large-consistency.txt"]["hash_skipped_reason"] == f"size>{LARGE_FILE_BYTES}"
    assert payload["search"]["staleness_warnings"] == {
        "count": 3,
        "affected_paths": [
            "src/pkg/modified_consistency.py",
            "src/pkg/missing_consistency.py",
            "assets/large-consistency.txt",
        ],
    }

    field_values = [
        value
        for item in results.values()
        for key, value in item.items()
        if key.startswith("snapshot_consistency")
    ]
    serialized = json.dumps(field_values, sort_keys=True).lower()
    assert "understood" not in serialized
    assert "analyzed" not in serialized
    assert "agent read" not in serialized

    assert main(["--root", str(tmp_path), "code", "search", "SnapshotConsistency"]) == 0
    text_output = capsys.readouterr().out
    assert "warning: snapshot_consistency=modified_since_index" in text_output
    assert "warning: snapshot_consistency=missing_from_worktree" in text_output
    assert "warning: snapshot_consistency=not_hashed" in text_output


def test_code_search_hashes_returned_results_only(tmp_path: Path, capsys, monkeypatch) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)
    original_sha256_file = code_context_store._sha256_file
    hashed_paths: list[str] = []

    def counting_sha256_file(path: Path) -> str:
        hashed_paths.append(path.relative_to(tmp_path).as_posix())
        return original_sha256_file(path)

    monkeypatch.setattr(code_context_store, "_sha256_file", counting_sha256_file)

    assert main(["--root", str(tmp_path), "code", "search", "Calculator", "--limit", "1", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["search"]["result_count"] == 1
    assert hashed_paths == [payload["search"]["results"][0]["path"]]


def test_code_search_json_is_deterministic_on_unchanged_tree(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "code", "search", "Calculator", "--json"]) == 0
    first_output = capsys.readouterr().out
    assert main(["--root", str(tmp_path), "code", "search", "Calculator", "--json"]) == 0
    second_output = capsys.readouterr().out

    assert first_output == second_output


def test_code_search_suggests_reindex_when_git_head_moves(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "pcl@example.test")
    _git(tmp_path, "config", "user.name", "Project Loop Harness")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    _build_index(tmp_path, capsys)

    (tmp_path / "docs" / "head-change.md").write_text("Calculator head change\n", encoding="utf-8")
    _git(tmp_path, "add", "docs/head-change.md")
    _git(tmp_path, "commit", "-m", "move head")

    assert main(["--root", str(tmp_path), "code", "search", "Calculator", "--json"]) == 0
    payload = _json_output(capsys)
    warning = payload["search"]["git_head_warning"]

    assert warning["code"] == "git_head_changed"
    assert warning["suggested_command"] == "pcl index build --json"
    assert warning["index_git_head"] != warning["current_git_head"]

    assert main(["--root", str(tmp_path), "code", "search", "Calculator"]) == 0
    text_output = capsys.readouterr().out
    assert text_output.count("Git HEAD differs from the latest code index snapshot") == 1
    assert "pcl index build --json" in text_output


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


def test_impact_diff_source_modes_are_unique_and_record_provenance(tmp_path: Path, capsys) -> None:
    _init_git_code_project(tmp_path, capsys)
    _append_text(tmp_path / "src" / "pkg" / "calc.py", "\ndef committed_change():\n    return 1\n")
    _git(tmp_path, "add", "src/pkg/calc.py")
    _git(tmp_path, "commit", "-m", "committed change")
    _build_index(tmp_path, capsys)
    _append_text(tmp_path / "src" / "pkg" / "calc.py", "\ndef staged_change():\n    return 2\n")
    _git(tmp_path, "add", "src/pkg/calc.py")
    _append_text(tmp_path / "docs" / "calc.md", "\nUnstaged note.\n")
    (tmp_path / "src" / "pkg" / "new_feature.py").write_text("def new_feature():\n    return 3\n", encoding="utf-8")

    cases = {
        "default": (["--diff"], "worktree-vs-HEAD", None),
        "base": (["--diff", "--base", "HEAD~1"], "worktree-vs-HEAD~1", "HEAD~1"),
        "staged": (["--diff", "--staged"], "staged-vs-HEAD", None),
        "staged-base": (["--diff", "--staged", "--base", "HEAD~1"], "staged-vs-HEAD~1", "HEAD~1"),
        "unstaged": (["--diff", "--unstaged"], "worktree-vs-index", None),
        "include-untracked": (
            ["--diff", "--include-untracked"],
            "worktree-vs-HEAD+untracked",
            None,
        ),
        "base-include-untracked": (
            ["--diff", "--base", "HEAD~1", "--include-untracked"],
            "worktree-vs-HEAD~1+untracked",
            "HEAD~1",
        ),
        "staged-include-untracked": (
            ["--diff", "--staged", "--include-untracked"],
            "staged-vs-HEAD+untracked",
            None,
        ),
        "unstaged-include-untracked": (
            ["--diff", "--unstaged", "--include-untracked"],
            "worktree-vs-index+untracked",
            None,
        ),
        "all-changes": (
            ["--diff", "--all-changes"],
            "all-changes-vs-HEAD+untracked",
            None,
        ),
    }

    observed_sources: list[str] = []
    for args, expected_source, expected_base_ref in cases.values():
        impact = _impact_json(tmp_path, capsys, *args)
        observed_sources.append(impact["diff_source"])
        assert impact["diff_source"] == expected_source
        assert impact["diff_provenance"]["attestation"] == "local-git"
        assert "command_shape" in impact["diff_provenance"]
        if expected_base_ref is None:
            assert "base_ref" not in impact
        else:
            assert impact["base_ref"] == expected_base_ref
        if expected_source.endswith("+untracked"):
            assert impact["diff_provenance"]["untracked_count"] == 1
            assert impact["untracked_included_count"] == 1
        else:
            assert "untracked_count" not in impact["diff_provenance"]
            assert "untracked_included_count" not in impact

    assert len(set(observed_sources)) == len(cases)


def test_impact_include_untracked_receipt_content_and_summary(tmp_path: Path, capsys) -> None:
    _init_git_code_project(tmp_path, capsys)
    (tmp_path / "src" / "pkg" / "new_feature.py").write_text(
        "def new_feature():\n    return 'new'\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(f"API_TOKEN={FAKE_SECRET_TOKEN}\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text(f"ignored {FAKE_SECRET_TOKEN}\n", encoding="utf-8")

    impact = _impact_json(tmp_path, capsys, "--diff", "--include-untracked")

    assert impact["diff_source"] == "worktree-vs-HEAD+untracked"
    assert impact["diff_provenance"]["untracked_count"] == 2
    assert impact["untracked_included_count"] == 2
    assert impact["untracked_included_paths"] == [".env", "src/pkg/new_feature.py"]
    assert impact["changed_files"] == [
        {
            "path": "src/pkg/new_feature.py",
            "status": "A",
            "indexed": False,
            "language": None,
            "reason": "untracked file included as added file",
            "untracked": True,
        }
    ]
    assert impact["excluded_changed_files"] == [
        {"path": ".env", "status": "A", "reason": "sensitive:agent_may_not_modify"}
    ]
    assert "ignored.txt" not in json.dumps(impact, sort_keys=True)

    receipt = _receipt_payload(tmp_path, impact)
    added_candidates = [
        item for item in receipt["included_candidate_context"] if item["role"] == "added_file"
    ]
    assert [item["path"] for item in added_candidates] == ["src/pkg/new_feature.py"]
    assert added_candidates[0]["language"] == "python"
    assert added_candidates[0]["line_count"] == 2
    assert added_candidates[0]["snapshot_consistency"] == "untracked"
    receipt_blob = json.dumps(receipt, sort_keys=True)
    assert FAKE_SECRET_TOKEN not in receipt_blob
    assert "ignored.txt" not in receipt_blob

    summary = summarize_code_context_receipt(receipt)
    assert summary["untracked_omission_warning"] is None
    assert summary["untracked_included_count"] == 2
    assert summary["included_candidate_context_top"][0]["role"] == "added_file"


def test_impact_all_changes_matches_default_with_include_untracked(tmp_path: Path, capsys) -> None:
    _init_git_code_project(tmp_path, capsys)
    _append_text(tmp_path / "src" / "pkg" / "calc.py", "\ndef tracked_change():\n    return 1\n")
    (tmp_path / "src" / "pkg" / "new_feature.py").write_text("def new_feature():\n    return 2\n", encoding="utf-8")

    include_untracked = _impact_json(tmp_path, capsys, "--diff", "--include-untracked")
    all_changes = _impact_json(tmp_path, capsys, "--diff", "--all-changes")

    assert include_untracked["diff_source"] == "worktree-vs-HEAD+untracked"
    assert all_changes["diff_source"] == "all-changes-vs-HEAD+untracked"
    assert _impact_equivalence_payload(tmp_path, all_changes) == _impact_equivalence_payload(
        tmp_path,
        include_untracked,
    )


def test_impact_base_auto_resolution_and_failure(tmp_path: Path, capsys) -> None:
    origin_root = tmp_path / "origin-head"
    origin_root.mkdir()
    _init_git_code_project(origin_root, capsys)
    _git(origin_root, "branch", "-M", "main")
    _git(origin_root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(origin_root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    _append_text(origin_root / "docs" / "calc.md", "\nOrigin auto note.\n")

    origin_impact = _impact_json(origin_root, capsys, "--diff", "--base", "auto")

    assert origin_impact["base_ref"] == "origin/main"
    assert origin_impact["diff_source"] == "worktree-vs-origin/main"
    assert origin_impact["diff_provenance"]["base_ref"] == "origin/main"
    assert origin_impact["diff_provenance"]["base_ref_resolution"] == "auto"
    assert origin_impact["diff_provenance"]["base_ref_attempted_refs"] == [
        "origin/HEAD",
        "main",
        "master",
    ]

    local_root = tmp_path / "local-main"
    local_root.mkdir()
    _init_git_code_project(local_root, capsys)
    _git(local_root, "branch", "-M", "main")
    _append_text(local_root / "docs" / "calc.md", "\nLocal auto note.\n")

    local_impact = _impact_json(local_root, capsys, "--diff", "--base", "auto")

    assert local_impact["base_ref"] == "main"
    assert local_impact["diff_source"] == "worktree-vs-main"
    assert local_impact["diff_provenance"]["base_ref"] == "main"

    missing_root = tmp_path / "missing-auto"
    missing_root.mkdir()
    _init_git_code_project(missing_root, capsys)
    _git(missing_root, "branch", "-M", "feature")

    payload = _impact_error(missing_root, capsys, "--diff", "--base", "auto")

    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"]["attempted_refs"] == ["origin/HEAD", "main", "master"]
    assert "Could not resolve --base auto" in payload["error"]["message"]


def test_impact_invalid_diff_mode_combinations_return_typed_errors(
    tmp_path: Path,
    capsys,
) -> None:
    _init_git_code_project(tmp_path, capsys)
    diff_path = _synthetic_diff(tmp_path)
    cases = [
        (["--diff", "--staged", "--unstaged"], "mutually_exclusive_diff_modes"),
        (["--diff", "--staged", "--all-changes"], "mutually_exclusive_diff_modes"),
        (["--diff", "--unstaged", "--all-changes"], "mutually_exclusive_diff_modes"),
        (["--diff", "--unstaged", "--base", "HEAD"], "base_unstaged_conflict"),
        (["--diff", "--all-changes", "--base", "HEAD"], "base_all_changes_conflict"),
        (["--diff", str(diff_path), "--include-untracked"], "provided_diff_mode_conflict"),
        (["--diff", str(diff_path), "--staged"], "provided_diff_mode_conflict"),
    ]

    for args, mode_error in cases:
        payload = _impact_error(tmp_path, capsys, *args)
        assert payload["error"]["code"] == "invalid_input"
        assert payload["error"]["details"]["mode_error"] == mode_error


def test_impact_empty_diff_guidance_is_mode_aware(tmp_path: Path, capsys) -> None:
    _init_git_code_project(tmp_path, capsys)
    (tmp_path / "src" / "pkg" / "untracked_only.py").write_text("VALUE = 1\n", encoding="utf-8")

    default_empty = _impact_json(tmp_path, capsys, "--diff")

    assert default_empty["diff_source"] == "worktree-vs-HEAD"
    assert default_empty["receipt_path"] is None
    assert any("--include-untracked" in step for step in default_empty["empty_diff_guidance"]["next_steps"])

    _append_text(tmp_path / "docs" / "calc.md", "\nUnstaged-only note.\n")
    staged_empty = _impact_json(tmp_path, capsys, "--diff", "--staged")

    assert staged_empty["diff_source"] == "staged-vs-HEAD"
    assert staged_empty["receipt_path"] is None
    assert any("git add" in step for step in staged_empty["empty_diff_guidance"]["next_steps"])

    _git(tmp_path, "add", "docs/calc.md")
    unstaged_empty = _impact_json(tmp_path, capsys, "--diff", "--unstaged")

    assert unstaged_empty["diff_source"] == "worktree-vs-index"
    assert unstaged_empty["receipt_path"] is None
    assert any("--staged" in step for step in unstaged_empty["empty_diff_guidance"]["next_steps"])


def test_impact_default_mode_contract_excludes_untracked_additive_fields(
    tmp_path: Path,
    capsys,
) -> None:
    _init_git_code_project(tmp_path, capsys)
    _append_text(tmp_path / "src" / "pkg" / "calc.py", "\ndef tracked_change():\n    return 1\n")
    (tmp_path / "src" / "pkg" / "new_feature.py").write_text("def new_feature():\n    return 2\n", encoding="utf-8")

    impact = _impact_json(tmp_path, capsys, "--diff")

    assert impact["diff_source"] == "worktree-vs-HEAD"
    assert impact["diff_provenance"] == {
        "source": "local-git-worktree",
        "attestation": "local-git",
        "command_shape": "git diff --no-ext-diff --no-textconv --name-status HEAD --",
    }
    assert "untracked_included_count" not in impact
    assert "untracked_included_paths" not in impact
    assert [item["path"] for item in impact["changed_files"]] == ["src/pkg/calc.py"]

    receipt = _receipt_payload(tmp_path, impact)
    summary = summarize_code_context_receipt(receipt)
    assert "untracked_included_count" not in summary
    assert summary["untracked_omission_warning"] == (
        "Untracked files are not included in this diff source; add them to Git "
        "or provide an explicit diff with `pcl impact --diff - --json`."
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
    included_snapshot_values = {
        item["snapshot_consistency"]
        for item in receipt["included_candidate_context"]
    }
    assert included_snapshot_values == {"fresh"}
    for item in receipt["included_candidate_context"]:
        assert "snapshot_consistency_reason" in item
    serialized = json.dumps(receipt, sort_keys=True).lower()
    assert "understood" not in serialized
    assert "analyzed" not in serialized
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


def test_impact_splits_excluded_changed_files_from_indexable_candidates(
    tmp_path: Path,
    capsys,
) -> None:
    _init_code_project(tmp_path, capsys)
    diff_path = _diff_with_excluded_session_noise(tmp_path)
    _build_index(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "impact", "--diff", str(diff_path), "--json"]) == 0
    impact = _json_output(capsys)["impact"]

    assert [item["path"] for item in impact["changed_files"]] == ["src/pkg/calc.py"]
    assert impact["excluded_changed_files"] == [
        {"path": ".claude/session-001.json", "status": "M", "reason": "code_index.exclude:.claude/"},
        {"path": ".claude/session-002.json", "status": "M", "reason": "code_index.exclude:.claude/"},
    ]
    assert not any(item["path"].startswith(".claude/") for item in impact["omitted"])
    assert {item["source_path"] for item in impact["likely_impacted"]} == {"src/pkg/calc.py"}
    assert any("python3 -m pytest tests/test_calc.py" in item for item in impact["verification_suggestions"])

    receipt = json.loads((tmp_path / impact["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["excluded_changed_files"] == impact["excluded_changed_files"]
    assert [item["path"] for item in receipt["included_candidate_context"] if item["role"] == "changed_file"] == [
        "src/pkg/calc.py"
    ]

    assert main(["--root", str(tmp_path), "impact", "--diff", str(diff_path)]) == 0
    text = capsys.readouterr().out
    assert "excluded_changed_file_count" in text
    assert "Excluded changed files: 2 (.claude/session-001.json, .claude/session-002.json)" in text
    assert '"excluded_changed_files"' not in text


def test_impact_excluded_only_diff_does_not_emit_indexable_suggestions(
    tmp_path: Path,
    capsys,
) -> None:
    _init_code_project(tmp_path, capsys)
    diff_path = tmp_path / "excluded-only.diff"
    diff_path.write_text(
        "\n".join(
            [
                "diff --git a/.claude/session-001.json b/.claude/session-001.json",
                "--- a/.claude/session-001.json",
                "+++ b/.claude/session-001.json",
                "@@ -1 +1 @@",
                '+{"session": 1}',
            ]
        ),
        encoding="utf-8",
    )
    _build_index(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "impact", "--diff", str(diff_path), "--json"]) == 0
    impact = _json_output(capsys)["impact"]

    assert impact["changed_files"] == []
    assert impact["likely_impacted"] == []
    assert impact["verification_suggestions"] == []
    assert impact["omitted"] == []
    assert impact["excluded_changed_files"] == [
        {"path": ".claude/session-001.json", "status": "M", "reason": "code_index.exclude:.claude/"}
    ]


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


def test_eval_retrieval_ignores_unknown_fixture_fields(tmp_path: Path, capsys) -> None:
    _init_code_project(tmp_path, capsys)
    _build_index(tmp_path, capsys)
    fixture_path = tmp_path / "retrieval_fixture_extra_fields.json"
    fixture_path.write_text(
        json.dumps(
            {
                "contract_version": "retrieval-fixture/v0",
                "fixture_family": "real-history",
                "unknown_top_level": {"ignored": True},
                "tasks": [
                    {
                        "id": "calc-query-extra-fields",
                        "query": "Calculator",
                        "expected_files": ["src/pkg/calc.py"],
                        "expected_tests": ["tests/test_calc.py"],
                        "critical_context": ["src/pkg/calc.py"],
                        "unknown_task_field": ["ignored"],
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    assert main(["--root", str(tmp_path), "eval", "retrieval", "--fixture", str(fixture_path), "--json"]) == 0
    evaluation = _json_output(capsys)["evaluation"]

    assert evaluation["task_count"] == 1
    assert evaluation["tasks"][0]["id"] == "calc-query-extra-fields"
    assert "src/pkg/calc.py" in evaluation["tasks"][0]["retrieved_paths"]


def test_eval_retrieval_rejects_missing_tasks_with_typed_error(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    fixture_path = tmp_path / "missing_tasks.json"
    fixture_path.write_text(
        json.dumps({"contract_version": "retrieval-fixture/v0"}, sort_keys=True),
        encoding="utf-8",
    )

    assert main(["--root", str(tmp_path), "eval", "retrieval", "--fixture", str(fixture_path), "--json"]) == 2
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "invalid_input"
    assert "non-empty tasks array" in payload["error"]["message"]


def test_eval_retrieval_rejects_invalid_json_fixture_with_typed_error(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    fixture_path = tmp_path / "invalid_retrieval_fixture.json"
    fixture_path.write_text("{not json", encoding="utf-8")

    assert main(["--root", str(tmp_path), "eval", "retrieval", "--fixture", str(fixture_path), "--json"]) == 2
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "invalid_input"
    assert "valid JSON" in payload["error"]["message"]


def test_adversarial_eval_secret_like_paths_are_omitted(tmp_path: Path, capsys) -> None:
    evaluation = _run_adversarial_retrieval_eval(tmp_path, capsys)
    task = _eval_task(evaluation, "adversarial-secret-like-omission")

    assert task["sensitive_omitted_count"] == len(SENSITIVE_FIXTURE_FILES)
    assert not (set(task["retrieved_paths"]) & set(SENSITIVE_FIXTURE_FILES))
    assert task["missing_critical_context"] == []
    assert task["excluded_changed_files"] == [
        {"path": ".env", "status": "M", "reason": "sensitive:agent_may_not_modify"}
    ]


def test_adversarial_eval_stale_index_surfaces_staleness(tmp_path: Path, capsys) -> None:
    evaluation = _run_adversarial_retrieval_eval(tmp_path, capsys)
    task = _eval_task(evaluation, "adversarial-stale-index")

    assert "src/pkg/calc.py" in task["retrieved_paths"]
    assert task["staleness_warnings"]
    assert task["staleness_affected_paths"] == ["src/pkg/calc.py"]
    assert task["retrieved_snapshot_consistency"] == {
        "src/pkg/calc.py": "modified_since_index"
    }
    assert task["missing_critical_context"] == []


def test_adversarial_eval_renamed_file_records_known_baseline_miss(
    tmp_path: Path,
    capsys,
) -> None:
    evaluation = _run_adversarial_retrieval_eval(tmp_path, capsys)
    task = _eval_task(evaluation, "adversarial-renamed-file-known-miss")

    assert task["expected_misses"] == [
        {
            "path": "src/pkg/current_widget.py",
            "reason": (
                "Current lexical impact baseline does not resolve renamed "
                "destination paths that were absent from the index."
            ),
        }
    ]
    assert "src/pkg/current_widget.py" not in task["retrieved_paths"]
    assert task["recall"] == 0.0
    assert {"task_id": task["id"], "path": "src/pkg/current_widget.py"} in evaluation[
        "metrics"
    ]["missing_critical_context"]


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


def _run_adversarial_retrieval_eval(root: Path, capsys) -> dict:
    _init_code_project(root, capsys)
    _write_sensitive_fixture_files(root)
    (root / "src" / "pkg" / "legacy_widget.py").write_text(
        "class LegacyWidget:\n    pass\n",
        encoding="utf-8",
    )
    _build_index(root, capsys)
    _append_text(
        root / "src" / "pkg" / "calc.py",
        "\nSTALE_EVAL_MARKER = 'StaleEvalMarker'\n",
    )
    (root / "src" / "pkg" / "legacy_widget.py").rename(
        root / "src" / "pkg" / "current_widget.py"
    )
    fixture_path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "retrieval_adversarial_v0.json"

    assert main(["--root", str(root), "eval", "retrieval", "--fixture", str(fixture_path), "--json"]) == 0
    return _json_output(capsys)["evaluation"]


def _eval_task(evaluation: dict, task_id: str) -> dict:
    return {task["id"]: task for task in evaluation["tasks"]}[task_id]
