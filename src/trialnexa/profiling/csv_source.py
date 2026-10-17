"""Streaming positional CSV statistics with explicit privacy and memory bounds."""

import csv
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from trialnexa.profiling import ProfileError
from trialnexa.profiling.inference import INTEGER, header_tokens, representation


@dataclass(frozen=True)
class ProfileOptions:
    """Samples require explicit opt-in; no sentinel is missing by default."""

    sample_limit: int = 0
    distinct_limit: int = 10_000
    missing_sentinels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not 0 <= self.sample_limit <= 100
            or not 1 <= self.distinct_limit <= 1_000_000
        ):
            raise ProfileError(
                "invalid_limits",
                "sample-limit must be 0–100; distinct-limit 1–1000000.",
            )
        if any(not s.strip() or len(s) > 128 for s in self.missing_sentinels):
            raise ProfileError(
                "invalid_sentinel", "Sentinels need 1–128 nonblank characters."
            )


class SourceAdapter(Protocol):
    """Future formats can supply the same observations without changing services."""

    def profile(self, path: Path, options: ProfileOptions) -> dict[str, Any]: ...


def checksum(path: Path) -> str:
    """Hash original bytes with bounded reads."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass
class _Column:
    name: str
    ordinal: int
    options: ProfileOptions
    warnings: list[str] = field(default_factory=list)
    missing: Counter[str] = field(default_factory=Counter)
    kinds: Counter[str] = field(default_factory=Counter)
    formats: Counter[str] = field(default_factory=Counter)
    distinct: set[bytes] = field(default_factory=set)
    overflow: bool = False
    samples: list[str] = field(default_factory=list)
    sample_hashes: set[bytes] = field(default_factory=set)
    nonnull: int = 0
    min_length: int | None = None
    max_length: int | None = None
    total_length: int = 0
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    numeric_count: int = 0
    numeric_errors: int = 0
    sign_counts: Counter[str] = field(default_factory=Counter)
    ambiguous_dates: int = 0
    leading_zero_count: int = 0
    surrounding_whitespace: int = 0

    def add(self, value: str, sentinels: frozenset[str]) -> None:
        digest = hashlib.sha256(value.encode("utf-8")).digest()
        if len(self.distinct) < self.options.distinct_limit:
            self.distinct.add(digest)
        elif digest not in self.distinct:
            self.overflow = True
        stripped = value.strip()
        if value == "":
            self.missing["empty"] += 1
            return
        if not stripped:
            self.missing["whitespace"] += 1
            return
        if stripped.casefold() in sentinels:
            self.missing["sentinel"] += 1
            return
        self.nonnull += 1
        length = len(value)
        self.min_length = (
            length if self.min_length is None else min(self.min_length, length)
        )
        self.max_length = (
            length if self.max_length is None else max(self.max_length, length)
        )
        self.total_length += length
        if (
            len(self.samples) < self.options.sample_limit
            and length <= 128
            and digest not in self.sample_hashes
        ):
            self.samples.append(value)
            self.sample_hashes.add(digest)
        self.surrounding_whitespace += value != stripped
        kind, formats = representation(value)
        self.kinds[kind] += 1
        self.formats.update(formats)
        self.ambiguous_dates += len(formats) > 1
        if kind in {"integer", "decimal"}:
            digits = value.lstrip("+-")
            self.leading_zero_count += bool(
                INTEGER.fullmatch(value) and len(digits) > 1 and digits.startswith("0")
            )
            try:
                number = Decimal(value)
                self.minimum = (
                    number if self.minimum is None else min(self.minimum, number)
                )
                self.maximum = (
                    number if self.maximum is None else max(self.maximum, number)
                )
                self.numeric_count += 1
                self.sign_counts[
                    "negative" if number < 0 else "positive" if number > 0 else "zero"
                ] += 1
            except InvalidOperation:
                self.numeric_errors += 1

    def finish(self, rows: int) -> dict[str, Any]:
        tokens = set(header_tokens(self.name))
        identifier_header = bool(tokens & {"id", "identifier"})
        identifier_like = identifier_header or bool(self.leading_zero_count)
        kinds = set(self.kinds)
        mixed = (
            len(kinds - {"integer", "decimal"}) + bool(kinds & {"integer", "decimal"})
            > 1
        )
        logical = "unknown"
        if self.nonnull:
            if identifier_like:
                logical = "string"
            elif kinds <= {"integer", "decimal"}:
                logical = "decimal" if "decimal" in kinds else "integer"
            elif len(kinds) == 1 and next(iter(kinds)) in {
                "boolean",
                "date",
                "datetime",
                "string",
            }:
                logical = next(iter(kinds))
            else:
                logical = "string"
        date_successes = self.kinds["date"] + self.kinds["datetime"]
        temporal = (
            bool(tokens & {"date", "datetime", "time"})
            or date_successes
            or self.kinds["invalid_date"]
        )
        date_failures = self.nonnull - date_successes if temporal else 0
        warnings = list(self.warnings)
        for condition, code in (
            (not rows, "header_only"),
            (not self.nonnull, "all_missing"),
            (mixed, "mixed_types"),
            (self.ambiguous_dates, "ambiguous_date_locale"),
            (len(self.formats) > 1, "mixed_date_formats"),
            (self.kinds["invalid_date"], "invalid_date"),
            (date_failures, "unrecognized_date_values"),
            (self.surrounding_whitespace, "surrounding_whitespace"),
            (self.numeric_errors, "numeric_range_unavailable"),
        ):
            if condition:
                warnings.append(code)
        missing_count = sum(self.missing.values())
        return {
            "ordinal": self.ordinal,
            "source_name": self.name,
            "normalized_key": "".join(header_tokens(self.name)),
            "physical_type": "string",
            "inferred_type": logical,
            "type_status": "no_observations"
            if not self.nonnull
            else "mixed"
            if mixed
            else "identifier_like"
            if identifier_like
            else "consistent",
            "mixed_type": mixed,
            "type_evidence": {
                "representation_counts": dict(sorted(self.kinds.items())),
                "identifier_header": identifier_header,
                "leading_zero_integer_count": self.leading_zero_count,
            },
            "nonnull_count": self.nonnull,
            "missing_count": missing_count,
            "missing_percentage": round(100 * missing_count / rows, 6)
            if rows
            else None,
            "missingness": {
                k: self.missing[k] for k in ("empty", "whitespace", "sentinel")
            },
            "distinct_count": None if self.overflow else len(self.distinct),
            "distinct_lower_bound": len(self.distinct) + int(self.overflow),
            "distinct_method": "capped_sha256_set"
            if self.overflow
            else "exact_sha256_set",
            "length": {
                "min": self.min_length,
                "max": self.max_length,
                "mean": round(self.total_length / self.nonnull, 6)
                if self.nonnull
                else None,
            },
            "numeric": {
                "count": self.numeric_count if not identifier_like else 0,
                "min": str(self.minimum)
                if not identifier_like and self.minimum is not None
                else None,
                "max": str(self.maximum)
                if not identifier_like and self.maximum is not None
                else None,
                "failure_count": self.numeric_errors,
                "sign_counts": {
                    k: self.sign_counts[k] if not identifier_like else 0
                    for k in ("negative", "zero", "positive")
                },
            },
            "dates": {
                "status": "ambiguous"
                if self.ambiguous_dates
                else "mixed"
                if len(self.formats) > 1
                else "observed"
                if date_successes
                else "unrecognized"
                if temporal
                else "not_observed",
                "formats": dict(sorted(self.formats.items())),
                "success_count": date_successes,
                "failure_count": date_failures,
                "invalid_calendar_count": self.kinds["invalid_date"],
                "ambiguous_count": self.ambiguous_dates,
                "ambiguous_locale": bool(self.ambiguous_dates),
                "mixed_formats": len(self.formats) > 1,
            },
            "examples": self.samples,
            "warnings": warnings,
        }


class CsvAdapter:
    """Mandatory-header, comma-delimited UTF-8 CSV, preserving positional fields."""

    def profile(self, path: Path, options: ProfileOptions) -> dict[str, Any]:
        before = checksum(path)
        with path.open("rb") as stream:
            encoding = "utf-8-bom" if stream.read(3) == b"\xef\xbb\xbf" else "utf-8"
        sentinels = frozenset(s.strip().casefold() for s in options.missing_sentinels)
        previous_limit = csv.field_size_limit()
        csv.field_size_limit(1_048_576)
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream, delimiter=",", strict=True)
                headers = next(reader, None)
                if not headers or all(not h.strip() for h in headers):
                    raise ProfileError(
                        "empty_csv", "CSV is blank or has no nonblank header."
                    )
                if len(headers) > 4096:
                    raise ProfileError("column_limit", "CSV exceeds 4096 columns.")
                if all(representation(h)[0] != "string" for h in headers):
                    raise ProfileError(
                        "headerless_csv",
                        "First record looks like values; CSV requires a header.",
                    )
                counts = Counter(headers)
                columns = []
                for ordinal, name in enumerate(headers, start=1):
                    warnings = []
                    if not name.strip():
                        warnings.append("blank_header")
                    if counts[name] > 1:
                        warnings.append("duplicate_header")
                    columns.append(_Column(name, ordinal, options, warnings))
                rows = 0
                for rows, values in enumerate(reader, start=1):
                    if len(values) != len(headers):
                        raise ProfileError(
                            "malformed_row",
                            f"CSV record {rows} has {len(values)} cells; "
                            f"expected {len(headers)}.",
                        )
                    for column, value in zip(columns, values, strict=True):
                        column.add(value, sentinels)
        except UnicodeError as exc:
            raise ProfileError(
                "invalid_encoding", "CSV must use UTF-8 or UTF-8-BOM."
            ) from exc
        except csv.Error as exc:
            raise ProfileError(
                "invalid_csv",
                "Malformed quoting or field exceeds the 1 MiB character limit.",
            ) from exc
        finally:
            csv.field_size_limit(previous_limit)
        if checksum(path) != before:
            raise ProfileError(
                "source_changed",
                "CSV changed during profiling; retry with stable input.",
            )
        return {
            "sha256": before,
            "encoding": encoding,
            "delimiter": ",",
            "row_count": rows,
            "column_count": len(headers),
            "parse_status": "header_only" if not rows else "parsed",
            "columns": [c.finish(rows) for c in columns],
        }
