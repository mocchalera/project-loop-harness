from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any


ARM_PACKET_CONTRACT = "layered-harness-ablation-arm-packet/v1"
PACKET_MANIFEST_CONTRACT = "layered-harness-ablation-arm-packet-manifest/v1"
MATERIALIZATION_CONTRACT = "layered-harness-ablation-materialization/v1"
CONSUMER_BRIEF_CONTRACT = "layered-harness-ablation-consumer-brief/v1"
RELEASED_LEGACY_REF = "v0.3.0"
RELEASED_LEGACY_COMMIT = "f04d9f70394eb288cfdb5dd2cd1bedef3f07c96c"
EXPECTED_ARM_IDS = {
    f"LHA-{case:03d}-{condition}"
    for case in range(1, 9)
    for condition in ("baseline", "treatment")
}
SUPPORTED_SETUP_OPS = {
    "pcl_init",
    "goal_create",
    "task_create",
    "feature_add",
    "story_draft",
    "seed_mixed_findings",
    "handoff_packet",
    "decision_open",
}
ID_RE = re.compile(r"^(?:G|T|F|US|DEC|E)-[0-9]{4,}$")
ENTITY_ID_RE = re.compile(r"^(?:G|T|F|US|TC|D|DEC|E)-[0-9]{4,}$")
EVENT_ID_RE = re.compile(r"^EV-[0-9A-F]+$")
TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
SEMANTIC_EXPORTS = {
    "goals.csv",
    "tasks.csv",
    "features.csv",
    "user_stories.csv",
    "test_cases.csv",
    "defects.csv",
    "decisions.csv",
    "evidence.csv",
    "evidence_links.csv",
}
DYNAMIC_COLUMNS = {"created_at", "updated_at", "resolved_at", "waived_at", "event_id"}


class MaterializationError(RuntimeError):
    pass


class DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str, capture_bytes: bool = False) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=not capture_bytes,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode() if capture_bytes else result.stderr
        raise MaterializationError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return result


def _resolve_commit(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").stdout.strip()


def _preflight(packet_manifest: Path, source_repo: Path, output_dir: Path) -> list[dict[str, Any]]:
    if output_dir == source_repo or source_repo in output_dir.parents:
        raise MaterializationError("materialization output directory must be outside source repository")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise MaterializationError("materialization output directory must be empty")
    try:
        manifest = _load_json(packet_manifest)
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
        raise MaterializationError(f"cannot load packet manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("contract_version") != PACKET_MANIFEST_CONTRACT:
        raise MaterializationError("unsupported arm packet manifest contract")
    packet_items = manifest.get("packets")
    if manifest.get("packet_count") != 16 or not isinstance(packet_items, list) or len(packet_items) != 16:
        raise MaterializationError("packet manifest must contain exactly 16 packets")
    item_ids = [item.get("arm_id") for item in packet_items if isinstance(item, dict)]
    if len(item_ids) != 16 or set(item_ids) != EXPECTED_ARM_IDS or len(set(item_ids)) != 16:
        raise MaterializationError("packet manifest arm IDs do not match the frozen 8x2 cohort")
    expires_at = _parse_utc_timestamp(manifest.get("authorization_expires_at"))
    if expires_at is None or expires_at <= datetime.now(timezone.utc):
        raise MaterializationError("packet authorization receipt is expired or invalid")

    packets: list[dict[str, Any]] = []
    packet_dir = packet_manifest.resolve().parent
    for item in sorted(packet_items, key=lambda value: value["arm_id"]):
        if set(item) != {"arm_id", "path", "sha256"}:
            raise MaterializationError(f"{item.get('arm_id')}: invalid packet manifest entry")
        path = (packet_dir / item["path"]).resolve()
        if path.parent != packet_dir:
            raise MaterializationError(f"{item['arm_id']}: packet path escapes packet directory")
        if not path.is_file() or _sha256(path) != item["sha256"]:
            raise MaterializationError(f"{item['arm_id']}: packet sha256 mismatch")
        try:
            packet = _load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
            raise MaterializationError(f"{item['arm_id']}: invalid packet JSON: {exc}") from exc
        _validate_packet(packet, item, manifest, source_repo)
        packet["_packet_path"] = str(path)
        packet["_packet_sha256"] = item["sha256"]
        packets.append(packet)

    legacy_commit = _resolve_commit(source_repo, RELEASED_LEGACY_REF)
    if legacy_commit != RELEASED_LEGACY_COMMIT:
        raise MaterializationError(
            f"released legacy ref drift: expected {RELEASED_LEGACY_COMMIT}, observed {legacy_commit}"
        )
    return packets


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def _validate_packet(
    packet: Any,
    item: dict[str, Any],
    manifest: dict[str, Any],
    source_repo: Path,
) -> None:
    arm_id = item["arm_id"]
    if not isinstance(packet, dict) or packet.get("contract_version") != ARM_PACKET_CONTRACT:
        raise MaterializationError(f"{arm_id}: unsupported arm packet contract")
    arm = packet.get("arm")
    case = packet.get("case")
    authorization = packet.get("authorization")
    if not isinstance(arm, dict) or not isinstance(case, dict) or not isinstance(authorization, dict):
        raise MaterializationError(f"{arm_id}: packet arm/case/authorization must be objects")
    if arm.get("arm_id") != arm_id or case.get("id") != arm.get("case_id"):
        raise MaterializationError(f"{arm_id}: packet arm/case identity mismatch")
    for field in ("cohort_sha256", "fixture_sha256", "runbook_sha256"):
        if packet.get(field) != manifest.get(field):
            raise MaterializationError(f"{arm_id}: {field} differs from packet manifest")
    if authorization.get("authorized") is not True:
        raise MaterializationError(f"{arm_id}: packet is not authorized")
    if authorization.get("receipt_sha256") != manifest.get("authorization_receipt_sha256"):
        raise MaterializationError(f"{arm_id}: authorization receipt hash mismatch")
    if authorization.get("expires_at") != manifest.get("authorization_expires_at"):
        raise MaterializationError(f"{arm_id}: authorization expiry mismatch")
    commit = arm.get("commit_full")
    try:
        resolved_commit = _resolve_commit(source_repo, commit) if isinstance(commit, str) else None
    except MaterializationError:
        resolved_commit = None
    if not isinstance(commit, str) or resolved_commit != commit:
        raise MaterializationError(f"{arm_id}: source commit is missing or does not resolve exactly")
    fixture_state = case.get("fixture_state")
    steps = fixture_state.get("steps") if isinstance(fixture_state, dict) else None
    if not isinstance(steps, list) or not steps:
        raise MaterializationError(f"{arm_id}: fixture setup steps are missing")
    ops = [step.get("op") for step in steps if isinstance(step, dict)]
    if len(ops) != len(steps) or any(op not in SUPPORTED_SETUP_OPS for op in ops):
        raise MaterializationError(f"{arm_id}: unsupported setup operation")
    expected_ids = fixture_state.get("expected_ids")
    if not isinstance(expected_ids, dict) or any(
        not isinstance(value, str) or ID_RE.fullmatch(value) is None
        for value in expected_ids.values()
    ):
        raise MaterializationError(f"{arm_id}: expected IDs violate frozen digit grammar")


class PclRunner:
    def __init__(self, source_root: Path, project_root: Path) -> None:
        self.source_root = source_root
        self.project_root = project_root
        self.log: list[dict[str, Any]] = []

    def run(
        self,
        args: list[str],
        *,
        label: str,
        expected_codes: set[int] | None = None,
    ) -> Any:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.source_root / "src")
        env.update(
            {
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NO_COLOR": "1",
                "PYTHONHASHSEED": "0",
                "TZ": "UTC",
            }
        )
        command = [sys.executable, "-m", "pcl", *args]
        result = subprocess.run(
            command,
            cwd=self.project_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        allowed = expected_codes or {0}
        payload: Any = None
        if result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                payload = result.stdout.strip()
        self.log.append(
            {
                "label": label,
                "argv": ["python", "-m", "pcl", *_display_args(args, self.project_root)],
                "exit_code": result.returncode,
                "stdout": _normalize(payload, self.project_root),
                "stderr": _normalize(result.stderr.strip(), self.project_root),
            }
        )
        if result.returncode not in allowed:
            raise MaterializationError(
                f"{label} failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
            )
        return payload


def _display_args(args: list[str], project_root: Path) -> list[str]:
    return ["<PROJECT_ROOT>" if value == str(project_root) else value for value in args]


def _normalize(value: Any, project_root: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize(item, project_root)
            for key, item in sorted(value.items())
            if key not in DYNAMIC_COLUMNS and key not in {"projection"}
        }
    if isinstance(value, list):
        return [_normalize(item, project_root) for item in value]
    if isinstance(value, str):
        normalized = value.replace(str(project_root), "<PROJECT_ROOT>").replace(
            str(project_root.resolve()), "<PROJECT_ROOT>"
        )
        if TIMESTAMP_RE.fullmatch(normalized):
            return "<TIMESTAMP>"
        if EVENT_ID_RE.fullmatch(normalized):
            return "<EVENT_ID>"
        return normalized
    return value


def _clone_source(source_repo: Path, destination: Path, commit: str) -> None:
    result = subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-checkout", str(source_repo), str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise MaterializationError(f"git clone failed: {result.stderr.strip()}")
    _git(destination, "checkout", "--quiet", "--detach", commit)
    if _resolve_commit(destination, "HEAD") != commit:
        raise MaterializationError(f"source checkout commit mismatch at {destination}")


def _command_args(step: dict[str, Any], project_root: Path) -> list[str]:
    command = step.get("command")
    if not isinstance(command, str):
        raise MaterializationError("setup command must be a string")
    tokens = shlex.split(command)
    if not tokens or tokens[0] != "pcl":
        raise MaterializationError(f"unsupported setup command: {command}")
    tokens = [str(project_root) if token == "<root>" else token for token in tokens[1:]]
    if step["op"] == "pcl_init":
        return [*tokens, "--json"]
    return ["--root", str(project_root), "--json", *tokens]


def _assert_produced_id(payload: Any, expected: str, label: str) -> None:
    observed = payload.get("id") if isinstance(payload, dict) else None
    if (
        observed != expected
        or not isinstance(observed, str)
        or ENTITY_ID_RE.fullmatch(observed) is None
    ):
        raise MaterializationError(f"{label}: expected produced ID {expected}, observed {observed!r}")


def _seed_mixed_findings(
    runner: PclRunner,
    legacy_runner: PclRunner,
    project_root: Path,
) -> None:
    legacy_steps = [
        ["--root", str(project_root), "--json", "feature", "add", "--name", "Synthetic mixed proof feature", "--surface", "eval"],
        ["--root", str(project_root), "--json", "story", "draft", "--feature", "F-0001", "--actor", "operator", "--goal", "classify proof", "--expected-behavior", "active and historical proof remain distinct"],
        ["--root", str(project_root), "--json", "story", "review", "US-0001", "--summary", "Synthetic fixture review"],
        ["--root", str(project_root), "--json", "story", "approve", "US-0001", "--summary", "Synthetic fixture approval"],
        ["--root", str(project_root), "--json", "test", "plan", "--feature", "F-0001", "--story", "US-0001", "--type", "acceptance", "--scenario", "synthetic mixed proof", "--expected", "active and historical proof remain visible"],
        ["--root", str(project_root), "--json", "test", "pass", "TC-0001", "--summary", "Synthetic released-runtime pass", "--evidence", "legacy-inline-proof"],
        ["--root", str(project_root), "--json", "defect", "open", "--feature", "F-0001", "--severity", "medium", "--expected", "no active proof gap", "--actual", "active synthetic proof gap"],
        ["--root", str(project_root), "--json", "feature", "status", "F-0001", "--status", "done", "--summary", "Synthetic legacy terminal state", "--evidence", "legacy-feature-proof"],
    ]
    expected = ["F-0001", "US-0001", None, None, "TC-0001", None, "D-0001", None]
    for index, (args, expected_id) in enumerate(zip(legacy_steps, expected, strict=True), start=1):
        payload = legacy_runner.run(args, label=f"mixed_legacy_{index:02d}")
        if expected_id:
            _assert_produced_id(payload, expected_id, f"mixed_legacy_{index:02d}")
    migration = runner.run(
        ["--root", str(project_root), "--json", "migrate", "apply"],
        label="mixed_supported_migration",
    )
    applied = migration.get("applied") if isinstance(migration, dict) else None
    if not isinstance(applied, list) or [item.get("version") for item in applied] != [8]:
        raise MaterializationError("mixed fixture must apply exactly supported migration 008")
    runner.run(
        ["init", "--target", str(project_root), "--json"],
        label="mixed_arm_runtime_init",
    )
    proof_path = project_root / "synthetic-proof.txt"
    proof_path.write_text("healthy synthetic proof\n", encoding="utf-8")
    evidence = runner.run(
        ["--root", str(project_root), "--json", "evidence", "add", "--file", proof_path.name, "--summary", "Healthy synthetic test proof", "--copy"],
        label="mixed_add_healthy_evidence",
    )
    evidence_id = evidence.get("evidence", {}).get("id") if isinstance(evidence, dict) else None
    if evidence_id != "E-0003":
        raise MaterializationError(f"mixed fixture expected E-0003, observed {evidence_id!r}")
    runner.run(
        ["--root", str(project_root), "--json", "test", "link", "TC-0001", "--story", "US-0001", "--evidence-id", "E-0003", "--summary", "Bind migrated synthetic proof"],
        label="mixed_bind_healthy_evidence",
    )
    validation = runner.run(
        ["--root", str(project_root), "--json", "validate", "--strict"],
        label="mixed_validate_expected_findings",
    )
    observed_codes = [item.get("code") for item in validation.get("findings", [])]
    if observed_codes != ["feature_done_open_defects", "feature_done_evidence_required"]:
        raise MaterializationError(
            "mixed fixture did not produce the exact active/historical finding families"
        )
    counts = validation.get("finding_counts")
    if counts is not None and counts != {"active": 1, "historical": 1}:
        raise MaterializationError("mixed fixture did not classify active=1 and historical=1")


def _semantic_snapshot(runner: PclRunner, project_root: Path) -> dict[str, Any]:
    runner.run(
        ["--root", str(project_root), "--json", "export", "csv"],
        label="semantic_export",
    )
    export_dir = project_root / ".project-loop" / "exports"
    tables: dict[str, list[dict[str, str]]] = {}
    for name in sorted(SEMANTIC_EXPORTS):
        path = export_dir / name
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            rows = []
            for row in csv.DictReader(handle):
                rows.append(
                    {
                        key: str(_normalize(value, project_root))
                        for key, value in sorted(row.items())
                        if key not in DYNAMIC_COLUMNS
                    }
                )
        tables[name] = rows
    validation = runner.run(
        ["--root", str(project_root), "--json", "validate", "--strict"],
        label="final_validate",
    )
    findings = [
        {
            "code": item.get("code"),
            "entity": item.get("entity"),
            "proof_scope": item.get("proof_scope"),
            "severity": item.get("severity"),
        }
        for item in validation.get("findings", [])
    ]
    return {"tables": tables, "findings": findings, "finding_counts": validation.get("finding_counts")}


def _consumer_brief(
    packet: dict[str, Any],
    project_root: Path,
    source_root: Path,
    handoff_path: Path | None,
    result_path: Path,
) -> dict[str, Any]:
    case = packet["case"]
    fixture_state = case["fixture_state"]
    return {
        "contract_version": CONSUMER_BRIEF_CONTRACT,
        "arm_id": packet["arm"]["arm_id"],
        "case_id": case["id"],
        "condition": packet["arm"]["condition"],
        "source_commit": packet["arm"]["commit_full"],
        "project_root": str(project_root),
        "runtime_source_root": str(source_root),
        "prompt": case["prompt"],
        "acceptance_oracle": case["acceptance_oracle"],
        "allowed_context": case["allowed_context"],
        "forbidden_context": case["forbidden_context"],
        "stop_conditions": case["stop_conditions"],
        "fixture": {
            "kind": fixture_state["kind"],
            "expected_ids": fixture_state["expected_ids"],
            "roles": fixture_state["roles"],
        },
        "handoff_packet": None if handoff_path is None else str(handoff_path),
        "result": {
            "path": str(result_path),
            "required_fields": packet["result_contract"]["required_fields"],
            "outcome_enum": packet["result_contract"]["outcome_enum"],
        },
        "measurement_boundary": {
            "starts_after_materialization": True,
            "exclude_setup_and_handoff_generation": True,
        },
    }


def materialize(packet_manifest: Path, output_dir: Path, source_repo: Path) -> dict[str, Any]:
    source_repo = source_repo.resolve()
    output_dir = output_dir.resolve()
    packets = _preflight(packet_manifest.resolve(), source_repo, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    legacy_source = output_dir / "released-runtime-v0.3.0"
    _clone_source(source_repo, legacy_source, RELEASED_LEGACY_COMMIT)

    entries: list[dict[str, Any]] = []
    snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    for packet in packets:
        arm = packet["arm"]
        case = packet["case"]
        arm_id = arm["arm_id"]
        arm_dir = output_dir / "arms" / arm_id
        source_root = arm_dir / "source"
        project_root = arm_dir / "project"
        source_root.parent.mkdir(parents=True, exist_ok=False)
        project_root.mkdir()
        _clone_source(source_repo, source_root, arm["commit_full"])
        skill_path = source_root / ".agents" / "skills" / "project-control-loop" / "SKILL.md"
        if not skill_path.is_file() or skill_path.stat().st_size != arm["loaded_skill_bytes"]:
            raise MaterializationError(f"{arm_id}: loaded Skill bytes differ from frozen arm")

        runner = PclRunner(source_root, project_root)
        legacy_runner = PclRunner(legacy_source, project_root)
        produced_ids: list[str] = []
        handoff_path: Path | None = None
        steps = case["fixture_state"]["steps"]
        for step in steps:
            op = step["op"]
            if case["id"] == "LHA-003" and op in {"pcl_init", "goal_create", "task_create"}:
                payload = legacy_runner.run(
                    _command_args(step, project_root),
                    label=f"setup_{op}",
                )
            elif op in {"pcl_init", "goal_create", "task_create", "feature_add", "story_draft"}:
                payload = runner.run(_command_args(step, project_root), label=f"setup_{op}")
            elif op == "seed_mixed_findings":
                _seed_mixed_findings(runner, legacy_runner, project_root)
                continue
            elif op == "decision_open":
                payload = runner.run(
                    ["--root", str(project_root), "--json", "decision", "open", "--question", "Should the LHA-007 target proceed?", "--recommendation", "Human operator must decide; keep this decision open."],
                    label="setup_decision_open",
                )
            elif op == "handoff_packet":
                target = case["fixture_state"]["roles"].get("task_id") or case["fixture_state"]["roles"].get("goal_id")
                if not isinstance(target, str) or ID_RE.fullmatch(target) is None:
                    raise MaterializationError(f"{arm_id}: invalid handoff target")
                handoff_path = arm_dir / "handoff-packet.json"
                runner.run(
                    ["--root", str(project_root), "--json", "resume", "--target", target, "--format", "json", "--output", str(handoff_path)],
                    label="setup_handoff_packet",
                )
                if not handoff_path.is_file():
                    raise MaterializationError(f"{arm_id}: handoff packet was not written")
                continue
            else:
                raise MaterializationError(f"{arm_id}: unsupported setup operation {op}")
            expected_id = step.get("produces")
            if isinstance(expected_id, str) and ID_RE.fullmatch(expected_id):
                _assert_produced_id(payload, expected_id, f"{arm_id}:{op}")
                produced_ids.append(expected_id)

        expected_ids = sorted(set(case["fixture_state"]["expected_ids"].values()))
        if sorted(produced_ids) != expected_ids:
            raise MaterializationError(
                f"{arm_id}: produced IDs {sorted(produced_ids)} do not match expected {expected_ids}"
            )
        if case["id"] == "LHA-007":
            decisions = runner.run(
                ["--root", str(project_root), "--json", "decision", "list", "--status", "open"],
                label="verify_open_decision",
            )
            if not _contains_entity(decisions, "DEC-0001", status="open"):
                raise MaterializationError(f"{arm_id}: DEC-0001 is not open")
        if case["id"] == "LHA-008":
            story = runner.run(
                ["--root", str(project_root), "--json", "story", "read", "US-0001"],
                label="verify_draft_story",
            )
            if story.get("story", {}).get("status") != "draft":
                raise MaterializationError(f"{arm_id}: US-0001 is not draft")

        snapshot = _semantic_snapshot(runner, project_root)
        snapshots[(case["id"], arm["condition"])] = snapshot
        snapshot_path = arm_dir / "semantic-snapshot.json"
        _write_json(snapshot_path, snapshot)
        setup_log = [*legacy_runner.log, *runner.log]
        setup_log_path = arm_dir / "setup-command-log.json"
        _write_json(setup_log_path, setup_log)
        result_path = arm_dir / "results" / packet["result_contract"]["result_path"]
        result_path.parent.mkdir()
        brief = _consumer_brief(packet, project_root, source_root, handoff_path, result_path)
        brief_path = arm_dir / "consumer-brief.json"
        _write_json(brief_path, brief)
        entries.append(
            {
                "arm_id": arm_id,
                "case_id": case["id"],
                "condition": arm["condition"],
                "root": str(project_root),
                "source_root": str(source_root),
                "source_commit": arm["commit_full"],
                "packet_path": packet["_packet_path"],
                "packet_sha256": packet["_packet_sha256"],
                "authorization_receipt_sha256": packet["authorization"]["receipt_sha256"],
                "entity_id_mapping": case["fixture_state"]["expected_ids"],
                "setup_command_log": str(setup_log_path),
                "setup_command_log_sha256": _sha256(setup_log_path),
                "handoff_packet": None if handoff_path is None else str(handoff_path),
                "handoff_packet_sha256": None if handoff_path is None else _sha256(handoff_path),
                "consumer_brief": str(brief_path),
                "consumer_brief_sha256": _sha256(brief_path),
                "semantic_snapshot_sha256": _sha256(snapshot_path),
                "loaded_skill_sha256": _sha256(skill_path),
            }
        )

    pair_equivalence: list[dict[str, Any]] = []
    for case_number in range(1, 9):
        case_id = f"LHA-{case_number:03d}"
        baseline = snapshots[(case_id, "baseline")]
        treatment = snapshots[(case_id, "treatment")]
        equivalent = _equivalence_projection(baseline) == _equivalence_projection(treatment)
        pair_equivalence.append({"case_id": case_id, "equivalent": equivalent})
        if not equivalent:
            raise MaterializationError(f"{case_id}: baseline/treatment semantic state differs")

    manifest = {
        "contract_version": MATERIALIZATION_CONTRACT,
        "packet_manifest": str(packet_manifest.resolve()),
        "packet_manifest_sha256": _sha256(packet_manifest.resolve()),
        "authorization_receipt_sha256": entries[0]["authorization_receipt_sha256"],
        "released_legacy_runtime": {
            "ref": RELEASED_LEGACY_REF,
            "commit": RELEASED_LEGACY_COMMIT,
            "source_root": str(legacy_source),
        },
        "root_count": len(entries),
        "arms": entries,
        "pair_semantic_equivalence": pair_equivalence,
        "models_called": False,
        "cockpit_sessions_launched": False,
        "measurement_boundary": {
            "setup_commands_counted": False,
            "handoff_generation_counted": False,
            "consumer_session_started": False,
        },
    }
    manifest_path = output_dir / "materialization-manifest.json"
    _write_json(manifest_path, manifest)
    return manifest


def _equivalence_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "tables": snapshot["tables"],
        "findings": [
            {
                "code": item["code"],
                "entity": item["entity"],
                "severity": item["severity"],
            }
            for item in snapshot["findings"]
        ],
    }


def _contains_entity(payload: Any, entity_id: str, *, status: str) -> bool:
    if not isinstance(payload, dict):
        return False
    for value in payload.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("id") == entity_id and item.get("status") == status:
                    return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the 16 frozen layered-harness ablation arms without launching models."
    )
    parser.add_argument("--packet-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        manifest = materialize(args.packet_manifest, args.output_dir, args.source_repo)
    except MaterializationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "manifest": manifest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
