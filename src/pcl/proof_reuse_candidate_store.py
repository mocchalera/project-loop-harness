from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Mapping

from .contracts.proof_reuse_candidate import (
    MAX_CANDIDATE_BYTES,
    canonical_proof_reuse_candidate_bytes,
    validate_proof_reuse_candidate,
)
from .paths import ProjectPaths
from .strict_evidence import (
    StrictDirectoryWrite,
    StrictFileWrite,
    strict_create_canonical_directory,
    strict_inspect_canonical_directory,
    strict_list_canonical_directory,
    strict_publish_written_directory,
    strict_read_canonical_file,
    strict_remove_written_directory,
    strict_write_new_canonical_file,
)
from .test_faults import crash_if_requested


CANDIDATE_STORAGE_NAME = "proof-reuse-candidates"
CANDIDATE_FILE_NAME = "candidate.json"
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class PublishedProofReuseCandidate:
    directory: StrictDirectoryWrite
    file_receipt: StrictFileWrite
    relative_candidate_path: str
    storage_root_created: bool


@dataclass(frozen=True)
class ProofReuseCandidateArtifactAssessment:
    status: str
    candidate: Mapping[str, Any] | None
    observed_sha256: str | None
    observed_size_bytes: int | None
    finding_codes: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return self.status == "healthy"


def candidate_storage_root(paths: ProjectPaths) -> Path:
    return paths.evidence_dir / CANDIDATE_STORAGE_NAME


def candidate_directory(paths: ProjectPaths, candidate_id: str) -> Path:
    return candidate_storage_root(paths) / _candidate_hex(candidate_id)


def publish_proof_reuse_candidate(
    paths: ProjectPaths,
    *,
    candidate_id: str,
    content: bytes,
) -> PublishedProofReuseCandidate:
    if not isinstance(content, bytes):
        raise TypeError("Proof-reuse candidate content must be bytes.")
    if not 1 <= len(content) <= MAX_CANDIDATE_BYTES:
        raise ValueError("Proof-reuse candidate capacity exceeded.")
    try:
        parsed = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Proof-reuse candidate is not canonical JSON.") from exc
    if (
        not validate_proof_reuse_candidate(parsed).ok
        or parsed.get("candidate_id") != candidate_id
        or canonical_proof_reuse_candidate_bytes(parsed) != content
    ):
        raise ValueError("Proof-reuse candidate contract is invalid.")

    storage, storage_created = _ensure_storage_root(paths)
    candidate_hex = _candidate_hex(candidate_id)
    staging = strict_create_canonical_directory(
        storage.path / f".{candidate_hex}.staging-{secrets.token_hex(16)}",
        expected_parent=storage.path,
    )
    crash_if_requested("proof_reuse_candidate_after_staging_directory")
    write: StrictFileWrite | None = None
    published: StrictDirectoryWrite | None = None
    try:
        write = strict_write_new_canonical_file(
            staging.path / CANDIDATE_FILE_NAME,
            expected_parent=staging.path,
            content=content,
        )
        crash_if_requested("proof_reuse_candidate_after_staging_file")
        staging = strict_inspect_canonical_directory(
            staging.path,
            expected_parent=storage.path,
        )
        published = strict_publish_written_directory(
            staging,
            final_path=storage.path / candidate_hex,
        )
        crash_if_requested("proof_reuse_candidate_after_publish")
        if strict_list_canonical_directory(published) != (CANDIDATE_FILE_NAME,):
            raise OSError("Published proof-reuse candidate entries changed.")
        return PublishedProofReuseCandidate(
            directory=published,
            file_receipt=write,
            relative_candidate_path=(
                published.path.relative_to(paths.root) / CANDIDATE_FILE_NAME
            ).as_posix(),
            storage_root_created=storage_created,
        )
    except BaseException:
        cleanup = published
        if cleanup is None:
            try:
                cleanup = strict_inspect_canonical_directory(
                    staging.path,
                    expected_parent=storage.path,
                )
            except OSError:
                cleanup = None
        if cleanup is not None:
            strict_remove_written_directory(
                cleanup,
                file_receipts=() if write is None else (write,),
            )
        if storage_created:
            _remove_empty_storage_root(paths)
        raise


def remove_published_proof_reuse_candidate(
    publication: PublishedProofReuseCandidate,
) -> bool:
    removed = strict_remove_written_directory(
        publication.directory,
        file_receipts=(publication.file_receipt,),
    )
    if removed and publication.storage_root_created:
        _remove_empty_storage_root_from_path(publication.directory.expected_parent)
    return removed


def assess_proof_reuse_candidate_artifact(
    paths: ProjectPaths,
    *,
    candidate_id: str,
    expected_sha256: str,
    expected_size_bytes: int,
) -> ProofReuseCandidateArtifactAssessment:
    findings: set[str] = set()
    directory_path = candidate_directory(paths, candidate_id)
    _assess_exact_metadata(
        candidate_storage_root(paths),
        expected_kind="directory",
        expected_mode=0o700,
        findings=findings,
    )
    _assess_exact_metadata(
        directory_path,
        expected_kind="directory",
        expected_mode=0o700,
        findings=findings,
    )
    receipt: StrictDirectoryWrite | None = None
    try:
        receipt = strict_inspect_canonical_directory(
            directory_path,
            expected_parent=candidate_storage_root(paths),
        )
        entries = strict_list_canonical_directory(receipt)
    except OSError:
        entries = ()
        findings.add("reuse_candidate_directory_invalid")
    if entries != (CANDIDATE_FILE_NAME,):
        findings.add("reuse_candidate_unexpected_entry")

    candidate: Mapping[str, Any] | None = None
    observed_sha: str | None = None
    observed_size: int | None = None
    read = strict_read_canonical_file(
        directory_path / CANDIDATE_FILE_NAME,
        expected_parent=directory_path,
        expected_size=expected_size_bytes,
    )
    _assess_exact_metadata(
        directory_path / CANDIDATE_FILE_NAME,
        expected_kind="file",
        expected_mode=0o600,
        findings=findings,
    )
    if not read.ok or read.content is None:
        findings.add(f"reuse_candidate_file_{read.status}")
    else:
        observed_size = len(read.content)
        observed_sha = "sha256:" + hashlib.sha256(read.content).hexdigest()
        if observed_size != expected_size_bytes:
            findings.add("reuse_candidate_file_size_mismatch")
        if observed_sha != expected_sha256:
            findings.add("reuse_candidate_file_hash_mismatch")
        try:
            parsed = json.loads(read.content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            findings.add("reuse_candidate_file_invalid")
        else:
            if (
                not validate_proof_reuse_candidate(parsed).ok
                or parsed.get("candidate_id") != candidate_id
                or canonical_proof_reuse_candidate_bytes(parsed) != read.content
            ):
                findings.add("reuse_candidate_file_invalid")
            else:
                candidate = parsed
    if receipt is not None:
        try:
            final = strict_inspect_canonical_directory(
                directory_path,
                expected_parent=candidate_storage_root(paths),
            )
        except OSError:
            findings.add("reuse_candidate_directory_changed")
        else:
            if final.directory_identity != receipt.directory_identity:
                findings.add("reuse_candidate_directory_changed")
    return ProofReuseCandidateArtifactAssessment(
        status="healthy" if not findings else "postcommit_unhealthy",
        candidate=candidate,
        observed_sha256=observed_sha,
        observed_size_bytes=observed_size,
        finding_codes=tuple(sorted(findings)),
    )


def _assess_exact_metadata(
    path: Path,
    *,
    expected_kind: str,
    expected_mode: int,
    findings: set[str],
) -> None:
    finding_prefix = f"reuse_candidate_{expected_kind}"
    try:
        observed = os.lstat(path)
    except OSError:
        findings.add(f"{finding_prefix}_metadata_unavailable")
        return
    expected_type = stat.S_ISDIR if expected_kind == "directory" else stat.S_ISREG
    if not expected_type(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        findings.add(f"{finding_prefix}_type_invalid")
    if stat.S_IMODE(observed.st_mode) != expected_mode:
        findings.add(f"{finding_prefix}_mode_invalid")
    if observed.st_uid != _expected_owner():
        findings.add(f"{finding_prefix}_owner_invalid")
    if expected_kind == "file" and observed.st_nlink != 1:
        findings.add("reuse_candidate_file_nlink_invalid")


def _expected_owner() -> int:
    return os.getuid()


def platform_supported() -> bool:
    import os
    import sys

    return os.name == "posix" and sys.platform != "win32"


def _ensure_storage_root(paths: ProjectPaths) -> tuple[StrictDirectoryWrite, bool]:
    strict_inspect_canonical_directory(
        paths.evidence_dir,
        expected_parent=paths.loop_dir,
    )
    root = candidate_storage_root(paths)
    try:
        return (
            strict_inspect_canonical_directory(
                root,
                expected_parent=paths.evidence_dir,
            ),
            False,
        )
    except FileNotFoundError:
        return (
            strict_create_canonical_directory(
                root,
                expected_parent=paths.evidence_dir,
            ),
            True,
        )


def _remove_empty_storage_root(paths: ProjectPaths) -> bool:
    return _remove_empty_storage_root_from_path(candidate_storage_root(paths))


def _remove_empty_storage_root_from_path(root: Path) -> bool:
    try:
        receipt = strict_inspect_canonical_directory(
            root,
            expected_parent=root.parent,
        )
    except OSError:
        return False
    return strict_remove_written_directory(receipt)


def _candidate_hex(candidate_id: str) -> str:
    if (
        not isinstance(candidate_id, str)
        or not candidate_id.startswith("PRC-")
        or len(candidate_id) != 68
    ):
        raise ValueError("Proof-reuse candidate id is invalid.")
    value = candidate_id[4:].lower()
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise ValueError("Proof-reuse candidate id is invalid.")
    return value


__all__ = [
    "CANDIDATE_FILE_NAME",
    "CANDIDATE_STORAGE_NAME",
    "ProofReuseCandidateArtifactAssessment",
    "PublishedProofReuseCandidate",
    "assess_proof_reuse_candidate_artifact",
    "candidate_directory",
    "candidate_storage_root",
    "platform_supported",
    "publish_proof_reuse_candidate",
    "remove_published_proof_reuse_candidate",
]
