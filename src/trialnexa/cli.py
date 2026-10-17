"""Command-line presentation and explicit workspace consent."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from trialnexa.profiling import ProfileError
from trialnexa.profiling.csv_source import ProfileOptions
from trialnexa.profiling.service import profile_study
from trialnexa.reference import ReferenceError
from trialnexa.reference.service import import_cdash
from trialnexa.study import StudyError
from trialnexa.study.service import initialize_study, list_studies
from trialnexa.study.validation import validate_study
from trialnexa.workspace import WorkspaceError, initialize_workspace


def _confirm() -> bool:
    while True:
        answer = input("Do you want to continue? [y/N]: ").strip().casefold()
        if answer in {"y", "yes"}:
            return True
        if answer in {"", "n", "no"}:
            return False
        print("Please answer y/yes or n/no (Enter means no).")


def _init() -> int:
    try:
        root = Path.cwd().resolve(strict=True)
        print(f"Current directory: {root}")
        print(
            "This directory will become the workspace root, "
            "containing cdisc_reference/."
        )
        if not _confirm():
            print("Initialization cancelled. No changes made.")
            return 0
        reference_root = initialize_workspace(root)
    except EOFError:
        print("\nInitialization cancelled: no confirmation received. No changes made.")
        return 0
    except KeyboardInterrupt:
        print("\nInitialization interrupted.", file=sys.stderr)
        return 130
    except (OSError, WorkspaceError) as exc:
        print(f"Unable to initialize workspace: {exc}", file=sys.stderr)
        return 1

    print(f"Workspace initialized: {reference_root}")
    return 0


def _study(arguments: argparse.Namespace) -> int:
    try:
        if arguments.study_command == "init":
            result = initialize_study(arguments.study_id, workspace=arguments.workspace)
            for warning in result.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
            print(f"Study initialized: {result.path}")
            print(f"Generated: {result.path / 'study.yaml'}")
        elif arguments.study_command == "list":
            studies = list_studies(workspace=arguments.workspace)
            print(
                "\n".join(studies)
                if studies
                else "No studies found. Use trialnexa study init ID."
            )
        else:
            validation = validate_study(
                arguments.study_id, workspace=arguments.workspace
            )
            for error in validation.errors:
                print(f"Error: {error}", file=sys.stderr)
            for warning in validation.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
            status = "failed" if validation.errors else "structurally valid"
            print(
                f"Study configuration {status}: {len(validation.errors)} error(s), "
                f"{len(validation.warnings)} warning(s). "
                "No clinical rules or checksum verification performed."
            )
            return 1 if validation.errors else 0
    except KeyboardInterrupt:
        print("\nStudy operation interrupted.", file=sys.stderr)
        return 130
    except (StudyError, WorkspaceError, OSError) as exc:
        print(f"Unable to {arguments.study_command} study: {exc}", file=sys.stderr)
        return 1
    return 0


def _profile(arguments: argparse.Namespace) -> int:
    try:
        result = profile_study(
            arguments.study,
            workspace=arguments.workspace,
            selected=arguments.input,
            options=ProfileOptions(
                sample_limit=arguments.sample_limit,
                distinct_limit=arguments.distinct_limit,
                missing_sentinels=tuple(arguments.missing_sentinel),
            ),
        )
    except KeyboardInterrupt:
        print("\nProfiling interrupted.", file=sys.stderr)
        return 130
    except (ProfileError, StudyError, OSError) as exc:
        code = exc.code if isinstance(exc, ProfileError) else "study_path_error"
        print(f"Unable to profile study [{code}]: {exc}", file=sys.stderr)
        return 1
    for filename, code, message in result.errors:
        print(f"Error: {filename!r}: {code}: {message}", file=sys.stderr)
    print(
        f"Profiled {result.processed} file(s); {result.warnings} warning(s); "
        f"{result.failures} failure(s). Reports: {result.destination}"
    )
    return 1 if result.failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its process exit code."""
    parser = argparse.ArgumentParser(
        prog="trialnexa",
        description="Manage workspaces, study configuration and offline references.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "init",
        help="Create empty CDISC reference directories in the current directory.",
    )
    cdash = subcommands.add_parser("cdash", help="Describe study source data.")
    cdash_commands = cdash.add_subparsers(dest="cdash_command", required=True)
    profiler = cdash_commands.add_parser(
        "profile",
        help="Profile existing study CSVs into source metadata.",
        description=(
            "Write source metadata YAML, statistical profile JSON and a summary "
            "under cdash/metadata/. No reference files are read. Examples are "
            "suppressed by default."
        ),
    )
    profiler.add_argument("--study", required=True, help="Existing study ID.")
    profiler.add_argument(
        "--workspace", type=Path, help="Explicit workspace containing studies/."
    )
    profiler.add_argument(
        "--input", help="One CSV filename directly under study cdash/data/."
    )
    profiler.add_argument(
        "--sample-limit",
        type=int,
        default=0,
        help=(
            "Opt in to 0–100 raw example strings per column (default: 0). "
            "Reports may contain sensitive values when enabled."
        ),
    )
    profiler.add_argument(
        "--distinct-limit",
        type=int,
        default=10000,
        help=(
            "Retained distinct hashes per column, 1–1000000 (default: 10000); "
            "overflow yields an explicit lower bound."
        ),
    )
    profiler.add_argument(
        "--missing-sentinel",
        action="append",
        default=[],
        help=(
            "Treat this token as missing (stripped/case-insensitive); repeat. "
            "Default: no sentinels, including Unknown."
        ),
    )
    reference = subcommands.add_parser(
        "reference", help="Manage offline reference metadata."
    )
    reference_commands = reference.add_subparsers(
        dest="reference_command", required=True
    )
    importer = reference_commands.add_parser(
        "import", help="Import a user-provided CDASHIG CSV."
    )
    importer.add_argument("--domain", required=True, choices=["cdash"])
    importer.add_argument("--version", required=True, choices=["2.3"])
    importer.add_argument("--source", required=True, type=Path)
    importer.add_argument(
        "--workspace", type=Path, help="Explicit existing workspace root."
    )
    importer.add_argument(
        "--force", action="store_true", help="Replace different reference files."
    )
    study = subcommands.add_parser(
        "study", help="Manage studies in an initialized workspace."
    )
    study_commands = study.add_subparsers(dest="study_command", required=True)
    for name, help_text in (
        ("init", "Create a new study directory tree and study.yaml."),
        ("list", "List studies in deterministic ID order."),
        (
            "validate",
            "Check study configuration and paths; no clinical data validation.",
        ),
    ):
        command = study_commands.add_parser(name, help=help_text, description=help_text)
        if name != "list":
            command.add_argument(
                "study_id",
                help="1–64 ASCII letters/digits/'_'/'-'; start with a letter/digit.",
            )
        command.add_argument(
            "--workspace", type=Path, help="Explicit initialized workspace root."
        )
    arguments = parser.parse_args(argv)
    if arguments.command == "init":
        return _init()
    if arguments.command == "study":
        return _study(arguments)
    if arguments.command == "cdash":
        return _profile(arguments)
    try:
        result = import_cdash(
            arguments.source, workspace=arguments.workspace, force=arguments.force
        )
    except KeyboardInterrupt:
        print("\nReference import interrupted.", file=sys.stderr)
        return 130
    except (ReferenceError, WorkspaceError, OSError) as exc:
        print(f"Unable to import reference: {exc}", file=sys.stderr)
        return 1
    print(f"Processed {result.rows} rows; {result.domains} distinct domains.")
    for path in result.paths:
        print(f"Generated: {path}")
    return 0
