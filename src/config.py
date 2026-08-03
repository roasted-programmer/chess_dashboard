"""Application-wide configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PGN_DIR = DATA_DIR / "pgns"
CSV_DIR = DATA_DIR / "csv"
METADATA_DIR = DATA_DIR / "metadata"

REQUEST_HEADERS = {
    "User-Agent": "Tool",
}
REQUEST_TIMEOUT = 30

_PLAYER = None


class ConfigurationError(Exception):
    """Raised when required application configuration is missing or invalid."""


def _load_player() -> str:
    """Load and validate the PLAYER environment variable."""
    load_dotenv(ROOT_DIR / ".env")
    player = os.environ.get("PLAYER", "")
    if not player or not player.strip():
        raise ConfigurationError(
            "Configuration error: the PLAYER environment variable is required."
        )
    player_name = player.strip()
    return player_name


def __getattr__(name: str):
    """Lazy-load module attributes that require environment configuration."""
    global _PLAYER
    if name == "PLAYER":
        if _PLAYER is None:
            _PLAYER = _load_player()
        configured_player = _PLAYER
        return configured_player
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
