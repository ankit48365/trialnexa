"""Install local distributions and exercise their CLI outside the source tree.

Run with: uv run --locked python scripts/smoke_distribution.py <wheel> [<sdist>]
Build first with uv build. The populated uv build cache permits offline installs.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path


def check_distribution(artifact: Path) -> None:
    """Smoke-test one distribution in an isolated environment and workspace."""
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv must be available on PATH")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("VIRTUAL_ENV", None)

    with tempfile.TemporaryDirectory(prefix="trialnexa-smoke-") as directory:
        temporary = Path(directory)
        venv = temporary / "venv"
        workspace = temporary / "workspace with spaces"
        workspace.mkdir()
        subprocess.run(
            [uv, "venv", "--python", sys.executable, str(venv)],
            cwd=temporary,
            env=environment,
            check=True,
        )
        binary_dir = venv / ("Scripts" if os.name == "nt" else "bin")
        python = binary_dir / ("python.exe" if os.name == "nt" else "python")
        executable = binary_dir / ("trialnexa.exe" if os.name == "nt" else "trialnexa")
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--python",
                str(python),
                str(artifact),
            ],
            cwd=temporary,
            env=environment,
            check=True,
        )
        installed_version = subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "from importlib.metadata import version; print(version('trialnexa'))",
            ],
            cwd=workspace,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert installed_version == version("trialnexa"), installed_version

        def run(*arguments: str, answer: str = "") -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [str(executable), *arguments],
                input=answer,
                cwd=workspace,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )

        assert "init" in run("--help").stdout
        for answer in ("\n", "NO\n", "", "invalid\nno\n"):
            result = run("init", answer=answer)
            assert "cancelled" in result.stdout, result
            assert str(workspace.resolve()) in result.stdout, result
            assert list(workspace.iterdir()) == []

        result = run("init", answer="YeS\n")
        assert "Workspace initialized:" in result.stdout, result
        paths = set(workspace.rglob("*"))
        assert len(paths) == 16, paths
        assert all(path.is_dir() for path in paths), paths
        existing = workspace / "cdisc_reference" / "study_profiles" / "keep.txt"
        existing.write_text("preserve", encoding="utf-8")
        run("init", answer="y\n")
        assert set(workspace.rglob("*")) == paths | {existing}
        assert existing.read_text(encoding="utf-8") == "preserve"
        print(f"PASS: {artifact.name} installed CLI, consent, empty tree, repeat init")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    arguments = parser.parse_args()
    for artifact in arguments.artifacts:
        check_distribution(artifact.resolve(strict=True))


if __name__ == "__main__":
    main()
