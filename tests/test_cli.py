import pytest

from lyricmv import __version__, cli


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_every_command_has_help(capsys):
    for command in ("doctor", "demo", "make", "align", "subs", "render"):
        with pytest.raises(SystemExit) as done:
            cli.main([command, "--help"])
        assert done.value.code == 0


def test_missing_input_file(tmp_path, capsys):
    with pytest.raises(SystemExit) as done:
        cli.main(["subs", "--lines", str(tmp_path / "nope.json")])
    assert done.value.code == 2
    assert "not found" in capsys.readouterr().err
