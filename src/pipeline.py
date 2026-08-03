"""Coordinate downloading, parsing, and storing Chess.com games."""

import logging
from datetime import datetime, timezone

from src import config
from src.chess_com import client, parser
from src.local_storage import games, metadata

logger = logging.getLogger(__name__)


def process_game(
    game: dict,
    month_metadata: dict,
    year: int,
    month: int,
) -> bool:
    """
    Process a single game.

    Returns True when the game is successfully handled (processed or already done).
    """
    uuid = game.get("uuid")
    pgn = game.get("pgn")

    if not uuid or not str(uuid).strip():
        logger.warning("Skipping invalid game: missing uuid")
        return False
    if not pgn or not str(pgn).strip():
        logger.warning("Skipping game %s: missing pgn", uuid)
        return False

    uuid = str(uuid).strip()

    if metadata.is_game_processed(month_metadata, uuid):
        logger.debug("Skipping already processed game: %s", uuid)
        return True

    if games.game_files_exist(uuid, year, month):
        logger.info("Recording existing files for game: %s", uuid)
        metadata.record_processed_game(month_metadata, uuid)
        return True

    parsed = parser.parse_game(game)
    if parsed is None:
        return False

    games.write_pgn_file(parsed, year, month)
    games.write_game_csv(parsed, year, month)
    metadata.record_processed_game(month_metadata, uuid)
    return True


def process_month(
    archive_url: str,
    current_year: int,
    current_month: int,
    player: str,
) -> dict[str, int]:
    """Process one monthly archive and return per-month counters."""
    year, month = parser.parse_archive_year_month(archive_url)
    is_historical = (year, month) < (current_year, current_month)

    month_metadata = metadata.ensure_month_metadata(
        player, year, month, archive_url
    )

    if is_historical and month_metadata.get("is_complete"):
        logger.info("Skipping completed historical month: %04d-%02d", year, month)
        return {
            "skipped_month": 1,
            "processed": 0,
            "failed": 0,
            "skipped_games": 0,
        }

    logger.info("Processing archive: %s", archive_url)
    api_games = client.get_monthly_games(archive_url)

    processed = 0
    failed = 0
    skipped_games = 0

    for game in api_games:
        uuid = game.get("uuid")
        if uuid and metadata.is_game_processed(month_metadata, str(uuid).strip()):
            skipped_games += 1
            continue

        if process_game(game, month_metadata, year, month):
            processed += 1
        else:
            failed += 1

    if is_historical and failed == 0:
        month_metadata["is_complete"] = True
    else:
        month_metadata["is_complete"] = False

    metadata.save_month_metadata(month_metadata)

    return {
        "skipped_month": 0,
        "processed": processed,
        "failed": failed,
        "skipped_games": skipped_games,
    }


def run_pipeline() -> dict[str, int]:
    """Run the full incremental download and storage workflow."""
    player = config.PLAYER
    games.ensure_data_directories()

    now = datetime.now(timezone.utc)
    current_year = now.year
    current_month = now.month

    archive_urls = client.get_archive_urls(player)
    archive_urls.sort(
        key=lambda url: parser.parse_archive_year_month(url)
    )

    totals = {
        "months_processed": 0,
        "months_skipped": 0,
        "games_processed": 0,
        "games_failed": 0,
        "games_skipped": 0,
    }

    for archive_url in archive_urls:
        result = process_month(
            archive_url, current_year, current_month, player
        )
        if result["skipped_month"]:
            totals["months_skipped"] += 1
        else:
            totals["months_processed"] += 1
            totals["games_processed"] += result["processed"]
            totals["games_failed"] += result["failed"]
            totals["games_skipped"] += result["skipped_games"]

    logger.info(
        "Pipeline complete: months_processed=%d, months_skipped=%d, "
        "games_processed=%d, games_failed=%d, games_skipped=%d",
        totals["months_processed"],
        totals["months_skipped"],
        totals["games_processed"],
        totals["games_failed"],
        totals["games_skipped"],
    )
    return totals
