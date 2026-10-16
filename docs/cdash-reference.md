# Offline CDASHIG 2.3 reference import

```console
trialnexa reference import --domain cdash --version 2.3 --source cdisc_reference/cdash/imports/CDASHIG_v2.3.csv
```

All three options are required. Initially only `cdash` and `2.3` are supported.
Supply an authorized, user-downloaded CSV; TrialNexa does not download standards,
contact CDISC, require credentials, infer mappings, or execute mapping guidance.
Actual standards content and generated full-reference JSON are not bundled in
the package. The committed four-record fixture is wholly synthetic.

## Paths

`--source` accepts an absolute path or a path relative to the invocation's current
directory, independently of the output root. Path resolution lives in
`trialnexa.workspace.resolve_reference_paths`:

1. `--workspace ROOT`, if supplied, selects an existing directory explicitly.
   A relative workspace path also resolves from the current directory.
2. Otherwise, select the nearest current/ancestor directory containing
   `cdisc_reference/`, matching `trialnexa init`.
3. Otherwise, select the nearest current/ancestor Git checkout (`.git` file or
   directory). Without either marker, fail and request init or `--workspace`.

Run init from the intended shared root, never from an individual study. No study
directory or configuration is inspected. A command invoked in
`ROOT/studies/example/` finds the initialized `ROOT`, keeping references outside
studies. An explicitly selected workspace is trusted as the shared root.

```text
ROOT/cdisc_reference/cdash/
├── imports/CDASHIG_v2.3.csv        # user-provided source; never modified
└── v2.3/
    ├── domains.json
    ├── variables.json
    └── mappings_to_sdtm.json
```

No `manifest.json` is generated. The repository ignores `cdisc_reference/` to
avoid accidentally committing licensed sources or derived reference snapshots.
The wheel contains only code; the sdist includes synthetic tests and docs.

## CSV validation and text preservation

The UTF-8 CSV may have a UTF-8 BOM and reordered columns. All 18 headers listed
below must occur exactly once; missing, duplicate, and unexpected headers fail.
Empty files, header-only files, empty records, wrong-width records, broken quoted
fields, invalid UTF-8, and unreadable sources fail without replacing outputs.
Quoted commas, doubled quotes, Unicode, and embedded LF/CRLF are preserved.

Every `Version` must be `2.3` or the download's release label `CDASHIG v2.3`.
Both identify the same supported release; other standards or releases fail.
The original cell text is retained in each variable's `source_version`, while
the top-level `version` remains canonical `2.3`. Keep CLI `--version 2.3`;
`v2.3` is the output directory name, not a supported CLI argument.
Class, Domain, and CDASHIG Variable must be
nonblank, have no surrounding whitespace or ASCII control characters, and Domain
and CDASHIG Variable must contain no whitespace. These are structural checks,
not claims that names are verified against CDISC standards. Generic `--` variable
prefixes are allowed. A domain associated with different Class values fails;
different scenarios for the same domain are retained.

Variable Order must contain one or more ASCII digits (zero is allowed). It is
stored as a **string**, preserving leading zeros and arbitrarily large values.
Negative, decimal, empty, and nonnumeric orders fail explicitly. No source text
is trimmed or rewritten. Empty optional cells become JSON `null`; nonempty
whitespace-only optional text remains text. All errors identify the structural
problem and, where applicable, the logical source row without dumping records.

## Stable JSON schema version 1

Each file is a UTF-8 object with two-space indentation and a final LF:

```json
{
  "schema_version": 1,
  "standard": "CDASHIG",
  "version": "2.3",
  "variables": []
}
```

The record-array key is `domains`, `variables`, or `mappings`, respectively.
The empty array above illustrates the envelope only; valid imports require data.
Domains are sorted lexicographically by source domain text. Each domain record
has exactly `domain`, `class`, and `scenarios`: the sorted distinct nonempty
scenario strings. No scenario is inferred for blank cells.

Variables and mappings each contain **one object per CSV data record** in source
order, including duplicate rows and variable names. Both carry an integer
`source_row`, starting at 1 after the header. It counts logical CSV records, not
physical lines, so quoted multiline cells do not affect association. Join on
`source_row` within the same snapshot; IDs are not persistent across edited CSVs.

The following table defines every source field's exact JSON meaning. Optional
values are strings or `null`; required identifiers and Variable Order are strings.

| CSV header | JSON key | Location |
| --- | --- | --- |
| Version | `source_version` | Variables; exact source text. Each envelope has canonical `version: "2.3"` |
| Class | `class` | All record arrays |
| Domain | `domain` | All record arrays |
| Data Collection Scenario/Implementation Option | `scenario` | Variables and mappings; aggregated as `scenarios` in domains |
| Variable Order | `variable_order` | Variables |
| CDASHIG Variable | `cdashig_variable` | Variables and mappings |
| CDASHIG Variable Label | `cdashig_variable_label` | Variables |
| DRAFT CDASHIG Definition | `draft_cdashig_definition` | Variables; DRAFT remains explicit |
| Question Text | `question_text` | Variables |
| Prompt | `prompt` | Variables |
| Type | `type` | Variables |
| CDASHIG Core | `cdashig_core` | Variables |
| Case Report Form Completion Instructions | `crf_completion_instructions` | Variables |
| SDTMIG Target | `sdtmig_target` | Mappings, including `null` targets |
| Mapping Instructions | `mapping_instructions` | Mappings; unchanged source guidance |
| CDISC CT Codelist Code(s), Subset Codes(s) | `ct_codelist_codes` | Variables; unsplit source text |
| Codelist Submission Value | `codelist_submission_value` | Variables |
| Implementation Notes | `implementation_notes` | Variables and mappings |

Mapping records have exactly `source_row`, `domain`, `class`, `scenario`,
`cdashig_variable`, `sdtmig_target`, `mapping_instructions`, and
`implementation_notes`. Variable records contain `source_row` and every field
marked Variables above, including the original `source_version`. No records are
deduplicated. Conditional, derived, complicated, and non-submitted mapping
instructions remain text. Runtime validation checks exact keys, types, version,
record counts, contiguous source IDs, matching contexts, domain/scenario coverage,
lossless reconstruction of all 18 source cells, and JSON serialization.

## Replacement and recovery

An identical rerun succeeds without rewriting files. Missing files may be filled
when remaining files are identical. Different existing files require `--force`.
The flag authorizes replacing only the three expected files; unexpected entries,
files in directory positions, symlinks, and Windows junctions are rejected.

All parsing, normalization, and serialization finish before publication. A
same-filesystem sibling staging directory receives and flushes all three files.
An exclusive `.v2.3.import.lock` directory prevents cooperating imports from
overlapping. The existing directory is renamed to a backup, then the complete
stage is renamed into place. An installation failure, including Ctrl+C during
the rename, restores the old directory. Each installed directory contains a
complete generation, but portable replacement has a brief interval where `v2.3/`
is absent. Coordinate concurrent readers with the importer: separate file opens
that straddle replacement can read from different generations.

If the OS also blocks rollback, the error names the retained `previous/` backup
inside `.v2.3.import-*/`; restore that directory before retrying. Process kill or
power loss is not a transaction guarantee: inspect retained staging/backup
directories and restore the previous snapshot if necessary. After verifying no
import is running, remove any stale lock before retrying. Cleanup of locked
temporary directories is best effort; no reference file is updated individually.
Existing directory trees may be partially created on a parent-creation failure,
but a previously published snapshot is preserved.

Success prints row/domain counts and all three absolute generated paths and exits
0. Input, collision, filesystem, and publication failures exit 1; invalid CLI
arguments exit 2; Ctrl+C exits 130. Diagnostic output does not print source cells.

## Optional verification with an authorized full download

No full source CSV is present in this repository. To run the optional integration
test locally, set `TRIALNEXA_CDASH_CSV` to its absolute path, for example PowerShell:

```powershell
$env:TRIALNEXA_CDASH_CSV='C:\authorized\CDASHIG_v2.3.csv'
uv run --locked pytest tests/test_reference.py -k optional_full_download
```

For the issue's specific download, the test expects 1,253 variable records,
1,253 mapping records, 42 domains, 888 distinct variable names, and 1,060 populated
targets. These are integration expectations only; the importer has no hardcoded
row/domain counts. Tests write derived JSON only to temporary workspaces. Do not
commit or redistribute actual CDISC content without the appropriate rights.
