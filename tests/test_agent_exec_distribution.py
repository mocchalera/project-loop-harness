from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.version_info[:2] != (3, 12), reason="single CI packaging lane")
def test_agent_exec_contract_and_cli_ship_in_wheel_and_sdist(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--sdist",
            "--outdir",
            str(dist_dir),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(dist_dir.glob("*.whl"))
    sdist = next(dist_dir.glob("*.tar.gz"))
    required_suffixes = {
        "pcl/agent_exec.py",
        "pcl/agent_exec_validation.py",
        "pcl/path_safety.py",
        "pcl/sensitive.py",
        "pcl/agent_exec_handlers.py",
        "pcl/parser_agent_exec.py",
        "pcl/contracts/agent_exec_result.py",
        "pcl/contracts/schemas/agent-exec-result-v1.schema.json",
    }

    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
    for suffix in required_suffixes:
        assert any(name.endswith(suffix) for name in wheel_names), suffix

    with tarfile.open(sdist, "r:gz") as archive:
        sdist_names = set(archive.getnames())
        archive.extractall(tmp_path / "sdist", filter="data")
    for suffix in required_suffixes:
        assert any(name.endswith(f"src/{suffix}") for name in sdist_names), suffix

    installed = tmp_path / "installed"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(installed), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(installed)
    env["PCL_AGENT_EXEC_STATE_DIR"] = str(tmp_path / "wheel-state")
    python_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pcl",
            "--json",
            "exec",
            "--",
            sys.executable,
            "-c",
            "for i in range(1000): print(i)",
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(python_result.stdout)
    assert payload["schema"] == "agent-exec-result/v1"
    assert payload["status"] == "PASS"
    assert payload["raw"]["stdout_bytes"] > payload["exposed"]["bytes"]

    extracted_root = next(path for path in (tmp_path / "sdist").iterdir() if path.is_dir())
    sdist_env = os.environ.copy()
    sdist_env["PYTHONPATH"] = str(extracted_root / "src")
    sdist_env["PCL_AGENT_EXEC_STATE_DIR"] = str(tmp_path / "sdist-state")
    sdist_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pcl",
            "--json",
            "exec",
            "--",
            sys.executable,
            "-c",
            "print('sdist-pass')",
        ],
        cwd=tmp_path,
        env=sdist_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(sdist_result.stdout)["status"] == "PASS"

    node = shutil.which("node")
    if node is not None:
        node_root = tmp_path / "node-project"
        node_root.mkdir()
        (node_root / "package.json").write_text(
            '{"name":"agent-exec-smoke","private":true}', encoding="utf-8"
        )
        node_env = env.copy()
        node_env["PCL_AGENT_EXEC_STATE_DIR"] = str(tmp_path / "node-state")
        node_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pcl",
                "--json",
                "exec",
                "--",
                node,
                "-e",
                "for (let i = 0; i < 1000; i++) console.log(i)",
            ],
            cwd=node_root,
            env=node_env,
            check=True,
            capture_output=True,
            text=True,
        )
        node_payload = json.loads(node_result.stdout)
        assert node_payload["status"] == "PASS"
        assert node_payload["raw"]["stdout_bytes"] > node_payload["exposed"]["bytes"]
