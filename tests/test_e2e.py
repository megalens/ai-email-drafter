"""End-to-end integration test — full pipeline cycle with mocked externals."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from ai_drafter.config import Config
from ai_drafter.context import ContextLoader
from ai_drafter.gmail import EmailMessage
from ai_drafter.llm import LLMClassifierDrafter, LLMResult
from ai_drafter.pipeline import PipelineRunner
from ai_drafter.poller import Poller
from ai_drafter.state import OAuthTokens, StateStore


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


CONTEXT_MD = """\
# Acme Widgets Inc.

## Products
- Standard Widget: $10/unit, MOQ 50
- Premium Widget: $25/unit, MOQ 10

## Contact
- Sales: sales@acme.com
- Support hours: Mon-Fri 9am-5pm EST

## Tone
Professional but friendly. Use first person plural (we/our).
"""

INBOUND_EMAIL = EmailMessage(
    message_id="msg-e2e-1",
    thread_id="thread-e2e-1",
    from_address="buyer@partner.com",
    to_address="sales@acme.com",
    subject="Widget pricing inquiry",
    date="Mon, 22 Apr 2026 10:00:00 +0000",
    body="Hi, I'm interested in ordering about 100 Standard Widgets. "
         "Can you confirm the pricing and any volume discounts?",
    headers={"message-id": "<abc123@partner.com>"},
    labels=["INBOX", "UNREAD"],
)

NOREPLY_EMAIL = EmailMessage(
    message_id="msg-e2e-2",
    thread_id="thread-e2e-2",
    from_address="noreply@notifications.example.com",
    to_address="sales@acme.com",
    subject="Your weekly digest",
    date="Mon, 22 Apr 2026 10:05:00 +0000",
    body="Here is your weekly activity summary...",
    headers={},
    labels=["INBOX", "UNREAD"],
)

OOF_EMAIL = EmailMessage(
    message_id="msg-e2e-3",
    thread_id="thread-e2e-3",
    from_address="colleague@other.com",
    to_address="sales@acme.com",
    subject="Out of Office Re: Meeting",
    date="Mon, 22 Apr 2026 10:10:00 +0000",
    body="I am currently out of the office...",
    headers={},
    labels=["INBOX", "UNREAD"],
)

SPAM_EMAIL = EmailMessage(
    message_id="msg-e2e-4",
    thread_id="thread-e2e-4",
    from_address="spammer@bad.com",
    to_address="sales@acme.com",
    subject="You won a prize!",
    date="Mon, 22 Apr 2026 10:15:00 +0000",
    body="Click here to claim...",
    headers={},
    labels=["SPAM"],
)


@pytest.fixture
def state(tmp_path: Path):
    db = tmp_path / "e2e.sqlite"
    key = Fernet.generate_key().decode()
    s = StateStore(db, key)
    s.save_oauth_tokens(OAuthTokens(
        account_email="sales@acme.com",
        access_token="tok", refresh_token="ref",
        expires_at=0, scope="s", created_at=0, updated_at=0,
    ))
    yield s
    s.close()


@pytest.fixture
def context(tmp_path: Path):
    f = tmp_path / "context.md"
    f.write_text(CONTEXT_MD)
    return ContextLoader(f)


@pytest.fixture
def provider():
    p = MagicMock()
    p.list_sent_thread_ids.return_value = set()
    p.check_draft_exists.return_value = False
    p.is_valid_inbound.side_effect = lambda msg: "SPAM" not in msg.labels
    p.save_draft.return_value = "draft-e2e-1"
    p.get_current_history_id.return_value = "99999"
    p.invalidate_drafts_cache.return_value = None
    return p


@pytest.fixture
def llm():
    m = MagicMock(spec=LLMClassifierDrafter)
    m.classify_and_draft.return_value = LLMResult(
        decision="DRAFT",
        reason="Pricing inquiry matches product catalog in context",
        draft_body=(
            "Hi,\n\n"
            "Thank you for your interest in our Standard Widgets! "
            "The pricing is $10/unit with a minimum order quantity of 50 units. "
            "For an order of 100, that would be $1,000.\n\n"
            "Please let us know if you'd like to proceed or have any other questions.\n\n"
            "Best regards,\nAcme Widgets Team"
        ),
        draft_subject=None,
        cost_usd=0.012,
        input_tokens=1500,
        output_tokens=200,
    )
    return m


class TestE2EFullCycle:
    def test_mixed_batch_processes_correctly(self, state, context, provider, llm):
        pipeline = PipelineRunner(
            provider=provider,
            state=state,
            context=context,
            llm=llm,
            user_email="sales@acme.com",
            daily_cost_cap=5.0,
        )

        batch = [INBOUND_EMAIL, NOREPLY_EMAIL, OOF_EMAIL, SPAM_EMAIL]
        stats = pipeline.process_batch(batch)

        assert stats.total == 4
        assert stats.drafted == 1
        assert stats.filtered == 3
        assert stats.errors == 0
        assert stats.cost_usd == pytest.approx(0.012, abs=0.001)

        assert state.is_processed("msg-e2e-1")
        assert state.is_processed("msg-e2e-2")
        assert state.is_processed("msg-e2e-3")
        assert state.is_processed("msg-e2e-4")

        provider.save_draft.assert_called_once()

        llm.classify_and_draft.assert_called_once()
        call_args = llm.classify_and_draft.call_args
        assert call_args[0][0].message_id == "msg-e2e-1"

    def test_idempotent_reprocessing(self, state, context, provider, llm):
        pipeline = PipelineRunner(
            provider=provider, state=state, context=context,
            llm=llm, user_email="sales@acme.com",
        )

        pipeline.process_batch([INBOUND_EMAIL])
        assert llm.classify_and_draft.call_count == 1

        llm.classify_and_draft.reset_mock()
        pipeline.process_batch([INBOUND_EMAIL])
        llm.classify_and_draft.assert_not_called()

    def test_cost_cap_enforcement(self, state, context, provider, llm):
        import time as t

        now = int(t.time())
        for i in range(10):
            state._conn.execute(
                "INSERT INTO processed_messages "
                "(message_id, thread_id, account_email, processed_at, "
                "layer1_result, llm_cost_usd, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"old-{i}", f"t-{i}", "sales@acme.com", now,
                 "passed", 0.6, "completed"),
            )
        state._conn.commit()

        pipeline = PipelineRunner(
            provider=provider, state=state, context=context,
            llm=llm, user_email="sales@acme.com", daily_cost_cap=5.0,
        )
        pipeline.process_batch([INBOUND_EMAIL])
        llm.classify_and_draft.assert_not_called()

    def test_audit_trail(self, state, context, provider, llm):
        pipeline = PipelineRunner(
            provider=provider, state=state, context=context,
            llm=llm, user_email="sales@acme.com",
        )
        pipeline.process_batch([INBOUND_EMAIL])

        rows = state._conn.execute(
            "SELECT * FROM audit_log WHERE event = 'draft_created'"
        ).fetchall()
        assert len(rows) == 1

        row = state._conn.execute(
            "SELECT * FROM processed_messages WHERE message_id = 'msg-e2e-1'"
        ).fetchone()
        assert row["llm_decision"] == "DRAFT"
        assert row["draft_id"] == "draft-e2e-1"
        assert row["llm_cost_usd"] == pytest.approx(0.012)


class TestE2EPollerIntegration:
    def test_poll_once_with_bootstrap(self, state, context, provider, llm):
        provider.fetch_unread_inbound.return_value = [INBOUND_EMAIL, NOREPLY_EMAIL]

        poller = Poller(
            provider=provider, state=state, context=context,
            llm=llm, config=Config(), user_email="sales@acme.com",
        )
        poller._poll_once()

        assert state.is_processed("msg-e2e-1")
        assert state.is_processed("msg-e2e-2")

        cp = state.get_checkpoint("sales@acme.com")
        assert cp["last_history_id"] == "99999"

    def test_poll_once_with_history(self, state, context, provider, llm):
        state.update_checkpoint("sales@acme.com", "50000")
        provider.fetch_by_history.return_value = ([INBOUND_EMAIL], "50001")

        poller = Poller(
            provider=provider, state=state, context=context,
            llm=llm, config=Config(), user_email="sales@acme.com",
        )
        poller._poll_once()

        assert state.is_processed("msg-e2e-1")
        cp = state.get_checkpoint("sales@acme.com")
        assert cp["last_history_id"] == "50001"
