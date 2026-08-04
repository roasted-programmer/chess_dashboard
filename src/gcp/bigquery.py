"""BigQuery persistence for structured game rows."""

import logging
import time
from typing import Dict, Iterable, List, Set

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from src import config
from src.gcp import gcs

logger = logging.getLogger(__name__)

GAME_COLUMNS = [
    "uuid",
    "white_username",
    "black_username",
    "result",
    "rules",
    "opening",
    "main_opening",
    "opening_variant",
    "opening_subvariant",
    "game_url",
    "utc_date",
    "utc_time",
    "white_elo",
    "black_elo",
    "time_control",
    "termination",
    "pgn_file",
]

BQ_INSERT_BATCH_SIZE = 500
BQ_LOOKUP_BATCH_SIZE = 1000

_bq_client = None


def reset_bq_client() -> None:
    """Clear the cached BigQuery client."""
    global _bq_client
    _bq_client = None


def get_bq_client() -> bigquery.Client:
    """Return a cached BigQuery client for the configured project.

    Returns:
        bq_client (bigquery.Client): Authenticated BigQuery client.
    """
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=config.GCP_PROJECT_ID)
    bq_client = _bq_client
    return bq_client


def games_table_schema() -> List[bigquery.SchemaField]:
    """Return the explicit BigQuery schema for the games table.

    Returns:
        schema_fields (List[bigquery.SchemaField]): Schema matching the former CSV columns.
    """
    schema_fields = [
        bigquery.SchemaField("uuid", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("white_username", "STRING"),
        bigquery.SchemaField("black_username", "STRING"),
        bigquery.SchemaField("result", "STRING"),
        bigquery.SchemaField("rules", "STRING"),
        bigquery.SchemaField("opening", "STRING"),
        bigquery.SchemaField("main_opening", "STRING"),
        bigquery.SchemaField("opening_variant", "STRING"),
        bigquery.SchemaField("opening_subvariant", "STRING"),
        bigquery.SchemaField("game_url", "STRING"),
        bigquery.SchemaField("utc_date", "STRING"),
        bigquery.SchemaField("utc_time", "STRING"),
        bigquery.SchemaField("white_elo", "STRING"),
        bigquery.SchemaField("black_elo", "STRING"),
        bigquery.SchemaField("time_control", "STRING"),
        bigquery.SchemaField("termination", "STRING"),
        bigquery.SchemaField("pgn_file", "STRING"),
    ]
    return schema_fields


def ensure_dataset_and_table() -> str:
    """Create the dataset and games table when missing.

    Returns:
        table_id (str): Fully qualified BigQuery table identifier.
    """
    client = get_bq_client()
    dataset_id = f"{config.GCP_PROJECT_ID}.{config.BQ_DATASET_NAME}"
    table_id = config.BQ_TABLE_ID

    dataset = bigquery.Dataset(dataset_id)
    dataset.location = config.LOCATION
    client.create_dataset(dataset, exists_ok=True)
    logger.info("Ensured BigQuery dataset: %s", dataset_id)

    table = bigquery.Table(table_id, schema=games_table_schema())
    client.create_table(table, exists_ok=True)
    # Streaming inserts can 404 briefly after table creation.
    readiness_attempts = range(10)
    for attempt in readiness_attempts:
        try:
            client.get_table(table_id)
            break
        except NotFound:
            time.sleep(1)
    else:
        raise RuntimeError(f"BigQuery table not ready after creation: {table_id}")
    logger.info("Ensured BigQuery table: %s", table_id)
    return table_id


def build_game_row(game_data: Dict[str, str], year: int, month: int) -> Dict[str, str]:
    """Build a BigQuery row dictionary from normalized game data.

    Args:
        game_data (Dict[str, str]): Normalized game data.
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        row (Dict[str, str]): Row payload ready for insertion.
    """
    row = {}
    for column in GAME_COLUMNS:
        if column == "pgn_file":
            row[column] = gcs.pgn_object_path(year, month, game_data["uuid"])
            continue
        row[column] = game_data.get(column, "")
    return row


def existing_uuids(uuids: Iterable[str]) -> Set[str]:
    """Return the subset of UUIDs that already exist in BigQuery.

    Args:
        uuids (Iterable[str]): Candidate Chess.com game UUIDs.

    Returns:
        found_uuids (Set[str]): UUIDs already present in the games table.
    """
    candidate_uuids = []
    for uuid in uuids:
        cleaned = str(uuid).strip()
        if cleaned:
            candidate_uuids.append(cleaned)
    if not candidate_uuids:
        found_uuids = set()
        return found_uuids

    client = get_bq_client()
    found_uuids = set()
    total = len(candidate_uuids)
    for start in range(0, total, BQ_LOOKUP_BATCH_SIZE):
        batch = candidate_uuids[start : start + BQ_LOOKUP_BATCH_SIZE]
        query = (
            f"SELECT uuid FROM `{config.BQ_TABLE_ID}` "
            "WHERE uuid IN UNNEST(@uuids)"
        )
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("uuids", "STRING", batch),
            ]
        )
        results = client.query(query, job_config=job_config).result()
        for row in results:
            found_uuids.add(row["uuid"])
    return found_uuids


def game_exists(uuid: str) -> bool:
    """Check whether a game UUID already exists in the BigQuery table.

    Args:
        uuid (str): Chess.com game UUID.

    Returns:
        exists (bool): True when a matching row is found.
    """
    found_uuids = existing_uuids([uuid])
    exists = uuid in found_uuids
    return exists


def insert_games(
    games_data: List[Dict[str, str]],
    year: int,
    month: int,
    batch_size: int = BQ_INSERT_BATCH_SIZE,
) -> Set[str]:
    """Insert many game rows into BigQuery in batches.

    Args:
        games_data (List[Dict[str, str]]): Normalized game data rows.
        year (int): Archive year.
        month (int): Archive month.
        batch_size (int): Maximum rows per streaming insert request.

    Returns:
        inserted_uuids (Set[str]): UUIDs successfully accepted by BigQuery.
    """
    if not games_data:
        inserted_uuids = set()
        return inserted_uuids

    client = get_bq_client()
    inserted_uuids = set()
    total = len(games_data)
    for start in range(0, total, batch_size):
        batch = games_data[start : start + batch_size]
        rows = []
        row_ids = []
        for game_data in batch:
            rows.append(build_game_row(game_data, year, month))
            row_ids.append(game_data["uuid"])

        errors = None
        insert_attempts = range(8)
        for attempt in insert_attempts:
            try:
                errors = client.insert_rows_json(
                    config.BQ_TABLE_ID,
                    rows,
                    row_ids=row_ids,
                )
                break
            except NotFound:
                logger.warning(
                    "BigQuery table not ready for insert (attempt %d); retrying",
                    attempt + 1,
                )
                time.sleep(2)
        if errors is None:
            raise RuntimeError(
                f"BigQuery table not found for inserts: {config.BQ_TABLE_ID}"
            )

        failed_indexes = set()
        if errors:
            for error in errors:
                index = error.get("index")
                if index is None:
                    failed_indexes = set(range(len(batch)))
                    logger.error("BigQuery insert batch error: %s", error)
                    break
                failed_indexes.add(index)
                logger.error(
                    "BigQuery insert error for %s: %s",
                    row_ids[index],
                    error.get("errors"),
                )

        batch_indexes = range(len(batch))
        for index in batch_indexes:
            if index in failed_indexes:
                continue
            inserted_uuids.add(row_ids[index])

    logger.info(
        "Inserted %d/%d game row(s) into BigQuery for %04d-%02d",
        len(inserted_uuids),
        len(games_data),
        year,
        month,
    )
    return inserted_uuids


def insert_game(game_data: Dict[str, str], year: int, month: int) -> None:
    """Insert one game row into BigQuery, skipping when the UUID already exists.

    Args:
        game_data (Dict[str, str]): Normalized game data.
        year (int): Archive year.
        month (int): Archive month.

    Raises:
        RuntimeError: If BigQuery reports insert errors.
    """
    uuid = game_data["uuid"]
    if game_exists(uuid):
        logger.debug("Game already in BigQuery: %s", uuid)
        return

    inserted_uuids = insert_games([game_data], year, month)
    if uuid not in inserted_uuids:
        raise RuntimeError(f"BigQuery insert failed for {uuid}")


def game_artifacts_exist(uuid: str, year: int, month: int) -> bool:
    """Check whether both the PGN object and BigQuery row exist for a game.

    Args:
        uuid (str): Chess.com game UUID.
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        artifacts_exist (bool): True when both cloud artifacts are present.
    """
    artifacts_exist = gcs.pgn_exists(uuid, year, month) and game_exists(uuid)
    return artifacts_exist
