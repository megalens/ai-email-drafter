"""Configuration loading from TOML file + environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import tomli


@dataclass(frozen=True)
class ServiceConfig:
    poll_interval_minutes: int = 5
    context_file: str = "/etc/ai-drafter/context.md"
    state_db: str = "/var/lib/ai-drafter/state.sqlite"


@dataclass(frozen=True)
class LLMConfig:
    model: str = "claude-sonnet-4-6"
    max_context_tokens: int = 25000
    daily_cost_cap_usd: float = 5.0


@dataclass(frozen=True)
class GmailConfig:
    poll_max_messages: int = 50
    bootstrap_lookback_days: int = 1


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file: str = "/var/log/ai-drafter/service.log"
    max_bytes: int = 10_485_760
    backup_count: int = 5


@dataclass(frozen=True)
class Config:
    service: ServiceConfig = field(default_factory=ServiceConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # Secrets resolved from env vars — never stored in config files
    anthropic_api_key: str = ""
    google_oauth_client_secrets: str = ""
    state_encryption_key: str = ""


def _merge_section(dc_class: type, toml_section: dict) -> dict:
    """Extract only keys that match the dataclass fields."""
    valid_fields = {f.name for f in dc_class.__dataclass_fields__.values()}
    return {k: v for k, v in toml_section.items() if k in valid_fields}


def load_config(config_path: str | Path | None = None) -> Config:
    """Load config from TOML file (optional) + env vars (required for secrets)."""
    service_kw: dict = {}
    llm_kw: dict = {}
    gmail_kw: dict = {}
    logging_kw: dict = {}

    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            with open(path, "rb") as f:
                data = tomli.load(f)
            if "service" in data:
                service_kw = _merge_section(ServiceConfig, data["service"])
            if "llm" in data:
                llm_kw = _merge_section(LLMConfig, data["llm"])
            if "gmail" in data:
                gmail_kw = _merge_section(GmailConfig, data["gmail"])
            if "logging" in data:
                logging_kw = _merge_section(LoggingConfig, data["logging"])

    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    google_oauth = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS", "")
    state_key = os.environ.get("STATE_ENCRYPTION_KEY", "")

    return Config(
        service=ServiceConfig(**service_kw),
        llm=LLMConfig(**llm_kw),
        gmail=GmailConfig(**gmail_kw),
        logging=LoggingConfig(**logging_kw),
        anthropic_api_key=anthropic_api_key,
        google_oauth_client_secrets=google_oauth,
        state_encryption_key=state_key,
    )
