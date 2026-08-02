from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Mapping

from .contracts.proof_anchor import (
    MAX_FINAL_DIRECTORY_BYTES,
    PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION,
    canonical_proof_anchor_bytes,
    finalize_proof_anchor_health,
    manifest_file_sha256,
    validate_proof_admission_anchor,
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


ANCHOR_STORAGE_NAME = "proof-admission-anchors"
MANIFEST_STORAGE_NAME = "evidence-manifest.json"
_FIXED_FILE_ORDER = (
    "basis.json",
    "independent-review.json",
    "human-gate.json",
    MANIFEST_STORAGE_NAME,
)
_REQUEST_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class PublishedProofAnchor:
    directory: StrictDirectoryWrite
    file_receipts: tuple[StrictFileWrite, ...]
    relative_manifest_path: str
    storage_root_created: bool


@dataclass(frozen=True)
class ProofAnchorArtifactAssessment:
    status: str
    manifest: Mapping[str, object] | None
    member_documents: Mapping[str, Mapping[str, object]]
    health: Mapping[str, object]

    @property
    def healthy(self) -> bool:
        return self.status == "healthy"


def anchor_storage_root(paths: ProjectPaths) -> Path:
    return paths.evidence_dir / ANCHOR_STORAGE_NAME


def anchor_directory(paths: ProjectPaths, request_id: str) -> Path:
    request_hex = _request_hex(request_id)
    return anchor_storage_root(paths) / request_hex


def publish_proof_anchor_artifact(
    paths: ProjectPaths,
    *,
    request_id: str,
    files: Mapping[str, bytes],
) -> PublishedProofAnchor:
    expected = {"basis.json", "independent-review.json", MANIFEST_STORAGE_NAME}
    if "human-gate.json" in files:
        expected.add("human-gate.json")
    if set(files) != expected:
        raise ValueError("Proof anchor files do not match the fixed member set.")
    if any(not isinstance(content, bytes) for content in files.values()):
        raise TypeError("Proof anchor files must be bytes.")
    if sum(len(content) for content in files.values()) > MAX_FINAL_DIRECTORY_BYTES:
        raise ValueError("Proof anchor directory capacity exceeded.")

    storage, storage_created = _ensure_storage_root(paths)
    request_hex = _request_hex(request_id)
    staging_name = f".{request_hex}.staging-{secrets.token_hex(16)}"
    staging = strict_create_canonical_directory(
        storage.path / staging_name,
        expected_parent=storage.path,
    )
    crash_if_requested("proof_anchor_after_staging_directory")
    writes: list[StrictFileWrite] = []
    published: StrictDirectoryWrite | None = None
    try:
        for name in _FIXED_FILE_ORDER:
            content = files.get(name)
            if content is None:
                continue
            writes.append(
                strict_write_new_canonical_file(
                    staging.path / name,
                    expected_parent=staging.path,
                    content=content,
                )
            )
        crash_if_requested("proof_anchor_after_staging_files")
        staging = strict_inspect_canonical_directory(
            staging.path,
            expected_parent=storage.path,
        )
        published = strict_publish_written_directory(
            staging,
            final_path=storage.path / request_hex,
        )
        crash_if_requested("proof_anchor_after_publish")
        expected_names = tuple(name for name in _FIXED_FILE_ORDER if name in files)
        actual_names = strict_list_canonical_directory(published)
        if (
            set(actual_names) != set(expected_names)
            or len({name.casefold() for name in actual_names}) != len(actual_names)
        ):
            raise OSError("Published proof anchor entries changed.")
        return PublishedProofAnchor(
            directory=published,
            file_receipts=tuple(writes),
            relative_manifest_path=(
                published.path.relative_to(paths.root) / MANIFEST_STORAGE_NAME
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
            strict_remove_written_directory(cleanup, file_receipts=tuple(writes))
        if storage_created:
            _remove_empty_storage_root(paths)
        raise


def remove_published_proof_anchor(publication: PublishedProofAnchor) -> bool:
    removed = strict_remove_written_directory(
        publication.directory,
        file_receipts=publication.file_receipts,
    )
    if removed and publication.storage_root_created:
        _remove_empty_storage_root_from_path(publication.directory.expected_parent)
    return removed


def assess_proof_anchor_artifact(
    paths: ProjectPaths,
    *,
    request_id: str,
    predecessor_event_id: str,
    anchor_generation: int,
    expected_anchor_sha256: str,
    expected_manifest_file_sha256: str,
    expected_manifest_size: int | None = None,
    expected_members: tuple[Mapping[str, object], ...] = (),
) -> ProofAnchorArtifactAssessment:
    directory_path = anchor_directory(paths, request_id)
    observations: list[dict[str, object]] = []
    findings: set[str] = set()
    documents: dict[str, Mapping[str, object]] = {}
    manifest: Mapping[str, object] | None = None
    expected_files: dict[str, tuple[str, int | None, str | None]] = {
        MANIFEST_STORAGE_NAME: (
            "manifest",
            expected_manifest_size,
            expected_manifest_file_sha256,
        )
    }
    directory_receipt: StrictDirectoryWrite | None = None
    for member in expected_members:
        expected_files[str(member["storage_name"])] = (
            str(member["role"]),
            int(member["size_bytes"]),
            str(member["file_sha256"]),
        )
    try:
        directory_receipt = strict_inspect_canonical_directory(
            directory_path,
            expected_parent=anchor_storage_root(paths),
        )
        entries = strict_list_canonical_directory(directory_receipt)
    except OSError:
        entries = ()
        findings.add("proof_anchor_directory_invalid")

    manifest_bytes: bytes | None = None
    manifest_read = strict_read_canonical_file(
        directory_path / MANIFEST_STORAGE_NAME,
        expected_parent=directory_path,
    )
    manifest_status = _health_status(manifest_read.status)
    observed_manifest_sha = None
    observed_manifest_size = None
    if manifest_read.ok and manifest_read.content is not None:
        manifest_bytes = manifest_read.content
        observed_manifest_size = len(manifest_bytes)
        observed_manifest_sha = manifest_file_sha256(manifest_bytes)
        if observed_manifest_sha != expected_manifest_file_sha256:
            manifest_status = "hash_mismatch"
        else:
            try:
                parsed = json.loads(manifest_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError):
                manifest_status = "changed"
            else:
                validation = validate_proof_admission_anchor(parsed)
                if (
                    not validation.ok
                    or parsed.get("contract_version")
                    != PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION
                    or parsed.get("anchor_sha256") != expected_anchor_sha256
                    or canonical_proof_anchor_bytes(parsed) + b"\n" != manifest_bytes
                ):
                    manifest_status = "changed"
                else:
                    manifest = parsed
                    for member in parsed["members"]:
                        expected_files[str(member["storage_name"])] = (
                            str(member["role"]),
                            int(member["size_bytes"]),
                            str(member["file_sha256"]),
                        )
    observations.append(
        _observation(
            role="manifest",
            storage_name=MANIFEST_STORAGE_NAME,
            status=manifest_status,
            expected_size=expected_manifest_size,
            observed_size=observed_manifest_size,
            expected_sha=expected_manifest_file_sha256,
            observed_sha=observed_manifest_sha,
        )
    )
    if manifest_status != "ok":
        findings.add(f"proof_anchor_manifest_{manifest_status}")

    for name in _FIXED_FILE_ORDER[:-1]:
        expected = expected_files.get(name)
        if expected is None:
            continue
        role, expected_size, expected_sha = expected
        read = strict_read_canonical_file(
            directory_path / name,
            expected_parent=directory_path,
            expected_size=expected_size,
        )
        status = _health_status(read.status)
        observed_size = None
        observed_sha = None
        if read.ok and read.content is not None:
            observed_size = len(read.content)
            observed_sha = "sha256:" + hashlib.sha256(read.content).hexdigest()
            if observed_sha != expected_sha:
                status = "hash_mismatch"
            else:
                try:
                    parsed = json.loads(read.content)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    status = "changed"
                else:
                    if canonical_proof_anchor_bytes(parsed) + b"\n" != read.content:
                        status = "changed"
                    else:
                        documents[role] = parsed
        observations.append(
            _observation(
                role=role,
                storage_name=name,
                status=status,
                expected_size=expected_size,
                observed_size=observed_size,
                expected_sha=expected_sha,
                observed_sha=observed_sha,
            )
        )
        if status != "ok":
            findings.add(f"proof_anchor_{role}_{status}")

    if set(entries) != set(expected_files):
        findings.add("proof_anchor_unexpected_entry")
    if directory_receipt is not None:
        try:
            final_directory_receipt = strict_inspect_canonical_directory(
                directory_path,
                expected_parent=anchor_storage_root(paths),
            )
        except OSError:
            findings.add("proof_anchor_directory_changed")
        else:
            if (
                final_directory_receipt.directory_identity
                != directory_receipt.directory_identity
            ):
                findings.add("proof_anchor_directory_changed")
    health = finalize_proof_anchor_health(
        {
            "contract_version": "proof-admission-anchor-health/v1",
            "predecessor": {
                "request_id": request_id,
                "anchor_generation": anchor_generation,
                "event_id": predecessor_event_id,
                "anchor_sha256": expected_anchor_sha256,
                "manifest_file_sha256": expected_manifest_file_sha256,
            },
            "authority_components": {
                "evidence_row": "matched",
                "evidence_link": "matched",
                "event": "matched",
                "outbox": "matched",
            },
            "artifact_observations": observations[:4],
            "finding_codes": sorted(findings)[:16],
            "health_sha256": "sha256:" + "0" * 64,
        }
    )
    return ProofAnchorArtifactAssessment(
        status="healthy" if not findings else "postcommit_unhealthy",
        manifest=manifest,
        member_documents=documents,
        health=health,
    )


def _ensure_storage_root(paths: ProjectPaths) -> tuple[StrictDirectoryWrite, bool]:
    strict_inspect_canonical_directory(
        paths.evidence_dir,
        expected_parent=paths.loop_dir,
    )
    root = anchor_storage_root(paths)
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
    return _remove_empty_storage_root_from_path(anchor_storage_root(paths))


def _remove_empty_storage_root_from_path(root: Path) -> bool:
    try:
        receipt = strict_inspect_canonical_directory(
            root,
            expected_parent=root.parent,
        )
    except OSError:
        return False
    return strict_remove_written_directory(receipt)


def _request_hex(request_id: str) -> str:
    if (
        not isinstance(request_id, str)
        or not request_id.startswith("PA-")
        or len(request_id) != 67
        or any(character.lower() not in _REQUEST_HEX for character in request_id[3:])
    ):
        raise ValueError("Invalid proof anchor request ID.")
    return request_id[3:].lower()


def _observation(
    *,
    role: str,
    storage_name: str,
    status: str,
    expected_size: int | None,
    observed_size: int | None,
    expected_sha: str | None,
    observed_sha: str | None,
) -> dict[str, object]:
    return {
        "role": role,
        "storage_name": storage_name,
        "status": status,
        "expected_size_bytes": expected_size,
        "observed_size_bytes": observed_size,
        "expected_file_sha256": expected_sha,
        "observed_file_sha256": observed_sha,
    }


def _health_status(status: str) -> str:
    return {
        "directory_missing": "missing",
        "directory_symlink": "symlink",
        "directory_not_directory": "not_regular",
        "directory_redirected": "redirected",
        "size_mismatch": "size_mismatch",
        "hash_mismatch": "hash_mismatch",
        "missing": "missing",
        "not_regular": "not_regular",
        "symlink": "symlink",
        "changed": "changed",
        "ok": "ok",
    }.get(status, "changed")


def platform_supported() -> bool:
    return os.name == "posix"


__all__ = [
    "ANCHOR_STORAGE_NAME",
    "MANIFEST_STORAGE_NAME",
    "ProofAnchorArtifactAssessment",
    "PublishedProofAnchor",
    "anchor_directory",
    "anchor_storage_root",
    "assess_proof_anchor_artifact",
    "platform_supported",
    "publish_proof_anchor_artifact",
    "remove_published_proof_anchor",
]
