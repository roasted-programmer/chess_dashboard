"""Tests for BigQuery dataset/table setup and game insertion."""

from unittest.mock import MagicMock, patch

import pytest
from google.cloud import bigquery

from src.gcp import bigquery as bq


@pytest.fixture(autouse=True)
def _reset_bq(monkeypatch):
    bq.reset_bq_client()
    monkeypatch.setattr("src.gcp.bigquery.config.GCP_PROJECT_ID", "demo-project")
    monkeypatch.setattr("src.gcp.bigquery.config.BQ_DATASET_NAME", "chess")
    monkeypatch.setattr("src.gcp.bigquery.config.BQ_TABLE_NAME", "games")
    monkeypatch.setattr(
        "src.gcp.bigquery.config.BQ_TABLE_ID", "demo-project.chess.games"
    )
    monkeypatch.setattr("src.gcp.bigquery.config.LOCATION", "us-central1")
    yield
    bq.reset_bq_client()


def _sample_game(uuid: str = "game-1") -> dict[str, str]:
    return {
        "uuid": uuid,
        "white_username": "alice",
        "black_username": "bob",
        "result": "1-0",
        "rules": "chess",
        "opening": "Sicilian Defense",
        "main_opening": "Sicilian Defense",
        "opening_variant": "",
        "opening_subvariant": "",
        "game_url": "https://www.chess.com/game/live/1",
        "utc_date": "2026.08.03",
        "utc_time": "12:00:00",
        "white_elo": "1500",
        "black_elo": "1500",
        "time_control": "600",
        "termination": "alice won",
        "pgn": '[White "alice"]\n\n1. e4 1-0',
    }


def test_games_table_schema_matches_csv_fields():
    schema = bq.games_table_schema()
    names = [field.name for field in schema]
    assert names == bq.GAME_COLUMNS
    assert all(isinstance(field, bigquery.SchemaField) for field in schema)
    assert schema[0].mode == "REQUIRED"


def test_ensure_dataset_and_table_creates_resources():
    mock_client = MagicMock()
    with patch("src.gcp.bigquery.get_bq_client", return_value=mock_client):
        table_id = bq.ensure_dataset_and_table()

    assert table_id == "demo-project.chess.games"
    mock_client.create_dataset.assert_called_once()
    mock_client.create_table.assert_called_once()


def test_build_game_row_sets_pgn_object_path():
    row = bq.build_game_row(_sample_game(), 2026, 8)
    assert row["uuid"] == "game-1"
    assert row["pgn_file"] == "pgns/2026-08-game-1.pgn"


def test_existing_uuids_queries_in_batches():
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.__iter__.return_value = [{"uuid": "a"}, {"uuid": "c"}]
    mock_client.query.return_value.result.return_value = mock_result

    with patch("src.gcp.bigquery.get_bq_client", return_value=mock_client):
        found = bq.existing_uuids(["a", "b", "c"])

    assert found == {"a", "c"}
    mock_client.query.assert_called_once()


def test_insert_game_skips_when_exists():
    mock_client = MagicMock()
    with patch("src.gcp.bigquery.get_bq_client", return_value=mock_client):
        with patch("src.gcp.bigquery.game_exists", return_value=True):
            bq.insert_game(_sample_game(), 2026, 8)

    mock_client.insert_rows_json.assert_not_called()


def test_insert_games_uses_uuid_as_insert_id():
    mock_client = MagicMock()
    mock_client.insert_rows_json.return_value = []
    games = [_sample_game("abc-123"), _sample_game("def-456")]

    with patch("src.gcp.bigquery.get_bq_client", return_value=mock_client):
        inserted = bq.insert_games(games, 2026, 8)

    assert inserted == {"abc-123", "def-456"}
    mock_client.insert_rows_json.assert_called_once()
    args, kwargs = mock_client.insert_rows_json.call_args
    assert args[0] == "demo-project.chess.games"
    assert kwargs["row_ids"] == ["abc-123", "def-456"]


def test_insert_games_excludes_failed_indexes():
    mock_client = MagicMock()
    mock_client.insert_rows_json.return_value = [
        {"index": 1, "errors": [{"message": "bad"}]},
    ]
    games = [_sample_game("ok"), _sample_game("bad")]

    with patch("src.gcp.bigquery.get_bq_client", return_value=mock_client):
        inserted = bq.insert_games(games, 2026, 8)

    assert inserted == {"ok"}


def test_insert_game_raises_on_errors():
    mock_client = MagicMock()
    mock_client.insert_rows_json.return_value = [{"errors": ["boom"]}]

    with patch("src.gcp.bigquery.get_bq_client", return_value=mock_client):
        with patch("src.gcp.bigquery.game_exists", return_value=False):
            with pytest.raises(RuntimeError, match="BigQuery insert failed"):
                bq.insert_game(_sample_game(), 2026, 8)
