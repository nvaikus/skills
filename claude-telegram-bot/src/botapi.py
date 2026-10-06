"""Minimal Telegram Bot API client (stdlib). The token never leaves this module:
URLs are built here and never logged; errors carry only Telegram's description."""
import http.client
import json
import mimetypes
import os
import shutil
import socket
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

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


class Bot:
    def __init__(self, token: str, api: str = API):
        self._token = token
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

    def call(self, method, _timeout=35, _retries=3, **params):
        params = {k: v for k, v in params.items() if v is not None}
        data = json.dumps(params).encode()
        for attempt in range(_retries + 1):
            try:
                return self._post(method, data, "application/json", _timeout)
            except TgError as e:
                if e.code == 429 and e.retry_after and attempt < _retries:
                    time.sleep(min(e.retry_after, 30) + 0.5)
                    continue
                raise

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
        return self._post(method, b"".join(parts), f"multipart/form-data; boundary={boundary}", _timeout)

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
