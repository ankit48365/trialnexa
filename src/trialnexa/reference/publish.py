"""Stage a complete snapshot and replace directories with rollback on failure."""

import os
import shutil
import tempfile
from pathlib import Path

from trialnexa.reference import ReferenceError
from trialnexa.reference.model import DOCUMENT_KEYS


def _check_path(path: Path, *, directory: bool) -> None:
    if path.is_symlink() or path.is_junction():
        raise ReferenceError(f"Reference path is a symbolic link or junction: {path}")
    if path.exists() and (not path.is_dir() if directory else not path.is_file()):
        raise ReferenceError(f"Reference path has an incompatible type: {path}")


def _check_destination(destination: Path) -> None:
    _check_path(destination, directory=True)
    if destination.exists():
        for entry in destination.iterdir():
            if entry.name not in DOCUMENT_KEYS:
                raise ReferenceError(
                    f"Unexpected destination entry; preserve it separately: {entry}"
                )
            _check_path(entry, directory=False)


def publish_snapshot(
    root: Path, destination: Path, contents: dict[str, bytes], *, force: bool = False
) -> None:
    """Publish one complete three-file directory, preserving old bytes on failure.

    Same-filesystem renames prevent mixed generations. Portable Python cannot
    exchange two nonempty directories in one operation: readers may briefly see
    an absent destination. A failed install restores the old directory; if even
    rollback fails, its backup is retained and its recovery path is reported.
    """
    if set(contents) != set(DOCUMENT_KEYS):
        raise ReferenceError(
            "Publishing requires exactly the three reference JSON files."
        )
    relative = destination.relative_to(root)
    current = root
    try:
        _check_path(root, directory=True)
        # Preflight all paths before creating parents or staging anything.
        for part in relative.parts:
            current = current / part
            _check_path(current, directory=True)
        _check_destination(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        lock = destination.parent / ".v2.3.import.lock"
        try:
            lock.mkdir()
        except FileExistsError as exc:
            raise ReferenceError(
                f"Another import or stale lock exists: {lock}"
            ) from exc
        try:
            _publish_locked(destination, contents, force=force)
        finally:
            lock.rmdir()
    except OSError as exc:
        raise ReferenceError(
            f"Unable to publish reference snapshot at '{destination}': {exc}"
        ) from exc


def _publish_locked(
    destination: Path, contents: dict[str, bytes], *, force: bool
) -> None:
    _check_destination(destination)
    existing = (
        {p.name: p.read_bytes() for p in destination.iterdir()}
        if destination.exists()
        else {}
    )
    if existing == contents:
        return
    if not force and any(
        name in existing and existing[name] != data for name, data in contents.items()
    ):
        raise ReferenceError(
            "Destination contains different reference data. Use --force to replace it."
        )

    transaction = Path(tempfile.mkdtemp(prefix=".v2.3.import-", dir=destination.parent))
    stage = transaction / "snapshot"
    backup = transaction / "previous"
    preserve_backup = False
    try:
        stage.mkdir()
        for name, data in contents.items():
            with (stage / name).open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        # Recheck after staging and before moving the existing snapshot.
        _check_destination(destination)
        try:
            if destination.exists():
                destination.rename(backup)
            stage.rename(destination)
        except BaseException as install_error:
            # Also restore the old snapshot on Ctrl+C during either rename.
            if backup.exists():
                try:
                    backup.rename(destination)
                except BaseException as rollback_error:
                    preserve_backup = True
                    raise ReferenceError(
                        "Publication and rollback failed. "
                        "Previous snapshot retained at "
                        f"'{backup}'. Restore it before retrying. "
                        f"Publication: {install_error}; rollback: {rollback_error}"
                    ) from rollback_error
            raise
    finally:
        if not preserve_backup:
            # Cleanup cannot change publication success or invalidate its result.
            # A locked backup/stage may remain for manual cleanup on Windows.
            shutil.rmtree(transaction, ignore_errors=True)
