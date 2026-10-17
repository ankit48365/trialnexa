"""Orchestrate descriptive source reports with no standards dependency."""

from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import yaml

from trialnexa.profiling import ProfileError
from trialnexa.profiling.csv_source import CsvAdapter, ProfileOptions, SourceAdapter
from trialnexa.profiling.paths import discover_sources, resolve_paths
from trialnexa.profiling.publish import GENERATOR, json_bytes, publish_reports
from trialnexa.study import StudyError
from trialnexa.study.layout import check_path


@dataclass(frozen=True)
class ProfileResult:
    """Counts and safe structural diagnostics, without cell values."""

    processed: int
    failures: int
    warnings: int
    destination: Path
    errors: tuple[tuple[str, str, str], ...]


def profile_study(
    study_id: str,
    *,
    workspace: Path | None = None,
    selected: str | None = None,
    options: ProfileOptions | None = None,
    adapter: SourceAdapter | None = None,
) -> ProfileResult:
    """Profile existing study CSVs and write source-only metadata artifacts."""
    paths = resolve_paths(study_id, workspace)
    sources = discover_sources(paths.source, selected)
    options = options or ProfileOptions()
    adapter = adapter or CsvAdapter()
    common = {
        "schema_version": "1.0",
        "study_id": study_id,
        "generated_by": {
            "tool": GENERATOR,
            "package_version": version("trialnexa"),
            "algorithm_version": "1",
        },
    }
    settings = {
        "examples": {
            "strategy": "suppressed"
            if not options.sample_limit
            else "first_distinct_nonmissing_raw_strings",
            "limit_per_column": options.sample_limit,
            "max_characters_per_value": 128,
            "long_values": "omitted",
        },
        "distinct_limit": options.distinct_limit,
        "missing_sentinels": sorted(
            set(s.strip().casefold() for s in options.missing_sentinels)
        ),
        "sentinel_matching": "strip_and_casefold_for_classification_only",
    }
    contents = {}
    files = []
    errors = []
    for path in sources:
        relative = path.relative_to(paths.root).as_posix()
        try:
            check_path(path, directory=False)
            observation = adapter.profile(path, options)
        except (ProfileError, OSError, StudyError) as exc:
            code = exc.code if isinstance(exc, ProfileError) else "source_unreadable"
            message = (
                str(exc)
                if isinstance(exc, ProfileError)
                else "Cannot read source CSV; check file type and read permissions."
            )
            errors.append((path.name, code, message))
            files.append(
                {
                    "source_path": relative,
                    "status": "failed",
                    "row_count": None,
                    "column_count": None,
                    "warning_count": 0,
                    "errors": [{"code": code, "message": message}],
                    "outputs": [],
                }
            )
            continue
        columns = observation.pop("columns")
        source = {
            "filename": path.name,
            "workspace_relative_path": relative,
            "study_relative_path": path.relative_to(paths.study).as_posix(),
            **observation,
        }
        metadata = {
            **common,
            "document_kind": "metadata",
            "source": source,
            "settings": settings,
            "columns": [
                {
                    k: c[k]
                    for k in (
                        "ordinal",
                        "source_name",
                        "normalized_key",
                        "physical_type",
                        "inferred_type",
                        "type_status",
                        "mixed_type",
                        "type_evidence",
                        "nonnull_count",
                        "missing_count",
                        "missing_percentage",
                        "dates",
                        "warnings",
                    )
                }
                for c in columns
            ],
        }
        profile = {
            **common,
            "document_kind": "profile",
            "source": source,
            "settings": settings,
            "columns": columns,
        }
        reports = {
            f"{path.stem}.metadata.yaml": yaml.safe_dump(
                metadata, sort_keys=False, allow_unicode=True
            ).encode("utf-8"),
            f"{path.stem}.profile.json": json_bytes(profile),
        }
        contents.update(reports)
        warnings = sum(len(c["warnings"]) for c in columns)
        files.append(
            {
                "source_path": relative,
                "status": "warning" if warnings else "profiled",
                "row_count": source["row_count"],
                "column_count": source["column_count"],
                "warning_count": warnings,
                "errors": [],
                "outputs": [
                    (paths.destination / name).relative_to(paths.root).as_posix()
                    for name in reports
                ],
            }
        )
    warnings = sum(f["warning_count"] for f in files)
    summary = {
        **common,
        "document_kind": "profiling_summary",
        "settings": settings,
        "scope": "selected_file" if selected else "all_direct_csv_files",
        "files": files,
        "files_processed": len(files) - len(errors),
        "files_discovered": len(files),
        "error_count": len(errors),
        "warning_count": warnings,
        "row_count": sum(f["row_count"] or 0 for f in files),
        "column_count": sum(f["column_count"] or 0 for f in files),
        "status": "failed" if errors else "warning" if warnings else "profiled",
    }
    contents["profiling_summary.json"] = json_bytes(summary)
    publish_reports(paths.destination, contents)
    return ProfileResult(
        len(files) - len(errors),
        len(errors),
        warnings,
        paths.destination,
        tuple(errors),
    )
