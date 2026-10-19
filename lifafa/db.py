"""SQLite store on this computer: events, register pages, and the shagun entries read from them."""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,          -- "Riya's wedding"
    event_date  TEXT,                   -- YYYY-MM-DD
    from_name   TEXT,                   -- who thank-you notes are signed by
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id      INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    file          TEXT NOT NULL,
    status        TEXT NOT NULL,        -- read | failed
    written_total INTEGER,              -- total written at the bottom of the page, if any
    latency_ms    INTEGER,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    place       TEXT,
    phone       TEXT,
    relation    TEXT,                 -- "Mama ji", "office", "neighbour"
    notes       TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS given (     -- what WE gave at THEIR occasion (the return side of lena-dena)
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id    INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    occasion      TEXT NOT NULL,      -- "Verma ji's son's wedding"
    occasion_date TEXT,
    amount        INTEGER,
    gift          TEXT,
    note          TEXT,
    source        TEXT NOT NULL DEFAULT 'manual',  -- manual | voice
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id      INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    page_id       INTEGER REFERENCES pages(id) ON DELETE SET NULL,
    name          TEXT NOT NULL,
    place         TEXT,
    phone         TEXT,
    amount        INTEGER,              -- rupees
    gift          TEXT,
    note          TEXT,
    review        TEXT,                 -- why a person should double-check this row (NULL = fine)
    thanked       INTEGER NOT NULL DEFAULT 0,
    thanked_at    TEXT,
    contact_id    INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    source        TEXT NOT NULL,        -- ai | manual | voice
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, latency_ms INTEGER NOT NULL, ok INTEGER NOT NULL
);
"""

ENTRY_FIELDS = ("name", "place", "phone", "amount", "gift", "note", "review", "thanked", "thanked_at", "contact_id")
CONTACT_FIELDS = ("name", "place", "phone", "relation", "notes")
GIVEN_FIELDS = ("occasion", "occasion_date", "amount", "gift", "note")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.conn() as c:
            c.executescript(SCHEMA)  # existing tables are left alone; _migrate adds new columns
            self._migrate(c)

    @staticmethod
    def _migrate(c) -> None:
        """Older Lifafa databases: add the new columns and give every existing entry a contact."""
        cols = {r["name"] for r in c.execute("PRAGMA table_info(entries)")}
        for col, ddl in (("thanked_at", "TEXT"), ("contact_id", "INTEGER REFERENCES contacts(id) ON DELETE SET NULL")):
            if col not in cols:
                c.execute(f"ALTER TABLE entries ADD COLUMN {col} {ddl}")
        from lifafa.people import person_key

        orphans = c.execute("SELECT id, name, place, phone FROM entries WHERE contact_id IS NULL").fetchall()
        if orphans:
            known = {person_key(r["name"], r["place"]): r["id"] for r in c.execute("SELECT id, name, place FROM contacts")}
            for e in orphans:
                key = person_key(e["name"], e["place"])
                if key not in known:
                    known[key] = c.execute("INSERT INTO contacts (name, place, phone, created_at) VALUES (?, ?, ?, ?)",
                                           (e["name"], e["place"], e["phone"], now_iso())).lastrowid
                c.execute("UPDATE entries SET contact_id = ? WHERE id = ?", (known[key], e["id"]))

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # events -----------------------------------------------------------------------------------
    def add_event(self, name: str, event_date: str | None, from_name: str | None) -> int:
        with self.conn() as c:
            return c.execute("INSERT INTO events (name, event_date, from_name, created_at) VALUES (?, ?, ?, ?)",
                             (name, event_date, from_name, now_iso())).lastrowid

    def update_event(self, eid: int, **fields) -> None:
        with self.conn() as c:
            c.execute(f"UPDATE events SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), eid))

    def event(self, eid: int) -> dict | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
        return dict(row) if row else None

    def events(self) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT e.*, COUNT(n.id) AS guests, COALESCE(SUM(n.amount), 0) AS cash_total,"
                " SUM(CASE WHEN n.review IS NOT NULL THEN 1 ELSE 0 END) AS to_review"
                " FROM events e LEFT JOIN entries n ON n.event_id = e.id GROUP BY e.id"
                " ORDER BY COALESCE(e.event_date, e.created_at) DESC")]

    def delete_event(self, eid: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM events WHERE id = ?", (eid,))

    # pages ------------------------------------------------------------------------------------
    def add_page(self, eid: int, file: str, status: str, written_total: int | None, latency_ms: int | None) -> int:
        with self.conn() as c:
            return c.execute("INSERT INTO pages (event_id, file, status, written_total, latency_ms, created_at)"
                             " VALUES (?, ?, ?, ?, ?, ?)", (eid, file, status, written_total, latency_ms, now_iso())).lastrowid

    def pages(self, eid: int) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT p.*, COUNT(n.id) AS rows, COALESCE(SUM(n.amount), 0) AS read_total FROM pages p"
                " LEFT JOIN entries n ON n.page_id = p.id WHERE p.event_id = ? GROUP BY p.id ORDER BY p.id", (eid,))]

    # entries ----------------------------------------------------------------------------------
    def add_entries(self, eid: int, page_id: int | None, rows: list[dict], source: str) -> None:
        with self.conn() as c:
            c.executemany(
                "INSERT INTO entries (event_id, page_id, name, place, phone, amount, gift, note, review, contact_id, source,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(eid, page_id, r["name"], r.get("place"), r.get("phone"), r.get("amount"), r.get("gift"), r.get("note"),
                  r.get("review"), r.get("contact_id"), source, now_iso()) for r in rows])

    def entry(self, nid: int) -> dict | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM entries WHERE id = ?", (nid,)).fetchone()
        return dict(row) | {"thanked": bool(row["thanked"])} if row else None

    def entries(self, eid: int) -> list[dict]:
        with self.conn() as c:
            return [dict(r) | {"thanked": bool(r["thanked"])}
                    for r in c.execute("SELECT * FROM entries WHERE event_id = ? ORDER BY id", (eid,))]

    def update_entry(self, nid: int, **fields) -> None:
        fields = {k: v for k, v in fields.items() if k in ENTRY_FIELDS}
        if fields:
            with self.conn() as c:
                c.execute(f"UPDATE entries SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), nid))

    def delete_entry(self, nid: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM entries WHERE id = ?", (nid,))

    def all_entries(self) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT n.*, e.name AS event_name, e.event_date FROM entries n JOIN events e ON e.id = n.event_id")]

    # contacts ---------------------------------------------------------------------------------
    def add_contact(self, name: str, place: str | None = None, phone: str | None = None,
                    relation: str | None = None, notes: str | None = None) -> int:
        with self.conn() as c:
            return c.execute("INSERT INTO contacts (name, place, phone, relation, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                             (name, place, phone, relation, notes, now_iso())).lastrowid

    def contact(self, cid: int) -> dict | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM contacts WHERE id = ?", (cid,)).fetchone()
        return dict(row) if row else None

    def contacts(self) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT c.*,"
                " (SELECT COALESCE(SUM(amount), 0) FROM entries WHERE contact_id = c.id) AS received_total,"
                " (SELECT COUNT(*) FROM entries WHERE contact_id = c.id) AS received_count,"
                " (SELECT COALESCE(SUM(amount), 0) FROM given WHERE contact_id = c.id) AS given_total,"
                " (SELECT COUNT(*) FROM given WHERE contact_id = c.id) AS given_count,"
                " (SELECT COUNT(*) FROM entries WHERE contact_id = c.id AND thanked = 0) AS unthanked"
                " FROM contacts c ORDER BY c.name COLLATE NOCASE")]

    def update_contact(self, cid: int, **fields) -> None:
        fields = {k: v for k, v in fields.items() if k in CONTACT_FIELDS}
        if fields:
            with self.conn() as c:
                c.execute(f"UPDATE contacts SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), cid))

    def merge_contacts(self, source_id: int, into_id: int) -> None:
        """One person, two records (e.g. "Sharma ji" from the register and "Ramesh Sharma" from the phone)."""
        with self.conn() as c:
            src = c.execute("SELECT * FROM contacts WHERE id = ?", (source_id,)).fetchone()
            dst = c.execute("SELECT * FROM contacts WHERE id = ?", (into_id,)).fetchone()
            for f in ("place", "phone", "relation", "notes"):
                if not dst[f] and src[f]:
                    c.execute(f"UPDATE contacts SET {f} = ? WHERE id = ?", (src[f], into_id))
            c.execute("UPDATE entries SET contact_id = ? WHERE contact_id = ?", (into_id, source_id))
            c.execute("UPDATE given SET contact_id = ? WHERE contact_id = ?", (into_id, source_id))
            c.execute("DELETE FROM contacts WHERE id = ?", (source_id,))

    def contact_entries(self, cid: int) -> list[dict]:
        with self.conn() as c:
            return [dict(r) | {"thanked": bool(r["thanked"])} for r in c.execute(
                "SELECT n.*, e.name AS event_name, e.event_date FROM entries n JOIN events e ON e.id = n.event_id"
                " WHERE n.contact_id = ? ORDER BY COALESCE(e.event_date, n.created_at) DESC", (cid,))]

    # given (return gifts) -----------------------------------------------------------------------
    def add_given(self, cid: int, occasion: str, occasion_date: str | None, amount: int | None, gift: str | None,
                  note: str | None, source: str = "manual") -> int:
        with self.conn() as c:
            return c.execute("INSERT INTO given (contact_id, occasion, occasion_date, amount, gift, note, source, created_at)"
                             " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (cid, occasion, occasion_date, amount, gift, note, source, now_iso())).lastrowid

    def given_one(self, gid: int) -> dict | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM given WHERE id = ?", (gid,)).fetchone()
        return dict(row) if row else None

    def given_for(self, cid: int) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM given WHERE contact_id = ? ORDER BY COALESCE(occasion_date, created_at) DESC", (cid,))]

    def update_given(self, gid: int, **fields) -> None:
        fields = {k: v for k, v in fields.items() if k in GIVEN_FIELDS}
        if fields:
            with self.conn() as c:
                c.execute(f"UPDATE given SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), gid))

    def delete_given(self, gid: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM given WHERE id = ?", (gid,))

    def log_ai(self, kind: str, latency_ms: int, ok: bool) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO ai_calls (at, kind, latency_ms, ok) VALUES (?, ?, ?, ?)", (now_iso(), kind, latency_ms, int(ok)))
