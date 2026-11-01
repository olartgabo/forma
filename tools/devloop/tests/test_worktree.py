"""Offline regression tests for dedicated devloop worktree preparation.

Each test builds a throwaway repository with a local bare ``origin``; no
network or provider is involved. Sentinel contents prove that a rejected
path is never reset or cleaned.
"""

import os
import subprocess
from pathlib import Path

import devloop
import pytest


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"git {' '.join(args)} failed:\n{proc.stdout}{proc.stderr}"
    )
    return proc.stdout + proc.stderr


@pytest.fixture
def parent_repo(tmp_path, monkeypatch):
    """A parent checkout with a local origin/main and a dedicated state dir."""
    repo = tmp_path / "repo"
    remote = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", str(remote))
    git(tmp_path, "init", "-b", "main", str(repo))
    git(repo, "config", "user.email", "devloop@example.invalid")
    git(repo, "config", "user.name", "Devloop Test")
    (repo / "tracked.txt").write_text("committed\n", encoding="utf-8")
    git(repo, "add", "tracked.txt")
    git(repo, "commit", "-m", "initial")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")

    state_dir = repo / ".devloop"
    worktree = state_dir / "worktree"
    monkeypatch.setattr(devloop, "ROOT", repo)
    monkeypatch.setattr(devloop, "STATE_DIR", state_dir)
    monkeypatch.setattr(devloop, "WORKTREE", worktree)
    return repo, worktree


def dirty_parent(repo: Path) -> None:
    (repo / "tracked.txt").write_text("dirty parent sentinel\n", encoding="utf-8")
    (repo / "parent-untracked.txt").write_text(
        "untracked parent sentinel\n", encoding="utf-8"
    )


def assert_parent_intact(repo: Path) -> None:
    assert (repo / "tracked.txt").read_text(
        encoding="utf-8"
    ) == "dirty parent sentinel\n"
    assert (repo / "parent-untracked.txt").read_text(
        encoding="utf-8"
    ) == "untracked parent sentinel\n"


def test_ordinary_nested_directory_is_rejected_and_parent_stays_intact(parent_repo):
    repo, worktree = parent_repo
    worktree.mkdir(parents=True)
    (worktree / "sentinel.txt").write_text(
        "ordinary directory sentinel\n", encoding="utf-8"
    )
    dirty_parent(repo)

    # Without identity verification, git reset/clean run from this ordinary
    # nested directory would resolve to the parent and destroy both sentinels.
    with pytest.raises(RuntimeError, match="dedicated worktree"):
        devloop.prepare_worktree()

    assert_parent_intact(repo)
    assert (worktree / "sentinel.txt").read_text(encoding="utf-8") == (
        "ordinary directory sentinel\n"
    )


def test_new_registered_worktree_is_created_detached_and_cleanly_reused(parent_repo):
    repo, worktree = parent_repo

    devloop.prepare_worktree()

    assert worktree.is_dir()
    registered = git(repo, "worktree", "list", "--porcelain")
    assert str(worktree) in registered or worktree.as_posix() in registered
    # Created detached at origin/main, as the runner expects.
    assert (
        git(worktree, "rev-parse", "HEAD").strip()
        == git(repo, "rev-parse", "origin/main").strip()
    )
    assert (
        subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"],
            cwd=worktree,
            capture_output=True,
            text=True,
        ).returncode
        != 0
    )

    # A clean local commit proves reuse does not reset the worktree away.
    git(worktree, "config", "user.email", "devloop@example.invalid")
    git(worktree, "config", "user.name", "Devloop Test")
    (worktree / "kept.txt").write_text("kept on reuse\n", encoding="utf-8")
    git(worktree, "add", "kept.txt")
    git(worktree, "commit", "-m", "worktree-local commit")
    head_before = git(worktree, "rev-parse", "HEAD").strip()

    devloop.prepare_worktree()

    assert git(worktree, "rev-parse", "HEAD").strip() == head_before
    assert (worktree / "kept.txt").read_text(encoding="utf-8") == "kept on reuse\n"
    assert git(worktree, "status", "--porcelain", "--untracked-files=all").strip() == ""


def test_dirty_registered_worktree_is_rejected_without_deleting_data(parent_repo):
    _, worktree = parent_repo
    devloop.prepare_worktree()
    (worktree / "tracked.txt").write_text("dirty worktree sentinel\n", encoding="utf-8")
    (worktree / "untracked.txt").write_text(
        "untracked worktree sentinel\n", encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="dirty"):
        devloop.prepare_worktree()

    assert (worktree / "tracked.txt").read_text(encoding="utf-8") == (
        "dirty worktree sentinel\n"
    )
    assert (worktree / "untracked.txt").read_text(encoding="utf-8") == (
        "untracked worktree sentinel\n"
    )


def test_staged_only_dirty_worktree_is_rejected_without_deleting_data(parent_repo):
    _, worktree = parent_repo
    devloop.prepare_worktree()
    (worktree / "tracked.txt").write_text(
        "staged worktree sentinel\n", encoding="utf-8"
    )
    git(worktree, "add", "tracked.txt")
    assert (
        git(worktree, "status", "--porcelain", "--untracked-files=all").strip()
        == "M  tracked.txt"
    )

    with pytest.raises(RuntimeError, match="dirty"):
        devloop.prepare_worktree()

    assert (worktree / "tracked.txt").read_text(encoding="utf-8") == (
        "staged worktree sentinel\n"
    )
    assert (
        git(worktree, "status", "--porcelain", "--untracked-files=all").strip()
        == "M  tracked.txt"
    )


def test_untracked_only_dirty_worktree_is_rejected_without_deleting_data(parent_repo):
    _, worktree = parent_repo
    devloop.prepare_worktree()
    (worktree / "untracked.txt").write_text(
        "untracked worktree sentinel\n", encoding="utf-8"
    )
    assert (
        git(worktree, "status", "--porcelain", "--untracked-files=all").strip()
        == "?? untracked.txt"
    )

    with pytest.raises(RuntimeError, match="dirty"):
        devloop.prepare_worktree()

    assert (worktree / "untracked.txt").read_text(encoding="utf-8") == (
        "untracked worktree sentinel\n"
    )


def test_worktree_from_wrong_repository_is_rejected_without_deleting_data(
    parent_repo, tmp_path
):
    repo, worktree = parent_repo
    other = tmp_path / "other"
    git(tmp_path, "init", "-b", "main", str(other))
    git(other, "config", "user.email", "devloop@example.invalid")
    git(other, "config", "user.name", "Devloop Test")
    (other / "tracked.txt").write_text("other repo committed\n", encoding="utf-8")
    git(other, "add", "tracked.txt")
    git(other, "commit", "-m", "other initial")
    # Place the foreign checkout exactly at the dedicated path.
    worktree.parent.mkdir(parents=True)
    other.replace(worktree)
    (worktree / "untracked.txt").write_text("wrong repo sentinel\n", encoding="utf-8")
    dirty_parent(repo)

    with pytest.raises(RuntimeError, match="dedicated worktree"):
        devloop.prepare_worktree()

    assert_parent_intact(repo)
    assert (worktree / "untracked.txt").read_text(encoding="utf-8") == (
        "wrong repo sentinel\n"
    )


@pytest.mark.parametrize("alias_location", ["WORKTREE", "STATE_DIR"])
def test_symlink_alias_to_parent_is_rejected_and_parent_stays_intact(
    parent_repo, alias_location
):
    repo, worktree = parent_repo
    alias = worktree if alias_location == "WORKTREE" else worktree.parent
    if alias_location == "WORKTREE":
        worktree.parent.mkdir(parents=True)
    try:
        alias.symlink_to(repo, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        if os.name == "nt":
            subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(alias), str(repo)],
                check=True,
                capture_output=True,
            )
        else:
            pytest.skip(f"cannot create a directory symlink here: {exc}")
    dirty_parent(repo)

    with pytest.raises(RuntimeError, match="symlink or junction|dedicated worktree"):
        devloop.prepare_worktree()

    assert_parent_intact(repo)
    assert alias.is_symlink() or (hasattr(alias, "is_junction") and alias.is_junction())
