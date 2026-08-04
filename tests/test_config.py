"""Tests for environment configuration validation."""

import pytest

from src import config
from src.config import ConfigurationError
from src.gcp.gcs import build_bucket_name


def _clear_env(monkeypatch):
    for name in config.REQUIRED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    config.reset_settings_cache()


def test_missing_player_raises_configuration_error(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr("src.config.load_dotenv", lambda *args, **kwargs: None)
    with pytest.raises(ConfigurationError, match="PLAYER environment variable is required"):
        config._load_player()


def test_blank_player_raises_configuration_error(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("PLAYER", "   ")
    monkeypatch.setattr("src.config.load_dotenv", lambda *args, **kwargs: None)
    with pytest.raises(ConfigurationError, match="PLAYER environment variable is required"):
        config._load_player()


def test_missing_gcp_variable_raises_before_clients(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("PLAYER", "LindaW25")
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    monkeypatch.setattr("src.config.load_dotenv", lambda *args, **kwargs: None)
    with pytest.raises(
        ConfigurationError, match="GCP_PROJECT_NUMBER environment variable is required"
    ):
        config.load_settings()


def test_bucket_name_construction():
    bucket_name = build_bucket_name("chess-data", "123456789", "us-central1")
    assert bucket_name == "chess-data-123456789-us-central1"


def test_load_settings_builds_bucket_and_table_ids(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("PLAYER", "LindaW25")
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    monkeypatch.setenv("GCP_PROJECT_NUMBER", "123456789")
    monkeypatch.setenv("LOCATION", "us-central1")
    monkeypatch.setenv("GCS_BASE_BUCKET_NAME", "chess-data")
    monkeypatch.setenv("BQ_DATASET_NAME", "chess")
    monkeypatch.setenv("BQ_TABLE_NAME", "games")
    monkeypatch.setattr("src.config.load_dotenv", lambda *args, **kwargs: None)

    settings = config.load_settings()
    assert settings.gcs_bucket_name == "chess-data-123456789-us-central1"
    assert settings.bq_table_id == "demo-project.chess.games"
