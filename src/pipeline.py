"""Coordinate downloading, parsing, and storing Chess.com games."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src import config
from src.chess_com import client, parser
from src.local_storage import games, metadata

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

    if metadata.is_game_processed(month_metadata, uuid):
        logger.debug("Skipping already processed game: %s", uuid)
        game_processed = True
        return game_processed

    if games.game_files_exist(uuid, year, month):
        logger.debug("Skipping already stored game: %s", uuid)
        metadata.record_processed_game(month_metadata, uuid)
        game_processed = True
        return game_processed

    parsed = parser.parse_game(game)
    if parsed is None:
        if parser.is_missing_link_tag(game):
            games.save_missing_link_pgn(game, year, month)
        game_processed = False
        return game_processed

    games.write_pgn_file(parsed, year, month)
    games.append_game_csv(parsed, year, month)
    metadata.record_processed_game(month_metadata, uuid)
    game_processed = True
    return game_processed


def process_month(
    archive_url: str,
    current_year: int,
    current_month: int,
    player: str,
    month_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """Process one monthly archive.

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
        month_metadata = metadata.ensure_month_metadata(
            player, year, month, archive_url
        )

    logger.info("Processing archive: %s", archive_url)
    monthly_games = client.get_monthly_games(archive_url)

    processed = 0
    failed = 0
    skipped_games = 0

    for game in monthly_games:
        uuid = game.get("uuid")
        if uuid and metadata.is_game_processed(month_metadata, str(uuid).strip()):
            skipped_games += 1
            continue

        if process_game(game, month_metadata, year, month):
            processed += 1
        else:
            failed += 1

    if not is_current_month and failed == 0:
        month_metadata["is_complete"] = True
    else:
        month_metadata["is_complete"] = False

    metadata.save_month_metadata(month_metadata)

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
    """Run the incremental download and storage workflow.

    Returns:
        pipeline_totals (Dict[str, int]): Summary counters for processed months and games.
    """
    player = config.PLAYER
    games.ensure_data_directories()
    games.load_csv_uuids()

    now = datetime.now(timezone.utc)
    current_year = now.year
    current_month = now.month

    master_metadata = metadata.load_master_metadata()
    if master_metadata is None:
        master_metadata = metadata.create_master_metadata()
    last_year = master_metadata.get("last_metadata_year")
    last_month = master_metadata.get("last_metadata_month")

    last_month_metadata = None
    if last_year is not None and last_month is not None:
        last_month_metadata = metadata.load_month_metadata(last_year, last_month)
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
        metadata.update_master_metadata(master_metadata, current_year, current_month)
        metadata.save_master_metadata(master_metadata)
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

    for archive_url in archives_to_process:
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

    metadata.update_master_metadata(master_metadata, current_year, current_month)
    metadata.save_master_metadata(master_metadata)

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
