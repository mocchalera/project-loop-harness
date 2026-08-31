from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def _run_cli(pythonpath: str, cwd: Path, *args: str) -> object:
    env = {**os.environ, "PYTHONPATH": pythonpath}
    result = subprocess.run(
        [sys.executable, "-m", "pcl", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_source_wheel_and_sdist_expose_the_same_agent_output_surface(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(dist_dir)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(dist_dir.glob("*.whl"))
    sdist = next(dist_dir.glob("*.tar.gz"))
    required = {
        "pcl/agent_output_policy.py",
        "pcl/agent_output_renderer.py",
        "pcl/agent_output_handlers.py",
        "pcl/parser_agent_output.py",
        "pcl/contracts/agent_output.py",
        "pcl/contracts/schemas/agent-output-policy-v1.schema.json",
        "pcl/contracts/schemas/agent-output-classification-v1.schema.json",
        "pcl/templates/agent-output-budget/GLOBAL_FRAGMENT.md",
        "pcl/templates/agent-output-budget/SKILL.md",
        "pcl/templates/agent-output-budget/policy.json",
    }
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
    with tarfile.open(sdist, "r:gz") as archive:
        sdist_names = set(archive.getnames())
        archive.extractall(tmp_path / "sdist", filter="data")
    assert all(any(name.endswith(path) for name in wheel_names) for path in required)
    assert all(any(name.endswith(f"src/{path}") for name in sdist_names) for path in required)

    installed = tmp_path / "wheel-installed"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(installed), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    extracted_root = next(path for path in (tmp_path / "sdist").iterdir() if path.is_dir())
    source_path = str(ROOT / "src")
    wheel_path = str(installed)
    sdist_path = str(extracted_root / "src")
    project_root = tmp_path / "project"
    project_root.mkdir()
    commands = (
        ("agent-output", "policy", "--json"),
        (
            "agent-output",
            "classify",
            "--argv-json",
            '["npm","run","verify:full"]',
            "--json",
        ),
        ("agent-output", "render", "--host", "cockpit", "--json"),
    )

    source_results = [_run_cli(source_path, project_root, *command) for command in commands]
    wheel_results = [_run_cli(wheel_path, project_root, *command) for command in commands]
    sdist_results = [_run_cli(sdist_path, project_root, *command) for command in commands]
    assert source_results == wheel_results == sdist_results
