"""Tests for configuration and pipeline coordination."""

import json
from unittest.mock import patch

import pytest
import requests

from src.config import ConfigurationError, _load_player
from src.local_storage import games, metadata
from src.pipeline import process_month, run_pipeline


def test_missing_player_raises_configuration_error(monkeypatch):
    monkeypatch.delenv("PLAYER", raising=False)
    monkeypatch.setattr(
        "src.config.load_dotenv", lambda *args, **kwargs: None
    )
    with pytest.raises(ConfigurationError, match="PLAYER environment variable is required"):
        _load_player()


def test_blank_player_raises_configuration_error(monkeypatch):
    monkeypatch.setenv("PLAYER", "   ")
    monkeypatch.setattr(
        "src.config.load_dotenv", lambda *args, **kwargs: None
    )
    with pytest.raises(ConfigurationError, match="PLAYER environment variable is required"):
        _load_player()


def test_completed_historical_month_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(games, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(games, "PGN_DIR", tmp_path / "data" / "pgns")
    monkeypatch.setattr(games, "CSV_DIR", tmp_path / "data" / "csv")
    monkeypatch.setattr(metadata, "METADATA_DIR", tmp_path / "data" / "metadata")

    archive_url = "https://api.chess.com/pub/player/test/games/2020/01"
    month_data = metadata.create_month_metadata("test", 2020, 1, archive_url)
    month_data["is_complete"] = True
    metadata.save_month_metadata(month_data)

    with patch("src.pipeline.client.get_monthly_games") as mock_games:
        result = process_month(archive_url, 2026, 8, "test")
        mock_games.assert_not_called()

    assert result["skipped_month"] == 1


def test_current_month_remains_updateable(tmp_path, monkeypatch):
    monkeypatch.setattr(games, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(games, "PGN_DIR", tmp_path / "data" / "pgns")
    monkeypatch.setattr(games, "CSV_DIR", tmp_path / "data" / "csv")
    monkeypatch.setattr(metadata, "METADATA_DIR", tmp_path / "data" / "metadata")
    games.ensure_data_directories()

    archive_url = "https://api.chess.com/pub/player/test/games/2026/08"
    sample_game = {
        "uuid": "new-game-uuid",
        "pgn": '[White "a"]\n\n1. e4 1-0',
    }

    with patch(
        "src.pipeline.client.get_monthly_games", return_value=[sample_game]
    ):
        result = process_month(archive_url, 2026, 8, "test")

    assert result["skipped_month"] == 0
    saved = metadata.load_month_metadata(2026, 8)
    assert saved["is_complete"] is False
    assert "new-game-uuid" in saved["processed_game_uuids"]


def test_existing_uuid_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(games, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(games, "PGN_DIR", tmp_path / "data" / "pgns")
    monkeypatch.setattr(games, "CSV_DIR", tmp_path / "data" / "csv")
    monkeypatch.setattr(metadata, "METADATA_DIR", tmp_path / "data" / "metadata")

    archive_url = "https://api.chess.com/pub/player/test/games/2026/07"
    month_data = metadata.create_month_metadata("test", 2026, 7, archive_url)
    metadata.record_processed_game(month_data, "existing-uuid")
    metadata.save_month_metadata(month_data)

    sample_game = {
        "uuid": "existing-uuid",
        "pgn": '[White "a"]\n\n1. e4 1-0',
    }

    with patch(
        "src.pipeline.client.get_monthly_games", return_value=[sample_game]
    ):
        result = process_month(archive_url, 2026, 8, "test")

    assert result["skipped_games"] == 1
    assert result["failed"] == 0


def test_api_requests_include_required_headers():
    from src.chess_com.client import _create_session

    session = _create_session()
    assert session.headers["User-Agent"] == "Tool"


def test_run_pipeline_integration(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config._PLAYER", "testplayer")
    monkeypatch.setattr(games, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(games, "PGN_DIR", tmp_path / "data" / "pgns")
    monkeypatch.setattr(games, "CSV_DIR", tmp_path / "data" / "csv")
    monkeypatch.setattr(metadata, "METADATA_DIR", tmp_path / "data" / "metadata")

    archives = ["https://api.chess.com/pub/player/test/games/2026/08"]
    sample_game = {
        "uuid": "pipeline-game",
        "pgn": '[White "w"]\n\n1. e4 1-0',
    }

    with patch("src.pipeline.client.get_archive_urls", return_value=archives):
        with patch(
            "src.pipeline.client.get_monthly_games", return_value=[sample_game]
        ):
            totals = run_pipeline()

    assert totals["games_processed"] == 1
    assert (tmp_path / "data" / "pgns" / "2026-08-pipeline-game.pgn").is_file()
