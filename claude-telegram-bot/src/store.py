"""Persistent state: owner + topic map `key -> {session_id, cwd, title, implicit}` + pending
requests `message_id -> {thread, chat, topic, msgs, started}`. key = config.topic_key: the thread id in the home chat,
`<chat>:<thread>` in an owner group (entries written before owner groups have no `topic`: their thread is it) (survive a restart; `claude-tg status` reads them).
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

    def topic(self, key) -> dict:
        with self._lock:
            t = self.data["topics"].get(str(key))
            if t is None:
                t = {"session_id": None, "cwd": self.default_cwd, "title": None, "implicit": None}
            return dict(t)

    def update(self, key, **fields):
        with self._lock:
            if str(key) in self._gone:
                return self.topic(key)
            t = self.topic(key)
            t.update(fields)
            self.data["topics"][str(key)] = t
            self._save()
            return dict(t)

    def drop(self, key):
        with self._lock:
            self._gone.add(str(key))
            gone = [k for k, e in self.pending().items() if str(e.get("topic", e["thread"])) == str(key)]
            for k in gone:
                self.data["pending"].pop(k)
            if self.data["topics"].pop(str(key), None) is not None or gone:
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
