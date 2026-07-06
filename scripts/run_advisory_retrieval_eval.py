from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


ADVERSARIAL_SECRET_TOKEN = "PCL_FAKE_TOKEN_0072_DO_NOT_LEAK"
ADVERSARIAL_SENSITIVE_FILES = {
    ".env": f"API_TOKEN={ADVERSARIAL_SECRET_TOKEN}\n",
    "server.pem": f"-----BEGIN PRIVATE KEY-----\n{ADVERSARIAL_SECRET_TOKEN}\n-----END PRIVATE KEY-----\n",
    "id_rsa": f"-----BEGIN OPENSSH PRIVATE KEY-----\n{ADVERSARIAL_SECRET_TOKEN}\n",
    "credentials.json": json.dumps({"token": ADVERSARIAL_SECRET_TOKEN}, sort_keys=True)
    + "\n",
    ".npmrc": f"//registry.npmjs.org/:_authToken={ADVERSARIAL_SECRET_TOKEN}\n",
}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    fixtures = args.fixtures or [
        str(root / "tests/fixtures/retrieval_v0.json"),
        str(root / "tests/fixtures/retrieval_real_history_v0.json"),
    ]
    fixture_summaries: list[dict[str, Any]] = []
    _init_project(root)
    _build_index(root)
    for fixture in fixtures:
        fixture_summaries.append(_evaluate_fixture(root, fixture))

    if not args.skip_adversarial:
        with tempfile.TemporaryDirectory(prefix="pcl-retrieval-adversarial-") as temp_dir:
            adversarial_root = Path(temp_dir)
            _prepare_adversarial_project(adversarial_root)
            fixture_summaries.append(
                _evaluate_fixture(
                    adversarial_root,
                    str(REPO_ROOT / "tests/fixtures/retrieval_adversarial_v0.json"),
                )
            )

    print(
        json.dumps(
            {
                "ok": True,
                "mode": "advisory",
                "note": "Metric values are reported for trend review; fixture or eval crashes fail this command.",
                "baseline_note": (
                    "Baseline comparisons are advisory when present; metric deltas do not fail this command."
                ),
                "fixtures": fixture_summaries,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--fixture", action="append", dest="fixtures", default=None)
    parser.add_argument("--skip-adversarial", action="store_true")
    return parser.parse_args(argv)


def _prepare_adversarial_project(root: Path) -> None:
    _init_project(root)
    (root / "src" / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "src" / "pkg" / "calc.py").write_text(
        "\n".join(
            [
                "class Calculator:",
                "    def add(self, left: int, right: int) -> int:",
                "        return left + right",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "tests" / "test_calc.py").write_text(
        "from pkg import calc\n\n"
        "def test_add():\n"
        "    assert calc.Calculator().add(1, 2) == 3\n",
        encoding="utf-8",
    )
    (root / "src" / "pkg" / "legacy_widget.py").write_text(
        "class LegacyWidget:\n    pass\n",
        encoding="utf-8",
    )
    for relative_path, content in ADVERSARIAL_SENSITIVE_FILES.items():
        (root / relative_path).write_text(content, encoding="utf-8")

    _build_index(root)
    _append_text(
        root / "src" / "pkg" / "calc.py",
        "\nSTALE_EVAL_MARKER = 'StaleEvalMarker'\n",
    )
    (root / "src" / "pkg" / "legacy_widget.py").rename(
        root / "src" / "pkg" / "current_widget.py"
    )


def _init_project(root: Path) -> None:
    _run_pcl(["init", "--target", str(root), "--json"])


def _build_index(root: Path) -> None:
    _run_pcl(["--root", str(root), "index", "build", "--json"])


def _evaluate_fixture(root: Path, fixture: str) -> dict[str, Any]:
    payload = _run_pcl(["--root", str(root), "eval", "retrieval", "--fixture", fixture, "--json"])
    evaluation = payload["evaluation"]
    summary = {
        "fixture_path": fixture,
        "task_count": evaluation["task_count"],
        "task_ids": [task["id"] for task in evaluation["tasks"]],
        "metrics": evaluation["metrics"],
    }
    adversarial = _adversarial_summary(evaluation["tasks"])
    if adversarial:
        summary["adversarial"] = adversarial
    comparison = _compare_fixture_if_baseline_exists(root, fixture)
    if comparison:
        summary["baseline_comparison"] = comparison
    return summary


def _adversarial_summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {task["id"]: task for task in tasks}
    if not any(task_id.startswith("adversarial-") for task_id in by_id):
        return {}
    secret = by_id["adversarial-secret-like-omission"]
    stale = by_id["adversarial-stale-index"]
    renamed = by_id["adversarial-renamed-file-known-miss"]
    return {
        "secret_sensitive_omitted_count": secret.get("sensitive_omitted_count"),
        "secret_retrieved_count": len(secret["retrieved_paths"]),
        "stale_affected_paths": stale.get("staleness_affected_paths", []),
        "renamed_expected_misses": renamed.get("expected_misses", []),
    }


def _run_pcl(args: list[str]) -> dict[str, Any]:
    completed = _run_pcl_completed(args)
    if completed.returncode != 0:
        _print_completed_output(completed)
        raise SystemExit(completed.returncode)
    return json.loads(completed.stdout)


def _run_pcl_completed(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-m", "pcl", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def _compare_fixture_if_baseline_exists(root: Path, fixture: str) -> dict[str, Any] | None:
    if not any((root / ".project-loop" / "evidence" / "retrieval-eval").glob("*.json")):
        return None
    completed = _run_pcl_completed(
        [
            "--root",
            str(root),
            "eval",
            "retrieval",
            "--fixture",
            fixture,
            "--compare-baseline",
            "--json",
        ]
    )
    if completed.returncode == 0:
        return json.loads(completed.stdout)["comparison"]
    _print_completed_output(completed)
    raise SystemExit(completed.returncode)


def _print_completed_output(completed: subprocess.CompletedProcess[str]) -> None:
    if completed.stdout:
        print(completed.stdout, file=sys.stderr, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")


def _append_text(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
