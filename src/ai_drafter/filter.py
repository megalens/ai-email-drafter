"""Layer 1 pre-filter — rule-based skip before LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ai_drafter.gmail import EmailMessage, EmailProvider

_NOREPLY_RE = re.compile(
    r"^(noreply|no-reply|notifications?|newsletter|mailer-daemon|"
    r"automated|do-not-reply|support)@",
    re.IGNORECASE,
)

_AUTO_HEADERS = frozenset({
    "auto-submitted",
    "list-unsubscribe",
    "x-auto-response-suppress",
})

_AUTO_SUBJECT_RE = re.compile(
    r"^(delivery status|undeliverable|automatic reply|out of office)",
    re.IGNORECASE,
)


def _extract_email(addr: str) -> str:
    match = re.search(r"<([^>]+)>", addr)
    if match:
        return match.group(1).lower()
    return addr.strip().lower()


def _extract_domain(addr: str) -> str:
    email_addr = _extract_email(addr)
    parts = email_addr.split("@")
    return parts[1] if len(parts) == 2 else ""


@dataclass
class FilterResult:
    skip: bool
    rule: str


class Layer1Filter:
    """Applies V1 hard rules to decide if a message should skip the LLM."""

    def __init__(self, user_email: str) -> None:
        self._user_email = user_email.lower()
        self._user_domain = _extract_domain(user_email)

    def apply(
        self,
        msg: EmailMessage,
        sent_thread_ids: set[str],
        provider: EmailProvider,
    ) -> FilterResult:
        if self._is_noreply(msg):
            return FilterResult(skip=True, rule="noreply_sender")

        if self._has_auto_headers(msg):
            return FilterResult(skip=True, rule="auto_header")

        if self._is_internal(msg):
            return FilterResult(skip=True, rule="internal_sender")

        if msg.thread_id in sent_thread_ids:
            return FilterResult(skip=True, rule="already_replied")

        if provider.check_draft_exists(msg.thread_id):
            return FilterResult(skip=True, rule="draft_exists")

        if not provider.is_valid_inbound(msg):
            return FilterResult(skip=True, rule="invalid_labels")

        if self._is_auto_subject(msg):
            return FilterResult(skip=True, rule="auto_subject")

        return FilterResult(skip=False, rule="passed")

    def _is_noreply(self, msg: EmailMessage) -> bool:
        addr = _extract_email(msg.from_address)
        return bool(_NOREPLY_RE.match(addr))

    def _has_auto_headers(self, msg: EmailMessage) -> bool:
        header_keys = {k.lower() for k in msg.headers}
        if header_keys & _AUTO_HEADERS:
            return True
        precedence = msg.headers.get("precedence", "").lower()
        return precedence == "bulk"

    def _is_internal(self, msg: EmailMessage) -> bool:
        sender_domain = _extract_domain(msg.from_address)
        return sender_domain == self._user_domain and self._user_domain != ""

    def _is_auto_subject(self, msg: EmailMessage) -> bool:
        return bool(_AUTO_SUBJECT_RE.match(msg.subject.strip()))
