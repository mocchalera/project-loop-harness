from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_advisory_retrieval_eval.py"
TEST_ENV = {
    **os.environ,
    "PYTHONPATH": str(REPO_ROOT / "src")
    + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
}


def test_advisory_retrieval_eval_script_blocks_corrupted_fixture(tmp_path: Path) -> None:
    fixture_path = tmp_path / "corrupted-retrieval.json"
    fixture_path.write_text("{not json", encoding="utf-8")

    completed = _run_script(
        "--root",
        str(tmp_path),
        "--fixture",
        str(fixture_path),
        "--skip-adversarial",
    )

    assert completed.returncode != 0
    assert "valid JSON" in completed.stderr


def test_advisory_retrieval_eval_script_metric_delta_is_advisory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    fixture_path = tmp_path / "retrieval-fixture.json"
    _create_metric_delta_project(root, fixture_path)

    completed = _run_script(
        "--root",
        str(root),
        "--fixture",
        str(fixture_path),
        "--skip-adversarial",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    comparison = payload["fixtures"][0]["baseline_comparison"]
    assert comparison["metrics"]["delta"]["precision"] < 0
    assert comparison["metrics"]["delta"]["token_cost_estimate"] > 0
    assert "pass" not in json.dumps(comparison).lower()
    assert "verdict" not in json.dumps(comparison).lower()


def _create_metric_delta_project(root: Path, fixture_path: Path) -> None:
    _run_pcl("init", "--target", str(root), "--json")
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "calc.py").write_text(
        "class CalculatorSymbol:\n    pass\n",
        encoding="utf-8",
    )
    fixture_path.write_text(
        json.dumps(
            {
                "contract_version": "retrieval-fixture/v0",
                "tasks": [
                    {
                        "id": "calculator-symbol-query",
                        "query": "CalculatorSymbol",
                        "expected_files": ["src/pkg/calc.py"],
                        "expected_tests": [],
                        "critical_context": ["src/pkg/calc.py"],
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")
    _run_pcl("--root", str(root), "index", "build", "--json")
    _run_pcl(
        "--root",
        str(root),
        "eval",
        "retrieval",
        "--fixture",
        str(fixture_path),
        "--record-baseline",
        "--json",
    )
    (root / "docs").mkdir()
    (root / "docs" / "noise.md").write_text(
        "# CalculatorSymbol\n\nAdditional indexed prose with the same query term.\n",
        encoding="utf-8",
    )


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        env=TEST_ENV,
        text=True,
    )


def _run_pcl(*args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "pcl", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        env=TEST_ENV,
        text=True,
    )
    return json.loads(completed.stdout)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
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
