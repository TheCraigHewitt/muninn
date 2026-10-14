"""SQLite storage for Sources, Memories, Evidence and the links between Memories."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .sources import Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    held_on TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lines (
    source_id INTEGER NOT NULL REFERENCES sources(id),
    line_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    author TEXT NOT NULL,
    text TEXT NOT NULL,
    ref TEXT NOT NULL DEFAULT '',  -- where the line lives outside Bruh, e.g. "C0123:1712345678.000100" for Slack
    PRIMARY KEY (source_id, line_id)
);
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
-- status: active | review (waiting for a person) | superseded | rejected
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    statement TEXT NOT NULL,
    topic_id INTEGER NOT NULL REFERENCES topics(id),
    owner TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL,
    confidence_reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    as_of TEXT NOT NULL,
    retold INTEGER NOT NULL DEFAULT 0,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    created_at TEXT NOT NULL
);
-- role: origin (the line it came from) | support (later evidence for the same thing)
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    memory_id INTEGER NOT NULL REFERENCES memories(id),
    source_id INTEGER NOT NULL,
    line_id TEXT NOT NULL,
    quote TEXT NOT NULL,
    role TEXT NOT NULL
);
-- kind: supersedes | contradicts | explains   (from_id <kind> to_id)
CREATE TABLE IF NOT EXISTS relations (
    from_id INTEGER NOT NULL REFERENCES memories(id),
    to_id INTEGER NOT NULL REFERENCES memories(id),
    kind TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id, kind)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        # One Store per thread of work (web, Slack, folder watcher); WAL lets them share the file.
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        if "ref" not in {r["name"] for r in self.db.execute("PRAGMA table_info(lines)")}:
            self.db.execute("ALTER TABLE lines ADD COLUMN ref TEXT NOT NULL DEFAULT ''")

    # ---- sources ----

    def has_source(self, source: Source) -> bool:
        return self.db.execute("SELECT 1 FROM sources WHERE content_hash = ?", (source.content_hash,)).fetchone() is not None

    def add_source(self, source: Source) -> int:
        cur = self.db.execute(
            "INSERT INTO sources (kind, name, title, held_on, content_hash, ingested_at) VALUES (?, ?, ?, ?, ?, ?)",
            (source.kind, source.name, source.title, source.held_on, source.content_hash, now()),
        )
        source_id = cur.lastrowid
        self.db.executemany(
            "INSERT INTO lines (source_id, line_id, seq, ts, author, text, ref) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(source_id, l.id, i, l.ts, l.author, l.text, l.ref) for i, l in enumerate(source.lines)],
        )
        return source_id

    def sources(self) -> list[dict]:
        rows = self.db.execute("""
            SELECT s.*, (SELECT COUNT(*) FROM lines l WHERE l.source_id = s.id) AS line_count,
                   (SELECT COUNT(*) FROM memories m WHERE m.source_id = s.id) AS memory_count
            FROM sources s ORDER BY s.held_on, s.id""").fetchall()
        return [dict(r) for r in rows]

    def source(self, source_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            return None
        lines = self.db.execute(
            "SELECT line_id, ts, author, text FROM lines WHERE source_id = ? ORDER BY seq", (source_id,)
        ).fetchall()
        cited = self.db.execute(
            "SELECT line_id, memory_id FROM evidence WHERE source_id = ?", (source_id,)
        ).fetchall()
        by_line: dict[str, list[int]] = {}
        for r in cited:
            by_line.setdefault(r["line_id"], []).append(r["memory_id"])
        return {**dict(row), "lines": [{**dict(l), "memories": by_line.get(l["line_id"], [])} for l in lines]}

    def last_line_ts(self, kind: str, title: str) -> str:
        """The newest line already read from conversations with this title, e.g. a Slack channel."""
        row = self.db.execute("""SELECT MAX(l.ts) FROM lines l JOIN sources s ON s.id = l.source_id
                                 WHERE s.kind = ? AND s.title = ?""", (kind, title)).fetchone()
        return row[0] or ""

    def erase_line(self, ref: str) -> int:
        """Someone deleted the original: blank every copy of it and drop the Evidence that quoted it.

        A Memory left with no Evidence goes too, along with its links. Returns how many Memories went.
        """
        lines = self.db.execute("SELECT source_id, line_id FROM lines WHERE ref = ?", (ref,)).fetchall()
        touched = set()
        for l in lines:
            rows = self.db.execute("SELECT memory_id FROM evidence WHERE source_id = ? AND line_id = ?",
                                   (l["source_id"], l["line_id"])).fetchall()
            touched |= {r["memory_id"] for r in rows}
            self.db.execute("DELETE FROM evidence WHERE source_id = ? AND line_id = ?", (l["source_id"], l["line_id"]))
        self.db.execute("UPDATE lines SET text = '', author = '' WHERE ref = ?", (ref,))
        orphans = [m for m in touched
                   if not self.db.execute("SELECT 1 FROM evidence WHERE memory_id = ?", (m,)).fetchone()]
        for m in orphans:
            self.db.execute("DELETE FROM relations WHERE from_id = ? OR to_id = ?", (m, m))
            self.db.execute("DELETE FROM memories WHERE id = ?", (m,))
        self.db.commit()
        return len(orphans)

    # ---- topics ----

    def topic_id(self, name: str) -> int:
        name = name.strip() or "General"
        row = self.db.execute("SELECT id FROM topics WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        return self.db.execute("INSERT INTO topics (name) VALUES (?)", (name,)).lastrowid

    def topics(self) -> list[dict]:
        rows = self.db.execute("""
            SELECT t.id, t.name, COUNT(m.id) AS memory_count, MAX(m.as_of) AS last_seen,
                   SUM(m.type = 'decision' AND m.status = 'active') AS decisions
            FROM topics t JOIN memories m ON m.topic_id = t.id AND m.status != 'rejected'
            GROUP BY t.id ORDER BY last_seen DESC, memory_count DESC""").fetchall()
        return [dict(r) for r in rows]

    # ---- memories ----

    def add_memory(self, *, type, statement, topic, owner, confidence, confidence_reason, status,
                   as_of, retold, source_id, evidence) -> int:
        memory_id = self.db.execute(
            """INSERT INTO memories (type, statement, topic_id, owner, confidence, confidence_reason,
                                     status, as_of, retold, source_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (type, statement, self.topic_id(topic), owner, confidence, confidence_reason, status,
             as_of, int(retold), source_id, now()),
        ).lastrowid
        self.add_evidence(memory_id, source_id, evidence, "origin")
        return memory_id

    def add_evidence(self, memory_id: int, source_id: int, evidence: list[dict], role: str) -> None:
        self.db.executemany(
            "INSERT INTO evidence (memory_id, source_id, line_id, quote, role) VALUES (?, ?, ?, ?, ?)",
            [(memory_id, source_id, ev["id"], ev["quote"], role) for ev in evidence],
        )

    def relate(self, from_id: int, to_id: int, kind: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO relations (from_id, to_id, kind) VALUES (?, ?, ?)", (from_id, to_id, kind))

    def set_status(self, memory_id: int, status: str) -> None:
        self.db.execute("UPDATE memories SET status = ? WHERE id = ?", (status, memory_id))

    def memories(self, *, status: str | None = None, type: str | None = None, topic_id: int | None = None,
                 include_rejected: bool = False, ids: list[int] | None = None) -> list[dict]:
        where, args = [], []
        if ids is not None:
            where.append(f"m.id IN ({','.join('?' * len(ids)) or 'NULL'})"); args.extend(ids)
        if status:
            where.append("m.status = ?"); args.append(status)
        elif not include_rejected:
            where.append("m.status != 'rejected'")
        if type:
            where.append("m.type = ?"); args.append(type)
        if topic_id:
            where.append("m.topic_id = ?"); args.append(topic_id)
        sql = """SELECT m.*, t.name AS topic, s.title AS source_title, s.kind AS source_kind,
                        (SELECT COUNT(*) FROM evidence e WHERE e.memory_id = m.id) AS evidence_count
                 FROM memories m JOIN topics t ON t.id = m.topic_id JOIN sources s ON s.id = m.source_id"""
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.as_of DESC, m.id DESC"
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def memory(self, memory_id: int) -> dict | None:
        rows = self.memories(include_rejected=True, ids=[memory_id])
        if not rows:
            return None
        found = rows[0]
        found["evidence"] = self.evidence(memory_id)
        found["relations"] = self.relations(memory_id)
        return found

    def evidence(self, memory_id: int) -> list[dict]:
        rows = self.db.execute("""
            SELECT e.source_id, e.line_id, e.quote, e.role, l.author, l.ts, l.ref, s.title AS source_title,
                   s.kind AS source_kind, s.held_on
            FROM evidence e
            JOIN lines l ON l.source_id = e.source_id AND l.line_id = e.line_id
            JOIN sources s ON s.id = e.source_id
            WHERE e.memory_id = ? ORDER BY s.held_on, l.seq""", (memory_id,)).fetchall()
        return [dict(r) for r in rows]

    def relations(self, memory_id: int) -> list[dict]:
        rows = self.db.execute("""
            SELECT r.kind, 'out' AS direction, m.id, m.type, m.statement, m.status, m.as_of
              FROM relations r JOIN memories m ON m.id = r.to_id WHERE r.from_id = ?
            UNION ALL
            SELECT r.kind, 'in' AS direction, m.id, m.type, m.statement, m.status, m.as_of
              FROM relations r JOIN memories m ON m.id = r.from_id WHERE r.to_id = ?""",
            (memory_id, memory_id)).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        one = lambda sql: self.db.execute(sql).fetchone()[0]
        return {
            "sources": one("SELECT COUNT(*) FROM sources"),
            "memories": one("SELECT COUNT(*) FROM memories WHERE status != 'rejected'"),
            "decisions": one("SELECT COUNT(*) FROM memories WHERE type = 'decision' AND status = 'active'"),
            "review": one("SELECT COUNT(*) FROM memories WHERE status = 'review'"),
            "topics": one("SELECT COUNT(DISTINCT topic_id) FROM memories WHERE status != 'rejected'"),
        }

    def commit(self) -> None:
        self.db.commit()
