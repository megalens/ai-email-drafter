"""SQLite state store with Fernet-encrypted token columns."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

SCHEMA_VERSION = 1

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    account_email TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    scope TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    account_email TEXT NOT NULL,
    processed_at INTEGER NOT NULL,
    layer1_result TEXT NOT NULL,
    llm_decision TEXT,
    llm_reason TEXT,
    draft_id TEXT,
    llm_cost_usd REAL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    last_error TEXT,
    FOREIGN KEY (account_email) REFERENCES oauth_tokens(account_email)
);

CREATE INDEX IF NOT EXISTS idx_processed_messages_account
    ON processed_messages(account_email, processed_at);

CREATE TABLE IF NOT EXISTS poll_checkpoints (
    account_email TEXT PRIMARY KEY,
    last_poll_at INTEGER NOT NULL,
    last_history_id TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    event TEXT NOT NULL,
    account_email TEXT,
    details TEXT
);
"""


@dataclass
class OAuthTokens:
    account_email: str
    access_token: str
    refresh_token: str
    expires_at: int
    scope: str
    created_at: int
    updated_at: int


class StateStore:
    """SQLite-backed state store with WAL mode and Fernet encryption for tokens."""

    def __init__(self, db_path: str | Path, encryption_key: str) -> None:
        self._db_path = str(db_path)
        key = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
        self._fernet = Fernet(key)
        self._conn = self._connect()
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self) -> None:
        cursor = self._conn.cursor()
        cursor.executescript(_SCHEMA)
        row = cursor.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        self._conn.commit()

    def _encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()

    # --- OAuth tokens ---

    def save_oauth_tokens(self, tokens: OAuthTokens) -> None:
        now = int(time.time())
        self._conn.execute(
            """INSERT INTO oauth_tokens
               (account_email, access_token, refresh_token,
                expires_at, scope, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(account_email) DO UPDATE SET
                   access_token=excluded.access_token,
                   refresh_token=excluded.refresh_token,
                   expires_at=excluded.expires_at,
                   scope=excluded.scope,
                   updated_at=excluded.updated_at""",
            (
                tokens.account_email,
                self._encrypt(tokens.access_token),
                self._encrypt(tokens.refresh_token),
                tokens.expires_at,
                tokens.scope,
                tokens.created_at or now,
                now,
            ),
        )
        self._conn.commit()

    def get_oauth_tokens(self, account_email: str) -> OAuthTokens | None:
        row = self._conn.execute(
            "SELECT * FROM oauth_tokens WHERE account_email = ?", (account_email,)
        ).fetchone()
        if row is None:
            return None
        return OAuthTokens(
            account_email=row["account_email"],
            access_token=self._decrypt(row["access_token"]),
            refresh_token=self._decrypt(row["refresh_token"]),
            expires_at=row["expires_at"],
            scope=row["scope"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_accounts(self) -> list[str]:
        rows = self._conn.execute("SELECT account_email FROM oauth_tokens").fetchall()
        return [r["account_email"] for r in rows]

    # --- Processed messages ---

    def is_processed(self, message_id: str) -> bool:
        row = self._conn.execute(
            "SELECT status FROM processed_messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        return row is not None and row["status"] == "completed"

    def record_processed(
        self,
        message_id: str,
        thread_id: str,
        account_email: str,
        layer1_result: str,
        llm_decision: str | None = None,
        llm_reason: str | None = None,
        draft_id: str | None = None,
        llm_cost_usd: float | None = None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO processed_messages
               (message_id, thread_id, account_email, processed_at, layer1_result,
                llm_decision, llm_reason, draft_id, llm_cost_usd, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed')
               ON CONFLICT(message_id) DO UPDATE SET
                   llm_decision=excluded.llm_decision,
                   llm_reason=excluded.llm_reason,
                   draft_id=excluded.draft_id,
                   llm_cost_usd=excluded.llm_cost_usd,
                   status='completed'""",
            (message_id, thread_id, account_email, int(time.time()),
             layer1_result, llm_decision, llm_reason, draft_id, llm_cost_usd),
        )
        self._conn.commit()

    def update_draft_id(self, message_id: str, draft_id: str) -> None:
        self._conn.execute(
            "UPDATE processed_messages SET draft_id = ? WHERE message_id = ?",
            (draft_id, message_id),
        )
        self._conn.commit()

    def clear_processed(self, message_id: str) -> None:
        self._conn.execute(
            "DELETE FROM processed_messages WHERE message_id = ?", (message_id,)
        )
        self._conn.commit()

    def increment_retry(self, message_id: str, error: str) -> int:
        self._conn.execute(
            """UPDATE processed_messages
               SET retry_count = retry_count + 1, last_error = ?,
                   status = CASE WHEN retry_count + 1 >= 3 THEN 'quarantined' ELSE 'pending' END
               WHERE message_id = ?""",
            (error, message_id),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT retry_count FROM processed_messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        return row["retry_count"] if row else 0

    def get_pending_retries(self, account_email: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT message_id FROM processed_messages "
            "WHERE account_email = ? AND status = 'pending'",
            (account_email,),
        ).fetchall()
        return [r["message_id"] for r in rows]

    def get_quarantined(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT message_id, thread_id, account_email, last_error, retry_count "
            "FROM processed_messages WHERE status = 'quarantined'"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Poll checkpoints ---

    def get_checkpoint(self, account_email: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM poll_checkpoints WHERE account_email = ?", (account_email,)
        ).fetchone()
        return dict(row) if row else None

    def update_checkpoint(
        self, account_email: str, history_id: str | None = None
    ) -> None:
        self._conn.execute(
            """INSERT INTO poll_checkpoints (account_email, last_poll_at, last_history_id)
               VALUES (?, ?, ?)
               ON CONFLICT(account_email) DO UPDATE SET
                   last_poll_at=excluded.last_poll_at,
                   last_history_id=excluded.last_history_id""",
            (account_email, int(time.time()), history_id),
        )
        self._conn.commit()

    # --- Audit log ---

    def log_event(
        self, event: str, account_email: str | None = None, details: dict | None = None
    ) -> None:
        self._conn.execute(
            "INSERT INTO audit_log (timestamp, event, account_email, details) VALUES (?, ?, ?, ?)",
            (int(time.time()), event, account_email, json.dumps(details) if details else None),
        )
        self._conn.commit()

    # --- Cost tracking ---

    def get_daily_cost(self, account_email: str | None = None) -> float:
        today_start = int(time.time()) // 86400 * 86400
        if account_email:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(llm_cost_usd), 0) as total FROM processed_messages "
                "WHERE account_email = ? AND processed_at >= ?",
                (account_email, today_start),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(llm_cost_usd), 0) as total FROM processed_messages "
                "WHERE processed_at >= ?",
                (today_start,),
            ).fetchone()
        return row["total"]

    def close(self) -> None:
        self._conn.close()
