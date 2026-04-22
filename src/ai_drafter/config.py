"""Configuration loading from TOML file + environment variables."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Raised when configuration is invalid or unparseable."""


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


_SECRET_MASK = "***"


@dataclass(frozen=True)
class Config:
    service: ServiceConfig = field(default_factory=ServiceConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    anthropic_api_key: str = field(default="", repr=False)
    google_oauth_client_secrets: str = field(default="", repr=False)
    state_encryption_key: str = field(default="", repr=False)

    def __str__(self) -> str:
        return (
            f"Config(service={self.service}, llm={self.llm}, "
            f"gmail={self.gmail}, logging={self.logging}, "
            f"anthropic_api_key={_SECRET_MASK}, "
            f"google_oauth_client_secrets={_SECRET_MASK}, "
            f"state_encryption_key={_SECRET_MASK})"
        )


def _merge_section(dc_class: type, toml_section: dict, section_name: str) -> dict:
    """Extract only keys that match the dataclass fields, with type validation."""
    if not isinstance(toml_section, dict):
        raise ConfigError(
            f"[{section_name}] must be a TOML table, got {type(toml_section).__name__}"
        )
    valid_fields = {f.name: f for f in dc_class.__dataclass_fields__.values()}
    result = {}
    for k, v in toml_section.items():
        if k not in valid_fields:
            continue
        expected_type = valid_fields[k].type
        if expected_type == "int" and isinstance(v, int) and not isinstance(v, bool):
            result[k] = v
        elif expected_type == "float" and isinstance(v, (int, float)) and not isinstance(v, bool):
            result[k] = float(v)
        elif expected_type == "str" and isinstance(v, str):
            result[k] = v
        else:
            raise ConfigError(
                f"[{section_name}].{k}: expected {expected_type}, got {type(v).__name__}"
            )
    return result


_SECTIONS: list[tuple[str, type]] = [
    ("service", ServiceConfig),
    ("llm", LLMConfig),
    ("gmail", GmailConfig),
    ("logging", LoggingConfig),
]


def load_config(config_path: str | Path | None = None) -> Config:
    """Load config from TOML file (optional) + env vars (required for secrets).

    Raises ConfigError if TOML is malformed or contains invalid types.
    """
    section_kw: dict[str, dict] = {name: {} for name, _ in _SECTIONS}

    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            try:
                with open(path, "rb") as f:
                    data = tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                raise ConfigError(f"Failed to parse {path}: {e}") from e
            for name, dc_class in _SECTIONS:
                if name in data:
                    section_kw[name] = _merge_section(dc_class, data[name], name)

    return Config(
        service=ServiceConfig(**section_kw["service"]),
        llm=LLMConfig(**section_kw["llm"]),
        gmail=GmailConfig(**section_kw["gmail"]),
        logging=LoggingConfig(**section_kw["logging"]),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        google_oauth_client_secrets=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS", ""),
        state_encryption_key=os.environ.get("STATE_ENCRYPTION_KEY", ""),
    )
