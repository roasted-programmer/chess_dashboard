"""Monthly and master processing metadata persistence."""

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.config import METADATA_DIR

logger = logging.getLogger(__name__)

MASTER_METADATA_PATH = METADATA_DIR / "master.json"


def metadata_path(year: int, month: int) -> Path:
    """Return the filesystem path for a monthly metadata file.

    Args:
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        metadata_file_path (Path): Absolute path to the monthly metadata JSON file.
    """
    metadata_file_path = METADATA_DIR / f"{year:04d}-{month:02d}.json"
    return metadata_file_path


def create_month_metadata(
    player: str, year: int, month: int, archive_url: str
) -> Dict[str, Any]:
    """Create a new monthly metadata record.

    Args:
        player (str): Chess.com username.
        year (int): Archive year.
        month (int): Archive month.
        archive_url (str): Chess.com monthly archive URL.

    Returns:
        month_metadata (Dict[str, Any]): Initialized monthly metadata dictionary.
    """
    month_metadata = {
        "player": player,
        "year": year,
        "month": month,
        "archive_url": archive_url,
        "processed_game_uuids": [],
        "game_count": 0,
        "last_updated_at": None,
        "is_complete": False,
    }
    return month_metadata


def create_master_metadata() -> Dict[str, Any]:
    """Create a new master metadata record.

    Returns:
        master_metadata (Dict[str, Any]): Initialized master metadata dictionary.
    """
    master_metadata = {
        "last_run_at": None,
        "last_metadata_year": None,
        "last_metadata_month": None,
        "last_metadata_file": None,
    }
    return master_metadata


def load_month_metadata(year: int, month: int) -> Optional[Dict[str, Any]]:
    """Load metadata for a month.

    Args:
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        loaded_metadata (Optional[Dict[str, Any]]): Loaded metadata dictionary, or
            None when no file exists.
    """
    path = metadata_path(year, month)
    if not path.is_file():
        loaded_metadata = None
        return loaded_metadata
    with path.open(encoding="utf-8") as handle:
        loaded_metadata = json.load(handle)
    return loaded_metadata


def load_master_metadata() -> Optional[Dict[str, Any]]:
    """Load master metadata.

    Returns:
        loaded_master (Optional[Dict[str, Any]]): Loaded master metadata dictionary, or
            None when no file exists.
    """
    if not MASTER_METADATA_PATH.is_file():
        loaded_master = None
        return loaded_master
    with MASTER_METADATA_PATH.open(encoding="utf-8") as handle:
        loaded_master = json.load(handle)
    return loaded_master


def _save_json_atomically(path: Path, payload: Dict[str, Any]) -> Path:
    """Write JSON payload to disk using an atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2) + "\n"

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as temp_handle:
        temp_handle.write(content)
        temp_handle.flush()
        temp_path = Path(temp_handle.name)

    temp_path.replace(path)
    saved_path = path
    return saved_path


def save_month_metadata(metadata: Dict[str, Any]) -> Path:
    """Save monthly metadata atomically.

    Args:
        metadata (Dict[str, Any]): Monthly metadata dictionary to persist.

    Returns:
        saved_metadata_path (Path): Path to the saved metadata file.
    """
    path = metadata_path(metadata["year"], metadata["month"])
    _save_json_atomically(path, metadata)
    logger.info("Updated metadata: %s", path)
    saved_metadata_path = path
    return saved_metadata_path


def save_master_metadata(metadata: Dict[str, Any]) -> Path:
    """Save master metadata atomically.

    Args:
        metadata (Dict[str, Any]): Master metadata dictionary to persist.

    Returns:
        saved_master_path (Path): Path to the saved master metadata file.
    """
    path = _save_json_atomically(MASTER_METADATA_PATH, metadata)
    logger.info("Updated master metadata: %s", path)
    saved_master_path = path
    return saved_master_path


def is_game_processed(metadata: Dict[str, Any], uuid: str) -> bool:
    """Check whether a game UUID is recorded in monthly metadata.

    Args:
        metadata (Dict[str, Any]): Monthly metadata dictionary.
        uuid (str): Chess.com game UUID.

    Returns:
        is_processed (bool): True when the UUID has already been processed for the month.
    """
    is_processed = uuid in metadata.get("processed_game_uuids", [])
    return is_processed


def record_processed_game(metadata: Dict[str, Any], uuid: str) -> None:
    """Record a successfully processed game UUID without duplicates.

    Args:
        metadata (Dict[str, Any]): Monthly metadata dictionary to update.
        uuid (str): Chess.com game UUID to record.
    """
    processed = metadata.setdefault("processed_game_uuids", [])
    if uuid not in processed:
        processed.append(uuid)
    metadata["game_count"] = len(processed)
    metadata["last_updated_at"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def ensure_month_metadata(
    player: str, year: int, month: int, archive_url: str
) -> Dict[str, Any]:
    """Load existing metadata or initialize a new monthly record.

    Args:
        player (str): Chess.com username.
        year (int): Archive year.
        month (int): Archive month.
        archive_url (str): Chess.com monthly archive URL.

    Returns:
        resolved_metadata (Dict[str, Any]): Existing or newly created monthly metadata.
    """
    month_metadata = load_month_metadata(year, month)
    if month_metadata is None:
        month_metadata = create_month_metadata(player, year, month, archive_url)
    resolved_metadata = month_metadata
    return resolved_metadata


def update_master_metadata(
    master: Dict[str, Any], year: int, month: int
) -> Dict[str, Any]:
    """Update master metadata with the latest run and month processed.

    Args:
        master (Dict[str, Any]): Master metadata dictionary to update.
        year (int): Last processed archive year.
        month (int): Last processed archive month.

    Returns:
        updated_master (Dict[str, Any]): Updated master metadata dictionary.
    """
    master["last_run_at"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    master["last_metadata_year"] = year
    master["last_metadata_month"] = month
    master["last_metadata_file"] = f"{year:04d}-{month:02d}"
    updated_master = master
    return updated_master
