"""Outbound leak filter: blocks bot messages that quote protected files verbatim (config `protected_paths`).

Index = hashes of every N-word window (N = `protect_min_words`) of the text files under the protected paths;
a message with any N consecutive words matching a window is a leak. Words = runs of letters/digits, lowercased,
so markdown/HTML punctuation and whitespace never matter. Paraphrase is not caught: this is a backstop against
verbatim copies, not a policy. Off (None from `from_config`) unless `protected_paths` is set. Pure stdlib."""
import glob
import html
import logging
import os
import re
import threading
import time
from array import array
from bisect import bisect_left

log = logging.getLogger("claude-tg")

WORD = re.compile(r"[^\W_]+")
TAG = re.compile(r"<[^>]+>")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
MAX_FILE = 1 << 20   # bigger files are not indexed
RECHECK = 10.0       # min seconds between mtime scans (refresh is called at every run start)


def words(text: str, is_html=False) -> list:
    if is_html:
        text = html.unescape(TAG.sub(" ", text))
    return WORD.findall(text.lower())


def _windows(ws: list, n: int):
    for i in range(len(ws) - n + 1):
        yield hash(tuple(ws[i:i + n]))


def _text(path: str):
    """File text, or None: unreadable, binary (NUL in the first 8 KB) or too big."""
    try:
        if os.path.getsize(path) > MAX_FILE:
            return None
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if b"\0" in raw[:8192]:
        return None
    return raw.decode("utf-8", "ignore")


class Guard:
    def __init__(self, paths, min_words=12, marker=".user-made"):
        self.paths = [os.path.expandvars(os.path.expanduser(p)) for p in paths]
        self.n = max(2, int(min_words))
        self.marker = marker
        self.lock = threading.Lock()
        self.sig = None
        self.checked = -RECHECK
        self.index = array("q")  # sorted window hashes
        self.files = []          # indexed files (to name the source of a match)
        self.roots = []          # realpaths of protected dirs/files (symlink targets too) for file blocking
        self.exempt = []         # realpaths of dirs holding the marker

    # ---------- index ----------
    def _scan(self):
        """(files, roots, exempt, signature) by walking the protected paths, following symlinks once."""
        files, roots, exempt, seen = [], [], [], set()
        for pat in self.paths:
            for top in sorted(glob.glob(pat)) or [pat]:
                if os.path.isfile(top):
                    files.append(top)
                    roots.append(os.path.realpath(top))
                    continue
                if not os.path.isdir(top):
                    continue
                roots.append(os.path.realpath(top))  # even when unlistable (exec-only dir)
                for d, dirs, names in os.walk(top, followlinks=True):
                    real = os.path.realpath(d)
                    if real in seen:
                        dirs[:] = []
                        continue
                    seen.add(real)
                    if self.marker and self.marker in names:
                        exempt.append(real)
                        dirs[:] = []
                        continue
                    if os.path.islink(d):
                        roots.append(real)
                    dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
                    for x in names:
                        f = os.path.join(d, x)
                        files.append(f)
                        if os.path.islink(f):
                            roots.append(os.path.realpath(f))
        sig = []
        for f in files:
            try:
                st = os.stat(f)
                sig.append((f, st.st_mtime_ns, st.st_size))
            except OSError:
                pass
        return files, roots, exempt, tuple(sig)

    def refresh(self, force=False):
        """Rebuild when any protected file was added, removed or changed. Cheap: stat only, at most every
        RECHECK seconds."""
        with self.lock:
            now = time.monotonic()
            if not force and now - self.checked < RECHECK:
                return
            self.checked = now
            files, roots, exempt, sig = self._scan()
            self.roots, self.exempt = roots, exempt
            if sig == self.sig:
                return
            t0 = time.monotonic()
            hs, kept = set(), []
            for f in files:
                text = _text(f)
                if text is None:
                    continue
                ws = words(text)
                if len(ws) >= self.n:
                    hs.update(_windows(ws, self.n))
                    kept.append(f)
            self.index = array("q", sorted(hs))
            self.files, self.sig = kept, sig
            log.info("leak filter: %d files, %d windows of %d words (%.1fs)", len(kept), len(self.index), self.n,
                     time.monotonic() - t0)

    def stats(self) -> str:
        return f"{len(self.files)} files, {len(self.index)} windows of {self.n} words"

    # ---------- checks ----------
    def _has(self, h) -> bool:
        i = bisect_left(self.index, h)
        return i < len(self.index) and self.index[i] == h

    def match(self, text: str, is_html=False):
        """Protected file the text quotes (>= n consecutive words), '?' if not found again, or None."""
        if not text or not self.index:
            return None
        ws = words(text, is_html)
        for i, h in enumerate(_windows(ws, self.n)):
            if self._has(h):
                return self._source(ws[i:i + self.n])
        return None

    def _source(self, window) -> str:
        h = hash(tuple(window))
        for f in self.files:
            text = _text(f)
            if text and h in set(_windows(words(text), self.n)):
                return f
        return "?"

    def protected_file(self, path) -> bool:
        """A file under a protected path (realpath; exempt dirs excluded)."""
        real = os.path.realpath(path)
        under = lambda root: real == root or real.startswith(root.rstrip("/") + "/")  # noqa: E731
        return any(under(r) for r in self.roots) and not any(under(e) for e in self.exempt)

    def file_leak(self, path):
        """Why a file must not be sent (protected path or quoting content), or None."""
        if self.protected_file(path):
            return os.path.realpath(path)
        text = _text(path)
        return self.match(text) if text else None


def from_config(cfg: dict):
    paths = cfg.get("protected_paths") or []
    if not paths:
        return None
    g = Guard(paths, cfg.get("protect_min_words") or 12, cfg.get("protect_exempt_marker", ".user-made"))
    g.refresh(force=True)
    return g
