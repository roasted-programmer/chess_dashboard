"""Tests for consolidated CSV and PGN storage."""

import csv

import pytest

from src.local_storage import games


@pytest.fixture
def storage_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(games, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(games, "PGN_DIR", tmp_path / "data" / "pgns")
    monkeypatch.setattr(games, "CSV_DIR", tmp_path / "data" / "csv")
    monkeypatch.setattr(games, "GAMES_CSV_PATH", tmp_path / "data" / "csv" / "games.csv")
    games.reset_csv_uuid_cache()
    games.ensure_data_directories()
    return tmp_path


def _sample_game(uuid: str = "game-1") -> dict[str, str]:
    return {
        "uuid": uuid,
        "white_username": "alice",
        "black_username": "bob",
        "result": "1-0",
        "variant": "",
        "eco_url": "",
        "utc_date": "2026.08.03",
        "utc_time": "12:00:00",
        "white_elo": "1500",
        "black_elo": "1500",
        "time_control": "600",
        "termination": "alice won",
        "pgn": '[White "alice"]\n\n1. e4 1-0',
    }


def test_append_creates_csv_with_header(storage_dirs):
    games.append_game_csv(_sample_game(), 2026, 8)
    csv_path = storage_dirs / "data" / "csv" / "games.csv"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["uuid"] == "game-1"
    assert rows[0]["pgn_file"] == "data/pgns/2026-08-game-1.pgn"


def test_append_adds_new_rows(storage_dirs):
    games.append_game_csv(_sample_game("game-1"), 2026, 8)
    games.append_game_csv(_sample_game("game-2"), 2026, 8)
    csv_path = storage_dirs / "data" / "csv" / "games.csv"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {row["uuid"] for row in rows} == {"game-1", "game-2"}


def test_append_skips_duplicate_uuid(storage_dirs):
    games.append_game_csv(_sample_game("game-1"), 2026, 8)
    games.append_game_csv(_sample_game("game-1"), 2026, 8)
    csv_path = storage_dirs / "data" / "csv" / "games.csv"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
