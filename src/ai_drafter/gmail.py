"""Gmail provider — OAuth, fetch inbound, save drafts."""

from __future__ import annotations

import base64
import contextlib
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from typing import Protocol

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger("ai_drafter")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

_SIG_PATTERNS = [
    re.compile(r"^-- \s*$", re.MULTILINE),
    re.compile(r"^_{3,}\s*$", re.MULTILINE),
    re.compile(r"^Sent from my (iPhone|iPad|Galaxy|Android)", re.MULTILINE),
    re.compile(r"^Get Outlook for", re.MULTILINE),
]

_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class EmailMessage:
    message_id: str
    thread_id: str
    from_address: str
    to_address: str
    subject: str
    date: str
    body: str
    headers: dict[str, str] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)


class EmailProvider(Protocol):
    def fetch_unread_inbound(self, since: datetime) -> list[EmailMessage]: ...
    def save_draft(
        self, thread_id: str, body: str, original: EmailMessage,
        subject: str | None = None,
    ) -> str: ...
    def list_sent_thread_ids(self, since: datetime) -> set[str]: ...
    def check_draft_exists(self, thread_id: str) -> bool: ...


class GmailProvider:
    """V1 Gmail provider using google-api-python-client."""

    def __init__(
        self,
        credentials: Credentials,
        user_email: str,
        max_body_chars: int = 16000,
    ) -> None:
        self._creds = credentials
        self._user_email = user_email
        self._max_body_chars = max_body_chars
        self._service = build("gmail", "v1", credentials=credentials)
        self._drafts_cache: set[str] | None = None

    @classmethod
    def from_oauth(
        cls,
        client_secrets_path: str,
        token_path: str,
        user_email: str,
    ) -> GmailProvider:
        creds = None
        with contextlib.suppress(FileNotFoundError, ValueError):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secrets_path, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as f:
            f.write(creds.to_json())

        return cls(creds, user_email)

    def fetch_unread_inbound(
        self, since: datetime, max_results: int = 50
    ) -> list[EmailMessage]:
        query = f"is:unread in:inbox after:{since.strftime('%Y/%m/%d')}"
        results = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])
        out = []
        for msg_stub in messages:
            msg = self._get_message(msg_stub["id"])
            if msg:
                out.append(msg)
        return out

    def fetch_by_history(
        self, history_id: str
    ) -> tuple[list[EmailMessage], str | None]:
        try:
            results = (
                self._service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=history_id,
                    historyTypes=["messageAdded"],
                )
                .execute()
            )
        except Exception as e:
            if "404" in str(e) or "410" in str(e):
                return [], None
            raise

        new_history_id = results.get("historyId")
        messages = []
        for record in results.get("history", []):
            for added in record.get("messagesAdded", []):
                msg_data = added.get("message", {})
                msg_id = msg_data.get("id")
                if msg_id:
                    msg = self._get_message(msg_id)
                    if msg:
                        messages.append(msg)
        return messages, new_history_id

    def _get_message(self, msg_id: str) -> EmailMessage | None:
        raw = (
            self._service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )
        headers = {}
        for h in raw.get("payload", {}).get("headers", []):
            headers[h["name"].lower()] = h["value"]

        labels = raw.get("labelIds", [])
        body = self._extract_body(raw.get("payload", {}))
        body = self._strip_signature(body)
        if len(body) > self._max_body_chars:
            body = body[: self._max_body_chars]

        return EmailMessage(
            message_id=raw["id"],
            thread_id=raw["threadId"],
            from_address=headers.get("from", ""),
            to_address=headers.get("to", ""),
            subject=headers.get("subject", ""),
            date=headers.get("date", ""),
            body=body,
            headers=headers,
            labels=labels,
        )

    def _extract_body(self, payload: dict) -> str:
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        if mime_type == "text/html":
            data = payload.get("body", {}).get("data", "")
            html_text = base64.urlsafe_b64decode(data).decode(
                "utf-8", errors="replace"
            )
            return self._html_to_text(html_text)

        parts = payload.get("parts", [])
        if not parts:
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode(
                    "utf-8", errors="replace"
                )
            return ""

        plain_parts = []
        html_parts = []
        for part in parts:
            part_mime = part.get("mimeType", "")
            if part_mime == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    plain_parts.append(
                        base64.urlsafe_b64decode(data).decode(
                            "utf-8", errors="replace"
                        )
                    )
            elif part_mime == "text/html":
                data = part.get("body", {}).get("data", "")
                if data:
                    html_parts.append(
                        base64.urlsafe_b64decode(data).decode(
                            "utf-8", errors="replace"
                        )
                    )
            elif "parts" in part:
                result = self._extract_body(part)
                if result:
                    plain_parts.append(result)

        if plain_parts:
            return "\n".join(plain_parts)
        if html_parts:
            return "\n".join(self._html_to_text(h) for h in html_parts)
        return ""

    @staticmethod
    def _html_to_text(html_text: str) -> str:
        text = html_text.replace("<br>", "\n").replace("<br/>", "\n")
        text = re.sub(r"<p[^>]*>", "\n", text)
        text = _HTML_TAG_RE.sub("", text)
        text = html.unescape(text)
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(lines).strip()

    @staticmethod
    def _strip_signature(body: str) -> str:
        for pattern in _SIG_PATTERNS:
            match = pattern.search(body)
            if match:
                body = body[: match.start()].rstrip()
                break
        return body

    def save_draft(
        self,
        thread_id: str,
        body: str,
        original: EmailMessage,
        subject: str | None = None,
    ) -> str:
        reply_to = original.headers.get("reply-to", original.from_address)
        msg_subject = subject or f"Re: {original.subject}"
        in_reply_to = original.headers.get("message-id", "")
        references = original.headers.get("references", "")
        if in_reply_to:
            references = f"{references} {in_reply_to}".strip()

        mime_msg = MIMEText(body, "plain", "utf-8")
        mime_msg["To"] = reply_to
        mime_msg["Subject"] = msg_subject
        mime_msg["In-Reply-To"] = in_reply_to
        mime_msg["References"] = references

        encoded = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
        draft = (
            self._service.users()
            .drafts()
            .create(
                userId="me",
                body={
                    "message": {
                        "raw": encoded,
                        "threadId": thread_id,
                    }
                },
            )
            .execute()
        )
        draft_id = draft["id"]
        logger.info("Draft created: %s in thread %s", draft_id, thread_id)
        return draft_id

    def list_sent_thread_ids(self, since: datetime) -> set[str]:
        query = f"in:sent after:{since.strftime('%Y/%m/%d')}"
        results = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=100)
            .execute()
        )
        thread_ids = set()
        for msg in results.get("messages", []):
            thread_ids.add(msg["threadId"])
        return thread_ids

    def check_draft_exists(self, thread_id: str) -> bool:
        if self._drafts_cache is None:
            self._refresh_drafts_cache()
        return thread_id in self._drafts_cache

    def _refresh_drafts_cache(self) -> None:
        self._drafts_cache = set()
        results = (
            self._service.users()
            .drafts()
            .list(userId="me", maxResults=100)
            .execute()
        )
        for draft in results.get("drafts", []):
            msg = draft.get("message", {})
            tid = msg.get("threadId")
            if tid:
                self._drafts_cache.add(tid)

    def invalidate_drafts_cache(self) -> None:
        self._drafts_cache = None

    def get_current_history_id(self) -> str:
        profile = (
            self._service.users().getProfile(userId="me").execute()
        )
        return profile["historyId"]

    def is_valid_inbound(self, msg: EmailMessage) -> bool:
        dominated = {"INBOX"}
        excluded = {"SPAM", "TRASH", "SENT"}
        label_set = set(msg.labels)
        return bool(label_set & dominated) and not bool(label_set & excluded)
