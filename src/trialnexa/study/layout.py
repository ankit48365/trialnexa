"""Portable names, fixed layout, and filesystem boundary checks."""

import re
import stat
from pathlib import Path

from trialnexa.study import StudyError

STUDY_PATHS = {
    "raw": ("crf", "external"),
    "cdash": ("data", "metadata"),
    "sdtm": ("data", "metadata"),
    "adam": ("data", "metadata"),
    "mappings": ("crf_to_cdash", "cdash_to_sdtm", "sdtm_to_adam"),
    "outputs": ("define_xml", "validation", "reports", "submission"),
}
STUDY_DIRECTORIES = (
    *(Path(group) / name for group, names in STUDY_PATHS.items() for name in names),
    Path("logs"),
)
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


def validate_study_id(study_id: str) -> None:
    """Require 1–64 ASCII characters, starting with a letter or digit."""
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", study_id)
        or study_id.upper() in RESERVED_NAMES
    ):
        raise StudyError(
            "Invalid study ID: use 1–64 ASCII letters, digits, '_' or '-', "
            "starting with a letter or digit; Windows device names are reserved."
        )


def is_release_name(value: str) -> bool:
    """Accept a single portable reference directory component, never a path."""
    return bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
        and not value.endswith(".")
        and value.split(".", 1)[0].upper() not in RESERVED_NAMES
    )


def check_path(path: Path, *, directory: bool, allow_missing: bool = False) -> bool:
    """Reject links/junctions and collisions; return False only if allowed absent."""
    if path.is_symlink() or path.is_junction():
        raise StudyError(f"Symbolic link or junction is not allowed: {path}")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        if allow_missing:
            return False
        raise StudyError(f"Required path is missing: {path}") from None
    predicate = stat.S_ISDIR if directory else stat.S_ISREG
    if not predicate(mode):
        kind = "directory" if directory else "regular file"
        raise StudyError(f"Expected a {kind}; incompatible path: {path}")
    return True


def check_study_directory(study: Path, relative: Path) -> None:
    """Check every component so an intermediate link cannot redirect a path."""
    current = study
    for part in relative.parts:
        current /= part
        check_path(current, directory=True)
