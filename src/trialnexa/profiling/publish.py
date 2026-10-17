"""Atomic report installation with exact-byte ownership and rollback."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from trialnexa.profiling import ProfileError
from trialnexa.profiling.paths import safe_filename
from trialnexa.study.layout import check_path

GENERATOR = "trialnexa.source_profile"
MANIFEST = ".profiling-manifest.json"


def json_bytes(document: object) -> bytes:
    """Stable UTF-8 JSON without runtime timestamps or nonfinite numbers."""
    return (
        json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _read_manifest(path: Path) -> tuple[dict[str, str], bytes | None]:
    if not check_path(path, directory=False, allow_missing=True):
        return {}, None
    with path.open("rb") as stream:
        raw = stream.read(16_777_217)
    try:
        if len(raw) > 16_777_216:
            raise ValueError("Size limit")
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        json.dumps(doc, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if (
            not isinstance(doc, dict)
            or set(doc) != {"generator", "schema_version", "files"}
            or doc["generator"] != GENERATOR
            or doc["schema_version"] != "1.0"
            or not isinstance(doc["files"], dict)
            or any(
                not safe_filename(k)
                or not isinstance(v, str)
                or len(v) != 64
                or any(c not in "0123456789abcdef" for c in v)
                for k, v in doc["files"].items()
            )
        ):
            raise ValueError("Schema")
    except (ValueError, RecursionError) as exc:
        raise ProfileError(
            "ownership_manifest",
            "Invalid profiling manifest. Preserve reports and inspect "
            ".profiling-manifest.json before retrying.",
        ) from exc
    return doc["files"], raw


def publish_reports(destination: Path, contents: dict[str, bytes]) -> None:
    """Replace only unedited generated files, preserving unrelated metadata.

    Cooperating writers use a metadata-local lock. Individual files are installed
    atomically; failure rolls the batch back. Process kill/power loss or external
    filesystem races are outside this guarantee.
    """
    if any(not safe_filename(name) or name == MANIFEST for name in contents):
        raise ProfileError("unsafe_output_path", "Reports require direct filenames.")
    check_path(destination, directory=True, allow_missing=True)
    destination.mkdir(exist_ok=True)
    lock = destination / ".profiling.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ProfileError(
            "publication_locked",
            f"Active profiling or stale lock: {lock}. Inspect before retrying.",
        ) from exc
    try:
        _publish_locked(destination, contents)
    finally:
        lock.rmdir()


def _publish_locked(destination: Path, contents: dict[str, bytes]) -> None:
    owned, manifest_raw = _read_manifest(destination / MANIFEST)
    previous = {MANIFEST: manifest_raw}
    for name, data in contents.items():
        path = destination / name
        exists = check_path(path, directory=False, allow_missing=True)
        if exists and name not in owned:
            raise ProfileError(
                "user_artifact_collision",
                f"Unmanaged or edited report: {path}. "
                "Preserve/move it before regenerating.",
            )
        raw = path.read_bytes() if exists else None
        if exists and hashlib.sha256(raw).hexdigest() != owned[name]:
            raise ProfileError(
                "user_artifact_collision",
                f"Unmanaged or edited report: {path}. "
                "Preserve/move it before regenerating.",
            )
        previous[name] = raw
        owned[name] = hashlib.sha256(data).hexdigest()
    planned = {
        **contents,
        MANIFEST: json_bytes(
            {
                "generator": GENERATOR,
                "schema_version": "1.0",
                "files": dict(sorted(owned.items())),
            }
        ),
    }
    changed = {name: data for name, data in planned.items() if previous[name] != data}
    if not changed:
        return
    transaction = Path(tempfile.mkdtemp(prefix=".profiling-stage-", dir=destination))
    installed = []
    preserve = False
    try:
        stage = transaction / "new"
        backup = transaction / "previous"
        stage.mkdir()
        backup.mkdir()
        for name, data in changed.items():
            with (stage / name).open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if previous[name] is not None:
                (backup / name).write_bytes(previous[name])
        for name in changed:
            path = destination / name
            exists = check_path(path, directory=False, allow_missing=True)
            if (path.read_bytes() if exists else None) != previous[name]:
                raise ProfileError(
                    "report_changed",
                    "Report changed during publication; retry after review.",
                )
        try:
            for name in changed:
                os.replace(stage / name, destination / name)
                installed.append(name)
        except BaseException:
            try:
                for name in reversed(installed):
                    if previous[name] is None:
                        (destination / name).unlink()
                    else:
                        os.replace(backup / name, destination / name)
            except BaseException as exc:
                preserve = True
                raise ProfileError(
                    "rollback_failed",
                    "Publication/rollback failed. Previous reports retained in "
                    f"{backup}; restore before retrying.",
                ) from exc
            raise
    finally:
        if not preserve:
            shutil.rmtree(transaction, ignore_errors=True)
