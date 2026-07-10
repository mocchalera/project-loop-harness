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
