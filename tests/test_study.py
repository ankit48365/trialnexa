"""Study acceptance tests use empty references and synthetic configuration only."""

import errno
import os
import socket
from pathlib import Path
from typing import Any

import pytest
import yaml

from trialnexa import cli
from trialnexa.study import StudyError
from trialnexa.study.config import read_config
from trialnexa.study.references import discover_versions
from trialnexa.study.service import initialize_study, list_studies
from trialnexa.study.validation import validate_study
from trialnexa.workspace import WorkspaceError, initialize_workspace

# Independent acceptance specification, including intermediate directories.
EXPECTED_DIRECTORIES = {
    "raw",
    "raw/crf",
    "raw/external",
    "cdash",
    "cdash/data",
    "cdash/metadata",
    "sdtm",
    "sdtm/data",
    "sdtm/metadata",
    "adam",
    "adam/data",
    "adam/metadata",
    "mappings",
    "mappings/crf_to_cdash",
    "mappings/cdash_to_sdtm",
    "mappings/sdtm_to_adam",
    "outputs",
    "outputs/define_xml",
    "outputs/validation",
    "outputs/reports",
    "outputs/submission",
    "logs",
}
REFERENCE_EXAMPLES = [
    ("cdash", "cdash/v", "7.12"),
    ("sdtmig", "sdtm/sdtmig_v", "9.8"),
    ("adamig", "adam/adamig_v", "6.5"),
    ("define_xml", "define_xml/v", "8.4"),
    ("controlled_terminology", "controlled_terminology/", "2040-10-01"),
]


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # A real marker is required; absent standard groups intentionally stay absent.
    (tmp_path / "cdisc_reference").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def update_config(study: Path, keys: tuple[str, ...], value: Any) -> None:
    config = read_config(study / "study.yaml")
    parent = config
    for key in keys[:-1]:
        parent = parent[key]
    parent[keys[-1]] = value
    (study / "study.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


@pytest.mark.parametrize(
    "study_id", ["STUDY_001", "ABC-2026-01", "pilot_02", "123", "No", "A" * 64]
)
def test_exact_tree_and_schema(study_id: str, workspace: Path) -> None:
    reference_before = snapshot(workspace / "cdisc_reference")
    result = initialize_study(study_id)
    assert result.path == workspace / "studies" / study_id
    assert {p.relative_to(result.path).as_posix() for p in result.path.rglob("*")} == (
        EXPECTED_DIRECTORIES | {"study.yaml"}
    )
    assert all((result.path / name).is_dir() for name in EXPECTED_DIRECTORIES)
    config = yaml.safe_load((result.path / "study.yaml").read_text(encoding="utf-8"))
    assert config == {
        "study_id": study_id,
        "standards": {
            "cdash": "",
            "sdtmig": "",
            "adamig": "",
            "define_xml": "",
            "controlled_terminology": "",
        },
        "paths": {
            "raw": {"crf": "./raw/crf", "external": "./raw/external"},
            "cdash": {"data": "./cdash/data", "metadata": "./cdash/metadata"},
            "sdtm": {"data": "./sdtm/data", "metadata": "./sdtm/metadata"},
            "adam": {"data": "./adam/data", "metadata": "./adam/metadata"},
            "mappings": {
                "crf_to_cdash": "./mappings/crf_to_cdash",
                "cdash_to_sdtm": "./mappings/cdash_to_sdtm",
                "sdtm_to_adam": "./mappings/sdtm_to_adam",
            },
            "outputs": {
                "define_xml": "./outputs/define_xml",
                "validation": "./outputs/validation",
                "reports": "./outputs/reports",
                "submission": "./outputs/submission",
            },
        },
        "validation": {
            "offline": True,
            "rule_engine": "cdisc_core",
            "custom_rules": True,
        },
        "reference": {"root": "../../cdisc_reference", "verify_checksums": True},
    }
    assert (
        result.path / config["reference"]["root"]
    ).resolve() == workspace / "cdisc_reference"
    assert snapshot(workspace / "cdisc_reference") == reference_before
    assert len(result.warnings) == 5
    assert validate_study(study_id).errors == ()


@pytest.mark.parametrize("standard,prefix,version", REFERENCE_EXAMPLES)
@pytest.mark.parametrize("count", [0, 1, 2])
def test_reference_discovery_policy(
    standard: str, prefix: str, version: str, count: int, workspace: Path
) -> None:
    reference = workspace / "cdisc_reference"
    candidate = reference / f"{prefix}{version}"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    # A filename alone cannot establish a candidate.
    candidate.write_text("synthetic", encoding="utf-8")
    assert discover_versions(reference).versions[standard] == ""
    candidate.unlink()
    if count:
        candidate.mkdir()
    if count == 2:
        (reference / f"{prefix}1.0").mkdir()
    before = snapshot(reference)
    result = initialize_study("dynamic")
    config = read_config(result.path / "study.yaml")
    assert config["standards"][standard] == (version if count == 1 else "")
    assert all(isinstance(value, str) for value in config["standards"].values())
    if count == 2:
        warning = next(w for w in result.warnings if f"standards.{standard}:" in w)
        assert (
            "multiple installed versions" in warning
            and version in warning
            and "1.0" in warning
        )
    assert snapshot(reference) == before


def test_existing_initializer_versions_and_validation_warnings(workspace: Path) -> None:
    initialize_workspace(workspace)
    result = initialize_study("pilot_02")
    config = read_config(result.path / "study.yaml")
    assert config["standards"] == {
        "cdash": "2.3",
        "sdtmig": "3.4",
        "adamig": "1.3",
        "define_xml": "",
        "controlled_terminology": "",
    }
    before = snapshot(workspace)
    validation = validate_study("pilot_02")
    assert not validation.errors
    assert len(validation.warnings) == 5
    assert sum("not verified" in warning for warning in validation.warnings) == 3
    assert (
        sum("empty reference directory" in warning for warning in validation.warnings)
        == 3
    )
    assert snapshot(workspace) == before
    assert not list(workspace.rglob("manifest.json"))


@pytest.mark.parametrize(
    "study_id",
    [
        "",
        " ",
        ".",
        "..",
        "../escape",
        "a/b",
        "a\\b",
        "/absolute",
        "C:\\absolute",
        "C:drive",
        "a.b",
        "two words",
        "x\n",
        "café",
        "_first",
        "-first",
        "CON",
        "nul",
        "COM1",
        "lpt9",
        "A" * 65,
    ],
)
def test_unsafe_ids_do_not_write(study_id: str, workspace: Path) -> None:
    before = snapshot(workspace)
    with pytest.raises(StudyError, match="Invalid study ID"):
        initialize_study(study_id)
    assert snapshot(workspace) == before


@pytest.mark.parametrize("command", ["init", "list", "validate"])
@pytest.mark.parametrize("marker", ["absent", "git_only", "file"])
def test_commands_require_initialized_workspace(
    command: str,
    marker: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    if marker == "git_only":
        (tmp_path / ".git").mkdir()
    elif marker == "file":
        (tmp_path / "cdisc_reference").write_text("preserve", encoding="utf-8")
    before = snapshot(tmp_path)
    assert cli.main(["study", command, *([] if command == "list" else ["demo"])]) == 1
    output = capsys.readouterr()
    assert "initialized" not in output.out
    assert "workspace" in output.err.lower() or "directory" in output.err.lower()
    assert snapshot(tmp_path) == before


def test_nested_root_resolution_and_explicit_override(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = initialize_study("first").path
    nested = first / "raw/crf"
    monkeypatch.chdir(nested)
    assert initialize_study("second").path == workspace / "studies/second"
    assert list_studies() == ("first", "second")
    assert not validate_study("first").errors
    alternate = workspace / "alternate"
    (alternate / "cdisc_reference").mkdir(parents=True)
    assert (
        initialize_study("third", workspace=alternate).path
        == alternate / "studies/third"
    )
    assert list_studies(workspace=alternate) == ("third",)
    assert not (nested / "studies").exists()
    with pytest.raises(WorkspaceError, match="Run trialnexa init"):
        initialize_study("bad", workspace=first)


def test_duplicate_init_preserves_yaml_data_and_mtimes(workspace: Path) -> None:
    study = initialize_study("demo").path
    (study / "raw/crf/synthetic.txt").write_text("synthetic", encoding="utf-8")
    (study / "study.yaml").write_text(
        "user-edited: preserve exactly\n", encoding="utf-8"
    )
    before = snapshot(workspace)
    mtimes = {p: p.stat().st_mtime_ns for p in study.rglob("*")}
    with pytest.raises(StudyError, match="already exists.*study validate"):
        initialize_study("demo")
    assert snapshot(workspace) == before
    assert {p: p.stat().st_mtime_ns for p in study.rglob("*")} == mtimes


@pytest.mark.parametrize(
    "kind", ["studies_file", "study_file", "study_directory", "lock"]
)
def test_creation_collisions_preserve_existing_content(
    kind: str, workspace: Path
) -> None:
    studies = workspace / "studies"
    if kind == "studies_file":
        studies.write_text("preserve", encoding="utf-8")
    else:
        studies.mkdir()
        if kind == "study_file":
            (studies / "demo").write_text("preserve", encoding="utf-8")
        else:
            (
                studies / ("demo" if kind == "study_directory" else ".demo.init.lock")
            ).mkdir()
    before = snapshot(workspace)
    with pytest.raises(StudyError):
        initialize_study("demo")
    assert snapshot(workspace) == before


@pytest.mark.parametrize("phase", ["mkdir", "write", "fsync", "rename", "interrupt"])
@pytest.mark.parametrize("existing_parent", [False, True])
def test_failed_creation_leaves_no_partial_study(
    phase: str, existing_parent: bool, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if existing_parent:
        (workspace / "studies").mkdir()
    before = snapshot(workspace)
    original_mkdir, original_open, original_rename = Path.mkdir, Path.open, Path.rename

    def mkdir(path: Path, *args: Any, **kwargs: Any) -> None:
        if phase == "mkdir" and path.name == "metadata":
            raise PermissionError(errno.EACCES, "Synthetic mkdir failure", str(path))
        original_mkdir(path, *args, **kwargs)

    def open_file(path: Path, *args: Any, **kwargs: Any) -> Any:
        if phase == "write" and path.name == "study.yaml":
            raise OSError(errno.ENOSPC, "Synthetic full disk", str(path))
        return original_open(path, *args, **kwargs)

    def rename(path: Path, target: Path) -> Path:
        if path.name == "study":
            if phase == "rename":
                raise PermissionError("Synthetic rename failure")
            if phase == "interrupt":
                raise KeyboardInterrupt
        return original_rename(path, target)

    def fsync(fd: int) -> None:
        raise OSError("Synthetic flush failure")

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(Path, "rename", rename)
    if phase == "fsync":
        monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(KeyboardInterrupt if phase == "interrupt" else OSError):
        initialize_study("demo")
    assert snapshot(workspace) == before


def test_list_sorted_presence_only_and_read_only(workspace: Path) -> None:
    assert list_studies() == ()
    assert not (workspace / "studies").exists()
    for study_id in ("zeta", "Alpha", "pilot_02"):
        initialize_study(study_id)
    studies = workspace / "studies"
    (studies / "notes.txt").write_text("unrelated", encoding="utf-8")
    (studies / "unrelated").mkdir()
    # Listing is based on presence only; validation is responsible for parsing.
    (studies / "zeta/study.yaml").write_text("not: [valid YAML", encoding="utf-8")
    before = snapshot(workspace)
    assert list_studies() == ("Alpha", "pilot_02", "zeta")
    assert snapshot(workspace) == before


@pytest.mark.parametrize("kind", ["unreadable", "config_directory", "bad_id"])
def test_list_malformed_entries_are_errors(
    kind: str, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    studies = workspace / "studies"
    studies.mkdir()
    if kind == "unreadable":
        original = Path.iterdir

        def denied(path: Path):
            if path == studies:
                raise PermissionError("Synthetic unreadable studies directory")
            return original(path)

        monkeypatch.setattr(Path, "iterdir", denied)
        with pytest.raises(PermissionError):
            list_studies()
    else:
        study = studies / ("bad.id" if kind == "bad_id" else "demo")
        study.mkdir()
        if kind == "bad_id":
            (study / "study.yaml").write_text("{}", encoding="utf-8")
        else:
            (study / "study.yaml").mkdir()
        with pytest.raises(StudyError):
            list_studies()


@pytest.mark.parametrize(
    "keys,value,expected",
    [
        (("study_id",), "other", "study_id"),
        (("study_id",), 123, "study_id"),
        (("standards",), [], "standards"),
        (("standards", "cdash"), None, "standards.cdash"),
        (("standards", "sdtmig"), 3.4, "standards.sdtmig"),
        (("standards", "adamig"), "../escape", "standards.adamig"),
        (("standards", "define_xml"), "C:\\outside", "standards.define_xml"),
        (("paths",), None, "paths"),
        (("paths", "raw"), "wrong", "paths.raw"),
        (("paths", "raw", "crf"), "../outside", "paths.raw.crf"),
        (("paths", "raw", "crf"), "/tmp/outside", "paths.raw.crf"),
        (("paths", "raw", "crf"), "C:\\outside", "paths.raw.crf"),
        (("paths", "raw", "crf"), "C:relative", "paths.raw.crf"),
        (("paths", "raw", "crf"), "raw/../raw/crf", "paths.raw.crf"),
        (("paths", "raw", "crf"), "./raw/external", "paths.raw.crf"),
        (("paths", "sdtm", "data"), 2, "paths.sdtm.data"),
        (("validation",), [], "validation"),
        (("validation", "offline"), "true", "validation.offline"),
        (("validation", "custom_rules"), 1, "validation.custom_rules"),
        (("validation", "rule_engine"), " ", "validation.rule_engine"),
        (("reference",), None, "reference"),
        (("reference", "root"), "../../other", "reference.root"),
        (("reference", "root"), "/cdisc_reference", "reference.root"),
        (("reference", "root"), "..\\..\\cdisc_reference", "reference.root"),
        (("reference", "verify_checksums"), "yes", "reference.verify_checksums"),
    ],
)
def test_validation_rejects_invalid_config_without_changes(
    keys: tuple[str, ...], value: Any, expected: str, workspace: Path
) -> None:
    study = initialize_study("demo").path
    update_config(study, keys, value)
    before = snapshot(workspace)
    result = validate_study("demo")
    assert any(expected in error for error in result.errors), result
    assert snapshot(workspace) == before


@pytest.mark.parametrize(
    "keys",
    [
        ("study_id",),
        ("standards",),
        ("paths",),
        ("validation",),
        ("reference",),
        ("standards", "controlled_terminology"),
        ("paths", "raw", "crf"),
        ("validation", "offline"),
        ("validation", "custom_rules"),
        ("validation", "rule_engine"),
        ("reference", "root"),
        ("reference", "verify_checksums"),
    ],
)
def test_missing_required_keys(keys: tuple[str, ...], workspace: Path) -> None:
    study = initialize_study("demo").path
    config = read_config(study / "study.yaml")
    parent = config
    for key in keys[:-1]:
        parent = parent[key]
    del parent[keys[-1]]
    (study / "study.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    assert validate_study("demo").errors


@pytest.mark.parametrize(
    "contents",
    [
        b"",
        b"[]",
        b"scalar",
        b"bad: [yaml",
        b"study_id: demo\nstudy_id: other\n",
        b"nested:\n  key: 1\n  key: 2\n",
        b"key: !!python/object:object {}",
        b"loop: &loop [*loop]",
        b"[a, b]: value",
        b"\xff\xfe",
        b"x" * 1_048_577,
        b"study_id: 2026-99-99\n",
        b"study_id: !!float invalid\n",
    ],
    ids=[
        "empty",
        "sequence",
        "scalar",
        "syntax",
        "duplicate-root",
        "duplicate-nested",
        "unsafe-tag",
        "alias",
        "non-string-key",
        "invalid-encoding",
        "oversized",
        "invalid-date",
        "invalid-float",
    ],
)
def test_malformed_yaml_is_actionable_and_read_only(
    contents: bytes, workspace: Path
) -> None:
    study = initialize_study("demo").path
    (study / "study.yaml").write_bytes(contents)
    before = snapshot(workspace)
    result = validate_study("demo")
    assert result.errors
    assert all("study.yaml" in error for error in result.errors)
    assert snapshot(workspace) == before


@pytest.mark.parametrize(
    "kind",
    [
        "missing_study",
        "missing_yaml",
        "yaml_directory",
        "missing_crf",
        "missing_logs",
        "directory_collision",
        "unreadable_yaml",
        "missing_version",
    ],
)
def test_validation_filesystem_errors(
    kind: str, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = initialize_study("demo").path
    if kind == "missing_study":
        assert validate_study("unknown").errors
        return
    yaml_path = study / "study.yaml"
    if kind in {"missing_yaml", "yaml_directory"}:
        yaml_path.unlink()
        if kind == "yaml_directory":
            yaml_path.mkdir()
    elif kind in {"missing_crf", "missing_logs", "directory_collision"}:
        path = study / ("logs" if kind == "missing_logs" else "raw/crf")
        path.rmdir()
        if kind == "directory_collision":
            path.write_text("preserve", encoding="utf-8")
    elif kind == "unreadable_yaml":
        original = Path.open

        def denied(path: Path, *args: Any, **kwargs: Any) -> Any:
            if path == yaml_path:
                raise PermissionError("Synthetic unreadable study.yaml")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", denied)
    elif kind == "missing_version":
        update_config(study, ("standards", "cdash"), "99.1")
    result = validate_study("demo")
    assert result.errors


@pytest.mark.parametrize("predicate", ["is_symlink", "is_junction"])
@pytest.mark.parametrize(
    "relative",
    [
        "studies",
        "studies/demo",
        "studies/demo/raw",
        "studies/demo/study.yaml",
        "cdisc_reference/cdash",
        "cdisc_reference/cdash/v2.3",
    ],
)
def test_links_and_junctions_rejected_without_privileges(
    predicate: str, relative: str, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialize_workspace(workspace)
    initialize_study("demo")
    blocked = workspace / relative
    original = getattr(Path, predicate)
    before = snapshot(workspace)
    monkeypatch.setattr(Path, predicate, lambda path: path == blocked or original(path))
    assert validate_study("demo").errors
    if relative == "studies" or relative.startswith("cdisc_reference"):
        with pytest.raises(StudyError, match="link or junction"):
            initialize_study("new")
    assert snapshot(workspace) == before


@pytest.mark.parametrize("dangling", [True, False])
def test_real_link_cannot_redirect_study_creation(
    dangling: bool, workspace: Path
) -> None:
    target = workspace / "outside"
    if not dangling:
        target.mkdir()
    link = workspace / "studies"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlink creation unavailable")
    with pytest.raises(StudyError, match="Symbolic link"):
        initialize_study("demo")
    assert not target.exists() if dangling else list(target.iterdir()) == []


@pytest.mark.parametrize(
    "args",
    [
        ["study"],
        ["study", "init"],
        ["study", "validate"],
        ["study", "init", "one", "two"],
        ["study", "list", "one"],
    ],
)
def test_cli_argument_count(args: list[str], workspace: Path) -> None:
    before = snapshot(workspace)
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    assert snapshot(workspace) == before


@pytest.mark.parametrize(
    "args",
    [
        ["study", "--help"],
        ["study", "init", "--help"],
        ["study", "list", "--help"],
        ["study", "validate", "--help"],
    ],
)
def test_cli_help(
    args: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 0
    assert list(tmp_path.iterdir()) == []


def test_cli_messages_exits_and_offline_behavior(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def network_forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Study commands must not use the network")

    monkeypatch.setattr(socket, "create_connection", network_forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", network_forbidden)
    monkeypatch.setattr(socket.socket, "connect", network_forbidden)
    assert cli.main(["study", "list"]) == 0
    assert "No studies" in capsys.readouterr().out
    assert cli.main(["study", "init", "demo"]) == 0
    output = capsys.readouterr()
    assert "Study initialized:" in output.out and "study.yaml" in output.out
    assert "unconfigured" in output.err
    assert cli.main(["study", "list"]) == 0
    assert capsys.readouterr().out == "demo\n"
    assert cli.main(["study", "validate", "demo"]) == 0
    output = capsys.readouterr()
    assert "0 error(s), 5 warning(s)" in output.out
    assert "unconfigured" in output.err
    assert cli.main(["study", "init", "demo"]) == 1
    output = capsys.readouterr()
    assert "already exists" in output.err and "initialized" not in output.out
    (workspace / "studies/demo/logs").rmdir()
    assert cli.main(["study", "validate", "demo"]) == 1
    output = capsys.readouterr()
    assert "1 error(s)" in output.out and "logs" in output.err


def test_cli_write_error_and_interrupt(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("Synthetic permission failure")

    monkeypatch.setattr(cli, "initialize_study", fail)
    assert cli.main(["study", "init", "demo"]) == 1
    output = capsys.readouterr()
    assert "permission failure" in output.err and "initialized" not in output.out

    def interrupt(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "initialize_study", interrupt)
    assert cli.main(["study", "init", "demo"]) == 130
    assert "interrupted" in capsys.readouterr().err


@pytest.mark.parametrize(
    "relative,operation",
    [
        ("cdisc_reference/cdash/v2.3", "init"),
        ("studies/demo", "list"),
    ],
)
def test_unreadable_entries_are_not_silently_ignored(
    relative: str,
    operation: str,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    initialize_workspace(workspace)
    initialize_study("demo")
    original = Path.lstat
    blocked = workspace / relative

    def denied(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == blocked:
            raise PermissionError("Synthetic unreadable entry")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", denied)
    assert (
        cli.main(["study", operation, *(["new"] if operation == "init" else [])]) == 1
    )
    output = capsys.readouterr()
    assert "unreadable entry" in output.err
    assert "initialized" not in output.out


def test_nearest_invalid_marker_does_not_fall_back(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = workspace / "nested"
    nested.mkdir()
    (nested / "cdisc_reference").write_text("preserve", encoding="utf-8")
    monkeypatch.chdir(nested)
    before = snapshot(workspace)
    with pytest.raises(WorkspaceError, match="non-directory"):
        initialize_study("demo")
    assert snapshot(workspace) == before
