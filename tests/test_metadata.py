"""Tests for monthly metadata persistence."""

import json
from pathlib import Path

import pytest

from src.local_storage import metadata


@pytest.fixture
def metadata_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "METADATA_DIR", tmp_path)
    return tmp_path


def test_create_and_save_metadata(metadata_dir):
    data = metadata.create_month_metadata(
        "LindaW25", 2026, 8, "https://api.chess.com/pub/player/lindaw25/games/2026/08"
    )
    path = metadata.save_month_metadata(data)
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["player"] == "LindaW25"
    assert loaded["processed_game_uuids"] == []
    assert loaded["is_complete"] is False


def test_load_existing_metadata(metadata_dir):
    data = metadata.create_month_metadata("player", 2025, 1, "http://example/2025/01")
    metadata.save_month_metadata(data)
    loaded = metadata.load_month_metadata(2025, 1)
    assert loaded is not None
    assert loaded["year"] == 2025
    assert loaded["month"] == 1


def test_record_processed_game(metadata_dir):
    data = metadata.create_month_metadata("player", 2026, 3, "http://example/2026/03")
    metadata.record_processed_game(data, "uuid-1")
    metadata.record_processed_game(data, "uuid-1")
    assert data["processed_game_uuids"] == ["uuid-1"]
    assert data["game_count"] == 1
    assert data["last_updated_at"] is not None


def test_is_game_processed(metadata_dir):
    data = metadata.create_month_metadata("player", 2026, 4, "http://example/2026/04")
    metadata.record_processed_game(data, "uuid-a")
    assert metadata.is_game_processed(data, "uuid-a")
    assert not metadata.is_game_processed(data, "uuid-b")


def test_atomic_metadata_write(metadata_dir):
    data = metadata.create_month_metadata("player", 2026, 5, "http://example/2026/05")
    path = metadata.metadata_path(2026, 5)
    metadata.save_month_metadata(data)
    original = path.read_text(encoding="utf-8")

    metadata.record_processed_game(data, "uuid-x")
    metadata.save_month_metadata(data)

    assert path.read_text(encoding="utf-8") != original
    assert not list(metadata_dir.glob("*.tmp"))
