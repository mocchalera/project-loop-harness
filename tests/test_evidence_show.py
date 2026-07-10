from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _fingerprint(root: Path) -> dict[str, object]:
    loop_dir = root / ".project-loop"
    return {
        str(path.relative_to(loop_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(loop_dir.rglob("*"))
        if path.is_file()
    }


def test_evidence_show_resolves_manifest_metadata_without_body_and_is_read_only(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    artifact = tmp_path / "result.txt"
    artifact.write_text("ARTIFACT_BODY_SENTINEL\n", encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "evidence", "add",
        "--file", "result.txt", "--summary", "Targeted checks",
        "--command", "python -m pytest tests/test_target.py", "--copy", "--json",
    ]) == 0
    evidence_id = _json_output(capsys)["evidence"]["id"]
    before = _fingerprint(tmp_path)

    assert main([
        "--root", str(tmp_path), "evidence", "show", evidence_id, "--json",
    ]) == 0
    payload = _json_output(capsys)

    assert payload == {
        "ok": True,
        "evidence": {
            "id": "E-0001",
            "type": "adhoc_artifact",
            "summary": "Targeted checks",
            "claimed_command": "python -m pytest tests/test_target.py",
            "recorded_path": ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json",
            "created_at": payload["evidence"]["created_at"],
            "manifest": {
                "contract_version": "adhoc-evidence/v0",
                "members": [{
                    "path": "result.txt",
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "stored_path": ".project-loop/evidence/adhoc-files/e-0001/01-result.txt",
                }],
            },
        },
    }
    assert "ARTIFACT_BODY_SENTINEL" not in json.dumps(payload)
    assert _fingerprint(tmp_path) == before


def test_evidence_show_resolves_inline_metadata_and_returns_typed_errors(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    assert main(["--root", str(tmp_path), "start", "Inline receipt", "--json"]) == 0
    evidence_id = _json_output(capsys)["result"]["created_ids"]["evidence"]
    before = _fingerprint(tmp_path)

    assert main([
        "--root", str(tmp_path), "evidence", "show", evidence_id, "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]
    assert evidence["id"] == evidence_id
    assert evidence["recorded_path"].startswith("inline:")
    assert "manifest" not in evidence
    assert _fingerprint(tmp_path) == before

    assert main([
        "--root", str(tmp_path), "evidence", "show", "E-9999", "--json",
    ]) == 2
    assert _json_output(capsys)["error"]["code"] == "evidence_not_found"
    assert main([
        "--root", str(tmp_path), "evidence", "show", "bad-id", "--json",
    ]) == 2
    assert _json_output(capsys)["error"]["code"] == "invalid_evidence_id"
    assert _fingerprint(tmp_path) == before


def test_evidence_show_execution_provenance_reports_drift_and_fails_closed_on_tamper(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    skill = tmp_path / "skill" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text("before\n", encoding="utf-8")
    root = tmp_path / "project"
    assert main(["--root", str(root), "start", "Inspect", "--skill", str(skill), "--json"]) == 0
    started = _json_output(capsys)
    provenance = started["result"]["provenance"]

    assert main(["--root", str(root), "evidence", "show", provenance["evidence_id"], "--json"]) == 0
    shown = _json_output(capsys)["evidence"]["provenance"]
    assert shown["artifact_health"] == "ok"
    assert shown["skills"][0]["health"] == "ok"

    skill.write_text("after\n", encoding="utf-8")
    assert main(["--root", str(root), "evidence", "show", provenance["evidence_id"], "--json"]) == 0
    assert _json_output(capsys)["evidence"]["provenance"]["skills"][0]["health"] == "drifted"

    artifact = root / provenance["path"]
    artifact.write_text(json.dumps({"contract_version": "execution-provenance/v1", "skills": [{"path": str(skill)}]}) + "\n")
    original_read_bytes = Path.read_bytes
    followed = False
    def guarded_read(path: Path):
        nonlocal followed
        if path == skill:
            followed = True
            raise AssertionError("unverified embedded path was followed")
        return original_read_bytes(path)
    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    assert main(["--root", str(root), "evidence", "show", provenance["evidence_id"], "--json"]) == 0
    assessment = _json_output(capsys)["evidence"]["provenance"]
    assert assessment["artifact_health"] == "artifact_hash_mismatch"
    assert assessment["skills"] == []
    assert followed is False
