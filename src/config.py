"""Application-wide configuration."""

from pathlib import Path

from dotenv import load_dotenv
import os

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PGN_DIR = DATA_DIR / "pgns"
CSV_DIR = DATA_DIR / "csv"
METADATA_DIR = DATA_DIR / "metadata"

REQUEST_HEADERS = {
    "User-Agent": "Tool",
}
REQUEST_TIMEOUT = 30

_PLAYER: str | None = None


class ConfigurationError(Exception):
    pass


def _load_player() -> str:
    load_dotenv(ROOT_DIR / ".env")
    player = os.environ.get("PLAYER", "")
    if not player or not player.strip():
        raise ConfigurationError(
            "Configuration error: the PLAYER environment variable is required."
        )
    return player.strip()


def __getattr__(name: str):
    global _PLAYER
    if name == "PLAYER":
        if _PLAYER is None:
            _PLAYER = _load_player()
        return _PLAYER
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
