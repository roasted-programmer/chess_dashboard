"""Application-wide configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent

REQUEST_HEADERS = {
    "User-Agent": "Tool",
}
REQUEST_TIMEOUT = 30

REQUIRED_ENV_VARS = (
    "PLAYER",
    "GCP_PROJECT_ID",
    "GCP_PROJECT_NUMBER",
    "LOCATION",
    "GCS_BASE_BUCKET_NAME",
    "BQ_DATASET_NAME",
    "BQ_TABLE_NAME",
)

_SETTINGS = None


class ConfigurationError(Exception):
    """Raised when required application configuration is missing or invalid."""


class Settings:
    """Validated runtime settings loaded from the environment."""

    def __init__(
        self,
        player: str,
        gcp_project_id: str,
        gcp_project_number: str,
        location: str,
        gcs_base_bucket_name: str,
        bq_dataset_name: str,
        bq_table_name: str,
    ):
        self.player = player
        self.gcp_project_id = gcp_project_id
        self.gcp_project_number = gcp_project_number
        self.location = location
        self.gcs_base_bucket_name = gcs_base_bucket_name
        self.bq_dataset_name = bq_dataset_name
        self.bq_table_name = bq_table_name
        self.gcs_bucket_name = (
            f"{gcs_base_bucket_name}-{gcp_project_number}-{location}"
        )
        self.bq_table_id = f"{gcp_project_id}.{bq_dataset_name}.{bq_table_name}"


def _require_env(name: str) -> str:
    """Return a required non-blank environment variable."""
    value = os.environ.get(name, "")
    if not value or not str(value).strip():
        raise ConfigurationError(
            f"Configuration error: the {name} environment variable is required."
        )
    cleaned_value = str(value).strip()
    return cleaned_value


def load_settings() -> Settings:
    """Load and validate all required environment settings.

    Returns:
        settings (Settings): Validated application settings.

    Raises:
        ConfigurationError: If any required environment variable is missing or blank.
    """
    global _SETTINGS
    if _SETTINGS is not None:
        cached_settings = _SETTINGS
        return cached_settings

    load_dotenv(ROOT_DIR / ".env")
    settings = Settings(
        player=_require_env("PLAYER"),
        gcp_project_id=_require_env("GCP_PROJECT_ID"),
        gcp_project_number=_require_env("GCP_PROJECT_NUMBER"),
        location=_require_env("LOCATION"),
        gcs_base_bucket_name=_require_env("GCS_BASE_BUCKET_NAME"),
        bq_dataset_name=_require_env("BQ_DATASET_NAME"),
        bq_table_name=_require_env("BQ_TABLE_NAME"),
    )
    _SETTINGS = settings
    return settings


def reset_settings_cache() -> None:
    """Clear the cached settings object."""
    global _SETTINGS
    _SETTINGS = None


def _load_player() -> str:
    """Load and validate the PLAYER environment variable."""
    load_dotenv(ROOT_DIR / ".env")
    player_name = _require_env("PLAYER")
    return player_name


def __getattr__(name: str):
    """Lazy-load module attributes that require environment configuration."""
    if name == "PLAYER":
        configured_player = load_settings().player
        return configured_player
    if name == "GCP_PROJECT_ID":
        project_id = load_settings().gcp_project_id
        return project_id
    if name == "GCP_PROJECT_NUMBER":
        project_number = load_settings().gcp_project_number
        return project_number
    if name == "LOCATION":
        location = load_settings().location
        return location
    if name == "GCS_BASE_BUCKET_NAME":
        base_bucket_name = load_settings().gcs_base_bucket_name
        return base_bucket_name
    if name == "GCS_BUCKET_NAME":
        bucket_name = load_settings().gcs_bucket_name
        return bucket_name
    if name == "BQ_DATASET_NAME":
        dataset_name = load_settings().bq_dataset_name
        return dataset_name
    if name == "BQ_TABLE_NAME":
        table_name = load_settings().bq_table_name
        return table_name
    if name == "BQ_TABLE_ID":
        table_id = load_settings().bq_table_id
        return table_id
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
