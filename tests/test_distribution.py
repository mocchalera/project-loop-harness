from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import venv
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str | Path], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command],
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


def _wheel_runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return env


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
    with zipfile.ZipFile(wheels[0]) as wheel:
        assert any(name.endswith("pcl/db/migrations/008_event_outbox.sql") for name in wheel.namelist())

    venv_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = _script(venv_dir, "python")
    pcl = _script(venv_dir, "pcl")
    pcl_mcp = _script(venv_dir, "pcl-mcp")

    wheel_env = _wheel_runtime_env()
    _run([python, "-m", "pip", "install", "--no-deps", wheels[0]], env=wheel_env)

    assert "Project Loop Harness CLI" in _run([pcl, "--help"], env=wheel_env).stdout
    assert "Project Loop Harness MCP server" in _run([pcl_mcp, "--help"], env=wheel_env).stdout
    update_command = _json_output(_run([pcl, "--json", "update", "command"], env=wheel_env))
    assert update_command["ok"] is True
    assert update_command["install"]["command"]

    target = tmp_path / "target-project"
    init = _json_output(_run([pcl, "--json", "init", "--target", target], env=wheel_env))
    assert init["created"] is True
    assert (target / "pcl.yaml").exists()
    assert (target / ".project-loop" / "workflows" / "feature_coverage.yaml").exists()
    assert (target / ".project-loop" / "workflows" / "executor_smoke.yaml").exists()
    installed_skill = target / ".agents" / "skills" / "project-control-loop" / "SKILL.md"
    canonical_skill = ROOT / "skills" / "project-control-loop" / "SKILL.md"
    assert installed_skill.read_bytes() == canonical_skill.read_bytes()

    migration_status = _json_output(
        _run([pcl, "--root", target, "--json", "migrate", "status"], env=wheel_env)
    )
    assert migration_status["current_schema_version"] == 8
    assert migration_status["applied_versions"] == list(range(1, 9))

    assert _json_output(_run([pcl, "--root", target, "--json", "doctor"], env=wheel_env))["ok"] is True
    assert _json_output(_run([pcl, "--root", target, "--json", "validate", "--strict"], env=wheel_env))["ok"] is True

    render = _json_output(_run([pcl, "--root", target, "--json", "render"], env=wheel_env))
    assert render["ok"] is True
    assert Path(render["path"]).exists()
    assert Path(render["data_path"]).exists()

    next_action = _json_output(_run([pcl, "--root", target, "--json", "next"], env=wheel_env))
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


def test_sdist_manifest_and_ci_include_doc_contract_smoke() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    ci_workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    publish_workflow = (ROOT / ".github" / "workflows" / "publish-pypi.yml").read_text(
        encoding="utf-8"
    )
    verifier = (ROOT / "scripts" / "verify_sdist_contracts.py").read_text(encoding="utf-8")

    for expected in [
        "recursive-include docs *.md",
        "recursive-include agent-tasks *.md",
        "recursive-include tests *.py *.json",
    ]:
        assert expected in manifest
    assert '"docs"' in verifier
    assert '"agent-adapter-contract.md"' in verifier
    assert "tests/test_agent_adapter_contract.py::test_agent_adapter_docs_match_contract" in verifier
    assert "python scripts/verify_sdist_contracts.py --dist-dir release-dist" in ci_workflow
    assert "python scripts/verify_sdist_contracts.py --dist-dir release-dist" in publish_workflow
