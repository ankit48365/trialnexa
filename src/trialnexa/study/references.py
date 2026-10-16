"""Discover only immediate reference version directories, without reading data."""

import stat
from dataclasses import dataclass
from pathlib import Path

from trialnexa.study.layout import check_path, is_release_name

# These are naming conventions, never default versions.
REFERENCE_PATTERNS = {
    "cdash": ("cdash", "v"),
    "sdtmig": ("sdtm", "sdtmig_v"),
    "adamig": ("adam", "adamig_v"),
    "define_xml": ("define_xml", "v"),
    "controlled_terminology": ("controlled_terminology", ""),
}


@dataclass(frozen=True)
class DiscoveryResult:
    """Unambiguous selections and reviewable warnings."""

    versions: dict[str, str]
    warnings: tuple[str, ...]


def reference_directory(reference: Path, standard: str, version: str) -> Path:
    """Construct a reference pointer after its version has been checked."""
    group, prefix = REFERENCE_PATTERNS[standard]
    return reference / group / f"{prefix}{version}"


def discover_versions(reference: Path) -> DiscoveryResult:
    """Select exactly one candidate, otherwise leave the setting empty."""
    versions = {}
    warnings = []
    for standard, (group, prefix) in REFERENCE_PATTERNS.items():
        parent = reference / group
        candidates = []
        if check_path(parent, directory=True, allow_missing=True):
            for entry in sorted(parent.iterdir()):
                if not entry.name.startswith(prefix):
                    continue
                version = entry.name[len(prefix) :]
                if not is_release_name(version):
                    continue
                # Version-like files are not installed directories. Links are
                # rejected rather than followed, including Windows junctions.
                if entry.is_symlink() or entry.is_junction():
                    check_path(entry, directory=True)
                if stat.S_ISDIR(entry.lstat().st_mode):
                    candidates.append(version)
        versions[standard] = candidates[0] if len(candidates) == 1 else ""
        if len(candidates) > 1:
            warnings.append(
                f"standards.{standard}: multiple installed versions "
                f"({', '.join(candidates)}); left unconfigured. "
                "Select a version in study.yaml after review."
            )
        elif not candidates:
            warnings.append(
                f"standards.{standard}: no installed version; unconfigured."
            )
    return DiscoveryResult(versions, tuple(warnings))
