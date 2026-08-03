"""Entrypoint for the Chess.com game data pipeline."""

import logging
import sys

import requests

from src.config import ConfigurationError
from src.pipeline import run_pipeline


def main() -> int:
    """Configure logging and run the Chess.com game pipeline.

    Returns:
        exit_code (int): Process exit code where zero indicates success.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    try:
        totals = run_pipeline()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        exit_code = 1
        return exit_code
    except requests.RequestException as exc:
        logger.error("HTTP failure: %s", exc)
        exit_code = 1
        return exit_code
    except (ValueError, OSError) as exc:
        logger.error("Fatal error: %s", exc)
        exit_code = 1
        return exit_code

    if totals["games_failed"] > 0:
        logger.error("Pipeline finished with %d failed game(s)", totals["games_failed"])
        exit_code = 1
        return exit_code

    exit_code = 0
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
