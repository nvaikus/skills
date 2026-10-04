"""index.sqlite: what the index knows about every item of the provider's corpus.

Every item is kept (not only the ones inside the profile's scope): an item moved INTO the scope
later is then placed by the next reconcile without walking its subtree. `path` is the item's
path inside the scope as the mount shows it (NULL = outside); `key` is the content fingerprint
(md5, or modifiedTime for Google-native files); `idx_key` is the key the index text was built
from - equal keys mean the text is current and nothing is downloaded again."""
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY, parent TEXT, name TEXT, mime TEXT, folder INTEGER NOT NULL DEFAULT 0,
  key TEXT, md5 TEXT, modified TEXT, size INTEGER,
  native INTEGER NOT NULL DEFAULT 0,  -- export-only content (no bytes to download)
  ext TEXT,            -- suffix the mount adds ('.docx' for a Google Doc, '' for a normal file); NULL = not shown by the mount
  path TEXT,           -- mount-relative path, NULL = outside the scope
  idx_key TEXT, extractor TEXT, error TEXT, indexed_at TEXT);
CREATE INDEX IF NOT EXISTS items_parent ON items(parent);
CREATE INDEX IF NOT EXISTS items_path ON items(path);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""
COLS = ("id", "parent", "name", "mime", "folder", "native", "key", "md5", "modified", "size", "ext")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Manifest:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---- meta -------------------------------------------------------------------------------
    def meta(self, k, default=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    def set_meta(self, **kv):
        with self.db:
            self.db.executemany("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                                [(k, None if v is None else str(v)) for k, v in kv.items()])

    # ---- items ------------------------------------------------------------------------------
    def upsert(self, items):
        """items: provider dicts (COLS). Keeps path/idx_key; a changed key makes the text stale."""
        rows = [tuple(it.get(c, 0 if c in ("folder", "native") else None) for c in COLS) for it in items]
        with self.db:
            self.db.executemany(
                f"INSERT INTO items({','.join(COLS)}) VALUES({','.join('?' * len(COLS))}) "
                "ON CONFLICT(id) DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in COLS[1:]), rows)

    def remove(self, ids):
        """-> the removed rows (their stored paths tell reconcile which index files to delete)."""
        gone = []
        with self.db:
            for i in ids:
                r = self.db.execute("SELECT * FROM items WHERE id=?", (i,)).fetchone()
                if r:
                    gone.append(dict(r))
                    self.db.execute("DELETE FROM items WHERE id=?", (i,))
        return gone

    def remove_except(self, keep):
        """After a full listing: rows the listing no longer returned are gone."""
        stale = [r["id"] for r in self.db.execute("SELECT id FROM items") if r["id"] not in keep]
        return self.remove(stale)

    def get(self, i):
        r = self.db.execute("SELECT * FROM items WHERE id=?", (i,)).fetchone()
        return dict(r) if r else None

    def rows(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM items")]

    def children(self, parent):
        return [dict(r) for r in self.db.execute("SELECT * FROM items WHERE parent=?", (parent,))]

    def by_path(self, path):
        r = self.db.execute("SELECT * FROM items WHERE path=?", (path,)).fetchone()
        return dict(r) if r else None

    def set_paths(self, changes):
        with self.db:
            self.db.executemany("UPDATE items SET path=? WHERE id=?", [(p, i) for i, p in changes.items()])

    def mark(self, i, key, extractor, error=None):
        with self.db:
            self.db.execute("UPDATE items SET idx_key=?, extractor=?, error=?, indexed_at=? WHERE id=?",
                            (key, extractor, error, now(), i))

    def pending(self, prefix=None):
        """In-scope files whose text is missing or stale, in path order."""
        q = ("SELECT * FROM items WHERE folder=0 AND path IS NOT NULL AND ext IS NOT NULL "
             "AND (idx_key IS NULL OR idx_key != key)")
        args = ()
        if prefix:
            q += " AND (path=? OR path LIKE ? ESCAPE '\\')"
            esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args = (prefix, esc + "/%")
        return [dict(r) for r in self.db.execute(q + " ORDER BY path", args)]

    def counts(self, prefix=None):
        """File totals of the scope, or of the subtree at path `prefix`."""
        q = ("SELECT COUNT(*) AS files, SUM(idx_key IS NOT NULL AND idx_key = key) AS indexed, "
             "SUM(extractor IN ('meta','error')) AS meta_only, SUM(error IS NOT NULL) AS errors "
             "FROM items WHERE folder=0 AND path IS NOT NULL AND ext IS NOT NULL")
        args = ()
        if prefix:
            esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q += " AND path LIKE ? ESCAPE '\\'"
            args = (esc + "/%",)
        r = self.db.execute(q, args).fetchone()
        files = r["files"] or 0
        return {"files": files, "indexed": r["indexed"] or 0, "pending": files - (r["indexed"] or 0),
                "meta_only": r["meta_only"] or 0, "errors": r["errors"] or 0}

    def reset(self):
        with self.db:
            self.db.execute("DELETE FROM items")
            self.db.execute("DELETE FROM meta")
