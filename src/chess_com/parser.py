"""Parse Chess.com game and archive data."""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

ARCHIVE_URL_PATTERN = re.compile(r"/games/(\d{4})/(\d{2})$")
PGN_TAG_PATTERN = re.compile(r'^\[(\w+)\s+"((?:[^"\\]|\\.)*)"\]', re.MULTILINE)

PGN_FIELD_MAP = {
    "White": "white_username",
    "Black": "black_username",
    "Result": "result",
    "Variant": "variant",
    "ECOUrl": "eco_url",
    "UTCDate": "utc_date",
    "UTCTime": "utc_time",
    "WhiteElo": "white_elo",
    "BlackElo": "black_elo",
    "TimeControl": "time_control",
    "Termination": "termination",
}


def parse_archive_year_month(archive_url: str) -> tuple[int, int]:
    """Extract year and month from a monthly archive URL."""
    match = ARCHIVE_URL_PATTERN.search(archive_url.rstrip("/"))
    if not match:
        raise ValueError(f"Cannot parse year and month from archive URL: {archive_url}")
    return int(match.group(1)), int(match.group(2))


def parse_pgn_headers(pgn_text: str) -> dict[str, str]:
    """Parse PGN tag pairs from the header section."""
    headers: dict[str, str] = {}
    for tag, value in PGN_TAG_PATTERN.findall(pgn_text):
        headers[tag] = value.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    return headers


def parse_game(game: dict[str, Any]) -> dict[str, str] | None:
    """
    Normalize a Chess.com game into a consistent dictionary.

    Returns None when required fields are missing.
    """
    uuid = game.get("uuid")
    pgn = game.get("pgn")

    if not uuid or not str(uuid).strip():
        logger.warning("Rejecting game: missing uuid")
        return None
    if not pgn or not str(pgn).strip():
        logger.warning("Rejecting game %s: missing pgn", uuid)
        return None

    headers = parse_pgn_headers(pgn)
    normalized: dict[str, str] = {
        "uuid": str(uuid).strip(),
        "pgn": pgn,
    }

    for pgn_tag, field_name in PGN_FIELD_MAP.items():
        value = headers.get(pgn_tag, "")
        if not value and field_name == "time_control":
            value = str(game.get("time_control") or "")
        normalized[field_name] = value

    return normalized
