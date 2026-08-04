"""Google Cloud Storage persistence for PGN files and metadata."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage
from google.cloud.exceptions import NotFound

from src import config

logger = logging.getLogger(__name__)

GCS_UPLOAD_WORKERS = 32

_storage_client = None
_bucket = None


def reset_gcs_clients() -> None:
    """Clear cached Storage client and bucket references."""
    global _storage_client, _bucket
    _storage_client = None
    _bucket = None


def get_storage_client() -> storage.Client:
    """Return a cached Storage client for the configured project.

    Returns:
        storage_client (storage.Client): Authenticated Google Cloud Storage client.
    """
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client(project=config.GCP_PROJECT_ID)
    storage_client = _storage_client
    return storage_client


def build_bucket_name(
    base_bucket_name: str, project_number: str, location: str
) -> str:
    """Build the final GCS bucket name from configuration parts.

    Args:
        base_bucket_name (str): Base bucket name prefix.
        project_number (str): GCP project number.
        location (str): Bucket location.

    Returns:
        bucket_name (str): Fully constructed bucket name.
    """
    bucket_name = f"{base_bucket_name}-{project_number}-{location}"
    return bucket_name


def pgn_object_path(year: int, month: int, uuid: str) -> str:
    """Return the GCS object path for a game PGN.

    Args:
        year (int): Archive year.
        month (int): Archive month.
        uuid (str): Chess.com game UUID.

    Returns:
        object_path (str): Object path inside the configured bucket.
    """
    object_path = f"pgns/{year:04d}-{month:02d}-{uuid}.pgn"
    return object_path


def metadata_object_path(year: int, month: int) -> str:
    """Return the GCS object path for monthly metadata.

    Args:
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        object_path (str): Object path inside the configured bucket.
    """
    object_path = f"metadata/{year:04d}-{month:02d}.json"
    return object_path


def master_metadata_object_path() -> str:
    """Return the GCS object path for master metadata."""
    object_path = "metadata/master.json"
    return object_path


def missing_link_object_path(year: int, month: int, uuid: str) -> str:
    """Return the GCS object path for a missing-link review PGN."""
    object_path = f"temp/missing-link/{year:04d}-{month:02d}-{uuid}.pgn"
    return object_path


def ensure_bucket() -> storage.Bucket:
    """Create the configured bucket when missing and return it.

    Returns:
        bucket (storage.Bucket): Existing or newly created bucket.
    """
    global _bucket
    if _bucket is not None:
        cached_bucket = _bucket
        return cached_bucket

    client = get_storage_client()
    bucket_name = config.GCS_BUCKET_NAME
    try:
        bucket = client.get_bucket(bucket_name)
        logger.info("Using existing GCS bucket: %s", bucket_name)
    except NotFound:
        bucket = client.create_bucket(bucket_name, location=config.LOCATION)
        logger.info("Created GCS bucket: %s in %s", bucket_name, config.LOCATION)

    _bucket = bucket
    return bucket


def object_exists(object_path: str) -> bool:
    """Check whether a GCS object exists.

    Args:
        object_path (str): Object path inside the configured bucket.

    Returns:
        exists (bool): True when the object exists.
    """
    bucket = ensure_bucket()
    exists = bucket.blob(object_path).exists()
    return exists


def pgn_exists(uuid: str, year: int, month: int) -> bool:
    """Check whether a game PGN object exists in GCS.

    Args:
        uuid (str): Chess.com game UUID.
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        exists (bool): True when the PGN object exists.
    """
    exists = object_exists(pgn_object_path(year, month, uuid))
    return exists


def list_existing_pgn_uuids(year: int, month: int) -> Set[str]:
    """List UUIDs that already have a PGN object for a month.

    Args:
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        existing_uuids (Set[str]): UUIDs found under the month PGN prefix.
    """
    bucket = ensure_bucket()
    prefix = f"pgns/{year:04d}-{month:02d}-"
    existing_uuids = set()
    month_blobs = bucket.list_blobs(prefix=prefix)
    for blob in month_blobs:
        name = blob.name
        if not name.startswith(prefix) or not name.endswith(".pgn"):
            continue
        uuid = name[len(prefix) : -len(".pgn")]
        if uuid:
            existing_uuids.add(uuid)
    return existing_uuids


def upload_pgn(game_data: Dict[str, str], year: int, month: int) -> str:
    """Upload a game PGN to GCS, skipping rewrite when the object already exists.

    Args:
        game_data (Dict[str, str]): Normalized game data including original PGN text.
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        object_path (str): GCS object path for the PGN.
    """
    uuid = game_data["uuid"]
    object_path = pgn_object_path(year, month, uuid)
    bucket = ensure_bucket()
    blob = bucket.blob(object_path)
    try:
        blob.upload_from_string(
            game_data["pgn"],
            content_type="text/plain; charset=utf-8",
            if_generation_match=0,
        )
        logger.info("Uploaded PGN object: %s", object_path)
    except PreconditionFailed:
        logger.debug("PGN object already exists: %s", object_path)
    return object_path


def _upload_pgn_task(game_data: Dict[str, str], year: int, month: int) -> Tuple[str, bool, str]:
    """Upload one PGN and return uuid, success flag, and error message."""
    uuid = game_data["uuid"]
    try:
        upload_pgn(game_data, year, month)
        upload_result = (uuid, True, "")
        return upload_result
    except Exception as exc:
        upload_result = (uuid, False, str(exc))
        return upload_result


def upload_pgns_concurrent(
    games_data: List[Dict[str, str]],
    year: int,
    month: int,
    max_workers: int = GCS_UPLOAD_WORKERS,
) -> Set[str]:
    """Upload many PGN objects concurrently.

    Args:
        games_data (List[Dict[str, str]]): Normalized games including PGN text.
        year (int): Archive year.
        month (int): Archive month.
        max_workers (int): Maximum concurrent upload workers.

    Returns:
        uploaded_uuids (Set[str]): UUIDs whose upload succeeded or already existed.
    """
    if not games_data:
        uploaded_uuids = set()
        return uploaded_uuids

    uploaded_uuids = set()
    worker_count = min(max_workers, len(games_data))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = []
        for game_data in games_data:
            futures.append(executor.submit(_upload_pgn_task, game_data, year, month))
        future_items = as_completed(futures)
        for future in future_items:
            uuid, succeeded, error_message = future.result()
            if succeeded:
                uploaded_uuids.add(uuid)
                continue
            logger.error("Failed PGN upload for %s: %s", uuid, error_message)
    logger.info(
        "Uploaded %d/%d PGN object(s) for %04d-%02d",
        len(uploaded_uuids),
        len(games_data),
        year,
        month,
    )
    return uploaded_uuids


def save_missing_link_pgn(game: Dict[str, Any], year: int, month: int) -> str:
    """Upload a PGN for a game missing the required Link tag.

    Args:
        game (Dict[str, Any]): Raw game payload including PGN text.
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        object_path (str): GCS object path used for review.
    """
    uuid = str(game.get("uuid", "unknown")).strip()
    object_path = missing_link_object_path(year, month, uuid)
    bucket = ensure_bucket()
    blob = bucket.blob(object_path)
    blob.upload_from_string(
        game.get("pgn", ""), content_type="text/plain; charset=utf-8"
    )
    logger.warning("Saved game with missing Link tag for review: %s", object_path)
    return object_path


def save_missing_link_pgns_concurrent(
    games: Iterable[Dict[str, Any]],
    year: int,
    month: int,
    max_workers: int = GCS_UPLOAD_WORKERS,
) -> None:
    """Upload many missing-link review PGNs concurrently.

    Args:
        games (Iterable[Dict[str, Any]]): Raw game payloads missing Link tags.
        year (int): Archive year.
        month (int): Archive month.
        max_workers (int): Maximum concurrent upload workers.
    """
    game_items = list(games)
    if not game_items:
        return

    worker_count = min(max_workers, len(game_items))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = []
        for game in game_items:
            futures.append(
                executor.submit(save_missing_link_pgn, game, year, month)
            )
        future_items = as_completed(futures)
        for future in future_items:
            future.result()


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


def _read_json_object(object_path: str) -> Optional[Dict[str, Any]]:
    """Read a JSON object from GCS, returning None when missing."""
    bucket = ensure_bucket()
    blob = bucket.blob(object_path)
    if not blob.exists():
        loaded_metadata = None
        return loaded_metadata
    loaded_metadata = json.loads(blob.download_as_text(encoding="utf-8"))
    return loaded_metadata


def _write_json_object(object_path: str, payload: Dict[str, Any]) -> str:
    """Write a JSON object to GCS, replacing any existing object."""
    bucket = ensure_bucket()
    blob = bucket.blob(object_path)
    content = json.dumps(payload, indent=2) + "\n"
    blob.upload_from_string(content, content_type="application/json; charset=utf-8")
    saved_object_path = object_path
    return saved_object_path


def load_month_metadata(year: int, month: int) -> Optional[Dict[str, Any]]:
    """Load metadata for a month from GCS.

    Args:
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        loaded_metadata (Optional[Dict[str, Any]]): Loaded metadata dictionary, or
            None when no object exists.
    """
    loaded_metadata = _read_json_object(metadata_object_path(year, month))
    return loaded_metadata


def load_master_metadata() -> Optional[Dict[str, Any]]:
    """Load master metadata from GCS.

    Returns:
        loaded_master (Optional[Dict[str, Any]]): Loaded master metadata dictionary, or
            None when no object exists.
    """
    loaded_master = _read_json_object(master_metadata_object_path())
    return loaded_master


def save_month_metadata(metadata: Dict[str, Any]) -> str:
    """Save monthly metadata to GCS.

    Args:
        metadata (Dict[str, Any]): Monthly metadata dictionary to persist.

    Returns:
        saved_object_path (str): GCS object path for the saved metadata.
    """
    object_path = metadata_object_path(metadata["year"], metadata["month"])
    saved_object_path = _write_json_object(object_path, metadata)
    logger.info("Updated metadata object: %s", saved_object_path)
    return saved_object_path


def save_master_metadata(metadata: Dict[str, Any]) -> str:
    """Save master metadata to GCS.

    Args:
        metadata (Dict[str, Any]): Master metadata dictionary to persist.

    Returns:
        saved_object_path (str): GCS object path for the saved master metadata.
    """
    object_path = master_metadata_object_path()
    saved_object_path = _write_json_object(object_path, metadata)
    logger.info("Updated master metadata object: %s", saved_object_path)
    return saved_object_path


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
