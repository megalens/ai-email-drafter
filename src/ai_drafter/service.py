"""Service entry point for the AI Email Drafter daemon."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_drafter.config import load_config
from ai_drafter.log import setup_logging

DEFAULT_CONFIG_PATH = "/etc/ai-drafter/config.toml"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ai-drafter",
        description="AI Email Drafter — polls Gmail, drafts replies from context.md",
    )
    parser.add_argument(
        "-c", "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to config.toml (default: {DEFAULT_CONFIG_PATH})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = Path(args.config)

    config = load_config(config_path if config_path.exists() else None)
    logger = setup_logging(config.logging)

    logger.info("AI Email Drafter v0.1.0 starting")
    logger.info("Config: poll=%dm, model=%s, cost_cap=$%.2f/day",
                config.service.poll_interval_minutes,
                config.llm.model,
                config.llm.daily_cost_cap_usd)

    if not config.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY not set — exiting")
        return 1

    context_path = Path(config.service.context_file)
    if not context_path.exists():
        logger.error("Context file not found: %s — exiting", context_path)
        return 1

    logger.info("Service initialized — ready for poll loop (not yet implemented)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
