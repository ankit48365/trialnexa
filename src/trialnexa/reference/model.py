"""Normalization and runtime validation of the version 1 JSON structure."""

import json
from typing import Any

from trialnexa.reference import ReferenceError
from trialnexa.reference.csv_source import COLUMNS, SourceRow, validate_source_values

CONTEXT_FIELDS = ("domain", "class", "scenario", "cdashig_variable")
MAPPING_FIELDS = (
    *CONTEXT_FIELDS,
    "sdtmig_target",
    "mapping_instructions",
    "implementation_notes",
)
VARIABLE_FIELDS = tuple(
    key
    for key in COLUMNS.values()
    if key not in {"sdtmig_target", "mapping_instructions"}
)
DOCUMENT_KEYS = {
    "domains.json": "domains",
    "variables.json": "variables",
    "mappings_to_sdtm.json": "mappings",
}


def normalize_rows(rows: list[SourceRow]) -> dict[str, dict[str, Any]]:
    """Retain source order and all row associations; sort domains and scenarios."""
    domains: dict[str, dict[str, Any]] = {}
    variables = []
    mappings = []
    for row in rows:
        values = row.values
        domain = values["domain"]
        if domain not in domains:
            domains[domain] = {
                "domain": domain,
                "class": values["class"],
                "scenarios": [],
            }
        entry = domains[domain]
        if entry["class"] != values["class"]:
            raise ReferenceError(
                f"Source row {row.source_row}: conflicting Class metadata for {domain}."
            )
        if values["scenario"] is not None:
            entry["scenarios"].append(values["scenario"])
        variables.append(
            {"source_row": row.source_row, **{k: values[k] for k in VARIABLE_FIELDS}}
        )
        mappings.append(
            {"source_row": row.source_row, **{k: values[k] for k in MAPPING_FIELDS}}
        )
    for entry in domains.values():
        entry["scenarios"] = sorted(set(entry["scenarios"]))
    records = {
        "domains": [domains[key] for key in sorted(domains)],
        "variables": variables,
        "mappings": mappings,
    }
    documents = {
        filename: {
            "schema_version": 1,
            "standard": "CDASHIG",
            "version": "2.3",
            key: records[key],
        }
        for filename, key in DOCUMENT_KEYS.items()
    }
    validate_documents(documents)
    # Validate the lossless 18-column reconstruction before any filesystem writes.
    for row, variable, mapping in zip(rows, variables, mappings, strict=True):
        rebuilt = {**variable, **mapping}
        if any(rebuilt[key] != value for key, value in row.values.items()):
            raise ReferenceError(
                f"Source row {row.source_row}: normalization lost text."
            )
    return documents


def validate_documents(documents: dict[str, dict[str, Any]]) -> None:
    """Check schema, provenance, cross-file joins, domain coverage and serialization."""

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ReferenceError(f"Invalid reference JSON: {message}")

    require(set(documents) == set(DOCUMENT_KEYS), "expected exactly three documents")
    for filename, key in DOCUMENT_KEYS.items():
        document = documents[filename]
        require(isinstance(document, dict), "document must be an object")
        require(
            set(document) == {"schema_version", "standard", "version", key}, filename
        )
        require(
            type(document["schema_version"]) is int and document["schema_version"] == 1,
            filename,
        )
        require(
            document["standard"] == "CDASHIG" and document["version"] == "2.3", filename
        )
        require(isinstance(document[key], list) and bool(document[key]), filename)

    variables = documents["variables.json"]["variables"]
    mappings = documents["mappings_to_sdtm.json"]["mappings"]
    require(len(variables) == len(mappings), "variable/mapping counts differ")
    for records, fields in ((variables, VARIABLE_FIELDS), (mappings, MAPPING_FIELDS)):
        for index, record in enumerate(records, start=1):
            require(isinstance(record, dict), "record must be an object")
            require(set(record) == {"source_row", *fields}, "record fields")
            require(
                type(record["source_row"]) is int and record["source_row"] == index,
                "source_row sequence",
            )
            require(
                all(record[k] is None or isinstance(record[k], str) for k in fields),
                "text types",
            )
            require(
                all(
                    isinstance(record[k], str) and bool(record[k])
                    for k in ("domain", "class", "cdashig_variable")
                ),
                "required identifiers",
            )
    for variable, mapping in zip(variables, mappings, strict=True):
        validate_source_values(variable["source_row"], {**variable, **mapping})
        require(
            all(
                variable[k] == mapping[k]
                for k in (*CONTEXT_FIELDS, "implementation_notes", "source_row")
            ),
            "row context mismatch",
        )
    expected_domains: dict[str, dict[str, Any]] = {}
    for variable in variables:
        domain = variable["domain"]
        entry = expected_domains.setdefault(
            domain, {"domain": domain, "class": variable["class"], "scenarios": []}
        )
        require(entry["class"] == variable["class"], "domain Class conflict")
        if variable["scenario"] is not None:
            entry["scenarios"].append(variable["scenario"])
    for entry in expected_domains.values():
        entry["scenarios"] = sorted(set(entry["scenarios"]))
    require(
        documents["domains.json"]["domains"]
        == [expected_domains[k] for k in sorted(expected_domains)],
        "domain/scenario coverage",
    )
    try:
        require(
            json.loads(json.dumps(documents, ensure_ascii=False, allow_nan=False))
            == documents,
            "JSON round trip",
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ReferenceError(f"Unable to serialize reference JSON: {exc}") from exc


def serialize_documents(documents: dict[str, dict[str, Any]]) -> dict[str, bytes]:
    """Validate and encode stable, indented UTF-8 JSON with a final newline."""
    validate_documents(documents)
    try:
        return {
            filename: (
                json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)
                + "\n"
            ).encode("utf-8")
            for filename, document in documents.items()
        }
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ReferenceError(f"Unable to serialize reference JSON: {exc}") from exc
