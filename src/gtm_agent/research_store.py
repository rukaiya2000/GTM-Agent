"""SQLite persistence for the research-outreach workspace."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RESEARCH_DB_PATH = Path("research_outreach.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    affiliation TEXT,
    semantic_scholar_author_id TEXT UNIQUE,
    relationship_stage TEXT NOT NULL DEFAULT 'Prospect',
    relationship_summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY,
    semantic_scholar_paper_id TEXT UNIQUE,
    title TEXT NOT NULL,
    year INTEGER,
    doi TEXT,
    source_url TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contact_papers (
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    PRIMARY KEY (contact_id, paper_id)
);

CREATE TABLE IF NOT EXISTS contact_links (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    url TEXT NOT NULL,
    user_verified INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(contact_id, url)
);

CREATE TABLE IF NOT EXISTS research_notes (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS follow_up_tasks (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS outreach_drafts (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    purpose TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchStore:
    def __init__(self, db_path: Path = DEFAULT_RESEARCH_DB_PATH):
        self._db_path = db_path
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def save_contact(
        self,
        *,
        name: str,
        affiliation: str | None,
        author_id: str | None,
        paper: dict | None,
        links: list[dict[str, str]],
        note: str | None,
    ) -> dict:
        now = _now()
        with closing(self._connect()) as conn:
            if author_id:
                conn.execute(
                    """INSERT INTO contacts (name, affiliation, semantic_scholar_author_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(semantic_scholar_author_id) DO UPDATE SET
                        name=excluded.name, affiliation=excluded.affiliation, updated_at=excluded.updated_at""",
                    (name, affiliation, author_id, now, now),
                )
                contact = conn.execute(
                    "SELECT * FROM contacts WHERE semantic_scholar_author_id = ?", (author_id,)
                ).fetchone()
            else:
                conn.execute(
                    "INSERT INTO contacts (name, affiliation, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (name, affiliation, now, now),
                )
                contact = conn.execute("SELECT * FROM contacts WHERE id = last_insert_rowid()").fetchone()
            contact_id = contact["id"]

            if paper and paper.get("title"):
                conn.execute(
                    """INSERT INTO papers (semantic_scholar_paper_id, title, year, doi, source_url, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(semantic_scholar_paper_id) DO UPDATE SET title=excluded.title""",
                    (paper.get("paper_id"), paper["title"], paper.get("year"), paper.get("doi"), paper.get("url"), now),
                )
                paper_row = conn.execute(
                    "SELECT id FROM papers WHERE semantic_scholar_paper_id = ?", (paper.get("paper_id"),)
                ).fetchone()
                if paper_row:
                    conn.execute("INSERT OR IGNORE INTO contact_papers (contact_id, paper_id) VALUES (?, ?)", (contact_id, paper_row["id"]))
            for link in links:
                conn.execute(
                    "INSERT OR IGNORE INTO contact_links (contact_id, label, url, user_verified, created_at) VALUES (?, ?, ?, 1, ?)",
                    (contact_id, link["label"], link["url"], now),
                )
            if note and note.strip():
                conn.execute("INSERT INTO research_notes (contact_id, body, created_at) VALUES (?, ?, ?)", (contact_id, note.strip(), now))
            conn.commit()
        return self.get_contact(contact_id)

    def get_contact(self, contact_id: int) -> dict:
        with closing(self._connect()) as conn:
            contact = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
            if not contact:
                raise KeyError(contact_id)
            links = conn.execute("SELECT label, url, user_verified FROM contact_links WHERE contact_id = ? ORDER BY id", (contact_id,)).fetchall()
            papers = conn.execute(
                """SELECT p.title, p.year, p.doi, p.source_url FROM papers p
                JOIN contact_papers cp ON cp.paper_id = p.id WHERE cp.contact_id = ? ORDER BY p.year DESC""", (contact_id,)
            ).fetchall()
            notes = conn.execute("SELECT body, created_at FROM research_notes WHERE contact_id = ? ORDER BY id DESC", (contact_id,)).fetchall()
            interactions = conn.execute("SELECT id, kind, body, occurred_at FROM interactions WHERE contact_id = ? ORDER BY occurred_at DESC, id DESC", (contact_id,)).fetchall()
            tasks = conn.execute("SELECT id, reason, due_at, status FROM follow_up_tasks WHERE contact_id = ? ORDER BY due_at", (contact_id,)).fetchall()
            drafts = conn.execute("SELECT id, channel, purpose, body, status, created_at FROM outreach_drafts WHERE contact_id = ? ORDER BY id DESC", (contact_id,)).fetchall()
        result = dict(contact)
        result["links"] = [dict(row) for row in links]
        result["papers"] = [dict(row) for row in papers]
        result["notes"] = [dict(row) for row in notes]
        result["interactions"] = [dict(row) for row in interactions]
        result["follow_ups"] = [dict(row) for row in tasks]
        result["drafts"] = [dict(row) for row in drafts]
        return result

    def list_contacts(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("""SELECT c.id, c.name, c.affiliation, c.relationship_stage, c.updated_at,
                (SELECT MIN(due_at) FROM follow_up_tasks WHERE contact_id = c.id AND status = 'open') AS next_due
                FROM contacts c ORDER BY c.updated_at DESC""").fetchall()
        return [dict(row) for row in rows]

    def update_contact(self, contact_id: int, stage: str | None, summary: str | None) -> dict:
        with closing(self._connect()) as conn:
            if stage is not None:
                conn.execute("UPDATE contacts SET relationship_stage = ?, updated_at = ? WHERE id = ?", (stage, _now(), contact_id))
            if summary is not None:
                conn.execute("UPDATE contacts SET relationship_summary = ?, updated_at = ? WHERE id = ?", (summary, _now(), contact_id))
            if not conn.execute("SELECT 1 FROM contacts WHERE id = ?", (contact_id,)).fetchone():
                raise KeyError(contact_id)
            conn.commit()
        return self.get_contact(contact_id)

    def add_interaction(self, contact_id: int, kind: str, body: str, occurred_at: str) -> dict:
        now = _now()
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO interactions (contact_id, kind, body, occurred_at, created_at) VALUES (?, ?, ?, ?, ?)", (contact_id, kind, body, occurred_at, now))
            conn.execute("UPDATE contacts SET updated_at = ? WHERE id = ?", (now, contact_id))
            conn.commit()
        return self.get_contact(contact_id)

    def add_follow_up(self, contact_id: int, reason: str, due_at: str) -> dict:
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO follow_up_tasks (contact_id, reason, due_at, created_at) VALUES (?, ?, ?, ?)", (contact_id, reason, due_at, _now()))
            conn.commit()
        return self.get_contact(contact_id)

    def list_follow_ups(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("""SELECT f.id, f.reason, f.due_at, f.status, c.id AS contact_id, c.name, c.affiliation
                FROM follow_up_tasks f JOIN contacts c ON c.id = f.contact_id
                WHERE f.status = 'open' ORDER BY f.due_at, f.id""").fetchall()
        return [dict(row) for row in rows]

    def complete_follow_up(self, task_id: int, status: str) -> None:
        with closing(self._connect()) as conn:
            result = conn.execute("UPDATE follow_up_tasks SET status = ?, completed_at = ? WHERE id = ?", (status, _now(), task_id))
            if not result.rowcount:
                raise KeyError(task_id)
            conn.commit()

    def save_draft(self, contact_id: int, channel: str, purpose: str, body: str) -> dict:
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO outreach_drafts (contact_id, channel, purpose, body, created_at) VALUES (?, ?, ?, ?, ?)", (contact_id, channel, purpose, body, _now()))
            conn.commit()
        return self.get_contact(contact_id)
