from __future__ import annotations

from pathlib import Path

from pcl.direct_spec import DirectSpecRootBinding
from pcl.paths import ProjectPaths, resolve_paths
from pcl.task_accept import accept_task

from task_accept_helpers import accept_args, prepare_acceptance, run_json, state_counts


def test_atomic_accept_uses_retained_root_proxy_without_weakening_path_checks(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    fixture = prepare_acceptance(project, capsys, test_count=2)
    retained_proxy = tmp_path / "retained-root-proxy"
    retained_proxy.symlink_to(project, target_is_directory=True)

    def bound_paths(binding: DirectSpecRootBinding) -> ProjectPaths:
        return ProjectPaths(
            root=retained_proxy,
            retained_root_descriptor=binding.descriptor,
            retained_root_identity=binding.identity,
        )

    monkeypatch.setattr(DirectSpecRootBinding, "bound_paths", bound_paths)

    result = run_json(project, capsys, *accept_args(fixture))

    assert result["ok"] is True
    assert result["mode"] == "fresh_success"
    assert result["mutation_committed"] is True


def test_linux_root_rebind_is_typed_noncommit_before_physical_commit(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    displaced = tmp_path / "displaced"
    fixture = prepare_acceptance(project, capsys, test_count=2)
    before = state_counts(project)
    from pcl import task_accept

    original = task_accept._verify_final_rows_and_events

    def rebind_after_final_rows(*args, **kwargs):
        original(*args, **kwargs)
        project.rename(displaced)
        project.mkdir()
        (project / ".project-loop").mkdir()

    monkeypatch.setattr(
        task_accept,
        "_verify_final_rows_and_events",
        rebind_after_final_rows,
    )
    monkeypatch.setattr(
        task_accept,
        "_requires_original_path_binding_at_commit",
        lambda: True,
    )

    result = accept_task(
        resolve_paths(project),
        task_id=fixture["task_id"],
        artifact_path=fixture["artifact"],
        command="pytest -q",
        summary="Acceptance verified",
        copy_files=True,
        test_ids=fixture["test_ids"],
    )

    assert result["ok"] is False
    assert result["mutation_committed"] is False
    assert result["error_code"] == "task_accept_root_changed"
    assert result["safe_to_retry_original"] is False
    assert state_counts(displaced) == before
    assert not (project / ".project-loop" / "project.db").exists()
