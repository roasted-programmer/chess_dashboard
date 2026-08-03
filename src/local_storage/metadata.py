"""Monthly processing metadata persistence."""

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import METADATA_DIR

logger = logging.getLogger(__name__)


def metadata_path(year: int, month: int) -> Path:
    return METADATA_DIR / f"{year:04d}-{month:02d}.json"


def create_month_metadata(
    player: str, year: int, month: int, archive_url: str
) -> dict[str, Any]:
    return {
        "player": player,
        "year": year,
        "month": month,
        "archive_url": archive_url,
        "processed_game_uuids": [],
        "game_count": 0,
        "last_updated_at": None,
        "is_complete": False,
    }


def load_month_metadata(year: int, month: int) -> dict[str, Any] | None:
    """Load metadata for a month, or return None when no file exists."""
    path = metadata_path(year, month)
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_month_metadata(metadata: dict[str, Any]) -> Path:
    """Save metadata atomically and return the destination path."""
    path = metadata_path(metadata["year"], metadata["month"])
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(metadata, indent=2)
    payload += "\n"

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as temp_handle:
        temp_handle.write(payload)
        temp_handle.flush()
        temp_path = Path(temp_handle.name)

    temp_path.replace(path)
    logger.info("Updated metadata: %s", path)
    return path


def is_game_processed(metadata: dict[str, Any], uuid: str) -> bool:
    return uuid in metadata.get("processed_game_uuids", [])


def record_processed_game(metadata: dict[str, Any], uuid: str) -> None:
    """Record a successfully processed game UUID without duplicates."""
    processed = metadata.setdefault("processed_game_uuids", [])
    if uuid not in processed:
        processed.append(uuid)
    metadata["game_count"] = len(processed)
    metadata["last_updated_at"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def ensure_month_metadata(
    player: str, year: int, month: int, archive_url: str
) -> dict[str, Any]:
    """Load existing metadata or initialize a new record."""
    metadata = load_month_metadata(year, month)
    if metadata is None:
        metadata = create_month_metadata(player, year, month, archive_url)
    return metadata
