"""Local persistence for per-game PGN files and a consolidated CSV."""

import csv
import logging
from pathlib import Path
from typing import Dict, Set

from src.config import CSV_DIR, DATA_DIR, METADATA_DIR, PGN_DIR

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "uuid",
    "white_username",
    "black_username",
    "result",
    "variant",
    "eco_url",
    "utc_date",
    "utc_time",
    "white_elo",
    "black_elo",
    "time_control",
    "termination",
    "pgn_file",
]

GAMES_CSV_PATH = CSV_DIR / "games.csv"

_csv_uuids = None


def ensure_data_directories() -> None:
    """Create required data directories if they do not exist."""
    data_directories = (DATA_DIR, PGN_DIR, CSV_DIR, METADATA_DIR)
    for directory in data_directories:
        directory.mkdir(parents=True, exist_ok=True)


def _file_stem(year: int, month: int, uuid: str) -> str:
    """Build the shared filename stem for a game."""
    filename_stem = f"{year:04d}-{month:02d}-{uuid}"
    return filename_stem


def pgn_file_path(year: int, month: int, uuid: str) -> Path:
    """Return the filesystem path for a game's PGN file.

    Args:
        year (int): Archive year.
        month (int): Archive month.
        uuid (str): Chess.com game UUID.

    Returns:
        pgn_path (Path): Absolute path to the PGN file.
    """
    pgn_path = PGN_DIR / f"{_file_stem(year, month, uuid)}.pgn"
    return pgn_path


def pgn_relative_path(year: int, month: int, uuid: str) -> str:
    """Return the relative path for a game's PGN file.

    Args:
        year (int): Archive year.
        month (int): Archive month.
        uuid (str): Chess.com game UUID.

    Returns:
        relative_pgn_path (str): Relative path used in CSV output.
    """
    relative_pgn_path = f"data/pgns/{_file_stem(year, month, uuid)}.pgn"
    return relative_pgn_path


def load_csv_uuids() -> Set[str]:
    """Load UUIDs already present in the consolidated CSV.

    Returns:
        loaded_uuids (Set[str]): Game UUIDs found in the consolidated CSV file.
    """
    global _csv_uuids
    if _csv_uuids is not None:
        cached_uuids = _csv_uuids
        return cached_uuids

    uuids = set()
    if GAMES_CSV_PATH.is_file():
        with GAMES_CSV_PATH.open(encoding="utf-8", newline="") as handle:
            csv_reader = csv.DictReader(handle)
            for row in csv_reader:
                uuid = row.get("uuid")
                if uuid:
                    uuids.add(uuid)

    _csv_uuids = uuids
    loaded_uuids = _csv_uuids
    return loaded_uuids


def reset_csv_uuid_cache() -> None:
    """Clear the in-memory CSV UUID cache."""
    global _csv_uuids
    _csv_uuids = None


def is_game_in_csv(uuid: str) -> bool:
    """Check whether a game UUID is already recorded in the CSV.

    Args:
        uuid (str): Chess.com game UUID.

    Returns:
        game_in_csv (bool): True when the UUID exists in the consolidated CSV.
    """
    game_in_csv = uuid in load_csv_uuids()
    return game_in_csv


def game_pgn_exists(uuid: str, year: int, month: int) -> bool:
    """Check whether the PGN file exists for a game.

    Args:
        uuid (str): Chess.com game UUID.
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        pgn_exists (bool): True when the PGN file exists on disk.
    """
    pgn_exists = pgn_file_path(year, month, uuid).is_file()
    return pgn_exists


def game_files_exist(uuid: str, year: int, month: int) -> bool:
    """Check whether both PGN and CSV records exist for a game.

    Args:
        uuid (str): Chess.com game UUID.
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        files_exist (bool): True when the game is stored in both PGN and CSV outputs.
    """
    files_exist = game_pgn_exists(uuid, year, month) and is_game_in_csv(uuid)
    return files_exist


def write_pgn_file(game_data: Dict[str, str], year: int, month: int) -> Path:
    """Write a PGN file for a processed game.

    Args:
        game_data (Dict[str, str]): Normalized game data including the original PGN text.
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        pgn_path (Path): Path to the written or existing PGN file.
    """
    path = pgn_file_path(year, month, game_data["uuid"])
    if path.is_file():
        logger.debug("PGN file already exists: %s", path)
        existing_pgn_path = path
        return existing_pgn_path
    path.write_text(game_data["pgn"], encoding="utf-8")
    logger.info("Wrote PGN file: %s", path)
    written_pgn_path = path
    return written_pgn_path


def append_game_csv(game_data: Dict[str, str], year: int, month: int) -> Path:
    """Append a game row to the consolidated CSV file.

    Args:
        game_data (Dict[str, str]): Normalized game data.
        year (int): Archive year.
        month (int): Archive month.

    Returns:
        csv_path (Path): Path to the consolidated CSV file.
    """
    uuid = game_data["uuid"]
    if is_game_in_csv(uuid):
        logger.debug("Game already in CSV: %s", uuid)
        existing_csv_path = GAMES_CSV_PATH
        return existing_csv_path

    pgn_rel = pgn_relative_path(year, month, uuid)
    csv_data_columns = CSV_COLUMNS[:-1]
    row = {}
    for column in csv_data_columns:
        row[column] = game_data.get(column, "")
    row["pgn_file"] = pgn_rel

    write_header = not GAMES_CSV_PATH.is_file() or GAMES_CSV_PATH.stat().st_size == 0
    with GAMES_CSV_PATH.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    load_csv_uuids().add(uuid)
    logger.info("Appended game to CSV: %s", uuid)
    updated_csv_path = GAMES_CSV_PATH
    return updated_csv_path
