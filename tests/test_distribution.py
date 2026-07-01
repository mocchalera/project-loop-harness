from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str | Path], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command],
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


def _scripts_dir(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts" if sys.platform == "win32" else "bin")


def _script(venv_dir: Path, name: str) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return _scripts_dir(venv_dir) / f"{name}{suffix}"


def _json_output(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def test_wheel_install_smoke_runs_cli_mcp_and_bundled_templates(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _run([
        sys.executable,
        "-m",
        "pip",
        "wheel",
        str(ROOT),
        "--no-deps",
        "--no-build-isolation",
        "-w",
        wheelhouse,
    ])
    wheels = sorted(wheelhouse.glob("project_loop_harness-*.whl"))
    assert len(wheels) == 1

    venv_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = _script(venv_dir, "python")
    pcl = _script(venv_dir, "pcl")
    pcl_mcp = _script(venv_dir, "pcl-mcp")

    _run([python, "-m", "pip", "install", "--no-deps", wheels[0]])

    assert "Project Loop Harness CLI" in _run([pcl, "--help"]).stdout
    assert "Project Loop Harness MCP server" in _run([pcl_mcp, "--help"]).stdout

    target = tmp_path / "target-project"
    init = _json_output(_run([pcl, "--json", "init", "--target", target]))
    assert init["created"] is True
    assert (target / "pcl.yaml").exists()
    assert (target / ".project-loop" / "workflows" / "feature_coverage.yaml").exists()
    assert (target / ".project-loop" / "workflows" / "executor_smoke.yaml").exists()
    assert (target / ".agents" / "skills" / "project-control-loop" / "SKILL.md").exists()

    assert _json_output(_run([pcl, "--root", target, "--json", "doctor"]))["ok"] is True
    assert _json_output(_run([pcl, "--root", target, "--json", "validate", "--strict"]))["ok"] is True

    render = _json_output(_run([pcl, "--root", target, "--json", "render"]))
    assert render["ok"] is True
    assert Path(render["path"]).exists()
    assert Path(render["data_path"]).exists()

    next_action = _json_output(_run([pcl, "--root", target, "--json", "next"]))
    assert next_action["type"] == "create_goal"


def test_reusable_github_action_contract_is_documented_and_wired() -> None:
    action = (ROOT / ".github" / "actions" / "project-loop-validate" / "action.yml").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / ".github" / "workflows" / "project-loop-validate.yml").read_text(
        encoding="utf-8"
    )

    assert "using: composite" in action
    for expected in ["root:", "strict:", "render:", "install-command:"]:
        assert expected in action
    assert "pcl validate --strict" in action
    assert "pcl validate" in action
    assert "pcl render" in action
    assert "python -m pip install project-loop-harness" in action

    assert "uses: ./.github/actions/project-loop-validate" in workflow
    assert "python -m pip install -e '.[dev]'" in workflow
    assert "hashFiles('.project-loop/project.db')" in workflow
