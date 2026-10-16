"""Install local distributions and exercise their CLI outside the source tree.

Run with: uv run --locked python scripts/smoke_distribution.py <wheel> [<sdist>]
Build first with uv build. The populated uv build cache permits offline installs.
"""

import argparse
import json
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
        assert len(paths) == 17, paths
        assert all(path.is_dir() for path in paths), paths
        imports = workspace / "cdisc_reference" / "cdash" / "imports"
        assert imports.is_dir()
        assert list(imports.iterdir()) == []
        existing = workspace / "cdisc_reference" / "study_profiles" / "keep.txt"
        existing.write_text("preserve", encoding="utf-8")
        run("init", answer="y\n")
        assert set(workspace.rglob("*")) == paths | {existing}
        assert existing.read_text(encoding="utf-8") == "preserve"
        source = imports / "synthetic.csv"
        fixture = (
            Path(__file__).resolve().parent.parent
            / "tests/fixtures/cdash_synthetic.csv"
        )
        source.write_bytes(fixture.read_bytes())
        arguments = (
            "reference",
            "import",
            "--domain",
            "cdash",
            "--version",
            "2.3",
            "--source",
            str(source.relative_to(workspace)),
        )
        result = run(*arguments)
        assert "Processed 4 rows; 2 distinct domains." in result.stdout, result
        destination = workspace / "cdisc_reference/cdash/v2.3"
        before = {p.name: p.read_bytes() for p in destination.iterdir()}
        assert set(before) == {
            "domains.json",
            "variables.json",
            "mappings_to_sdtm.json",
        }
        variables = json.loads(before["variables.json"])["variables"]
        mappings = json.loads(before["mappings_to_sdtm.json"])["mappings"]
        assert len(variables) == len(mappings) == 4
        assert len(json.loads(before["domains.json"])["domains"]) == 2
        assert mappings[1]["sdtmig_target"] is None
        assert variables[1]["variable_order"] == "002"
        assert variables[0]["source_version"] == "CDASHIG v2.3"
        assert variables[0]["question_text"].endswith("café 患者")
        run(*arguments)
        assert {p.name: p.read_bytes() for p in destination.iterdir()} == before
        # Installed CLI error behavior must preserve the previous snapshot.
        source.write_text("invalid headers\n", encoding="utf-8")
        invalid = subprocess.run(
            [str(executable), *arguments, "--force"],
            cwd=workspace,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert invalid.returncode == 1, invalid
        assert "Invalid CSV headers" in invalid.stderr, invalid
        assert {p.name: p.read_bytes() for p in destination.iterdir()} == before
        print(
            f"PASS: {artifact.name} installed CLI, consent, init, "
            "CDASH import and errors"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    arguments = parser.parse_args()
    for artifact in arguments.artifacts:
        check_distribution(artifact.resolve(strict=True))


if __name__ == "__main__":
    main()
