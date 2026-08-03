"""Entrypoint for the Chess.com game data pipeline."""

import logging
import sys

import requests

from src.config import ConfigurationError
from src.pipeline import run_pipeline


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    try:
        totals = run_pipeline()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        return 1
    except requests.RequestException as exc:
        logger.error("HTTP failure: %s", exc)
        return 1
    except (ValueError, OSError) as exc:
        logger.error("Fatal error: %s", exc)
        return 1

    if totals["games_failed"] > 0:
        logger.error("Pipeline finished with %d failed game(s)", totals["games_failed"])
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
