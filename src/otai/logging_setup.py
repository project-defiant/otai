"""Configures loguru's global logger for the otai CLI.

Library modules just `from loguru import logger` and log directly; this is
the one place that decides where those messages go and at what level.
Always stderr, never stdout - stdout is reserved for the JSON envelope
(PRD §7), so logging must never risk corrupting it. Level is configurable
via OTAI_LOG_LEVEL (see config.py), defaulting to INFO.
"""

from __future__ import annotations

import sys

from loguru import logger

from otai.config import get_log_level

_LOG_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<level>{message}</level>"
)


def configure_logging() -> None:
    """Reset loguru to a single stderr sink at the configured level.

    Safe to call more than once (e.g. across CLI invocations in tests):
    `logger.remove()` clears any prior sink before adding the new one, so
    repeated calls never accumulate duplicate handlers.
    """
    logger.remove()
    logger.add(sys.stderr, level=get_log_level(), format=_LOG_FORMAT, colorize=True)
