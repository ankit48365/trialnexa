# Source CSV metadata and statistical profiles (schema 1.0)

```console
trialnexa cdash profile --study DEMO_MODERN_01
trialnexa cdash profile --study DEMO_MODERN_01 --input 01_demographics_modern.csv
trialnexa cdash profile --study DEMO_MODERN_01 --workspace /path/to/workspace
trialnexa cdash profile --study DEMO_MODERN_01 --missing-sentinel NA --missing-sentinel NULL
trialnexa cdash profile --study DEMO_MODERN_01 --sample-limit 3 --distinct-limit 10000
```

This feature describes existing source CSVs. Upstream delivery must already have
placed them in `studies/<ID>/cdash/data/`. The `cdash/` location is an existing
study layout convention; it does not indicate standardized data. There is no
reference lookup, domain identification, target-variable matching, scoring,
mapping, conversion, standards validation, network access or AI execution.
Those interpretations belong to a subsequent Part 4 workflow.

## Existing study resolution

Without `--workspace`, use the nearest current/ancestor directory containing a
`studies/` entry as the workspace. A nearest invalid entry is an error; it never
silently falls back to a farther workspace. `--workspace ROOT` selects an existing
root explicitly, including when invoked from an unrelated directory.
No `cdisc_reference/` directory or reference configuration is read or required.
This feature's discovery differs intentionally from reference-dependent study
initialization/validation; those existing commands keep their current behavior.

Study IDs follow the existing portable 1–64 ASCII letters/digits/underscore/hyphen
rules, beginning with a letter/digit, excluding Windows device names. Existing
`study.yaml` is read with the project's safe loader: at most 1 MiB, UTF-8, mapping
with unique string keys, without aliases or executable tags. Its `study_id` must
match the requested directory. `paths.cdash.data` and `paths.cdash.metadata` must
be `cdash/data` and `cdash/metadata`, optionally prefixed with `./`, relative to
the parent of `study.yaml`. No other study sections or standards are needed.

The study and input directory must exist. Only the metadata directory may be
created. Sources, configuration and other study directories are never modified.
Paths within the workspace must be real directories/regular files; symlinks and
Windows junctions are rejected. An explicit root is user-selected and trusted;
links at the root itself or in study/output components are still rejected.
Hostile concurrent filesystem changes and hard-link detection are outside these
checks. Publication replaces files by rename rather than modifying linked bytes
in place.

## Discovery, encoding, and limits

Profile direct files ending in `.csv` (case-insensitive extension), in stable,
case-sensitive filename order. Discovery is not recursive; other extensions are
ignored. `--input` selects one exact filename from that directory, case-sensitively.
Separators, traversal, absolute/drive paths, reserved Windows names, control
characters and nonportable filename characters are rejected. All CSV stems must
remain distinct after NFC normalization and case folding, even during single-file
selection. Rename colliding inputs before profiling. No output stem is guessed
from a dataset's clinical meaning.

CSV is UTF-8 or UTF-8-BOM, comma-delimited, with a mandatory header and Python's
strict `csv.reader` double-quote escaping. Quoted commas and embedded CR/LF are
supported. Header spelling, order, duplicate/blank names, raw value strings,
leading zeros and surrounding whitespace are preserved. Physical type is always
`string`; inferred logical types describe observed syntax without converting data.
`row_count` counts logical data records, excluding the header and allowing quoted
line breaks. SHA-256 describes the original bytes including any BOM. The source
is hashed before and after streaming to reject changes during processing.

Blank/no nonblank header, value-looking first records, wrong-width rows, malformed
quoting, invalid UTF-8, and header-only files have separate outcomes below. Text-only
headerless data cannot reliably be distinguished from column names: a real header
is required. All-numeric/date-only headers are unsupported. A blank record inside
data is a malformed row. Individual blank/duplicate names remain positional
columns with warnings; consumers must join by one-based `ordinal`, not name.

Data is iterated one logical record at a time. Limits are 4,096 columns and
1 MiB characters per field. Each column retains at most `--distinct-limit` hashes
(default 10,000; range 1–1,000,000) and `--sample-limit` examples (default 0; maximum
100). Memory scales with retained hashes, columns and generated artifacts across
files, rather than input rows. The synchronous CSV adapter restores the process's
CSV field limit on exit. Future input formats may implement `SourceAdapter.profile`
without changing study resolution or output publication.

## Privacy and missingness

Examples are **suppressed by default**. `--sample-limit N` explicitly opts in to
the first N distinct nonmissing raw strings per column, in source order, omitting
values longer than 128 characters. This is not anonymization: opted-in reports
may contain sensitive identifiers/values. No complete subject rows are emitted.
Normal logs contain only filenames/paths, counts, structural diagnostics and
error codes. The CLI console summary serves as the execution log; no additional
disk log is written. Aggregates in very small datasets can still describe an
individual, so generated artifacts require the same governance as source data.

Missingness is the sum of three disjoint categories: `empty`, `whitespace`, and
explicitly configured `sentinel`. Sentinel classification compares stripped,
case-folded strings but never changes source strings. **No sentinel is missing
by default**, including `NA`, `N/A`, `NULL`, and `Unknown`. Configure each token
with repeatable `--missing-sentinel TOKEN`. Non-null plus missing count equals
row count. Percentages are 0–100, rounded to six decimal places; zero-row inputs
have null percentages. Settings are saved in metadata, profile and summary.

Distinct counts cover all original raw strings, including missing ones: `""`
and `" "` are distinct. SHA-256 sets give exact counts subject to cryptographic
collision assumptions, labeled `exact_sha256_set`. After the retained-set limit
is exceeded, `distinct_count` becomes null, `distinct_lower_bound` is limit + 1,
and the method is `capped_sha256_set`. No partial count is presented as exact.
Length min/max/mean describe nonmissing raw strings; all-missing columns return
null length statistics. Arbitrary value-frequency tables are deliberately omitted
to avoid exposing all distinct clinical strings.

## Logical types and dates

`inferred_type` is string, integer, decimal, boolean, date, datetime or unknown.
`type_evidence.representation_counts` provides observed syntax counts.
Integer/decimal mixtures infer decimal. Boolean text is case-insensitive
true/false/yes/no; 0/1 remain integers. Identifier header tokens `id`/`identifier`
(including camel case) and integer strings with leading zeros retain type string
and suppress numeric statistics. This is a generic representation safeguard, not
clinical field classification. `normalized_key` applies NFKC/case/punctuation/
camel-case normalization for future nonclinical use only; it never renames fields.

`type_status` is consistent, mixed, identifier_like or no_observations, with a
separate `mixed_type` boolean. Identifier-like mixed columns retain string and
still flag conflicting observations. All-missing columns infer unknown. Numeric
min/max are strings using Decimal syntax, avoiding binary-float precision loss;
count and negative/zero/positive bins describe successfully parsed numeric
observations even in a mixed column. `numeric.failure_count` reports syntactically
numeric values beyond Decimal's supported range. No numeric normal ranges,
clinical roles, unit vocabularies or conversions are inferred. Embedded values
such as `70 bpm` remain strings.

Recognized date formats are `YYYY-MM-DD`, English `DD-Mon-YYYY`, slash dates and
ISO 8601 datetime text with T/space separator and optional offset. Calendar
validity is checked. `03/04/2026` records both `MM/DD/YYYY` and `DD/MM/YYYY`, one
success and one ambiguous observation, without choosing a locale. Other rows do
not resolve that ambiguity automatically. Format counts may exceed successes.
`dates` includes formats/counts, ambiguous_locale, mixed_formats, status, success,
failure, ambiguous and invalid-calendar counts. Failure count covers nonmissing
non-date values in columns with date/time header tokens or any temporal evidence;
otherwise date status is not_observed and failures are zero. Arbitrary date
grammars, locale/timezone normalization and clinical chronology are not supported.

Warnings include duplicate_header, blank_header, header_only, all_missing,
mixed_types, ambiguous_date_locale, mixed_date_formats, invalid_date,
unrecognized_date_values, surrounding_whitespace and numeric_range_unavailable.
These are descriptive anomalies, not standards compliance errors.

## Artifact schema and downstream consumption

The [draft 2020-12 JSON Schema](schemas/source-profile.schema.json) validates
both JSON and safely loaded YAML. Complete [synthetic examples](examples/profiling/)
are generated by the implementation and validated by tests. Schema 1.0 uses
required keys, explicit nulls/unknown statuses and finite JSON numbers. The sdist
includes documentation/schema; the wheel contains the runtime package.

| Artifact under `cdash/metadata/` | Content |
| --- | --- |
| `<stem>.metadata.yaml` | Study/source identity, provenance, settings, original field order/names, inferred type/evidence, dates, missing counts, warnings |
| `<stem>.profile.json` | Same identity/settings, detailed missingness/distinct/length/numeric distributions, date statistics and optional examples |
| `profiling_summary.json` | Invocation scope, ordered file outcomes, relative artifact paths, processed/discovered totals, row/column totals, warning/error counts |
| `.profiling-manifest.json` | Tool/schema identifier and exact-byte hashes of generated reports, protecting human edits |

Report envelopes contain schema_version, document_kind, study_id and generated_by
(tool, installed package version and algorithm version). Per-file `source`
includes filename, workspace_relative_path, study_relative_path, sha256,
row_count, column_count, parse_status, encoding and delimiter. Consumers can read
these files directly, join columns by ordinal, and check checksums before later
Part 4 interpretation. No reference-version, target-field, score or mapping keys
are emitted.

Summary `row_count` and `column_count` sum successfully profiled files; columns
are summed per file, not deduplicated across datasets. `files_processed` includes
header-only observations. `error_count` counts failed files, and warning_count
sums per-column warning codes. Null per-file counts, errors with code/message,
and empty outputs mean that source failed this invocation. Input errors do not
prevent other valid sources from finishing.

Summary scope is this invocation: all_direct_csv_files or selected_file.
`--input` does not incorporate previous coverage. Reports for unselected, deleted,
or failed inputs remain on disk and may be stale; they are not listed as current
outputs. Check source hashes and the current summary before downstream use.
Global study/configuration/discovery errors produce no new reports.

## Safe reruns and recovery

Unedited generated artifacts regenerate automatically. Any colliding unmanaged
filename, or a generated file whose current bytes differ from its recorded hash,
causes an error before report changes. Preserve/move manually maintained files
before retrying. There is no force flag. Keep the ownership manifest with its
reports; deleting it makes existing files unmanaged. Unrelated metadata is
preserved. Identical reruns preserve bytes and modification times, with no
runtime timestamps or absolute machine paths in stable artifacts.

An exclusive `.profiling.lock` inside metadata coordinates cooperating writers.
New reports are staged and flushed inside metadata; each file is atomically
installed by rename, with the manifest last. A caught installation failure rolls
back the batch, including Ctrl+C. Readers can see mixed generations during a
successful batch installation and should coordinate with the lock/manifest.
Process kill, power loss and hostile external filesystem changes are outside
the guarantee. Rollback failure retains named backups in
`.profiling-stage-*/previous/` and reports their location. Ensure no writer is
active, preserve/review staged backups and file hashes, restore reports with a
matching manifest, then remove stale transaction/lock entries. Windows locked
temporary-file cleanup is best effort.

## Outcomes

Success including warnings/header-only input exits 0. Failed inputs or fatal
study/discovery/publication errors exit 1, invalid CLI syntax exits 2, and Ctrl+C
exits 130. Error codes include empty_csv, headerless_csv, malformed_row,
invalid_csv, invalid_encoding, column_limit, source_changed, source_unreadable,
workspace_not_found, study_config, empty_input_directory, invalid_input_path,
missing_input, unsafe_filename, output_name_collision, invalid_limits,
invalid_sentinel, user_artifact_collision, ownership_manifest,
publication_locked, report_changed, rollback_failed and unsafe_output_path.
Existing study/path errors use study_path_error in CLI diagnostics.

Profiling success establishes no clinical mapping, clinical validation,
regulatory compliance or certification.
