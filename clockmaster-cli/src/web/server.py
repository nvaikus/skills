#!/usr/bin/env python3
"""Local web UI server: stdlib only, 127.0.0.1, HTTP/1.1 with Content-Length
and no-store on every reply.

- The built SPA (dist/) is resolved per request: a fresh build needs no restart.
- Port taken: only a previous instance of THIS server is evicted; anything else
  is refused, never killed.
- Re-execs itself when any src/**/*.py changes (a skill update in place).
- Every request passes web/peer.py (Linux: only this user or root may connect)
  and web/gate.py (owner gate for `ui --share`) first.

    server.py [--port N]
"""
import errno
import os
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import identity  # noqa: E402
import procs  # noqa: E402
from errors import UserError  # noqa: E402
from web import api, gate, peer  # noqa: E402

HOST = "127.0.0.1"
DIST = Path(__file__).resolve().parent / "dist"
CTYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
          ".ico": "image/x-icon", ".json": "application/json", ".woff2": "font/woff2",
          ".woff": "font/woff", ".map": "application/json", ".txt": "text/plain; charset=utf-8",
          ".webmanifest": "application/manifest+json"}
MARK = f"{identity.APP}-ui"  # in our argv: how a previous instance is recognised


class Req:
    def __init__(self, method, path, query, body):
        self.method, self.path, self.query, self.body = method, path, query, body


def h_static(req, rel):
    if rel.startswith("api/"):
        return api.fail(404, f"no route for {req.method} /{rel}")
    root = DIST.resolve()
    path = (root / (rel or "index.html")).resolve()
    if root != path and root not in path.parents:
        return api.fail(404, f"not found: /{rel}")
    if not path.is_file():
        if path.suffix:
            return api.fail(404, f"not found: /{rel}")
        path = root / "index.html"  # client-side route: serve the shell
        if not path.is_file():
            return api.text("no UI build yet — run `npm run build` in src/web/frontend\n")
    return api.text(path.read_bytes(), CTYPES.get(path.suffix, "application/octet-stream"))


ROUTES = [(m, re.compile(rx), h) for m, rx, h in
          api.ROUTES + [("GET", r"/(?P<rel>[\w.\-/@]*)$", h_static)]]


class Handler(BaseHTTPRequestHandler):
    server_version = MARK
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        try:
            self.peer_uid = peer.owner(self.client_address, self.connection.getsockname())
        except OSError:
            self.peer_uid = peer.UNKNOWN if peer.enabled() else None

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        url = urlparse(self.path)
        path = unquote(url.path)
        n = int(self.headers.get("Content-Length") or 0)
        req = Req(method, path, parse_qs(url.query), self.rfile.read(n) if n else b"")
        refused = peer.check(self.peer_uid)
        if refused:
            sys.stderr.write(f"{time.strftime('%H:%M:%S')} refused {self.client_address}: {refused}\n")
        else:
            refused = gate.check(method, self.headers)
        if refused:
            return self.reply(api.fail(403, refused))
        resp = None
        for m, rx, fn in ROUTES:
            hit = rx.match(path) if m == method else None
            if hit:
                resp = self.call(fn, req, hit.groupdict())
                break
        self.reply(resp or api.fail(404, f"no route for {method} {path}"))

    def call(self, fn, req, params):
        try:
            return fn(req, **params)
        except UserError as e:
            return api.fail(e.status, e.msg)  # a web form has no file:line
        except Exception as e:  # one bad request never takes the server down
            sys.stderr.write(f"{time.strftime('%H:%M:%S')} {type(e).__name__}: {e}\n")
            return api.fail(500, f"{type(e).__name__}: {e}")

    def reply(self, resp):
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.ctype)
        self.send_header("Content-Length", str(len(resp.body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(resp.body)
        sys.stdout.write(f"{time.strftime('%H:%M:%S')} {self.command} {self.path} -> {resp.status}\n")
        sys.stdout.flush()

    def log_message(self, fmt, *args):
        pass


# ---------- lifecycle ----------

def _sources():
    return sorted(identity.SRC_DIR.rglob("*.py"))


def _stamp():
    out = []
    for p in _sources():
        try:
            out.append((str(p), p.stat().st_mtime))
        except OSError:
            pass
    return out


def is_ours(cmd):
    """Our server: this skill's server.py, or anything carrying our tag."""
    return bool(cmd) and (str(identity.SERVER) in cmd or (identity.SERVER.name in cmd and MARK in cmd))


def bind(port):
    try:
        return ThreadingHTTPServer((HOST, port), Handler)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
    for pid, cmd in procs.listeners(port):
        if not is_ours(cmd):
            sys.exit(f"error: port {port} is held by pid {pid} ({cmd or '?'}) — not a {identity.APP} UI, refusing to kill it")
        print(f"port {port} held by a previous UI (pid {pid}) — replacing it", flush=True)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + 5
    while True:
        try:
            return ThreadingHTTPServer((HOST, port), Handler)
        except OSError as e:
            if e.errno != errno.EADDRINUSE or time.time() > deadline:
                raise
            time.sleep(0.2)


def watch(httpd):
    first = _stamp()
    while _stamp() == first:
        time.sleep(2)
    print("source changed — restarting", flush=True)
    httpd.restart = True
    httpd.shutdown()


def argv_for(port):
    """How to start this server; MARK rides along so a later instance (or
    `ui --stop`) can tell ours from a stranger on the same port."""
    return [sys.executable, str(identity.SERVER), "--port", str(port), "--tag", MARK]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    port = identity.UI_PORT
    while argv:
        a = argv.pop(0)
        if a in ("-h", "--help"):
            print(f"usage: server.py [--port N]   (default http://{HOST}:{identity.UI_PORT})")
            return 0
        if a == "--port" and argv:
            port = int(argv.pop(0))
        elif a == "--tag" and argv:
            argv.pop(0)
        else:
            sys.exit(f"error: unexpected argument '{a}'")
    if signal.getsignal(signal.SIGTERM) is signal.SIG_DFL and hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    httpd = bind(port)
    httpd.daemon_threads = True
    httpd.restart = False
    threading.Thread(target=watch, args=(httpd,), daemon=True).start()
    print(f"{identity.TITLE} UI -> http://{HOST}:{port}   (ctrl-c to stop)", flush=True)
    print(f"data: {identity.data_dir()}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        return 0
    finally:
        httpd.server_close()
    if httpd.restart:
        os.execv(sys.executable, argv_for(port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
