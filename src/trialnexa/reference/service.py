"""Coordinate offline ingestion, validation and snapshot publication."""

from dataclasses import dataclass
from pathlib import Path

from trialnexa.reference.csv_source import read_csv
from trialnexa.reference.model import normalize_rows, serialize_documents
from trialnexa.reference.publish import publish_snapshot
from trialnexa.workspace import resolve_reference_paths


@dataclass(frozen=True)
class ImportResult:
    """Counts and generated paths without including source cell contents."""

    rows: int
    domains: int
    paths: tuple[Path, ...]


def import_cdash(
    source: Path, *, workspace: Path | None = None, force: bool = False
) -> ImportResult:
    """Import user-supplied CDASHIG 2.3 metadata; never execute mapping guidance."""
    paths = resolve_reference_paths(source, workspace)
    rows = read_csv(paths.source)
    documents = normalize_rows(rows)
    contents = serialize_documents(documents)
    publish_snapshot(paths.root, paths.destination, contents, force=force)
    return ImportResult(
        len(rows),
        len(documents["domains.json"]["domains"]),
        tuple(paths.destination / name for name in contents),
    )
