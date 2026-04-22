"""Poller — periodic poll loop with history-based fetch + bootstrap fallback."""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timedelta

from ai_drafter.config import Config
from ai_drafter.context import ContextLoader
from ai_drafter.gmail import GmailProvider
from ai_drafter.llm import LLMClassifierDrafter
from ai_drafter.pipeline import PipelineRunner
from ai_drafter.state import StateStore

logger = logging.getLogger("ai_drafter")


class Poller:
    """Runs the poll loop: fetch → pipeline → checkpoint."""

    def __init__(
        self,
        provider: GmailProvider,
        state: StateStore,
        context: ContextLoader,
        llm: LLMClassifierDrafter,
        config: Config,
        user_email: str,
    ) -> None:
        self._provider = provider
        self._state = state
        self._context = context
        self._llm = llm
        self._config = config
        self._user_email = user_email
        self._pipeline = PipelineRunner(
            provider=provider,
            state=state,
            context=context,
            llm=llm,
            user_email=user_email,
            daily_cost_cap=config.llm.daily_cost_cap_usd,
        )
        self._running = True

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info("Poller started for %s", self._user_email)
        interval = self._config.service.poll_interval_minutes * 60

        while self._running:
            try:
                self._poll_once()
            except Exception:
                logger.exception("Poll cycle failed")

            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)

        logger.info("Poller stopped")

    def _poll_once(self) -> None:
        self._provider.invalidate_drafts_cache()

        checkpoint = self._state.get_checkpoint(self._user_email)
        history_id = checkpoint["last_history_id"] if checkpoint else None

        messages = []
        new_history_id = None

        if history_id:
            messages, new_history_id = self._provider.fetch_by_history(history_id)
            if not new_history_id:
                logger.info("History expired, falling back to bootstrap")
                history_id = None

        if not history_id:
            cutoff = datetime.now() - timedelta(
                days=self._config.gmail.bootstrap_lookback_days
            )
            messages = self._provider.fetch_unread_inbound(
                cutoff, max_results=self._config.gmail.poll_max_messages
            )
            new_history_id = self._provider.get_current_history_id()

        if messages:
            logger.info("Processing %d messages", len(messages))
            stats = self._pipeline.process_batch(messages)
            logger.info(
                "Batch done: %d drafted, %d filtered, %d skipped, %d errors, $%.4f",
                stats.drafted, stats.filtered, stats.skipped, stats.errors, stats.cost_usd,
            )

        if new_history_id:
            self._state.update_checkpoint(self._user_email, new_history_id)

    def stop(self) -> None:
        self._running = False

    def _handle_signal(self, signum: int, frame: object) -> None:
        logger.info("Received signal %d, stopping", signum)
        self._running = False
