"""Filesystem services for the empty CDISC reference hierarchy."""

import stat
from dataclasses import dataclass
from pathlib import Path

REFERENCE_ROOT = Path("cdisc_reference")
REFERENCE_DIRECTORIES = (
    REFERENCE_ROOT,
    REFERENCE_ROOT / "cdash",
    REFERENCE_ROOT / "cdash" / "imports",
    REFERENCE_ROOT / "cdash" / "v2.3",
    REFERENCE_ROOT / "sdtm",
    REFERENCE_ROOT / "sdtm" / "sdtmig_v3.4",
    REFERENCE_ROOT / "adam",
    REFERENCE_ROOT / "adam" / "adamig_v1.3",
    REFERENCE_ROOT / "controlled_terminology",
    REFERENCE_ROOT / "define_xml",
    REFERENCE_ROOT / "define_xml" / "v2.0",
    REFERENCE_ROOT / "define_xml" / "v2.1",
    REFERENCE_ROOT / "define_xml" / "v2.1" / "schemas",
    REFERENCE_ROOT / "validation_rules",
    REFERENCE_ROOT / "validation_rules" / "cdisc_core",
    REFERENCE_ROOT / "validation_rules" / "custom",
    REFERENCE_ROOT / "study_profiles",
)


class WorkspaceError(RuntimeError):
    """The workspace hierarchy cannot be initialized safely."""


@dataclass(frozen=True)
class ReferencePaths:
    """Resolved paths for an import, independent of CSV/model/publishing code."""

    root: Path
    source: Path
    destination: Path


def resolve_reference_paths(
    source: Path, workspace: Path | None = None
) -> ReferencePaths:
    """Resolve source from cwd and root from an explicit path or ancestor marker.

    Prefer the nearest initialized cdisc_reference workspace; otherwise use the
    nearest Git checkout. Without either marker, require init or --workspace.
    """
    cwd = Path.cwd().resolve(strict=True)
    source = source if source.is_absolute() else cwd / source
    if workspace is None:
        ancestors = (cwd, *cwd.parents)
        root = next((p for p in ancestors if (p / REFERENCE_ROOT).exists()), None)
        if root is None:
            root = next((p for p in ancestors if (p / ".git").exists()), None)
        if root is None:
            raise WorkspaceError(
                "No workspace root found. Run trialnexa init at the intended root "
                "or specify --workspace ROOT."
            )
    else:
        root = workspace.resolve(strict=True)
    _check_directory(root, allow_missing=False)
    return ReferencePaths(root, source, root / REFERENCE_ROOT / "cdash" / "v2.3")


def _check_directory(path: Path, *, allow_missing: bool) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        if allow_missing:
            return
        raise
    if stat.S_ISLNK(mode):
        raise WorkspaceError(f"Required directory is a symbolic link: {path}")
    if not stat.S_ISDIR(mode):
        raise WorkspaceError(
            f"Required directory is occupied by a non-directory: {path}"
        )


def initialize_workspace(root: Path) -> Path:
    """Fill in the hierarchy at an existing root after the caller obtains consent.

    Preflight every required path before creating anything. Existing contents are
    preserved; symbolic links in the hierarchy are rejected to keep writes local.
    An I/O failure may leave a partial tree, which a subsequent call can complete.
    """
    try:
        root = root.resolve(strict=True)
        _check_directory(root, allow_missing=False)
        paths = tuple(root / relative for relative in REFERENCE_DIRECTORIES)
        for path in paths:
            _check_directory(path, allow_missing=True)
        for path in paths:
            path.mkdir(exist_ok=True)
        for path in paths:
            _check_directory(path, allow_missing=False)
    except OSError as exc:
        failed_path = exc.filename or root
        reason = exc.strerror or str(exc)
        raise WorkspaceError(f"Filesystem error at '{failed_path}': {reason}") from exc
    return root / REFERENCE_ROOT
