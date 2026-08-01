from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from pcl.authority_surface import (
    AuthoritySurfaceError,
    canonical_git_diff,
    derive_trusted_base,
    derive_trusted_base_for_task,
    load_task_start_events,
    resolve_authority_surface,
)
from pcl.contracts.authority_surface import (
    AUTHORITY_CANARY_CONTRACT_VERSION,
    AUTHORITY_CATALOG_CONTRACT_VERSION,
    AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION,
    BOOTSTRAP_AUTHORITY_PROFILE_CONTRACT_VERSION,
    authority_document_sha256,
    authority_surface_resolution_schema,
    bootstrap_authority_profile_schema,
    load_bootstrap_authority_profile,
    merge_authority_canaries,
    merge_authority_catalogs,
    validate_authority_surface_resolution,
    validate_bootstrap_authority_profile,
)
from pcl.project_config import trusted_integration_head_oid
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.start import start_work


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "authority_surface"
    / "bootstrap-authority-profile-v0.json"
)
FROZEN_SHA = FIXTURE.with_suffix(".sha256")
SHA = "sha256:" + "a" * 64
BASE = "1" * 40
CANDIDATE = "2" * 40
TREE = "3" * 40


def _empty_catalog(catalog_id: str) -> dict:
    return {
        "contract_version": AUTHORITY_CATALOG_CONTRACT_VERSION,
        "catalog_id": catalog_id,
        "rules": [],
    }


def _catalog(catalog_id: str, *, risk: str, rule_id: str = "authority") -> dict:
    return {
        "contract_version": AUTHORITY_CATALOG_CONTRACT_VERSION,
        "catalog_id": catalog_id,
        "rules": [
            {
                "id": rule_id,
                "minimum_risk": risk,
                "patterns": ["src/pcl/task_accept.py"],
            }
        ],
    }


def _empty_canary() -> dict:
    return {"contract_version": AUTHORITY_CANARY_CONTRACT_VERSION, "items": []}


def _base_resolution(*, status: str = "resolved") -> dict:
    if status == "resolved":
        return {
            "status": "resolved",
            "derivation": "task_start_event",
            "commit_oid": BASE,
            "source_ref": "EV-START",
            "ancestry_result": "ancestor",
            "reuse_allowed": True,
            "reason_codes": ["task_start_ancestor"],
        }
    if status == "base_unknown":
        return {
            "status": status,
            "derivation": "base_unknown",
            "commit_oid": None,
            "source_ref": None,
            "ancestry_result": "unknown",
            "reuse_allowed": False,
            "reason_codes": [status],
        }
    return {
        "status": "no_candidate_change",
        "derivation": "task_start_event",
        "commit_oid": CANDIDATE,
        "source_ref": "EV-START",
        "ancestry_result": "same_as_candidate",
        "reuse_allowed": False,
        "reason_codes": ["no_candidate_change"],
    }


def _resolution(
    *,
    path: str = "src/pcl/task_accept.py",
    existing_route_risk: str = "R0",
    existing_adaptive_depth: str = "basic",
    trusted_base_floor: str = "R0",
    reviewer_risk: str = "R0",
    reviewer_depth: str = "basic",
    base_catalog: dict | None = None,
    candidate_catalog: dict | None = None,
    base_canary: dict | None = None,
    candidate_canary: dict | None = None,
    base_resolution: dict | None = None,
    packaged_catalog: dict | None = None,
    bootstrap_profile: dict | None = None,
    old_mode: str = "100644",
    new_mode: str = "100644",
) -> dict:
    profile = bootstrap_profile or load_bootstrap_authority_profile(FIXTURE)
    entries = [
        {
            "old_mode": old_mode,
            "new_mode": new_mode,
            "old_oid": "4" * 40,
            "new_oid": "5" * 40,
            "status": "M",
            "path": path,
        }
    ]
    diff_sha = "sha256:" + hashlib.sha256(
        json.dumps(entries, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return resolve_authority_surface(
        target={"type": "task", "id": "T-0001"},
        candidate={"commit_oid": CANDIDATE, "tree_oid": TREE},
        base_resolution=base_resolution or _base_resolution(),
        actual_diff={
            "sha256": diff_sha,
            "entries": entries,
        },
        existing_route_risk=existing_route_risk,
        existing_adaptive_depth=existing_adaptive_depth,
        trusted_base_floor=trusted_base_floor,
        reviewer_escalation={
            "risk_level": reviewer_risk,
            "verification_depth": reviewer_depth,
        },
        packaged_catalog=(
            packaged_catalog
            if packaged_catalog is not None
            else profile["authority_catalog"]
        ),
        base_catalog=base_catalog or _empty_catalog("base"),
        candidate_catalog=candidate_catalog or _empty_catalog("candidate"),
        base_canary=base_canary or _empty_canary(),
        candidate_canary=candidate_canary or _empty_canary(),
        resolver={
            "version": "p1-c-c1",
            "sha256": SHA,
            "source": "external_bootstrap",
        },
        bootstrap_profile=profile,
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT
    ).strip()


def _commit(root: Path, name: str, content: str) -> str:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(content, encoding="utf-8")
    _git(root, "add", name)
    _git(root, "commit", "-q", "-m", f"write {name}")
    return _git(root, "rev-parse", "HEAD")


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    base = _commit(root, "README.md", "base\n")
    candidate = _commit(root, "src/pcl/task_accept.py", "candidate\n")
    return root, base, candidate


def _event(event_id: str, revision: str | None) -> dict:
    receipt = {"repository_revision": revision} if revision is not None else {}
    return {
        "id": event_id,
        "payload_json": json.dumps({"receipt": receipt}),
    }


def test_external_bootstrap_profile_is_strict_frozen_and_non_self_certifying() -> None:
    profile = load_bootstrap_authority_profile(FIXTURE)

    assert profile["contract_version"] == BOOTSTRAP_AUTHORITY_PROFILE_CONTRACT_VERSION
    assert profile["resolver_contract_version"] == AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION
    assert validate_bootstrap_authority_profile(profile).ok
    assert authority_document_sha256(profile) == FROZEN_SHA.read_text(encoding="utf-8").strip()
    assert profile["verification_boundary"] == {
        "exact_candidate_full_regression_required": True,
        "fixed_hash_independent_review_required": True,
        "self_certification_allowed": False,
    }

    candidate_runtime = json.loads(json.dumps(profile))
    candidate_runtime["verification_boundary"]["self_certification_allowed"] = True
    validation = validate_bootstrap_authority_profile(candidate_runtime)
    assert not validation.ok
    assert any("self_certification_allowed" in error for error in validation.errors)
    assert authority_surface_resolution_schema()["$id"].endswith(
        "authority-surface-resolution-v1.schema.json"
    )
    assert bootstrap_authority_profile_schema()["$id"].endswith(
        "bootstrap-authority-profile-v0.schema.json"
    )
    test_bytes = Path(__file__).read_bytes()
    test_blob_oid = hashlib.sha1(
        f"blob {len(test_bytes)}\0".encode() + test_bytes,
        usedforsecurity=False,
    ).hexdigest()
    assert {
        tuple(item["referenced_blob_oids"])
        for item in profile["canary_contract"]["items"]
    } == {(test_blob_oid,)}


def test_resolution_contract_binds_all_c1_hashes_and_has_no_terminal_authority() -> None:
    resolution = _resolution(path="src/pcl/task_accept.py")

    assert validate_authority_surface_resolution(resolution).ok
    assert resolution["contract_version"] == AUTHORITY_SURFACE_RESOLUTION_CONTRACT_VERSION
    assert resolution["actual_diff"]["sha256"].startswith("sha256:")
    assert set(resolution["catalog"]) >= {
        "packaged_minimum_sha256",
        "base_sha256",
        "candidate_sha256",
        "union_sha256",
        "diff_sha256",
    }
    assert set(resolution["canary"]) >= {
        "packaged_minimum_sha256",
        "base_sha256",
        "candidate_sha256",
        "union_sha256",
        "diff_sha256",
    }
    assert resolution["resolver"]["sha256"] == SHA
    assert resolution["bootstrap_profile"]["sha256"].startswith("sha256:")
    assert resolution["terminal_authority"] is False
    assert resolution["mandatory_evidence"] is False


def test_risk_and_depth_are_composed_by_maximum_rank() -> None:
    resolution = _resolution(
        existing_route_risk="R3",
        existing_adaptive_depth="human",
        trusted_base_floor="R2",
        reviewer_risk="R0",
        reviewer_depth="basic",
    )

    assert resolution["effective"]["risk_level"] == "R3"
    assert resolution["effective"]["verification_depth"] == "human"
    assert resolution["effective"]["human_gate_required"] is True
    assert resolution["inputs"]["existing_route_risk"] == "R3"
    assert resolution["inputs"]["reviewer_escalation"]["risk_level"] == "R0"


def test_r3_requires_human_gate_with_basic_depth() -> None:
    resolution = _resolution(
        path="docs/operator-guide.md",
        existing_route_risk="R3",
        existing_adaptive_depth="basic",
    )

    assert resolution["effective"]["risk_level"] == "R3"
    assert resolution["effective"]["verification_depth"] == "independent"
    assert resolution["effective"]["human_gate_required"] is True


def test_r2_human_depth_disables_reuse() -> None:
    resolution = _resolution(
        path="docs/operator-guide.md",
        existing_route_risk="R2",
        existing_adaptive_depth="human",
    )

    assert resolution["effective"]["risk_level"] == "R2"
    assert resolution["effective"]["verification_depth"] == "human"
    assert resolution["effective"]["human_gate_required"] is True
    assert resolution["effective"]["reuse_allowed"] is False


def test_r4_preserves_human_depth_gate_and_disables_reuse() -> None:
    resolution = _resolution(
        existing_route_risk="R4",
        existing_adaptive_depth="basic",
    )

    assert resolution["effective"]["risk_level"] == "R4"
    assert resolution["effective"]["verification_depth"] == "human"
    assert resolution["effective"]["human_gate_required"] is True
    assert resolution["effective"]["reuse_allowed"] is False


@pytest.mark.parametrize(
    ("source", "kwargs"),
    [
        ("existing_route", {"existing_route_risk": "R3"}),
        ("trusted_base", {"trusted_base_floor": "R3"}),
        ("base_catalog", {"base_catalog": _catalog("base", risk="R3")}),
        ("candidate_catalog", {"candidate_catalog": _catalog("candidate", risk="R3")}),
        ("reviewer", {"reviewer_risk": "R3"}),
    ],
)
def test_removing_any_risk_source_would_underclassify(source: str, kwargs: dict) -> None:
    resolution = _resolution(**kwargs)

    assert resolution["effective"]["risk_level"] == "R3", source


def test_candidate_deletion_and_weakening_cannot_remove_base_requirement() -> None:
    base = _catalog("base", risk="R3")
    deleted = _empty_catalog("candidate")
    weakened = _catalog("candidate", risk="R1")

    deleted_result = _resolution(base_catalog=base, candidate_catalog=deleted)
    weakened_result = _resolution(base_catalog=base, candidate_catalog=weakened)
    union = merge_authority_catalogs(
        _empty_catalog("packaged"), base, weakened
    )

    assert deleted_result["effective"]["risk_level"] == "R3"
    assert weakened_result["effective"]["risk_level"] == "R3"
    assert union["rules"][0]["minimum_risk"] == "R3"
    assert deleted_result["catalog"]["base_sha256"] != deleted_result["catalog"]["candidate_sha256"]
    assert deleted_result["catalog"]["diff_sha256"].startswith("sha256:")


def test_candidate_may_add_and_escalate_catalog_requirements() -> None:
    result = _resolution(
        base_catalog=_catalog("base", risk="R2"),
        candidate_catalog=_catalog("candidate", risk="R3"),
    )

    assert result["effective"]["risk_level"] == "R3"
    assert result["inputs"]["candidate_catalog_floor"] == "R3"


def test_candidate_canary_deletion_is_retained_and_conflicting_narrowing_fails() -> None:
    profile = load_bootstrap_authority_profile(FIXTURE)
    base = profile["canary_contract"]
    effective = merge_authority_canaries(base, _empty_canary())

    assert effective == base

    narrowed = json.loads(json.dumps(base))
    narrowed["items"][0]["selectors"] = narrowed["items"][0]["selectors"][:1]
    with pytest.raises(AuthoritySurfaceError) as exc_info:
        _resolution(base_canary=base, candidate_canary=narrowed)
    assert exc_info.value.code == "authority_canary_conflict"


@pytest.mark.parametrize(
    ("field", "replacement", "expected_code"),
    [
        (
            "command",
            ["python", "-m", "pytest", "-q", "tests/test_authority_surface.py", "--strict"],
            "authority_canary_conflict",
        ),
        ("required_outcome", "fail", "authority_canary_invalid"),
        (
            "supported_platform_conditions",
            ["python>=3.11"],
            "authority_canary_conflict",
        ),
    ],
)
def test_candidate_canary_preserves_command_outcome_and_platform(
    field: str,
    replacement: object,
    expected_code: str,
) -> None:
    profile = load_bootstrap_authority_profile(FIXTURE)
    candidate = json.loads(json.dumps(profile["canary_contract"]))
    candidate["items"][0][field] = replacement

    with pytest.raises(AuthoritySurfaceError) as exc_info:
        _resolution(
            base_canary=profile["canary_contract"],
            candidate_canary=candidate,
        )

    assert exc_info.value.code == expected_code
    assert field in str(exc_info.value.details)


def test_packaged_catalog_must_match_bootstrap_profile() -> None:
    profile = load_bootstrap_authority_profile(FIXTURE)
    packaged = json.loads(json.dumps(profile["authority_catalog"]))
    packaged["rules"][0]["minimum_risk"] = "R4"

    with pytest.raises(AuthoritySurfaceError) as exc_info:
        _resolution(packaged_catalog=packaged, bootstrap_profile=profile)

    assert exc_info.value.code == "bootstrap_authority_catalog_mismatch"


@pytest.mark.parametrize(
    ("path", "minimum"),
    [
        ("src/pcl/authority_surface.py", "R2"),
        ("docs/authority-surface-resolution-v1.md", "R2"),
        ("src/pcl/contracts/authority-catalog.json", "R2"),
        ("src/pcl/adaptive_policy.py", "R2"),
        ("tests/authority-canary.json", "R2"),
        ("src/pcl/proof_key.py", "R2"),
        ("src/pcl/proof_anchor.py", "R2"),
        ("src/pcl/terminal_readiness.py", "R2"),
        ("src/pcl/evidence.py", "R2"),
        ("src/pcl/check_result_reuse.py", "R2"),
        ("src/pcl/finish_recovery.py", "R2"),
        ("src/pcl/mutation_tail.py", "R2"),
        ("src/pcl/locks.py", "R2"),
        ("src/pcl/receipt_show.py", "R2"),
        ("src/pcl/task_accept.py", "R2"),
        ("src/pcl/db/schema.sql", "R3"),
        ("src/pcl/db/migrations/009_future.sql", "R3"),
        ("pyproject.toml", "R3"),
        ("requirements.txt", "R3"),
        ("src/pcl/permissions.py", "R3"),
        ("src/pcl/guards.py", "R3"),
        ("src/pcl/db.py", "R3"),
        ("src/pcl/outbox.py", "R3"),
        ("src/pcl/strict_evidence.py", "R3"),
    ],
)
def test_frozen_catalog_applies_named_authority_floors(path: str, minimum: str) -> None:
    resolution = _resolution(path=path)

    assert resolution["effective"]["risk_level"] in {minimum, "R4"}
    assert int(resolution["effective"]["risk_level"][1]) >= int(minimum[1])


def test_unknown_executable_path_is_never_silent_r0_or_r1() -> None:
    resolution = _resolution(path="tools/previously-unknown-runtime.py")

    assert resolution["effective"]["risk_level"] == "R2"
    assert "unknown_executable_path" in resolution["effective"]["reason_codes"]


def test_candidate_cannot_classify_unknown_executable_as_non_executable_r0() -> None:
    candidate = {
        "contract_version": AUTHORITY_CATALOG_CONTRACT_VERSION,
        "catalog_id": "candidate",
        "rules": [
            {
                "id": "candidate-silent-runtime",
                "minimum_risk": "R0",
                "path_class": "non_executable",
                "patterns": ["tools/*"],
            }
        ],
    }

    resolution = _resolution(
        path="tools/previously-unknown-runtime.py",
        candidate_catalog=candidate,
    )

    assert resolution["effective"]["risk_level"] == "R2"
    assert "unknown_executable_path" in resolution["effective"]["reason_codes"]


def test_packaged_floor_survives_candidate_r0_non_executable_rule() -> None:
    candidate = {
        "contract_version": AUTHORITY_CATALOG_CONTRACT_VERSION,
        "catalog_id": "candidate",
        "rules": [
            {
                "id": "candidate-silent-artifact",
                "minimum_risk": "R0",
                "path_class": "non_executable",
                "patterns": ["artifacts/opaque.bin"],
            }
        ],
    }

    resolution = _resolution(
        path="artifacts/opaque.bin",
        candidate_catalog=candidate,
    )

    assert resolution["inputs"]["packaged_catalog_floor"] == "R2"
    assert resolution["inputs"]["candidate_catalog_floor"] == "R0"
    assert resolution["effective"]["risk_level"] == "R2"


def test_shared_rule_id_unions_patterns_before_risk_classification() -> None:
    base = {
        "contract_version": AUTHORITY_CATALOG_CONTRACT_VERSION,
        "catalog_id": "base",
        "rules": [
            {
                "id": "shared-authority",
                "minimum_risk": "R3",
                "patterns": ["docs/trusted-only.md"],
            }
        ],
    }
    candidate = {
        "contract_version": AUTHORITY_CATALOG_CONTRACT_VERSION,
        "catalog_id": "candidate",
        "rules": [
            {
                "id": "shared-authority",
                "minimum_risk": "R0",
                "patterns": ["docs/operator-guide.md"],
            }
        ],
    }

    union = merge_authority_catalogs(base, candidate)
    resolution = _resolution(
        path="docs/operator-guide.md",
        base_catalog=base,
        candidate_catalog=candidate,
    )

    assert union["rules"] == [
        {
            "id": "shared-authority",
            "minimum_risk": "R3",
            "patterns": ["docs/operator-guide.md", "docs/trusted-only.md"],
        }
    ]
    assert resolution["inputs"]["base_catalog_floor"] == "R0"
    assert resolution["inputs"]["candidate_catalog_floor"] == "R0"
    assert resolution["effective"]["risk_level"] == "R3"
    assert resolution["effective"]["human_gate_required"] is True


def test_executable_mode_cannot_hide_below_documentation_floor() -> None:
    resolution = _resolution(
        path="docs/operator-guide.md",
        old_mode="100644",
        new_mode="100755",
    )

    assert resolution["effective"]["risk_level"] == "R2"
    assert "non_executable_classification_conflict" in resolution["effective"]["reason_codes"]


def test_only_explicit_documentation_paths_may_remain_below_r2() -> None:
    documented = _resolution(path="docs/operator-guide.md")
    unknown_binary = _resolution(path="artifacts/opaque.bin")

    assert documented["effective"]["risk_level"] == "R0"
    assert unknown_binary["effective"]["risk_level"] == "R2"
    assert "unknown_path" in unknown_binary["effective"]["reason_codes"]


@pytest.mark.parametrize("status", ["base_unknown", "no_candidate_change"])
def test_base_state_floor_isolated_on_documentation_diff(status: str) -> None:
    resolution = _resolution(
        path="docs/operator-guide.md",
        base_resolution=_base_resolution(status=status),
    )

    assert resolution["inputs"]["base_state_floor"] == "R2"
    assert resolution["inputs"]["packaged_catalog_floor"] == "R0"
    assert resolution["effective"]["risk_level"] == "R2"
    assert resolution["effective"]["reuse_allowed"] is False


@pytest.mark.parametrize(
    "path",
    ["docs/operator-guide.md", "src/pcl/task_accept.py"],
)
def test_resolved_base_equal_to_candidate_is_rejected(path: str) -> None:
    forged = _base_resolution()
    forged["commit_oid"] = CANDIDATE

    with pytest.raises(AuthoritySurfaceError) as exc_info:
        _resolution(path=path, base_resolution=forged)

    assert exc_info.value.code == "authority_base_no_candidate_change_mismatch"


def test_no_candidate_change_base_must_equal_candidate() -> None:
    forged = _base_resolution(status="no_candidate_change")
    forged["commit_oid"] = BASE

    with pytest.raises(AuthoritySurfaceError) as exc_info:
        _resolution(path="docs/operator-guide.md", base_resolution=forged)

    assert exc_info.value.code == "authority_base_no_candidate_change_mismatch"


def test_internally_inconsistent_base_resolution_is_rejected() -> None:
    forged = _base_resolution(status="base_unknown")
    forged["reuse_allowed"] = True

    with pytest.raises(AuthoritySurfaceError) as exc_info:
        _resolution(base_resolution=forged)
    assert exc_info.value.code == "authority_base_invalid"


def test_terminal_authority_literal_is_validated() -> None:
    resolution = _resolution(path="docs/operator-guide.md")
    resolution["terminal_authority"] = True

    validation = validate_authority_surface_resolution(resolution)

    assert not validation.ok
    assert "$.terminal_authority: must equal False" in validation.errors


def test_candidate_runtime_cannot_self_certify() -> None:
    profile = load_bootstrap_authority_profile(FIXTURE)
    with pytest.raises(AuthoritySurfaceError) as exc_info:
        resolve_authority_surface(
            target={"type": "task", "id": "T-0001"},
            candidate={"commit_oid": CANDIDATE, "tree_oid": TREE},
            base_resolution=_base_resolution(),
            actual_diff={
                "sha256": "sha256:" + hashlib.sha256(b"[]").hexdigest(),
                "entries": [],
            },
            existing_route_risk="R0",
            existing_adaptive_depth="basic",
            trusted_base_floor="R0",
            reviewer_escalation={"risk_level": "R0", "verification_depth": "basic"},
            packaged_catalog=profile["authority_catalog"],
            base_catalog=_empty_catalog("base"),
            candidate_catalog=_empty_catalog("candidate"),
            base_canary=_empty_canary(),
            candidate_canary=_empty_canary(),
            resolver={"version": "p1-c-c1", "sha256": SHA, "source": "candidate"},
            bootstrap_profile=profile,
        )
    assert exc_info.value.code == "authority_resolver_untrusted"


def test_actual_diff_digest_mismatch_fails_closed() -> None:
    profile = load_bootstrap_authority_profile(FIXTURE)
    with pytest.raises(AuthoritySurfaceError) as exc_info:
        resolve_authority_surface(
            target={"type": "task", "id": "T-0001"},
            candidate={"commit_oid": CANDIDATE, "tree_oid": TREE},
            base_resolution=_base_resolution(),
            actual_diff={"sha256": SHA, "entries": []},
            existing_route_risk="R0",
            existing_adaptive_depth="basic",
            trusted_base_floor="R0",
            reviewer_escalation={"risk_level": "R0", "verification_depth": "basic"},
            packaged_catalog=profile["authority_catalog"],
            base_catalog=_empty_catalog("base"),
            candidate_catalog=_empty_catalog("candidate"),
            base_canary=_empty_canary(),
            candidate_canary=_empty_canary(),
            resolver={"version": "p1-c-c1", "sha256": SHA, "source": "external_bootstrap"},
            bootstrap_profile=profile,
        )
    assert exc_info.value.code == "authority_diff_digest_mismatch"


def test_trusted_base_precedence_and_fail_closed_states(tmp_path: Path) -> None:
    root, base, candidate = _repository(tmp_path)

    task_start = derive_trusted_base(
        root,
        candidate_commit_oid=candidate,
        work_started_events=[_event("EV-START", base)],
        trusted_integration_head_oid=base,
    )
    assert task_start["derivation"] == "task_start_event"
    assert task_start["commit_oid"] == base
    assert task_start["source_ref"] == "EV-START"

    unchanged = derive_trusted_base(
        root,
        candidate_commit_oid=candidate,
        work_started_events=[_event("EV-SAME", candidate)],
        trusted_integration_head_oid=base,
    )
    assert unchanged["status"] == "no_candidate_change"
    assert unchanged["reuse_allowed"] is False

    ambiguous = derive_trusted_base(
        root,
        candidate_commit_oid=candidate,
        work_started_events=[_event("EV-A", base), _event("EV-B", candidate)],
        trusted_integration_head_oid=base,
    )
    assert ambiguous["status"] == "base_unknown"
    assert "task_start_ambiguous" in ambiguous["reason_codes"]

    _git(root, "checkout", "-q", "--orphan", "unrelated")
    (root / "README.md").unlink()
    unrelated = _commit(root, "other.txt", "unrelated\n")
    _git(root, "checkout", "-q", candidate)
    nonancestor = derive_trusted_base(
        root,
        candidate_commit_oid=candidate,
        work_started_events=[_event("EV-BAD", unrelated)],
        trusted_integration_head_oid=base,
    )
    assert nonancestor["status"] == "base_unknown"
    assert "task_start_nonancestor" in nonancestor["reason_codes"]


def test_integration_head_fallback_and_caller_base_assertion(tmp_path: Path) -> None:
    root, base, candidate = _repository(tmp_path)

    fallback = derive_trusted_base(
        root,
        candidate_commit_oid=candidate,
        work_started_events=[],
        trusted_integration_head_oid=base,
        caller_base_oid=base,
    )
    assert fallback["status"] == "resolved"
    assert fallback["derivation"] == "integration_merge_base"
    assert fallback["commit_oid"] == base

    with pytest.raises(AuthoritySurfaceError) as exc_info:
        derive_trusted_base(
            root,
            candidate_commit_oid=candidate,
            work_started_events=[],
            trusted_integration_head_oid=base,
            caller_base_oid=candidate,
        )
    assert exc_info.value.code == "authority_base_assertion_mismatch"


def test_missing_invalid_and_ambiguous_base_provenance_fail_closed(tmp_path: Path) -> None:
    root, _, candidate = _repository(tmp_path)

    missing = derive_trusted_base(
        root,
        candidate_commit_oid=candidate,
        work_started_events=[],
        trusted_integration_head_oid=None,
    )
    invalid = derive_trusted_base(
        root,
        candidate_commit_oid=candidate,
        work_started_events=[_event("EV-MISSING", None)],
        trusted_integration_head_oid=None,
    )

    assert missing["status"] == "base_unknown"
    assert invalid["status"] == "base_unknown"
    assert missing["reuse_allowed"] is False
    assert invalid["reuse_allowed"] is False


def test_task_start_event_loading_is_unbounded_and_target_scoped() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE events (sequence INTEGER, id TEXT, event_type TEXT, "
        "entity_type TEXT, entity_id TEXT, payload_json TEXT)"
    )
    for index in range(130):
        conn.execute(
            "INSERT INTO events VALUES (?, ?, 'work_started', 'task', 'T-0001', ?)",
            (index + 1, f"EV-{index:04d}", json.dumps({"receipt": {"repository_revision": BASE}})),
        )
    conn.execute(
        "INSERT INTO events VALUES (131, 'EV-OTHER', 'work_started', 'task', 'T-0002', ?)",
        (json.dumps({"receipt": {"repository_revision": CANDIDATE}}),),
    )

    events = load_task_start_events(conn, "T-0001")

    assert len(events) == 130
    assert events[0]["id"] == "EV-0000"
    assert events[-1]["id"] == "EV-0129"


def test_project_trusted_base_wrapper_reads_authoritative_task_event(tmp_path: Path) -> None:
    root, _, started_at = _repository(tmp_path)
    paths = resolve_paths(root)
    init_project(paths)
    started = start_work(paths, intent="Resolve C1 base")
    task_id = str(started["result"]["created_ids"]["task"])
    assert started["result"]["receipt"]["repository_revision"] == started_at
    candidate = _commit(root, "src/pcl/authority_surface.py", "candidate\n")

    derived = derive_trusted_base_for_task(
        paths,
        task_id=task_id,
        candidate_commit_oid=candidate,
    )

    assert derived["status"] == "resolved"
    assert derived["derivation"] == "task_start_event"
    assert derived["commit_oid"] == started_at


def test_canonical_git_diff_binds_modes_blobs_status_and_paths(tmp_path: Path) -> None:
    root, base, candidate = _repository(tmp_path)

    diff = canonical_git_diff(root, base_commit_oid=base, candidate_commit_oid=candidate)

    assert diff["entries"] == [
        {
            "old_mode": "000000",
            "new_mode": "100644",
            "old_oid": "0" * 40,
            "new_oid": _git(root, "rev-parse", f"{candidate}:src/pcl/task_accept.py"),
            "status": "A",
            "path": "src/pcl/task_accept.py",
        }
    ]
    canonical = json.dumps(diff["entries"], separators=(",", ":"), sort_keys=True).encode()
    assert diff["sha256"] == "sha256:" + hashlib.sha256(canonical).hexdigest()


def test_trusted_integration_head_config_is_optional_strict_and_flat(tmp_path: Path) -> None:
    assert trusted_integration_head_oid(tmp_path) is None

    (tmp_path / "pcl.yaml").write_text(
        "authority:\n  trusted_integration_head_oid: '" + BASE + "'\n",
        encoding="utf-8",
    )
    assert trusted_integration_head_oid(tmp_path) == BASE

    (tmp_path / "pcl.yaml").write_text(
        "authority:\n  trusted_integration_head_oid: main\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception) as exc_info:
        trusted_integration_head_oid(tmp_path)
    assert "full Git commit OID" in str(exc_info.value)
