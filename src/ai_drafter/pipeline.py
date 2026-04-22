"""PipelineRunner — wires filter, LLM, Gmail, and state together."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from ai_drafter.context import ContextLoader
from ai_drafter.filter import Layer1Filter
from ai_drafter.gmail import EmailMessage, EmailProvider
from ai_drafter.llm import LLMClassifierDrafter
from ai_drafter.state import StateStore

logger = logging.getLogger("ai_drafter")


@dataclass
class PipelineStats:
    total: int = 0
    filtered: int = 0
    drafted: int = 0
    skipped: int = 0
    errors: int = 0
    cost_usd: float = 0.0


class PipelineRunner:
    """Processes a batch of emails: filter → classify → draft → record."""

    def __init__(
        self,
        provider: EmailProvider,
        state: StateStore,
        context: ContextLoader,
        llm: LLMClassifierDrafter,
        user_email: str,
        daily_cost_cap: float = 5.0,
    ) -> None:
        self._provider = provider
        self._state = state
        self._context = context
        self._llm = llm
        self._filter = Layer1Filter(user_email)
        self._user_email = user_email
        self._daily_cost_cap = daily_cost_cap

    def process_batch(self, messages: list[EmailMessage]) -> PipelineStats:
        stats = PipelineStats(total=len(messages))
        sent_thread_ids = self._provider.list_sent_thread_ids(
            datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        )

        for msg in messages:
            if self._state.is_processed(msg.message_id):
                stats.filtered += 1
                continue

            if self._over_daily_cap():
                logger.warning("Daily cost cap reached, stopping batch")
                break

            try:
                self._process_one(msg, sent_thread_ids, stats)
            except Exception:
                logger.exception("Error processing message %s", msg.message_id)
                stats.errors += 1
                self._handle_error(msg)

        return stats

    def _process_one(
        self,
        msg: EmailMessage,
        sent_thread_ids: set[str],
        stats: PipelineStats,
    ) -> None:
        result = self._filter.apply(msg, sent_thread_ids, self._provider)
        if result.skip:
            logger.info("Filtered %s: %s", msg.message_id, result.rule)
            self._state.record_processed(
                message_id=msg.message_id,
                thread_id=msg.thread_id,
                account_email=self._user_email,
                layer1_result=result.rule,
            )
            stats.filtered += 1
            return

        context_md = self._context.get()
        llm_result = self._llm.classify_and_draft(msg, context_md)
        stats.cost_usd += llm_result.cost_usd

        if llm_result.decision == "DRAFT" and llm_result.draft_body:
            draft_id = self._provider.save_draft(
                thread_id=msg.thread_id,
                body=llm_result.draft_body,
                original=msg,
                subject=llm_result.draft_subject,
            )
            self._state.record_processed(
                message_id=msg.message_id,
                thread_id=msg.thread_id,
                account_email=self._user_email,
                layer1_result="passed",
                llm_decision="DRAFT",
                llm_reason=llm_result.reason,
                draft_id=draft_id,
                llm_cost_usd=llm_result.cost_usd,
            )
            self._state.log_event(
                "draft_created",
                self._user_email,
                {"message_id": msg.message_id, "draft_id": draft_id},
            )
            stats.drafted += 1
            logger.info("Drafted reply for %s → %s", msg.message_id, draft_id)
        else:
            self._state.record_processed(
                message_id=msg.message_id,
                thread_id=msg.thread_id,
                account_email=self._user_email,
                layer1_result="passed",
                llm_decision="SKIP",
                llm_reason=llm_result.reason,
                llm_cost_usd=llm_result.cost_usd,
            )
            stats.skipped += 1
            logger.info("LLM skipped %s: %s", msg.message_id, llm_result.reason)

    def _handle_error(self, msg: EmailMessage) -> None:
        if not self._state.is_processed(msg.message_id):
            self._state.record_processed(
                message_id=msg.message_id,
                thread_id=msg.thread_id,
                account_email=self._user_email,
                layer1_result="error",
            )
        retry_count = self._state.increment_retry(msg.message_id, "processing_error")
        if retry_count >= 3:
            logger.warning("Message %s quarantined after %d retries", msg.message_id, retry_count)

    def _over_daily_cap(self) -> bool:
        current = self._state.get_daily_cost(self._user_email)
        return current >= self._daily_cost_cap
