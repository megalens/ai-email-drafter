"""Logging setup with rotating file handler."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ai_drafter.config import LoggingConfig

_CONFIGURED = False


def setup_logging(cfg: LoggingConfig) -> logging.Logger:
    """Configure root logger with console + rotating file handler.

    Safe to call multiple times — only configures once.
    """
    global _CONFIGURED
    logger = logging.getLogger("ai_drafter")

    if _CONFIGURED:
        return logger

    logger.setLevel(cfg.level.upper())
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    logger.addHandler(console)

    log_dir = Path(cfg.file).parent
    if log_dir.exists() or _try_create_log_dir(log_dir):
        file_handler = RotatingFileHandler(
            cfg.file,
            maxBytes=cfg.max_bytes,
            backupCount=cfg.backup_count,
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
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
