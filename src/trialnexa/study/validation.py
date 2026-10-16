"""Read-only configuration checks; no clinical rules or checksum verification."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from trialnexa.study import StudyError
from trialnexa.study.config import read_config
from trialnexa.study.layout import (
    STUDY_PATHS,
    check_path,
    check_study_directory,
    is_release_name,
    validate_study_id,
)
from trialnexa.study.references import REFERENCE_PATTERNS, reference_directory
from trialnexa.workspace import resolve_initialized_workspace


@dataclass(frozen=True)
class ValidationResult:
    """Structural errors and warnings, with no claim about standards compliance."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _mapping(
    config: dict[str, Any], key: str, label: str, errors: list[str]
) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        errors.append(
            f"{label}: required YAML mapping is missing or has the wrong type."
        )
        return {}
    return value


def _check_directory(study: Path, relative: Path, errors: list[str]) -> None:
    try:
        check_study_directory(study, relative)
    except (StudyError, OSError) as exc:
        errors.append(str(exc))


def _validate_paths(config: dict[str, Any], study: Path, errors: list[str]) -> None:
    paths = _mapping(config, "paths", "paths", errors)
    for group, names in STUDY_PATHS.items():
        values = _mapping(paths, group, f"paths.{group}", errors)
        for name in names:
            relative = Path(group) / name
            value = values.get(name)
            expected = relative.as_posix()
            if not isinstance(value, str) or value not in {expected, f"./{expected}"}:
                errors.append(
                    f"paths.{group}.{name}: expected './{expected}', "
                    "relative to study.yaml and contained in the study root."
                )
            # Check the prescribed layout even if the YAML pointer is malformed.
            _check_directory(study, relative, errors)
    _check_directory(study, Path("logs"), errors)


def _validate_options(config: dict[str, Any], errors: list[str]) -> None:
    validation = _mapping(config, "validation", "validation", errors)
    for name in ("offline", "custom_rules"):
        if type(validation.get(name)) is not bool:
            errors.append(f"validation.{name}: expected a YAML boolean.")
    engine = validation.get("rule_engine")
    if not isinstance(engine, str) or not engine.strip():
        errors.append("validation.rule_engine: expected a nonempty string.")
    reference = _mapping(config, "reference", "reference", errors)
    if type(reference.get("verify_checksums")) is not bool:
        errors.append("reference.verify_checksums: expected a YAML boolean.")
    value = reference.get("root")
    if (
        not isinstance(value, str)
        or "\\" in value
        or PureWindowsPath(value).drive
        or PurePosixPath(value) != PurePosixPath("../../cdisc_reference")
    ):
        errors.append(
            "reference.root: expected '../../cdisc_reference', resolving to the "
            "workspace's shared reference directory relative to study.yaml."
        )


def _validate_standards(
    config: dict[str, Any], reference: Path, errors: list[str], warnings: list[str]
) -> None:
    standards = _mapping(config, "standards", "standards", errors)
    for standard, (group, _) in REFERENCE_PATTERNS.items():
        value = standards.get(standard)
        label = f"standards.{standard}"
        if not isinstance(value, str):
            errors.append(f"{label}: expected a version string (empty is allowed).")
        elif not value:
            warnings.append(f"{label}: unconfigured; no standard version validated.")
        elif not is_release_name(value):
            errors.append(f"{label}: expected a safe version/release directory name.")
        else:
            try:
                check_path(reference / group, directory=True)
                candidate = reference_directory(reference, standard, value)
                check_path(candidate, directory=True)
                empty = not any(candidate.iterdir())
            except (StudyError, OSError) as exc:
                errors.append(
                    f"{label}: {exc}. Install the reference or update study.yaml."
                )
                continue
            status = "empty reference directory; " if empty else ""
            warnings.append(
                f"{label}: {status}reference completeness/content and checksums "
                "not verified."
            )


def validate_study(study_id: str, *, workspace: Path | None = None) -> ValidationResult:
    """Validate the expected structure and reference pointers without mutations."""
    validate_study_id(study_id)
    root = resolve_initialized_workspace(workspace)
    study = root / "studies" / study_id
    try:
        check_path(root / "studies", directory=True)
        check_path(study, directory=True)
        config = read_config(study / "study.yaml")
    except (StudyError, OSError) as exc:
        return ValidationResult((str(exc),), ())
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(config.get("study_id"), str) or config["study_id"] != study_id:
        errors.append(
            "study_id: required string must match the requested study directory."
        )
    _validate_paths(config, study, errors)
    _validate_options(config, errors)
    _validate_standards(config, root / "cdisc_reference", errors, warnings)
    return ValidationResult(tuple(errors), tuple(warnings))
