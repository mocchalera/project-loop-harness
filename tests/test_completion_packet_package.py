from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


PROJECT_ROOT = Path(__file__).parents[1]
SCHEMA_MEMBER = "pcl/contracts/schemas/completion-packet-v1.schema.json"


def test_wheel_installs_with_readable_completion_packet_schema(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheel = next(wheel_dir.glob("*.whl"))

    with zipfile.ZipFile(wheel) as archive:
        assert SCHEMA_MEMBER in archive.namelist()

    site_dir = tmp_path / "site"
    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(site_dir),
            str(wheel),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    env = dict(os.environ)
    env["PYTHONPATH"] = str(site_dir)
    smoke = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from pcl.contracts import completion_packet_schema; "
                "print(json.dumps(completion_packet_schema(), sort_keys=True))"
            ),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    schema = json.loads(smoke.stdout)
    assert schema["properties"]["contract_version"]["const"] == "completion-packet/v1"
