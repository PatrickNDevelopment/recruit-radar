"""The ``python -m recruit_radar`` entry point: configuration and start-up failures."""

from __future__ import annotations

from pathlib import Path

import pytest

from recruit_radar.main import build_settings, main


def test_command_line_options_override_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RECRUIT_RADAR_PORT", "9001")
    settings = build_settings(["--port", "9002", "--db-path", str(tmp_path / "x.sqlite3")])
    assert settings.port == 9002
    assert settings.db_path == (tmp_path / "x.sqlite3").resolve()


def test_a_bad_setting_is_one_line_and_exit_code_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RECRUIT_RADAR_ALLOWED_HOSTS", "*")
    assert main([]) == 2
    assert "configuration error" in capsys.readouterr().out


def test_a_file_that_is_not_a_database_is_reported_by_name_not_as_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    garbage = tmp_path / "garbage.sqlite3"
    garbage.write_bytes(b"this is not a sqlite database " * 20)
    monkeypatch.setenv("RECRUIT_RADAR_DB_PATH", str(garbage))
    assert main([]) == 2
    out = capsys.readouterr().out
    assert "cannot open the database" in out
    assert str(garbage) in out
    assert "not a database" in out


def test_a_database_path_that_cannot_be_created_is_reported_the_same_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("RECRUIT_RADAR_DB_PATH", str(blocker / "sub" / "db.sqlite3"))
    assert main([]) == 2
    assert "cannot open the database" in capsys.readouterr().out
