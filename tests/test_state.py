"""Tests for SQLite state store."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from ai_drafter.state import OAuthTokens, StateStore


@pytest.fixture
def encryption_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def store(tmp_path: Path, encryption_key: str) -> StateStore:
    db = tmp_path / "test.sqlite"
    s = StateStore(db, encryption_key)
    yield s
    s.close()


@pytest.fixture
def store_with_account(store: StateStore) -> StateStore:
    """Store with a pre-created test account for FK constraints."""
    store.save_oauth_tokens(OAuthTokens(
        account_email="test@example.com",
        access_token="tok", refresh_token="ref",
        expires_at=0, scope="s", created_at=0, updated_at=0,
    ))
    return store


class TestSchema:
    def test_creates_tables(self, store: StateStore):
        cursor = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [r["name"] for r in cursor.fetchall()]
        assert "oauth_tokens" in tables
        assert "processed_messages" in tables
        assert "poll_checkpoints" in tables
        assert "audit_log" in tables
        assert "schema_version" in tables

    def test_wal_mode_enabled(self, store: StateStore):
        row = store._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_idempotent_init(self, tmp_path: Path, encryption_key: str):
        db = tmp_path / "test.sqlite"
        s1 = StateStore(db, encryption_key)
        s1.close()
        s2 = StateStore(db, encryption_key)
        s2.close()


class TestOAuthTokens:
    def test_save_and_retrieve(self, store: StateStore):
        tokens = OAuthTokens(
            account_email="test@example.com",
            access_token="access-123",
            refresh_token="refresh-456",
            expires_at=9999999999,
            scope="gmail.readonly gmail.compose",
            created_at=1000000,
            updated_at=1000000,
        )
        store.save_oauth_tokens(tokens)
        result = store.get_oauth_tokens("test@example.com")

        assert result is not None
        assert result.access_token == "access-123"
        assert result.refresh_token == "refresh-456"
        assert result.expires_at == 9999999999

    def test_tokens_encrypted_at_rest(self, store: StateStore):
        tokens = OAuthTokens(
            account_email="test@example.com",
            access_token="plaintext-access-token",
            refresh_token="plaintext-refresh-token",
            expires_at=9999999999,
            scope="gmail.readonly",
            created_at=1000000,
            updated_at=1000000,
        )
        store.save_oauth_tokens(tokens)

        row = store._conn.execute(
            "SELECT access_token, refresh_token FROM oauth_tokens WHERE account_email = ?",
            ("test@example.com",),
        ).fetchone()
        assert row["access_token"] != "plaintext-access-token"
        assert row["refresh_token"] != "plaintext-refresh-token"

    def test_upsert_updates_existing(self, store: StateStore):
        tokens = OAuthTokens(
            account_email="test@example.com",
            access_token="old-token",
            refresh_token="old-refresh",
            expires_at=1000,
            scope="gmail.readonly",
            created_at=1000000,
            updated_at=1000000,
        )
        store.save_oauth_tokens(tokens)

        tokens2 = OAuthTokens(
            account_email="test@example.com",
            access_token="new-token",
            refresh_token="new-refresh",
            expires_at=2000,
            scope="gmail.readonly gmail.compose",
            created_at=1000000,
            updated_at=1000000,
        )
        store.save_oauth_tokens(tokens2)

        result = store.get_oauth_tokens("test@example.com")
        assert result.access_token == "new-token"
        assert result.refresh_token == "new-refresh"

    def test_get_nonexistent_returns_none(self, store: StateStore):
        assert store.get_oauth_tokens("nobody@example.com") is None

    def test_list_accounts(self, store: StateStore):
        for email in ["a@test.com", "b@test.com"]:
            store.save_oauth_tokens(OAuthTokens(
                account_email=email, access_token="x", refresh_token="y",
                expires_at=0, scope="s", created_at=0, updated_at=0,
            ))
        accounts = store.list_accounts()
        assert set(accounts) == {"a@test.com", "b@test.com"}

    def test_wrong_key_fails_decrypt(self, tmp_path: Path):
        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()
        db = tmp_path / "test.sqlite"

        s1 = StateStore(db, key1)
        s1.save_oauth_tokens(OAuthTokens(
            account_email="test@example.com",
            access_token="secret", refresh_token="secret",
            expires_at=0, scope="s", created_at=0, updated_at=0,
        ))
        s1.close()

        s2 = StateStore(db, key2)
        from cryptography.fernet import InvalidToken
        with pytest.raises(InvalidToken):
            s2.get_oauth_tokens("test@example.com")
        s2.close()


class TestProcessedMessages:
    def test_record_and_check(self, store_with_account: StateStore):
        store = store_with_account
        assert not store.is_processed("msg-1")
        store.record_processed(
            message_id="msg-1", thread_id="thread-1",
            account_email="test@example.com", layer1_result="passed",
            llm_decision="DRAFT", draft_id="draft-1",
        )
        assert store.is_processed("msg-1")

    def test_update_draft_id(self, store_with_account: StateStore):
        store = store_with_account
        store.record_processed(
            message_id="msg-1", thread_id="thread-1",
            account_email="test@example.com", layer1_result="passed",
            llm_decision="DRAFT",
        )
        store.update_draft_id("msg-1", "new-draft-id")
        row = store._conn.execute(
            "SELECT draft_id FROM processed_messages WHERE message_id = 'msg-1'"
        ).fetchone()
        assert row["draft_id"] == "new-draft-id"

    def test_clear_processed(self, store_with_account: StateStore):
        store = store_with_account
        store.record_processed(
            message_id="msg-1", thread_id="thread-1",
            account_email="test@example.com", layer1_result="passed",
        )
        store.clear_processed("msg-1")
        assert not store.is_processed("msg-1")

    def test_retry_and_quarantine(self, store_with_account: StateStore):
        store = store_with_account
        store.record_processed(
            message_id="msg-1", thread_id="thread-1",
            account_email="test@example.com", layer1_result="passed",
            llm_decision=None,
        )
        store._conn.execute(
            "UPDATE processed_messages SET status = 'pending' WHERE message_id = 'msg-1'"
        )
        store._conn.commit()

        store.increment_retry("msg-1", "error 1")
        store.increment_retry("msg-1", "error 2")
        count = store.increment_retry("msg-1", "error 3")
        assert count == 3

        quarantined = store.get_quarantined()
        assert len(quarantined) == 1
        assert quarantined[0]["message_id"] == "msg-1"


class TestPollCheckpoints:
    def test_set_and_get(self, store: StateStore):
        assert store.get_checkpoint("test@example.com") is None
        store.update_checkpoint("test@example.com", "history-123")
        cp = store.get_checkpoint("test@example.com")
        assert cp is not None
        assert cp["last_history_id"] == "history-123"

    def test_update_overwrites(self, store: StateStore):
        store.update_checkpoint("test@example.com", "h1")
        store.update_checkpoint("test@example.com", "h2")
        cp = store.get_checkpoint("test@example.com")
        assert cp["last_history_id"] == "h2"


class TestAuditLog:
    def test_log_event(self, store: StateStore):
        store.log_event("draft_created", "test@example.com", {"draft_id": "d1"})
        rows = store._conn.execute("SELECT * FROM audit_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["event"] == "draft_created"


class TestCostTracking:
    def test_daily_cost_zero_when_empty(self, store: StateStore):
        assert store.get_daily_cost() == 0.0

    def test_daily_cost_sums_correctly(self, store_with_account: StateStore):
        store = store_with_account
        import time as t
        now = int(t.time())
        for i, cost in enumerate([0.01, 0.02, 0.03]):
            store._conn.execute(
                "INSERT INTO processed_messages "
                "(message_id, thread_id, account_email, processed_at, layer1_result, "
                "llm_cost_usd, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"msg-{i}", f"t-{i}", "test@example.com", now, "passed", cost, "completed"),
            )
        store._conn.commit()
        total = store.get_daily_cost()
        assert abs(total - 0.06) < 0.001
