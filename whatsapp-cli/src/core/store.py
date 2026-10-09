"""Local per-account store: chats, contacts, messages + FTS5. stdlib sqlite3 only, no domain parsing.

WhatsApp multi-device has no server-side search or arbitrary history fetch: whatever reached this
device (history sync at login, then every connect) is all wa-cli can read. Writers: api/sync.py
only (one connect at a time per account, guarded by the account lock); a future `sync --follow`
daemon is the same writer looping.
"""
import os
import sqlite3
import time

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS chats (
  jid TEXT PRIMARY KEY, kind TEXT, name TEXT, alt_jid TEXT, last_ts INTEGER, unread INTEGER,
  info TEXT, updated INTEGER, members INTEGER);
CREATE TABLE IF NOT EXISTS contacts (
  jid TEXT PRIMARY KEY, phone TEXT, full_name TEXT, first_name TEXT, push_name TEXT, business_name TEXT,
  updated INTEGER);
CREATE TABLE IF NOT EXISTS messages (
  rowid INTEGER PRIMARY KEY, chat_jid TEXT NOT NULL, id TEXT NOT NULL, ts INTEGER, sender_jid TEXT,
  sender_name TEXT, from_me INTEGER, kind TEXT, text TEXT, server_id INTEGER, views INTEGER,
  file TEXT, mime TEXT, media BLOB, reply_to TEXT, reply_to_jid TEXT, mentions TEXT, UNIQUE (chat_jid, id));
CREATE INDEX IF NOT EXISTS messages_chat_ts ON messages (chat_jid, ts);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5 (
  text, content='messages', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts (rowid, text) VALUES (new.rowid, new.text); END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
  INSERT INTO messages_fts (messages_fts, rowid, text) VALUES ('delete', old.rowid, old.text); END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE OF text ON messages BEGIN
  INSERT INTO messages_fts (messages_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
  INSERT INTO messages_fts (rowid, text) VALUES (new.rowid, new.text); END;
"""

MSG_COLS = ("chat_jid", "id", "ts", "sender_jid", "sender_name", "from_me", "kind", "text", "server_id", "views", "file",
            "mime", "media", "reply_to", "reply_to_jid", "mentions")
# Columns older stores lack, added on open: v2 download keys (rows before it: media NULL); v3 quote/mentions
# (rows before it: mentions NULL, ""= parsed, none) and chats.members (group size from the hourly refresh).
ADDED = (("messages", "file", "TEXT"), ("messages", "mime", "TEXT"), ("messages", "media", "BLOB"),
         ("messages", "reply_to", "TEXT"), ("messages", "reply_to_jid", "TEXT"), ("messages", "mentions", "TEXT"),
         ("chats", "members", "INTEGER"))


def fts_query(words):
    """User words -> FTS5 query: every word must match, as a prefix ("отпуск" finds "отпуска")."""
    toks = [w.replace('"', "") for w in words.split()]
    return " ".join(f'"{t}"*' for t in toks if t)


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for table, col, typ in ADDED:
            if col not in {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.db.execute("INSERT INTO meta VALUES ('schema', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (str(SCHEMA_VERSION),))
        os.chmod(path, 0o600)  # message history

    def close(self):
        self.db.commit()
        self.db.close()

    def commit(self):
        self.db.commit()

    # ---- meta ---------------------------------------------------------------
    def get_meta(self, key, default=None):
        r = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_meta(self, key, value):
        self.db.execute("INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, str(value)))

    # ---- writes (non-empty values win; an event never blanks a known name) ---
    def upsert_chat(self, jid, kind=None, name=None, alt_jid=None, last_ts=None, unread=None, info=None, members=None):
        self.db.execute(
            "INSERT INTO chats (jid, kind, name, alt_jid, last_ts, unread, info, updated, members) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(jid) DO UPDATE SET kind=COALESCE(excluded.kind, kind), name=COALESCE(excluded.name, name), "
            "alt_jid=COALESCE(excluded.alt_jid, alt_jid), last_ts=MAX(COALESCE(excluded.last_ts, 0), COALESCE(last_ts, 0)), "
            "unread=COALESCE(excluded.unread, unread), info=COALESCE(excluded.info, info), updated=excluded.updated, "
            "members=COALESCE(excluded.members, members)",
            (jid, kind, name or None, alt_jid or None, last_ts, unread, info, int(time.time()), members))

    def upsert_contact(self, jid, phone=None, full_name=None, first_name=None, push_name=None, business_name=None):
        self.db.execute(
            "INSERT INTO contacts VALUES (?,?,?,?,?,?,?) ON CONFLICT(jid) DO UPDATE SET "
            "phone=COALESCE(excluded.phone, phone), full_name=COALESCE(excluded.full_name, full_name), "
            "first_name=COALESCE(excluded.first_name, first_name), push_name=COALESCE(excluded.push_name, push_name), "
            "business_name=COALESCE(excluded.business_name, business_name), updated=excluded.updated",
            (jid, phone or None, full_name or None, first_name or None, push_name or None, business_name or None,
             int(time.time())))

    def upsert_message(self, m):
        """m: dict with MSG_COLS keys. Returns True when the message is new."""
        vals = [m.get(c) for c in MSG_COLS]
        new = self.db.execute("SELECT 1 FROM messages WHERE chat_jid=? AND id=?", (m["chat_jid"], m["id"])).fetchone() is None
        self.db.execute(
            f"INSERT INTO messages ({', '.join(MSG_COLS)}) VALUES ({', '.join('?' * len(MSG_COLS))}) "
            "ON CONFLICT(chat_jid, id) DO UPDATE SET text=COALESCE(excluded.text, text), "
            "ts=COALESCE(excluded.ts, ts), sender_name=COALESCE(excluded.sender_name, sender_name), "
            "views=COALESCE(excluded.views, views), file=COALESCE(excluded.file, file), "
            "mime=COALESCE(excluded.mime, mime), media=COALESCE(excluded.media, media), "
            "reply_to=COALESCE(excluded.reply_to, reply_to), reply_to_jid=COALESCE(excluded.reply_to_jid, reply_to_jid), "
            "mentions=COALESCE(excluded.mentions, mentions)", vals)
        if m.get("ts"):
            self.upsert_chat(m["chat_jid"], last_ts=m["ts"])
        return new

    def edit_message(self, chat_jid, msg_id, text):
        self.db.execute("UPDATE messages SET text=?, kind=COALESCE(kind, 'text') WHERE chat_jid=? AND id=?",
                        (text, chat_jid, msg_id))

    def delete_message(self, chat_jid, msg_id):
        self.db.execute("UPDATE messages SET text='[deleted]', kind='deleted' WHERE chat_jid=? AND id=?",
                        (chat_jid, msg_id))

    # ---- reads ----------------------------------------------------------------
    def chats(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM chats ORDER BY COALESCE(last_ts, 0) DESC")]

    def chat(self, jid):
        r = self.db.execute("SELECT * FROM chats WHERE jid=? OR alt_jid=?", (jid, jid)).fetchone()
        return dict(r) if r else None

    def contacts(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM contacts ORDER BY COALESCE(full_name, push_name, phone)")]

    def contact(self, jid):
        r = self.db.execute("SELECT * FROM contacts WHERE jid=?", (jid,)).fetchone()
        return dict(r) if r else None

    def message(self, chat_jids, msg_id):
        q = f"SELECT * FROM messages WHERE id=? AND chat_jid IN ({', '.join('?' * len(chat_jids))})"
        r = self.db.execute(q, [msg_id] + list(chat_jids)).fetchone()
        return dict(r) if r else None

    def messages(self, chat_jids=None, query=None, sender_jids=None, since=None, until=None, limit=50, kinds=None):
        """Newest first. chat_jids/sender_jids/kinds: lists (a chat may be known under its phone and its lid jid)."""
        where, args = [], []
        if query:
            where.append("m.rowid IN (SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?)")
            args.append(fts_query(query))
        for col, vals in (("m.chat_jid", chat_jids), ("m.sender_jid", sender_jids), ("m.kind", kinds)):
            if vals:
                where.append(f"{col} IN ({', '.join('?' * len(vals))})")
                args += list(vals)
        if since is not None:
            where.append("m.ts >= ?")
            args.append(since)
        if until is not None:
            where.append("m.ts < ?")
            args.append(until)
        sql = ("SELECT m.* FROM messages m" + (" WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY COALESCE(m.ts, 0) DESC, COALESCE(m.server_id, 0) DESC, m.rowid DESC LIMIT ?")
        return [dict(r) for r in self.db.execute(sql, args + [limit])]

    def counts(self):
        one = lambda t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
        return {"chats": one("chats"), "contacts": one("contacts"), "messages": one("messages")}
