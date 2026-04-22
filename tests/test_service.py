"""Tests for service entry point."""

from __future__ import annotations

from ai_drafter.service import parse_args


class TestParseArgs:
    def test_default_config_path(self):
        args = parse_args([])
        assert args.config == "/etc/ai-drafter/config.toml"

    def test_custom_config_path(self):
        args = parse_args(["-c", "/tmp/custom.toml"])
        assert args.config == "/tmp/custom.toml"

    def test_long_flag(self):
        args = parse_args(["--config", "/tmp/other.toml"])
        assert args.config == "/tmp/other.toml"
