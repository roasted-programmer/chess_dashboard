"""Parse Chess.com game and archive data."""

import logging
import re
from typing import Any, Dict, Optional, Tuple

from src.chess_com.openings import split_opening

logger = logging.getLogger(__name__)

ARCHIVE_URL_PATTERN = re.compile(r"/games/(\d{4})/(\d{2})$")
PGN_TAG_PATTERN = re.compile(r'^\[(\w+)\s+"((?:[^"\\]|\\.)*)"\]', re.MULTILINE)
CHESS_OPENINGS_URL_PREFIX = "https://www.chess.com/openings/"
STANDARD_CHESS_RULES = "chess"

PGN_FIELD_MAP = {
    "White": "white_username",
    "Black": "black_username",
    "Result": "result",
    "Link": "game_url",
    "UTCDate": "utc_date",
    "UTCTime": "utc_time",
    "WhiteElo": "white_elo",
    "BlackElo": "black_elo",
    "TimeControl": "time_control",
    "Termination": "termination",
}


def parse_archive_year_month(archive_url: str) -> Tuple[int, int]:
    """Extract the year and month from a monthly archive URL.

    Args:
        archive_url (str): Chess.com monthly games archive URL.

    Returns:
        archive_year_month (Tuple[int, int]): Parsed archive year and month.

    Raises:
        ValueError: If the URL does not contain a valid year and month.
    """
    match = ARCHIVE_URL_PATTERN.search(archive_url.rstrip("/"))
    if not match:
        raise ValueError(f"Cannot parse year and month from archive URL: {archive_url}")
    year = int(match.group(1))
    month = int(match.group(2))
    archive_year_month = (year, month)
    return archive_year_month


def parse_pgn_headers(pgn_text: str) -> Dict[str, str]:
    """Parse PGN tag pairs from the header section.

    Args:
        pgn_text (str): Full PGN text including headers and movetext.

    Returns:
        headers (Dict[str, str]): Mapping of PGN tag names to their values.
    """
    headers = {}
    pgn_tag_matches = PGN_TAG_PATTERN.findall(pgn_text)
    for tag, value in pgn_tag_matches:
        headers[tag] = value.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    return headers


def is_missing_link_tag(game: Dict[str, Any]) -> bool:
    """Check whether a game PGN is missing the required Link tag."""
    pgn = game.get("pgn")
    if not pgn or not str(pgn).strip():
        link_missing = False
        return link_missing
    headers = parse_pgn_headers(pgn)
    link_missing = not headers.get("Link", "").strip()
    return link_missing


def extract_opening_from_eco_url(eco_url: str) -> str:
    """Extract a human-readable opening name from a Chess.com ECOUrl tag value.

    Args:
        eco_url (str): Opening URL from the PGN ECOUrl header tag.

    Returns:
        opening (str): Opening name derived from the URL slug, or an empty string
            when the URL is missing or not a Chess.com openings link.
    """
    eco_url = eco_url.strip()
    if not eco_url.startswith(CHESS_OPENINGS_URL_PREFIX):
        opening = ""
        return opening
    slug = eco_url[len(CHESS_OPENINGS_URL_PREFIX) :].strip("/")
    if not slug:
        opening = ""
        return opening
    opening = slug.replace("-", " ")
    return opening


def parse_game(game: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Normalize a Chess.com game into a consistent dictionary.

    Args:
        game (Dict[str, Any]): Raw game payload returned by the Chess.com API.

    Returns:
        parsed_game (Optional[Dict[str, str]]): Normalized game data, or None when
            required fields are missing.
    """
    uuid = game.get("uuid")
    pgn = game.get("pgn")

    if not uuid or not str(uuid).strip():
        logger.warning("Rejecting game: missing uuid")
        parsed_game = None
        return parsed_game
    if not pgn or not str(pgn).strip():
        logger.warning("Rejecting game %s: missing pgn", uuid)
        parsed_game = None
        return parsed_game

    headers = parse_pgn_headers(pgn)
    normalized = {
        "uuid": str(uuid).strip(),
        "pgn": pgn,
    }

    pgn_field_mappings = PGN_FIELD_MAP.items()
    for pgn_tag, field_name in pgn_field_mappings:
        value = headers.get(pgn_tag, "")
        if not value and field_name == "time_control":
            value = str(game.get("time_control") or "")
        normalized[field_name] = value

    game_url = normalized.get("game_url", "").strip()
    if not game_url:
        logger.warning("Rejecting game %s: missing Link tag in PGN", uuid)
        parsed_game = None
        return parsed_game

    rules = game.get("rules")
    if rules is None:
        rules = ""
    else:
        rules = str(rules).strip()
    normalized["rules"] = rules

    if rules == STANDARD_CHESS_RULES:
        eco_url = headers.get("ECOUrl", "")
        opening = extract_opening_from_eco_url(eco_url)
    else:
        opening = ""
    normalized["opening"] = opening

    main_opening, opening_variant, opening_subvariant = split_opening(opening)
    normalized["main_opening"] = main_opening
    normalized["opening_variant"] = opening_variant
    normalized["opening_subvariant"] = opening_subvariant

    parsed_game = normalized
    return parsed_game
