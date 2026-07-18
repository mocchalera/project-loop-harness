from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/materialize_layered_harness_ablation.py"
EVALUATOR = ROOT / "scripts/evaluate_layered_harness_ablation.py"
AUTHORIZATION_CONTRACT = "layered-harness-ablation-authorization/v1"
COHORT_SHA256 = "2726dc760e0dfcb46494d4c9072601868d9b6edc7d7fe13e15378ffdd7a51080"


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MATERIALIZER_MODULE = _load_script(SCRIPT, "lha_materializer_test_module")
EVALUATOR_MODULE = _load_script(EVALUATOR, "lha_evaluator_test_module")
_equivalence_projection = MATERIALIZER_MODULE._equivalence_projection
prepare_arm_packets = EVALUATOR_MODULE.prepare_arm_packets


def _write_authorization(path: Path) -> None:
    fixture = json.loads(
        (
            ROOT
            / "tests/fixtures/layered_harness_ablation_v0/layered-harness-ablation-fixture.json"
        ).read_text(encoding="utf-8")
    )
    now = datetime.now(timezone.utc)
    payload = {
        "contract_version": AUTHORIZATION_CONTRACT,
        "cohort_id": "LHA-20260718-01",
        "cohort_sha256": COHORT_SHA256,
        "authorized_arm_ids": sorted(arm["arm_id"] for arm in fixture["prepared_arms"]),
        "independent_cockpit_sessions": True,
        "network_model_provider_runs": True,
        "authorized_agent_types": ["codex", "grok"],
        "data_class": "synthetic repository fixture",
        "budget": {"currency": "USD", "max_amount": 0, "paid_runs_allowed": False},
        "cost_policy": "No model calls from fixture materialization.",
        "authorized_by": "human:test-fixture",
        "authorized_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _prepare_packets(tmp_path: Path) -> Path:
    authorization = tmp_path / "authorization.json"
    packet_dir = tmp_path / "packets"
    _write_authorization(authorization)
    payload, exit_code = prepare_arm_packets(packet_dir, authorization)
    assert exit_code == 0, payload
    return packet_dir / "manifest.json"


def _run_materializer(packet_manifest: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--packet-manifest",
            str(packet_manifest),
            "--output-dir",
            str(output_dir),
            "--source-repo",
            str(ROOT),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _rewrite_packet_and_hash(packet_manifest: Path, arm_id: str, mutate) -> None:
    manifest = json.loads(packet_manifest.read_text(encoding="utf-8"))
    item = next(packet for packet in manifest["packets"] if packet["arm_id"] == arm_id)
    packet_path = packet_manifest.parent / item["path"]
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    mutate(packet)
    packet_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    item["sha256"] = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    packet_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_materializes_sixteen_isolated_roots_and_consumer_briefs(tmp_path: Path) -> None:
    packet_manifest = _prepare_packets(tmp_path)
    output_dir = tmp_path / "materialized"

    result = _run_materializer(packet_manifest, output_dir)

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    manifest = payload["manifest"]
    assert manifest["root_count"] == 16
    assert manifest["models_called"] is False
    assert manifest["cockpit_sessions_launched"] is False
    assert all(pair["equivalent"] is True for pair in manifest["pair_semantic_equivalence"])
    roots = [Path(arm["root"]) for arm in manifest["arms"]]
    assert len(set(roots)) == 16
    assert all(root.is_dir() and ROOT not in root.parents for root in roots)

    for arm in manifest["arms"]:
        source_head = subprocess.run(
            ["git", "-C", arm["source_root"], "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        assert source_head == arm["source_commit"]
        assert arm["packet_sha256"]
        assert arm["authorization_receipt_sha256"] == manifest["authorization_receipt_sha256"]
        brief_path = Path(arm["consumer_brief"])
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        brief_text = brief_path.read_text(encoding="utf-8")
        assert "setup-command-log" not in brief_text
        assert "mixed_legacy_" not in brief_text
        assert "pcl init --target" not in brief_text
        result_path = Path(brief["result"]["path"])
        assert result_path.is_absolute()
        assert result_path.parent.is_dir()
        assert result_path.parent == brief_path.parent / "results"

    by_arm = {arm["arm_id"]: arm for arm in manifest["arms"]}
    for arm_id in (
        "LHA-004-baseline",
        "LHA-004-treatment",
        "LHA-005-baseline",
        "LHA-005-treatment",
    ):
        assert Path(by_arm[arm_id]["handoff_packet"]).is_file()
        assert by_arm[arm_id]["handoff_packet_sha256"]
    for arm_id, arm in by_arm.items():
        if not arm_id.startswith(("LHA-004", "LHA-005")):
            assert arm["handoff_packet"] is None

    baseline_snapshot = json.loads(
        (Path(by_arm["LHA-003-baseline"]["consumer_brief"]).parent / "semantic-snapshot.json").read_text()
    )
    treatment_snapshot = json.loads(
        (Path(by_arm["LHA-003-treatment"]["consumer_brief"]).parent / "semantic-snapshot.json").read_text()
    )
    assert baseline_snapshot["finding_counts"] is None
    assert treatment_snapshot["finding_counts"] == {"active": 1, "historical": 1}
    assert _equivalence_projection(baseline_snapshot) == _equivalence_projection(
        treatment_snapshot
    )

    decisions = json.loads(
        (
            Path(by_arm["LHA-007-treatment"]["consumer_brief"]).parent
            / "semantic-snapshot.json"
        ).read_text()
    )["tables"]["decisions.csv"]
    assert [(row["id"], row["status"]) for row in decisions] == [("DEC-0001", "open")]
    stories = json.loads(
        (
            Path(by_arm["LHA-008-treatment"]["consumer_brief"]).parent
            / "semantic-snapshot.json"
        ).read_text()
    )["tables"]["user_stories.csv"]
    assert [(row["id"], row["status"]) for row in stories] == [("US-0001", "draft")]


def test_pair_equivalence_excludes_projection_but_not_finding_semantics() -> None:
    baseline = {
        "tables": {"tasks.csv": [{"id": "T-0001", "status": "todo"}]},
        "findings": [
            {
                "code": "feature_done_open_defects",
                "entity": {"type": "feature", "id": "F-0001"},
                "severity": "warning",
                "proof_scope": None,
            }
        ],
        "finding_counts": None,
    }
    treatment = json.loads(json.dumps(baseline))
    treatment["findings"][0]["proof_scope"] = "active"
    treatment["finding_counts"] = {"active": 1, "historical": 0}

    assert _equivalence_projection(baseline) == _equivalence_projection(treatment)
    treatment["findings"][0]["severity"] = "error"
    assert _equivalence_projection(baseline) != _equivalence_projection(treatment)


def test_materializer_rechecks_authorization_expiry_before_writing(tmp_path: Path) -> None:
    packet_manifest = _prepare_packets(tmp_path)
    manifest = json.loads(packet_manifest.read_text(encoding="utf-8"))
    manifest["authorization_expires_at"] = "2000-01-01T00:00:00Z"
    packet_manifest.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    output_dir = tmp_path / "materialized"

    result = _run_materializer(packet_manifest, output_dir)

    assert result.returncode == 2
    assert "authorization receipt is expired" in json.loads(result.stdout)["error"]
    assert not output_dir.exists()


def test_materializer_rejects_output_inside_source_repository(tmp_path: Path) -> None:
    packet_manifest = _prepare_packets(tmp_path)
    output_dir = ROOT / "forbidden-materialized-output"

    result = _run_materializer(packet_manifest, output_dir)

    assert result.returncode == 2
    assert "must be outside source repository" in json.loads(result.stdout)["error"]
    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            lambda packet: packet["case"]["fixture_state"]["steps"].append(
                {"op": "raw_sql", "command": "sqlite3 project.db"}
            ),
            "unsupported setup operation",
        ),
        (
            lambda packet: packet["arm"].__setitem__("commit_full", "0" * 40),
            "source commit is missing",
        ),
        (
            lambda packet: packet["case"]["fixture_state"]["expected_ids"].__setitem__(
                "goal", "GOAL-NOT-DIGITS"
            ),
            "digit grammar",
        ),
    ],
)
def test_preflight_fails_closed_on_unsupported_ops_commits_and_ids(
    tmp_path: Path, mutation, error: str
) -> None:
    packet_manifest = _prepare_packets(tmp_path)
    _rewrite_packet_and_hash(packet_manifest, "LHA-006-baseline", mutation)
    output_dir = tmp_path / "materialized"

    result = _run_materializer(packet_manifest, output_dir)

    assert result.returncode == 2
    assert error in json.loads(result.stdout)["error"]
    assert not output_dir.exists()


def test_preflight_rejects_packet_hash_drift(tmp_path: Path) -> None:
    packet_manifest = _prepare_packets(tmp_path)
    packet = packet_manifest.parent / "LHA-001-baseline.json"
    packet.write_text(packet.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    result = _run_materializer(packet_manifest, tmp_path / "materialized")

    assert result.returncode == 2
    assert "packet sha256 mismatch" in json.loads(result.stdout)["error"]
