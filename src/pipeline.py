"""Coordinate downloading, parsing, and storing Chess.com games."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src import config
from src.chess_com import client, parser
from src.gcp import bigquery as bq
from src.gcp import gcs

logger = logging.getLogger(__name__)


def process_game(
    game: Dict[str, Any],
    month_metadata: Dict[str, Any],
    year: int,
    month: int,
) -> bool:
    """Process a single Chess.com game.

    Args:
        game (Dict[str, Any]): Raw game payload returned by the Chess.com API.
        month_metadata (Dict[str, Any]): Monthly metadata dictionary for deduplication.
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        game_processed (bool): True when the game is successfully handled or already
            processed.
    """
    uuid = game.get("uuid")
    pgn = game.get("pgn")

    if not uuid or not str(uuid).strip():
        logger.warning("Skipping invalid game: missing uuid")
        game_processed = False
        return game_processed
    if not pgn or not str(pgn).strip():
        logger.warning("Skipping game %s: missing pgn", uuid)
        game_processed = False
        return game_processed

    uuid = str(uuid).strip()

    if gcs.is_game_processed(month_metadata, uuid):
        logger.debug("Skipping already processed game: %s", uuid)
        game_processed = True
        return game_processed

    if bq.game_artifacts_exist(uuid, year, month):
        logger.debug("Skipping already stored game: %s", uuid)
        gcs.record_processed_game(month_metadata, uuid)
        game_processed = True
        return game_processed

    parsed = parser.parse_game(game)
    if parsed is None:
        if parser.is_missing_link_tag(game):
            gcs.save_missing_link_pgn(game, year, month)
        game_processed = False
        return game_processed

    try:
        gcs.upload_pgn(parsed, year, month)
        bq.insert_game(parsed, year, month)
    except Exception:
        logger.exception("Failed cloud write for game %s", uuid)
        game_processed = False
        return game_processed

    gcs.record_processed_game(month_metadata, uuid)
    game_processed = True
    return game_processed


def _partition_raw_games(
    monthly_games: List[Dict[str, Any]],
    month_metadata: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """Split raw games into skipped, missing-link, and candidate buckets."""
    missing_link_games = []
    candidate_games = []
    skipped_games = 0
    for game in monthly_games:
        uuid = game.get("uuid")
        if not uuid or not str(uuid).strip():
            logger.warning("Skipping invalid game: missing uuid")
            continue
        uuid = str(uuid).strip()
        if gcs.is_game_processed(month_metadata, uuid):
            skipped_games += 1
            continue
        pgn = game.get("pgn")
        if not pgn or not str(pgn).strip():
            logger.warning("Skipping game %s: missing pgn", uuid)
            continue
        if parser.is_missing_link_tag(game):
            missing_link_games.append(game)
            continue
        candidate_games.append(game)
    return missing_link_games, candidate_games, skipped_games


def _parse_candidate_games(
    candidate_games: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, str]], int]:
    """Parse candidate games and count parse failures."""
    parsed_games = []
    parse_failures = 0
    for game in candidate_games:
        parsed = parser.parse_game(game)
        if parsed is None:
            parse_failures += 1
            continue
        parsed_games.append(parsed)
    return parsed_games, parse_failures


def _persist_parsed_games(
    parsed_games: List[Dict[str, str]],
    month_metadata: Dict[str, Any],
    year: int,
    month: int,
) -> Tuple[int, int]:
    """Upload PGNs concurrently and insert BigQuery rows in batches."""
    if not parsed_games:
        processed = 0
        failed = 0
        return processed, failed

    uuids = []
    for game in parsed_games:
        uuids.append(game["uuid"])

    existing_pgn_uuids = gcs.list_existing_pgn_uuids(year, month)
    existing_bq_uuids = bq.existing_uuids(uuids)

    already_complete = []
    games_needing_pgn = []
    games_needing_bq = []
    for game in parsed_games:
        uuid = game["uuid"]
        pgn_ready = uuid in existing_pgn_uuids
        bq_ready = uuid in existing_bq_uuids
        if pgn_ready and bq_ready:
            already_complete.append(uuid)
            continue
        if not pgn_ready:
            games_needing_pgn.append(game)
        if not bq_ready:
            games_needing_bq.append(game)

    for uuid in already_complete:
        gcs.record_processed_game(month_metadata, uuid)

    pgn_ok_uuids = gcs.upload_pgns_concurrent(games_needing_pgn, year, month)
    for game in games_needing_bq:
        uuid = game["uuid"]
        if uuid in existing_pgn_uuids:
            pgn_ok_uuids.add(uuid)

    bq_candidates = []
    for game in games_needing_bq:
        if game["uuid"] in pgn_ok_uuids:
            bq_candidates.append(game)

    bq_ok_uuids = bq.insert_games(bq_candidates, year, month)

    newly_complete = []
    for game in parsed_games:
        uuid = game["uuid"]
        if uuid in already_complete:
            continue
        pgn_ok = uuid in pgn_ok_uuids or uuid in existing_pgn_uuids
        bq_ok = uuid in bq_ok_uuids or uuid in existing_bq_uuids
        if pgn_ok and bq_ok:
            newly_complete.append(uuid)
            gcs.record_processed_game(month_metadata, uuid)

    processed = len(already_complete) + len(newly_complete)
    failed = len(parsed_games) - processed
    return processed, failed


def process_month(
    archive_url: str,
    current_year: int,
    current_month: int,
    player: str,
    month_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """Process one monthly archive using batched GCS and BigQuery writes.

    Args:
        archive_url (str): Chess.com monthly archive URL.
        current_year (int): Current UTC year.
        current_month (int): Current UTC month.
        player (str): Chess.com username.
        month_metadata (Optional[Dict[str, Any]]): Preloaded metadata for the archive month.

    Returns:
        month_result (Dict[str, int]): Counters for processed, failed, and skipped games.
    """
    year, month = parser.parse_archive_year_month(archive_url)
    is_current_month = (year, month) == (current_year, current_month)

    if month_metadata is None:
        month_metadata = gcs.ensure_month_metadata(
            player, year, month, archive_url
        )

    logger.info("Processing archive: %s", archive_url)
    monthly_games = client.get_monthly_games(archive_url)

    missing_link_games, candidate_games, skipped_games = _partition_raw_games(
        monthly_games,
        month_metadata,
    )

    if missing_link_games:
        gcs.save_missing_link_pgns_concurrent(missing_link_games, year, month)

    parsed_games, parse_failures = _parse_candidate_games(candidate_games)
    processed, write_failures = _persist_parsed_games(
        parsed_games,
        month_metadata,
        year,
        month,
    )
    failed = len(missing_link_games) + parse_failures + write_failures

    if not is_current_month and failed == 0:
        month_metadata["is_complete"] = True
    else:
        month_metadata["is_complete"] = False

    gcs.save_month_metadata(month_metadata)

    month_result = {
        "processed": processed,
        "failed": failed,
        "skipped_games": skipped_games,
    }
    return month_result


def select_archive_urls(
    archive_urls: List[str],
    last_year: Optional[int],
    last_month: Optional[int],
    current_year: int,
    current_month: int,
) -> List[str]:
    """Select archive URLs to process based on the last executed month.

    Args:
        archive_urls (List[str]): All available archive URLs for the player.
        last_year (Optional[int]): Year from the last executed master metadata record.
        last_month (Optional[int]): Month from the last executed master metadata record.
        current_year (int): Current UTC year.
        current_month (int): Current UTC month.

    Returns:
        selected_archives (List[str]): Archive URLs from the last executed month through
            the current month.
    """
    dated_archives = []
    for archive_url in archive_urls:
        archive_year, archive_month = parser.parse_archive_year_month(archive_url)
        dated_archives.append((archive_url, archive_year, archive_month))
    dated_archives.sort(key=lambda item: (item[1], item[2]))
    current = (current_year, current_month)

    if last_year is None or last_month is None:
        if dated_archives:
            start = (dated_archives[0][1], dated_archives[0][2])
        else:
            start = current
    elif current > (last_year, last_month):
        start = (last_year, last_month)
    else:
        start = current

    selected_archives = []
    for archive_url, year, month in dated_archives:
        if start <= (year, month) <= current:
            selected_archives.append(archive_url)
    return selected_archives


def run_pipeline() -> Dict[str, int]:
    """Run the incremental download and cloud persistence workflow.

    Returns:
        pipeline_totals (Dict[str, int]): Summary counters for processed months and games.
    """
    player = config.PLAYER
    gcs.ensure_bucket()
    bq.ensure_dataset_and_table()

    now = datetime.now(timezone.utc)
    current_year = now.year
    current_month = now.month

    master_metadata = gcs.load_master_metadata()
    if master_metadata is None:
        master_metadata = gcs.create_master_metadata()
    last_year = master_metadata.get("last_metadata_year")
    last_month = master_metadata.get("last_metadata_month")

    last_month_metadata = None
    if last_year is not None and last_month is not None:
        last_month_metadata = gcs.load_month_metadata(last_year, last_month)
        if last_month_metadata:
            logger.info(
                "Loaded last executed month metadata: %04d-%02d",
                last_year,
                last_month,
            )

    archive_urls = client.get_archive_urls(player)
    archives_to_process = select_archive_urls(
        archive_urls,
        last_year,
        last_month,
        current_year,
        current_month,
    )

    if not archives_to_process:
        logger.info("No archives to process")
        gcs.update_master_metadata(master_metadata, current_year, current_month)
        gcs.save_master_metadata(master_metadata)
        empty_totals = {
            "months_processed": 0,
            "games_processed": 0,
            "games_failed": 0,
            "games_skipped": 0,
        }
        return empty_totals

    logger.info(
        "Processing %d archive(s) from last executed month through current month",
        len(archives_to_process),
    )

    totals = {
        "months_processed": 0,
        "games_processed": 0,
        "games_failed": 0,
        "games_skipped": 0,
    }

    archive_items = archives_to_process
    for archive_url in archive_items:
        year, month = parser.parse_archive_year_month(archive_url)
        preloaded = None
        if (
            last_year is not None
            and last_month is not None
            and (year, month) == (last_year, last_month)
        ):
            preloaded = last_month_metadata

        result = process_month(
            archive_url,
            current_year,
            current_month,
            player,
            month_metadata=preloaded,
        )
        totals["months_processed"] += 1
        totals["games_processed"] += result["processed"]
        totals["games_failed"] += result["failed"]
        totals["games_skipped"] += result["skipped_games"]

    gcs.update_master_metadata(master_metadata, current_year, current_month)
    gcs.save_master_metadata(master_metadata)

    logger.info(
        "Pipeline complete: months_processed=%d, "
        "games_processed=%d, games_failed=%d, games_skipped=%d",
        totals["months_processed"],
        totals["games_processed"],
        totals["games_failed"],
        totals["games_skipped"],
    )
    pipeline_totals = totals
    return pipeline_totals
