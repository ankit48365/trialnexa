"""Synthetic acceptance tests; no licensed CDISC content is bundled."""

import copy
import csv
import errno
import json
import os
from pathlib import Path

import pytest

from trialnexa import cli
from trialnexa.reference import ReferenceError
from trialnexa.reference.csv_source import read_csv
from trialnexa.reference.model import (
    normalize_rows,
    serialize_documents,
    validate_documents,
)
from trialnexa.reference.service import import_cdash
from trialnexa.workspace import (
    WorkspaceError,
    initialize_workspace,
    resolve_reference_paths,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cdash_synthetic.csv"
NAMES = {"domains.json", "variables.json", "mappings_to_sdtm.json"}
# Independent source-to-output acceptance contract, not the implementation map.
FIELDS = [
    "version",
    "class",
    "domain",
    "scenario",
    "variable_order",
    "cdashig_variable",
    "cdashig_variable_label",
    "draft_cdashig_definition",
    "question_text",
    "prompt",
    "type",
    "cdashig_core",
    "crf_completion_instructions",
    "sdtmig_target",
    "mapping_instructions",
    "ct_codelist_codes",
    "codelist_submission_value",
    "implementation_notes",
]


def snapshot(root: Path) -> dict[str, bytes]:
    destination = root / "cdisc_reference/cdash/v2.3"
    return {path.name: path.read_bytes() for path in destination.iterdir()}


def write_source(
    tmp_path: Path, rows: list[list[str]], headers: list[str] | None = None
) -> Path:
    source = tmp_path / "input.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        if headers is not None:
            writer.writerow(headers)
        writer.writerows(rows)
    return source


def source_cells() -> tuple[list[str], list[list[str]]]:
    with FIXTURE.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        return next(reader), list(reader)


def test_complete_import_preserves_all_18_columns(tmp_path: Path) -> None:
    result = import_cdash(FIXTURE, workspace=tmp_path)
    assert (result.rows, result.domains) == (4, 2)
    files = snapshot(tmp_path)
    assert set(files) == NAMES
    assert {path.name for path in result.paths} == NAMES
    docs = {name: json.loads(data) for name, data in files.items()}
    for doc in docs.values():
        assert doc["schema_version"] == 1
        assert doc["standard"] == "CDASHIG"
        assert doc["version"] == "2.3"
    assert docs["domains.json"]["domains"] == [
        {"domain": "AE", "class": "Events", "scenarios": ["Follow-up", "Initial"]},
        {"domain": "DM", "class": "Special Purpose", "scenarios": []},
    ]
    variables = docs["variables.json"]["variables"]
    mappings = docs["mappings_to_sdtm.json"]["mappings"]
    _, expected_rows = source_cells()
    assert len(variables) == len(mappings) == len(expected_rows) == 4
    for index, (variable, mapping, expected) in enumerate(
        zip(variables, mappings, expected_rows, strict=True), start=1
    ):
        assert variable["source_row"] == mapping["source_row"] == index
        combined = {**variable, **mapping, "version": docs["variables.json"]["version"]}
        assert [combined[key] for key in FIELDS] == [
            value or None for value in expected
        ]
    assert variables[1]["variable_order"] == "002"
    assert variables[2]["variable_order"] == "0"
    assert all(row["cdashig_variable"] == "SHARED" for row in variables)
    assert mappings[1]["sdtmig_target"] is None
    assert mappings[3]["sdtmig_target"] is None
    assert b"\\u" not in files["variables.json"]
    assert all(data.endswith(b"\n") for data in files.values())


def test_deterministic_reruns_and_force(tmp_path: Path) -> None:
    import_cdash(FIXTURE, workspace=tmp_path)
    before = snapshot(tmp_path)
    destination = tmp_path / "cdisc_reference/cdash/v2.3"
    mtimes = {p.name: p.stat().st_mtime_ns for p in destination.iterdir()}
    import_cdash(FIXTURE, workspace=tmp_path)
    assert snapshot(tmp_path) == before
    assert {p.name: p.stat().st_mtime_ns for p in destination.iterdir()} == mtimes
    headers, rows = source_cells()
    rows[0][6] = "Changed synthetic label"
    changed = write_source(tmp_path, rows, headers)
    with pytest.raises(ReferenceError, match="--force"):
        import_cdash(changed, workspace=tmp_path)
    assert snapshot(tmp_path) == before
    import_cdash(changed, workspace=tmp_path, force=True)
    assert snapshot(tmp_path) != before
    assert (
        json.loads(snapshot(tmp_path)["variables.json"])["variables"][0][
            "cdashig_variable_label"
        ]
        == "Changed synthetic label"
    )
    assert {p.name for p in destination.parent.iterdir()} == {"v2.3"}


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "duplicate",
        "extra",
        "empty",
        "header_only",
        "short",
        "long",
        "blank_row",
        "version",
        "mixed_version",
        "domain",
        "variable",
        "class",
        "order",
        "negative",
        "decimal",
        "null_order",
        "nul_identifier",
        "conflict",
        "encoding",
        "quote",
    ],
)
def test_invalid_source_does_not_replace_snapshot(kind: str, tmp_path: Path) -> None:
    import_cdash(FIXTURE, workspace=tmp_path)
    before = snapshot(tmp_path)
    headers, rows = source_cells()
    if kind == "missing":
        headers.pop()
    elif kind == "duplicate":
        headers[-1] = headers[0]
    elif kind == "extra":
        headers.append("Unexpected")
    elif kind == "empty":
        headers, rows = None, []
    elif kind == "header_only":
        rows = []
    elif kind == "short":
        rows[-1].pop()
    elif kind == "long":
        rows[-1].append("extra")
    elif kind == "blank_row":
        rows.append([])
    elif kind in {"version", "mixed_version"}:
        rows[-1][0] = "2.2"
        if kind == "version":
            rows = rows[-1:]
    elif kind in {"domain", "variable", "class", "nul_identifier"}:
        column = {"domain": 2, "variable": 5, "class": 1, "nul_identifier": 5}[kind]
        rows[0][column] = "bad\x00identifier" if kind == "nul_identifier" else " "
    elif kind in {"order", "negative", "decimal", "null_order"}:
        rows[0][4] = {
            "order": "NaN",
            "negative": "-1",
            "decimal": "1.5",
            "null_order": "",
        }[kind]
    elif kind == "conflict":
        rows[1][1] = "Conflicting class"
    source = write_source(tmp_path, rows, headers)
    if kind == "encoding":
        source.write_bytes(b"\xff\xfeinvalid")
    elif kind == "quote":
        with source.open("a", encoding="utf-8") as stream:
            stream.write('"unterminated')
    with pytest.raises(ReferenceError):
        import_cdash(source, workspace=tmp_path, force=True)
    assert snapshot(tmp_path) == before
    assert {p.name for p in (tmp_path / "cdisc_reference/cdash").iterdir()} == {"v2.3"}


def test_reordered_headers_bom_and_crlf_preserve_text(tmp_path: Path) -> None:
    headers, rows = source_cells()
    rows[0][8] = ' CRLF\r\n"quoted", café '
    source = write_source(
        tmp_path, [list(reversed(row)) for row in rows], list(reversed(headers))
    )
    source.write_bytes(b"\xef\xbb\xbf" + source.read_bytes())
    import_cdash(source, workspace=tmp_path)
    variables = json.loads(snapshot(tmp_path)["variables.json"])["variables"]
    assert variables[0]["question_text"] == rows[0][8]


@pytest.mark.parametrize("source_kind", ["missing", "directory", "unreadable"])
def test_source_file_errors(
    source_kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.csv"
    if source_kind == "directory":
        source.mkdir()
    elif source_kind == "unreadable":
        original = Path.open

        def denied(path: Path, *args: object, **kwargs: object):
            if path == source:
                raise PermissionError(errno.EACCES, "Permission denied", str(path))
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(ReferenceError, match="Unable to read"):
        import_cdash(source, workspace=tmp_path)
    assert not (tmp_path / "cdisc_reference").exists()


@pytest.mark.parametrize("phase", ["write", "fsync", "backup", "install"])
def test_publication_failure_preserves_previous_snapshot(
    phase: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import_cdash(FIXTURE, workspace=tmp_path)
    before = snapshot(tmp_path)
    headers, rows = source_cells()
    rows[0][6] = "Changed"
    source = write_source(tmp_path, rows, headers)
    original_open, original_rename = Path.open, Path.rename

    def failed_open(path: Path, *args: object, **kwargs: object):
        if (
            phase == "write"
            and path.parent.name == "snapshot"
            and path.name == "variables.json"
        ):
            raise OSError(errno.ENOSPC, "Synthetic full disk", str(path))
        return original_open(path, *args, **kwargs)

    def failed_rename(path: Path, target: Path) -> Path:
        if (phase == "backup" and path.name == "v2.3") or (
            phase == "install" and path.name == "snapshot"
        ):
            raise PermissionError(errno.EACCES, "Synthetic rename failure", str(path))
        return original_rename(path, target)

    def failed_fsync(fd: int) -> None:
        raise OSError(errno.ENOSPC, "Synthetic fsync failure")

    monkeypatch.setattr(Path, "open", failed_open)
    monkeypatch.setattr(Path, "rename", failed_rename)
    if phase == "fsync":
        monkeypatch.setattr(os, "fsync", failed_fsync)
    with pytest.raises(ReferenceError, match="publish"):
        import_cdash(source, workspace=tmp_path, force=True)
    assert snapshot(tmp_path) == before
    assert {p.name for p in (tmp_path / "cdisc_reference/cdash").iterdir()} == {"v2.3"}


@pytest.mark.parametrize("rollback_error", [PermissionError, KeyboardInterrupt])
def test_failed_rollback_retains_recovery_copy(
    rollback_error: type[BaseException], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import_cdash(FIXTURE, workspace=tmp_path)
    before = snapshot(tmp_path)
    (tmp_path / "cdisc_reference/cdash/v2.3/variables.json").write_text(
        "old", encoding="utf-8"
    )
    before["variables.json"] = b"old"
    original = Path.rename

    def fail(path: Path, target: Path) -> Path:
        if path.name == "previous":
            raise rollback_error("Synthetic interrupted rollback")
        if path.name == "snapshot":
            raise PermissionError("Synthetic blocked rename")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", fail)
    with pytest.raises(ReferenceError, match="Previous snapshot retained at"):
        import_cdash(FIXTURE, workspace=tmp_path, force=True)
    (backup,) = (tmp_path / "cdisc_reference/cdash").glob(".v2.3.import-*/previous")
    assert {p.name: p.read_bytes() for p in backup.iterdir()} == before


@pytest.mark.parametrize(
    "kind",
    ["parent_file", "destination_file", "output_directory", "unexpected", "lock"],
)
def test_destination_collisions_preserve_content(kind: str, tmp_path: Path) -> None:
    if kind != "parent_file":
        initialize_workspace(tmp_path)
    destination = tmp_path / "cdisc_reference/cdash/v2.3"
    collision = {
        "parent_file": tmp_path / "cdisc_reference",
        "destination_file": destination,
        "output_directory": destination / "variables.json",
        "unexpected": destination / "keep.txt",
        "lock": destination.parent / ".v2.3.import.lock",
    }[kind]
    if kind == "destination_file":
        destination.rmdir()
    if kind in {"lock", "output_directory"}:
        collision.mkdir()
    else:
        collision.write_text("preserve", encoding="utf-8")
    with pytest.raises(ReferenceError):
        import_cdash(FIXTURE, workspace=tmp_path, force=True)
    assert collision.exists()
    if collision.is_file():
        assert collision.read_text(encoding="utf-8") == "preserve"


def test_symlink_destination_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    target = tmp_path / "outside"
    root.mkdir()
    target.mkdir()
    try:
        (root / "cdisc_reference").symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable")
    with pytest.raises(ReferenceError, match="symbolic link"):
        import_cdash(FIXTURE, workspace=root)
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("predicate", ["is_symlink", "is_junction"])
@pytest.mark.parametrize(
    "relative", ["cdisc_reference/cdash", "cdisc_reference/cdash/v2.3/variables.json"]
)
def test_link_preflight_without_platform_privileges(
    predicate: str, relative: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import_cdash(FIXTURE, workspace=tmp_path)
    before = snapshot(tmp_path)
    blocked = tmp_path / relative
    original = getattr(Path, predicate)
    monkeypatch.setattr(Path, predicate, lambda path: path == blocked or original(path))
    with pytest.raises(ReferenceError, match="symbolic link or junction"):
        import_cdash(FIXTURE, workspace=tmp_path, force=True)
    assert snapshot(tmp_path) == before


def test_interrupted_install_restores_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import_cdash(FIXTURE, workspace=tmp_path)
    before = snapshot(tmp_path)
    headers, rows = source_cells()
    rows[0][6] = "Changed"
    source = write_source(tmp_path, rows, headers)
    original = Path.rename

    def interrupted(path: Path, target: Path) -> Path:
        if path.name == "snapshot":
            raise KeyboardInterrupt
        return original(path, target)

    monkeypatch.setattr(Path, "rename", interrupted)
    with pytest.raises(KeyboardInterrupt):
        import_cdash(source, workspace=tmp_path, force=True)
    assert snapshot(tmp_path) == before


def test_failed_first_install_has_no_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.rename

    def denied(path: Path, target: Path) -> Path:
        if path.name == "snapshot":
            raise PermissionError("Synthetic blocked install")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", denied)
    with pytest.raises(ReferenceError, match="publish"):
        import_cdash(FIXTURE, workspace=tmp_path)
    assert list((tmp_path / "cdisc_reference/cdash").iterdir()) == []


def test_missing_output_is_repaired(tmp_path: Path) -> None:
    import_cdash(FIXTURE, workspace=tmp_path)
    before = snapshot(tmp_path)
    (tmp_path / "cdisc_reference/cdash/v2.3/mappings_to_sdtm.json").unlink()
    import_cdash(FIXTURE, workspace=tmp_path)
    assert snapshot(tmp_path) == before


def test_model_validation_before_publication() -> None:
    documents = normalize_rows(read_csv(FIXTURE))
    for filename, key, field, value in [
        ("mappings_to_sdtm.json", "mappings", "source_row", 100),
        ("variables.json", "variables", "question_text", object()),
        ("mappings_to_sdtm.json", "mappings", "scenario", "wrong"),
        ("variables.json", "variables", "variable_order", "invalid"),
    ]:
        broken = copy.deepcopy(documents)
        broken[filename][key][0][field] = value
        with pytest.raises(ReferenceError):
            serialize_documents(broken)
    broken = copy.deepcopy(documents)
    broken["mappings_to_sdtm.json"]["mappings"].pop()
    with pytest.raises(ReferenceError, match="counts"):
        validate_documents(broken)
    broken = copy.deepcopy(documents)
    broken["domains.json"]["domains"].pop()
    with pytest.raises(ReferenceError, match="coverage"):
        validate_documents(broken)


def test_root_resolution_from_study_and_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialize_workspace(tmp_path)
    study = tmp_path / "studies/study-001/data"
    study.mkdir(parents=True)
    source = study / "local.csv"
    source.write_bytes(FIXTURE.read_bytes())
    monkeypatch.chdir(study)
    paths = resolve_reference_paths(Path("local.csv"))
    assert paths.root == tmp_path
    assert paths.source == source
    import_cdash(Path("local.csv"))
    assert not (study / "cdisc_reference").exists()
    explicit = tmp_path / "other"
    explicit.mkdir()
    assert resolve_reference_paths(Path("local.csv"), explicit).root == explicit


def test_root_requires_marker_or_explicit_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkspaceError, match="No workspace root"):
        resolve_reference_paths(FIXTURE)
    (tmp_path / ".git").write_text("gitdir: synthetic", encoding="utf-8")
    assert resolve_reference_paths(FIXTURE).root == tmp_path


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--domain", "sdtm", "--version", "2.3", "--source", "x"],
        ["--domain", "cdash", "--version", "9", "--source", "x"],
        ["--domain", "cdash", "--version", "2.3"],
    ],
)
def test_invalid_import_cli(
    arguments: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as result:
        cli.main(["reference", "import", *arguments])
    assert result.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_import_cli_counts_paths_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    arguments = [
        "reference",
        "import",
        "--domain",
        "cdash",
        "--version",
        "2.3",
        "--source",
        str(FIXTURE),
        "--workspace",
        str(tmp_path),
    ]
    assert cli.main(arguments) == 0
    output = capsys.readouterr()
    assert "Processed 4 rows; 2 distinct domains." in output.out
    assert all(
        str(tmp_path / "cdisc_reference/cdash/v2.3" / name) in output.out
        for name in NAMES
    )
    arguments[arguments.index(str(FIXTURE))] = "missing.csv"
    assert cli.main(arguments) == 1
    output = capsys.readouterr()
    assert "Unable to read source CSV" in output.err
    assert "Processed" not in output.out


@pytest.mark.skipif(
    not os.environ.get("TRIALNEXA_CDASH_CSV"),
    reason="Authorized full CDASHIG CSV not supplied",
)
def test_optional_full_download(tmp_path: Path) -> None:
    source = Path(os.environ["TRIALNEXA_CDASH_CSV"])
    result = import_cdash(source, workspace=tmp_path)
    assert (result.rows, result.domains) == (1253, 42)
    docs = snapshot(tmp_path)
    variables = json.loads(docs["variables.json"])["variables"]
    mappings = json.loads(docs["mappings_to_sdtm.json"])["mappings"]
    assert len(variables) == len(mappings) == 1253
    assert len({row["cdashig_variable"] for row in variables}) == 888
    assert sum(row["sdtmig_target"] is not None for row in mappings) == 1060
