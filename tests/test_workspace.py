import errno
from pathlib import Path

import pytest

from trialnexa import cli
from trialnexa.workspace import WorkspaceError, initialize_workspace


def test_exact_empty_tree(tmp_path: Path, expected_directories: set[Path]) -> None:
    root = initialize_workspace(tmp_path)
    assert root == tmp_path / "cdisc_reference"
    actual = list(tmp_path.rglob("*"))
    assert {p.relative_to(tmp_path) for p in actual} == expected_directories
    assert all(p.is_dir() for p in actual)


def test_partial_tree_and_existing_content_are_preserved(
    tmp_path: Path,
    expected_directories: set[Path],
) -> None:
    existing = tmp_path / "cdisc_reference" / "define_xml" / "v2.1" / "schemas"
    existing.mkdir(parents=True)
    imports = tmp_path / "cdisc_reference" / "cdash" / "imports"
    imports.mkdir(parents=True)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    files = [
        tmp_path / "notes.txt",
        existing / "existing.xml",
        imports / "CDASHIG_v2.3.csv",
    ]
    for file in files:
        file.write_bytes(b"preserve exactly\x00\xff")
    initialize_workspace(tmp_path)
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    initialize_workspace(tmp_path)
    after = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    assert (
        before
        == after
        == expected_directories
        | {Path("unrelated"), *(file.relative_to(tmp_path) for file in files)}
    )
    assert all(file.read_bytes() == b"preserve exactly\x00\xff" for file in files)


@pytest.mark.parametrize(
    "collision_path",
    [
        "cdisc_reference",
        "cdisc_reference/cdash",
        "cdisc_reference/cdash/imports",
        "cdisc_reference/cdash/v2.3",
        "cdisc_reference/define_xml/v2.1/schemas",
        "cdisc_reference/study_profiles",
    ],
)
def test_preflight_detects_collisions_before_creating_anything(
    collision_path: str,
    tmp_path: Path,
) -> None:
    collision = tmp_path / collision_path
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_text("preserve", encoding="utf-8")
    before = set(tmp_path.rglob("*"))
    with pytest.raises(WorkspaceError, match="non-directory") as error:
        initialize_workspace(tmp_path)
    assert str(collision) in str(error.value)
    assert set(tmp_path.rglob("*")) == before
    assert collision.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize(
    "error_type, error_number, message",
    [
        (PermissionError, errno.EACCES, "Permission denied"),
        (OSError, errno.ENOSPC, "No space left on device"),
    ],
)
def test_filesystem_failure_has_nonzero_exit_and_can_be_retried(
    error_type: type[OSError],
    error_number: int,
    message: str,
    tmp_path: Path,
    expected_directories: set[Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    failing_path = tmp_path / "cdisc_reference" / "sdtm"
    original_mkdir = Path.mkdir

    def failing_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        if path == failing_path:
            raise error_type(error_number, message, str(path))
        original_mkdir(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "mkdir", failing_mkdir)
        assert cli.main(["init"]) == 1
    output = capsys.readouterr()
    assert str(failing_path) in output.err
    assert message in output.err
    assert "Workspace initialized:" not in output.out
    assert all(p.is_dir() for p in tmp_path.rglob("*"))
    assert cli.main(["init"]) == 0
    assert {
        p.relative_to(tmp_path) for p in tmp_path.rglob("*")
    } == expected_directories


def test_preflight_permission_error_does_not_create_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = tmp_path / "cdisc_reference"
    original_lstat = Path.lstat

    def denied_lstat(path: Path) -> object:
        if path == blocked:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", denied_lstat)
    with pytest.raises(WorkspaceError, match="Permission denied"):
        initialize_workspace(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_success_requires_complete_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    original_mkdir = Path.mkdir

    def incomplete_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        if path.name != "study_profiles":
            original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", incomplete_mkdir)
    assert cli.main(["init"]) == 1
    output = capsys.readouterr()
    assert "study_profiles" in output.err
    assert "Workspace initialized:" not in output.out


@pytest.mark.parametrize("root_kind", ["missing", "file"])
def test_root_must_be_an_existing_directory(root_kind: str, tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    if root_kind == "file":
        root.write_text("keep", encoding="utf-8")
    with pytest.raises(WorkspaceError):
        initialize_workspace(root)
    assert not (root / "cdisc_reference").exists()


@pytest.mark.parametrize("dangling", [False, True])
def test_symbolic_links_cannot_redirect_writes(dangling: bool, tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = tmp_path / "elsewhere"
    if not dangling:
        target.mkdir()
    link = root / "cdisc_reference"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlink creation is unavailable on this platform")
    with pytest.raises(WorkspaceError, match="symbolic link"):
        initialize_workspace(root)
    assert link.is_symlink()
    assert not target.exists() if dangling else list(target.iterdir()) == []
