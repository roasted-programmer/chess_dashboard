"""Tests for pipeline coordination with mocked GCP persistence."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src import config
from src.gcp import bigquery as bq
from src.gcp import gcs
from src.pipeline import process_game, process_month, run_pipeline, select_archive_urls

SAMPLE_PGN_WITH_LINK = (
    '[White "w"]\n'
    '[Black "b"]\n'
    '[Result "1-0"]\n'
    '[Link "https://www.chess.com/game/live/1234567890"]\n'
    '[UTCDate "2026.08.01"]\n'
    '[UTCTime "12:00:00"]\n'
    '[WhiteElo "1500"]\n'
    '[BlackElo "1500"]\n'
    '[TimeControl "600"]\n'
    '[Termination "w won"]\n'
    '[ECOUrl "https://www.chess.com/openings/Sicilian-Defense"]\n\n'
    "1. e4 1-0"
)


def _set_settings(monkeypatch):
    config.reset_settings_cache()
    gcs.reset_gcs_clients()
    bq.reset_bq_client()
    monkeypatch.setenv("PLAYER", "testplayer")
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    monkeypatch.setenv("GCP_PROJECT_NUMBER", "123456789")
    monkeypatch.setenv("LOCATION", "us-central1")
    monkeypatch.setenv("GCS_BASE_BUCKET_NAME", "chess-data")
    monkeypatch.setenv("BQ_DATASET_NAME", "chess")
    monkeypatch.setenv("BQ_TABLE_NAME", "games")
    monkeypatch.setattr("src.config.load_dotenv", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    _set_settings(monkeypatch)
    yield
    config.reset_settings_cache()
    gcs.reset_gcs_clients()
    bq.reset_bq_client()


def _mock_cloud_storage(stored=None):
    if stored is None:
        stored = {}
    mock_bucket = MagicMock()

    def _blob(path):
        blob = MagicMock()
        blob.exists.side_effect = lambda: path in stored

        def _download(encoding="utf-8"):
            return stored[path]

        def _upload(content, content_type=None, if_generation_match=None):
            if if_generation_match == 0 and path in stored:
                from google.api_core.exceptions import PreconditionFailed

                raise PreconditionFailed("exists")
            stored[path] = content

        blob.download_as_text.side_effect = _download
        blob.upload_from_string.side_effect = _upload
        return blob

    mock_bucket.blob.side_effect = _blob
    mock_bucket.list_blobs.return_value = []
    return mock_bucket, stored


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


def test_current_month_remains_updateable():
    mock_bucket, stored = _mock_cloud_storage()
    sample_game = {
        "uuid": "new-game-uuid",
        "pgn": SAMPLE_PGN_WITH_LINK,
        "rules": "chess",
    }

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        with patch("src.pipeline.bq.existing_uuids", return_value=set()):
            with patch("src.pipeline.bq.insert_games", return_value={"new-game-uuid"}):
                with patch(
                    "src.pipeline.client.get_monthly_games", return_value=[sample_game]
                ):
                    result = process_month(
                        "https://api.chess.com/pub/player/test/games/2026/08",
                        2026,
                        8,
                        "test",
                    )

    assert result["failed"] == 0
    saved = json.loads(stored["metadata/2026-08.json"])
    assert saved["is_complete"] is False
    assert "new-game-uuid" in saved["processed_game_uuids"]
    assert "pgns/2026-08-new-game-uuid.pgn" in stored


def test_existing_uuid_is_skipped():
    month_data = gcs.create_month_metadata(
        "test", 2026, 7, "https://api.chess.com/pub/player/test/games/2026/07"
    )
    gcs.record_processed_game(month_data, "existing-uuid")
    sample_game = {"uuid": "existing-uuid", "pgn": SAMPLE_PGN_WITH_LINK}

    with patch("src.pipeline.bq.insert_games") as mock_insert:
        with patch(
            "src.pipeline.client.get_monthly_games", return_value=[sample_game]
        ):
            with patch("src.pipeline.gcs.save_month_metadata"):
                result = process_month(
                    "https://api.chess.com/pub/player/test/games/2026/07",
                    2026,
                    8,
                    "test",
                    month_metadata=month_data,
                )

    assert result["skipped_games"] == 1
    assert result["failed"] == 0
    mock_insert.assert_not_called()


def test_game_missing_link_is_saved_for_review():
    mock_bucket, stored = _mock_cloud_storage()
    sample_game = {"uuid": "missing-link-game", "pgn": '[White "a"]\n\n1. e4 1-0'}

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        with patch(
            "src.pipeline.client.get_monthly_games", return_value=[sample_game]
        ):
            result = process_month(
                "https://api.chess.com/pub/player/test/games/2026/08",
                2026,
                8,
                "test",
            )

    assert result["failed"] == 1
    assert "temp/missing-link/2026-08-missing-link-game.pgn" in stored


def test_failed_cloud_write_does_not_record_metadata():
    month_data = gcs.create_month_metadata(
        "test", 2026, 8, "https://api.chess.com/pub/player/test/games/2026/08"
    )
    sample_game = {
        "uuid": "fail-game",
        "pgn": SAMPLE_PGN_WITH_LINK,
        "rules": "chess",
    }

    with patch("src.pipeline.bq.game_artifacts_exist", return_value=False):
        with patch("src.pipeline.gcs.upload_pgn", return_value="pgns/x.pgn"):
            with patch(
                "src.pipeline.bq.insert_game", side_effect=RuntimeError("bq down")
            ):
                processed = process_game(sample_game, month_data, 2026, 8)

    assert processed is False
    assert "fail-game" not in month_data["processed_game_uuids"]


def test_batch_write_failure_does_not_record_metadata():
    mock_bucket, stored = _mock_cloud_storage()
    sample_game = {
        "uuid": "fail-game",
        "pgn": SAMPLE_PGN_WITH_LINK,
        "rules": "chess",
    }

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        with patch("src.pipeline.bq.existing_uuids", return_value=set()):
            with patch("src.pipeline.bq.insert_games", return_value=set()):
                with patch(
                    "src.pipeline.client.get_monthly_games",
                    return_value=[sample_game],
                ):
                    result = process_month(
                        "https://api.chess.com/pub/player/test/games/2026/08",
                        2026,
                        8,
                        "test",
                    )

    assert result["failed"] == 1
    saved = json.loads(stored["metadata/2026-08.json"])
    assert "fail-game" not in saved["processed_game_uuids"]


def test_api_requests_include_required_headers():
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


def test_run_pipeline_skips_older_months_with_master():
    mock_bucket, stored = _mock_cloud_storage()
    master = gcs.create_master_metadata()
    gcs.update_master_metadata(master, 2026, 8)
    stored["metadata/master.json"] = json.dumps(master)

    archives = [
        "https://api.chess.com/pub/player/test/games/2026/06",
        "https://api.chess.com/pub/player/test/games/2026/08",
    ]
    sample_game = {
        "uuid": "pipeline-game",
        "pgn": SAMPLE_PGN_WITH_LINK,
        "rules": "chess",
    }

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        with patch("src.pipeline.bq.ensure_dataset_and_table"):
            with patch("src.pipeline.bq.existing_uuids", return_value=set()):
                with patch(
                    "src.pipeline.bq.insert_games", return_value={"pipeline-game"}
                ):
                    with patch(
                        "src.pipeline.client.get_archive_urls", return_value=archives
                    ):
                        with patch(
                            "src.pipeline.client.get_monthly_games",
                            return_value=[sample_game],
                        ) as mock_monthly:
                            totals = run_pipeline()

    mock_monthly.assert_called_once()
    assert totals["months_processed"] == 1
    assert totals["games_processed"] == 1


def test_run_pipeline_processes_gap_months():
    mock_bucket, stored = _mock_cloud_storage()
    master = gcs.create_master_metadata()
    gcs.update_master_metadata(master, 2026, 6)
    stored["metadata/master.json"] = json.dumps(master)

    archives = [
        "https://api.chess.com/pub/player/test/games/2026/06",
        "https://api.chess.com/pub/player/test/games/2026/07",
        "https://api.chess.com/pub/player/test/games/2026/08",
    ]
    sample_game = {
        "uuid": "pipeline-game",
        "pgn": SAMPLE_PGN_WITH_LINK,
        "rules": "chess",
    }

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        with patch("src.pipeline.bq.ensure_dataset_and_table"):
            with patch("src.pipeline.bq.existing_uuids", return_value=set()):
                with patch(
                    "src.pipeline.bq.insert_games", return_value={"pipeline-game"}
                ):
                    with patch(
                        "src.pipeline.client.get_archive_urls", return_value=archives
                    ):
                        with patch(
                            "src.pipeline.client.get_monthly_games",
                            return_value=[sample_game],
                        ) as mock_monthly:
                            totals = run_pipeline()

    assert mock_monthly.call_count == 3
    assert totals["months_processed"] == 3
    saved_master = json.loads(stored["metadata/master.json"])
    assert saved_master["last_metadata_file"] == "2026-08"


def test_run_pipeline_integration():
    mock_bucket, stored = _mock_cloud_storage()
    archives = ["https://api.chess.com/pub/player/test/games/2026/08"]
    sample_game = {
        "uuid": "pipeline-game",
        "pgn": SAMPLE_PGN_WITH_LINK,
        "rules": "chess",
    }

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        with patch("src.pipeline.bq.ensure_dataset_and_table"):
            with patch("src.pipeline.bq.existing_uuids", return_value=set()):
                with patch(
                    "src.pipeline.bq.insert_games", return_value={"pipeline-game"}
                ) as mock_insert:
                    with patch(
                        "src.pipeline.client.get_archive_urls", return_value=archives
                    ):
                        with patch(
                            "src.pipeline.client.get_monthly_games",
                            return_value=[sample_game],
                        ):
                            totals = run_pipeline()

    assert totals["games_processed"] == 1
    assert "pgns/2026-08-pipeline-game.pgn" in stored
    mock_insert.assert_called_once()
    month_meta = json.loads(stored["metadata/2026-08.json"])
    assert "pipeline-game" in month_meta["processed_game_uuids"]
    saved_master = json.loads(stored["metadata/master.json"])
    assert saved_master["last_metadata_file"] == "2026-08"
