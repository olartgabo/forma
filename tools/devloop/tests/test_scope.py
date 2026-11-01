import os
import subprocess
from io import BytesIO
from pathlib import Path

import devloop
import pytest
from scope import ScopeError, check_path, resolve_path


@pytest.mark.parametrize(
    "path",
    [
        "apps/api/src/forma_api/model_gateway.py.secret",
        "scripts/smoke_meta.py.bak",
        "apps/api/src/forma_api/model_gateway.py/child",
        "packages/compiler-other/file.py",
        "C:/packages/compiler/file.py",
        "C:packages/compiler/file.py",
        r"\\server\packages\compiler\file.py",
        r"\packages\compiler\file.py",
        "packages/compiler/../renderer/file.py",
        "packages/compiler/file.py:stream",
        "packages/compiler/file.py.",
        "packages/compiler/file.py ",
        "packages/compiler/.ENV.local",
        "packages/compiler/generated/types.py",
        "packages/compiler/PACKAGE-LOCK.JSON",
        "packages/compiler/invalid\x00.py",
        "packages/compiler/NUL.py",
        "packages/compiler/aux/file.py",
        "packages/compiler/key.dpapi",
        "packages/compiler/client.PEM",
        "packages/compiler/credentials.json",
        "packages/compiler/secrets/value.txt",
        "packages/compiler/token.txt",
        "packages/compiler/.ssh/id_rsa",
    ],
)
def test_invalid_paths_rejected_for_reads_and_writes(tmp_path, path):
    with pytest.raises(ScopeError):
        check_path(path)
    with pytest.raises(ScopeError):
        resolve_path(tmp_path, path)


def put(root: Path, relative: str, content: str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    return target


def test_read_context_preserves_complete_files_and_normalizes_duplicates(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(devloop, "WORKTREE", tmp_path)
    path = "packages/compiler/src/example.py"
    content = "# measured input\nvalue = 'á'\n"
    put(tmp_path, path, content)
    assert devloop.read_files([path, path.replace("/", "\\")]) == {path: content}
    assert devloop.read_files(["packages/compiler/src/new.py"]) == {}
    assert check_path("packages/compiler/test_secret_redaction.py")
    assert (
        resolve_path(tmp_path, "scripts/smoke_meta.py")
        == (tmp_path / "scripts/smoke_meta.py").resolve()
    )


@pytest.mark.parametrize(
    "relative",
    ["packages/compiler/.env", "packages/compiler/generated/private.py"],
)
def test_forbidden_context_rejected_before_any_file_open(
    tmp_path, monkeypatch, relative
):
    monkeypatch.setattr(devloop, "WORKTREE", tmp_path)
    put(tmp_path, relative, "synthetic secret must never be returned")
    permitted = "packages/compiler/src/allowed.py"
    put(tmp_path, permitted, "ordinary code")

    def forbidden_open(*args, **kwargs):
        pytest.fail("context was opened before all requested paths were validated")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(ScopeError):
        devloop.read_files([permitted, relative])


def test_absolute_external_secret_is_never_opened(tmp_path, monkeypatch):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    secret = put(tmp_path, ".env", "synthetic external secret")
    monkeypatch.setattr(devloop, "WORKTREE", worktree)
    with pytest.raises(ScopeError):
        devloop.read_files([str(secret)])


@pytest.mark.parametrize(
    "kind", ["external_file", "external_directory", "internal_secret"]
)
def test_linked_context_and_write_destinations_rejected(tmp_path, monkeypatch, kind):
    root = tmp_path / "worktree"
    root.mkdir()
    link = root / "packages/compiler/link.py"
    link.parent.mkdir(parents=True)
    if kind == "internal_secret":
        destination = put(root, "packages/compiler/.env", "synthetic secret")
    elif kind == "external_file":
        destination = put(tmp_path, "outside.py", "synthetic external secret")
    else:
        destination = tmp_path / "outside"
        destination.mkdir()
        put(destination, "file.py", "synthetic external secret")
    try:
        link.symlink_to(destination, target_is_directory=destination.is_dir())
    except (OSError, NotImplementedError) as exc:
        if os.name == "nt" and destination.is_dir():
            subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(link), str(destination)],
                check=True,
                capture_output=True,
            )
        else:
            pytest.skip(f"symlink creation unavailable: {exc}")
    relative = link.relative_to(root).as_posix()
    if destination.is_dir():
        relative += "/file.py"
    monkeypatch.setattr(devloop, "WORKTREE", root)
    with pytest.raises(ScopeError):
        devloop.read_files([relative])
    with pytest.raises(ScopeError):
        resolve_path(root, relative)
    assert destination.exists()


def test_per_file_limit_uses_bytes_and_never_truncates(tmp_path, monkeypatch):
    monkeypatch.setattr(devloop, "WORKTREE", tmp_path)
    monkeypatch.setattr(devloop, "MAX_FILE", 4)
    path = "packages/compiler/example.py"
    put(tmp_path, path, "áá")
    assert devloop.read_files([path]) == {path: "áá"}
    put(tmp_path, path, "ááá")
    with pytest.raises(ScopeError, match="context file exceeds 4 bytes"):
        devloop.read_files([path])


def test_total_limit_counts_unique_files_and_rejects_partial_context(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(devloop, "WORKTREE", tmp_path)
    monkeypatch.setattr(devloop, "MAX_TOTAL", 6)
    first, second = "packages/compiler/first.py", "packages/compiler/second.py"
    put(tmp_path, first, "abc")
    put(tmp_path, second, "def")
    assert devloop.read_files([first, first, second]) == {first: "abc", second: "def"}
    put(tmp_path, second, "defg")
    with pytest.raises(ScopeError, match="context exceeds 6 total bytes"):
        devloop.read_files([first, second])


def test_non_utf8_context_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(devloop, "WORKTREE", tmp_path)
    path = "packages/compiler/example.py"
    target = put(tmp_path, path, "")
    target.write_bytes(b"\xff")
    with pytest.raises(ScopeError, match="not UTF-8"):
        devloop.read_files([path])


def test_growth_after_stat_is_bounded_and_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(devloop, "WORKTREE", tmp_path)
    monkeypatch.setattr(devloop, "MAX_FILE", 4)
    path = "packages/compiler/example.py"
    target = put(tmp_path, path, "a")
    original_open = Path.open
    stream = BytesIO(b"abcdefghi")

    def growing_open(self, *args, **kwargs):
        if self == target and args == ("rb",):
            return stream
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", growing_open)
    with pytest.raises(ScopeError, match="context file exceeds 4 bytes"):
        devloop.read_files([path])
