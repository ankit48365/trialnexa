# TrialNexa

TrialNexa is a Python CLI for setting up a workspace and importing offline CDASH
reference metadata for future clinical trial data processing. `init` creates an
**empty CDISC reference directory hierarchy** after explicit confirmation.
`reference import` converts a user-supplied CDASHIG 2.3 CSV into three JSON files.
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
updated `pyproject.toml` and `uv.lock` together. There are no runtime dependencies.

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
synthetic CSV. `uv build` also builds the wheel from the sdist.
Automated tests use isolated temporary directories; filesystem errors are
simulated so those checks also run on systems with elevated permissions.
Symbolic-link tests skip if the host cannot create links.

## Current limitations

This scaffold does not ingest CRFs, transform CDASH/SDTM/ADaM data, generate
Define-XML, validate studies, manage terminology releases, or integrate AI/LLM/MCP
services. Those are roadmap capabilities. Creating this directory tree does not
provide regulatory compliance or validation certification.

Licensed standards and study content must be supplied separately under the
appropriate rights. CI, release automation, and publication are outside the
current implementation.

Licensed under the [MIT License](LICENSE).
