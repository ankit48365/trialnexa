"""Source-only acceptance tests, using synthetic data and no reference metadata."""

import hashlib
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

from trialnexa import cli
from trialnexa.profiling import ProfileError
from trialnexa.profiling.csv_source import CsvAdapter, ProfileOptions
from trialnexa.profiling.publish import publish_reports
from trialnexa.profiling.service import profile_study
from trialnexa.study.config import make_config, read_config, serialize_config

FIXTURES = Path(__file__).parent / "fixtures/profiling"
SCHEMA = Path(__file__).parent.parent / "docs/schemas/source-profile.schema.json"


@pytest.fixture
def study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Existing initialized manifest/layout conventions, deliberately WITHOUT
    # creating cdisc_reference or calling the reference-dependent initializer.
    path = tmp_path / "studies/DEMO_MODERN_01"
    (path / "cdash/data").mkdir(parents=True)
    (path / "cdash/metadata").mkdir()
    (path / "raw/crf").mkdir(parents=True)
    config = make_config(path.name, {})
    (path / "study.yaml").write_text(serialize_config(config), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return path


def put_csv(study: Path, text: str, name: str = "source.csv") -> Path:
    path = study / "cdash/data" / name
    path.write_text(text, encoding="utf-8", newline="")
    return path


def artifacts(study: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in (study / "cdash/metadata").iterdir()}


def profile(study: Path, stem: str = "source") -> Any:
    return json.loads((study / f"cdash/metadata/{stem}.profile.json").read_bytes())


def summary(study: Path) -> Any:
    return json.loads((study / "cdash/metadata/profiling_summary.json").read_bytes())


def validate_artifacts(study: Path) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for name, raw in artifacts(study).items():
        doc = yaml.safe_load(raw) if name.endswith(".yaml") else json.loads(raw)
        validator.validate(doc)


def test_all_files_provenance_schema_determinism_and_inputs_untouched(
    study: Path,
) -> None:
    root = study.parent.parent
    for fixture in FIXTURES.iterdir():
        shutil.copyfile(fixture, study / "cdash/data" / fixture.name)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = profile_study(study.name)
    assert (result.processed, result.failures) == (4, 0)
    assert not (root / "cdisc_reference").exists()
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert all(
        p.is_relative_to(study / "cdash/metadata")
        for p in root.rglob("*")
        if p.is_file() and p not in before
    )
    doc = summary(study)
    assert doc["files_processed"] == doc["files_discovered"] == 4
    assert doc["row_count"] == 8 and doc["column_count"] == 15
    assert [Path(f["source_path"]).name for f in doc["files"]] == sorted(
        p.name for p in FIXTURES.iterdir()
    )
    validate_artifacts(study)
    first = artifacts(study)
    times = {p.name: p.stat().st_mtime_ns for p in result.destination.iterdir()}
    profile_study(study.name)
    assert artifacts(study) == first
    assert {p.name: p.stat().st_mtime_ns for p in result.destination.iterdir()} == times
    assert len(first) == 10  # two per source, summary, ownership manifest
    for raw in first.values():
        assert b"00123" not in raw and b"Synthetic event" not in raw
    dm = profile(study, "01_demographics_modern")
    assert dm["source"]["row_count"] == 1
    assert dm["columns"][0]["inferred_type"] == "string"
    assert dm["columns"][0]["numeric"]["min"] is None
    lb = profile(study, "03_laboratory_grid")
    assert lb["columns"][1]["inferred_type"] == "decimal"
    assert lb["columns"][1]["numeric"] == {
        "count": 2,
        "min": "4.5",
        "max": "7.2",
        "failure_count": 0,
        "sign_counts": {"negative": 0, "zero": 0, "positive": 2},
    }
    assert lb["columns"][1]["missing_count"] == 1


def test_never_reads_references_or_network_and_has_no_interpretation(
    study: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_csv(study, "Participant ID,Visit Date,Result\n00123,03/04/2026,70 bpm\n")

    def reject(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Network/standards operations are forbidden")

    original_lstat = Path.lstat
    original_open = Path.open

    def no_reference_stat(path: Path, *args: Any, **kwargs: Any) -> Any:
        if "cdisc_reference" in path.parts:
            reject()
        return original_lstat(path, *args, **kwargs)

    def no_reference_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if "cdisc_reference" in path.parts:
            reject()
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", reject)
    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(Path, "lstat", no_reference_stat)
    monkeypatch.setattr(Path, "open", no_reference_open)
    assert cli.main(["cdash", "profile", "--study", study.name]) == 0
    forbidden = {
        "cdash_domain",
        "domain",
        "target_variable",
        "candidate_mappings",
        "reference_version",
        "mapping_confidence",
        "mapping_approved",
        "score",
        "candidates",
    }

    def inspect(value: Any) -> None:
        if isinstance(value, dict):
            assert not (set(value) & forbidden)
            for item in value.values():
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    for raw in artifacts(study).values():
        inspect(yaml.safe_load(raw))


def test_dates_types_missingness_and_opt_in_raw_examples(study: Path) -> None:
    source = put_csv(
        study,
        "Identifier,Date,Empty,Sentinel,Numbers,Mixed,Flag,Timestamp,Odd Date\r\n"
        "00123,03/04/2026,,NA,-2,2,true,2026-03-04T12:30:00Z,bad\r\n"
        "00456,14/04/2026,   ,Unknown,0,word,false,"
        "2026-03-04 13:00:00,2026-02-30\r\n"
        "00789,05-Mar-2026,,,2.5,4.5,true,2026-03-05T14:00:00+01:00,2026-03-06\r\n",
    )
    original = source.read_bytes()
    profile_study(study.name, options=ProfileOptions(sample_limit=2, distinct_limit=2))
    columns = profile(study)["columns"]
    identifier, dates, empty, sentinel, numbers, mixed, flag, timestamp, odd = columns
    assert identifier["examples"] == ["00123", "00456"]
    assert identifier["inferred_type"] == "string"
    assert (
        identifier["distinct_count"] is None and identifier["distinct_lower_bound"] == 3
    )
    assert dates["dates"]["ambiguous_locale"] and dates["dates"]["mixed_formats"]
    assert (
        dates["dates"]["ambiguous_count"] == 1 and dates["dates"]["success_count"] == 3
    )
    assert set(dates["dates"]["formats"]) == {"MM/DD/YYYY", "DD/MM/YYYY", "DD-Mon-YYYY"}
    assert empty["missing_count"] == 3 and empty["missing_percentage"] == 100
    assert empty["missingness"] == {"empty": 2, "whitespace": 1, "sentinel": 0}
    assert empty["inferred_type"] == "unknown" and empty["examples"] == []
    assert sentinel["missing_count"] == 1 and sentinel["nonnull_count"] == 2
    assert numbers["numeric"]["sign_counts"] == {
        "negative": 1,
        "zero": 1,
        "positive": 1,
    }
    assert mixed["inferred_type"] == "string" and mixed["mixed_type"]
    assert (
        flag["inferred_type"] == "boolean" and timestamp["inferred_type"] == "datetime"
    )
    assert (
        odd["dates"]["invalid_calendar_count"] == 1
        and odd["dates"]["failure_count"] == 2
    )
    assert source.read_bytes() == original
    validate_artifacts(study)
    profile_study(
        study.name, options=ProfileOptions(missing_sentinels=("na", "UNKNOWN"))
    )
    sentinel = profile(study)["columns"][3]
    assert sentinel["missing_count"] == 3 and sentinel["missingness"]["sentinel"] == 2
    assert sentinel["examples"] == []


def test_bom_quoted_lines_duplicate_blank_headers_and_zero_rows(study: Path) -> None:
    source = put_csv(
        study, '\ufeffID,Value,Value,\r\n00123,"line 1, quoted\r\nline 2",0004,\r\n'
    )
    profile_study(study.name, options=ProfileOptions(sample_limit=1))
    doc = profile(study)
    assert doc["source"]["encoding"] == "utf-8-bom"
    assert doc["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert [c["source_name"] for c in doc["columns"]] == ["ID", "Value", "Value", ""]
    assert [c["ordinal"] for c in doc["columns"]] == [1, 2, 3, 4]
    assert doc["columns"][1]["examples"] == ["line 1, quoted\r\nline 2"]
    assert "duplicate_header" in doc["columns"][1]["warnings"]
    assert "blank_header" in doc["columns"][3]["warnings"]
    assert doc["columns"][2]["inferred_type"] == "string"
    put_csv(study, "A,B\n", "header_only.csv")
    profile_study(study.name, selected="header_only.csv")
    doc = profile(study, "header_only")
    assert doc["source"]["parse_status"] == "header_only"
    assert doc["columns"][0]["missing_percentage"] is None
    assert "header_only" in doc["columns"][0]["warnings"]
    validate_artifacts(study)


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"", "empty_csv"),
        (b" \n", "empty_csv"),
        (b"00123,34\n00456,35\n", "headerless_csv"),
        (b"A,B\n1\n", "malformed_row"),
        (b"A\n1,2\n", "malformed_row"),
        (b"A\n\n", "malformed_row"),
        (b'A\n"unterminated', "invalid_csv"),
        (b"A\n\xff\n", "invalid_encoding"),
    ],
)
def test_bad_csv_has_explicit_safe_outcome(
    study: Path, raw: bytes, code: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = study / "cdash/data/bad.csv"
    path.write_bytes(raw)
    assert cli.main(["cdash", "profile", "--study", study.name]) == 1
    output = capsys.readouterr()
    assert code in output.err and "Traceback" not in output.err
    assert "00123" not in output.out + output.err
    doc = summary(study)
    assert doc["error_count"] == 1 and doc["files_processed"] == 0
    assert doc["files"][0]["outputs"] == []
    assert doc["files"][0]["errors"][0]["code"] == code
    assert path.read_bytes() == raw and len(artifacts(study)) == 2
    validate_artifacts(study)


def test_file_selection_batch_failure_scope_and_nested_cwd(
    study: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_csv(study, 'A\n"unterminated', "a.csv")
    put_csv(study, "ID\n00123\n", "b.csv")
    monkeypatch.chdir(study / "raw/crf")
    result = profile_study(study.name)
    assert (result.processed, result.failures) == (1, 1)
    profile_study(study.name, selected="b.csv")
    doc = summary(study)
    assert doc["scope"] == "selected_file" and doc["files_discovered"] == 1
    assert doc["row_count"] == doc["column_count"] == 1
    assert profile(study, "b")["columns"][0]["inferred_type"] == "string"


def test_missing_study_empty_input_and_unsafe_paths(study: Path) -> None:
    with pytest.raises(ProfileError, match="No CSV"):
        profile_study(study.name)
    assert artifacts(study) == {}
    assert cli.main(["cdash", "profile", "--study", "absent"]) == 1
    put_csv(study, "A\n1\n")
    for name in (
        "../source.csv",
        "sub/source.csv",
        "sub\\source.csv",
        "/source.csv",
        "C:\\source.csv",
        "absent.csv",
        "notes.txt",
    ):
        assert (
            cli.main(["cdash", "profile", "--study", study.name, "--input", name]) == 1
        )
    for study_id in ("../outside", "C:\\outside", "CON"):
        assert cli.main(["cdash", "profile", "--study", study_id]) == 1
    assert artifacts(study) == {}


@pytest.mark.parametrize(
    "key,value",
    [
        (("paths", "cdash", "data"), "../outside"),
        (("paths", "cdash", "metadata"), []),
        (("paths", "cdash", "metadata"), "/outside"),
        (("study_id",), "other"),
    ],
)
def test_relevant_manifest_fields_validated(
    study: Path, key: tuple[str, ...], value: Any
) -> None:
    put_csv(study, "A\n1\n")
    path = study / "study.yaml"
    config = read_config(path)
    parent = config
    for item in key[:-1]:
        parent = parent[item]
    parent[key[-1]] = value
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert cli.main(["cdash", "profile", "--study", study.name]) == 1
    assert artifacts(study) == {}


def test_irrelevant_reference_settings_not_required(study: Path) -> None:
    put_csv(study, "A\n1\n")
    path = study / "study.yaml"
    config = read_config(path)
    config.pop("reference")
    config.pop("standards")
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert profile_study(study.name).processed == 1


def test_missing_metadata_directory_and_explicit_workspace(
    study: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_csv(study, "ID\n00123\n")
    (study / "cdash/metadata").rmdir()
    unrelated = tmp_path / "elsewhere"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    assert profile_study(study.name, workspace=study.parent.parent).processed == 1
    assert (study / "cdash/metadata").is_dir()


def test_regeneration_protects_unmanaged_and_edited_metadata(study: Path) -> None:
    source = put_csv(study, "A\n1\n")
    destination = study / "cdash/metadata"
    note = destination / "notes.yaml"
    note.write_text("human: notes\n", encoding="utf-8")
    report = destination / "source.metadata.yaml"
    report.write_text("human: metadata\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="Unmanaged or edited"):
        profile_study(study.name)
    assert report.read_text() == "human: metadata\n"
    report.unlink()
    profile_study(study.name)
    first = artifacts(study)
    source.write_text("A\n2\n", encoding="utf-8")
    profile_study(study.name)
    assert artifacts(study) != first and note.read_text() == "human: notes\n"
    report.write_text("human: edited\n", encoding="utf-8")
    before = artifacts(study)
    with pytest.raises(ProfileError, match="Unmanaged or edited"):
        profile_study(study.name)
    assert artifacts(study) == before


@pytest.mark.parametrize("existing", [False, True])
def test_install_failure_rolls_back_entire_batch(
    study: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    source = put_csv(study, "A\n1\n")
    if existing:
        profile_study(study.name)
    before = artifacts(study)
    source.write_text("A\n2\n", encoding="utf-8")
    replace = os.replace
    calls = 0

    def fail_second(src: Path, dest: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("simulated install failure")
        replace(src, dest)

    monkeypatch.setattr(os, "replace", fail_second)
    with pytest.raises(PermissionError):
        profile_study(study.name)
    assert artifacts(study) == before


def test_staging_and_rollback_failures(
    study: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = put_csv(study, "A\n1\n")
    profile_study(study.name)
    before = artifacts(study)
    source.write_text("A\n2\n", encoding="utf-8")

    def fail_fsync(fd: int) -> None:
        raise OSError("simulated staging failure")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_fsync)
        with pytest.raises(OSError):
            profile_study(study.name)
    assert artifacts(study) == before
    replace = os.replace
    calls = 0

    def fail_restore(src: Path, dest: Path) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise PermissionError("simulated rollback failure")
        replace(src, dest)

    monkeypatch.setattr(os, "replace", fail_restore)
    with pytest.raises(ProfileError, match="Previous reports retained"):
        profile_study(study.name)
    stage = next((study / "cdash/metadata").glob(".profiling-stage-*"))
    for backup in (stage / "previous").iterdir():
        assert backup.read_bytes() == before[backup.name]


@pytest.mark.parametrize(
    "location", ["source", "data", "metadata", "report", "study_yaml", "studies"]
)
def test_symlinks_cannot_escape_workspace(
    study: Path, tmp_path: Path, location: str
) -> None:
    put_csv(study, "A\n1\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = {
        "source": study / "cdash/data/source.csv",
        "data": study / "cdash/data",
        "metadata": study / "cdash/metadata",
        "report": study / "cdash/metadata/source.profile.json",
        "study_yaml": study / "study.yaml",
        "studies": study.parent,
    }[location]
    directory = target.is_dir()
    if directory:
        shutil.rmtree(target)
        linked = outside
    else:
        target.unlink(missing_ok=True)
        linked = outside / "keep.txt"
        linked.write_bytes(b"preserve")
    try:
        target.symlink_to(linked, target_is_directory=directory)
    except OSError:
        pytest.skip("Host cannot create symlinks")
    before = {p: p.read_bytes() for p in outside.rglob("*") if p.is_file()}
    assert cli.main(["cdash", "profile", "--study", study.name]) == 1
    assert {p: p.read_bytes() for p in outside.rglob("*") if p.is_file()} == before


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions only")
@pytest.mark.parametrize("relative", ["cdash/data", "cdash/metadata"])
def test_windows_junctions_cannot_redirect_paths(
    study: Path, tmp_path: Path, relative: str
) -> None:
    put_csv(study, "A\n1\n")
    target = study / relative
    outside = tmp_path / "outside-junction"
    outside.mkdir()
    keep = outside / "keep.txt"
    keep.write_bytes(b"preserve")
    shutil.rmtree(target)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(target), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        pytest.skip("Host cannot create junctions")
    try:
        assert target.is_junction()
        assert cli.main(["cdash", "profile", "--study", study.name]) == 1
        assert list(outside.iterdir()) == [keep] and keep.read_bytes() == b"preserve"
    finally:
        target.rmdir()


def test_case_collision_and_stale_lock(study: Path) -> None:
    put_csv(study, "A\n1\n", "a.csv")
    put_csv(study, "A\n1\n", "A.CSV")
    if len(list((study / "cdash/data").iterdir())) == 2:
        with pytest.raises(ProfileError, match="stems collide"):
            profile_study(study.name)
    (study / "cdash/metadata/.profiling.lock").mkdir()
    with pytest.raises(ProfileError, match="stale lock"):
        publish_reports(study / "cdash/metadata", {})


def test_bounds_mixed_dates_and_source_strings(study: Path) -> None:
    long_text = "x" * 129
    put_csv(study, f'Date,Text\n2026-03-04,{long_text}\n05-Mar-2026,"  raw  "\n')
    profile_study(study.name, options=ProfileOptions(sample_limit=1))
    dates, text = profile(study)["columns"]
    assert (
        dates["dates"]["status"] == "mixed" and not dates["dates"]["ambiguous_locale"]
    )
    assert text["examples"] == ["  raw  "] and text["length"]["max"] == 129


def test_streaming_many_records_and_capped_distinct(study: Path) -> None:
    source = study / "cdash/data/many.csv"
    with source.open("w", encoding="utf-8") as stream:
        stream.write("Reading\n")
        for index in range(20_000):
            stream.write(f"{index}\n")
    doc = CsvAdapter().profile(source, ProfileOptions(distinct_limit=3))
    assert doc["row_count"] == 20_000
    column = doc["columns"][0]
    assert column["distinct_count"] is None and column["distinct_lower_bound"] == 4
    assert column["examples"] == [] and column["numeric"]["max"] == "19999"


def test_changed_csv_and_safe_io_diagnostics(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    put_csv(study, "A\nSENSITIVE\n")
    calls = iter(("a" * 64, "b" * 64))
    with monkeypatch.context() as patch:
        patch.setattr("trialnexa.profiling.csv_source.checksum", lambda _: next(calls))
        assert profile_study(study.name).errors[0][1] == "source_changed"

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError("SENSITIVE")

    monkeypatch.setattr(CsvAdapter, "profile", fail)
    assert cli.main(["cdash", "profile", "--study", study.name]) == 1
    assert "SENSITIVE" not in capsys.readouterr().err

    def interrupt(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(CsvAdapter, "profile", interrupt)
    assert cli.main(["cdash", "profile", "--study", study.name]) == 130


@pytest.mark.parametrize("args", [["cdash", "--help"], ["cdash", "profile", "--help"]])
def test_help_is_safe(
    args: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 0 and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_limit": -1},
        {"sample_limit": 101},
        {"distinct_limit": 0},
        {"missing_sentinels": (" ",)},
    ],
)
def test_invalid_options(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ProfileError):
        ProfileOptions(**kwargs)


def test_documented_examples_validate() -> None:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    paths = list((SCHEMA.parent.parent / "examples/profiling").iterdir())
    assert len(paths) == 3
    for path in paths:
        raw = path.read_bytes()
        doc = yaml.safe_load(raw) if path.suffix == ".yaml" else json.loads(raw)
        validator.validate(doc)


@pytest.mark.parametrize(
    "raw", [b"{", b'{"a":1,"a":2}', b"null", b'{"value":NaN}', b"\xff"]
)
def test_invalid_ownership_manifest_fails_safely(study: Path, raw: bytes) -> None:
    put_csv(study, "A\n1\n")
    manifest = study / "cdash/metadata/.profiling-manifest.json"
    manifest.write_bytes(raw)
    with pytest.raises(ProfileError, match="Invalid profiling manifest"):
        profile_study(study.name)
    assert artifacts(study) == {manifest.name: raw}


def test_csv_limits_and_exact_distinct_boundary(study: Path) -> None:
    source = put_csv(study, "Value\nA\nB\nA\n")
    observation = CsvAdapter().profile(source, ProfileOptions(distinct_limit=2))
    column = observation["columns"][0]
    assert (
        column["distinct_count"] == 2
        and column["distinct_method"] == "exact_sha256_set"
    )
    put_csv(study, "Value\n" + "x" * 1_048_577)
    assert profile_study(study.name).errors[0][1] == "invalid_csv"
    put_csv(study, ",".join(f"C{index}" for index in range(4097)) + "\n")
    assert profile_study(study.name).errors[0][1] == "column_limit"


def test_missing_workspace_and_invalid_manifest_do_not_write(
    tmp_path: Path,
    study: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Explicit root resolution must not create a study or a source directory.
    assert (
        cli.main(
            [
                "cdash",
                "profile",
                "--study",
                "absent",
                "--workspace",
                str(tmp_path / "absent"),
            ]
        )
        == 1
    )
    assert not (tmp_path / "absent").exists()
    put_csv(study, "A\n1\n")
    (study / "study.yaml").write_text("secret: [SENSITIVE\n", encoding="utf-8")
    assert cli.main(["cdash", "profile", "--study", study.name]) == 1
    assert "SENSITIVE" not in capsys.readouterr().err
    assert artifacts(study) == {}
    with pytest.raises(SystemExit) as exc:
        cli.main(["cdash", "profile"])
    assert exc.value.code == 2
