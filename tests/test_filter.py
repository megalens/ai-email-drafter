"""Tests for Layer 1 pre-filter rules."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ai_drafter.filter import Layer1Filter, _extract_domain, _extract_email
from ai_drafter.gmail import EmailMessage


def _msg(
    from_address: str = "sender@external.com",
    to_address: str = "me@mycompany.com",
    subject: str = "Hello",
    headers: dict | None = None,
    labels: list[str] | None = None,
    thread_id: str = "thread-1",
) -> EmailMessage:
    return EmailMessage(
        message_id="msg-1",
        thread_id=thread_id,
        from_address=from_address,
        to_address=to_address,
        subject=subject,
        date="Mon, 1 Jan 2024 12:00:00 +0000",
        body="Test body",
        headers=headers or {},
        labels=labels or ["INBOX", "UNREAD"],
    )


@pytest.fixture
def provider():
    p = MagicMock()
    p.check_draft_exists.return_value = False
    p.is_valid_inbound.return_value = True
    return p


@pytest.fixture
def filt():
    return Layer1Filter("me@mycompany.com")


class TestHelpers:
    def test_extract_email_bare(self):
        assert _extract_email("user@example.com") == "user@example.com"

    def test_extract_email_angle_brackets(self):
        assert _extract_email("John Doe <john@example.com>") == "john@example.com"

    def test_extract_domain(self):
        assert _extract_domain("user@example.com") == "example.com"

    def test_extract_domain_angle_brackets(self):
        assert _extract_domain("Name <user@example.com>") == "example.com"


class TestNoreplyRule:
    @pytest.mark.parametrize("sender", [
        "noreply@example.com",
        "no-reply@example.com",
        "notifications@example.com",
        "notification@example.com",
        "newsletter@example.com",
        "mailer-daemon@example.com",
        "automated@example.com",
        "do-not-reply@example.com",
        "support@example.com",
        "NOREPLY@EXAMPLE.COM",
        "NoReply <noreply@example.com>",
    ])
    def test_noreply_senders_skipped(self, filt, provider, sender):
        result = filt.apply(_msg(from_address=sender), set(), provider)
        assert result.skip is True
        assert result.rule == "noreply_sender"

    def test_normal_sender_passes(self, filt, provider):
        result = filt.apply(_msg(from_address="john@example.com"), set(), provider)
        assert result.skip is False


class TestAutoHeaders:
    def test_auto_submitted_skipped(self, filt, provider):
        msg = _msg(headers={"auto-submitted": "auto-generated"})
        result = filt.apply(msg, set(), provider)
        assert result.skip is True
        assert result.rule == "auto_header"

    def test_list_unsubscribe_skipped(self, filt, provider):
        msg = _msg(headers={"list-unsubscribe": "<mailto:unsub@list.com>"})
        result = filt.apply(msg, set(), provider)
        assert result.skip is True
        assert result.rule == "auto_header"

    def test_x_auto_response_suppress_skipped(self, filt, provider):
        msg = _msg(headers={"x-auto-response-suppress": "OOF"})
        result = filt.apply(msg, set(), provider)
        assert result.skip is True
        assert result.rule == "auto_header"

    def test_precedence_bulk_skipped(self, filt, provider):
        msg = _msg(headers={"precedence": "bulk"})
        result = filt.apply(msg, set(), provider)
        assert result.skip is True
        assert result.rule == "auto_header"

    def test_precedence_normal_passes(self, filt, provider):
        msg = _msg(headers={"precedence": "normal"})
        result = filt.apply(msg, set(), provider)
        assert result.skip is False


class TestInternalSender:
    def test_same_domain_skipped(self, filt, provider):
        msg = _msg(from_address="colleague@mycompany.com")
        result = filt.apply(msg, set(), provider)
        assert result.skip is True
        assert result.rule == "internal_sender"

    def test_different_domain_passes(self, filt, provider):
        msg = _msg(from_address="client@external.com")
        result = filt.apply(msg, set(), provider)
        assert result.skip is False


class TestAlreadyReplied:
    def test_thread_in_sent_skipped(self, filt, provider):
        msg = _msg(thread_id="thread-99")
        result = filt.apply(msg, {"thread-99"}, provider)
        assert result.skip is True
        assert result.rule == "already_replied"

    def test_thread_not_in_sent_passes(self, filt, provider):
        msg = _msg(thread_id="thread-99")
        result = filt.apply(msg, {"thread-100"}, provider)
        assert result.skip is False


class TestDraftExists:
    def test_draft_exists_skipped(self, filt, provider):
        provider.check_draft_exists.return_value = True
        result = filt.apply(_msg(), set(), provider)
        assert result.skip is True
        assert result.rule == "draft_exists"

    def test_no_draft_passes(self, filt, provider):
        provider.check_draft_exists.return_value = False
        result = filt.apply(_msg(), set(), provider)
        assert result.skip is False


class TestInvalidLabels:
    def test_invalid_labels_skipped(self, filt, provider):
        provider.is_valid_inbound.return_value = False
        result = filt.apply(_msg(), set(), provider)
        assert result.skip is True
        assert result.rule == "invalid_labels"


class TestAutoSubject:
    @pytest.mark.parametrize("subject", [
        "Delivery Status Notification",
        "Undeliverable: Your message",
        "Automatic Reply: Out of office",
        "Out of Office Re: Meeting",
    ])
    def test_auto_subjects_skipped(self, filt, provider, subject):
        result = filt.apply(_msg(subject=subject), set(), provider)
        assert result.skip is True
        assert result.rule == "auto_subject"

    def test_normal_subject_passes(self, filt, provider):
        result = filt.apply(_msg(subject="Meeting tomorrow"), set(), provider)
        assert result.skip is False


class TestPassesAllRules:
    def test_legit_email_passes(self, filt, provider):
        msg = _msg(
            from_address="client@partner.com",
            subject="Quote request",
            headers={},
            labels=["INBOX", "UNREAD"],
        )
        result = filt.apply(msg, set(), provider)
        assert result.skip is False
        assert result.rule == "passed"
