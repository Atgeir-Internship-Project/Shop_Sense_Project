"""
Logging setup for the staging_to_silver Cloud Function.

Identical in spirit to the other two functions: every module imports
`get_logger()` from here so all log lines share one format. Cloud
Functions forwards stdout straight to Cloud Logging, so a plain
StreamHandler is enough.
"""

import logging
import sys

# when | severity | which module | message
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def get_logger(name: str = "staging_to_silver") -> logging.Logger:
    """
    Return a shared logger.

    `logging.getLogger(name)` returns the same object every time for a
    given name, so this is safe to call from every module. The handler
    guard stops a warm instance that re-imports modules from printing
    each line twice.
    """

    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False  # don't double-log via the root logger

    return logger
