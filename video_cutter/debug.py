"""Small logging and environment helpers shared across the app."""

from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    """Configure process-wide logging from the debug environment."""
    level_name = os.environ.get("VIDEO_CUTTER_LOG", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger for a module or component."""
    return logging.getLogger(name)


def env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean-like environment flag with a fallback value."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
