"""Tests for LLM classifier/drafter — API calls mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ai_drafter.gmail import EmailMessage
from ai_drafter.llm import (
    LLMClassifierDrafter,
    _sanitize_header,
    calculate_cost,
)


def _msg(
    body: str = "I need a quote for 100 widgets",
    from_addr: str = "client@partner.com",
    subject: str = "Quote request",
) -> EmailMessage:
    return EmailMessage(
        message_id="msg-1",
        thread_id="thread-1",
        from_address=from_addr,
        to_address="me@company.com",
        subject=subject,
        date="Mon, 1 Jan 2024 12:00:00 +0000",
        body=body,
        headers={},
    )


def _mock_response(text: str, input_tokens: int = 500, output_tokens: int = 200):
    resp = MagicMock()
    content_block = MagicMock()
    content_block.text = text
    resp.content = [content_block]
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    resp.usage.cache_read_input_tokens = 0
    return resp


class TestSanitizeHeader:
    def test_strips_control_chars(self):
        assert _sanitize_header("hello\x00world") == "helloworld"

    def test_replaces_newlines(self):
        assert _sanitize_header("line1\nline2") == "line1 line2"

    def test_truncates_long(self):
        result = _sanitize_header("A" * 600)
        assert len(result) == 500

    def test_normal_header_unchanged(self):
        assert _sanitize_header("John Doe <john@example.com>") == "John Doe <john@example.com>"


class TestCalculateCost:
    def test_sonnet_cost(self):
        usage = MagicMock()
        usage.input_tokens = 1000
        usage.output_tokens = 500
        usage.cache_read_input_tokens = 0
        cost = calculate_cost(usage, "claude-sonnet-4-6")
        expected = (1000 / 1_000_000) * 3.0 + (500 / 1_000_000) * 15.0
        assert abs(cost - expected) < 0.000001

    def test_with_cache_read(self):
        usage = MagicMock()
        usage.input_tokens = 1000
        usage.output_tokens = 500
        usage.cache_read_input_tokens = 2000
        cost = calculate_cost(usage, "claude-sonnet-4-6")
        expected = (
            (1000 / 1_000_000) * 3.0
            + (500 / 1_000_000) * 15.0
            + (2000 / 1_000_000) * 0.30
        )
        assert abs(cost - expected) < 0.000001

    def test_unknown_model_uses_defaults(self):
        usage = MagicMock()
        usage.input_tokens = 1000
        usage.output_tokens = 500
        usage.cache_read_input_tokens = 0
        cost = calculate_cost(usage, "unknown-model")
        assert cost > 0


class TestClassifyAndDraft:
    @patch("ai_drafter.llm.anthropic.Anthropic")
    def test_draft_decision(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        response_json = (
            '{"decision": "DRAFT", "reason": "Quote request matches context", '
            '"draft_body": "Hello, our widgets cost $10 each.", "draft_subject": null}'
        )
        mock_client.messages.create.return_value = _mock_response(response_json)

        drafter = LLMClassifierDrafter(api_key="test-key")
        result = drafter.classify_and_draft(_msg(), "We sell widgets at $10 each.")

        assert result.decision == "DRAFT"
        assert result.draft_body == "Hello, our widgets cost $10 each."
        assert result.cost_usd > 0

    @patch("ai_drafter.llm.anthropic.Anthropic")
    def test_skip_decision(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        response_json = (
            '{"decision": "SKIP", "reason": "Newsletter, not actionable", '
            '"draft_body": null, "draft_subject": null}'
        )
        mock_client.messages.create.return_value = _mock_response(response_json)

        drafter = LLMClassifierDrafter(api_key="test-key")
        result = drafter.classify_and_draft(_msg(body="Weekly digest"), "Context")

        assert result.decision == "SKIP"
        assert result.draft_body is None

    @patch("ai_drafter.llm.anthropic.Anthropic")
    def test_invalid_json_returns_skip(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response("not json at all")

        drafter = LLMClassifierDrafter(api_key="test-key")
        result = drafter.classify_and_draft(_msg(), "Context")

        assert result.decision == "SKIP"
        assert "unparseable" in result.reason

    @patch("ai_drafter.llm.anthropic.Anthropic")
    def test_json_embedded_in_prose(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        text = (
            'Here is the result: {"decision": "DRAFT", "reason": "ok",'
            ' "draft_body": "Hi", "draft_subject": null}'
        )
        mock_client.messages.create.return_value = _mock_response(text)

        drafter = LLMClassifierDrafter(api_key="test-key")
        result = drafter.classify_and_draft(_msg(), "Context")

        assert result.decision == "DRAFT"
        assert result.draft_body == "Hi"

    @patch("ai_drafter.llm.anthropic.Anthropic")
    def test_invalid_decision_defaults_skip(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        text = (
            '{"decision": "MAYBE", "reason": "unsure",'
            ' "draft_body": null, "draft_subject": null}'
        )
        mock_client.messages.create.return_value = _mock_response(text)

        drafter = LLMClassifierDrafter(api_key="test-key")
        result = drafter.classify_and_draft(_msg(), "Context")

        assert result.decision == "SKIP"

    @patch("ai_drafter.llm.anthropic.Anthropic")
    def test_prompt_caching_enabled(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        text = '{"decision": "SKIP", "reason": "test", "draft_body": null, "draft_subject": null}'
        mock_client.messages.create.return_value = _mock_response(text)

        drafter = LLMClassifierDrafter(api_key="test-key")
        drafter.classify_and_draft(_msg(), "Context")

        call_kwargs = mock_client.messages.create.call_args[1]
        system = call_kwargs["system"]
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    @patch("ai_drafter.llm.anthropic.Anthropic")
    def test_header_sanitization_in_prompt(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        text = '{"decision": "SKIP", "reason": "test", "draft_body": null, "draft_subject": null}'
        mock_client.messages.create.return_value = _mock_response(text)

        drafter = LLMClassifierDrafter(api_key="test-key")
        msg = _msg(from_addr="evil\x00sender@bad.com", subject="Inject\nNewline")
        drafter.classify_and_draft(msg, "Context")

        call_kwargs = mock_client.messages.create.call_args[1]
        user_msg = call_kwargs["messages"][0]["content"]
        assert "\x00" not in user_msg
        assert "\n" not in user_msg.split("---")[1].split("\n")[1]
