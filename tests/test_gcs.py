"""Tests for Google Cloud Storage PGN and metadata persistence."""

import json
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import PreconditionFailed
from google.cloud.exceptions import NotFound

from src.gcp import gcs


@pytest.fixture(autouse=True)
def _reset_gcs(monkeypatch):
    gcs.reset_gcs_clients()
    monkeypatch.setattr("src.gcp.gcs.config.GCS_BUCKET_NAME", "chess-data-123-us")
    monkeypatch.setattr("src.gcp.gcs.config.GCP_PROJECT_ID", "demo-project")
    monkeypatch.setattr("src.gcp.gcs.config.LOCATION", "us-central1")
    yield
    gcs.reset_gcs_clients()


def test_ensure_bucket_creates_when_missing():
    mock_client = MagicMock()
    mock_client.get_bucket.side_effect = NotFound("missing")
    created = MagicMock()
    mock_client.create_bucket.return_value = created

    with patch("src.gcp.gcs.get_storage_client", return_value=mock_client):
        bucket = gcs.ensure_bucket()

    assert bucket is created
    mock_client.create_bucket.assert_called_once_with(
        "chess-data-123-us", location="us-central1"
    )


def test_ensure_bucket_uses_existing():
    mock_client = MagicMock()
    existing = MagicMock()
    mock_client.get_bucket.return_value = existing

    with patch("src.gcp.gcs.get_storage_client", return_value=mock_client):
        bucket = gcs.ensure_bucket()

    assert bucket is existing
    mock_client.create_bucket.assert_not_called()


def test_upload_pgn_skips_existing_object():
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_blob.upload_from_string.side_effect = PreconditionFailed("exists")
    mock_bucket.blob.return_value = mock_blob

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        path = gcs.upload_pgn(
            {"uuid": "abc", "pgn": '[Link "x"]\n\n1. e4 1-0'}, 2026, 8
        )

    assert path == "pgns/2026-08-abc.pgn"
    mock_blob.upload_from_string.assert_called_once_with(
        '[Link "x"]\n\n1. e4 1-0',
        content_type="text/plain; charset=utf-8",
        if_generation_match=0,
    )


def test_upload_pgn_writes_when_missing():
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        path = gcs.upload_pgn(
            {"uuid": "abc", "pgn": '[Link "x"]\n\n1. e4 1-0'}, 2026, 8
        )

    assert path == "pgns/2026-08-abc.pgn"
    mock_blob.upload_from_string.assert_called_once_with(
        '[Link "x"]\n\n1. e4 1-0',
        content_type="text/plain; charset=utf-8",
        if_generation_match=0,
    )


def test_list_existing_pgn_uuids():
    mock_bucket = MagicMock()
    blob_a = MagicMock()
    blob_a.name = "pgns/2026-08-uuid-a.pgn"
    blob_b = MagicMock()
    blob_b.name = "pgns/2026-08-uuid-b.pgn"
    mock_bucket.list_blobs.return_value = [blob_a, blob_b]

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        existing = gcs.list_existing_pgn_uuids(2026, 8)

    assert existing == {"uuid-a", "uuid-b"}
    mock_bucket.list_blobs.assert_called_once_with(prefix="pgns/2026-08-")


def test_upload_pgns_concurrent_returns_successes():
    games = [
        {"uuid": "a", "pgn": "pgn-a"},
        {"uuid": "b", "pgn": "pgn-b"},
    ]

    with patch("src.gcp.gcs.upload_pgn") as mock_upload:
        mock_upload.side_effect = [
            "pgns/2026-08-a.pgn",
            RuntimeError("upload failed"),
        ]
        uploaded = gcs.upload_pgns_concurrent(games, 2026, 8, max_workers=2)

    assert uploaded == {"a"}


def test_metadata_save_and_load_roundtrip():
    stored = {}

    mock_bucket = MagicMock()

    def _blob(path):
        blob = MagicMock()
        blob.exists.side_effect = lambda: path in stored
        blob.download_as_text.side_effect = lambda encoding="utf-8": stored[path]
        blob.upload_from_string.side_effect = (
            lambda content, content_type=None, if_generation_match=None: stored.__setitem__(
                path, content
            )
        )
        return blob

    mock_bucket.blob.side_effect = _blob
    mock_bucket.list_blobs.return_value = []

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        data = gcs.create_month_metadata(
            "player", 2026, 8, "https://api.chess.com/pub/player/player/games/2026/08"
        )
        gcs.record_processed_game(data, "uuid-1")
        gcs.save_month_metadata(data)
        loaded = gcs.load_month_metadata(2026, 8)

    assert loaded is not None
    assert loaded["processed_game_uuids"] == ["uuid-1"]
    assert json.loads(stored["metadata/2026-08.json"])["game_count"] == 1


def test_master_metadata_save_and_load():
    stored = {}
    mock_bucket = MagicMock()

    def _blob(path):
        blob = MagicMock()
        blob.exists.side_effect = lambda: path in stored
        blob.download_as_text.side_effect = lambda encoding="utf-8": stored[path]
        blob.upload_from_string.side_effect = (
            lambda content, content_type=None, if_generation_match=None: stored.__setitem__(
                path, content
            )
        )
        return blob

    mock_bucket.blob.side_effect = _blob
    mock_bucket.list_blobs.return_value = []

    with patch("src.gcp.gcs.ensure_bucket", return_value=mock_bucket):
        master = gcs.create_master_metadata()
        gcs.update_master_metadata(master, 2026, 8)
        gcs.save_master_metadata(master)
        loaded = gcs.load_master_metadata()

    assert loaded["last_metadata_file"] == "2026-08"
    assert "metadata/master.json" in stored


def test_is_game_processed_and_record():
    data = gcs.create_month_metadata("player", 2026, 3, "http://example/2026/03")
    gcs.record_processed_game(data, "uuid-1")
    gcs.record_processed_game(data, "uuid-1")
    assert data["processed_game_uuids"] == ["uuid-1"]
    assert data["game_count"] == 1
    assert gcs.is_game_processed(data, "uuid-1")
    assert not gcs.is_game_processed(data, "uuid-2")
