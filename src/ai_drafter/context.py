"""ContextLoader — reads context.md with mtime-based reload."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("ai_drafter")


class ContextLoadError(Exception):
    """Raised when context file cannot be read."""


class ContextLoader:
    """Loads and caches context.md, reloading when the file changes on disk."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._content: str = ""
        self._mtime: float = 0.0
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            raise ContextLoadError(f"Context file not found: {self._path}")
        try:
            self._content = self._path.read_text(encoding="utf-8")
            self._mtime = self._path.stat().st_mtime
            logger.info("Loaded context from %s (%d chars)", self._path, len(self._content))
        except OSError as e:
            raise ContextLoadError(f"Failed to read context file: {e}") from e

    def get(self) -> str:
        try:
            current_mtime = self._path.stat().st_mtime
            if current_mtime > self._mtime:
                logger.info("Context file changed, reloading")
                self._load()
        except OSError:
            logger.warning("Context file stat failed, using cached version")
        return self._content

    @property
    def path(self) -> Path:
        return self._path
