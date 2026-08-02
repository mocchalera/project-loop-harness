from __future__ import annotations

import os
from pathlib import Path

import pytest

from pcl.strict_evidence import (
    strict_create_canonical_directory,
    strict_inspect_canonical_directory,
    strict_publish_written_directory,
    strict_read_canonical_file,
    strict_remove_written_directory,
    strict_write_new_canonical_file,
)


def test_strict_directory_publish_is_exclusive_durable_and_exactly_removable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    storage = strict_create_canonical_directory(
        root / "proof-admission-anchors",
        expected_parent=root,
    )
    staging = strict_create_canonical_directory(
        storage.path / ".request.staging",
        expected_parent=storage.path,
    )
    write = strict_write_new_canonical_file(
        staging.path / "basis.json",
        expected_parent=staging.path,
        content=b"{}\n",
    )

    published = strict_publish_written_directory(
        staging,
        final_path=storage.path / "request",
    )

    assert published.path.name == "request"
    assert (published.path / "basis.json").read_bytes() == b"{}\n"
    assert stat_mode(published.path) == 0o700
    assert stat_mode(published.path / "basis.json") == 0o600
    assert strict_remove_written_directory(published, file_receipts=(write,))
    assert not published.path.exists()


def test_strict_directory_publish_rejects_final_collision_and_symlink_parent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    storage = strict_create_canonical_directory(root / "anchors", expected_parent=root)
    staging = strict_create_canonical_directory(
        storage.path / ".request.staging",
        expected_parent=storage.path,
    )
    (storage.path / "request").mkdir()
    with pytest.raises(FileExistsError):
        strict_publish_written_directory(staging, final_path=storage.path / "request")

    redirected = tmp_path / "redirected"
    redirected.symlink_to(storage.path, target_is_directory=True)
    with pytest.raises(OSError):
        strict_create_canonical_directory(
            redirected / "child",
            expected_parent=redirected,
        )


def test_strict_directory_cleanup_refuses_identity_change_or_nonempty_unknown_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    directory = strict_create_canonical_directory(root / "staging", expected_parent=root)
    (directory.path / "unknown").write_bytes(b"do not delete")
    assert not strict_remove_written_directory(directory)
    assert (directory.path / "unknown").read_bytes() == b"do not delete"

    owned_directory = strict_create_canonical_directory(
        root / "owned-staging",
        expected_parent=root,
    )
    owned = strict_write_new_canonical_file(
        owned_directory.path / "basis.json",
        expected_parent=owned_directory.path,
        content=b"{}\n",
    )
    (owned_directory.path / "unexpected").write_bytes(b"preserve all")
    owned_directory = strict_inspect_canonical_directory(
        owned_directory.path,
        expected_parent=root,
    )
    owned_bytes = (owned_directory.path / "basis.json").read_bytes()
    assert not strict_remove_written_directory(
        owned_directory,
        file_receipts=(owned,),
    )
    assert (owned_directory.path / "basis.json").read_bytes() == owned_bytes
    assert (owned_directory.path / "unexpected").read_bytes() == b"preserve all"


def test_strict_read_rejects_hardlink_and_directory_create_rejects_case_alias(
    tmp_path: Path,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    directory = strict_create_canonical_directory(root / "Anchor", expected_parent=root)
    with pytest.raises(OSError):
        strict_create_canonical_directory(root / "anchor", expected_parent=root)
    source = directory.path / "basis.json"
    source.write_bytes(b"{}\n")
    os.link(source, directory.path / "alias.json")
    assert strict_read_canonical_file(
        source,
        expected_parent=directory.path,
    ).status == "hardlink"


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode & 0o777
