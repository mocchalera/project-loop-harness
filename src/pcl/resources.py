from __future__ import annotations

from importlib import resources
from pathlib import Path


PACKAGE = "pcl"


def read_text_resource(relative_path: str) -> str:
    ref = resources.files(PACKAGE).joinpath(relative_path)
    return ref.read_text(encoding="utf-8")


def copy_tree_resource(relative_dir: str, destination: Path, *, overwrite: bool = False) -> None:
    src = resources.files(PACKAGE).joinpath(relative_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        out = destination / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() and not overwrite:
            continue
        out.write_bytes(item.read_bytes())
