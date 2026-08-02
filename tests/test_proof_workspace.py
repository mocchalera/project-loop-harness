from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile

import pytest

import pcl.proof_workspace as proof_workspace_module
from pcl.authority_surface import canonical_git_diff, resolve_authority_surface
from pcl.contracts.authority_surface import (
    AUTHORITY_CANARY_CONTRACT_VERSION,
    AUTHORITY_CATALOG_CONTRACT_VERSION,
    authority_document_sha256,
    load_bootstrap_authority_profile,
)
from pcl.contracts.proof_workspace import (
    PROOF_WORKSPACE_BINDING_CONTRACT_VERSION,
    PROOF_WORKSPACE_SPEC_CONTRACT_VERSION,
    VERIFICATION_PROFILE_CONTRACT_VERSION,
    proof_document_sha256,
    proof_workspace_binding_schema,
    proof_workspace_spec_schema,
    validate_proof_workspace_binding,
    validate_proof_workspace_spec,
    validate_verification_profile,
    verification_profile_schema,
)
from pcl.proof_workspace import (
    ProofWorkspaceError,
    _Lease,
    directory_bundle_manifest,
    prepare_proof_workspace,
)
from pcl.git_runtime import GitRunner


BOOTSTRAP_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "authority_surface"
    / "bootstrap-authority-profile-v0.json"
)
SHA256_EMPTY = "sha256:" + hashlib.sha256(b"").hexdigest()


def _git(root: Path, *args: str) -> str:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("GIT_")
    }
    return subprocess.check_output(
        ["git", *args],
        cwd=root,
        env=environment,
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def _commit(root: Path, path: str, content: str, *, executable: bool = False) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if executable:
        target.chmod(0o755)
    _git(root, "add", path)
    _git(root, "commit", "-q", "-m", f"write {path}")
    return _git(root, "rev-parse", "HEAD")


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "source"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    base = _commit(root, "README.md", "base\n")
    candidate = _commit(root, "src/candidate_only.py", "VALUE = 'candidate'\n")
    return root, base, candidate


def _empty_catalog(catalog_id: str) -> dict:
    return {
        "contract_version": AUTHORITY_CATALOG_CONTRACT_VERSION,
        "catalog_id": catalog_id,
        "rules": [],
    }


def _empty_canary() -> dict:
    return {"contract_version": AUTHORITY_CANARY_CONTRACT_VERSION, "items": []}


def _base(base: str, candidate: str, *, status: str = "resolved") -> dict:
    if status == "base_unknown":
        return {
            "status": "base_unknown",
            "derivation": "base_unknown",
            "commit_oid": None,
            "source_ref": None,
            "ancestry_result": "unknown",
            "reuse_allowed": False,
            "reason_codes": ["trusted_integration_head_missing"],
        }
    if status == "no_candidate_change":
        return {
            "status": "no_candidate_change",
            "derivation": "task_start_event",
            "commit_oid": candidate,
            "source_ref": "EV-START",
            "ancestry_result": "same_as_candidate",
            "reuse_allowed": False,
            "reason_codes": ["no_candidate_change"],
        }
    return {
        "status": "resolved",
        "derivation": "task_start_event",
        "commit_oid": base,
        "source_ref": "EV-START",
        "ancestry_result": "ancestor",
        "reuse_allowed": True,
        "reason_codes": ["task_start_ancestor"],
    }


def _authority(
    root: Path,
    base: str,
    candidate: str,
    *,
    status: str = "resolved",
) -> tuple[dict, dict]:
    bootstrap = load_bootstrap_authority_profile(BOOTSTRAP_FIXTURE)
    tree = _git(root, "rev-parse", f"{candidate}^{{tree}}")
    git_runner = GitRunner(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "HOME": str(root),
            "LANG": "C",
            "PATH": os.defpath,
        }
    )
    diff = (
        canonical_git_diff(
            root,
            base_commit_oid=candidate,
            candidate_commit_oid=candidate,
            git_runner=git_runner,
        )
        if status == "no_candidate_change"
        else canonical_git_diff(
            root,
            base_commit_oid=base,
            candidate_commit_oid=candidate,
            git_runner=git_runner,
        )
    )
    resolution = resolve_authority_surface(
        target={"type": "task", "id": "T-0001"},
        candidate={"commit_oid": candidate, "tree_oid": tree},
        base_resolution=_base(base, candidate, status=status),
        actual_diff=diff,
        existing_route_risk="R0",
        existing_adaptive_depth="basic",
        trusted_base_floor="R0",
        reviewer_escalation={"risk_level": "R0", "verification_depth": "basic"},
        packaged_catalog=bootstrap["authority_catalog"],
        base_catalog=_empty_catalog("base"),
        candidate_catalog=_empty_catalog("candidate"),
        base_canary=_empty_canary(),
        candidate_canary=_empty_canary(),
        resolver={
            "version": "p1-c-c1",
            "sha256": "sha256:" + "a" * 64,
            "source": "external_bootstrap",
        },
        bootstrap_profile=bootstrap,
    )
    return resolution, bootstrap


def _profile(*, argv: list[str] | None = None, input_ids: list[str] | None = None) -> dict:
    return {
        "contract_version": VERIFICATION_PROFILE_CONTRACT_VERSION,
        "profile_id": "p1c-candidate-verification",
        "execution_policy": {
            "spawn_contract": "prepared-check/v1",
            "workspace_contract": "proof-workspace-isolation/v1",
            "shell": False,
            "os_sandbox": False,
            "network_sandbox": False,
            "supported_platforms": ["darwin", "linux"],
        },
        "checks": [
            {
                "check_id": "full-regression",
                "role": "full_regression",
                "argv": argv
                or [
                    sys.executable,
                    "-c",
                    "import candidate_only; print(candidate_only.VALUE)",
                ],
                "cwd": ".",
                "selectors": [],
                "referenced_git_blobs": [],
                "input_ids": sorted(input_ids or []),
                "environment": {
                    "inherit_names": ["LANG", "PATH"],
                    "workspace_pythonpath": ["src"],
                },
                "timeout_seconds": 30,
                "max_output_bytes": 65_536,
                "declared_outputs": [],
            }
        ],
        "terminal_authority": False,
        "mandatory_evidence": False,
    }


def _spec(
    resolution: dict,
    bootstrap: dict,
    profile: dict,
    *,
    external_inputs: list[dict] | None = None,
) -> dict:
    oid_length = len(resolution["candidate"]["commit_oid"])
    return {
        "contract_version": PROOF_WORKSPACE_SPEC_CONTRACT_VERSION,
        "target": dict(resolution["target"]),
        "candidate": {
            "object_format": "sha1" if oid_length == 40 else "sha256",
            **resolution["candidate"],
        },
        "authority_surface_resolution_sha256": authority_document_sha256(resolution),
        "bootstrap_profile_sha256": authority_document_sha256(bootstrap),
        "verification_profile_sha256": proof_document_sha256(profile),
        "isolation_contract_version": "proof-workspace-isolation/v1",
        "external_inputs": external_inputs or [],
        "terminal_authority": False,
        "mandatory_evidence": False,
    }


def _prepare(
    root: Path,
    base: str,
    candidate: str,
    temp_parent: Path,
    *,
    profile: dict | None = None,
    external_inputs: list[dict] | None = None,
    source_bindings: dict[str, Path] | None = None,
    status: str = "resolved",
    resolution_mutator=None,
    parent_environment: dict[str, str] | None = None,
):
    resolution, bootstrap = _authority(root, base, candidate, status=status)
    if resolution_mutator is not None:
        resolution_mutator(resolution)
    chosen_profile = profile or _profile(
        input_ids=[item["input_id"] for item in external_inputs or []]
    )
    spec = _spec(
        resolution,
        bootstrap,
        chosen_profile,
        external_inputs=external_inputs,
    )
    return prepare_proof_workspace(
        root,
        spec=spec,
        authority_resolution=resolution,
        bootstrap_profile=bootstrap,
        verification_profile=chosen_profile,
        source_bindings=source_bindings or {},
        parent_environment=parent_environment
        or {"LANG": "C", "PATH": os.environ.get("PATH", os.defpath)},
        temp_parent=temp_parent,
    )


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_contracts_are_strict_and_schema_resources_are_additive(
    tmp_path: Path,
) -> None:
    root, base, candidate = _repository(tmp_path)
    resolution, bootstrap = _authority(root, base, candidate)
    profile = _profile()
    spec = _spec(resolution, bootstrap, profile)

    assert validate_verification_profile(profile).ok
    assert validate_proof_workspace_spec(spec).ok
    assert verification_profile_schema()["$id"].endswith("verification-profile-v1.schema.json")
    assert proof_workspace_spec_schema()["$id"].endswith("proof-workspace-spec-v1.schema.json")
    assert proof_workspace_binding_schema()["$id"].endswith(
        "proof-workspace-binding-v1.schema.json"
    )

    profile["result"] = "passed"
    assert not validate_verification_profile(profile).ok
    spec["checks"] = []
    assert not validate_proof_workspace_spec(spec).ok


def test_exact_clone_excludes_host_dirt_and_uses_candidate_only_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, base, candidate = _repository(tmp_path)
    (root / "src/candidate_only.py").write_text("VALUE = 'host-dirty'\n", encoding="utf-8")
    (root / ".claude").mkdir()
    (root / ".claude/session.json").write_text("host-only\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules/host-only").write_text("host-only\n", encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "hostile-git-dir"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(tmp_path / "hostile-objects"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "hostile-index"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "hostile-config"))

    with _prepare(root, base, candidate, tmp_path) as prepared:
        assert prepared.root != root
        assert (prepared.root / "src/candidate_only.py").read_text() == "VALUE = 'candidate'\n"
        assert not (prepared.root / ".claude/session.json").exists()
        assert not (prepared.root / "node_modules").exists()
        assert prepared.binding["repository"]["detached"] is True
        assert prepared.binding["repository"]["origin_absent"] is True
        assert prepared.binding["repository"]["git_common_dir_distinct"] is True
        check = prepared.prepared_checks["full-regression"]
        assert str(root / "src") not in check.env.get("PYTHONPATH", "")
        assert not ({"GIT_DIR", "GIT_OBJECT_DIRECTORY", "GIT_INDEX_FILE"} & set(check.env))
        completed = subprocess.run(
            list(check.argv),
            cwd=check.cwd,
            env=dict(check.env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "candidate"


def test_pre_post_manifest_and_repository_tool_reseal_fail_closed(
    tmp_path: Path,
) -> None:
    root, base, _ = _repository(tmp_path)
    (root / ".gitignore").write_text("out/\n", encoding="utf-8")
    tool = root / "bin/candidate-tool"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\necho candidate\n", encoding="utf-8")
    tool.chmod(0o755)
    _git(root, "add", ".gitignore", "bin/candidate-tool")
    _git(root, "commit", "-q", "-m", "tool and outputs")
    candidate = _git(root, "rev-parse", "HEAD")
    profile = _profile(argv=["bin/candidate-tool"])
    profile["checks"][0]["declared_outputs"] = ["out/**"]

    with _prepare(root, base, candidate, tmp_path, profile=profile) as prepared:
        before = prepared.capture_before("full-regression")
        output = prepared.root / "out/result.txt"
        output.parent.mkdir()
        output.write_text("result\n", encoding="utf-8")
        reseal = prepared.reseal_after("full-regression", before_manifest=before)
        assert reseal["effect"]["classification"] == "declared_outputs"

        (prepared.root / "bin/candidate-tool").write_text("#!/bin/sh\necho changed\n")
        with pytest.raises(ProofWorkspaceError) as tool_changed:
            prepared.assert_ready_to_spawn("full-regression")
        assert tool_changed.value.code == "proof_git_tree_materialization_mismatch"

    with _prepare(root, base, candidate, tmp_path, profile=profile) as prepared:
        _git(prepared.root, "remote", "add", "origin", str(root))
        with pytest.raises(ProofWorkspaceError) as remote_changed:
            prepared.assert_ready_to_spawn("full-regression")
        assert remote_changed.value.code == "proof_git_remote_present"

    with _prepare(root, base, candidate, tmp_path, profile=profile) as prepared:
        common = Path(
            _git(
                prepared.root,
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            )
        )
        alternates = common / "objects/info/alternates"
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_text(str(Path(_git(root, "rev-parse", "--git-common-dir")) / "objects"))
        with pytest.raises(ProofWorkspaceError) as alternates_changed:
            prepared.assert_ready_to_spawn("full-regression")
        assert alternates_changed.value.code == "proof_git_alternates_present"

    with _prepare(root, base, candidate, tmp_path, profile=profile) as prepared:
        _git(prepared.root, "config", "--local", "core.hooksPath", str(root / "hooks"))
        with pytest.raises(ProofWorkspaceError) as config_changed:
            prepared.assert_ready_to_spawn("full-regression")
        assert config_changed.value.code == "proof_git_configuration_unsafe"


def test_linked_worktree_resolves_common_store_and_produces_distinct_clone(
    tmp_path: Path,
) -> None:
    root, base, candidate = _repository(tmp_path)
    linked = tmp_path / "linked"
    _git(root, "worktree", "add", "--detach", str(linked), candidate)

    with _prepare(linked, base, candidate, tmp_path) as prepared:
        source_common = Path(_git(linked, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        clone_common = Path(
            _git(prepared.root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        )
        assert source_common.resolve() != clone_common.resolve()
        assert prepared.binding["repository"]["candidate"]["commit_oid"] == candidate


def test_tracked_mode_symlink_and_gitlink_are_verified_and_resealed(tmp_path: Path) -> None:
    root, base, _ = _repository(tmp_path)
    executable = root / "bin/check"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    os.symlink("README.md", root / "README.link")
    nested = tmp_path / "nested-source"
    nested.mkdir()
    _git(nested, "init", "-q")
    _git(nested, "config", "user.email", "test@example.com")
    _git(nested, "config", "user.name", "Test")
    nested_commit = _commit(nested, "nested.txt", "nested\n")
    _git(root, "add", "bin/check", "README.link")
    _git(root, "update-index", "--add", "--cacheinfo", f"160000,{nested_commit},vendor/sub")
    _git(root, "commit", "-q", "-m", "tree kinds")
    candidate = _git(root, "rev-parse", "HEAD")

    with _prepare(root, base, candidate, tmp_path) as prepared:
        assert (prepared.root / "bin/check").stat().st_mode & stat.S_IXUSR
        assert (prepared.root / "README.link").is_symlink()
        executable_copy = prepared.root / "bin/check"
        executable_copy.chmod(0o644)
        with pytest.raises(ProofWorkspaceError) as exc_info:
            prepared.assert_ready_to_spawn("full-regression")
        assert exc_info.value.code == "proof_git_tree_materialization_mismatch"


def test_declared_submodule_binds_gitlink_commit_tree_and_distinct_clone(
    tmp_path: Path,
) -> None:
    root, base, _ = _repository(tmp_path)
    nested = tmp_path / "submodule-source"
    nested.mkdir()
    _git(nested, "init", "-q")
    _git(nested, "config", "user.email", "test@example.com")
    _git(nested, "config", "user.name", "Test")
    nested_commit = _commit(nested, "module.py", "VALUE = 1\n")
    nested_tree = _git(nested, "rev-parse", f"{nested_commit}^{{tree}}")
    _git(root, "update-index", "--add", "--cacheinfo", f"160000,{nested_commit},vendor/sub")
    _git(root, "commit", "-q", "-m", "gitlink")
    candidate = _git(root, "rev-parse", "HEAD")
    declaration = {
        "input_id": "submodule",
        "type": "submodule",
        "destination": "vendor/sub",
        "consumer_check_ids": ["full-regression"],
        "gitlink_oid": nested_commit,
        "commit_oid": nested_commit,
        "tree_oid": nested_tree,
        "object_format": "sha1",
        "on_unavailable": "block",
    }

    with _prepare(
        root,
        base,
        candidate,
        tmp_path,
        external_inputs=[declaration],
        source_bindings={"submodule": nested},
    ) as prepared:
        submodule = prepared.root / "vendor/sub"
        assert _git(submodule, "rev-parse", "HEAD") == nested_commit
        assert _git(submodule, "remote") == ""
        assert prepared.binding["external_inputs"]["entries"][0]["tree_oid"] == nested_tree


def test_lfs_material_requires_pointer_and_supplied_bytes_to_agree(tmp_path: Path) -> None:
    root, base, _ = _repository(tmp_path)
    material = tmp_path / "asset.bin"
    material.write_bytes(b"materialized-lfs\n")
    material_sha = _sha(material)
    pointer = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid {material_sha}\n"
        f"size {material.stat().st_size}\n"
    )
    candidate = _commit(root, "assets/model.bin", pointer)
    pointer_blob = _git(root, "rev-parse", f"{candidate}:assets/model.bin")
    declaration = {
        "input_id": "lfs",
        "type": "materialized_file",
        "material_kind": "git_lfs",
        "destination": "assets/model.bin",
        "consumer_check_ids": ["full-regression"],
        "pointer_blob_oid": pointer_blob,
        "lfs_oid_sha256": material_sha,
        "lfs_size": material.stat().st_size,
        "sha256": material_sha,
        "size": material.stat().st_size,
        "mode": "0644",
        "on_unavailable": "block",
    }

    with _prepare(
        root,
        base,
        candidate,
        tmp_path,
        external_inputs=[declaration],
        source_bindings={"lfs": material},
    ) as prepared:
        assert (prepared.root / "assets/model.bin").read_bytes() == material.read_bytes()
        prepared.assert_ready_to_spawn("full-regression")


@pytest.mark.parametrize("status", ["base_unknown", "no_candidate_change"])
def test_nonresolved_base_states_are_monotonic_fresh_only(
    tmp_path: Path,
    status: str,
) -> None:
    root, base, candidate = _repository(tmp_path)
    if status == "no_candidate_change":
        base = candidate

    with _prepare(root, base, candidate, tmp_path, status=status) as prepared:
        reuse = prepared.binding["reuse"]
        assert reuse["disposition"] == "fresh_only"
        assert reuse["r2_reuse_eligible"] is False
        assert reuse["reuse_authorized"] is False
        assert f"proof_authority_{status}" in reuse["reason_codes"]
        assert "proof_authority_reuse_forbidden" in reuse["reason_codes"]


def test_no_candidate_change_requires_base_oid_to_equal_candidate_oid(
    tmp_path: Path,
) -> None:
    root, _, base = _repository(tmp_path)
    _git(root, "commit", "--allow-empty", "-q", "-m", "same tree, distinct commit")
    candidate = _git(root, "rev-parse", "HEAD")

    def mismatch_base(resolution: dict) -> None:
        resolution["base"]["commit_oid"] = base

    with pytest.raises(ProofWorkspaceError) as exc_info:
        with _prepare(
            root,
            base,
            candidate,
            tmp_path,
            status="no_candidate_change",
            resolution_mutator=mismatch_base,
        ):
            pass
    assert exc_info.value.code == "proof_authority_diff_mismatch"


def test_literal_false_authority_reuse_is_never_inferred_from_risk(tmp_path: Path) -> None:
    root, base, candidate = _repository(tmp_path)

    def forbid(resolution: dict) -> None:
        resolution["effective"]["reuse_allowed"] = False

    with _prepare(
        root,
        base,
        candidate,
        tmp_path,
        resolution_mutator=forbid,
    ) as prepared:
        assert prepared.binding["reuse"]["authority_effective"]["risk_level"] == "R2"
        assert prepared.binding["reuse"]["r2_reuse_eligible"] is False
        assert "proof_authority_reuse_forbidden" in prepared.binding["reuse"]["reason_codes"]


def test_resolved_authority_diff_is_recomputed_in_the_sealed_clone(tmp_path: Path) -> None:
    root, base, candidate = _repository(tmp_path)

    def trim_diff(resolution: dict) -> None:
        resolution["actual_diff"] = {
            "sha256": "sha256:" + hashlib.sha256(b"[]").hexdigest(),
            "entries": [],
        }

    with pytest.raises(ProofWorkspaceError) as exc_info:
        with _prepare(
            root,
            base,
            candidate,
            tmp_path,
            resolution_mutator=trim_diff,
        ):
            pass
    assert exc_info.value.code == "proof_authority_diff_mismatch"


def test_unreachable_candidate_and_ref_race_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, base, candidate = _repository(tmp_path)
    original_branch = _git(root, "symbolic-ref", "--short", "HEAD")
    _git(root, "checkout", "-q", "--detach", base)
    _git(root, "branch", "-D", original_branch)
    with pytest.raises(ProofWorkspaceError) as unreachable:
        with _prepare(root, base, candidate, tmp_path):
            pass
    assert unreachable.value.code == "proof_candidate_not_reachable"

    _git(root, "branch", "candidate-ref", candidate)
    original_clone = proof_workspace_module._clone_exact_repository

    def race_clone(*args, **kwargs):
        _git(root, "branch", "-D", "candidate-ref")
        return original_clone(*args, **kwargs)

    monkeypatch.setattr(proof_workspace_module, "_clone_exact_repository", race_clone)
    with pytest.raises(ProofWorkspaceError) as raced:
        with _prepare(root, base, candidate, tmp_path):
            pass
    assert raced.value.code == "proof_candidate_object_unavailable"


def test_regular_file_directory_bundle_and_generated_material_are_bound(
    tmp_path: Path,
) -> None:
    root, base, candidate = _repository(tmp_path)
    file_source = tmp_path / "tool.bin"
    file_source.write_bytes(b"tool\n")
    bundle_source = tmp_path / "bundle"
    (bundle_source / "empty").mkdir(parents=True)
    (bundle_source / "data.txt").write_text("bundle\n", encoding="utf-8")
    os.symlink("data.txt", bundle_source / "link")
    generated_source = tmp_path / "generated.txt"
    generated_source.write_text("generated\n", encoding="utf-8")
    bundle = directory_bundle_manifest(bundle_source)
    symlink_entry = next(entry for entry in bundle["entries"] if entry["kind"] == "symlink")
    assert "target" not in symlink_entry
    assert symlink_entry["target_sha256"].startswith("sha256:")
    inputs = [
        {
            "input_id": "tool",
            "type": "file",
            "destination": "inputs/tool.bin",
            "consumer_check_ids": ["full-regression"],
            "sha256": _sha(file_source),
            "size": file_source.stat().st_size,
            "mode": "0644",
            "on_unavailable": "block",
        },
        {
            "input_id": "bundle",
            "type": "directory_bundle",
            "destination": "inputs/bundle",
            "consumer_check_ids": ["full-regression"],
            "bundle_sha256": bundle["sha256"],
            "on_unavailable": "block",
        },
        {
            "input_id": "generated",
            "type": "materialized_file",
            "material_kind": "generated",
            "destination": "generated/output.txt",
            "consumer_check_ids": ["full-regression"],
            "sha256": _sha(generated_source),
            "size": generated_source.stat().st_size,
            "mode": "0644",
            "base_expectation": {"kind": "absent"},
            "on_unavailable": "block",
        },
    ]

    with _prepare(
        root,
        base,
        candidate,
        tmp_path,
        external_inputs=inputs,
        source_bindings={
            "tool": file_source,
            "bundle": bundle_source,
            "generated": generated_source,
        },
    ) as prepared:
        assert (prepared.root / "inputs/tool.bin").read_bytes() == b"tool\n"
        assert (prepared.root / "inputs/bundle/empty").is_dir()
        assert os.readlink(prepared.root / "inputs/bundle/link") == "data.txt"
        assert (prepared.root / "generated/output.txt").read_text() == "generated\n"
        assert validate_proof_workspace_binding(prepared.binding).ok
        assert prepared.binding["contract_version"] == PROOF_WORKSPACE_BINDING_CONTRACT_VERSION


def test_source_and_destination_toctou_changes_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, base, candidate = _repository(tmp_path)
    source = tmp_path / "source-input"
    source.write_bytes(b"stable")
    declaration = {
        "input_id": "input",
        "type": "file",
        "destination": "inputs/value",
        "consumer_check_ids": ["full-regression"],
        "sha256": _sha(source),
        "size": source.stat().st_size,
        "mode": "0644",
        "on_unavailable": "block",
    }
    original_write = proof_workspace_module._write_created_file

    def racing_write(destination: Path, contents: bytes, mode: str) -> None:
        original_write(destination, contents, mode)
        source.write_bytes(b"changed")

    monkeypatch.setattr(proof_workspace_module, "_write_created_file", racing_write)
    with pytest.raises(ProofWorkspaceError) as raced:
        with _prepare(
            root,
            base,
            candidate,
            tmp_path,
            external_inputs=[declaration],
            source_bindings={"input": source},
        ):
            pass
    assert raced.value.code == "proof_external_input_changed_during_materialization"

    monkeypatch.setattr(proof_workspace_module, "_write_created_file", original_write)
    source.write_bytes(b"stable")
    with _prepare(
        root,
        base,
        candidate,
        tmp_path,
        external_inputs=[declaration],
        source_bindings={"input": source},
    ) as prepared:
        (prepared.root / "inputs/value").write_bytes(b"changed")
        with pytest.raises(ProofWorkspaceError) as destination_changed:
            prepared.assert_ready_to_spawn("full-regression")
        assert destination_changed.value.code == "proof_external_input_changed_during_materialization"


def test_directory_source_toctou_change_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, base, candidate = _repository(tmp_path)
    source = tmp_path / "bundle-race"
    source.mkdir()
    (source / "value").write_text("stable", encoding="utf-8")
    bundle = directory_bundle_manifest(source)
    declaration = {
        "input_id": "bundle",
        "type": "directory_bundle",
        "destination": "inputs/bundle",
        "consumer_check_ids": ["full-regression"],
        "bundle_sha256": bundle["sha256"],
        "on_unavailable": "block",
    }
    original_write = proof_workspace_module._write_directory_bundle

    def racing_write(destination: Path, entries) -> None:
        original_write(destination, entries)
        (source / "added").write_text("race", encoding="utf-8")

    monkeypatch.setattr(proof_workspace_module, "_write_directory_bundle", racing_write)
    with pytest.raises(ProofWorkspaceError) as raced:
        with _prepare(
            root,
            base,
            candidate,
            tmp_path,
            external_inputs=[declaration],
            source_bindings={"bundle": source},
        ):
            pass
    assert raced.value.code == "proof_external_input_changed_during_materialization"


def test_opaque_and_unavailable_inputs_are_fresh_only_or_blocked_by_spec(
    tmp_path: Path,
) -> None:
    root, base, candidate = _repository(tmp_path)
    opaque = {
        "input_id": "service",
        "type": "opaque",
        "consumer_check_ids": ["full-regression"],
        "on_unavailable": "fresh_only",
    }
    missing = {
        "input_id": "missing",
        "type": "file",
        "destination": "inputs/missing",
        "consumer_check_ids": ["full-regression"],
        "sha256": SHA256_EMPTY,
        "size": 0,
        "mode": "0644",
        "on_unavailable": "fresh_only",
    }
    with _prepare(
        root,
        base,
        candidate,
        tmp_path,
        external_inputs=[opaque, missing],
    ) as prepared:
        assert prepared.binding["reuse"]["disposition"] == "fresh_only"
        assert prepared.binding["reuse"]["reuse_authorized"] is False
        assert {
            "proof_external_input_missing",
            "proof_external_input_unknown",
        }.issubset(prepared.binding["reuse"]["reason_codes"])

    missing["on_unavailable"] = "block"
    with pytest.raises(ProofWorkspaceError) as exc_info:
        with _prepare(
            root,
            base,
            candidate,
            tmp_path,
            external_inputs=[missing],
        ):
            pass
    assert exc_info.value.code == "proof_external_input_missing"


def test_unreadable_input_obeys_fresh_only_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, base, candidate = _repository(tmp_path)
    source = tmp_path / "unreadable"
    source.write_bytes(b"declared")
    declaration = {
        "input_id": "unreadable",
        "type": "file",
        "destination": "inputs/unreadable",
        "consumer_check_ids": ["full-regression"],
        "sha256": _sha(source),
        "size": source.stat().st_size,
        "mode": "0644",
        "on_unavailable": "fresh_only",
    }
    original_read = proof_workspace_module._read_regular_file

    def unreadable_read(path: Path, *, require_single_link: bool):
        if path == source:
            raise ProofWorkspaceError(
                message="unreadable",
                code="proof_external_input_unreadable",
            )
        return original_read(path, require_single_link=require_single_link)

    monkeypatch.setattr(proof_workspace_module, "_read_regular_file", unreadable_read)
    with _prepare(
        root,
        base,
        candidate,
        tmp_path,
        external_inputs=[declaration],
        source_bindings={"unreadable": source},
    ) as prepared:
        assert prepared.binding["reuse"]["disposition"] == "fresh_only"
        assert "proof_external_input_unreadable" in prepared.binding["reuse"]["reason_codes"]


@pytest.mark.parametrize("unsafe_kind", ["fifo", "socket", "hardlink", "escape", "nested_git"])
def test_directory_bundle_rejects_unsafe_filesystem_inputs(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    short_socket_root = None
    if unsafe_kind == "socket":
        short_socket_root = tempfile.TemporaryDirectory(prefix="pws-sock-", dir="/tmp")
        source = Path(short_socket_root.name)
    else:
        source = tmp_path / unsafe_kind
        source.mkdir()
    if unsafe_kind == "fifo":
        os.mkfifo(source / "entry")
    elif unsafe_kind == "socket":
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(source / "entry"))
    elif unsafe_kind == "hardlink":
        (source / "entry").write_text("x", encoding="utf-8")
        os.link(source / "entry", source / "entry-2")
    elif unsafe_kind == "escape":
        os.symlink("../outside", source / "entry")
    else:
        (source / ".git").mkdir()
    try:
        with pytest.raises(ProofWorkspaceError):
            directory_bundle_manifest(source)
    finally:
        if unsafe_kind == "socket":
            sock.close()
            short_socket_root.cleanup()


@pytest.mark.parametrize(
    "destination",
    [
        ".git/config",
        ".project-loop/project.db",
        "pkg/.git/config",
        "pkg/.git/hooks/pre-commit",
        "pkg/.project-loop/project.db",
        "pkg/deep/.project-loop/state",
    ],
)
def test_protected_destinations_fail_closed(tmp_path: Path, destination: str) -> None:
    root, base, candidate = _repository(tmp_path)
    source = tmp_path / "input"
    source.write_bytes(b"x")
    declaration = {
        "input_id": "input",
        "type": "file",
        "destination": destination,
        "consumer_check_ids": ["full-regression"],
        "sha256": _sha(source),
        "size": 1,
        "mode": "0644",
        "on_unavailable": "block",
    }
    with pytest.raises(ProofWorkspaceError) as exc_info:
        with _prepare(
            root,
            base,
            candidate,
            tmp_path,
            external_inputs=[declaration],
            source_bindings={"input": source},
        ):
            pass
    assert exc_info.value.code == "proof_external_destination_conflict"


def test_file_symlink_device_collision_and_integrity_mismatch_fail_closed(
    tmp_path: Path,
) -> None:
    root, base, candidate = _repository(tmp_path)
    regular = tmp_path / "regular"
    regular.write_bytes(b"regular")
    symlink = tmp_path / "symlink"
    symlink.symlink_to(regular)
    base_declaration = {
        "input_id": "input",
        "type": "file",
        "destination": "inputs/value",
        "consumer_check_ids": ["full-regression"],
        "sha256": _sha(regular),
        "size": regular.stat().st_size,
        "mode": "0644",
        "on_unavailable": "block",
    }
    for unsafe_source in (symlink, Path("/dev/null")):
        with pytest.raises(ProofWorkspaceError) as unsafe:
            with _prepare(
                root,
                base,
                candidate,
                tmp_path,
                external_inputs=[base_declaration],
                source_bindings={"input": unsafe_source},
            ):
                pass
        assert unsafe.value.code == "proof_external_input_unsafe"

    mismatched = dict(base_declaration)
    mismatched["sha256"] = SHA256_EMPTY
    with pytest.raises(ProofWorkspaceError) as integrity:
        with _prepare(
            root,
            base,
            candidate,
            tmp_path,
            external_inputs=[mismatched],
            source_bindings={"input": regular},
        ):
            pass
    assert integrity.value.code == "proof_external_input_digest_mismatch"

    second = dict(base_declaration)
    second["input_id"] = "second"
    second["destination"] = "Inputs/value"
    with pytest.raises(ProofWorkspaceError) as collision:
        with _prepare(
            root,
            candidate,
            candidate,
            tmp_path,
            status="no_candidate_change",
            external_inputs=[base_declaration, second],
            source_bindings={"input": regular, "second": regular},
        ):
            pass
    assert collision.value.code == "proof_external_destination_conflict"


def test_secret_environment_digest_is_not_public_and_forces_fresh_only(
    tmp_path: Path,
) -> None:
    root, base, candidate = _repository(tmp_path)
    profile = _profile()
    profile["checks"][0]["environment"]["inherit_names"].append("API_TOKEN")
    profile["checks"][0]["environment"]["inherit_names"].sort()

    with _prepare(
        root,
        base,
        candidate,
        tmp_path,
        profile=profile,
        parent_environment={
            "API_TOKEN": "not-serialized",
            "LANG": "C",
            "PATH": os.environ.get("PATH", os.defpath),
        },
    ) as prepared:
        public = prepared.binding["checks"][0]
        check = prepared.prepared_checks["full-regression"]
        assert check.env["API_TOKEN"] == "not-serialized"
        assert public["spawn_vector_sha256"] is None
        assert public["environment"]["secret_derived_digest_recorded"] is False
        assert "not-serialized" not in json.dumps(prepared.binding)
        assert prepared.binding["reuse"]["disposition"] == "fresh_only"


def test_complete_environment_does_not_merge_undeclared_host_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, base, candidate = _repository(tmp_path)
    monkeypatch.setenv("UNDECLARED_HOST_VALUE", "must-not-leak")
    with _prepare(
        root,
        base,
        candidate,
        tmp_path,
        parent_environment={"LANG": "C", "PATH": os.environ.get("PATH", os.defpath)},
    ) as prepared:
        check = prepared.prepared_checks["full-regression"]
        assert "UNDECLARED_HOST_VALUE" not in check.env
        assert "must-not-leak" not in json.dumps(prepared.binding)


@pytest.mark.parametrize(
    "forbidden_name",
    [
        "BASH_ENV",
        "DYLD_INSERT_LIBRARIES",
        "PYTHONHOME",
        "LD_AUDIT",
        "LD_BIND_NOW",
        "LD_PROFILE",
    ],
)
def test_loader_and_shell_startup_environment_is_blocked(
    tmp_path: Path,
    forbidden_name: str,
) -> None:
    root, base, candidate = _repository(tmp_path)
    profile = _profile()
    profile["checks"][0]["environment"]["inherit_names"].append(forbidden_name)
    profile["checks"][0]["environment"]["inherit_names"].sort()
    with pytest.raises(ProofWorkspaceError) as exc_info:
        with _prepare(
            root,
            base,
            candidate,
            tmp_path,
            profile=profile,
            parent_environment={
                forbidden_name: "hostile",
                "LANG": "C",
                "PATH": os.environ.get("PATH", os.defpath),
            },
        ):
            pass
    assert exc_info.value.code == "proof_environment_injection_forbidden"

    with _prepare(
        root,
        base,
        candidate,
        tmp_path,
        parent_environment={
            forbidden_name: "hostile",
            "LANG": "C",
            "PATH": os.environ.get("PATH", os.defpath),
        },
    ) as prepared:
        check = prepared.prepared_checks["full-regression"]
        environment_binding = prepared.binding["checks"][0]["environment"]
        assert forbidden_name not in check.env
        assert forbidden_name not in environment_binding["inherited_names"]


def test_proof_key_and_logical_spawn_identity_are_stable_across_temp_roots(
    tmp_path: Path,
) -> None:
    root, base, candidate = _repository(tmp_path)
    parent_a = tmp_path / "a"
    parent_b = tmp_path / "b"
    parent_a.mkdir()
    parent_b.mkdir()
    with _prepare(root, base, candidate, parent_a) as first:
        first_key = first.binding["proof_key"]["sha256"]
        first_spawn = first.binding["checks"][0]["spawn_vector_sha256"]
        first_root = first.root
        first_manifest = first.capture_before("full-regression")
        assert any(
            token == "$HOST_TOOL:full-regression"
            for _, token in first.prepared_checks["full-regression"]._token_map
        )
        with _prepare(root, base, candidate, parent_b) as second:
            assert second.root != first_root
            assert second.binding["proof_key"]["sha256"] == first_key
            assert second.binding["checks"][0]["spawn_vector_sha256"] == first_spawn
            second_manifest = second.capture_before("full-regression")
            assert second_manifest["manifest_sha256"] != first_manifest["manifest_sha256"]


def test_concurrent_preparations_share_identity_but_not_mutable_workspace(
    tmp_path: Path,
) -> None:
    root, base, candidate = _repository(tmp_path)

    def prepare_once(index: int) -> tuple[str, str]:
        parent = tmp_path / f"worker-{index}"
        parent.mkdir()
        with _prepare(root, base, candidate, parent) as prepared:
            return str(prepared.root), prepared.binding["proof_key"]["sha256"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(prepare_once, range(2)))
    assert results[0][0] != results[1][0]
    assert results[0][1] == results[1][1]


def test_check_plan_change_invalidates_shared_proof_key(tmp_path: Path) -> None:
    root, base, candidate = _repository(tmp_path)
    first_profile = _profile()
    second_profile = _profile()
    second_profile["checks"][0]["argv"].append("ignored-argument")
    with _prepare(root, base, candidate, tmp_path, profile=first_profile) as first:
        first_key = first.binding["proof_key"]["sha256"]
    with _prepare(root, base, candidate, tmp_path, profile=second_profile) as second:
        assert second.binding["proof_key"]["sha256"] != first_key


def test_success_cleanup_failure_retention_and_identity_refusal(tmp_path: Path) -> None:
    root, base, candidate = _repository(tmp_path)
    with _prepare(root, base, candidate, tmp_path) as prepared:
        successful_lease = prepared.lease_root
        assert successful_lease.exists()
    assert not successful_lease.exists()

    with pytest.raises(RuntimeError):
        with _prepare(root, base, candidate, tmp_path) as prepared:
            retained = prepared.lease_root
            raise RuntimeError("retain")
    assert retained.exists()

    with pytest.raises(ProofWorkspaceError) as exc_info:
        with _prepare(root, base, candidate, tmp_path) as prepared:
            original = prepared.lease_root
            moved = original.with_name(original.name + "-moved")
            original.rename(moved)
            original.mkdir()
    assert exc_info.value.code == "proof_cleanup_identity_changed"
    assert moved.exists()
    assert original.exists()

    with pytest.raises(ProofWorkspaceError) as marker_refusal:
        with _prepare(root, base, candidate, tmp_path) as prepared:
            marker = prepared.lease_root / ".pcl-proof-workspace-lease"
            nonce = marker.read_bytes()
            marker.unlink()
            marker.write_bytes(nonce)
    assert marker_refusal.value.code == "proof_cleanup_identity_changed"


def test_caught_invalid_state_retains_workspace_on_normal_context_exit(
    tmp_path: Path,
) -> None:
    root, base, candidate = _repository(tmp_path)
    with _prepare(root, base, candidate, tmp_path) as prepared:
        retained = prepared.lease_root
        prepared.binding["state"] = "tampered"
        with pytest.raises(ProofWorkspaceError) as exc_info:
            prepared.assert_ready_to_spawn("full-regression")
        assert exc_info.value.code == "proof_workspace_binding_invalid"
        assert prepared.state == "invalid"
    assert retained.exists()
    assert prepared.state == "retained_failure"


def test_cleanup_refuses_name_replacement_after_descriptor_walk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = _Lease.create(tmp_path)
    moved = lease.root.with_name(lease.root.name + "-moved-during-cleanup")
    replacement = lease.root.with_name(lease.root.name + "-replacement")
    replacement.mkdir()
    sentinel = replacement / "must-survive"
    sentinel.write_text("outside identity", encoding="utf-8")
    original_remove = proof_workspace_module._remove_directory_contents

    def replace_name_after_walk(root_fd: int) -> None:
        original_remove(root_fd)
        lease.root.rename(moved)
        replacement.rename(lease.root)

    monkeypatch.setattr(
        proof_workspace_module,
        "_remove_directory_contents",
        replace_name_after_walk,
    )
    with pytest.raises(ProofWorkspaceError) as exc_info:
        lease.cleanup_success()
    assert exc_info.value.code == "proof_cleanup_identity_changed"
    assert (lease.root / sentinel.name).read_text(encoding="utf-8") == "outside identity"
    assert moved.exists()


def test_tmp_alias_is_canonicalized_before_lease_identity() -> None:
    lease = _Lease.create(Path("/tmp"))
    try:
        assert lease.parent == Path("/tmp").resolve()
        assert lease.root.parent == Path("/tmp").resolve()
    finally:
        lease.cleanup_success()


def test_crash_lease_is_retained_and_never_swept_or_adopted(tmp_path: Path) -> None:
    output = tmp_path / "lease-path"
    code = (
        "import os, pathlib; "
        "from pcl.proof_workspace import _Lease; "
        f"lease=_Lease.create(pathlib.Path({str(tmp_path)!r})); "
        f"pathlib.Path({str(output)!r}).write_text(str(lease.root)); "
        "os._exit(0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        env={"PYTHONPATH": "src", "PATH": os.environ.get("PATH", os.defpath)},
        check=False,
    )
    assert completed.returncode == 0
    retained = Path(output.read_text(encoding="utf-8"))
    assert retained.exists()

    second = _Lease.create(tmp_path)
    try:
        assert retained.exists()
        assert second.root != retained
    finally:
        second.cleanup_success()


def test_c2_has_no_pcl_or_c3_effects(tmp_path: Path) -> None:
    root, base, candidate = _repository(tmp_path)
    loop = root / ".project-loop"
    loop.mkdir()
    db = loop / "project.db"
    events = loop / "events.jsonl"
    db.write_bytes(b"schema-8-sentinel")
    events.write_bytes(b"event-sentinel")
    before = {path: path.read_bytes() for path in (db, events)}

    with _prepare(root, base, candidate, tmp_path) as prepared:
        assert prepared.binding["reuse"]["reuse_authorized"] is False
        assert not ({"result", "artifact", "evidence", "event", "outbox"} & set(prepared.binding))

    assert {path: path.read_bytes() for path in (db, events)} == before


def test_c3_bridge_keeps_source_capability_private_and_retains_failure(
    tmp_path: Path,
) -> None:
    root, base, candidate = _repository(tmp_path)
    with _prepare(root, base, candidate, tmp_path) as prepared:
        public = json.dumps(prepared.binding, sort_keys=True)
        assert str(prepared._source_root) not in public
        assert str(prepared._source_common_dir) not in public
        assert str(prepared._source_object_dir) not in public
        assert prepared._source_root == root.resolve()
        assert prepared._source_object_format == "sha1"
        retained = prepared.lease_root
        prepared.retain_failure("failed")
        assert prepared.state == "retained_failure"
        assert prepared.reuse_disposition == "fresh_only"
    assert retained.exists()
