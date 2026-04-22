"""Tests for ContextLoader."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ai_drafter.context import ContextLoader, ContextLoadError


@pytest.fixture
def ctx_file(tmp_path: Path) -> Path:
    f = tmp_path / "context.md"
    f.write_text("# My Business\nWe sell widgets.", encoding="utf-8")
    return f


class TestContextLoader:
    def test_loads_content(self, ctx_file: Path):
        loader = ContextLoader(ctx_file)
        assert "We sell widgets" in loader.get()

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(ContextLoadError, match="not found"):
            ContextLoader(tmp_path / "nonexistent.md")

    def test_reloads_on_change(self, ctx_file: Path):
        loader = ContextLoader(ctx_file)
        assert "widgets" in loader.get()

        time.sleep(0.05)
        ctx_file.write_text("# Updated\nNow we sell gadgets.", encoding="utf-8")

        content = loader.get()
        assert "gadgets" in content

    def test_returns_cached_when_unchanged(self, ctx_file: Path):
        loader = ContextLoader(ctx_file)
        content1 = loader.get()
        content2 = loader.get()
        assert content1 == content2

    def test_survives_stat_failure(self, ctx_file: Path, monkeypatch):
        loader = ContextLoader(ctx_file)
        original = loader.get()

        ctx_file.unlink()

        result = loader.get()
        assert result == original

    def test_path_property(self, ctx_file: Path):
        loader = ContextLoader(ctx_file)
        assert loader.path == ctx_file

    def test_empty_file_loads(self, tmp_path: Path):
        f = tmp_path / "empty.md"
        f.write_text("", encoding="utf-8")
        loader = ContextLoader(f)
        assert loader.get() == ""

    def test_unicode_content(self, tmp_path: Path):
        f = tmp_path / "unicode.md"
        f.write_text("Pricing: €100/hr — premium tier", encoding="utf-8")
        loader = ContextLoader(f)
        assert "€100" in loader.get()
