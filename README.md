# TrialNexa

TrialNexa is a Python CLI for setting up workspaces, managing study configuration,
and importing offline CDASH reference metadata for future clinical trial data
processing. `init` creates an
**empty CDISC reference directory hierarchy** after explicit confirmation.
`reference import` converts a user-supplied CDASHIG 2.3 CSV into three JSON files.
`study init`, `study list`, and `study validate` manage independently named studies.
The package does not include or download licensed CDISC content.

Python 3.12 or newer is required. Supported Python versions are 3.12, 3.13, and
3.14 on Windows, macOS, and Linux.

## Local developer installation

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```console
git clone https://github.com/ankit48365/trialnexa.git
cd trialnexa
uv sync --locked
uv run --locked trialnexa --help
```

`uv sync --locked` installs the project in editable mode and the development
tools specified in `uv.lock`. Use `uv add` for dependency changes and commit the
updated `pyproject.toml` and `uv.lock` together. PyYAML is the only runtime dependency,
used to serialize and safely parse editable study configuration.

## Build and install locally

```console
uv build
uv venv .venv-installed
uv pip install --python .venv-installed dist/trialnexa-0.0.0.dev2-py3-none-any.whl
```

Run the installed command directly, including from a directory outside the
repository. On macOS/Linux:

```console
.venv-installed/bin/trialnexa --help
```

On Windows PowerShell:

```powershell
.\.venv-installed\Scripts\trialnexa.exe --help
```

The source distribution in `dist/` can also be installed with `uv pip install`
using the same `--python` argument. The version `0.0.0.dev2` is an unpublished
development version, defined only in `pyproject.toml`. Installed code can read it
with `importlib.metadata.version("trialnexa")`.

To install or update the built wheel as a dependency in a separate uv project,
run from that project's directory (replace the example absolute path):

```console
uv add /absolute/path/to/trialnexa/dist/trialnexa-0.0.0.dev2-py3-none-any.whl
uv run trialnexa --help
uv run trialnexa init
```

Increment the development version before distributing changed local builds.
uv locks the wheel's hash; replacing an already locked wheel with different
contents under the same filename causes a hash mismatch, even with `--reinstall`.
Add the new version's wheel path to update the dependency and lockfile together.

**Public-index installation is pending a separately approved PyPI release.**
Only after that release has been approved and published will users be able to
install this project from the public index with:

```console
pip install trialnexa
```

Local builds and verification do not publish anything. Release versions follow
semantic versioning; pre-1.0 compatibility changes must be assessed deliberately.

## Initialize a workspace

Change to the directory you want to use as your workspace and run the installed
`trialnexa` command (activate its environment or use its absolute executable path):

```console
trialnexa --help
trialnexa init
```

Init displays the resolved absolute current directory and explains that it will
become the workspace root, containing `cdisc_reference/`. It then asks:

```text
Do you want to continue? [y/N]:
```

- `y` or `yes`, case-insensitive, approves creation. Surrounding spaces are ignored.
- `n`, `no`, or Enter cancels with no filesystem changes. **No is the default.**
- Invalid answers prompt again without making changes.
- End-of-input cancels without changes; Ctrl+C interrupts without a traceback.

After approval, the following directories are created, with **no files**:

```text
<current-working-directory>/
└── cdisc_reference/
    ├── cdash/
    │   ├── imports/
    │   └── v2.3/
    ├── sdtm/
    │   └── sdtmig_v3.4/
    ├── adam/
    │   └── adamig_v1.3/
    ├── controlled_terminology/
    ├── define_xml/
    │   ├── v2.0/
    │   └── v2.1/
    │       └── schemas/
    ├── validation_rules/
    │   ├── cdisc_core/
    │   └── custom/
    └── study_profiles/
```

No terminology release version is assumed; `controlled_terminology/` remains
empty. No JSON, YAML, catalogs, manifests, or placeholder files are generated.
`cdash/imports/` is an empty location for separately supplied source files, such
as `CDASHIG_v2.3.csv`. Init does not create that CSV or generate `domains.json`,
`variables.json`, `mappings_to_sdtm.json`, or `manifest.json` in `cdash/v2.3/`.

Every invocation asks for confirmation, including repeat runs. Running init
again in the same workspace fills in missing directories, preserves existing
content and unrelated files, and does not create a second nested hierarchy.
Always invoke it from the intended workspace root.

Required paths occupied by files or symbolic links are reported before directory
creation starts. Permission and other filesystem failures return a clear error
and exit code 1. A failure during creation can leave a partial directory tree;
resolve the cause and run init again to complete it. Existing content is never
deleted or overwritten. Success is reported only after all directories exist.
Explicit cancellation and end-of-input exit with code 0; Ctrl+C exits with 130;
invalid command syntax exits with 2.

## Import CDASHIG reference metadata

Supply your own authorized UTF-8 CDASHIG v2.3 CSV, then run from the workspace root:

```console
trialnexa reference import --domain cdash --version 2.3 --source cdisc_reference/cdash/imports/CDASHIG_v2.3.csv
```

This writes `domains.json`, `variables.json`, and `mappings_to_sdtm.json` under
`cdisc_reference/cdash/v2.3/`. It retains every source row, blank SDTM targets,
and mapping instructions as source text. It never executes mappings or creates
a manifest. No network, API keys, or study configuration are needed.

Relative source paths resolve from the current directory. The output root is the
nearest ancestor with `cdisc_reference/`, otherwise the nearest Git checkout.
Use `--workspace ROOT` to select an existing root explicitly. Without a marker or
an explicit workspace, run `trialnexa init` at the intended root first. Running
inside an initialized workspace's study subdirectory still writes to the shared
reference root.

Identical reruns preserve existing files. Different files require `--force`;
unexpected destination entries and linked paths are rejected even with that flag.
Invalid input is rejected before output creation; staged publication restores
the previous snapshot if installation fails. See the [importer contract and JSON
schema](docs/cdash-reference.md) for validation rules, recovery limits, column
mapping, errors, and the optional full-source integration test.

## Manage studies

Run these commands in an initialized workspace or any of its subdirectories:

```console
trialnexa study init ABC-2026-01
trialnexa study init pilot_02
trialnexa study list
trialnexa study validate ABC-2026-01
```

Each `init` and `validate` command requires exactly one study ID. IDs contain
1–64 ASCII letters, digits, `_`, or `-`, starting with a letter or digit.
Windows device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`)
are reserved, case-insensitively. Dots, spaces, separators, drive paths, Unicode,
and traversal are rejected. IDs are supplied by the user; no study is hardcoded.
Use distinct IDs that also remain distinct on case-insensitive filesystems.

The nearest current/ancestor directory with a real `cdisc_reference/` directory
is the workspace root. A partial reference hierarchy is allowed; absent standard
groups are unconfigured. An invalid nearest marker is an error. Unlike reference
import, study commands require this initialized marker and do not fall back to a
Git checkout. Run `trialnexa init` at the intended root first. All three commands
also accept `--workspace ROOT` to select an initialized root explicitly.

Study initialization creates `studies/` if absent, then this exact layout:

```text
<workspace>/
├── cdisc_reference/                 # existing, shared, unchanged
└── studies/
    └── ABC-2026-01/                 # user-provided ID
        ├── study.yaml
        ├── raw/
        │   ├── crf/
        │   └── external/
        ├── cdash/
        │   ├── data/
        │   └── metadata/
        ├── sdtm/
        │   ├── data/
        │   └── metadata/
        ├── adam/
        │   ├── data/
        │   └── metadata/
        ├── mappings/
        │   ├── crf_to_cdash/
        │   ├── cdash_to_sdtm/
        │   └── sdtm_to_adam/
        ├── outputs/
        │   ├── define_xml/
        │   ├── validation/
        │   ├── reports/
        │   └── submission/
        └── logs/
```

No clinical records, mapping files, reports, placeholder metadata, or `.gitkeep`
files are generated. An existing study path causes an error with guidance to run
`study validate`; its YAML and data are preserved. There is no overwrite flag.

The generated YAML has this schema. This example assumes exactly the shown
single version directories exist; versions are discovered, never defaults:

```yaml
study_id: ABC-2026-01
standards:
  cdash: "2.3"
  sdtmig: "3.4"
  adamig: "1.3"
  define_xml: "2.1"
  controlled_terminology: ""
paths:
  raw:
    crf: "./raw/crf"
    external: "./raw/external"
  cdash:
    data: "./cdash/data"
    metadata: "./cdash/metadata"
  sdtm:
    data: "./sdtm/data"
    metadata: "./sdtm/metadata"
  adam:
    data: "./adam/data"
    metadata: "./adam/metadata"
  mappings:
    crf_to_cdash: "./mappings/crf_to_cdash"
    cdash_to_sdtm: "./mappings/cdash_to_sdtm"
    sdtm_to_adam: "./mappings/sdtm_to_adam"
  outputs:
    define_xml: "./outputs/define_xml"
    validation: "./outputs/validation"
    reports: "./outputs/reports"
    submission: "./outputs/submission"
validation:
  offline: true
  rule_engine: cdisc_core
  custom_rules: true
reference:
  root: "../../cdisc_reference"
  verify_checksums: true
```

YAML quoting may differ, but versions and IDs remain strings, empty versions
remain empty strings, and the three boolean settings remain booleans. All paths
are relative to the **parent of `study.yaml`**, independent of the shell's current
directory. `logs/` is required even though it has no YAML path entry.

Version discovery scans only immediate directories using these conventions:

| YAML key | Directory below `cdisc_reference/` |
| --- | --- |
| `cdash` | `cdash/v<version>/` |
| `sdtmig` | `sdtm/sdtmig_v<version>/` |
| `adamig` | `adam/adamig_v<version>/` |
| `define_xml` | `define_xml/v<version>/` |
| `controlled_terminology` | `controlled_terminology/<release>/` |

Version/release names must be portable single components: 1–128 ASCII letters,
digits, `.`, `_`, or `-`, beginning with a letter/digit, without a trailing dot or
a Windows device basename. Files and unrelated version names are ignored; linked
candidate directories are rejected. Exactly one candidate sets the string.
No candidate leaves `""` and prints an unconfigured warning. Multiple candidates
also leave `""` and print **all available versions**, so the user can review and
edit the setting explicitly. This applies equally to terminology releases.

The original `trialnexa init` creates both Define-XML `v2.0/` and `v2.1/`, so a
fresh workspace leaves `define_xml` empty with an ambiguity warning. Its other
empty version directories are discoverable candidates. Directory existence
does not establish complete, approved, or verified reference metadata.

`study list` prints sorted IDs, one per line, for direct study directories with a
regular `study.yaml`. With no studies, it prints a helpful message without
creating `studies/`. Unrelated files and directories without YAML are ignored.
Listing does not parse YAML; use validation to inspect it. Unreadable directories,
linked entries, invalid study names with YAML, and non-file YAML entries are errors.

`study validate` checks the ID, required sections/keys and types, the prescribed
directory layout (including `logs/`), paths contained in the study, shared
reference root, and existence of each configured version. Path values must match
the expected layout, with an optional leading `./`; absolute paths, traversal,
symlinks, and Windows junctions are rejected. `reference.root` must point to
`../../cdisc_reference`. YAML must be a UTF-8 mapping, at most 1 MiB, with unique
string keys and no aliases or executable tags. Missing or malformed configuration,
collisions, missing directories, and missing configured versions are errors.

Empty versions produce **unconfigured warnings**. Existing configured versions
produce **not verified warnings** for reference completeness/content and checksums;
empty directories are identified explicitly. `verify_checksums: true` is a saved
configuration setting only. No manifest is required or generated. Validation
does not execute CDISC CORE, examine clinical datasets, transform data, verify
checksums, or establish regulatory compliance. Listing and validation never write
files; none of these commands access the network.

Creation stages the complete tree and YAML beside the destination, flushes the
YAML, then installs the directory by rename. Failed writes, directory creation,
or installation leave no partially initialized final study. A hidden per-study
lock coordinates TrialNexa writers. Process termination/power loss or concurrent
external filesystem changes are outside the transaction guarantee. If a process
is killed, inspect any `.ID.init-*` staging directory and `.ID.init.lock` under
`studies/` after ensuring no initialization is active. Cleanup of locked temporary
files on Windows is best effort. Existing study paths are never deliberately
replaced, and references are never modified.

Successful init/list and structurally valid configuration exit **0**, including
validation with warnings. Configuration/filesystem errors exit **1**; invalid CLI
syntax exits **2**; Ctrl+C exits **130**. Validation prints error/warning counts.

## Development checks

Run the repository's prescribed quality checks:

```console
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
uv run --locked python scripts/smoke_distribution.py dist/trialnexa-0.0.0.dev2-py3-none-any.whl dist/trialnexa-0.0.0.dev2.tar.gz
```

The smoke test installs each built distribution into a fresh temporary virtual
environment and runs its console script from a separate temporary workspace,
without `PYTHONPATH`. It checks help, default cancellation, consent, the empty
tree, repeat initialization, and CDASH import/rerun/error behavior using a small
synthetic CSV. It also checks installed study init/list/validate, unsafe IDs,
duplicate creation, and validation errors from a nested directory. Distribution
installation may fetch runtime/build dependencies; the tested CLI operations are
offline. `uv build` also builds the wheel from the sdist.
Automated tests use isolated temporary directories; filesystem errors are
simulated so those checks also run on systems with elevated permissions.
Symbolic-link tests skip if the host cannot create links.

## Current limitations

This scaffold does not ingest CRFs, transform CDASH/SDTM/ADaM data, generate
Define-XML, execute clinical data validation, manage terminology releases, or integrate AI/LLM/MCP
services. Those are roadmap capabilities. Creating this directory tree does not
provide regulatory compliance or validation certification.

Licensed standards and study content must be supplied separately under the
appropriate rights. CI, release automation, and publication are outside the
current implementation.

Licensed under the [MIT License](LICENSE).
