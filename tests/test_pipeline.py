"""Tests for PipelineRunner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from ai_drafter.context import ContextLoader
from ai_drafter.gmail import EmailMessage
from ai_drafter.llm import LLMClassifierDrafter, LLMResult
from ai_drafter.pipeline import PipelineRunner
from ai_drafter.state import OAuthTokens, StateStore


def _msg(
    msg_id: str = "msg-1",
    thread_id: str = "thread-1",
    from_addr: str = "client@external.com",
    subject: str = "Quote request",
) -> EmailMessage:
    return EmailMessage(
        message_id=msg_id,
        thread_id=thread_id,
        from_address=from_addr,
        to_address="me@mycompany.com",
        subject=subject,
        date="Mon, 1 Jan 2024 12:00:00 +0000",
        body="I need a quote",
        headers={},
        labels=["INBOX", "UNREAD"],
    )


@pytest.fixture
def state(tmp_path: Path):
    db = tmp_path / "test.sqlite"
    key = Fernet.generate_key().decode()
    s = StateStore(db, key)
    s.save_oauth_tokens(OAuthTokens(
        account_email="me@mycompany.com",
        access_token="tok", refresh_token="ref",
        expires_at=0, scope="s", created_at=0, updated_at=0,
    ))
    yield s
    s.close()


@pytest.fixture
def context(tmp_path: Path):
    f = tmp_path / "context.md"
    f.write_text("# Business\nWe sell widgets at $10 each.")
    return ContextLoader(f)


@pytest.fixture
def provider():
    p = MagicMock()
    p.list_sent_thread_ids.return_value = set()
    p.check_draft_exists.return_value = False
    p.is_valid_inbound.return_value = True
    p.save_draft.return_value = "draft-1"
    return p


@pytest.fixture
def llm():
    m = MagicMock(spec=LLMClassifierDrafter)
    return m


@pytest.fixture
def pipeline(provider, state, context, llm):
    return PipelineRunner(
        provider=provider,
        state=state,
        context=context,
        llm=llm,
        user_email="me@mycompany.com",
        daily_cost_cap=5.0,
    )


class TestProcessBatch:
    def test_draft_flow(self, pipeline, llm, state):
        llm.classify_and_draft.return_value = LLMResult(
            decision="DRAFT", reason="matches context",
            draft_body="Hi, widgets cost $10.", draft_subject=None,
            cost_usd=0.01, input_tokens=500, output_tokens=200,
        )
        stats = pipeline.process_batch([_msg()])

        assert stats.drafted == 1
        assert stats.filtered == 0
        assert stats.cost_usd == 0.01
        assert state.is_processed("msg-1")

    def test_skip_flow(self, pipeline, llm, state):
        llm.classify_and_draft.return_value = LLMResult(
            decision="SKIP", reason="not relevant",
            draft_body=None, draft_subject=None,
            cost_usd=0.005, input_tokens=500, output_tokens=100,
        )
        stats = pipeline.process_batch([_msg()])

        assert stats.skipped == 1
        assert stats.drafted == 0
        assert state.is_processed("msg-1")

    def test_noreply_filtered(self, pipeline, llm, state):
        msg = _msg(from_addr="noreply@service.com")
        stats = pipeline.process_batch([msg])

        assert stats.filtered == 1
        llm.classify_and_draft.assert_not_called()

    def test_already_processed_skipped(self, pipeline, llm, state):
        state.record_processed(
            message_id="msg-1", thread_id="thread-1",
            account_email="me@mycompany.com", layer1_result="passed",
        )
        stats = pipeline.process_batch([_msg()])

        assert stats.filtered == 1
        llm.classify_and_draft.assert_not_called()

    def test_multiple_messages(self, pipeline, llm, state):
        llm.classify_and_draft.return_value = LLMResult(
            decision="DRAFT", reason="ok",
            draft_body="Reply", draft_subject=None,
            cost_usd=0.01, input_tokens=500, output_tokens=200,
        )
        msgs = [
            _msg(msg_id="m1", thread_id="t1"),
            _msg(msg_id="m2", thread_id="t2"),
            _msg(msg_id="m3", thread_id="t3", from_addr="noreply@x.com"),
        ]
        stats = pipeline.process_batch(msgs)

        assert stats.total == 3
        assert stats.drafted == 2
        assert stats.filtered == 1

    def test_error_handling(self, pipeline, llm, state):
        llm.classify_and_draft.side_effect = RuntimeError("API error")
        stats = pipeline.process_batch([_msg()])

        assert stats.errors == 1

    def test_daily_cap_stops_batch(self, pipeline, llm, state):
        import time as t

        now = int(t.time())
        for i in range(10):
            state._conn.execute(
                "INSERT INTO processed_messages "
                "(message_id, thread_id, account_email, processed_at, "
                "layer1_result, llm_cost_usd, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"old-{i}", f"t-{i}", "me@mycompany.com", now, "passed", 0.6, "completed"),
            )
        state._conn.commit()

        pipeline.process_batch([_msg()])
        llm.classify_and_draft.assert_not_called()

    def test_draft_saved_to_gmail(self, pipeline, llm, provider):
        llm.classify_and_draft.return_value = LLMResult(
            decision="DRAFT", reason="ok",
            draft_body="Hello reply", draft_subject=None,
            cost_usd=0.01, input_tokens=500, output_tokens=200,
        )
        pipeline.process_batch([_msg()])

        provider.save_draft.assert_called_once()
        call_kwargs = provider.save_draft.call_args
        assert call_kwargs[1]["body"] == "Hello reply"
        assert call_kwargs[1]["thread_id"] == "thread-1"

    def test_audit_log_on_draft(self, pipeline, llm, state):
        llm.classify_and_draft.return_value = LLMResult(
            decision="DRAFT", reason="ok",
            draft_body="Reply", draft_subject=None,
            cost_usd=0.01, input_tokens=500, output_tokens=200,
        )
        pipeline.process_batch([_msg()])

        rows = state._conn.execute("SELECT * FROM audit_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["event"] == "draft_created"
