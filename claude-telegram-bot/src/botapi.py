"""Minimal Telegram Bot API client (stdlib). The token never leaves this module:
URLs are built here and never logged; errors carry only Telegram's description."""
import http.client
import json
import logging
import mimetypes
import os
import shutil
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: no lock, the file stays race-tolerant (atomic replace)
    fcntl = None

log = logging.getLogger("claude-tg")

API = "https://api.telegram.org"
CONNECT_TIMEOUT = 4  # per address; the call's timeout applies to reads only


class _Net:
    family = None  # last family that connected: tried first next time


def fast_connect(address, timeout=None, source_address=None, *_):
    """socket.create_connection with a short connect timeout per resolved address, preferring the family
    that worked last. Plain create_connection spends the whole call timeout (35-65 s) on an address that
    blackholes SYNs - e.g. a flaky IPv6 route - before trying the next one."""
    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    infos.sort(key=lambda i: i[0] != _Net.family)
    err = None
    for fam, typ, proto, _, addr in infos:
        sock = socket.socket(fam, typ, proto)
        try:
            sock.settimeout(min(CONNECT_TIMEOUT, timeout) if timeout else CONNECT_TIMEOUT)
            if source_address:
                sock.bind(source_address)
            sock.connect(addr)
            sock.settimeout(timeout)
            _Net.family = fam
            return sock
        except OSError as e:
            err = e
            sock.close()
    raise err or OSError(f"no address for {host}")


class _Conn(http.client.HTTPSConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = fast_connect  # __init__ sets it per instance


class _Handler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_Conn, req, context=self._context)


_open = urllib.request.build_opener(_Handler()).open


class TgError(Exception):
    def __init__(self, method, code, description, retry_after=None):
        super().__init__(f"{method}: {code} {description}")
        self.method, self.code, self.description, self.retry_after = method, code, description, retry_after


class Skipped(TgError):
    """A cosmetic call dropped locally (flood wait or rate budget): no HTTP request was made."""
    def __init__(self, method, why):
        super().__init__(method, 429, f"skipped locally ({why})")


class Flood:
    """Per-chat send state shared by every thread of one Bot - and, with `path`, by every process (the bot and
    CLI calls like notify/spawn/send/topic-icon) through a JSON file under STATE_DIR. Telegram's limits are per
    chat, shared across topics (one 429 bans the whole chat). `until`: flood wait from a 429's retry_after.
    Bucket: cosmetic calls (status edits, drafts, typing) spend RATE tokens/s up to BURST; real sends spend too
    (down to -BURST) but are never refused, so parallel topics' cosmetics shrink to what's left.
    Times are wall clock (time.time) so other processes can read them. The file is rewritten atomically under
    an flock; any file error falls back to this process's memory."""
    RATE, BURST = 0.5, 5.0
    # Groups (chat id < 0): Telegram allows ~20 messages/min per group, edits included -> 0.2/s (12/min) for
    # cosmetics leaves room for real sends, which spend the same bucket.
    GROUP_RATE, GROUP_BURST = 0.2, 3.0
    COST = {"sendChatAction": 0.25, "deleteMessage": 0.0}  # deletes clean up (status, stream): never budgeted

    def __init__(self, clock=time.time, path=None):
        self.clock, self.lock = clock, threading.Lock()
        self.path = Path(path) if path else None
        self.until, self.since, self.bucket = {}, {}, {}
        self._seen = None  # (inode, mtime_ns) of the file last read or written: unchanged = memory is current

    # ---- shared file (no path = memory only) ----
    def _open(self):
        """Lock fd for the file, or None. Caller holds self.lock."""
        if not self.path:
            return None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            return None
        if fcntl:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError:
                pass
        try:
            st = os.stat(self.path)
        except OSError:
            return fd
        if (st.st_ino, st.st_mtime_ns) != self._seen:
            try:
                data = json.loads(self.path.read_text())
                self.until = {k: v["until"] for k, v in data.items() if v.get("until")}
                self.since = {k: v.get("since", v["until"]) for k, v in data.items() if v.get("until")}
                self.bucket = {k: (float(v["tokens"]), float(v["at"])) for k, v in data.items() if "tokens" in v}
                self._seen = (st.st_ino, st.st_mtime_ns)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                pass
        return fd

    def _close(self, fd, dirty):
        if fd is None:
            return
        try:
            if dirty:
                data = {}
                for k, (tokens, at) in self.bucket.items():
                    data.setdefault(k, {}).update(tokens=round(tokens, 3), at=at)
                for k, u in self.until.items():
                    data.setdefault(k, {}).update(until=u, since=self.since.get(k, u))
                tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
                tmp.write_text(json.dumps(data))
                os.replace(tmp, self.path)
                st = os.stat(self.path)
                self._seen = (st.st_ino, st.st_mtime_ns)
        except OSError:
            pass
        finally:
            os.close(fd)  # releases the flock

    # ---- API ----
    def left(self, chat) -> float:
        """Seconds of flood wait left for this chat; logs the end of a wait once."""
        chat = str(chat)
        with self.lock:
            fd = self._open()
            dirty = False
            try:
                until = self.until.get(chat)
                if until is None:
                    return 0.0
                now = self.clock()
                if now < until:
                    return until - now
                del self.until[chat]
                dirty = True
                log.warning("flood wait over: chat %s, %d s", chat, now - self.since.pop(chat, now))
                return 0.0
            finally:
                self._close(fd, dirty)

    def ready(self, chat, method="editMessageText") -> bool:
        """Would a cosmetic call go out now? Lets callers skip work (and keep their state) up front."""
        if self.left(chat):
            return False
        with self.lock:
            fd = self._open()
            try:
                return self._tokens(str(chat)) >= self.COST.get(method, 1.0)
            finally:
                self._close(fd, False)

    def limits(self, chat) -> tuple:
        """(rate, burst) of this chat's bucket: groups (negative ids) get the tighter group budget."""
        return (self.GROUP_RATE, self.GROUP_BURST) if str(chat).startswith("-") else (self.RATE, self.BURST)

    def _tokens(self, chat) -> float:
        now = self.clock()
        rate, burst = self.limits(chat)
        tokens, at = self.bucket.get(chat, (burst, now))
        tokens = min(burst, tokens + max(0.0, now - at) * rate)
        self.bucket[chat] = (tokens, now)
        return tokens

    def take(self, chat, method, cosmetic) -> bool:
        chat = str(chat)
        with self.lock:
            fd = self._open()
            cost = self.COST.get(method, 1.0)
            try:
                tokens = self._tokens(chat)
                if cosmetic and cost and tokens < cost:
                    return False
                self.bucket[chat] = (max(-self.limits(chat)[1], tokens - cost), self.clock())
                return True
            finally:
                self._close(fd, bool(cost))

    def hit(self, chat, retry_after, method):
        chat = str(chat)
        with self.lock:
            fd = self._open()
            try:
                now = self.clock()
                if chat not in self.until or self.until[chat] <= now:
                    self.since[chat] = now
                    log.warning("flood wait %s s: chat %s (%s); cosmetic calls skipped, real sends wait",
                                retry_after, chat, method)
                self.until[chat] = max(self.until.get(chat, 0.0), now + retry_after)
                self.bucket[chat] = (-self.limits(chat)[1], now)  # come back slowly
            finally:
                self._close(fd, True)


class Bot:
    def __init__(self, token: str, api: str = API, state_dir=None, on_wait=None):
        """state_dir: share the flood state with other processes (STATE_DIR/flood.json). on_wait(seconds): told
        before a real send sleeps out a flood wait (CLI: a stderr note)."""
        self._token = token
        self.flood = Flood(path=Path(state_dir) / "flood.json" if state_dir else None)
        self.on_wait = on_wait
        self.api = (api or API).rstrip("/")  # a local Bot API server (--local) for files > 20 MB

    def _url(self, method):
        return f"{self.api}/bot{self._token}/{method}"

    def _post(self, method, data: bytes, ctype: str, timeout: float):
        req = urllib.request.Request(self._url(method), data=data, headers={"Content-Type": ctype})
        try:
            with _open(req, timeout=timeout) as r:
                body = json.load(r)
        except urllib.error.HTTPError as e:
            try:
                body = json.load(e)
            except Exception:
                raise TgError(method, e.code, "HTTP error") from None
        except urllib.error.URLError as e:
            raise TgError(method, 0, f"network: {e.reason}") from None
        if not body.get("ok"):
            params = body.get("parameters") or {}
            raise TgError(method, body.get("error_code"), body.get("description", ""), params.get("retry_after"))
        return body["result"]

    def _gated(self, method, chat, cosmetic, retries, post):
        """post() under the chat's flood state: cosmetic = Skipped during a wait / over budget; real = sleep out
        the wait, retry a 429 with its full retry_after."""
        attempt = 0
        while True:
            if chat is not None:
                left = self.flood.left(chat)
                if left:
                    if cosmetic:
                        raise Skipped(method, "flood wait")
                    if self.on_wait:
                        self.on_wait(left)
                    time.sleep(left + 0.5)
                    continue
                if not self.flood.take(chat, method, cosmetic):
                    raise Skipped(method, "rate budget")
            try:
                return post()
            except TgError as e:
                if e.code != 429 or not e.retry_after:
                    raise
                if chat is not None:
                    self.flood.hit(chat, e.retry_after, method)
                if attempt >= retries:
                    raise
                attempt += 1
                if chat is None:
                    time.sleep(e.retry_after + 0.5)

    def call(self, method, _timeout=35, _retries=3, **params):
        """_retries=0 with a chat_id = cosmetic: skipped locally (Skipped) during a flood wait or over the
        chat's budget. Anything else waits out the whole flood wait - a real answer is never dropped by it."""
        params = {k: v for k, v in params.items() if v is not None}
        data = json.dumps(params).encode()
        chat = params.get("chat_id")
        return self._gated(method, chat, _retries == 0 and chat is not None, _retries,
                           lambda: self._post(method, data, "application/json", _timeout))

    def upload(self, method, field, path: Path, _timeout=120, **params):
        """multipart/form-data upload (sendDocument etc.)."""
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in params.items():
            if v is None:
                continue
            v = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
            f"Content-Type: {mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}\r\n\r\n".encode() + path.read_bytes() + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        return self._gated(method, params.get("chat_id"), False, 3,
                           lambda: self._post(method, body, f"multipart/form-data; boundary={boundary}", _timeout))

    def download(self, file_id: str, dest: Path, timeout: float = 120) -> Path:
        """getFile + fetch. A local server (--local) fetches the whole file inside getFile and returns an
        absolute path on its disk (same host, same user): the file is moved out, never served over HTTP.
        That path contains the token - never log it."""
        info = self.call("getFile", file_id=file_id, _timeout=timeout, _retries=0 if timeout > 120 else 3)
        path = info.get("file_path") or ""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if os.path.isabs(path):
            try:
                shutil.copyfile(path, dest)
            except OSError as e:
                raise TgError("download", 0, f"local Bot API file not readable ({e.strerror})") from None
            try:
                os.unlink(path)  # the server re-fetches on the next getFile; don't keep a second copy
            except OSError:
                pass
            return dest
        url = f"{self.api}/file/bot{self._token}/{path}"
        try:
            with _open(url, timeout=timeout) as r, open(dest, "wb") as f:
                while chunk := r.read(1 << 16):
                    f.write(chunk)
        except urllib.error.URLError:
            raise TgError("download", 0, "file download failed") from None
        return dest

    def redact(self, text: str) -> str:
        return text.replace(self._token, "<token>") if self._token else text
