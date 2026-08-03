"""Tests for configuration and pipeline coordination."""

import csv
from unittest.mock import patch

import pytest

from src.config import ConfigurationError, _load_player
from src.local_storage import games, metadata
from src.pipeline import process_month, run_pipeline, select_archive_urls

SAMPLE_PGN_WITH_LINK = (
    '[White "w"]\n'
    '[Link "https://www.chess.com/game/live/1234567890"]\n\n'
    "1. e4 1-0"
)


def _patch_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(games, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(games, "PGN_DIR", tmp_path / "data" / "pgns")
    monkeypatch.setattr(games, "CSV_DIR", tmp_path / "data" / "csv")
    monkeypatch.setattr(games, "GAMES_CSV_PATH", tmp_path / "data" / "csv" / "games.csv")
    monkeypatch.setattr(
        games, "MISSING_LINK_DIR", tmp_path / "data" / "temp" / "missing-link"
    )
    monkeypatch.setattr(metadata, "METADATA_DIR", tmp_path / "data" / "metadata")
    monkeypatch.setattr(
        metadata, "MASTER_METADATA_PATH", tmp_path / "data" / "metadata" / "master.json"
    )
    games.reset_csv_uuid_cache()


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


def test_select_archives_when_current_equals_last_executed():
    archives = [
        "https://api.chess.com/pub/player/test/games/2026/06",
        "https://api.chess.com/pub/player/test/games/2026/07",
        "https://api.chess.com/pub/player/test/games/2026/08",
    ]
    selected = select_archive_urls(archives, 2026, 8, 2026, 8)
    assert selected == [
        "https://api.chess.com/pub/player/test/games/2026/08",
    ]


def test_select_archives_when_current_is_after_last_executed():
    archives = [
        "https://api.chess.com/pub/player/test/games/2026/06",
        "https://api.chess.com/pub/player/test/games/2026/07",
        "https://api.chess.com/pub/player/test/games/2026/08",
    ]
    selected = select_archive_urls(archives, 2026, 6, 2026, 8)
    assert selected == archives


def test_select_archives_on_first_run():
    archives = [
        "https://api.chess.com/pub/player/test/games/2026/06",
        "https://api.chess.com/pub/player/test/games/2026/07",
        "https://api.chess.com/pub/player/test/games/2026/08",
    ]
    selected = select_archive_urls(archives, None, None, 2026, 8)
    assert selected == archives


def test_current_month_remains_updateable(tmp_path, monkeypatch):
    _patch_storage(tmp_path, monkeypatch)
    games.ensure_data_directories()

    archive_url = "https://api.chess.com/pub/player/test/games/2026/08"
    sample_game = {
        "uuid": "new-game-uuid",
        "pgn": SAMPLE_PGN_WITH_LINK,
    }

    with patch(
        "src.pipeline.client.get_monthly_games", return_value=[sample_game]
    ):
        result = process_month(archive_url, 2026, 8, "test")

    assert result["failed"] == 0
    saved = metadata.load_month_metadata(2026, 8)
    assert saved["is_complete"] is False
    assert "new-game-uuid" in saved["processed_game_uuids"]


def test_existing_uuid_is_skipped(tmp_path, monkeypatch):
    _patch_storage(tmp_path, monkeypatch)

    archive_url = "https://api.chess.com/pub/player/test/games/2026/07"
    month_data = metadata.create_month_metadata("test", 2026, 7, archive_url)
    metadata.record_processed_game(month_data, "existing-uuid")
    metadata.save_month_metadata(month_data)

    sample_game = {
        "uuid": "existing-uuid",
        "pgn": SAMPLE_PGN_WITH_LINK,
    }

    with patch(
        "src.pipeline.client.get_monthly_games", return_value=[sample_game]
    ):
        result = process_month(
            archive_url, 2026, 8, "test", month_metadata=month_data
        )

    assert result["skipped_games"] == 1
    assert result["failed"] == 0


def test_game_missing_link_is_saved_for_review(tmp_path, monkeypatch):
    _patch_storage(tmp_path, monkeypatch)
    games.ensure_data_directories()

    archive_url = "https://api.chess.com/pub/player/test/games/2026/08"
    sample_game = {
        "uuid": "missing-link-game",
        "pgn": '[White "a"]\n\n1. e4 1-0',
    }

    with patch(
        "src.pipeline.client.get_monthly_games", return_value=[sample_game]
    ):
        result = process_month(archive_url, 2026, 8, "test")

    assert result["failed"] == 1
    missing_link_path = (
        tmp_path / "data" / "temp" / "missing-link" / "2026-08-missing-link-game.pgn"
    )
    assert missing_link_path.is_file()


def test_api_requests_include_required_headers():
    from unittest.mock import MagicMock, patch

    from src.config import REQUEST_HEADERS

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.ok = True
    mock_response.json.return_value = {"archives": []}

    with patch("src.chess_com.client.requests.get", return_value=mock_response) as mock_get:
        from src.chess_com.client import get_archive_urls

        get_archive_urls("testplayer")

    mock_get.assert_called_once()
    _, call_kwargs = mock_get.call_args
    assert call_kwargs["headers"] == REQUEST_HEADERS
    assert call_kwargs["headers"]["User-Agent"] == "Tool"


def test_run_pipeline_skips_older_months_with_master(tmp_path, monkeypatch):
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr("src.config._PLAYER", "testplayer")
    games.ensure_data_directories()

    master = metadata.create_master_metadata()
    metadata.update_master_metadata(master, 2026, 8)
    metadata.save_master_metadata(master)

    archives = [
        "https://api.chess.com/pub/player/test/games/2026/06",
        "https://api.chess.com/pub/player/test/games/2026/08",
    ]
    sample_game = {
        "uuid": "pipeline-game",
        "pgn": SAMPLE_PGN_WITH_LINK,
    }

    with patch("src.pipeline.client.get_archive_urls", return_value=archives):
        with patch(
            "src.pipeline.client.get_monthly_games", return_value=[sample_game]
        ) as mock_monthly:
            totals = run_pipeline()

    mock_monthly.assert_called_once()
    assert totals["months_processed"] == 1
    assert totals["games_processed"] == 1


def test_run_pipeline_processes_gap_months(tmp_path, monkeypatch):
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr("src.config._PLAYER", "testplayer")
    games.ensure_data_directories()

    master = metadata.create_master_metadata()
    metadata.update_master_metadata(master, 2026, 6)
    metadata.save_master_metadata(master)

    archives = [
        "https://api.chess.com/pub/player/test/games/2026/06",
        "https://api.chess.com/pub/player/test/games/2026/07",
        "https://api.chess.com/pub/player/test/games/2026/08",
    ]
    sample_game = {
        "uuid": "pipeline-game",
        "pgn": SAMPLE_PGN_WITH_LINK,
    }

    with patch("src.pipeline.client.get_archive_urls", return_value=archives):
        with patch(
            "src.pipeline.client.get_monthly_games", return_value=[sample_game]
        ) as mock_monthly:
            totals = run_pipeline()

    assert mock_monthly.call_count == 3
    assert totals["months_processed"] == 3

    saved_master = metadata.load_master_metadata()
    assert saved_master["last_metadata_file"] == "2026-08"


def test_run_pipeline_integration(tmp_path, monkeypatch):
    _patch_storage(tmp_path, monkeypatch)
    monkeypatch.setattr("src.config._PLAYER", "testplayer")

    archives = ["https://api.chess.com/pub/player/test/games/2026/08"]
    sample_game = {
        "uuid": "pipeline-game",
        "pgn": SAMPLE_PGN_WITH_LINK,
    }

    with patch("src.pipeline.client.get_archive_urls", return_value=archives):
        with patch(
            "src.pipeline.client.get_monthly_games", return_value=[sample_game]
        ):
            totals = run_pipeline()

    assert totals["games_processed"] == 1
    assert (tmp_path / "data" / "pgns" / "2026-08-pipeline-game.pgn").is_file()
    csv_path = tmp_path / "data" / "csv" / "games.csv"
    assert csv_path.is_file()
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["uuid"] == "pipeline-game"

    saved_master = metadata.load_master_metadata()
    assert saved_master["last_metadata_file"] == "2026-08"
