from __future__ import annotations

from pathlib import Path

import pytest

from mikrotik_minder_agent.gitrepo import GitRepo


def test_first_write_creates_repo_and_commits(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "configs")
    result = repo.write_and_commit("devices/a/exports/latest.rsc", "hello\n", message="first")
    assert result is not None
    assert result.lines_added == 1
    assert result.lines_removed == 0
    assert len(result.sha) >= 7
    assert (tmp_path / "configs" / "devices/a/exports/latest.rsc").read_text() == "hello\n"
    assert (tmp_path / "configs" / ".git").is_dir()


def test_unchanged_content_does_not_commit(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "configs")
    repo.write_and_commit("devices/a/exports/latest.rsc", "hello\n", message="first")
    second = repo.write_and_commit("devices/a/exports/latest.rsc", "hello\n", message="second")
    assert second is None  # no commit; content matched


def test_changed_content_reports_line_delta(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "configs")
    path = "devices/a/exports/latest.rsc"
    repo.write_and_commit(path, "a\nb\nc\n", message="first")
    updated = repo.write_and_commit(path, "a\nB\nc\nd\n", message="second")
    assert updated is not None
    # Modified line counts as 1 add + 1 remove; new line counts as 1 add.
    assert updated.lines_added == 2
    assert updated.lines_removed == 1


def test_each_device_lives_in_its_own_directory(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "configs")
    repo.write_and_commit("devices/core/exports/latest.rsc", "core-config\n", message="core")
    repo.write_and_commit("devices/edge/exports/latest.rsc", "edge-config\n", message="edge")
    assert (tmp_path / "configs/devices/core/exports/latest.rsc").exists()
    assert (tmp_path / "configs/devices/edge/exports/latest.rsc").exists()


def test_git_binary_missing_is_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import shutil as _shutil

    monkeypatch.setattr(_shutil, "which", lambda _name: None)
    with pytest.raises(Exception, match="git"):
        GitRepo(tmp_path / "x")
