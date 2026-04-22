"""Logging setup with rotating file handler."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ai_drafter.config import LoggingConfig

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_CONFIGURED = False


def setup_logging(cfg: LoggingConfig) -> logging.Logger:
    """Configure logger with console + rotating file handler.

    Safe to call multiple times — only configures once.
    Degrades to console-only if file handler fails.
    """
    global _CONFIGURED
    logger = logging.getLogger("ai_drafter")

    if _CONFIGURED:
        return logger

    level = cfg.level.upper()
    if level not in _VALID_LEVELS:
        level = "INFO"

    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    logger.addHandler(console)

    log_dir = Path(cfg.file).parent
    if log_dir.exists() or _try_create_log_dir(log_dir):
        try:
            file_handler = RotatingFileHandler(
                cfg.file,
                maxBytes=cfg.max_bytes,
                backupCount=cfg.backup_count,
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:
            logger.warning("Could not open log file %s — file logging disabled", cfg.file)
    else:
        logger.warning(
            "Log directory %s does not exist, could not create — file logging disabled", log_dir
        )

    _CONFIGURED = True
    return logger


def _try_create_log_dir(log_dir: Path) -> bool:
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False
