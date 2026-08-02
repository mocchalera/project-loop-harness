from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass, replace
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
from typing import Any

import pytest

import pcl.proof_execution as proof_execution_module
import test_proof_workspace as c2
from pcl.contracts.proof_workspace import proof_document_sha256
from pcl.db import connect, initialize_database
from pcl.evidence import insert_evidence_link, record_adhoc_evidence
from pcl.outbox import canonical_event_bytes, canonical_event_record
from pcl.paths import ProjectPaths
from pcl.proof_execution import (
    AuthorityInputSnapshot,
    CurrentProofSnapshot,
    StreamAccumulator,
    aggregate_verdict,
    capture_current_proof,
    capture_current_proof_in_snapshot,
    derive_current_proof,
    execute_proof_workspace,
)
from pcl.proof_workspace import ProofWorkspaceError, prepare_proof_workspace


@dataclass
class _Case:
    root: Path
    base: str
    candidate: str
    resolution: dict[str, Any]
    bootstrap: dict[str, Any]
    profile: dict[str, Any]
    spec: dict[str, Any]
    authority: AuthorityInputSnapshot


def _case(
    tmp_path: Path,
    *,
    argv: list[str] | None = None,
    timeout_seconds: int = 10,
    max_output_bytes: int = 65_536,
    checks: int = 1,
    authority_status: str = "resolved",
) -> _Case:
    tmp_path.mkdir(parents=True, exist_ok=True)
    root, base, candidate = c2._repository(tmp_path)
    resolution, bootstrap = c2._authority(
        root,
        base,
        candidate,
        status=authority_status,
    )
    profile = c2._profile(argv=argv)
    profile["checks"][0]["timeout_seconds"] = timeout_seconds
    profile["checks"][0]["max_output_bytes"] = max_output_bytes
    for index in range(1, checks):
        duplicate = deepcopy(profile["checks"][0])
        duplicate["check_id"] = f"check-{index}"
        duplicate["role"] = f"role_{index}"
        profile["checks"].append(duplicate)
    spec = c2._spec(resolution, bootstrap, profile)
    authority = AuthorityInputSnapshot(
        target=dict(resolution["target"]),
        candidate=dict(resolution["candidate"]),
        base_resolution=c2._base(base, candidate, status=authority_status),
        actual_diff=dict(resolution["actual_diff"]),
        existing_route_risk="R0",
        existing_adaptive_depth="basic",
        trusted_base_floor="R0",
        reviewer_escalation={"risk_level": "R0", "verification_depth": "basic"},
        packaged_catalog=bootstrap["authority_catalog"],
        base_catalog=c2._empty_catalog("base"),
        candidate_catalog=c2._empty_catalog("candidate"),
        base_canary=c2._empty_canary(),
        candidate_canary=c2._empty_canary(),
        resolver={
            "version": "p1-c-c1",
            "sha256": "sha256:" + "a" * 64,
            "source": "external_bootstrap",
        },
        bootstrap_profile=bootstrap,
    )
    assert authority.resolve() == resolution
    return _Case(root, base, candidate, resolution, bootstrap, profile, spec, authority)


def _prepare(
    case: _Case,
    temp_parent: Path,
    *,
    parent_environment: dict[str, str] | None = None,
):
    return prepare_proof_workspace(
        case.root,
        spec=case.spec,
        authority_resolution=case.resolution,
        bootstrap_profile=case.bootstrap,
        verification_profile=case.profile,
        source_bindings={},
        parent_environment=parent_environment
        or {"LANG": "C", "PATH": os.environ.get("PATH", os.defpath)},
        temp_parent=temp_parent,
    )


def _not_applicable() -> CurrentProofSnapshot:
    preimage = {
        "contract_version": "proof-current-feature-snapshot/v1",
        "scope": "not_applicable",
        "status": "not_applicable",
    }
    return CurrentProofSnapshot(
        scope="not_applicable",
        status="not_applicable",
        preimage=preimage,
        proof_sha256=proof_document_sha256(
            {
                "contract_version": "proof-current-feature-snapshot-digest/v1",
                "snapshot": preimage,
            }
        ),
        event_high_watermark=1,
    )


def _healthy_feature() -> CurrentProofSnapshot:
    digest = "sha256:" + "a" * 64
    preimage = {
        "contract_version": "proof-current-feature-snapshot/v1",
        "scope": "feature",
        "status": "healthy",
        "feature_id": "F-0001",
        "feature_status": "done",
        "evidence_id": "E-0001",
        "evidence_type": "adhoc_artifact",
        "evidence_content_sha256": digest,
        "superseded_by": None,
        "recording_event_id": "EV-0001",
        "recording_event_sha256": digest,
        "link_identity_sha256": digest,
        "health_failure_codes": [],
    }
    return CurrentProofSnapshot(
        scope="feature",
        status="healthy",
        preimage=preimage,
        proof_sha256=proof_document_sha256(
            {
                "contract_version": "proof-current-feature-snapshot-digest/v1",
                "snapshot": preimage,
            }
        ),
        event_high_watermark=1,
    )


def _execute(case: _Case, prepared, **kwargs):
    authority_provider = kwargs.pop("authority_provider", lambda: case.authority)
    current_proof_provider = kwargs.pop("current_proof_provider", _not_applicable)
    return execute_proof_workspace(
        prepared,
        spec=case.spec,
        authority_resolution=case.resolution,
        bootstrap_profile=case.bootstrap,
        verification_profile=case.profile,
        authority_provider=authority_provider,
        current_proof_provider=current_proof_provider,
        **kwargs,
    )


def _stdout(bundle) -> bytes:
    log = next(item for item in bundle.stream_logs if item["stream"] == "stdout")
    assert log["commitment"] == "committed"
    return base64.b64decode(log["content_base64"])


def test_executes_exact_candidate_prepared_check_and_returns_idempotent_bundle(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    with _prepare(case, tmp_path) as prepared:
        original = prepared.prepared_checks["full-regression"]
        bundle = _execute(case, prepared)
        duplicate = _execute(case, prepared)
        assert bundle is duplicate
        assert bundle.frozen_packet.prepared_checks == (original,)
        assert bundle.aggregate["verdict"] == "passed"
        assert bundle.aggregate["positive_proof_handoff"] == "candidate"
        assert bundle.aggregate["reuse_authorized"] is False
        assert _stdout(bundle).strip() == b"candidate"
        public = json.dumps(bundle.public_documents(), sort_keys=True)
        for forbidden in (
            str(case.root),
            str(prepared.root),
            "pid",
            "pgid",
            "duration",
            "wallclock",
            "symlink_chain_sha256",
        ):
            assert forbidden not in public


@pytest.mark.parametrize(
    ("result_verdicts", "not_run", "expected"),
    [
        (["failed", "invalid"], [], "invalid"),
        (["failed", "indeterminate"], [], "indeterminate"),
        (["timed_out", "spawn_failed"], [], "spawn_failed"),
        (["cancelled", "timed_out"], [], "timed_out"),
        (["failed"], ["b"], "failed"),
        ([], ["a", "b"], "blocked"),
        (["passed", "passed"], [], "passed"),
    ],
)
def test_total_verdict_precedence_and_exact_prefix_suffix(
    result_verdicts: list[str],
    not_run: list[str],
    expected: str,
) -> None:
    ordered = ["a", "b"]
    results = [
        {"check_id": ordered[index], "verdict": verdict}
        for index, verdict in enumerate(result_verdicts)
    ]
    assert aggregate_verdict(ordered, results, not_run) == expected
    if results:
        malformed = deepcopy(results)
        malformed[0]["check_id"] = "unknown"
        assert aggregate_verdict(ordered, malformed, not_run) == "invalid"


@pytest.mark.parametrize(
    ("raised", "error_kind"),
    [
        (FileNotFoundError(2, "missing"), "not_found"),
        (PermissionError(13, "denied"), "permission_denied"),
    ],
)
def test_spawn_enoent_and_eacces_reseal_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raised: OSError,
    error_kind: str,
) -> None:
    case = _case(tmp_path)
    with _prepare(case, tmp_path) as prepared:
        original_popen = proof_execution_module._PROCESS_POPEN
        original_reseal = prepared.reseal_after
        calls = 0

        def fail_once(*args, **kwargs):
            monkeypatch.setattr(proof_execution_module, "_PROCESS_POPEN", original_popen)
            raise raised

        def count_reseal(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original_reseal(*args, **kwargs)

        monkeypatch.setattr(proof_execution_module, "_PROCESS_POPEN", fail_once)
        monkeypatch.setattr(prepared, "reseal_after", count_reseal)
        bundle = _execute(case, prepared)
        assert bundle.aggregate["verdict"] == "spawn_failed"
        assert bundle.check_receipts[0]["spawn"] == {
            "status": "failed",
            "error_kind": error_kind,
        }
        assert calls == 1
        retained = prepared.lease_root
    assert retained.exists()


def test_reseal_failure_and_post_authority_uncertainty_override_process_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reseal_case = _case(tmp_path / "reseal")
    with _prepare(reseal_case, tmp_path / "reseal") as prepared:
        calls = 0

        def fail_reseal(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            raise ProofWorkspaceError(
                "reseal unavailable",
                code="proof_reseal_inconclusive",
                details={},
            )

        monkeypatch.setattr(prepared, "reseal_after", fail_reseal)
        bundle = _execute(reseal_case, prepared)
        assert calls == 1
        assert bundle.aggregate["verdict"] == "invalid"
        assert bundle.check_receipts[0]["reseal"]["status"] == "inconclusive"

    authority_case = _case(tmp_path / "post-authority")
    authority_calls = 0

    def uncertain_after_execution() -> AuthorityInputSnapshot:
        nonlocal authority_calls
        authority_calls += 1
        if authority_calls == 3:
            raise OSError("canonical source temporarily unavailable")
        return authority_case.authority

    with _prepare(authority_case, tmp_path / "post-authority") as prepared:
        bundle = _execute(
            authority_case,
            prepared,
            authority_provider=uncertain_after_execution,
        )
        assert bundle.aggregate["verdict"] == "indeterminate"
        assert bundle.check_receipts[0]["reseal"]["status"] == "matched"


def test_post_reseal_input_drift_is_invalid_and_retained(tmp_path: Path) -> None:
    case = _case(
        tmp_path,
        argv=[sys.executable, "-c", "from pathlib import Path; Path('README.md').write_text('drift')"],
    )
    with _prepare(case, tmp_path) as prepared:
        bundle = _execute(case, prepared)
        assert bundle.aggregate["verdict"] == "invalid"
        assert prepared.state == "retained_failure"
        retained = prepared.lease_root
    assert retained.exists()


@pytest.mark.parametrize(("size", "committed"), [(8, True), (9, False)])
def test_profile_output_cap_exact_and_cap_plus_one(
    tmp_path: Path,
    size: int,
    committed: bool,
) -> None:
    case = _case(
        tmp_path,
        argv=[sys.executable, "-c", f"import os; os.write(1, b'x' * {size})"],
        max_output_bytes=8,
    )
    with _prepare(case, tmp_path) as prepared:
        bundle = _execute(case, prepared)
        log = next(item for item in bundle.stream_logs if item["stream"] == "stdout")
        assert (log["commitment"] == "committed") is committed
        assert bundle.aggregate["verdict"] == "passed"
        assert bundle.aggregate["anchoring_eligible"] is committed
        if not committed:
            assert set(log) == {
                "contract_version",
                "packet_sha256",
                "check_id",
                "stream",
                "commitment",
                "reason_codes",
                "log_sha256",
            }


def test_public_ceiling_binary_base64_and_secret_shape_withholding(tmp_path: Path) -> None:
    binary_case = _case(
        tmp_path / "binary",
        argv=[sys.executable, "-c", "import os; os.write(1, b'\\x00\\xff')"],
    )
    with _prepare(binary_case, tmp_path / "binary") as prepared:
        binary = _execute(binary_case, prepared)
        assert _stdout(binary) == b"\x00\xff"

    secret_case = _case(
        tmp_path / "secret",
        argv=[sys.executable, "-c", "import os; os.write(1,b'token='); os.write(1,b'ordinary-value')"],
    )
    with _prepare(secret_case, tmp_path / "secret") as prepared:
        secret = _execute(secret_case, prepared)
        log = next(item for item in secret.stream_logs if item["stream"] == "stdout")
        assert log["commitment"] == "uncommitted"
        assert log["reason_codes"] == ["secret_shape_match"]
        assert secret.aggregate["verdict"] == "passed"
        assert secret.aggregate["positive_proof_handoff"] == "withheld"

    ceiling_case = _case(
        tmp_path / "ceiling",
        argv=[sys.executable, "-c", f"import os; os.write(1,b'x'*{1_048_577})"],
        max_output_bytes=2_000_000,
    )
    with _prepare(ceiling_case, tmp_path / "ceiling") as prepared:
        ceiling = _execute(ceiling_case, prepared)
        log = next(item for item in ceiling.stream_logs if item["stream"] == "stdout")
        assert log["commitment"] == "uncommitted"
        assert log["reason_codes"] == ["public_disclosure_ceiling_exceeded"]


def test_uncommitted_output_collision_has_no_byte_identity() -> None:
    def log_for(content: bytes) -> dict[str, Any]:
        accumulator = StreamAccumulator(1)
        accumulator.consume(content)
        accumulator.eof = True
        return accumulator.public_log(
            packet_sha256="sha256:" + "a" * 64,
            check_id="check",
            stream="stdout",
            secret_environment=False,
        )

    first = log_for(b"first")
    second = log_for(b"other")
    assert first == second
    assert first["commitment"] == "uncommitted"
    assert not ({"content_byte_count", "content_base64", "content_sha256"} & set(first))


def test_dual_stream_drain_timeout_term_kill_and_descendant_cleanup(tmp_path: Path) -> None:
    dual_case = _case(
        tmp_path / "dual",
        argv=[
            sys.executable,
            "-c",
            "import os; os.write(1,b'x'*200000); os.write(2,b'y'*200000)",
        ],
        max_output_bytes=300_000,
    )
    with _prepare(dual_case, tmp_path / "dual") as prepared:
        dual = _execute(dual_case, prepared)
        assert dual.aggregate["verdict"] == "passed"
        assert all(item["commitment"] == "committed" for item in dual.stream_logs)

    timeout_case = _case(
        tmp_path / "timeout",
        argv=[
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(20)",
        ],
        timeout_seconds=1,
    )
    with _prepare(timeout_case, tmp_path / "timeout") as prepared:
        timed = _execute(timeout_case, prepared)
        receipt = timed.check_receipts[0]
        assert timed.aggregate["verdict"] == "timed_out", json.dumps(receipt["process"])
        assert receipt["process"]["term_sent"] is True
        assert receipt["process"]["kill_sent"] is True
        assert receipt["process"]["pipes_eof"] is True
        assert receipt["process"]["group_quiescent"] is True

    descendant_case = _case(
        tmp_path / "descendant",
        argv=[
            sys.executable,
            "-c",
            "import os,time; pid=os.fork(); time.sleep(20) if pid==0 else None",
        ],
        timeout_seconds=10,
    )
    with _prepare(descendant_case, tmp_path / "descendant") as prepared:
        descendant = _execute(descendant_case, prepared)
        assert descendant.aggregate["verdict"] == "failed"
        assert descendant.check_receipts[0]["process"]["controller_cause"] == "descendant_cleanup"


def test_exit_signal_cancellation_and_eperm_uncertainty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_case = _case(
        tmp_path / "exit",
        argv=[sys.executable, "-c", "raise SystemExit(3)"],
    )
    with _prepare(exit_case, tmp_path / "exit") as prepared:
        failed = _execute(exit_case, prepared)
        assert failed.aggregate["verdict"] == "failed"
        assert failed.check_receipts[0]["process"]["leader_value"] == 3

    signal_case = _case(
        tmp_path / "signal",
        argv=[sys.executable, "-c", "import os,signal; os.kill(os.getpid(),signal.SIGTERM)"],
    )
    with _prepare(signal_case, tmp_path / "signal") as prepared:
        signaled = _execute(signal_case, prepared)
        assert signaled.aggregate["verdict"] == "failed"
        assert signaled.check_receipts[0]["process"]["leader_kind"] == "signaled"

    cancel_case = _case(
        tmp_path / "cancel",
        argv=[sys.executable, "-c", "import time; time.sleep(20)"],
    )
    cancel = threading.Event()
    with _prepare(cancel_case, tmp_path / "cancel") as prepared:
        original_popen = proof_execution_module._PROCESS_POPEN
        timer: threading.Timer | None = None

        def spawn_then_arm_cancellation(*args, **kwargs):
            nonlocal timer
            process = original_popen(*args, **kwargs)
            timer = threading.Timer(0.2, cancel.set)
            timer.start()
            return process

        with monkeypatch.context() as spawn_patch:
            spawn_patch.setattr(
                proof_execution_module,
                "_PROCESS_POPEN",
                spawn_then_arm_cancellation,
            )
            try:
                cancelled = _execute(cancel_case, prepared, cancel_event=cancel)
                assert cancelled.aggregate["verdict"] == "cancelled"
                assert (
                    cancelled.check_receipts[0]["process"]["controller_cause"]
                    == "cancellation"
                )
            finally:
                if timer is not None:
                    timer.cancel()

    eperm_case = _case(tmp_path / "eperm")
    monkeypatch.setattr(proof_execution_module, "_process_group_state", lambda _pgid: "uncertain")
    with _prepare(eperm_case, tmp_path / "eperm") as prepared:
        uncertain = _execute(eperm_case, prepared)
        assert uncertain.aggregate["verdict"] == "indeterminate"
        assert uncertain.check_receipts[0]["process"]["group_quiescent"] is False


def test_exact_public_ceiling_has_maximum_base64_length() -> None:
    accumulator = StreamAccumulator(1_048_576)
    accumulator.consume(b"x" * 1_048_576)
    accumulator.eof = True
    log = accumulator.public_log(
        packet_sha256="sha256:" + "a" * 64,
        check_id="ceiling",
        stream="stdout",
        secret_environment=False,
    )
    assert log["commitment"] == "committed"
    assert log["content_byte_count"] == 1_048_576
    assert len(log["content_base64"]) == 1_398_104


def test_secret_shaped_environment_withholds_even_ordinary_output(tmp_path: Path) -> None:
    case = _case(tmp_path, argv=[sys.executable, "-c", "print('ordinary')"])
    case.profile["checks"][0]["environment"]["inherit_names"] = ["LANG", "MY_TOKEN", "PATH"]
    case.spec = c2._spec(case.resolution, case.bootstrap, case.profile)
    environment = {
        "LANG": "C",
        "MY_TOKEN": "not-printed-value",
        "PATH": os.environ.get("PATH", os.defpath),
    }
    with _prepare(case, tmp_path, parent_environment=environment) as prepared:
        bundle = _execute(case, prepared)
        assert bundle.aggregate["verdict"] == "passed"
        assert bundle.aggregate["reuse_disposition"] == "fresh_only"
        assert bundle.aggregate["anchoring_eligible"] is False
        assert all(item["commitment"] == "uncommitted" for item in bundle.stream_logs)
        assert all(
            item["reason_codes"] == ["secret_shaped_environment"]
            for item in bundle.stream_logs
        )


def test_pre_spawn_final_seal_order_has_no_callback_before_popen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path)
    with _prepare(case, tmp_path) as prepared:
        events: list[str] = []
        original_capture = prepared.capture_before
        original_assert = prepared.assert_ready_to_spawn
        original_checkpoint = proof_execution_module._authority_checkpoint
        original_guard = proof_execution_module._lightweight_guard
        original_popen = proof_execution_module._PROCESS_POPEN

        def capture(*args, **kwargs):
            events.append("capture:start")
            result = original_capture(*args, **kwargs)
            events.append("capture:done")
            return result

        def assert_ready(*args, **kwargs):
            events.append("assert")
            return original_assert(*args, **kwargs)

        def checkpoint(*args, **kwargs):
            events.append(f"authority:{kwargs['phase']}")
            return original_checkpoint(*args, **kwargs)

        def guard(*args, **kwargs):
            events.append("guard")
            return original_guard(*args, **kwargs)

        def popen(*args, **kwargs):
            events.append("popen")
            return original_popen(*args, **kwargs)

        monkeypatch.setattr(prepared, "capture_before", capture)
        monkeypatch.setattr(prepared, "assert_ready_to_spawn", assert_ready)
        monkeypatch.setattr(proof_execution_module, "_authority_checkpoint", checkpoint)
        monkeypatch.setattr(proof_execution_module, "_lightweight_guard", guard)
        monkeypatch.setattr(proof_execution_module, "_PROCESS_POPEN", popen)
        bundle = _execute(case, prepared)
        assert bundle.aggregate["verdict"] == "passed"
        start = events.index("capture:start")
        assert events[start : events.index("popen") + 1] == [
            "capture:start",
            "assert",
            "capture:done",
            "authority:pre_spawn",
            "assert",
            "guard",
            "popen",
        ]


def test_preparation_symlink_is_not_reresolved_and_resolved_tool_drift_is_invalid(
    tmp_path: Path,
) -> None:
    link = tmp_path / "python-link"
    link.symlink_to(sys.executable)
    symlink_case = _case(
        tmp_path / "symlink",
        argv=[str(link), "-c", "print('resolved')"],
    )
    with _prepare(symlink_case, tmp_path / "symlink") as prepared:
        link.unlink()
        bundle = _execute(symlink_case, prepared)
        assert bundle.aggregate["verdict"] == "passed"
        assert _stdout(bundle).strip() == b"resolved"

    tool = tmp_path / "owned-tool"
    tool.write_bytes(Path(sys.executable).read_bytes())
    tool.chmod(0o755)
    drift_case = _case(
        tmp_path / "tool-drift",
        argv=[str(tool), "-c", "print('never')"],
    )
    with _prepare(drift_case, tmp_path / "tool-drift") as prepared:
        with tool.open("ab") as stream:
            stream.write(b"drift")
        bundle = _execute(drift_case, prepared)
        assert bundle.aggregate["verdict"] == "invalid"
        assert bundle.check_receipts[0]["spawn"]["status"] == "not_attempted"


def test_fresh_c1_change_is_blocked_initially_and_invalid_after_initial_checkpoint(
    tmp_path: Path,
) -> None:
    initial_case = _case(tmp_path / "initial")
    escalated = replace(initial_case.authority, existing_route_risk="R4")
    with _prepare(initial_case, tmp_path / "initial") as prepared:
        bundle = _execute(
            initial_case,
            prepared,
            authority_provider=lambda: escalated,
        )
        assert bundle.aggregate["verdict"] == "blocked"

    later_case = _case(tmp_path / "later")
    calls = 0

    def drift_after_initial() -> AuthorityInputSnapshot:
        nonlocal calls
        calls += 1
        if calls == 2:
            c2._git(later_case.root, "update-ref", "-d", "refs/heads/master")
        return later_case.authority

    with _prepare(later_case, tmp_path / "later") as prepared:
        bundle = _execute(
            later_case,
            prepared,
            authority_provider=drift_after_initial,
        )
        assert bundle.aggregate["verdict"] == "invalid"
        assert bundle.check_receipts[0]["spawn"]["status"] == "not_attempted"


def test_inconclusive_current_proof_is_nullable_and_withheld(tmp_path: Path) -> None:
    case = _case(tmp_path)

    def unavailable() -> CurrentProofSnapshot:
        raise OSError("read-only snapshot unavailable")

    with _prepare(case, tmp_path) as prepared:
        bundle = _execute(case, prepared, current_proof_provider=unavailable)
        assert bundle.aggregate["verdict"] == "passed"
        assert bundle.aggregate["current_proof"] == {
            "scope": "feature",
            "status": "indeterminate",
            "proof_sha256": None,
        }
        assert bundle.aggregate["anchoring_eligible"] is False
        assert bundle.aggregate["positive_proof_handoff"] == "withheld"


def test_standalone_end_capture_failure_returns_indeterminate_bundle_and_retains(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    calls = 0

    def standalone_then_unavailable() -> CurrentProofSnapshot:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _not_applicable()
        raise OSError("end snapshot unavailable")

    with _prepare(case, tmp_path) as prepared:
        retained = prepared.lease_root
        bundle = _execute(
            case,
            prepared,
            current_proof_provider=standalone_then_unavailable,
        )
        assert calls == 2
        assert bundle.aggregate["current_proof"] == {
            "scope": "not_applicable",
            "status": "indeterminate",
            "proof_sha256": None,
        }
        assert bundle.aggregate["anchoring_eligible"] is False
        assert bundle.aggregate["positive_proof_handoff"] == "withheld"
        assert prepared.state == "retained_failure"
    assert retained.exists()


def test_feature_to_standalone_change_returns_changed_bundle_and_retains(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    snapshots = iter((_healthy_feature(), _not_applicable()))

    with _prepare(case, tmp_path) as prepared:
        retained = prepared.lease_root
        bundle = _execute(
            case,
            prepared,
            current_proof_provider=lambda: next(snapshots),
        )
        assert bundle.aggregate["current_proof"] == {
            "scope": "not_applicable",
            "status": "changed",
            "proof_sha256": _not_applicable().proof_sha256,
        }
        assert bundle.aggregate["anchoring_eligible"] is False
        assert bundle.aggregate["positive_proof_handoff"] == "withheld"
        assert prepared.state == "retained_failure"
    assert retained.exists()


def test_source_authority_and_clone_drift_fail_before_spawn(tmp_path: Path) -> None:
    source_case = _case(tmp_path / "source")
    with _prepare(source_case, tmp_path / "source") as prepared:
        c2._git(source_case.root, "update-ref", "-d", "refs/heads/master")
        bundle = _execute(source_case, prepared)
        assert bundle.aggregate["verdict"] == "blocked"
        assert bundle.check_receipts[0]["spawn"]["status"] == "not_attempted"

    clone_case = _case(tmp_path / "clone")
    with _prepare(clone_case, tmp_path / "clone") as prepared:
        (prepared.root / "README.md").write_text("clone drift\n", encoding="utf-8")
        bundle = _execute(clone_case, prepared)
        assert bundle.aggregate["verdict"] == "invalid"
        assert bundle.check_receipts[0]["spawn"]["status"] == "not_attempted"


def test_base_unknown_uses_canonical_source_without_fabricating_diff(tmp_path: Path) -> None:
    case = _case(tmp_path, authority_status="base_unknown")
    with _prepare(case, tmp_path) as prepared:
        bundle = _execute(case, prepared)
        assert bundle.aggregate["verdict"] == "passed"
        assert bundle.aggregate["reuse_disposition"] == "fresh_only"
        assert bundle.aggregate["reuse_authorized"] is False
        assert all(
            checkpoint["clone_diff_cross_check"]
            == {"status": "not_applicable_base_unknown", "diff_sha256": None}
            for checkpoint in bundle.authority_checkpoints
        )


def test_same_workspace_concurrent_callers_spawn_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(
        tmp_path,
        argv=[sys.executable, "-c", "import time; time.sleep(.2); print('once')"],
    )
    with _prepare(case, tmp_path) as prepared:
        original = proof_execution_module._PROCESS_POPEN
        count = 0
        lock = threading.Lock()

        def counted(*args, **kwargs):
            nonlocal count
            with lock:
                count += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(proof_execution_module, "_PROCESS_POPEN", counted)
        with ThreadPoolExecutor(max_workers=2) as pool:
            bundles = list(pool.map(lambda _: _execute(case, prepared), range(2)))
        assert bundles[0] is bundles[1]
        assert count == 1


def test_independent_workspaces_can_spawn_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_case = _case(tmp_path / "first")
    second_case = _case(tmp_path / "second")
    original = proof_execution_module._PROCESS_POPEN
    barrier = threading.Barrier(2)
    count = 0
    count_lock = threading.Lock()

    def synchronized(*args, **kwargs):
        nonlocal count
        with count_lock:
            count += 1
        barrier.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(proof_execution_module, "_PROCESS_POPEN", synchronized)
    with ExitStack() as stack:
        first = stack.enter_context(_prepare(first_case, tmp_path / "first"))
        second = stack.enter_context(_prepare(second_case, tmp_path / "second"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(_execute, first_case, first),
                pool.submit(_execute, second_case, second),
            ]
            bundles = [future.result(timeout=30) for future in futures]
        assert count == 2
        assert bundles[0] is not bundles[1]
        assert all(bundle.aggregate["verdict"] == "passed" for bundle in bundles)


def _current_proof_project(tmp_path: Path) -> tuple[ProjectPaths, str, str]:
    paths = ProjectPaths(tmp_path)
    initialize_database(paths.db_path, paths.events_path)
    conn = connect(paths.db_path)
    try:
        now = "2026-08-02T00:00:00Z"
        conn.execute(
            "INSERT INTO features(id,name,surface,description,status,confidence,created_at,updated_at) VALUES ('F-0001','proof','runtime','', 'done','high',?,?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO tasks(id,title,status,priority,related_feature_id,created_at,updated_at) VALUES ('T-0001','proof','in_progress',1,'F-0001',?,?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO tasks(id,title,status,priority,created_at,updated_at) VALUES ('T-0002','standalone','in_progress',1,?,?)",
            (now, now),
        )
        conn.commit()
    finally:
        conn.close()
    artifact = tmp_path / "proof.txt"
    artifact.write_text("healthy\n", encoding="utf-8")
    record = record_adhoc_evidence(
        paths,
        files=[str(artifact)],
        summary="current proof",
        command="pytest",
        copy_files=True,
    )
    evidence_id = str(record["evidence"]["id"])
    conn = connect(paths.db_path)
    try:
        insert_evidence_link(
            conn,
            evidence_id=evidence_id,
            target_type="feature",
            target_id="F-0001",
            link_role="acceptance",
            created_at="2026-08-02T00:00:01Z",
        )
        conn.commit()
    finally:
        conn.close()
    return paths, evidence_id, "T-0001"


def test_current_proof_exact_preimage_hwm_independence_and_read_only_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, evidence_id, task_id = _current_proof_project(tmp_path)
    opened = []
    original_connect_read_only = proof_execution_module.connect_read_only

    def observed_read_only(db_path):
        conn = original_connect_read_only(db_path)
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        opened.append(conn)
        return conn

    monkeypatch.setattr(
        proof_execution_module,
        "connect_read_only",
        observed_read_only,
    )
    lock_state = {
        path.name: (path.stat().st_dev, path.stat().st_ino, path.read_bytes())
        for path in (paths.loop_dir / "project.lock", paths.loop_dir / "events-jsonl.lock")
        if path.exists()
    }
    db_before = paths.db_path.read_bytes()
    first = capture_current_proof(paths, {"type": "task", "id": task_id})
    assert first.scope == "feature"
    assert first.status == "healthy"
    assert first.preimage["feature_status"] == "done"
    assert first.preimage["evidence_id"] == evidence_id
    assert first.preimage["health_failure_codes"] == []
    assert first.preimage["link_identity_sha256"] == proof_document_sha256(
        {
            "contract_version": "proof-current-feature-link-identity/v1",
            "evidence_id": evidence_id,
            "target_type": "feature",
            "target_id": "F-0001",
            "link_role": "acceptance",
        }
    )
    conn = connect(paths.db_path)
    try:
        event = conn.execute(
            "SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at "
            "FROM events WHERE id = ?",
            (first.preimage["recording_event_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert event is not None
    assert first.preimage["recording_event_sha256"] == (
        "sha256:" + hashlib.sha256(canonical_event_bytes(canonical_event_record(event))).hexdigest()
    )
    exact = proof_document_sha256(
        {
            "contract_version": "proof-current-feature-snapshot-digest/v1",
            "snapshot": dict(first.preimage),
        }
    )
    assert first.proof_sha256 == exact
    assert paths.db_path.read_bytes() == db_before
    assert {
        path.name: (path.stat().st_dev, path.stat().st_ino, path.read_bytes())
        for path in (paths.loop_dir / "project.lock", paths.loop_dir / "events-jsonl.lock")
        if path.exists()
    } == lock_state
    assert opened
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        opened[0].execute("SELECT 1")

    conn = connect(paths.db_path)
    try:
        sequence = conn.execute("SELECT MAX(sequence) + 1 FROM events").fetchone()[0]
        conn.execute(
            "INSERT INTO events(id,sequence,event_type,entity_type,entity_id,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
            ("EV-UNRELATED", sequence, "unrelated", "goal", "G-X", "{}", "2026-08-02T00:00:02Z"),
        )
        conn.commit()
    finally:
        conn.close()
    second = capture_current_proof(paths, {"type": "task", "id": task_id})
    assert second.event_high_watermark > first.event_high_watermark
    assert second.proof_sha256 == first.proof_sha256
    assert derive_current_proof(first, second)["status"] == "healthy"

    standalone = capture_current_proof(paths, {"type": "task", "id": "T-0002"})
    assert standalone.scope == "not_applicable"
    assert standalone.status == "not_applicable"


def test_current_proof_connection_scoped_capture_uses_caller_snapshot(
    tmp_path: Path,
) -> None:
    paths, _, task_id = _current_proof_project(tmp_path)
    conn = connect(paths.db_path)
    try:
        conn.execute("BEGIN")
        hwm = int(conn.execute("SELECT MAX(sequence) FROM events").fetchone()[0])
        scoped = capture_current_proof_in_snapshot(
            paths,
            conn,
            {"type": "task", "id": task_id},
            hwm=hwm,
        )
        standalone = capture_current_proof_in_snapshot(
            paths,
            conn,
            {"type": "task", "id": "T-0002"},
            hwm=hwm,
        )
        assert conn.in_transaction
    finally:
        conn.rollback()
        conn.close()
    assert scoped == capture_current_proof(paths, {"type": "task", "id": task_id})
    assert standalone.scope == "not_applicable"
    assert standalone.event_high_watermark == hwm


def test_current_proof_event_and_link_changes_are_digest_relevant(tmp_path: Path) -> None:
    event_root = tmp_path / "event"
    paths, _, task_id = _current_proof_project(event_root)
    first = capture_current_proof(paths, {"type": "task", "id": task_id})
    conn = connect(paths.db_path)
    try:
        conn.execute(
            "UPDATE events SET created_at = ? WHERE id = ?",
            ("2026-08-02T00:00:09Z", first.preimage["recording_event_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    event_changed = capture_current_proof(paths, {"type": "task", "id": task_id})
    assert event_changed.status == "healthy"
    assert event_changed.preimage["recording_event_sha256"] != first.preimage["recording_event_sha256"]
    assert event_changed.proof_sha256 != first.proof_sha256

    link_root = tmp_path / "link"
    paths, evidence_id, task_id = _current_proof_project(link_root)
    first = capture_current_proof(paths, {"type": "task", "id": task_id})
    artifact = link_root / "second-proof.txt"
    artifact.write_text("second\n", encoding="utf-8")
    record = record_adhoc_evidence(
        paths,
        files=[str(artifact)],
        summary="new selected proof",
        command="pytest",
        copy_files=True,
    )
    second_evidence_id = str(record["evidence"]["id"])
    conn = connect(paths.db_path)
    try:
        insert_evidence_link(
            conn,
            evidence_id=second_evidence_id,
            target_type="feature",
            target_id="F-0001",
            link_role="acceptance",
            created_at="2026-08-02T00:00:10Z",
        )
        conn.commit()
    finally:
        conn.close()
    link_changed = capture_current_proof(paths, {"type": "task", "id": task_id})
    assert link_changed.status == "healthy"
    assert link_changed.preimage["evidence_id"] == second_evidence_id
    assert link_changed.preimage["link_identity_sha256"] != first.preimage["link_identity_sha256"]
    assert link_changed.proof_sha256 != event_changed.proof_sha256
    assert evidence_id != second_evidence_id


def test_current_proof_relevant_change_and_inconclusive_are_withheld(tmp_path: Path) -> None:
    paths, evidence_id, task_id = _current_proof_project(tmp_path)
    first = capture_current_proof(paths, {"type": "task", "id": task_id})
    manifest = json.loads(
        (paths.evidence_dir / "adhoc" / f"{evidence_id.lower()}-adhoc-v0.json").read_text()
    )
    copied = paths.root / manifest["members"][0]["stored_path"]
    copied.write_text("changed\n", encoding="utf-8")
    second = capture_current_proof(paths, {"type": "task", "id": task_id})
    assert second.status == "unhealthy"
    assert derive_current_proof(first, second) == {
        "scope": "feature",
        "status": "changed",
        "proof_sha256": second.proof_sha256,
    }
    assert derive_current_proof(first, None) == {
        "scope": "feature",
        "status": "indeterminate",
        "proof_sha256": None,
    }


def test_no_cli_lifecycle_or_persistence_integration() -> None:
    cli = (Path(__file__).parents[1] / "src" / "pcl" / "cli.py").read_text(encoding="utf-8")
    assert "proof-execution-packet/v1" not in cli
    assert "execute_proof_workspace" not in cli
    source = Path(proof_execution_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "connect_mutation",
        "append_event",
        "render_dashboard",
        "set_task_status",
        "record_adhoc_evidence",
    ):
        assert forbidden not in source
