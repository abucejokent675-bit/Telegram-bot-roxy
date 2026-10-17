from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS archived_messages (
                    source_chat_id INTEGER NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    archive_message_id INTEGER,
                    PRIMARY KEY (source_chat_id, source_message_id)
                );
                CREATE TABLE IF NOT EXISTS mediation_consent (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS conversation_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER,
                    username TEXT,
                    text TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_state (
                    chat_id INTEGER PRIMARY KEY,
                    mode TEXT NOT NULL DEFAULT 'paused',
                    message_count INTEGER NOT NULL DEFAULT 0,
                    last_offer_at REAL NOT NULL DEFAULT 0
                );
                """
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def is_source(self, chat_id: int) -> bool:
        sources = self.get_setting("source_chat_ids", "")
        return str(chat_id) in sources.split(",") if sources else False

    def add_source(self, chat_id: int) -> None:
        sources = set(filter(None, self.get_setting("source_chat_ids", "").split(",")))
        sources.add(str(chat_id))
        self.set_setting("source_chat_ids", ",".join(sorted(sources)))

    def remove_source(self, chat_id: int) -> None:
        sources = set(filter(None, self.get_setting("source_chat_ids", "").split(",")))
        sources.discard(str(chat_id))
        self.set_setting("source_chat_ids", ",".join(sorted(sources)))

    def get_archive_chat_id(self) -> int | None:
        value = self.get_setting("archive_chat_id", "")
        return int(value) if value else None

    def set_archive_chat_id(self, chat_id: int) -> None:
        self.set_setting("archive_chat_id", str(chat_id))

    def was_archived(self, source_chat_id: int, source_message_id: int) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM archived_messages WHERE source_chat_id = ? AND source_message_id = ?",
                (source_chat_id, source_message_id),
            ).fetchone()
        return bool(row)

    def mark_archived(self, source_chat_id: int, source_message_id: int, archive_message_id: int | None) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO archived_messages(source_chat_id, source_message_id, archive_message_id) "
                "VALUES(?, ?, ?)",
                (source_chat_id, source_message_id, archive_message_id),
            )

    def give_consent(self, chat_id: int, user_id: int) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO mediation_consent(chat_id, user_id) VALUES(?, ?)",
                (chat_id, user_id),
            )

    def withdraw_consent(self, chat_id: int, user_id: int) -> None:
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM mediation_consent WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )

    def consented_ids(self, chat_id: int) -> set[int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT user_id FROM mediation_consent WHERE chat_id = ?",
                (chat_id,),
            ).fetchall()
        return {int(row["user_id"]) for row in rows}

    def add_context(self, chat_id: int, user_id: int | None, username: str | None, text: str, created_at: float) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO conversation_context(chat_id, user_id, username, text, created_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (chat_id, user_id, username, text, created_at),
            )

    def get_context(self, chat_id: int, limit: int) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT user_id, username, text, created_at FROM conversation_context "
                "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def clear_context(self, chat_id: int) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM conversation_context WHERE chat_id = ?", (chat_id,))

    def get_chat_state(self, chat_id: int) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT mode, message_count, last_offer_at FROM chat_state WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if not row:
            return {"mode": "paused", "message_count": 0, "last_offer_at": 0.0}
        return {
            "mode": str(row["mode"]),
            "message_count": int(row["message_count"]),
            "last_offer_at": float(row["last_offer_at"]),
        }

    def set_chat_mode(self, chat_id: int, mode: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO chat_state(chat_id, mode) VALUES(?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET mode = excluded.mode",
                (chat_id, mode),
            )

    def set_last_offer(self, chat_id: int, timestamp: float) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO chat_state(chat_id, mode, last_offer_at) VALUES(?, 'paused', ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET last_offer_at = excluded.last_offer_at",
                (chat_id, timestamp),
            )

    def delete_all_data(self) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for table in (
                "settings",
                "archived_messages",
                "mediation_consent",
                "conversation_context",
                "chat_state",
            ):
                connection.execute(f"DELETE FROM {table}")
            connection.commit()
        with self._connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("VACUUM")

    def pause_and_clear_context(self) -> None:
        with self._connection() as connection:
            connection.execute("UPDATE chat_state SET mode = 'paused'")
            connection.execute("DELETE FROM conversation_context")
