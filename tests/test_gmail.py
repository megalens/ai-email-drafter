"""Tests for Gmail provider — all API calls mocked."""

from __future__ import annotations

import base64
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from ai_drafter.gmail import EmailMessage, GmailProvider


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _make_message_resource(
    msg_id: str = "msg-1",
    thread_id: str = "thread-1",
    subject: str = "Hello",
    from_addr: str = "sender@example.com",
    to_addr: str = "me@example.com",
    date: str = "Mon, 1 Jan 2024 12:00:00 +0000",
    body_text: str = "Test body",
    labels: list[str] | None = None,
    mime_type: str = "text/plain",
    extra_headers: dict[str, str] | None = None,
) -> dict:
    headers = [
        {"name": "Subject", "value": subject},
        {"name": "From", "value": from_addr},
        {"name": "To", "value": to_addr},
        {"name": "Date", "value": date},
    ]
    if extra_headers:
        for k, v in extra_headers.items():
            headers.append({"name": k, "value": v})

    return {
        "id": msg_id,
        "threadId": thread_id,
        "labelIds": labels or ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": mime_type,
            "headers": headers,
            "body": {"data": _b64(body_text)},
        },
    }


def _make_multipart_message(
    msg_id: str = "msg-1",
    thread_id: str = "thread-1",
    plain_text: str = "Plain body",
    html_text: str = "<p>HTML body</p>",
) -> dict:
    return {
        "id": msg_id,
        "threadId": thread_id,
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Subject", "value": "Multi"},
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64(plain_text)},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64(html_text)},
                },
            ],
        },
    }


@pytest.fixture
def mock_service():
    return MagicMock()


@pytest.fixture
def provider(mock_service):
    creds = MagicMock()
    with patch("ai_drafter.gmail.build", return_value=mock_service):
        p = GmailProvider(creds, "me@example.com")
    return p


class TestFetchUnreadInbound:
    def test_returns_messages(self, provider, mock_service):
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg-1"}, {"id": "msg-2"}],
        }
        msg_resource = _make_message_resource()
        mock_service.users().messages().get().execute.return_value = msg_resource

        since = datetime(2024, 1, 1)
        result = provider.fetch_unread_inbound(since)

        assert len(result) == 2
        assert result[0].message_id == "msg-1"
        assert result[0].subject == "Hello"
        assert result[0].from_address == "sender@example.com"

    def test_empty_inbox(self, provider, mock_service):
        mock_service.users().messages().list().execute.return_value = {}

        since = datetime(2024, 1, 1)
        result = provider.fetch_unread_inbound(since)

        assert result == []


class TestFetchByHistory:
    def test_returns_new_messages(self, provider, mock_service):
        msg_resource = _make_message_resource(msg_id="msg-new")
        mock_service.users().history().list().execute.return_value = {
            "historyId": "12345",
            "history": [
                {
                    "messagesAdded": [
                        {"message": {"id": "msg-new"}},
                    ],
                },
            ],
        }
        mock_service.users().messages().get().execute.return_value = msg_resource

        messages, new_hid = provider.fetch_by_history("10000")

        assert len(messages) == 1
        assert messages[0].message_id == "msg-new"
        assert new_hid == "12345"

    def test_handles_404(self, provider, mock_service):
        mock_service.users().history().list().execute.side_effect = Exception("404 Not Found")

        messages, hid = provider.fetch_by_history("10000")

        assert messages == []
        assert hid is None

    def test_handles_410(self, provider, mock_service):
        mock_service.users().history().list().execute.side_effect = Exception("410 Gone")

        messages, hid = provider.fetch_by_history("10000")

        assert messages == []
        assert hid is None


class TestExtractBody:
    def test_plain_text(self, provider):
        payload = {
            "mimeType": "text/plain",
            "body": {"data": _b64("Hello world")},
        }
        assert provider._extract_body(payload) == "Hello world"

    def test_html_converted(self, provider):
        html = "<p>Hello</p><br>World"
        payload = {
            "mimeType": "text/html",
            "body": {"data": _b64(html)},
        }
        result = provider._extract_body(payload)
        assert "Hello" in result
        assert "World" in result
        assert "<p>" not in result

    def test_multipart_prefers_plain(self, provider):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("Plain")}},
                {"mimeType": "text/html", "body": {"data": _b64("<b>HTML</b>")}},
            ],
        }
        assert provider._extract_body(payload) == "Plain"

    def test_multipart_falls_back_to_html(self, provider):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<b>Bold</b>")}},
            ],
        }
        result = provider._extract_body(payload)
        assert "Bold" in result
        assert "<b>" not in result

    def test_nested_multipart(self, provider):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64("Nested plain")}},
                    ],
                },
            ],
        }
        result = provider._extract_body(payload)
        assert "Nested plain" in result

    def test_empty_payload(self, provider):
        payload = {"mimeType": "multipart/mixed", "parts": []}
        assert provider._extract_body(payload) == ""


class TestHtmlToText:
    def test_strips_tags(self):
        assert GmailProvider._html_to_text("<b>bold</b>") == "bold"

    def test_br_to_newline(self):
        result = GmailProvider._html_to_text("line1<br>line2")
        assert "line1" in result
        assert "line2" in result

    def test_unescape_entities(self):
        assert GmailProvider._html_to_text("&amp; &lt;") == "& <"


class TestStripSignature:
    def test_strips_double_dash(self):
        body = "Hello\n\n-- \nJohn Doe\nCEO"
        result = GmailProvider._strip_signature(body)
        assert result == "Hello"

    def test_strips_sent_from_iphone(self):
        body = "Reply text\nSent from my iPhone"
        result = GmailProvider._strip_signature(body)
        assert result == "Reply text"

    def test_strips_underscores(self):
        body = "Content\n___\nSignature"
        result = GmailProvider._strip_signature(body)
        assert result == "Content"

    def test_no_signature_unchanged(self):
        body = "Just a normal email body"
        assert GmailProvider._strip_signature(body) == body


class TestSaveDraft:
    def test_creates_draft(self, provider, mock_service):
        mock_service.users().drafts().create().execute.return_value = {"id": "draft-1"}

        original = EmailMessage(
            message_id="msg-1",
            thread_id="thread-1",
            from_address="sender@example.com",
            to_address="me@example.com",
            subject="Original Subject",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            body="Original body",
            headers={"message-id": "<abc@mail.com>"},
        )
        draft_id = provider.save_draft("thread-1", "Reply body", original)

        assert draft_id == "draft-1"
        call_args = mock_service.users().drafts().create.call_args
        body = call_args[1]["body"]
        assert body["message"]["threadId"] == "thread-1"

    def test_uses_reply_to_header(self, provider, mock_service):
        mock_service.users().drafts().create().execute.return_value = {"id": "draft-2"}

        original = EmailMessage(
            message_id="msg-1",
            thread_id="thread-1",
            from_address="sender@example.com",
            to_address="me@example.com",
            subject="Test",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            body="Body",
            headers={"reply-to": "replyto@example.com", "message-id": "<x@mail.com>"},
        )
        provider.save_draft("thread-1", "Reply", original)

        call_args = mock_service.users().drafts().create.call_args
        raw = call_args[1]["body"]["message"]["raw"]
        decoded = base64.urlsafe_b64decode(raw).decode()
        assert "replyto@example.com" in decoded


class TestCheckDraftExists:
    def test_caches_drafts(self, provider, mock_service):
        mock_service.users().drafts().list().execute.return_value = {
            "drafts": [
                {"id": "d1", "message": {"threadId": "thread-1"}},
                {"id": "d2", "message": {"threadId": "thread-2"}},
            ],
        }
        assert provider.check_draft_exists("thread-1") is True
        assert provider.check_draft_exists("thread-3") is False

    def test_invalidate_cache(self, provider, mock_service):
        mock_service.users().drafts().list().execute.return_value = {"drafts": []}
        assert provider.check_draft_exists("thread-1") is False

        provider.invalidate_drafts_cache()
        mock_service.users().drafts().list().execute.return_value = {
            "drafts": [{"id": "d1", "message": {"threadId": "thread-1"}}],
        }
        assert provider.check_draft_exists("thread-1") is True


class TestIsValidInbound:
    def test_inbox_message_valid(self, provider):
        msg = EmailMessage(
            message_id="m1", thread_id="t1", from_address="a@b.com",
            to_address="me@b.com", subject="Hi", date="", body="",
            labels=["INBOX", "UNREAD"],
        )
        assert provider.is_valid_inbound(msg) is True

    def test_sent_message_invalid(self, provider):
        msg = EmailMessage(
            message_id="m1", thread_id="t1", from_address="a@b.com",
            to_address="me@b.com", subject="Hi", date="", body="",
            labels=["INBOX", "SENT"],
        )
        assert provider.is_valid_inbound(msg) is False

    def test_spam_invalid(self, provider):
        msg = EmailMessage(
            message_id="m1", thread_id="t1", from_address="a@b.com",
            to_address="me@b.com", subject="Hi", date="", body="",
            labels=["SPAM"],
        )
        assert provider.is_valid_inbound(msg) is False

    def test_no_inbox_label_invalid(self, provider):
        msg = EmailMessage(
            message_id="m1", thread_id="t1", from_address="a@b.com",
            to_address="me@b.com", subject="Hi", date="", body="",
            labels=["UNREAD"],
        )
        assert provider.is_valid_inbound(msg) is False


class TestGetCurrentHistoryId:
    def test_returns_history_id(self, provider, mock_service):
        mock_service.users().getProfile().execute.return_value = {
            "historyId": "99999",
        }
        assert provider.get_current_history_id() == "99999"


class TestListSentThreadIds:
    def test_returns_thread_ids(self, provider, mock_service):
        mock_service.users().messages().list().execute.return_value = {
            "messages": [
                {"id": "m1", "threadId": "t1"},
                {"id": "m2", "threadId": "t2"},
                {"id": "m3", "threadId": "t1"},
            ],
        }
        since = datetime(2024, 1, 1)
        result = provider.list_sent_thread_ids(since)
        assert result == {"t1", "t2"}


class TestBodyTruncation:
    def test_long_body_truncated(self, mock_service):
        creds = MagicMock()
        with patch("ai_drafter.gmail.build", return_value=mock_service):
            p = GmailProvider(creds, "me@example.com", max_body_chars=20)

        long_text = "A" * 100
        msg_resource = _make_message_resource(body_text=long_text)
        mock_service.users().messages().get().execute.return_value = msg_resource

        msg = p._get_message("msg-1")
        assert len(msg.body) == 20
