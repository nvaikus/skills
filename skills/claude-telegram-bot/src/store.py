"""Persistent state: owner + topic map `thread_id -> {session_id, cwd, title, implicit}` + pending
requests `message_id -> {thread, chat, msgs, started}` (survive a restart; `claude-tg status` reads them).
One JSON file, atomic replace, guarded by a lock (topic workers write concurrently)."""
import json
import os
import threading
from pathlib import Path

GENERAL = 0  # key for messages outside any topic ("All messages")


class Store:
    def __init__(self, path: Path, default_cwd: str):
        self.path = path
        self.default_cwd = os.path.expanduser(default_cwd)
        self._lock = threading.RLock()
        self.data = {"owner_id": None, "topics": {}}
        self._gone = set()  # dropped threads: late writes from a finishing run must not resurrect them
        if path.exists():
            self.data.update(json.loads(path.read_text()))

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1))
        os.replace(tmp, self.path)

    @property
    def owner_id(self):
        return self.data.get("owner_id")

    def set_owner(self, uid: int):
        with self._lock:
            self.data["owner_id"] = uid
            self._save()

    def topic(self, thread: int) -> dict:
        with self._lock:
            t = self.data["topics"].get(str(thread))
            if t is None:
                t = {"session_id": None, "cwd": self.default_cwd, "title": None, "implicit": None}
            return dict(t)

    def update(self, thread: int, **fields):
        with self._lock:
            if str(thread) in self._gone:
                return self.topic(thread)
            t = self.topic(thread)
            t.update(fields)
            self.data["topics"][str(thread)] = t
            self._save()
            return dict(t)

    def drop(self, thread: int):
        with self._lock:
            self._gone.add(str(thread))
            gone = [k for k, e in self.pending().items() if e["thread"] == thread]
            for k in gone:
                self.data["pending"].pop(k)
            if self.data["topics"].pop(str(thread), None) is not None or gone:
                self._save()

    def pending(self) -> dict:
        with self._lock:
            return {k: dict(e) for k, e in self.data.get("pending", {}).items()}

    def pend(self, key, **fields):
        with self._lock:
            e = self.data.setdefault("pending", {}).setdefault(str(key), {})
            e.update(fields)
            self._save()

    def unpend(self, key):
        with self._lock:
            if self.data.get("pending", {}).pop(str(key), None) is not None:
                self._save()
