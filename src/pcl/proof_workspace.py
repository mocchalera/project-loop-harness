from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import secrets
import shutil
import stat
import sys
import tempfile
from types import MappingProxyType
from typing import Any
import unicodedata

from .authority_surface import canonical_git_diff
from .contracts.authority_surface import (
    authority_document_sha256,
    validate_authority_surface_resolution,
    validate_bootstrap_authority_profile,
)
from .contracts.proof_workspace import (
    PROOF_WORKSPACE_BINDING_CONTRACT_VERSION,
    PROOF_WORKSPACE_ISOLATION_CONTRACT_VERSION,
    proof_document_sha256,
    validate_proof_workspace_binding,
    validate_proof_workspace_spec,
    validate_verification_profile,
)
from .errors import PclError
from .git_runtime import GitRunner
from .verification_manifest import (
    collect_verification_input_manifest,
    compare_verification_input_manifests,
)


_LEASE_MARKER = ".pcl-proof-workspace-lease"
_PROTECTED_DESTINATIONS = {".git", ".project-loop", ".proof-workspace"}
_SECRET_FRAGMENTS = (
    "API_KEY",
    "AUTH",
    "CREDENTIAL",
    "PASSWORD",
    "PASSWD",
    "PRIVATE_KEY",
    "SECRET",
    "TOKEN",
)
_FORBIDDEN_ENVIRONMENT_NAMES = {
    "BASH_ENV",
    "CDPATH",
    "ENV",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_WORK_TREE",
    "HOME",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "NODE_OPTIONS",
    "PERL5OPT",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "RUBYOPT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "VIRTUAL_ENV",
    "ZDOTDIR",
}
_GIT_UNSAFE_CONFIG_PREFIXES = (
    "credential.",
    "filter.",
    "http.",
    "include.",
    "remote.",
    "url.",
)
_GIT_UNSAFE_CONFIG_KEYS = {
    "core.alternaterefscommand",
    "core.gitproxy",
    "core.sshcommand",
    "extensions.partialclone",
}


class ProofWorkspaceError(PclError):
    pass


@dataclass(frozen=True)
class _StatIdentity:
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    changed_ns: int
    links: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> _StatIdentity:
        return cls(
            device=value.st_dev,
            inode=value.st_ino,
            mode=value.st_mode,
            size=value.st_size,
            modified_ns=value.st_mtime_ns,
            changed_ns=value.st_ctime_ns,
            links=value.st_nlink,
        )


@dataclass
class _Lease:
    parent: Path
    root: Path
    root_identity: _StatIdentity
    marker_identity: _StatIdentity
    nonce: str
    cleaned: bool = False

    @classmethod
    def create(cls, temp_parent: Path | None = None) -> _Lease:
        if os.name != "posix" or sys.platform not in {"darwin", "linux"}:
            raise _error(
                "proof_platform_capability_missing",
                "C2 proof workspaces require POSIX Linux or macOS.",
            )
        parent = Path(temp_parent or tempfile.gettempdir()).resolve()
        parent_stat = os.lstat(parent)
        if not stat.S_ISDIR(parent_stat.st_mode) or stat.S_ISLNK(parent_stat.st_mode):
            raise _error(
                "proof_platform_capability_missing",
                "The proof temp parent must be a real POSIX directory.",
                temp_parent=str(parent),
            )
        root = Path(tempfile.mkdtemp(prefix="pcl-proof-workspace-", dir=parent)).resolve()
        root_stat = os.lstat(root)
        nonce = secrets.token_hex(32)
        marker = root / _LEASE_MARKER
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(marker, flags, 0o600)
        try:
            os.write(descriptor, nonce.encode("ascii"))
            os.fsync(descriptor)
            marker_stat = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        return cls(
            parent=parent,
            root=root,
            root_identity=_StatIdentity.from_stat(root_stat),
            marker_identity=_StatIdentity.from_stat(marker_stat),
            nonce=nonce,
        )

    @property
    def marker(self) -> Path:
        return self.root / _LEASE_MARKER

    def assert_identity(self) -> None:
        if self.cleaned:
            raise _error(
                "proof_cleanup_identity_changed",
                "The proof lease was already cleaned.",
            )
        try:
            root_stat = os.lstat(self.root)
            marker_lstat = os.lstat(self.marker)
        except OSError as exc:
            raise _error(
                "proof_cleanup_identity_changed",
                "The proof lease path or marker is unavailable.",
                lease_root=str(self.root),
            ) from exc
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or stat.S_ISLNK(root_stat.st_mode)
            or root_stat.st_dev != self.root_identity.device
            or root_stat.st_ino != self.root_identity.inode
        ):
            raise _error(
                "proof_cleanup_identity_changed",
                "The proof lease root identity changed.",
                lease_root=str(self.root),
            )
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.marker, flags)
        except OSError as exc:
            raise _error(
                "proof_cleanup_identity_changed",
                "The proof lease marker could not be opened safely.",
                lease_root=str(self.root),
            ) from exc
        try:
            marker_stat = os.fstat(descriptor)
            marker_bytes = os.read(descriptor, 256)
        finally:
            os.close(descriptor)
        if (
            not stat.S_ISREG(marker_stat.st_mode)
            or marker_stat.st_nlink != 1
            or _StatIdentity.from_stat(marker_stat) != self.marker_identity
            or _StatIdentity.from_stat(marker_lstat) != self.marker_identity
            or marker_bytes != self.nonce.encode("ascii")
        ):
            raise _error(
                "proof_cleanup_identity_changed",
                "The proof lease marker identity changed.",
                lease_root=str(self.root),
            )

    def cleanup_success(self) -> None:
        if self.cleaned:
            return
        self.assert_identity()
        forbidden = {
            Path("/").resolve(),
            Path.home().resolve(),
            self.parent.resolve(),
        }
        if self.root in forbidden or self.root.parent != self.parent:
            raise _error(
                "proof_cleanup_identity_changed",
                "The proof lease cleanup target is unsafe.",
                lease_root=str(self.root),
            )
        parent_fd = _open_directory(self.parent)
        try:
            root_fd = _open_directory_at(parent_fd, self.root.name)
            try:
                opened_root = os.fstat(root_fd)
                if (
                    opened_root.st_dev != self.root_identity.device
                    or opened_root.st_ino != self.root_identity.inode
                ):
                    raise _error(
                        "proof_cleanup_identity_changed",
                        "The descriptor-bound proof lease identity changed.",
                        lease_root=str(self.root),
                    )
                _remove_directory_contents(root_fd)
            finally:
                os.close(root_fd)
            named_root = os.stat(self.root.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                named_root.st_dev != self.root_identity.device
                or named_root.st_ino != self.root_identity.inode
            ):
                raise _error(
                    "proof_cleanup_identity_changed",
                    "The proof lease name changed during descriptor-relative cleanup.",
                    lease_root=str(self.root),
                )
            os.rmdir(self.root.name, dir_fd=parent_fd)
        except ProofWorkspaceError:
            raise
        except OSError as exc:
            raise _error(
                "proof_cleanup_identity_changed",
                "Descriptor-relative proof lease cleanup was refused.",
                lease_root=str(self.root),
                error=f"{exc.__class__.__name__}: {exc}",
            ) from exc
        finally:
            os.close(parent_fd)
        self.cleaned = True


@dataclass(frozen=True)
class PreparedCheck:
    check_id: str
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    timeout_seconds: int
    max_output_bytes: int
    plan_sha256: str
    tool_identity: Mapping[str, Any]
    environment_binding: Mapping[str, Any]
    spawn_vector_sha256: str
    _tool_path: Path = field(repr=False, compare=False)
    _tool_identity_runtime: _StatIdentity = field(repr=False, compare=False)
    _token_map: tuple[tuple[str, str], ...] = field(repr=False, compare=False)
    _secret_names: tuple[str, ...] = field(repr=False, compare=False)


@dataclass
class _InputRuntime:
    input_id: str
    kind: str
    destination: Path | None
    expected: Mapping[str, Any]


@dataclass
class PreparedProofWorkspace:
    root: Path
    lease_root: Path
    binding: dict[str, Any]
    prepared_checks: Mapping[str, PreparedCheck]
    state: str
    reuse_disposition: str
    _lease: _Lease = field(repr=False)
    _git: GitRunner = field(repr=False)
    _candidate_commit: str = field(repr=False)
    _candidate_tree: str = field(repr=False)
    _object_format: str = field(repr=False)
    _tracked_replacement_paths: frozenset[str] = field(repr=False)
    _config_sha256: str = field(repr=False)
    _input_runtime: tuple[_InputRuntime, ...] = field(repr=False)
    _declared_outputs: Mapping[str, tuple[str, ...]] = field(repr=False)
    _binding_sha256: str = field(repr=False)

    def capture_before(self, check_id: str) -> dict[str, Any]:
        check = self._require_check(check_id)
        self.assert_ready_to_spawn(check_id)
        self.state = "yielded_to_executor"
        return collect_verification_input_manifest(
            self.root,
            declared_output_patterns=self._declared_outputs[check.check_id],
            git_runner=self._git,
        )

    def assert_ready_to_spawn(self, check_id: str) -> None:
        check = self._require_check(check_id)
        try:
            if proof_document_sha256(self.binding) != self._binding_sha256:
                raise _error(
                    "proof_workspace_binding_invalid",
                    "The public proof workspace binding changed after preparation.",
                )
            self._lease.assert_identity()
            _assert_repository_sealed(
                self.root,
                self._git,
                candidate_commit=self._candidate_commit,
                candidate_tree=self._candidate_tree,
                config_sha256=self._config_sha256,
                object_format=self._object_format,
                tracked_replacement_paths=self._tracked_replacement_paths,
            )
            _reseal_materialized_inputs(self._input_runtime, self._git)
            current_tool = _stat_identity_no_follow(check._tool_path)
            if current_tool != check._tool_identity_runtime:
                raise _error(
                    "proof_spawn_vector_mismatch",
                    "The prepared executable identity changed before spawn.",
                    check_id=check_id,
                )
            actual_spawn = _spawn_vector_sha256(
                check.argv,
                check.cwd,
                check.env,
                token_map=check._token_map,
            )
            if actual_spawn != check.spawn_vector_sha256:
                raise _error(
                    "proof_spawn_vector_mismatch",
                    "The frozen prepared-check spawn vector changed.",
                    check_id=check_id,
                )
        except ProofWorkspaceError:
            self.state = "invalid"
            self.reuse_disposition = "fresh_only"
            raise

    def reseal_after(
        self,
        check_id: str,
        *,
        before_manifest: Mapping[str, Any],
    ) -> dict[str, Any]:
        check = self._require_check(check_id)
        after = collect_verification_input_manifest(
            self.root,
            declared_output_patterns=self._declared_outputs[check.check_id],
            git_runner=self._git,
        )
        effect = compare_verification_input_manifests(
            dict(before_manifest),
            after,
        )
        self.assert_ready_to_spawn(check_id)
        self.state = "resealed"
        return {
            "contract_version": "proof-check-reseal/v1",
            "check_id": check_id,
            "effect": effect,
            "before_manifest_sha256": before_manifest.get("manifest_sha256"),
            "after_manifest_sha256": after["manifest_sha256"],
        }

    def _require_check(self, check_id: str) -> PreparedCheck:
        check = self.prepared_checks.get(check_id)
        if check is None:
            raise _error(
                "proof_verification_profile_contract_invalid",
                "The requested check is not part of the frozen verification profile.",
                check_id=check_id,
            )
        return check


@contextmanager
def prepare_proof_workspace(
    canonical_root: Path,
    *,
    spec: Mapping[str, Any],
    authority_resolution: Mapping[str, Any],
    bootstrap_profile: Mapping[str, Any],
    verification_profile: Mapping[str, Any],
    source_bindings: Mapping[str, Path],
    parent_environment: Mapping[str, str],
    failure_retention: str = "retain",
    temp_parent: Path | None = None,
) -> Iterator[PreparedProofWorkspace]:
    """Prepare a fresh, exact, non-reusable C2 proof workspace."""

    if failure_retention != "retain":
        raise _error(
            "proof_workspace_spec_invalid",
            "C2 retains every failure; delete_if_owned is not implemented.",
        )
    normalized = _validate_inputs(
        spec,
        authority_resolution,
        bootstrap_profile,
        verification_profile,
        source_bindings,
        parent_environment,
    )
    lease: _Lease | None = None
    prepared: PreparedProofWorkspace | None = None
    try:
        lease = _Lease.create(temp_parent)
        prepared = _prepare_owned_workspace(
            Path(canonical_root),
            lease=lease,
            spec=normalized["spec"],
            authority_resolution=normalized["authority_resolution"],
            bootstrap_profile=normalized["bootstrap_profile"],
            verification_profile=normalized["verification_profile"],
            source_bindings=normalized["source_bindings"],
            parent_environment=normalized["parent_environment"],
        )
    except ProofWorkspaceError as exc:
        if lease is not None:
            exc.details.setdefault("retained_temp_dir", str(lease.root))
            exc.details.setdefault("failure_class", "blocked")
            exc.details.setdefault("operational_state", "retained_failure")
        raise
    try:
        yield prepared
    except BaseException:
        prepared.state = "retained_failure"
        raise
    else:
        if prepared.state == "invalid":
            prepared.state = "retained_failure"
        else:
            prepared.state = "complete"
            lease.cleanup_success()
            prepared.state = "cleaned_success"


def directory_bundle_manifest(source: Path) -> dict[str, Any]:
    public, _ = _collect_directory_bundle(Path(source))
    return public


def _prepare_owned_workspace(
    canonical_root: Path,
    *,
    lease: _Lease,
    spec: dict[str, Any],
    authority_resolution: dict[str, Any],
    bootstrap_profile: dict[str, Any],
    verification_profile: dict[str, Any],
    source_bindings: dict[str, Path],
    parent_environment: dict[str, str],
) -> PreparedProofWorkspace:
    control = lease.root / "control"
    repository = lease.root / "repository"
    home = control / "home"
    temporary = control / "tmp"
    hooks = control / "hooks"
    for directory in (control, home, temporary, hooks):
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    empty_config = control / "empty.gitconfig"
    descriptor = os.open(
        empty_config,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    os.close(descriptor)
    git_environment = _git_environment(
        home=home,
        temporary=temporary,
        empty_config=empty_config,
    )
    runner = GitRunner(MappingProxyType(git_environment))
    source = _source_repository(canonical_root, runner)
    candidate = spec["candidate"]
    if source["object_format"] != candidate["object_format"]:
        raise _error(
            "proof_candidate_identity_mismatch",
            "The candidate object format does not match the source repository.",
        )
    source_commit = _resolve_exact_commit(
        source["root"],
        candidate["commit_oid"],
        runner,
        code="proof_candidate_identity_mismatch",
    )
    source_tree = _git_text(
        source["root"],
        runner,
        "rev-parse",
        "--verify",
        f"{source_commit}^{{tree}}",
    )
    if source_tree != candidate["tree_oid"]:
        raise _error(
            "proof_candidate_identity_mismatch",
            "The candidate tree does not match the source commit.",
            expected=candidate["tree_oid"],
            actual=source_tree,
        )
    if not _candidate_reachable(source["root"], source_commit, runner):
        raise _error(
            "proof_candidate_not_reachable",
            "The candidate is not reachable from source HEAD, heads, or tags.",
            candidate=source_commit,
        )
    _clone_exact_repository(
        source["root"],
        repository,
        candidate_commit=source_commit,
        candidate_tree=source_tree,
        source_common_dir=source["common_dir"],
        runner=runner,
        hooks=hooks,
    )
    state = "candidate_checked_out"
    tree_entries, tree_sha256 = _verify_exact_tree(
        repository,
        runner,
        candidate_commit=source_commit,
        object_format=candidate["object_format"],
    )
    if _git_bytes(repository, runner, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise _error("proof_checkout_dirty", "The exact candidate checkout is not initially clean.")
    state = "initially_clean"
    actual_diff_sha256 = _verify_authority_diff(
        repository,
        authority_resolution,
        runner,
    )
    disposition = "eligible"
    reasons: set[str] = set()
    effective = authority_resolution["effective"]
    if effective["reuse_allowed"] is not True:
        disposition = "fresh_only"
        reasons.add("proof_authority_reuse_forbidden")
    base_status = authority_resolution["base"]["status"]
    if base_status == "base_unknown":
        disposition = "fresh_only"
        reasons.add("proof_authority_base_unknown")
    elif base_status == "no_candidate_change":
        disposition = "fresh_only"
        reasons.add("proof_authority_no_candidate_change")
    tracked_by_path = {entry["path"]: entry for entry in tree_entries}
    external_public, input_runtime, input_reasons = _materialize_external_inputs(
        repository,
        spec["external_inputs"],
        source_bindings,
        tracked_by_path=tracked_by_path,
        super_object_format=candidate["object_format"],
        runner=runner,
        hooks=hooks,
    )
    if input_reasons:
        disposition = "fresh_only"
        reasons.update(input_reasons)
    state = "inputs_materialized"
    token_map = _token_map(
        repository=repository,
        home=home,
        temporary=temporary,
        hooks=hooks,
        empty_config=empty_config,
        input_runtime=input_runtime,
    )
    prepared_checks, check_public, check_reasons = _prepare_checks(
        verification_profile,
        repository=repository,
        canonical_root=source["root"],
        parent_environment=parent_environment,
        home=home,
        temporary=temporary,
        empty_config=empty_config,
        token_map=token_map,
    )
    if check_reasons:
        disposition = "fresh_only"
        reasons.update(check_reasons)
    state = "checks_prepared"
    config_sha256 = _repository_config_sha256(repository, runner)
    external_binding_sha256 = proof_document_sha256(
        {
            "contract_version": "proof-external-input-binding/v1",
            "entries": external_public,
        }
    )
    check_plan_sha256 = proof_document_sha256(
        {
            "contract_version": "proof-check-plan/v1",
            "checks": verification_profile["checks"],
        }
    )
    resolution_sha256 = authority_document_sha256(authority_resolution)
    profile_sha256 = proof_document_sha256(verification_profile)
    proof_key_sha256 = proof_document_sha256(
        {
            "contract_version": "proof-key/v1",
            "target": spec["target"],
            "candidate_commit_oid": candidate["commit_oid"],
            "candidate_tree_oid": candidate["tree_oid"],
            "authority_surface_resolution_sha256": resolution_sha256,
            "bootstrap_profile_sha256": authority_document_sha256(bootstrap_profile),
            "actual_diff_sha256": actual_diff_sha256,
            "verification_profile_sha256": profile_sha256,
            "check_plan_sha256": check_plan_sha256,
            "external_input_binding_sha256": external_binding_sha256,
            "isolation_contract_version": PROOF_WORKSPACE_ISOLATION_CONTRACT_VERSION,
        }
    )
    binding = {
        "contract_version": PROOF_WORKSPACE_BINDING_CONTRACT_VERSION,
        "spec_sha256": proof_document_sha256(spec),
        "repository": {
            "candidate": dict(candidate),
            "git_tree_entries_sha256": tree_sha256,
            "detached": True,
            "initially_clean": True,
            "git_common_dir_distinct": True,
            "alternates_absent": True,
            "origin_absent": True,
            "configuration_sealed": True,
        },
        "authority": {
            "resolution_sha256": resolution_sha256,
            "base_status": base_status,
            "actual_diff_sha256": actual_diff_sha256,
        },
        "verification_profile": {
            "profile_id": verification_profile["profile_id"],
            "sha256": profile_sha256,
            "check_plan_sha256": check_plan_sha256,
        },
        "external_inputs": {
            "binding_sha256": external_binding_sha256,
            "entries": external_public,
        },
        "checks": check_public,
        "proof_key": {
            "contract_version": "proof-key/v1",
            "sha256": proof_key_sha256,
        },
        "reuse": {
            "authority_effective": {
                "reuse_allowed": effective["reuse_allowed"],
                "risk_level": effective["risk_level"],
                "human_gate_required": effective["human_gate_required"],
            },
            "disposition": disposition,
            "r2_reuse_eligible": disposition == "eligible",
            "reuse_authorized": False,
            "reason_codes": sorted(reasons),
        },
        "terminal_authority": False,
        "mandatory_evidence": False,
    }
    binding_validation = validate_proof_workspace_binding(binding)
    if not binding_validation.ok:
        raise _error(
            "proof_workspace_binding_invalid",
            "The prepared proof workspace binding failed its strict contract.",
            errors=list(binding_validation.errors),
        )
    declared_outputs = MappingProxyType(
        {
            check["check_id"]: tuple(check["declared_outputs"])
            for check in verification_profile["checks"]
        }
    )
    workspace = PreparedProofWorkspace(
        root=repository,
        lease_root=lease.root,
        binding=binding,
        prepared_checks=MappingProxyType(prepared_checks),
        state=state,
        reuse_disposition=disposition,
        _lease=lease,
        _git=runner,
        _candidate_commit=source_commit,
        _candidate_tree=source_tree,
        _object_format=candidate["object_format"],
        _tracked_replacement_paths=frozenset(
            str(item.expected["destination"])
            for item in input_runtime
            if item.kind == "materialized_file" and item.destination is not None
        ),
        _config_sha256=config_sha256,
        _input_runtime=tuple(input_runtime),
        _declared_outputs=declared_outputs,
        _binding_sha256=proof_document_sha256(binding),
    )
    workspace.assert_ready_to_spawn(next(iter(prepared_checks)))
    workspace.state = "ready"
    return workspace


def _validate_inputs(
    spec: Mapping[str, Any],
    authority_resolution: Mapping[str, Any],
    bootstrap_profile: Mapping[str, Any],
    verification_profile: Mapping[str, Any],
    source_bindings: Mapping[str, Path],
    parent_environment: Mapping[str, str],
) -> dict[str, Any]:
    spec_value = _json_copy(spec, code="proof_workspace_spec_invalid")
    authority_value = _json_copy(
        authority_resolution,
        code="proof_authority_contract_invalid",
    )
    bootstrap_value = _json_copy(
        bootstrap_profile,
        code="proof_authority_contract_invalid",
    )
    profile_value = _json_copy(
        verification_profile,
        code="proof_verification_profile_contract_invalid",
    )
    spec_validation = validate_proof_workspace_spec(spec_value)
    if not spec_validation.ok:
        raise _error(
            "proof_workspace_spec_invalid",
            "The proof workspace spec is invalid.",
            errors=list(spec_validation.errors),
        )
    authority_validation = validate_authority_surface_resolution(authority_value)
    if not authority_validation.ok:
        raise _error(
            "proof_authority_contract_invalid",
            "The C1 authority resolution is invalid.",
            errors=list(authority_validation.errors),
        )
    bootstrap_validation = validate_bootstrap_authority_profile(bootstrap_value)
    if not bootstrap_validation.ok:
        raise _error(
            "proof_authority_contract_invalid",
            "The bootstrap authority profile is invalid.",
            errors=list(bootstrap_validation.errors),
        )
    profile_validation = validate_verification_profile(profile_value)
    if not profile_validation.ok:
        raise _error(
            "proof_verification_profile_contract_invalid",
            "The verification profile is invalid.",
            errors=list(profile_validation.errors),
        )
    expected_hashes = {
        "authority_surface_resolution_sha256": authority_document_sha256(authority_value),
        "bootstrap_profile_sha256": authority_document_sha256(bootstrap_value),
        "verification_profile_sha256": proof_document_sha256(profile_value),
    }
    for digest_field, actual in expected_hashes.items():
        if spec_value[digest_field] != actual:
            code = (
                "proof_bootstrap_profile_digest_mismatch"
                if digest_field == "bootstrap_profile_sha256"
                else "proof_verification_profile_digest_mismatch"
                if digest_field == "verification_profile_sha256"
                else "proof_authority_contract_invalid"
            )
            raise _error(
                code,
                "A bound proof workspace input digest does not match its object.",
                field=digest_field,
                expected=spec_value[digest_field],
                actual=actual,
            )
    if spec_value["target"] != authority_value["target"]:
        raise _error(
            "proof_authority_contract_invalid",
            "The proof target does not match the C1 authority target.",
        )
    if {
        "commit_oid": spec_value["candidate"]["commit_oid"],
        "tree_oid": spec_value["candidate"]["tree_oid"],
    } != authority_value["candidate"]:
        raise _error(
            "proof_candidate_identity_mismatch",
            "The proof candidate does not match the C1 authority candidate.",
        )
    if authority_value["bootstrap_profile"]["sha256"] != expected_hashes[
        "bootstrap_profile_sha256"
    ]:
        raise _error(
            "proof_bootstrap_profile_digest_mismatch",
            "The C1 resolution does not bind the supplied bootstrap profile.",
        )
    declared_ids = {item["input_id"] for item in spec_value["external_inputs"]}
    if not set(source_bindings).issubset(declared_ids):
        raise _error(
            "proof_external_input_contract_invalid",
            "Source bindings contain undeclared input IDs.",
            undeclared=sorted(set(source_bindings) - declared_ids),
        )
    check_ids = {check["check_id"] for check in profile_value["checks"]}
    by_check = {check["check_id"]: set(check["input_ids"]) for check in profile_value["checks"]}
    for declaration in spec_value["external_inputs"]:
        consumers = set(declaration["consumer_check_ids"])
        if not consumers.issubset(check_ids):
            raise _error(
                "proof_verification_profile_contract_invalid",
                "An external input names an unknown consumer check.",
                input_id=declaration["input_id"],
            )
        for check_id in consumers:
            if declaration["input_id"] not in by_check[check_id]:
                raise _error(
                    "proof_verification_profile_contract_invalid",
                    "The profile and external input consumer binding disagree.",
                    input_id=declaration["input_id"],
                    check_id=check_id,
                )
    declarations = {item["input_id"]: item for item in spec_value["external_inputs"]}
    for check_id, input_ids in by_check.items():
        for input_id in input_ids:
            if input_id not in declarations or check_id not in declarations[input_id][
                "consumer_check_ids"
            ]:
                raise _error(
                    "proof_verification_profile_contract_invalid",
                    "The profile references an unbound external input.",
                    input_id=input_id,
                    check_id=check_id,
                )
    if any(not isinstance(name, str) or not isinstance(value, str) for name, value in parent_environment.items()):
        raise _error(
            "proof_environment_injection_forbidden",
            "The explicit parent environment must contain only string pairs.",
        )
    return {
        "spec": spec_value,
        "authority_resolution": authority_value,
        "bootstrap_profile": bootstrap_value,
        "verification_profile": profile_value,
        "source_bindings": {str(key): Path(value) for key, value in source_bindings.items()},
        "parent_environment": dict(parent_environment),
    }


def _json_copy(value: Mapping[str, Any], *, code: str) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise _error(code, "The proof contract is not canonical-JSON compatible.") from exc
    if not isinstance(decoded, dict):
        raise _error(code, "The proof contract must be an object.")
    return decoded


def _git_environment(
    *,
    home: Path,
    temporary: Path,
    empty_config: Path,
) -> dict[str, str]:
    return {
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_CONFIG_GLOBAL": str(empty_config),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
        "TEMP": str(temporary),
        "TMP": str(temporary),
        "TMPDIR": str(temporary),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }


def _source_repository(root: Path, runner: GitRunner) -> dict[str, Any]:
    canonical = root.resolve()
    try:
        root_stat = os.lstat(canonical)
    except OSError as exc:
        raise _error("proof_candidate_object_unavailable", "The canonical repository is unavailable.") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise _error("proof_candidate_object_unavailable", "The canonical repository root is unsafe.")
    toplevel = Path(_git_text(canonical, runner, "rev-parse", "--show-toplevel")).resolve()
    if toplevel != canonical:
        raise _error(
            "proof_candidate_object_unavailable",
            "The canonical root must be the exact linked or primary worktree root.",
            root=str(canonical),
            repository_root=str(toplevel),
        )
    common = Path(
        _git_text(
            canonical,
            runner,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        )
    ).resolve()
    object_format = _git_text(canonical, runner, "rev-parse", "--show-object-format")
    if object_format not in {"sha1", "sha256"}:
        raise _error("proof_candidate_identity_mismatch", "Unsupported Git object format.")
    return {
        "root": canonical,
        "common_dir": common,
        "object_dir": (common / "objects").resolve(),
        "object_format": object_format,
    }


def _resolve_exact_commit(root: Path, oid: str, runner: GitRunner, *, code: str) -> str:
    resolved = _git_text(root, runner, "rev-parse", "--verify", f"{oid}^{{commit}}", code=code)
    if resolved != oid:
        raise _error(code, "The Git commit did not resolve exactly.", expected=oid, actual=resolved)
    return resolved


def _candidate_reachable(root: Path, candidate: str, runner: GitRunner) -> bool:
    head = _git_text(root, runner, "rev-parse", "--verify", "HEAD^{commit}")
    if _git_returncode(root, runner, "merge-base", "--is-ancestor", candidate, head) == 0:
        return True
    refs = _git_bytes(
        root,
        runner,
        "for-each-ref",
        f"--contains={candidate}",
        "--format=%(refname)",
        "refs/heads",
        "refs/tags",
    )
    return any(line for line in refs.splitlines())


def _clone_exact_repository(
    source: Path,
    destination: Path,
    *,
    candidate_commit: str,
    candidate_tree: str,
    source_common_dir: Path,
    runner: GitRunner,
    hooks: Path,
) -> None:
    _git_bytes(
        source.parent,
        runner,
        "clone",
        "--quiet",
        "--no-local",
        "--no-checkout",
        str(source),
        str(destination),
        code="proof_clone_failed",
    )
    try:
        cloned_commit = _resolve_exact_commit(
            destination,
            candidate_commit,
            runner,
            code="proof_candidate_object_unavailable",
        )
    except ProofWorkspaceError as exc:
        raise _error(
            "proof_candidate_object_unavailable",
            "The exact ref-reachable candidate did not transfer to the clone.",
            candidate=candidate_commit,
        ) from exc
    clone_common = Path(
        _git_text(
            destination,
            runner,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        )
    ).resolve()
    if clone_common == source_common_dir.resolve() or (clone_common / "objects").resolve() == (
        source_common_dir / "objects"
    ).resolve():
        raise _error(
            "proof_git_common_dir_shared",
            "The proof clone shares Git metadata or objects with its source.",
        )
    for remote in _git_text(destination, runner, "remote").splitlines():
        if remote:
            _git_bytes(destination, runner, "remote", "remove", remote)
    _git_bytes(destination, runner, "config", "--local", "core.hooksPath", str(hooks))
    _git_bytes(destination, runner, "config", "--local", "core.filemode", "true")
    _assert_no_alternates_or_promisor(destination, runner)
    _assert_no_remotes(destination, runner)
    _git_bytes(
        destination,
        runner,
        "-c",
        f"core.hooksPath={hooks}",
        "checkout",
        "--quiet",
        "--detach",
        cloned_commit,
        code="proof_clone_failed",
    )
    head = _git_text(destination, runner, "rev-parse", "--verify", "HEAD^{commit}")
    tree = _git_text(destination, runner, "rev-parse", "--verify", "HEAD^{tree}")
    symbolic_rc = _git_returncode(destination, runner, "symbolic-ref", "-q", "HEAD")
    if head != candidate_commit or tree != candidate_tree or symbolic_rc == 0:
        raise _error(
            "proof_checkout_tree_mismatch",
            "The proof clone is not detached at the exact candidate commit and tree.",
        )
    _assert_safe_config(destination, runner, hooks)


def _verify_authority_diff(
    repository: Path,
    resolution: Mapping[str, Any],
    runner: GitRunner,
) -> str:
    status = resolution["base"]["status"]
    recorded = resolution["actual_diff"]
    if status == "base_unknown":
        return str(recorded["sha256"])
    base = resolution["base"]["commit_oid"]
    candidate = resolution["candidate"]["commit_oid"]
    if status == "no_candidate_change" and base != candidate:
        raise _error(
            "proof_authority_diff_mismatch",
            "no_candidate_change requires identical base and candidate commit OIDs.",
            base_commit_oid=base,
            candidate_commit_oid=candidate,
        )
    actual = canonical_git_diff(
        repository,
        base_commit_oid=base,
        candidate_commit_oid=candidate,
        git_runner=runner,
    )
    if status == "no_candidate_change" and actual["entries"]:
        raise _error(
            "proof_authority_diff_mismatch",
            "no_candidate_change must have an empty canonical diff.",
        )
    if actual != recorded:
        raise _error(
            "proof_authority_diff_mismatch",
            "The sealed clone's canonical diff does not match the C1 resolution.",
            expected=recorded,
            actual=actual,
        )
    return str(actual["sha256"])


def _verify_exact_tree(
    root: Path,
    runner: GitRunner,
    *,
    candidate_commit: str,
    object_format: str,
    excluded_materialized_paths: frozenset[str] = frozenset(),
) -> tuple[list[dict[str, str]], str]:
    raw = _git_bytes(root, runner, "ls-tree", "-rz", "--full-tree", candidate_commit)
    entries: list[dict[str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, object_type, oid = header.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise _error(
                "proof_git_tree_materialization_mismatch",
                "The candidate Git tree contains an unsupported entry.",
            ) from exc
        if path != unicodedata.normalize("NFC", path) or not _safe_relative(path):
            raise _error(
                "proof_git_tree_materialization_mismatch",
                "The candidate Git tree path is not canonical POSIX UTF-8.",
                path=path,
            )
        if mode not in {"100644", "100755", "120000", "160000"}:
            raise _error(
                "proof_git_tree_materialization_mismatch",
                "The candidate Git tree mode is unsupported.",
                path=path,
                mode=mode,
            )
        expected_type = "commit" if mode == "160000" else "blob"
        if object_type != expected_type:
            raise _error(
                "proof_git_tree_materialization_mismatch",
                "The candidate Git tree object type does not match its mode.",
                path=path,
            )
        entry = {"path": path, "mode": mode, "object_type": object_type, "oid": oid}
        entries.append(entry)
        if path in excluded_materialized_paths:
            continue
        path_value = root.joinpath(*PurePosixPath(path).parts)
        if mode == "160000":
            if path_value.exists() and (not path_value.is_dir() or path_value.is_symlink()):
                raise _error(
                    "proof_git_tree_materialization_mismatch",
                    "A gitlink materialized as an unsafe filesystem kind.",
                    path=path,
                )
            continue
        try:
            value = os.lstat(path_value)
        except OSError as exc:
            raise _error(
                "proof_git_tree_materialization_mismatch",
                "A tracked candidate path is missing.",
                path=path,
            ) from exc
        if mode == "120000":
            if not stat.S_ISLNK(value.st_mode):
                raise _error(
                    "proof_git_tree_materialization_mismatch",
                    "A Git symlink did not materialize as a symlink.",
                    path=path,
                )
            target = os.fsencode(os.readlink(path_value))
            actual_oid = _git_blob_oid(target, object_format)
        else:
            if not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode):
                raise _error(
                    "proof_git_tree_materialization_mismatch",
                    "A Git blob did not materialize as a regular file.",
                    path=path,
                )
            executable = bool(stat.S_IMODE(value.st_mode) & 0o111)
            if executable != (mode == "100755"):
                raise _error(
                    "proof_git_tree_materialization_mismatch",
                    "A tracked executable mode changed during checkout.",
                    path=path,
                )
            contents, _ = _read_regular_file(path_value, require_single_link=True)
            actual_oid = _git_blob_oid(contents, object_format)
        if actual_oid != oid:
            raise _error(
                "proof_git_tree_materialization_mismatch",
                "A tracked candidate object does not match its tree OID.",
                path=path,
                expected=oid,
                actual=actual_oid,
            )
    entries.sort(key=lambda item: item["path"])
    digest = proof_document_sha256(
        {"contract_version": "proof-git-tree/v1", "entries": entries}
    )
    return entries, digest


def _materialize_external_inputs(
    repository: Path,
    declarations: Sequence[Mapping[str, Any]],
    source_bindings: Mapping[str, Path],
    *,
    tracked_by_path: Mapping[str, Mapping[str, str]],
    super_object_format: str,
    runner: GitRunner,
    hooks: Path,
) -> tuple[list[dict[str, Any]], list[_InputRuntime], set[str]]:
    public: list[dict[str, Any]] = []
    runtime: list[_InputRuntime] = []
    reasons: set[str] = set()
    _validate_destination_set(declarations, tracked_by_path)
    for declaration in sorted(declarations, key=lambda item: str(item["input_id"])):
        input_id = str(declaration["input_id"])
        kind = str(declaration["type"])
        if kind == "opaque":
            public.append({"input_id": input_id, "type": kind, "status": "opaque"})
            runtime.append(_InputRuntime(input_id, kind, None, MappingProxyType({})))
            reasons.add("proof_external_input_unknown")
            continue
        source = source_bindings.get(input_id)
        if source is None or not _lexists(source):
            if declaration["on_unavailable"] == "block":
                raise _error(
                    "proof_external_input_missing",
                    "A required typed external input is unavailable.",
                    input_id=input_id,
                )
            public.append({"input_id": input_id, "type": kind, "status": "unavailable"})
            runtime.append(_InputRuntime(input_id, kind, None, MappingProxyType({})))
            reasons.add("proof_external_input_missing")
            continue
        destination = repository.joinpath(*PurePosixPath(str(declaration["destination"])).parts)
        if kind == "file":
            try:
                contents, source_identity = _read_regular_file(source, require_single_link=True)
            except ProofWorkspaceError as exc:
                if _record_unavailable_input(
                    exc, declaration, public=public, runtime=runtime, reasons=reasons
                ):
                    continue
                raise
            _require_material_digest(contents, declaration, input_id=input_id)
            _write_created_file(destination, contents, str(declaration["mode"]))
            _assert_source_unchanged(source, source_identity)
            entry = _file_binding_entry(input_id, kind, declaration, contents)
            public.append(entry)
            runtime.append(
                _InputRuntime(input_id, kind, destination, MappingProxyType(dict(entry)))
            )
        elif kind == "directory_bundle":
            try:
                bundle, private_entries = _collect_directory_bundle(source)
            except ProofWorkspaceError as exc:
                if _record_unavailable_input(
                    exc, declaration, public=public, runtime=runtime, reasons=reasons
                ):
                    continue
                raise
            if bundle["sha256"] != declaration["bundle_sha256"]:
                raise _error(
                    "proof_external_input_digest_mismatch",
                    "The deterministic directory bundle digest does not match its declaration.",
                    input_id=input_id,
                )
            _write_directory_bundle(destination, private_entries)
            final_bundle, _ = _collect_directory_bundle(source)
            if final_bundle != bundle:
                raise _error(
                    "proof_external_input_changed_during_materialization",
                    "The directory bundle changed during materialization.",
                    input_id=input_id,
                )
            entry = {
                "input_id": input_id,
                "type": kind,
                "status": "materialized",
                "destination": str(declaration["destination"]),
                "bundle_sha256": bundle["sha256"],
            }
            public.append(entry)
            runtime.append(
                _InputRuntime(input_id, kind, destination, MappingProxyType(dict(entry)))
            )
        elif kind == "submodule":
            entry = _materialize_submodule(
                source,
                destination,
                declaration,
                tracked_by_path=tracked_by_path,
                runner=runner,
                hooks=hooks,
                super_common=Path(
                    _git_text(
                        repository,
                        runner,
                        "rev-parse",
                        "--path-format=absolute",
                        "--git-common-dir",
                    )
                ).resolve(),
            )
            public.append(entry)
            runtime.append(
                _InputRuntime(input_id, kind, destination, MappingProxyType(dict(entry)))
            )
            if entry["object_format"] != super_object_format:
                reasons.add("proof_object_format_combination_unsupported")
        elif kind == "materialized_file":
            try:
                contents, source_identity = _read_regular_file(source, require_single_link=True)
            except ProofWorkspaceError as exc:
                if _record_unavailable_input(
                    exc, declaration, public=public, runtime=runtime, reasons=reasons
                ):
                    continue
                raise
            _require_material_digest(contents, declaration, input_id=input_id)
            if declaration["material_kind"] == "git_lfs":
                _verify_lfs_base(repository, declaration, tracked_by_path)
            else:
                _verify_generated_base(repository, declaration, tracked_by_path)
            _replace_or_create_file(destination, contents, str(declaration["mode"]))
            _assert_source_unchanged(source, source_identity)
            entry = _file_binding_entry(input_id, kind, declaration, contents)
            entry["material_kind"] = declaration["material_kind"]
            if declaration["material_kind"] == "git_lfs":
                entry["pointer_blob_oid"] = declaration["pointer_blob_oid"]
            public.append(entry)
            runtime.append(
                _InputRuntime(input_id, kind, destination, MappingProxyType(dict(entry)))
            )
        else:
            raise _error(
                "proof_external_input_contract_invalid",
                "Unsupported typed external input.",
                input_id=input_id,
            )
    public.sort(key=lambda item: item["input_id"])
    return public, runtime, reasons


def _record_unavailable_input(
    error: ProofWorkspaceError,
    declaration: Mapping[str, Any],
    *,
    public: list[dict[str, Any]],
    runtime: list[_InputRuntime],
    reasons: set[str],
) -> bool:
    if error.code not in {"proof_external_input_missing", "proof_external_input_unreadable"}:
        return False
    if declaration["on_unavailable"] == "block":
        return False
    input_id = str(declaration["input_id"])
    kind = str(declaration["type"])
    public.append({"input_id": input_id, "type": kind, "status": "unavailable"})
    runtime.append(_InputRuntime(input_id, kind, None, MappingProxyType({})))
    reasons.add(error.code)
    return True


def _validate_destination_set(
    declarations: Sequence[Mapping[str, Any]],
    tracked_by_path: Mapping[str, Mapping[str, str]],
) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []
    tracked_casefold = {path.casefold(): path for path in tracked_by_path}
    for declaration in declarations:
        destination = declaration.get("destination")
        if destination is None:
            continue
        parts = PurePosixPath(str(destination)).parts
        if not parts or any(
            part.casefold() in _PROTECTED_DESTINATIONS for part in parts
        ):
            raise _error(
                "proof_external_destination_conflict",
                "A typed input targets a protected proof or repository destination.",
                input_id=declaration["input_id"],
                destination=destination,
            )
        folded = tuple(part.casefold() for part in parts)
        for prior_id, prior in seen:
            shared = min(len(prior), len(folded))
            if prior[:shared] == folded[:shared]:
                raise _error(
                    "proof_external_destination_conflict",
                    "Typed external input destinations overlap.",
                    input_id=declaration["input_id"],
                    prior_input_id=prior_id,
                )
        seen.append((str(declaration["input_id"]), folded))
        exact_tracked = tracked_by_path.get(str(destination))
        case_collision = tracked_casefold.get(str(destination).casefold())
        kind = declaration["type"]
        allowed_exact = kind == "submodule" or kind == "materialized_file" and (
            declaration.get("material_kind") == "git_lfs"
            or declaration.get("base_expectation", {}).get("kind") == "placeholder"
        )
        if case_collision is not None and case_collision != destination:
            raise _error(
                "proof_external_destination_conflict",
                "A typed input has a case-fold collision with tracked content.",
                destination=destination,
            )
        if exact_tracked is not None and not allowed_exact:
            raise _error(
                "proof_external_destination_conflict",
                "A typed input overlaps tracked candidate content.",
                destination=destination,
            )
        prefix = str(destination) + "/"
        if any(path.startswith(prefix) for path in tracked_by_path) and not allowed_exact:
            raise _error(
                "proof_external_destination_conflict",
                "A typed input directory overlaps tracked candidate content.",
                destination=destination,
            )


def _collect_directory_bundle(
    source: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_path = Path(source)
    try:
        root_lstat = os.lstat(source_path)
    except OSError as exc:
        code = (
            "proof_external_input_unreadable"
            if isinstance(exc, PermissionError)
            else "proof_external_input_missing"
        )
        raise _error(
            code,
            "The directory bundle source is unavailable.",
        ) from exc
    if not stat.S_ISDIR(root_lstat.st_mode) or stat.S_ISLNK(root_lstat.st_mode):
        raise _error(
            "proof_external_input_unsafe",
            "The directory bundle source must be a real directory.",
        )
    try:
        root_fd = _open_directory(source_path)
    except PermissionError as exc:
        raise _error(
            "proof_external_input_unreadable",
            "The directory bundle source is unreadable.",
        ) from exc
    private: list[dict[str, Any]] = []
    seen_casefold: set[str] = set()
    try:
        try:
            _walk_bundle(root_fd, (), private, seen_casefold)
        except PermissionError as exc:
            raise _error(
                "proof_external_input_unreadable",
                "A directory bundle member is unreadable.",
            ) from exc
        if _StatIdentity.from_stat(os.fstat(root_fd)) != _StatIdentity.from_stat(root_lstat):
            raise _error(
                "proof_external_input_changed_during_materialization",
                "The directory bundle root changed during collection.",
            )
    finally:
        os.close(root_fd)
    public_entries = [
        {key: value for key, value in entry.items() if key not in {"bytes", "target"}}
        for entry in private
    ]
    public_entries.sort(key=lambda item: (item["path"], item["kind"]))
    private.sort(key=lambda item: (item["path"], item["kind"]))
    digest = proof_document_sha256(
        {
            "contract_version": "proof-directory-bundle/v1",
            "entries": public_entries,
        }
    )
    return {
        "contract_version": "proof-directory-bundle/v1",
        "sha256": digest,
        "entries": public_entries,
    }, private


def _walk_bundle(
    directory_fd: int,
    prefix: tuple[str, ...],
    entries: list[dict[str, Any]],
    seen_casefold: set[str],
) -> None:
    for name in sorted(os.listdir(directory_fd)):
        if not name or name in {".", ".."} or "/" in name or "\0" in name:
            raise _error("proof_external_input_unsafe", "A directory bundle name is unsafe.")
        normalized = unicodedata.normalize("NFC", name)
        if normalized != name or normalized.casefold() in _PROTECTED_DESTINATIONS:
            raise _error(
                "proof_external_input_unsafe",
                "A directory bundle contains a protected or non-canonical name.",
                name=name,
            )
        parts = (*prefix, name)
        relative = "/".join(parts)
        folded = relative.casefold()
        if folded in seen_casefold:
            raise _error(
                "proof_external_input_unsafe",
                "A directory bundle contains a path collision.",
                path=relative,
            )
        seen_casefold.add(folded)
        value = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(value.st_mode):
            entries.append({"path": relative, "kind": "directory", "mode": "0755"})
            child_fd = _open_directory_at(directory_fd, name)
            try:
                _walk_bundle(child_fd, parts, entries, seen_casefold)
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(value.st_mode):
            if value.st_nlink != 1:
                raise _error(
                    "proof_external_input_unsafe",
                    "Directory bundle regular files must be single-link.",
                    path=relative,
                )
            contents, identity = _read_regular_file_at(directory_fd, name)
            if identity != _StatIdentity.from_stat(value):
                raise _error(
                    "proof_external_input_changed_during_materialization",
                    "A directory bundle file changed while read.",
                    path=relative,
                )
            entries.append(
                {
                    "path": relative,
                    "kind": "file",
                    "mode": "0755" if stat.S_IMODE(value.st_mode) & 0o111 else "0644",
                    "size": len(contents),
                    "sha256": _bytes_sha256(contents),
                    "bytes": contents,
                }
            )
        elif stat.S_ISLNK(value.st_mode):
            target = os.readlink(name, dir_fd=directory_fd)
            _require_safe_bundle_symlink(parts, target)
            entries.append(
                {
                    "path": relative,
                    "kind": "symlink",
                    "target_sha256": _bytes_sha256(os.fsencode(target)),
                    "target": target,
                }
            )
        else:
            raise _error(
                "proof_external_input_unsafe",
                "A directory bundle contains a FIFO, socket, device, or unsupported kind.",
                path=relative,
            )


def _require_safe_bundle_symlink(parts: tuple[str, ...], target: str) -> None:
    target_path = PurePosixPath(target)
    if target_path.is_absolute() or "\0" in target or "\\" in target:
        raise _error("proof_external_input_unsafe", "A directory bundle symlink is unsafe.")
    stack = list(parts[:-1])
    for component in target_path.parts:
        if component in {"", "."}:
            continue
        if component == "..":
            if not stack:
                raise _error(
                    "proof_external_input_unsafe",
                    "A directory bundle symlink escapes its source root.",
                )
            stack.pop()
        else:
            stack.append(component)


def _write_directory_bundle(destination: Path, entries: Sequence[Mapping[str, Any]]) -> None:
    if _lexists(destination):
        raise _error(
            "proof_external_destination_conflict",
            "The directory bundle destination already exists.",
            destination=str(destination),
        )
    destination.mkdir(mode=0o755, parents=True, exist_ok=False)
    root_fd = _open_directory(destination)
    try:
        for entry in entries:
            parts = PurePosixPath(str(entry["path"])).parts
            parent_fd = _walk_destination_parent(root_fd, parts[:-1], create=True)
            try:
                name = parts[-1]
                if entry["kind"] == "directory":
                    try:
                        os.mkdir(name, 0o755, dir_fd=parent_fd)
                    except FileExistsError:
                        existing_fd = _open_directory_at(parent_fd, name)
                        os.close(existing_fd)
                elif entry["kind"] == "symlink":
                    os.symlink(str(entry["target"]), name, dir_fd=parent_fd)
                else:
                    _write_file_at(parent_fd, name, bytes(entry["bytes"]), str(entry["mode"]))
            finally:
                os.close(parent_fd)
    finally:
        os.close(root_fd)


def _materialize_submodule(
    source: Path,
    destination: Path,
    declaration: Mapping[str, Any],
    *,
    tracked_by_path: Mapping[str, Mapping[str, str]],
    runner: GitRunner,
    hooks: Path,
    super_common: Path,
) -> dict[str, Any]:
    relative = str(declaration["destination"])
    tracked = tracked_by_path.get(relative)
    if (
        tracked is None
        or tracked["mode"] != "160000"
        or tracked["oid"] != declaration["gitlink_oid"]
        or declaration["gitlink_oid"] != declaration["commit_oid"]
    ):
        raise _error(
            "proof_submodule_gitlink_mismatch",
            "The submodule declaration does not match the candidate gitlink.",
            input_id=declaration["input_id"],
        )
    source_info = _source_repository(source, runner)
    if source_info["object_format"] != declaration["object_format"]:
        raise _error("proof_submodule_commit_mismatch", "Submodule object format mismatch.")
    commit = _resolve_exact_commit(
        source_info["root"],
        str(declaration["commit_oid"]),
        runner,
        code="proof_submodule_commit_mismatch",
    )
    tree = _git_text(source_info["root"], runner, "rev-parse", "--verify", f"{commit}^{{tree}}")
    if tree != declaration["tree_oid"]:
        raise _error("proof_submodule_tree_mismatch", "Submodule tree identity mismatch.")
    if not _candidate_reachable(source_info["root"], commit, runner):
        raise _error("proof_candidate_not_reachable", "The submodule commit is not ref-reachable.")
    if destination.exists():
        try:
            destination.rmdir()
        except OSError as exc:
            raise _error(
                "proof_external_destination_conflict",
                "The candidate gitlink path is not an empty directory.",
            ) from exc
    _clone_exact_repository(
        source_info["root"],
        destination,
        candidate_commit=commit,
        candidate_tree=tree,
        source_common_dir=source_info["common_dir"],
        runner=runner,
        hooks=hooks,
    )
    clone_common = Path(
        _git_text(
            destination,
            runner,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        )
    ).resolve()
    if clone_common == super_common:
        raise _error("proof_git_common_dir_shared", "Submodule shares superproject metadata.")
    _verify_exact_tree(
        destination,
        runner,
        candidate_commit=commit,
        object_format=str(declaration["object_format"]),
    )
    return {
        "input_id": declaration["input_id"],
        "type": "submodule",
        "status": "materialized",
        "destination": relative,
        "gitlink_oid": declaration["gitlink_oid"],
        "commit_oid": commit,
        "tree_oid": tree,
        "object_format": declaration["object_format"],
    }


def _verify_lfs_base(
    repository: Path,
    declaration: Mapping[str, Any],
    tracked_by_path: Mapping[str, Mapping[str, str]],
) -> None:
    relative = str(declaration["destination"])
    tracked = tracked_by_path.get(relative)
    if tracked is None or tracked["oid"] != declaration["pointer_blob_oid"]:
        raise _error("proof_lfs_pointer_mismatch", "The declared LFS pointer blob is not tracked.")
    pointer, _ = _read_regular_file(
        repository.joinpath(*PurePosixPath(relative).parts),
        require_single_link=True,
    )
    try:
        text = pointer.decode("ascii")
        lines = text.splitlines()
        parsed = {
            "version": lines[0],
            "oid": lines[1].removeprefix("oid "),
            "size": int(lines[2].removeprefix("size ")),
        }
    except (IndexError, UnicodeDecodeError, ValueError) as exc:
        raise _error("proof_lfs_pointer_mismatch", "The tracked LFS pointer is invalid.") from exc
    if (
        parsed["version"] != "version https://git-lfs.github.com/spec/v1"
        or parsed["oid"] != declaration["lfs_oid_sha256"]
        or parsed["size"] != declaration["lfs_size"]
    ):
        raise _error("proof_lfs_pointer_mismatch", "The tracked LFS pointer does not match material.")


def _verify_generated_base(
    repository: Path,
    declaration: Mapping[str, Any],
    tracked_by_path: Mapping[str, Mapping[str, str]],
) -> None:
    relative = str(declaration["destination"])
    expectation = declaration["base_expectation"]
    tracked = tracked_by_path.get(relative)
    destination = repository.joinpath(*PurePosixPath(relative).parts)
    if expectation["kind"] == "absent":
        if tracked is not None or _lexists(destination):
            raise _error(
                "proof_external_destination_conflict",
                "Generated material expected an absent candidate destination.",
            )
        return
    expected_mode = "100755" if expectation["mode"] == "0755" else "100644"
    if (
        tracked is None
        or tracked["oid"] != expectation["blob_oid"]
        or tracked["mode"] != expected_mode
    ):
        raise _error(
            "proof_external_input_digest_mismatch",
            "Generated material placeholder does not match the candidate tree.",
        )


def _file_binding_entry(
    input_id: str,
    kind: str,
    declaration: Mapping[str, Any],
    contents: bytes,
) -> dict[str, Any]:
    return {
        "input_id": input_id,
        "type": kind,
        "status": "materialized",
        "destination": declaration["destination"],
        "sha256": _bytes_sha256(contents),
        "size": len(contents),
        "mode": declaration["mode"],
    }


def _require_material_digest(
    contents: bytes,
    declaration: Mapping[str, Any],
    *,
    input_id: str,
) -> None:
    if _bytes_sha256(contents) != declaration["sha256"] or len(contents) != declaration["size"]:
        raise _error(
            "proof_external_input_digest_mismatch",
            "Typed external input bytes do not match their declaration.",
            input_id=input_id,
        )


def _prepare_checks(
    profile: Mapping[str, Any],
    *,
    repository: Path,
    canonical_root: Path,
    parent_environment: Mapping[str, str],
    home: Path,
    temporary: Path,
    empty_config: Path,
    token_map: tuple[tuple[str, str], ...],
) -> tuple[dict[str, PreparedCheck], list[dict[str, Any]], set[str]]:
    prepared: dict[str, PreparedCheck] = {}
    public: list[dict[str, Any]] = []
    reasons: set[str] = set()
    for raw_check in profile["checks"]:
        check = dict(raw_check)
        check_id = str(check["check_id"])
        cwd = repository.joinpath(*PurePosixPath(str(check["cwd"])).parts).resolve()
        if cwd != repository and repository not in cwd.parents:
            raise _error(
                "proof_environment_injection_forbidden",
                "The prepared check cwd escapes the proof workspace.",
                check_id=check_id,
            )
        if not cwd.is_dir() or cwd.is_symlink():
            raise _error(
                "proof_environment_injection_forbidden",
                "The prepared check cwd is not an owned directory.",
                check_id=check_id,
            )
        env, environment_public, secret_names = _complete_check_environment(
            check,
            repository=repository,
            canonical_root=canonical_root,
            parent_environment=parent_environment,
            home=home,
            temporary=temporary,
            empty_config=empty_config,
            token_map=token_map,
        )
        argv = list(check["argv"])
        tool_path, tool_runtime, tool_public = _resolve_tool(argv[0], cwd=cwd, environment=env)
        argv[0] = str(tool_path)
        check_token_map = tuple(
            sorted(
                {*token_map, (str(tool_path), f"$HOST_TOOL:{check_id}")},
                key=lambda item: len(item[0]),
                reverse=True,
            )
        )
        plan_sha256 = proof_document_sha256(
            {"contract_version": "proof-check-plan-entry/v1", "check": check}
        )
        spawn_sha256 = _spawn_vector_sha256(argv, cwd, env, token_map=check_token_map)
        public_environment_sha = str(environment_public["public_values_sha256"])
        public_execution_sha = proof_document_sha256(
            {
                "contract_version": "proof-check-public-execution/v1",
                "check_id": check_id,
                "plan_sha256": plan_sha256,
                "tool_identity_sha256": tool_public["sha256"],
                "environment_sha256": public_environment_sha,
                "platform": {
                    "system": platform.system(),
                    "release": platform.release(),
                    "machine": platform.machine(),
                },
            }
        )
        if secret_names:
            reasons.add("proof_environment_unbound")
        prepared_check = PreparedCheck(
            check_id=check_id,
            argv=tuple(argv),
            cwd=cwd,
            env=MappingProxyType(dict(env)),
            timeout_seconds=int(check["timeout_seconds"]),
            max_output_bytes=int(check["max_output_bytes"]),
            plan_sha256=plan_sha256,
            tool_identity=MappingProxyType(dict(tool_public)),
            environment_binding=MappingProxyType(dict(environment_public)),
            spawn_vector_sha256=spawn_sha256,
            _tool_path=tool_path,
            _tool_identity_runtime=tool_runtime,
            _token_map=check_token_map,
            _secret_names=tuple(secret_names),
        )
        prepared[check_id] = prepared_check
        public.append(
            {
                "check_id": check_id,
                "plan_sha256": plan_sha256,
                "tool_identity_sha256": tool_public["sha256"],
                "environment": environment_public,
                "public_execution_sha256": public_execution_sha,
                "spawn_vector_sha256": None if secret_names else spawn_sha256,
                "secret_derived_digests_public": False,
            }
        )
    public.sort(key=lambda item: item["check_id"])
    return prepared, public, reasons


def _complete_check_environment(
    check: Mapping[str, Any],
    *,
    repository: Path,
    canonical_root: Path,
    parent_environment: Mapping[str, str],
    home: Path,
    temporary: Path,
    empty_config: Path,
    token_map: tuple[tuple[str, str], ...],
) -> tuple[dict[str, str], dict[str, Any], list[str]]:
    requested = list(check["environment"]["inherit_names"])
    forbidden = sorted(
        name
        for name in requested
        if name in _FORBIDDEN_ENVIRONMENT_NAMES
        or name.startswith("DYLD_")
        or name.startswith("GIT_")
        or name.startswith("LD_")
    )
    if forbidden:
        raise _error(
            "proof_environment_injection_forbidden",
            "The verification profile inherits a runtime-control environment variable.",
            names=forbidden,
        )
    environment = {
        name: parent_environment[name]
        for name in requested
        if name in parent_environment
    }
    fixed = {
        "GIT_CONFIG_GLOBAL": str(empty_config),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
        "TEMP": str(temporary),
        "TMP": str(temporary),
        "TMPDIR": str(temporary),
    }
    environment.update(fixed)
    python_entries: list[str] = []
    for raw in check["environment"]["workspace_pythonpath"]:
        path = repository if raw == "." else repository.joinpath(*PurePosixPath(raw).parts)
        resolved = path.resolve()
        if (
            (resolved != repository and repository not in resolved.parents)
            or resolved == canonical_root
            or canonical_root in resolved.parents
        ):
            raise _error(
                "proof_environment_injection_forbidden",
                "A verification PYTHONPATH entry escapes into canonical host source.",
                entry=raw,
            )
        python_entries.append(str(resolved))
    if python_entries:
        environment["PYTHONPATH"] = os.pathsep.join(python_entries)
    secret_names = sorted(name for name in requested if _secret_shaped(name) and name in environment)
    public_environment = {
        name: value for name, value in environment.items() if name not in secret_names
    }
    logical_public = _logicalize_environment(public_environment, token_map)
    binding = {
        "inheritance": "allowlist",
        "inherited_names": sorted(name for name in requested if name in environment),
        "fixed_names": sorted(fixed),
        "public_values_sha256": proof_document_sha256(
            {
                "contract_version": "proof-environment-values/v1",
                "values": sorted(logical_public.items()),
            }
        ),
        "values_recorded": False,
        "secret_shaped_names": secret_names,
        "secret_derived_digest_recorded": False,
    }
    return environment, binding, secret_names


def _resolve_tool(
    argv0: str,
    *,
    cwd: Path,
    environment: Mapping[str, str],
) -> tuple[Path, _StatIdentity, dict[str, Any]]:
    if os.sep in argv0 or (os.altsep and os.altsep in argv0):
        candidate = Path(argv0)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        unresolved = candidate
    else:
        found = shutil.which(argv0, path=environment.get("PATH", os.defpath))
        if found is None:
            raise _error(
                "proof_tool_identity_unbound",
                "The prepared check executable could not be resolved.",
                argv0=argv0,
            )
        unresolved = Path(found)
    try:
        resolved = unresolved.resolve(strict=True)
    except OSError as exc:
        raise _error(
            "proof_tool_identity_unbound",
            "The prepared check executable could not be resolved safely.",
            argv0=argv0,
        ) from exc
    contents, identity = _read_regular_file(resolved, require_single_link=False)
    if not stat.S_IMODE(identity.mode) & 0o111:
        raise _error(
            "proof_tool_identity_unbound",
            "The prepared check tool is not executable.",
            argv0=argv0,
        )
    shebang_sha256: str | None = None
    if contents.startswith(b"#!"):
        first_line = contents.splitlines()[0][2:].strip().split(maxsplit=1)[0]
        if first_line:
            interpreter = Path(os.fsdecode(first_line))
            if interpreter.is_absolute() and interpreter.exists():
                interpreter_bytes, _ = _read_regular_file(
                    interpreter.resolve(strict=True),
                    require_single_link=False,
                )
                shebang_sha256 = _bytes_sha256(interpreter_bytes)
    symlink_payload = proof_document_sha256(
        {
            "contract_version": "proof-tool-symlink-chain/v1",
            "requested_basename": Path(argv0).name,
            "resolved_basename": resolved.name,
            "was_symlink": unresolved.is_symlink(),
        }
    )
    public = {
        "contract_version": "proof-tool-identity/v1",
        "sha256": _bytes_sha256(contents),
        "size": len(contents),
        "mode": f"{stat.S_IMODE(identity.mode):04o}",
        "symlink_chain_sha256": symlink_payload,
        "shebang_interpreter_sha256": shebang_sha256,
    }
    return resolved, identity, public


def _token_map(
    *,
    repository: Path,
    home: Path,
    temporary: Path,
    hooks: Path,
    empty_config: Path,
    input_runtime: Sequence[_InputRuntime],
) -> tuple[tuple[str, str], ...]:
    pairs = [
        (str(repository), "$WORKSPACE"),
        (str(home), "$WORKSPACE_HOME"),
        (str(temporary), "$WORKSPACE_TMP"),
        (str(hooks), "$WORKSPACE_HOOKS"),
        (str(empty_config), "$WORKSPACE_GIT_CONFIG"),
    ]
    for item in input_runtime:
        if item.destination is not None:
            pairs.append((str(item.destination), f"$INPUT:{item.input_id}"))
    return tuple(sorted(set(pairs), key=lambda item: len(item[0]), reverse=True))


def _spawn_vector_sha256(
    argv: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    *,
    token_map: tuple[tuple[str, str], ...],
) -> str:
    return proof_document_sha256(
        {
            "contract_version": "proof-spawn-vector/v1",
            "argv": [_logicalize(value, token_map) for value in argv],
            "cwd": _logicalize(str(cwd), token_map),
            "env": sorted(_logicalize_environment(environment, token_map).items()),
            "shell": False,
        }
    )


def _logicalize_environment(
    environment: Mapping[str, str],
    token_map: tuple[tuple[str, str], ...],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in environment.items():
        if name in {"PATH", "PYTHONPATH"}:
            result[name] = os.pathsep.join(
                _logicalize(item, token_map) for item in value.split(os.pathsep)
            )
        else:
            result[name] = _logicalize(value, token_map)
    return result


def _logicalize(value: str, token_map: tuple[tuple[str, str], ...]) -> str:
    matches: list[tuple[int, str]] = []
    for raw_path, token in token_map:
        if value == raw_path:
            matches.append((len(raw_path), token))
        elif value.startswith(raw_path + os.sep):
            matches.append(
                (
                    len(raw_path),
                    token + "/" + value[len(raw_path + os.sep) :].replace(os.sep, "/"),
                )
            )
    if not matches:
        return value
    best_length = max(length for length, _ in matches)
    best = {logical for length, logical in matches if length == best_length}
    if len(best) != 1:
        raise _error(
            "proof_environment_injection_forbidden",
            "An operational path has an ambiguous logical identity.",
        )
    return best.pop()


def _secret_shaped(name: str) -> bool:
    upper = name.upper()
    return any(fragment in upper for fragment in _SECRET_FRAGMENTS)


def _assert_repository_sealed(
    root: Path,
    runner: GitRunner,
    *,
    candidate_commit: str,
    candidate_tree: str,
    config_sha256: str,
    object_format: str,
    tracked_replacement_paths: frozenset[str],
) -> None:
    head = _git_text(root, runner, "rev-parse", "--verify", "HEAD^{commit}")
    tree = _git_text(root, runner, "rev-parse", "--verify", "HEAD^{tree}")
    if head != candidate_commit or tree != candidate_tree:
        raise _error(
            "proof_checkout_tree_mismatch",
            "The prepared proof workspace HEAD or tree changed.",
        )
    if _git_returncode(root, runner, "symbolic-ref", "-q", "HEAD") == 0:
        raise _error("proof_checkout_not_detached", "The prepared proof workspace is no longer detached.")
    _assert_no_remotes(root, runner)
    _assert_no_alternates_or_promisor(root, runner)
    if _repository_config_sha256(root, runner) != config_sha256:
        raise _error(
            "proof_git_configuration_unsafe",
            "The prepared proof workspace Git configuration changed.",
        )
    _verify_exact_tree(
        root,
        runner,
        candidate_commit=candidate_commit,
        object_format=object_format,
        excluded_materialized_paths=tracked_replacement_paths,
    )


def _assert_safe_config(root: Path, runner: GitRunner, hooks: Path) -> None:
    hook_value = _git_text(root, runner, "config", "--local", "--get", "core.hooksPath")
    if Path(hook_value).resolve() != hooks.resolve() or not Path(hook_value).is_absolute():
        raise _error(
            "proof_git_configuration_unsafe",
            "core.hooksPath is not the absolute owned empty hooks directory.",
        )
    names = _git_bytes(root, runner, "config", "--local", "--name-only", "--null", "--list")
    for raw in names.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8", errors="strict").casefold()
        if name in _GIT_UNSAFE_CONFIG_KEYS or name.startswith(_GIT_UNSAFE_CONFIG_PREFIXES):
            raise _error(
                "proof_git_configuration_unsafe",
                "The proof clone contains unsafe Git configuration.",
                key=name,
            )


def _assert_no_remotes(root: Path, runner: GitRunner) -> None:
    if _git_text(root, runner, "remote"):
        raise _error("proof_git_remote_present", "The proof clone retains a Git remote.")


def _assert_no_alternates_or_promisor(root: Path, runner: GitRunner) -> None:
    common = Path(
        _git_text(root, runner, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ).resolve()
    alternates = common / "objects/info/alternates"
    if alternates.exists() and alternates.read_bytes().strip():
        raise _error("proof_git_alternates_present", "The proof clone uses alternate objects.")
    names = _git_bytes(root, runner, "config", "--local", "--name-only", "--null", "--list")
    for raw in names.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8", errors="strict").casefold()
        if name.endswith(".promisor") or name == "extensions.partialclone":
            raise _error(
                "proof_git_alternates_present",
                "The proof clone uses promisor or partial-clone state.",
            )


def _repository_config_sha256(root: Path, runner: GitRunner) -> str:
    _assert_no_remotes(root, runner)
    raw = _git_bytes(root, runner, "config", "--local", "--null", "--list")
    return _bytes_sha256(raw)


def _reseal_materialized_inputs(
    runtime: Sequence[_InputRuntime],
    runner: GitRunner,
) -> None:
    for item in runtime:
        if item.destination is None:
            continue
        if item.kind == "directory_bundle":
            bundle, _ = _collect_directory_bundle(item.destination)
            if bundle["sha256"] != item.expected["bundle_sha256"]:
                raise _error(
                    "proof_external_input_changed_during_materialization",
                    "A materialized directory bundle changed.",
                    input_id=item.input_id,
                )
        elif item.kind == "submodule":
            head = _git_text(item.destination, runner, "rev-parse", "--verify", "HEAD^{commit}")
            tree = _git_text(item.destination, runner, "rev-parse", "--verify", "HEAD^{tree}")
            if head != item.expected["commit_oid"] or tree != item.expected["tree_oid"]:
                raise _error(
                    "proof_external_input_changed_during_materialization",
                    "A materialized submodule changed.",
                    input_id=item.input_id,
                )
            _assert_no_remotes(item.destination, runner)
            _assert_no_alternates_or_promisor(item.destination, runner)
        else:
            contents, identity = _read_regular_file(item.destination, require_single_link=True)
            if (
                _bytes_sha256(contents) != item.expected["sha256"]
                or len(contents) != item.expected["size"]
                or f"{stat.S_IMODE(identity.mode):04o}" != item.expected["mode"]
            ):
                raise _error(
                    "proof_external_input_changed_during_materialization",
                    "A materialized typed input changed.",
                    input_id=item.input_id,
                )


def _read_regular_file(
    path: Path,
    *,
    require_single_link: bool,
) -> tuple[bytes, _StatIdentity]:
    try:
        before = os.lstat(path)
    except OSError as exc:
        code = (
            "proof_external_input_unreadable"
            if isinstance(exc, PermissionError)
            else "proof_external_input_missing"
        )
        raise _error(code, "A required regular file is unavailable.") from exc
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise _error("proof_external_input_unsafe", "A typed file source must be regular and non-symlink.")
    if require_single_link and before.st_nlink != 1:
        raise _error("proof_external_input_unsafe", "A typed file source must be single-link.")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except PermissionError as exc:
        raise _error(
            "proof_external_input_unreadable",
            "A typed file source is unreadable.",
        ) from exc
    except OSError as exc:
        raise _error("proof_external_input_unsafe", "A typed file source could not be opened safely.") from exc
    try:
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = os.lstat(path)
    identities = {
        _StatIdentity.from_stat(before),
        _StatIdentity.from_stat(opened),
        _StatIdentity.from_stat(after),
        _StatIdentity.from_stat(final),
    }
    if len(identities) != 1:
        raise _error(
            "proof_external_input_changed_during_materialization",
            "A typed file source changed while its bytes were read.",
        )
    identity = identities.pop()
    return b"".join(chunks), identity


def _read_regular_file_at(directory_fd: int, name: str) -> tuple[bytes, _StatIdentity]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=directory_fd)
    try:
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _StatIdentity.from_stat(opened) != _StatIdentity.from_stat(after):
        raise _error(
            "proof_external_input_changed_during_materialization",
            "A directory bundle file changed while read.",
        )
    return b"".join(chunks), _StatIdentity.from_stat(after)


def _assert_source_unchanged(path: Path, expected: _StatIdentity) -> None:
    try:
        actual = _StatIdentity.from_stat(os.lstat(path))
    except OSError as exc:
        raise _error(
            "proof_external_input_changed_during_materialization",
            "A typed file source disappeared after copying.",
        ) from exc
    if actual != expected:
        raise _error(
            "proof_external_input_changed_during_materialization",
            "A typed file source changed after copying.",
        )


def _write_created_file(destination: Path, contents: bytes, mode: str) -> None:
    if _lexists(destination):
        raise _error(
            "proof_external_destination_conflict",
            "A typed file destination already exists.",
            destination=str(destination),
        )
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    _assert_no_symlink_parents(destination)
    parent_fd = _open_directory(destination.parent)
    try:
        _write_file_at(parent_fd, destination.name, contents, mode)
    finally:
        os.close(parent_fd)


def _replace_or_create_file(destination: Path, contents: bytes, mode: str) -> None:
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    _assert_no_symlink_parents(destination)
    parent_fd = _open_directory(destination.parent)
    try:
        if _lexists(destination):
            value = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode):
                raise _error(
                    "proof_external_destination_conflict",
                    "A materialized-file destination is not a regular candidate file.",
                )
            os.unlink(destination.name, dir_fd=parent_fd)
        _write_file_at(parent_fd, destination.name, contents, mode)
    finally:
        os.close(parent_fd)


def _write_file_at(parent_fd: int, name: str, contents: bytes, mode: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, int(mode, 8), dir_fd=parent_fd)
    try:
        offset = 0
        while offset < len(contents):
            offset += os.write(descriptor, contents[offset:])
        os.fchmod(descriptor, int(mode, 8))
        os.fsync(descriptor)
        final = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if not stat.S_ISREG(final.st_mode) or final.st_nlink != 1:
        raise _error(
            "proof_external_input_changed_during_materialization",
            "A typed input destination changed during creation.",
        )


def _assert_no_symlink_parents(path: Path) -> None:
    current = path.parent
    while current != current.parent:
        if current.is_symlink():
            raise _error(
                "proof_external_destination_conflict",
                "A typed input destination traverses a symlinked parent.",
                path=str(path),
            )
        current = current.parent


def _stat_identity_no_follow(path: Path) -> _StatIdentity:
    return _StatIdentity.from_stat(os.stat(path, follow_symlinks=False))


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags)


def _open_directory_at(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(name, flags, dir_fd=parent_fd)


def _walk_destination_parent(root_fd: int, parts: Sequence[str], *, create: bool) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                next_fd = _open_directory_at(current, part)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o755, dir_fd=current)
                next_fd = _open_directory_at(current, part)
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        os.close(current)
        raise


def _remove_directory_contents(directory_fd: int) -> None:
    for name in os.listdir(directory_fd):
        value = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode):
            child_fd = _open_directory_at(directory_fd, name)
            try:
                _remove_directory_contents(child_fd)
            finally:
                os.close(child_fd)
            os.rmdir(name, dir_fd=directory_fd)
        else:
            os.unlink(name, dir_fd=directory_fd)


def _git_blob_oid(contents: bytes, object_format: str) -> str:
    payload = f"blob {len(contents)}\0".encode("ascii") + contents
    if object_format == "sha1":
        return hashlib.sha1(payload, usedforsecurity=False).hexdigest()
    return hashlib.sha256(payload).hexdigest()


def _bytes_sha256(contents: bytes) -> str:
    return "sha256:" + hashlib.sha256(contents).hexdigest()


def _safe_relative(value: str) -> bool:
    if not value or "\0" in value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _git_text(
    root: Path,
    runner: GitRunner,
    *args: str,
    code: str = "proof_git_configuration_unsafe",
) -> str:
    return _git_bytes(root, runner, *args, code=code).decode(
        "utf-8",
        errors="surrogateescape",
    ).strip()


def _git_bytes(
    root: Path,
    runner: GitRunner,
    *args: str,
    code: str = "proof_git_configuration_unsafe",
) -> bytes:
    completed = runner.run(root, *args)
    if completed.returncode != 0:
        raise _error(
            code,
            "A sealed Git command failed.",
            argv=["git", *args],
            exit_code=completed.returncode,
            stderr=completed.stderr.decode("utf-8", errors="replace").strip(),
        )
    return completed.stdout


def _git_returncode(root: Path, runner: GitRunner, *args: str) -> int:
    completed = runner.run(root, *args)
    if completed.returncode not in {0, 1}:
        raise _error(
            "proof_git_configuration_unsafe",
            "A sealed Git predicate failed.",
            argv=["git", *args],
            exit_code=completed.returncode,
            stderr=completed.stderr.decode("utf-8", errors="replace").strip(),
        )
    return completed.returncode


def _error(code: str, message: str, **details: Any) -> ProofWorkspaceError:
    return ProofWorkspaceError(message=message, code=code, details=details)
