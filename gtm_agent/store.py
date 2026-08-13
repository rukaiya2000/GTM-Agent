import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path("gtm_agent.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    tweet_id TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_cache (
    username TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self._db_path = db_path
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def filter_unseen(self, tweet_ids: list[str]) -> list[str]:
        if not tweet_ids:
            return []
        with closing(self._connect()) as conn:
            placeholders = ",".join("?" * len(tweet_ids))
            rows = conn.execute(
                f"SELECT tweet_id FROM seen WHERE tweet_id IN ({placeholders})",
                tweet_ids,
            ).fetchall()
        already_seen = {row[0] for row in rows}
        return [t for t in tweet_ids if t not in already_seen]

    def mark_seen(self, tweet_ids: list[str]) -> None:
        if not tweet_ids:
            return
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO seen (tweet_id, fetched_at) VALUES (?, ?)",
                [(t, now) for t in tweet_ids],
            )
            conn.commit()

    def get_cached_user_id(self, username: str) -> str | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT user_id FROM user_cache WHERE username = ?", (username,)
            ).fetchone()
        return row[0] if row else None

    def cache_user_id(self, username: str, user_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_cache (username, user_id, resolved_at) "
                "VALUES (?, ?, ?)",
                (username, user_id, now),
            )
            conn.commit()
