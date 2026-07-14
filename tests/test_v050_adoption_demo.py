from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "v0.5.0-adoption-demo" / "run-demo.sh"


def _fake_python(path: Path, *, venv_ok: bool) -> None:
    venv_body = (
        'mkdir -p "$3/bin"\n'
        ': > "$3/bin/python"\n'
        'chmod +x "$3/bin/python"\n'
        "exit 0"
        if venv_ok
        else "exit 1"
    )
    path.write_text(
        "#!/bin/bash\n"
        'if [[ "$1" == "-c" ]]; then exit 0; fi\n'
        'if [[ "$1" == "-m" && "$2" == "venv" ]]; then\n'
        f"{venv_body}\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=SCRIPT.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_python_check_uses_explicit_interpreter(tmp_path: Path) -> None:
    python = tmp_path / "custom-python"
    _fake_python(python, venv_ok=True)
    env = {**os.environ, "TMPDIR": str(tmp_path)}

    result = _run("--python", str(python), "--check-python", env=env)

    assert result.returncode == 0, result.stderr
    assert f"VENV_CREATOR={python}" in result.stdout
    assert "PYTHON_CHECK_OK=1" in result.stdout
    assert not list(tmp_path.glob("pcl-v0.5.0-demo.*"))


def test_python_check_falls_back_after_broken_default(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_python(bin_dir / "python3", venv_ok=False)
    _fake_python(bin_dir / "python3.13", venv_ok=True)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "TMPDIR": str(tmp_path),
    }

    result = _run("--check-python", env=env)

    assert result.returncode == 0, result.stderr
    assert f"VENV_CREATOR={bin_dir / 'python3.13'}" in result.stdout
    assert "PYTHON_CHECK_OK=1" in result.stdout


def test_python_check_rejects_broken_explicit_interpreter(tmp_path: Path) -> None:
    python = tmp_path / "broken-python"
    _fake_python(python, venv_ok=False)
    env = {**os.environ, "TMPDIR": str(tmp_path)}

    result = _run("--python", str(python), "--check-python", env=env)

    assert result.returncode == 1
    assert "cannot create a venv or is older than 3.10" in result.stderr
    assert "--python COMMAND or PYTHON_BIN=COMMAND" in result.stderr
