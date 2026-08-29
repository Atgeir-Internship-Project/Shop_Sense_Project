"""
Logging setup for the silver_to_gold Cloud Function.

Same shape as the other three functions: every module imports
`get_logger()` from here so all log lines share one format. Cloud
Functions forwards stdout straight to Cloud Logging, so a plain
StreamHandler is enough.
"""

import logging
import sys

# when | severity | which module | message
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def get_logger(name: str = "silver_to_gold") -> logging.Logger:
    """Return a shared logger (safe to call from every module)."""

    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False  # don't double-log via the root logger

    return logger
