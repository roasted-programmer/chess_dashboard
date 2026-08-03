"""HTTP client for the Chess.com public API."""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

RETRY_STATUS_CODES = (429, 500, 502, 503, 504)


def _create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    retry = Retry(
        total=5,
        status_forcelist=list(RETRY_STATUS_CODES),
        allowed_methods=["GET"],
        respect_retry_after_header=True,
        backoff_factor=1,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _create_session()
    return _session


def _request_json(url: str) -> dict:
    logger.debug("Requesting %s", url)
    response = _get_session().get(url, timeout=REQUEST_TIMEOUT)
    if response.status_code in RETRY_STATUS_CODES:
        response.raise_for_status()
    if not response.ok:
        raise requests.HTTPError(
            f"HTTP {response.status_code} for {url}",
            response=response,
        )
    return response.json()


def get_archive_urls(player: str) -> list[str]:
    """Return monthly archive URLs for a player."""
    url = f"https://api.chess.com/pub/player/{player}/games/archives"
    data = _request_json(url)
    if "archives" not in data:
        raise ValueError(f"Missing 'archives' key in response from {url}")
    archives = data["archives"]
    if not isinstance(archives, list):
        raise ValueError(f"'archives' must be a list in response from {url}")
    return archives


def get_monthly_games(archive_url: str) -> list[dict]:
    """Return games for a monthly archive URL."""
    data = _request_json(archive_url)
    if "games" not in data:
        raise ValueError(f"Missing 'games' key in response from {archive_url}")
    games = data["games"]
    if not isinstance(games, list):
        raise ValueError(f"'games' must be a list in response from {archive_url}")
    return games
