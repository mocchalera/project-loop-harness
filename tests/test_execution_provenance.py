from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from pcl.cli import main
from pcl.db import connect
from pcl.errors import PclError
from pcl.evidence import inspect_skill_files
from pcl.paths import ProjectPaths


def _json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json(capsys)


def _assert_no_provenance(root: Path) -> None:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM evidence WHERE type = 'execution_provenance'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM evidence_links WHERE link_role = 'execution_provenance'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM events WHERE event_type = 'work_started'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM outbox_records WHERE event_id IN (SELECT id FROM events WHERE event_type = 'work_started')").fetchone()[0] == 0
    finally:
        conn.close()
    directory = root / ".project-loop" / "evidence" / "execution-provenance"
    assert not directory.exists() or list(directory.iterdir()) == []
    assert "execution_provenance" not in (root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("kind,code", [
    ("missing", "skill_path_missing"),
    ("directory", "skill_path_not_file"),
    ("unreadable", "skill_path_unreadable"),
])
def test_skill_input_failures_are_typed_and_zero_mutation(tmp_path: Path, capsys, kind: str, code: str) -> None:
    root = tmp_path / "project"
    skill = tmp_path / "skill"
    if kind == "directory":
        skill.mkdir()
    elif kind == "unreadable":
        skill.write_text("secret", encoding="utf-8")
        skill.chmod(0)
    assert main(["--root", str(root), "start", "No mutation", "--skill", str(skill), "--json"]) == 2
    payload = _json(capsys)
    assert payload["error"]["code"] == code
    assert str(skill.resolve(strict=False)) not in json.dumps(payload)
    assert not root.exists()


def test_changed_during_read_is_typed_and_zero_mutation(tmp_path: Path, monkeypatch) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text("before", encoding="utf-8")
    original_open = Path.open

    class ChangingReader:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def fileno(self):
            return self.stream.fileno()
        def read(self):
            data = self.stream.read()
            os.utime(skill, ns=(skill.stat().st_atime_ns, skill.stat().st_mtime_ns + 1_000_000))
            return data

    def changing_open(path: Path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return ChangingReader(stream) if path == skill and args and args[0] == "rb" else stream

    monkeypatch.setattr(Path, "open", changing_open)
    with pytest.raises(PclError) as exc:
        inspect_skill_files(ProjectPaths(tmp_path / "project"), [str(skill)])
    assert exc.value.code == "skill_changed_during_read"
    assert not (tmp_path / "project").exists()


def test_same_inode_size_rewrite_with_restored_mtime_is_changed_during_read(
    tmp_path: Path, monkeypatch,
) -> None:
    skill = tmp_path / "outside" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_bytes(b"before")
    original_open = Path.open
    original_stat = skill.stat()

    class RewritingReader:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def fileno(self):
            return self.stream.fileno()
        def read(self):
            data = self.stream.read()
            with original_open(skill, "r+b") as writer:
                writer.seek(0)
                writer.write(b"after!")
                writer.flush()
                os.fsync(writer.fileno())
            os.utime(skill, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            return data

    def rewriting_open(path: Path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return RewritingReader(stream) if path == skill and args and args[0] == "rb" else stream

    monkeypatch.setattr(Path, "open", rewriting_open)
    with pytest.raises(PclError) as exc:
        inspect_skill_files(ProjectPaths(tmp_path / "project"), [str(skill)])
    assert exc.value.code == "skill_changed_during_read"
    assert str(skill.resolve()) not in str(exc.value)
    assert str(skill.resolve()) not in json.dumps(exc.value.to_dict())


@pytest.mark.parametrize("fault", ["write", "temp_verify", "link", "event"])
def test_provenance_failures_cleanup_artifact_rows_links_event_outbox_and_jsonl(
    tmp_path: Path, capsys, monkeypatch, fault: str,
) -> None:
    _init(tmp_path, capsys)
    skill = tmp_path / "SKILL.md"
    skill.write_text("skill", encoding="utf-8")
    if fault == "write":
        monkeypatch.setattr("pcl.start.write_provenance_artifact", lambda *a, **k: (_ for _ in ()).throw(OSError("write failed")))
        expected = "data_store_error"
    elif fault == "temp_verify":
        original_read = Path.read_bytes
        def corrupt_temp(path: Path):
            return b"corrupt" if path.suffix == ".tmp" else original_read(path)
        monkeypatch.setattr(Path, "read_bytes", corrupt_temp)
        expected = "data_store_error"
    else:
        target = "pcl.start.insert_evidence_link" if fault == "link" else "pcl.start.append_event"
        def fail(*args, **kwargs):
            raise PclError("injected", code=f"injected_{fault}", exit_code=2)
        monkeypatch.setattr(target, fail)
        expected = f"injected_{fault}"
    assert main(["--root", str(tmp_path), "start", "Fault", "--skill", str(skill), "--json"]) == (4 if fault in {"write", "temp_verify"} else 2)
    assert _json(capsys)["error"]["code"] == expected
    _assert_no_provenance(tmp_path)


def _started(root: Path, capsys) -> tuple[Path, dict]:
    skill = root.parent / f"outside-{root.name}" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text("outside skill", encoding="utf-8")
    assert main(["--root", str(root), "start", "Inspect", "--skill", str(skill), "--json"]) == 0
    return skill, _json(capsys)["result"]["provenance"]


@pytest.mark.parametrize("fault,health", [
    ("wrong_type", "wrong_evidence_type"),
    ("wrong_path", "wrong_evidence_path"),
    ("missing_anchor", "anchor_missing"),
    ("missing_event", "anchor_missing"),
    ("missing_artifact", "artifact_missing"),
    ("wrong_link", "task_link_mismatch"),
])
def test_inspection_fails_closed_for_broken_trust_chain(tmp_path: Path, capsys, fault: str, health: str) -> None:
    root = tmp_path / "project"
    _, provenance = _started(root, capsys)
    conn = connect(root / ".project-loop" / "project.db")
    try:
        if fault == "wrong_type":
            conn.execute("UPDATE evidence SET type = 'adhoc_artifact' WHERE id = ?", (provenance["evidence_id"],))
        elif fault == "wrong_path":
            conn.execute("UPDATE evidence SET path = 'elsewhere.json' WHERE id = ?", (provenance["evidence_id"],))
        elif fault == "missing_anchor":
            row = conn.execute("SELECT id, payload_json FROM events WHERE event_type = 'work_started'").fetchone()
            payload = json.loads(row["payload_json"])
            payload.pop("execution_provenance")
            conn.execute("UPDATE events SET payload_json = ? WHERE id = ?", (json.dumps(payload), row["id"]))
        elif fault == "missing_event":
            conn.execute("UPDATE events SET event_type = 'work_started_missing' WHERE event_type = 'work_started'")
        elif fault == "wrong_link":
            conn.execute("UPDATE evidence_links SET link_role = 'supporting' WHERE evidence_id = ?", (provenance["evidence_id"],))
        conn.commit()
    finally:
        conn.close()
    if fault == "missing_artifact":
        (root / provenance["path"]).unlink()
    assert main(["--root", str(root), "evidence", "show", provenance["evidence_id"], "--json"]) == 0
    assessment = _json(capsys)["evidence"]["provenance"]
    assert assessment["artifact_health"] == health
    assert assessment["skills"] == []


def test_verified_artifact_reports_unreadable_skill(tmp_path: Path, capsys) -> None:
    root = tmp_path / "project"
    skill, provenance = _started(root, capsys)
    skill.chmod(0)
    assert main(["--root", str(root), "evidence", "show", provenance["evidence_id"], "--json"]) == 0
    assert _json(capsys)["evidence"]["provenance"]["skills"][0]["health"] == "unreadable"


@pytest.mark.parametrize("fault,health", [
    ("event_target", "anchor_target_mismatch"),
    ("artifact_target", "artifact_target_mismatch"),
])
def test_inspection_requires_event_link_and_artifact_target_consistency(
    tmp_path: Path, capsys, fault: str, health: str,
) -> None:
    root = tmp_path / "project"
    _, provenance = _started(root, capsys)
    artifact = root / provenance["path"]
    conn = connect(root / ".project-loop" / "project.db")
    try:
        row = conn.execute("SELECT id, payload_json FROM events WHERE event_type = 'work_started'").fetchone()
        payload = json.loads(row["payload_json"])
        if fault == "event_target":
            payload["execution_provenance"]["target"] = {"type": "task", "id": "T-9999"}
        else:
            document = json.loads(artifact.read_bytes())
            document["target"] = {"type": "task", "id": "T-9999"}
            raw = (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            artifact.write_bytes(raw)
            payload["execution_provenance"]["artifact_sha256"] = hashlib.sha256(raw).hexdigest()
        conn.execute("UPDATE events SET payload_json = ? WHERE id = ?", (json.dumps(payload), row["id"]))
        conn.commit()
    finally:
        conn.close()
    assert main(["--root", str(root), "evidence", "show", provenance["evidence_id"], "--json"]) == 0
    assessment = _json(capsys)["evidence"]["provenance"]
    assert assessment["artifact_health"] == health
    assert assessment["skills"] == []


def test_artifact_symlink_to_matching_valid_bytes_is_rejected_without_following(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    root = tmp_path / "project"
    _, provenance = _started(root, capsys)
    artifact = root / provenance["path"]
    matching = tmp_path / "matching-valid.json"
    matching.write_bytes(artifact.read_bytes())
    artifact.unlink()
    artifact.symlink_to(matching)
    original_open = os.open
    followed = False

    def guarded_open(path, flags, *args, **kwargs):
        nonlocal followed
        if Path(path) == artifact:
            followed = True
            raise AssertionError("artifact symlink was opened")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("pcl.evidence.os.open", guarded_open)
    assert main(["--root", str(root), "evidence", "show", provenance["evidence_id"], "--json"]) == 0
    assessment = _json(capsys)["evidence"]["provenance"]
    assert assessment["artifact_health"] == "artifact_symlink"
    assert assessment["skills"] == []
    assert followed is False


@pytest.mark.parametrize("artifact_kind,health", [
    ("dangling_symlink", "artifact_symlink"),
    ("directory", "artifact_not_regular"),
])
def test_artifact_dangling_symlink_and_other_type_fail_closed(
    tmp_path: Path, capsys, artifact_kind: str, health: str,
) -> None:
    root = tmp_path / "project"
    _, provenance = _started(root, capsys)
    artifact = root / provenance["path"]
    artifact.unlink()
    if artifact_kind == "dangling_symlink":
        artifact.symlink_to(tmp_path / "absent-artifact.json")
    else:
        artifact.mkdir()
    assert main(["--root", str(root), "evidence", "show", provenance["evidence_id"], "--json"]) == 0
    assessment = _json(capsys)["evidence"]["provenance"]
    assert assessment["artifact_health"] == health
    assert assessment["skills"] == []


@pytest.mark.parametrize("collision", ["dangling_artifact", "artifact_directory_symlink", "provenance_directory_symlink"])
def test_provenance_symlink_collisions_are_typed_zero_mutation_and_preserved(
    tmp_path: Path, capsys, collision: str,
) -> None:
    _init(tmp_path, capsys)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        before = tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "goals", "tasks", "evidence", "evidence_links", "events", "outbox_records",
        ))
    finally:
        conn.close()
    skill = tmp_path / "SKILL.md"
    skill.write_text("skill", encoding="utf-8")
    provenance_dir = tmp_path / ".project-loop" / "evidence" / "execution-provenance"
    target_dir = tmp_path / "collision-target"
    target_dir.mkdir()
    if collision == "provenance_directory_symlink":
        provenance_dir.symlink_to(target_dir, target_is_directory=True)
    else:
        provenance_dir.mkdir()
        artifact = provenance_dir / "E-0002.json"
        if collision == "dangling_artifact":
            artifact.symlink_to(tmp_path / "absent.json")
        else:
            artifact.symlink_to(target_dir, target_is_directory=True)
    assert main(["--root", str(tmp_path), "start", "Collision", "--skill", str(skill), "--json"]) == 4
    payload = _json(capsys)
    assert payload["error"]["code"] == "data_store_error"
    assert str(skill.resolve()) not in json.dumps(payload)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        after = tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "goals", "tasks", "evidence", "evidence_links", "events", "outbox_records",
        ))
        assert after == before
        assert conn.execute("SELECT COUNT(*) FROM evidence WHERE type = 'execution_provenance'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM evidence_links WHERE link_role = 'execution_provenance'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM events WHERE event_type = 'work_started'").fetchone()[0] == 0
    finally:
        conn.close()
    assert provenance_dir.is_symlink() if collision == "provenance_directory_symlink" else (provenance_dir / "E-0002.json").is_symlink()


def test_noninspection_surfaces_redact_outside_skill_absolute_path(tmp_path: Path, capsys) -> None:
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "README.md").write_text("project\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    skill, provenance = _started(root, capsys)
    absolute = str(skill.resolve())
    assert main(["--root", str(root), "report", "goal", "G-0001", "--json"]) == 0
    report_payload = _json(capsys)
    assert absolute not in json.dumps(report_payload)
    report_path = root / report_payload["path"]
    assert absolute not in report_path.read_text(encoding="utf-8")
    assert main(["--root", str(root), "render", "--json"]) == 0
    _json(capsys)
    assert absolute not in (root / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(encoding="utf-8")
    assert absolute not in (root / ".project-loop" / "dashboard" / "dashboard.html").read_text(encoding="utf-8")
    assert main(["--root", str(root), "export", "csv", "--json"]) == 0
    exports = _json(capsys)["paths"]
    assert all(absolute not in Path(path).read_text(encoding="utf-8") for path in exports)
    assert main(["--root", str(root), "finish", "--emit-packet", "--dry-run", "--task", "T-0001", "--json"]) == 0
    assert absolute not in json.dumps(_json(capsys))
    assert main(["--root", str(root), "start", "Ordinary", "--new", "--skill", str(skill)]) == 0
    ordinary = capsys.readouterr()
    assert absolute not in ordinary.out + ordinary.err
    assert main(["--root", str(root), "evidence", "show", provenance["evidence_id"], "--json"]) == 0
    assert absolute in json.dumps(_json(capsys))
