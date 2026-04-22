"""Tests for logging setup."""

from __future__ import annotations

import logging
from pathlib import Path

import ai_drafter.log as log_module
from ai_drafter.config import LoggingConfig
from ai_drafter.log import setup_logging


class TestLogging:
    def setup_method(self):
        log_module._CONFIGURED = False
        logger = logging.getLogger("ai_drafter")
        logger.handlers.clear()

    def test_creates_logger_with_correct_level(self, tmp_path: Path):
        cfg = LoggingConfig(level="DEBUG", file=str(tmp_path / "test.log"))
        logger = setup_logging(cfg)
        assert logger.name == "ai_drafter"
        assert logger.level == logging.DEBUG

    def test_creates_console_handler(self, tmp_path: Path):
        cfg = LoggingConfig(level="INFO", file=str(tmp_path / "test.log"))
        logger = setup_logging(cfg)
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "StreamHandler" in handler_types

    def test_creates_file_handler(self, tmp_path: Path):
        cfg = LoggingConfig(level="INFO", file=str(tmp_path / "test.log"))
        logger = setup_logging(cfg)
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "RotatingFileHandler" in handler_types

    def test_idempotent_setup(self, tmp_path: Path):
        cfg = LoggingConfig(level="INFO", file=str(tmp_path / "test.log"))
        logger1 = setup_logging(cfg)
        count1 = len(logger1.handlers)
        logger2 = setup_logging(cfg)
        assert len(logger2.handlers) == count1

    def test_missing_log_dir_no_crash(self):
        cfg = LoggingConfig(level="INFO", file="/nonexistent/deep/path/test.log")
        logger = setup_logging(cfg)
        assert logger is not None

    def test_log_message_written_to_file(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        cfg = LoggingConfig(level="INFO", file=str(log_file))
        logger = setup_logging(cfg)
        logger.info("test message 12345")
        for h in logger.handlers:
            h.flush()
        content = log_file.read_text()
        assert "test message 12345" in content
