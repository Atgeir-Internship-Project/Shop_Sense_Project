"""
Logging setup for the gcs_to_bronze Cloud Function.

Every other module in this function imports `get_logger()` from here so
that all log lines share the same format and level. We deliberately keep
this tiny and dependency-free - Cloud Functions automatically forwards
anything printed to stdout/stderr into Cloud Logging, so a plain
StreamHandler is all we need.
"""

import logging
import sys

# One consistent line format everywhere: when + how serious + which module + message.
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def get_logger(name: str = "gcs_to_bronze") -> logging.Logger:
    """Return a ready-to-use logger.

    `logging.getLogger(name)` always hands back the *same* logger object
    for a given name, so this function may be called from many modules.
    The `if not logger.handlers` guard makes sure we attach our handler
    only once - without it, a warm function instance that re-imports
    modules would print every log line two or three times.
    """

    logger = logging.getLogger(name)

    if not logger.handlers:
        # Send logs to stdout so Cloud Logging picks them up.
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)

        # INFO is a good default for a pipeline: we want the milestones,
        # not every internal DEBUG line from the Google client libraries.
        logger.setLevel(logging.INFO)

        # Don't also bubble records up to the root logger (avoids dupes).
        logger.propagate = False

    return logger
