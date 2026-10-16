"""Command-line presentation and explicit workspace consent."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from trialnexa.reference import ReferenceError
from trialnexa.reference.service import import_cdash
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its process exit code."""
    parser = argparse.ArgumentParser(
        prog="trialnexa", description="Set up workspaces and import reference metadata."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "init",
        help="Create empty CDISC reference directories in the current directory.",
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
    arguments = parser.parse_args(argv)
    if arguments.command == "init":
        return _init()
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
