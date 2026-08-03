"""Local persistence for per-game PGN and CSV files."""

import csv
import logging
from pathlib import Path

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


def ensure_data_directories() -> None:
    """Create required data directories if they do not exist."""
    for directory in (DATA_DIR, PGN_DIR, CSV_DIR, METADATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def _file_stem(year: int, month: int, uuid: str) -> str:
    return f"{year:04d}-{month:02d}-{uuid}"


def pgn_file_path(year: int, month: int, uuid: str) -> Path:
    return PGN_DIR / f"{_file_stem(year, month, uuid)}.pgn"


def csv_file_path(year: int, month: int, uuid: str) -> Path:
    return CSV_DIR / f"{_file_stem(year, month, uuid)}.csv"


def pgn_relative_path(year: int, month: int, uuid: str) -> str:
    return f"data/pgns/{_file_stem(year, month, uuid)}.pgn"


def game_files_exist(uuid: str, year: int, month: int) -> bool:
    """Return True when both PGN and CSV files exist for a game."""
    return pgn_file_path(year, month, uuid).is_file() and csv_file_path(
        year, month, uuid
    ).is_file()


def write_pgn_file(game_data: dict[str, str], year: int, month: int) -> Path:
    """Write a PGN file and return its path."""
    path = pgn_file_path(year, month, game_data["uuid"])
    if path.is_file():
        logger.debug("PGN file already exists: %s", path)
        return path
    path.write_text(game_data["pgn"], encoding="utf-8")
    logger.info("Wrote PGN file: %s", path)
    return path


def write_game_csv(game_data: dict[str, str], year: int, month: int) -> Path:
    """Write a single-row CSV file and return its path."""
    path = csv_file_path(year, month, game_data["uuid"])
    pgn_rel = pgn_relative_path(year, month, game_data["uuid"])
    if path.is_file():
        logger.debug("CSV file already exists: %s", path)
        return path
    row = {column: game_data.get(column, "") for column in CSV_COLUMNS[:-1]}
    row["pgn_file"] = pgn_rel
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    logger.info("Wrote CSV file: %s", path)
    return path
