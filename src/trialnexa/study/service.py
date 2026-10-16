"""Transactional study creation and read-only enumeration."""

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from trialnexa.study import StudyError
from trialnexa.study.config import make_config, serialize_config
from trialnexa.study.layout import STUDY_DIRECTORIES, check_path, validate_study_id
from trialnexa.study.references import discover_versions
from trialnexa.workspace import resolve_initialized_workspace


@dataclass(frozen=True)
class StudyResult:
    """Created location and reference selection warnings."""

    path: Path
    warnings: tuple[str, ...]


def _check_new_study(destination: Path) -> None:
    try:
        destination.lstat()
    except FileNotFoundError:
        return
    raise StudyError(
        f"Study path already exists: {destination}. "
        f"Use trialnexa study validate {destination.name} to inspect it."
    )


def initialize_study(study_id: str, *, workspace: Path | None = None) -> StudyResult:
    """Install a complete new study without changing references or existing studies.

    A per-study exclusive lock coordinates TrialNexa writers. Same-filesystem
    staging/rename keeps failed writes away from the final study path. This is
    not protection against hostile concurrent filesystem modifications or power
    loss; a killed process can leave a hidden stage/lock for manual inspection.
    """
    validate_study_id(study_id)
    root = resolve_initialized_workspace(workspace)
    studies = root / "studies"
    studies_existed = check_path(studies, directory=True, allow_missing=True)
    destination = studies / study_id
    _check_new_study(destination)
    discovery = discover_versions(root / "cdisc_reference")
    contents = serialize_config(make_config(study_id, discovery.versions))
    try:
        studies.mkdir(exist_ok=True)
        check_path(studies, directory=True)
        lock = studies / f".{study_id}.init.lock"
        try:
            lock.mkdir()
        except FileExistsError as exc:
            raise StudyError(
                f"Study initialization is running or a stale lock exists: {lock}. "
                "Inspect it before retrying."
            ) from exc
        try:
            _check_new_study(destination)
            with tempfile.TemporaryDirectory(
                prefix=f".{study_id}.init-", dir=studies, ignore_cleanup_errors=True
            ) as temporary:
                stage = Path(temporary) / "study"
                stage.mkdir()
                for relative in STUDY_DIRECTORIES:
                    (stage / relative).mkdir(parents=True)
                with (stage / "study.yaml").open(
                    "x", encoding="utf-8", newline="\n"
                ) as f:
                    f.write(contents)
                    f.flush()
                    os.fsync(f.fileno())
                _check_new_study(destination)
                check_path(studies, directory=True)
                stage.rename(destination)
        finally:
            lock.rmdir()
    finally:
        if not studies_existed:
            try:
                studies.rmdir()  # Only remove our newly created, empty parent.
            except OSError:
                pass
    return StudyResult(destination, discovery.warnings)


def list_studies(*, workspace: Path | None = None) -> tuple[str, ...]:
    """List direct studies with a regular study.yaml; never parse clinical data.

    Unrelated files/directories are ignored. Links, invalid IDs with study.yaml,
    and incompatible configuration entries are actionable errors.
    """
    root = resolve_initialized_workspace(workspace)
    studies = root / "studies"
    if not check_path(studies, directory=True, allow_missing=True):
        return ()
    result = []
    for entry in sorted(studies.iterdir()):
        if entry.is_symlink() or entry.is_junction():
            raise StudyError(f"Linked entry in studies/ is not allowed: {entry}")
        if not stat.S_ISDIR(entry.lstat().st_mode):
            continue
        config = entry / "study.yaml"
        if not check_path(config, directory=False, allow_missing=True):
            continue
        validate_study_id(entry.name)
        result.append(entry.name)
    return tuple(result)
