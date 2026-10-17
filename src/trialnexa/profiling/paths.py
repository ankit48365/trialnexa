"""Study manifest resolution without accessing a standards/reference marker."""

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from trialnexa.profiling import ProfileError
from trialnexa.study.config import read_config
from trialnexa.study.layout import RESERVED_NAMES, check_path, validate_study_id


@dataclass(frozen=True)
class ProfilePaths:
    """Validated existing source location and permitted output location."""

    root: Path
    study: Path
    source: Path
    destination: Path


def resolve_paths(study_id: str, workspace: Path | None = None) -> ProfilePaths:
    """Find the nearest studies/ parent, then validate the requested manifest."""
    validate_study_id(study_id)
    if workspace is None:
        cwd = Path.cwd()
        root = None
        for ancestor in (cwd, *cwd.parents):
            try:
                (ancestor / "studies").lstat()
            except FileNotFoundError:
                continue
            root = ancestor
            break
        if root is None:
            raise ProfileError(
                "workspace_not_found",
                "No study workspace found. Run from its root/subdirectory "
                "or use --workspace ROOT.",
            )
    else:
        root = Path(os.path.abspath(workspace))
    check_path(root, directory=True)
    check_path(root / "studies", directory=True)
    study = root / "studies" / study_id
    check_path(study, directory=True)
    config = read_config(study / "study.yaml")
    if not isinstance(config.get("study_id"), str) or config["study_id"] != study_id:
        raise ProfileError(
            "study_config", "study.yaml study_id must match the requested directory."
        )
    paths = config.get("paths")
    cdash = paths.get("cdash") if isinstance(paths, dict) else None
    if not isinstance(cdash, dict) or any(
        not isinstance(cdash.get(key), str)
        or cdash[key] not in {f"cdash/{key}", f"./cdash/{key}"}
        for key in ("data", "metadata")
    ):
        raise ProfileError(
            "study_config",
            "paths.cdash.data/metadata must use './cdash/data' and "
            "'./cdash/metadata', relative to study.yaml.",
        )
    check_path(study / "cdash", directory=True)
    source = study / "cdash/data"
    check_path(source, directory=True)
    destination = study / "cdash/metadata"
    check_path(destination, directory=True, allow_missing=True)
    return ProfilePaths(root, study, source, destination)


def safe_filename(name: str) -> bool:
    """One portable filename component; never an absolute or traversal path."""
    try:
        name.encode("utf-8")
    except UnicodeError:
        return False
    return bool(
        name
        and name not in {".", ".."}
        and not re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', name)
        and not name.endswith((" ", "."))
        and name.split(".", 1)[0].upper() not in RESERVED_NAMES
    )


def discover_sources(data: Path, selected: str | None = None) -> tuple[Path, ...]:
    """Direct CSV files in stable order, rejecting portable output collisions."""
    if selected is not None and (
        not safe_filename(selected) or Path(selected).suffix.casefold() != ".csv"
    ):
        raise ProfileError(
            "invalid_input_path",
            "--input must be one direct CSV filename under cdash/data/, "
            "without traversal or separators.",
        )
    sources = []
    stems = set()
    for path in sorted(data.iterdir(), key=lambda p: p.name):
        if path.suffix.casefold() != ".csv":
            continue
        check_path(path, directory=False)
        if not safe_filename(path.name) or not safe_filename(path.stem):
            raise ProfileError(
                "unsafe_filename",
                "CSV filenames/stems must be portable path components.",
            )
        stem = unicodedata.normalize("NFC", path.stem).casefold()
        if stem in stems:
            raise ProfileError(
                "output_name_collision",
                "CSV stems collide after Unicode/case normalization. "
                "Rename files distinctly before profiling.",
            )
        stems.add(stem)
        sources.append(path)
    if selected is not None:
        sources = [p for p in sources if p.name == selected]
        if not sources:
            raise ProfileError(
                "missing_input",
                "Selected CSV not found directly under cdash/data/; "
                "filename matching is case-sensitive.",
            )
    if not sources:
        raise ProfileError(
            "empty_input_directory",
            "No CSV files in cdash/data/. Supply UTF-8 source CSVs first.",
        )
    return tuple(sources)
