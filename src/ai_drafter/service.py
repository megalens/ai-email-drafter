"""Service entry point for the AI Email Drafter daemon."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_drafter.config import load_config
from ai_drafter.context import ContextLoader
from ai_drafter.gmail import GmailProvider
from ai_drafter.llm import LLMClassifierDrafter
from ai_drafter.log import setup_logging
from ai_drafter.poller import Poller
from ai_drafter.state import StateStore

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
    logger.info(
        "Config: poll=%dm, model=%s, cost_cap=$%.2f/day",
        config.service.poll_interval_minutes,
        config.llm.model,
        config.llm.daily_cost_cap_usd,
    )

    if not config.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        return 1

    if not config.state_encryption_key:
        logger.error("STATE_ENCRYPTION_KEY not set")
        return 1

    context_path = Path(config.service.context_file)
    if not context_path.exists():
        logger.error("Context file not found: %s", context_path)
        return 1

    state = StateStore(config.service.state_db, config.state_encryption_key)
    context = ContextLoader(context_path)

    accounts = state.list_accounts()
    if not accounts:
        logger.error("No OAuth accounts configured — run auth flow first")
        state.close()
        return 1

    user_email = accounts[0]
    tokens = state.get_oauth_tokens(user_email)

    from google.oauth2.credentials import Credentials

    creds = Credentials(
        token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id="",
        client_secret="",
    )

    provider = GmailProvider(creds, user_email)
    llm = LLMClassifierDrafter(
        api_key=config.anthropic_api_key,
        model=config.llm.model,
    )

    poller = Poller(
        provider=provider,
        state=state,
        context=context,
        llm=llm,
        config=config,
        user_email=user_email,
    )

    logger.info("Starting poll loop for %s", user_email)
    try:
        poller.run()
    finally:
        state.close()
        logger.info("Service stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
