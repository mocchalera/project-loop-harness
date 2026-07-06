from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
import venv
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify that the sdist is self-contained for doc/contract tests."
    )
    parser.add_argument("--dist-dir", type=Path, default=Path("release-dist"))
    args = parser.parse_args(argv)

    sdist = _single_sdist(args.dist_dir)
    with tempfile.TemporaryDirectory(prefix="pcl-sdist-contract-") as tmp:
        work = Path(tmp)
        extract_dir = work / "extract"
        extract_dir.mkdir()
        with tarfile.open(sdist, "r:gz") as archive:
            if sys.version_info >= (3, 12):
                archive.extractall(extract_dir, filter="data")
            else:
                archive.extractall(extract_dir)

        roots = [path for path in extract_dir.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise SystemExit(f"Expected one extracted sdist root, found {len(roots)}")
        source_root = roots[0]

        required_paths = [
            source_root / "docs" / "agent-adapter-contract.md",
            source_root / "docs" / "agent-output-template.md",
            source_root / "agent-tasks",
            source_root / "tests" / "test_agent_adapter_contract.py",
        ]
        missing = [str(path.relative_to(source_root)) for path in required_paths if not path.exists()]
        if missing:
            raise SystemExit(f"sdist is missing required contract files: {', '.join(missing)}")

        venv_dir = work / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python = _script(venv_dir, "python")
        _run([python, "-m", "pip", "install", "-e", ".[dev]"], cwd=source_root)
        _run(
            [
                python,
                "-m",
                "pytest",
                "tests/test_agent_adapter_contract.py::test_agent_adapter_docs_match_contract",
            ],
            cwd=source_root,
        )
    return 0


def _single_sdist(dist_dir: Path) -> Path:
    matches = sorted(dist_dir.glob("project_loop_harness-*.tar.gz"))
    if len(matches) != 1:
        raise SystemExit(f"Expected one project_loop_harness sdist in {dist_dir}, found {len(matches)}")
    return matches[0]


def _script(venv_dir: Path, name: str) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    directory = "Scripts" if sys.platform == "win32" else "bin"
    return venv_dir / directory / f"{name}{suffix}"


def _run(command: list[str | Path], *, cwd: Path) -> None:
    subprocess.run([str(part) for part in command], cwd=cwd, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
