# AGENTS.md — Trialnexa

## Purpose and scope
Trialnexa is a Python command-line project for metadata-driven clinical trial data processing. Planned capabilities include CRF ingestion and profiling, standards-aware mapping and transformation (CDASH, SDTM, ADaM), Define-XML generation, validation, and optional AI-assisted mapping. These are roadmap goals, not claims of existing functionality.

This file governs agent contributions throughout this repository. Favor maintainable, testable, reproducible code suitable for distribution on PyPI. Do not introduce a feature until the requested issue or task calls for it.

## Inspect before changing
- Read README.md, pyproject.toml (when present), the source tree, tests, existing workflows, and the linked issue before editing.
- The repository may initially be a skeleton; do not assume source modules, commands, or CI exist.
- Make focused changes within the task scope. Explain architectural or dependency trade-offs in the PR.
- Never overwrite unrelated work or change release/publication settings without explicit authorization.

## Python packaging and layout
- The intended PyPI distribution name and CLI command are `trialnexa`; confirm the distribution name is available before an initial publication.
- Use a standards-compliant `pyproject.toml` (PEP 517/518/621), with an explicitly configured build backend supported by `uv build`. Prefer Hatchling for a new scaffold unless the project already uses another backend.
- Prefer a `src/` layout: `src/trialnexa/` for importable code and `tests/` for tests. Put CLI entry points under `[project.scripts]`.
- Keep the package importable without running commands, making network requests, or initializing heavy optional dependencies.
- Define `requires-python` and supported Python versions explicitly. Do not invent package metadata such as author email, homepage, license, or published version; verify against repository metadata.
- Store the version in one authoritative place; keep Python package version, Git tags, and published distribution version consistent. Follow semantic versioning as a policy, with deliberate assessment of pre-1.0 compatibility.

## uv is the required workflow
- Use `uv` for virtual environments, dependency resolution, installation, tool execution, builds, and package publishing. Do not add Poetry, Pipenv, or a parallel lockfile.
- Scaffold only when needed: `uv init --package` may be useful for a new project, but preserve existing files and inspect changes before committing.
- Add runtime dependencies with `uv add <package>` and development dependencies with `uv add --dev <package>` (or named groups if established by the project).
- Use `uv sync --locked` for reproducible setup; when changing dependencies, update and commit both `pyproject.toml` and `uv.lock`.
- Run commands through `uv run` wherever practical. Prefer `uv run --locked` in CI.
- Use `uv build` to create wheel and sdist in `dist/`, and `uv publish` only in an explicitly approved release job.
- Do not commit `.venv/`, `dist/`, `build/`, credentials, tokens, or other generated artifacts. Commit `uv.lock` for this application/CLI repository.

## CLI and application design
- Provide a predictable `trialnexa` CLI through a declared console-script entry point when the CLI is implemented.
- Use clean separation between CLI parsing, application services, metadata, adapters, transformations, and validation.
- Prefer deterministic, configuration-driven operations over source-specific hardcoding. Handle arbitrary supported input schemas while reporting unmapped/ambiguous fields instead of guessing.
- Make transformations auditable, with structured errors, reproducible results, explicit standards/terminology versions, and input-to-output lineage.
- Keep AI/LLM/MCP integrations optional and behind well-defined interfaces. AI suggestions must be distinguishable from verified deterministic mappings, with review/approval where clinically significant.
- Do not claim regulatory compliance or validation certification merely because code passes unit tests.

## Quality gates
- Use `pytest` for automated tests and `ruff` for linting and formatting once development dependencies are configured.
- Before completing an implementation task, run the applicable equivalent of:
  - `uv sync --locked`
  - `uv run --locked ruff check .`
  - `uv run --locked ruff format --check .`
  - `uv run --locked pytest`
  - `uv build`
- If the repository is not yet scaffolded or a check cannot run, state precisely why; do not report success for an unexecuted check.
- Test CLI behavior, invalid input, boundary cases, configuration resolution, and packaging/installation where relevant. Use synthetic or de-identified clinical data only.
- Add type annotations to public interfaces and document non-obvious design decisions. Introduce static type checking when configured by an implementation task.
- Keep each PR narrow, with tests and documentation for behavior changes.

## GitHub and agent workflow
- Use issues as implementation specifications: identify scope, dependencies, acceptance criteria, and out-of-scope work before coding.
- Work in a feature branch and open a pull request linked to its issue. Summarize changes, verification commands/results, unresolved risks, and breaking changes.
- Do not merge to the default branch, create releases, publish to PyPI, change repository protections, or configure credentials without explicit human approval.
- Do not force-push over others' work, and do not silently alter public APIs or CLI behavior.
- For uncertain clinical semantics or ambiguous mappings, ask for clarification or surface reviewable choices rather than fabricating standards rules.

## CI and releases
- Introduce GitHub Actions CI when requested: on pull requests/pushes, install uv and supported Python, sync locked dependencies, lint, test, and build wheel/sdist. Validate that installed distributions and the console script work.
- Prefer a protected, manually approved release workflow using PyPI Trusted Publishing (GitHub OIDC) and a dedicated environment; grant minimal workflow permissions. Never commit PyPI tokens or use long-lived publish secrets when Trusted Publishing is available.
- Treat version bumps, changelog/release notes, tags, and distribution metadata as part of a release. Ensure the version has not been published already.
- Before any approved release, run `uv build`, check package contents and metadata, and run `uv publish --check-url https://pypi.org/simple/` only when the release procedure warrants it. Actually publish only after explicit authorization.
- PyPI package names are globally shared and uploads are immutable for a given release/version; verify the intended distribution ownership and version before publication.

## Documentation and security
- Maintain README.md with supported installation and CLI examples, configuration requirements, current limitations, and developer setup once implemented.
- Record provenance/version of clinical standards and controlled terminology; do not embed licensed standards resources without appropriate rights.
- Treat clinical inputs as potentially sensitive: avoid printing patient-level records or secrets in logs; do not send clinical data to external AI services unless explicitly authorized and compliant with applicable governance.
- Minimize dependencies and pin/lock resolved versions through uv. Review unexpected dependencies, network access, and security-sensitive workflow changes.
