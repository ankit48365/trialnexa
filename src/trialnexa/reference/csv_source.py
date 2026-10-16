"""Strict CSV ingestion without interpreting clinical metadata."""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from trialnexa.reference import ReferenceError

# Order defines the stable JSON field order; CSV columns may arrive reordered.
COLUMNS = {
    "Version": "source_version",
    "Class": "class",
    "Domain": "domain",
    "Data Collection Scenario/Implementation Option": "scenario",
    "Variable Order": "variable_order",
    "CDASHIG Variable": "cdashig_variable",
    "CDASHIG Variable Label": "cdashig_variable_label",
    "DRAFT CDASHIG Definition": "draft_cdashig_definition",
    "Question Text": "question_text",
    "Prompt": "prompt",
    "Type": "type",
    "CDASHIG Core": "cdashig_core",
    "Case Report Form Completion Instructions": "crf_completion_instructions",
    "SDTMIG Target": "sdtmig_target",
    "Mapping Instructions": "mapping_instructions",
    "CDISC CT Codelist Code(s), Subset Codes(s)": "ct_codelist_codes",
    "Codelist Submission Value": "codelist_submission_value",
    "Implementation Notes": "implementation_notes",
}


@dataclass(frozen=True)
class SourceRow:
    """A logical CSV record; source_row starts at 1 after the header."""

    source_row: int
    values: dict[str, str | None]


def read_csv(source: Path) -> list[SourceRow]:
    """Read exactly the supported 18 columns, retaining all nonempty text."""
    rows = []
    try:
        with source.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            headers = next(reader, None)
            if not headers:
                raise ReferenceError("Source CSV is empty or has no header.")
            duplicates = sorted({name for name in headers if headers.count(name) > 1})
            missing = sorted(set(COLUMNS) - set(headers))
            extra = sorted(set(headers) - set(COLUMNS))
            if duplicates or missing or extra:
                raise ReferenceError(
                    f"Invalid CSV headers: missing={missing}, "
                    f"duplicate={duplicates}, unexpected={extra}"
                )
            for index, cells in enumerate(reader, start=1):
                if len(cells) != len(headers):
                    raise ReferenceError(
                        f"Source row {index}: expected 18 cells, got {len(cells)}."
                    )
                raw = dict(zip(headers, cells, strict=True))
                values = {key: raw[column] or None for column, key in COLUMNS.items()}
                validate_source_values(index, values)
                rows.append(SourceRow(index, values))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ReferenceError(f"Unable to read source CSV '{source}': {exc}") from exc
    if not rows:
        raise ReferenceError("Source CSV contains no data rows.")
    return rows


def validate_source_values(index: int, values: dict[str, str | None]) -> None:
    """Validate structural identifiers, exact version and lossless order text."""
    if values["source_version"] not in {"2.3", "CDASHIG v2.3"}:
        raise ReferenceError(
            f"Source row {index}: Version must identify CDASHIG 2.3 "
            "(expected '2.3' or 'CDASHIG v2.3')."
        )
    for key in ("class", "domain", "cdashig_variable"):
        value = values[key]
        # Structural validation only: allow generic '--' variables and avoid
        # inventing CDISC naming/terminology rules from an unavailable standard.
        if (
            value is None
            or not value.strip()
            or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or (key != "class" and any(char.isspace() for char in value))
        ):
            raise ReferenceError(f"Source row {index}: invalid required {key}.")
    order = values["variable_order"]
    if order is None or re.fullmatch(r"[0-9]+", order) is None:
        raise ReferenceError(
            f"Source row {index}: Variable Order must contain "
            "nonnegative integer digits."
        )
