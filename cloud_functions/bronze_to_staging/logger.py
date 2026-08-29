"""
Logging setup for the bronze_to_staging Cloud Function.

Same idea as the sibling function: every module imports `get_logger()`
from here so all log lines look the same. Cloud Functions ships stdout
straight to Cloud Logging, so a StreamHandler is all we need - no extra
dependencies.
"""

import logging
import sys

# when | severity | which module | message
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def get_logger(name: str = "bronze_to_staging") -> logging.Logger:
    """
    Return a shared logger.

    `logging.getLogger(name)` returns the same object every time for a
    given name, so this is safe to call from every module. The handler
    guard means a warm instance that re-imports modules won't start
    printing each line twice.
    """

    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False  # don't double-log via the root logger

    return logger
