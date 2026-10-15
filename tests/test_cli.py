from pathlib import Path

import pytest

from trialnexa import cli


@pytest.mark.parametrize("args", [["--help"], ["init", "--help"]])
def test_help_does_not_prompt_or_write(
    args: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as result:
        cli.main(args)
    assert result.value.code == 0
    assert "usage: trialnexa" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args", [[], ["unknown"], ["init", "--yes"]])
def test_invalid_command_is_safe(
    args: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as result:
        cli.main(args)
    assert result.value.code == 2
    assert "error:" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("answer", ["", "n", "no", "N", "NO", " No "])
def test_decline_preserves_workspace(
    answer: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "notes.txt"
    existing.write_text("keep", encoding="utf-8")

    def respond(prompt: str) -> str:
        assert prompt == "Do you want to continue? [y/N]: "
        assert list(tmp_path.iterdir()) == [existing]
        return answer

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(["init"]) == 0
    output = capsys.readouterr()
    assert str(tmp_path.resolve()) in output.out
    assert "workspace root" in output.out
    assert "cdisc_reference/" in output.out
    assert "cancelled" in output.out
    assert "initialized" not in output.out
    assert list(tmp_path.iterdir()) == [existing]
    assert existing.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("answer", ["y", "yes", "Y", "YES", " YeS "])
def test_consent_creates_exact_empty_tree(
    answer: str,
    tmp_path: Path,
    expected_directories: set[Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    def respond(prompt: str) -> str:
        assert list(tmp_path.iterdir()) == []
        output = capsys.readouterr().out
        assert str(tmp_path.resolve()) in output
        assert "workspace root" in output
        return answer

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(["init"]) == 0
    assert {
        p.relative_to(tmp_path) for p in tmp_path.rglob("*")
    } == expected_directories
    assert all(p.is_dir() for p in tmp_path.rglob("*"))
    assert "Workspace initialized:" in capsys.readouterr().out


@pytest.mark.parametrize("final_answer", ["yes", "no", ""])
def test_invalid_answers_reprompt_without_writes(
    final_answer: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    answers = iter(["maybe", "true", final_answer])

    def respond(prompt: str) -> str:
        assert list(tmp_path.iterdir()) == []
        return next(answers)

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(["init"]) == 0
    assert capsys.readouterr().out.count("Please answer") == 2
    assert (tmp_path / "cdisc_reference").exists() == (final_answer == "yes")


@pytest.mark.parametrize(
    "interrupt, expected_code", [(EOFError, 0), (KeyboardInterrupt, 130)]
)
def test_prompt_interrupt_is_safe(
    interrupt: type[BaseException],
    expected_code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    def respond(prompt: str) -> str:
        raise interrupt

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(["init"]) == expected_code
    output = capsys.readouterr()
    assert "cancelled" in output.out or "interrupted" in output.err
    assert "Workspace initialized:" not in output.out
    assert list(tmp_path.iterdir()) == []


def test_every_invocation_requires_consent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    answers = iter(["yes", "no", "yes"])
    prompts = []

    def respond(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(["init"]) == 0
    missing = tmp_path / "cdisc_reference" / "cdash" / "imports"
    missing.rmdir()
    assert cli.main(["init"]) == 0
    assert not missing.exists()
    assert cli.main(["init"]) == 0
    assert missing.is_dir()
    assert len(prompts) == 3


def test_collision_is_reported_without_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    collision = tmp_path / "cdisc_reference"
    collision.write_text("keep", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    assert cli.main(["init"]) == 1
    output = capsys.readouterr()
    assert str(collision) in output.err
    assert "non-directory" in output.err
    assert "Workspace initialized:" not in output.out
    assert collision.read_text(encoding="utf-8") == "keep"


def test_cwd_failure_is_reported_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unavailable_cwd() -> Path:
        raise FileNotFoundError("Current directory is unavailable")

    monkeypatch.setattr(Path, "cwd", unavailable_cwd)
    assert cli.main(["init"]) == 1
    output = capsys.readouterr()
    assert "Current directory is unavailable" in output.err
    assert "Workspace initialized:" not in output.out
