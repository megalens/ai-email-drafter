"""Tests for Poller."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from ai_drafter.config import Config
from ai_drafter.context import ContextLoader
from ai_drafter.gmail import EmailMessage
from ai_drafter.llm import LLMClassifierDrafter
from ai_drafter.poller import Poller
from ai_drafter.state import OAuthTokens, StateStore


def _msg(msg_id: str = "msg-1") -> EmailMessage:
    return EmailMessage(
        message_id=msg_id,
        thread_id=f"thread-{msg_id}",
        from_address="client@external.com",
        to_address="me@company.com",
        subject="Hello",
        date="Mon, 1 Jan 2024 12:00:00 +0000",
        body="Test body",
        headers={},
        labels=["INBOX", "UNREAD"],
    )


@pytest.fixture
def state(tmp_path: Path):
    db = tmp_path / "test.sqlite"
    key = Fernet.generate_key().decode()
    s = StateStore(db, key)
    s.save_oauth_tokens(OAuthTokens(
        account_email="me@company.com",
        access_token="tok", refresh_token="ref",
        expires_at=0, scope="s", created_at=0, updated_at=0,
    ))
    yield s
    s.close()


@pytest.fixture
def context(tmp_path: Path):
    f = tmp_path / "context.md"
    f.write_text("# Context\nWe do things.")
    return ContextLoader(f)


@pytest.fixture
def provider():
    p = MagicMock()
    p.list_sent_thread_ids.return_value = set()
    p.check_draft_exists.return_value = False
    p.is_valid_inbound.return_value = True
    p.save_draft.return_value = "draft-1"
    p.get_current_history_id.return_value = "99999"
    p.fetch_unread_inbound.return_value = []
    p.fetch_by_history.return_value = ([], "12345")
    p.invalidate_drafts_cache.return_value = None
    return p


@pytest.fixture
def llm():
    return MagicMock(spec=LLMClassifierDrafter)


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def poller(provider, state, context, llm, config):
    return Poller(
        provider=provider,
        state=state,
        context=context,
        llm=llm,
        config=config,
        user_email="me@company.com",
    )


class TestPollOnce:
    def test_bootstrap_on_first_run(self, poller, provider):
        poller._poll_once()
        provider.fetch_unread_inbound.assert_called_once()
        provider.fetch_by_history.assert_not_called()

    def test_history_fetch_with_checkpoint(self, poller, provider, state):
        state.update_checkpoint("me@company.com", "50000")
        provider.fetch_by_history.return_value = ([_msg()], "50001")

        poller._poll_once()

        provider.fetch_by_history.assert_called_once_with("50000")
        provider.fetch_unread_inbound.assert_not_called()

    def test_fallback_when_history_expired(self, poller, provider, state):
        state.update_checkpoint("me@company.com", "50000")
        provider.fetch_by_history.return_value = ([], None)

        poller._poll_once()

        provider.fetch_by_history.assert_called_once()
        provider.fetch_unread_inbound.assert_called_once()

    def test_updates_checkpoint(self, poller, provider, state):
        provider.fetch_unread_inbound.return_value = []
        provider.get_current_history_id.return_value = "77777"

        poller._poll_once()

        cp = state.get_checkpoint("me@company.com")
        assert cp["last_history_id"] == "77777"

    def test_invalidates_drafts_cache(self, poller, provider):
        poller._poll_once()
        provider.invalidate_drafts_cache.assert_called_once()


class TestSignalHandling:
    def test_stop_sets_flag(self, poller):
        poller.stop()
        assert poller._running is False

    def test_signal_handler_stops(self, poller):
        poller._handle_signal(15, None)
        assert poller._running is False
