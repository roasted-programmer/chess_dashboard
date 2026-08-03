"""HTTP client for the Chess.com public API."""

import logging
from typing import Any, Dict, List

import requests

from src.config import REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
MAX_RETRIES = 5


def _request_json(url: str) -> Dict[str, Any]:
    """Perform a GET request and return the parsed JSON body."""
    logger.debug("Requesting %s", url)
    response = None
    for attempt in range(MAX_RETRIES):
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code not in RETRY_STATUS_CODES:
            break
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            logger.warning(
                "Retrying %s after HTTP %s (Retry-After: %s)",
                url,
                response.status_code,
                retry_after,
            )
        else:
            logger.warning(
                "Retrying %s after HTTP %s (attempt %d of %d)",
                url,
                response.status_code,
                attempt + 1,
                MAX_RETRIES,
            )

    if response.status_code in RETRY_STATUS_CODES:
        response.raise_for_status()
    if not response.ok:
        raise requests.HTTPError(
            f"HTTP {response.status_code} for {url}",
            response=response,
        )
    response_data = response.json()
    return response_data


def get_archive_urls(player: str) -> List[str]:
    """Return monthly archive URLs for a player.

    Args:
        player (str): Chess.com username.

    Returns:
        archives (List[str]): Monthly archive endpoint URLs.

    Raises:
        ValueError: If the response does not contain a valid archives list.
    """
    url = f"https://api.chess.com/pub/player/{player}/games/archives"
    data = _request_json(url)
    if "archives" not in data:
        raise ValueError(f"Missing 'archives' key in response from {url}")
    archives = data["archives"]
    if not isinstance(archives, list):
        raise ValueError(f"'archives' must be a list in response from {url}")
    return archives


def get_monthly_games(archive_url: str) -> List[Dict[str, Any]]:
    """Return games for a monthly archive URL.

    Args:
        archive_url (str): Chess.com monthly games archive URL.

    Returns:
        monthly_games (List[Dict[str, Any]]): Raw game payloads for the archive month.

    Raises:
        ValueError: If the response does not contain a valid games list.
    """
    data = _request_json(archive_url)
    if "games" not in data:
        raise ValueError(f"Missing 'games' key in response from {archive_url}")
    monthly_games = data["games"]
    if not isinstance(monthly_games, list):
        raise ValueError(f"'games' must be a list in response from {archive_url}")
    return monthly_games
