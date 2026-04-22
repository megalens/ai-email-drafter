"""Tests for config loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_drafter.config import Config, ServiceConfig, load_config


class TestDefaults:
    def test_default_config_has_sane_values(self):
        cfg = Config()
        assert cfg.service.poll_interval_minutes == 5
        assert cfg.llm.model == "claude-sonnet-4-6"
        assert cfg.llm.daily_cost_cap_usd == 5.0
        assert cfg.gmail.poll_max_messages == 50
        assert cfg.gmail.bootstrap_lookback_days == 1
        assert cfg.logging.level == "INFO"
        assert cfg.logging.max_bytes == 10_485_760

    def test_secrets_default_empty(self):
        cfg = Config()
        assert cfg.anthropic_api_key == ""
        assert cfg.google_oauth_client_secrets == ""
        assert cfg.state_encryption_key == ""


class TestLoadFromToml:
    def test_load_full_config(self, tmp_path: Path):
        toml_content = """\
[service]
poll_interval_minutes = 10
context_file = "/tmp/ctx.md"
state_db = "/tmp/state.sqlite"

[llm]
model = "claude-sonnet-4-6"
max_context_tokens = 50000
daily_cost_cap_usd = 10.0

[gmail]
poll_max_messages = 25
bootstrap_lookback_days = 3

[logging]
level = "DEBUG"
file = "/tmp/test.log"
max_bytes = 1048576
backup_count = 3
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)
        cfg = load_config(config_file)

        assert cfg.service.poll_interval_minutes == 10
        assert cfg.service.context_file == "/tmp/ctx.md"
        assert cfg.llm.max_context_tokens == 50000
        assert cfg.llm.daily_cost_cap_usd == 10.0
        assert cfg.gmail.poll_max_messages == 25
        assert cfg.gmail.bootstrap_lookback_days == 3
        assert cfg.logging.level == "DEBUG"
        assert cfg.logging.backup_count == 3

    def test_partial_config_uses_defaults(self, tmp_path: Path):
        toml_content = """\
[service]
poll_interval_minutes = 2
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)
        cfg = load_config(config_file)

        assert cfg.service.poll_interval_minutes == 2
        assert cfg.llm.model == "claude-sonnet-4-6"  # default
        assert cfg.gmail.poll_max_messages == 50  # default

    def test_unknown_keys_ignored(self, tmp_path: Path):
        toml_content = """\
[service]
poll_interval_minutes = 3
unknown_key = "should be ignored"

[unknown_section]
foo = "bar"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)
        cfg = load_config(config_file)
        assert cfg.service.poll_interval_minutes == 3

    def test_missing_file_returns_defaults(self):
        cfg = load_config("/nonexistent/path/config.toml")
        assert cfg.service.poll_interval_minutes == 5

    def test_none_path_returns_defaults(self):
        cfg = load_config(None)
        assert cfg.service.poll_interval_minutes == 5


class TestEnvVars:
    def test_env_vars_loaded(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRETS", "/path/to/creds.json")
        monkeypatch.setenv("STATE_ENCRYPTION_KEY", "test-fernet-key")

        cfg = load_config(None)
        assert cfg.anthropic_api_key == "sk-test-123"
        assert cfg.google_oauth_client_secrets == "/path/to/creds.json"
        assert cfg.state_encryption_key == "test-fernet-key"

    def test_missing_env_vars_default_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRETS", raising=False)
        monkeypatch.delenv("STATE_ENCRYPTION_KEY", raising=False)

        cfg = load_config(None)
        assert cfg.anthropic_api_key == ""
        assert cfg.state_encryption_key == ""


class TestConfigImmutability:
    def test_config_is_frozen(self):
        cfg = Config()
        with pytest.raises(AttributeError):
            cfg.anthropic_api_key = "hacked"

    def test_service_config_is_frozen(self):
        cfg = ServiceConfig()
        with pytest.raises(AttributeError):
            cfg.poll_interval_minutes = 999
