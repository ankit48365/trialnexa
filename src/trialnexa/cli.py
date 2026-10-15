"""Command-line presentation and explicit workspace consent."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

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
        prog="trialnexa", description="Set up a TrialNexa workspace."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "init",
        help="Create empty CDISC reference directories in the current directory.",
    )
    parser.parse_args(argv)
    return _init()
