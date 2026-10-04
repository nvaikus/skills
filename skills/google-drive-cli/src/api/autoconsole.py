"""Automatic mode of `gdrive onboard`: a background job sets up the Google Cloud side in a VISIBLE
Chrome window; the user only signs in and clicks "Continue" on the consent page. Optional: needs
Node.js + Playwright (playwright-core) + a Chrome/Chromium; without them onboarding stays manual.

Split of work: `scripts/console-auto.mjs` only drives the browser and speaks JSON lines (events
on its stdout, answers on its stdin). This module is the job around it and owns every gdrive
state change: config writes, client import, the PKCE login, the loopback catch of the redirect,
login finish. The foreground `onboard` starts the job and polls status.json for <= --wait s
(an agent command must return within ~240 s).

<profile>/auto/: status.json · job.log · plan.json · shots/ (screenshot + .txt page dump per failure or stall) ·
browser/ (Chrome profile holding the Google session: deleted when the job succeeds) ·
client.json (transient: imported, then deleted)."""
import http.server
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..core import config, paths, proc, profile
from ..core.errors import CliError
from . import onboard_say as say

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "console-auto.mjs"
ENTRY = Path(__file__).resolve().parents[2] / "gdrive.py"
TERMINAL = ("done", "failed")
USER_STATES = ("signin", "terms", "consent")
IDLE_S = 1800  # no event from the browser driver for this long = stuck
_avail = {}


def auto_dir(prof=None):
    return paths.sub(profile.dir(prof), "auto")


def node():
    for c in (os.environ.get("GDRIVE_NODE"), shutil.which("node"), "/opt/homebrew/bin/node", "/usr/local/bin/node"):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def unavailable():
    """None when automatic mode can run here, else the reason (shown to the agent)."""
    if "why" in _avail:
        return _avail["why"]
    why = _probe()
    _avail["why"] = why
    return why


def _probe():
    if os.environ.get("GDRIVE_AUTO", "").lower() in ("0", "off", "no"):
        return "switched off by GDRIVE_AUTO"
    if os.environ.get("SSH_CONNECTION"):
        return "remote (SSH) session: the browser window would open on another screen"
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "no screen (no DISPLAY)"
    exe = node()
    if not exe:
        return "Node.js is not installed"
    if not SCRIPT.is_file():
        return f"{SCRIPT} is missing"
    try:
        out = subprocess.run([exe, str(SCRIPT), "--check"], capture_output=True, text=True, timeout=30)
        got = json.loads(out.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return "the browser automation check failed"
    return None if got.get("ok") else got.get("reason") or "Playwright or Chrome not found"


# ---- foreground side -------------------------------------------------------------------------

def _read(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(p, data):
    paths.write_private(p, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def status(prof):
    """{} (never ran) or the job's status + alive. A dead job that never reported an end = failed."""
    d = auto_dir(prof)
    st = _read(d / "status.json")
    if not st:
        return {}
    st["alive"] = proc.alive(st.get("pid"))
    if not st["alive"] and st.get("state") not in TERMINAL:
        tail = "; ".join(proc.tail(d / "job.log", 3)) or "no log"
        st.update(state="failed", msg=f"the automation stopped unexpectedly ({tail[-300:]})")
    return st


def start(prof):
    """Start the background job (no-op while one runs)."""
    d = auto_dir(prof)
    if status(prof).get("alive"):
        return
    job = time.strftime("%Y%m%d-%H%M%S")
    _write(d / "status.json", {"job": job, "state": "starting", "step": "browser", "pid": None,
                               "updated": time.time()})
    pid = proc.spawn([sys.executable, str(ENTRY), "--profile", prof, "onboard", "--auto-job"], d / "job.log")
    st = _read(d / "status.json")
    if st.get("job") == job and not st.get("pid"):
        st["pid"] = pid
        _write(d / "status.json", st)


def wait(prof, st, seconds):
    """Poll until the job ends, newly needs the user (each such state is announced once),
    or the time is up. -> status."""
    d = auto_dir(prof)
    seen_p = d / "announced"
    try:
        seen = set(seen_p.read_text(encoding="utf-8").split())
    except OSError:
        seen = set()
    end = time.time() + max(seconds, 0)
    while True:
        st = status(prof)
        if not st.get("alive"):
            return st
        key = f"{st.get('job')}:{st.get('state')}"
        if st.get("state") in USER_STATES and key not in seen:
            with open(seen_p, "a", encoding="utf-8") as f:
                f.write(key + "\n")
            return st
        if time.time() >= end:
            return st
        time.sleep(2)


def stop(prof):
    st = status(prof)
    if not st.get("alive"):
        return False
    proc.terminate(st.get("pid"))
    st.pop("alive", None)
    st.update(state="failed", msg="stopped: manual mode chosen", updated=time.time())
    _write(auto_dir(prof) / "status.json", st)
    return True


# ---- the job ---------------------------------------------------------------------------------

class Job:
    def __init__(self, prof, note):
        self.prof, self.note, self.d = prof, note, auto_dir(prof)
        self.st = _read(self.d / "status.json") or {"job": time.strftime("%Y%m%d-%H%M%S")}
        self.st.update(pid=os.getpid(), state="starting", step="browser", msg=None, warnings=[])
        self.events = queue.Queue()
        self.child = None
        self.server = None
        self.finishing = False

    def set(self, **kw):
        self.st.update(kw, updated=time.time())
        _write(self.d / "status.json", self.st)

    def send(self, obj):
        try:
            self.child.stdin.write(json.dumps(obj) + "\n")
            self.child.stdin.flush()
        except (OSError, ValueError):
            pass

    def plan(self):
        cfg = config.load()
        done = set(cfg.get("done_steps") or [])
        todo = []
        if not cfg.get("client_id"):
            todo += [] if cfg.get("project_id") else ["project"]
            todo += [] if cfg.get("apis_confirmed") else ["apis"]
            todo += [] if "consent" in done else ["consent"]
            if cfg.get("audience") != "internal":
                todo += [] if "branding" in done else ["branding"]
                todo += [] if "publish" in done or cfg.get("keep_testing") else ["publish"]
            todo.append("client")
        todo.append("login")
        from . import auth
        return {"todo": todo, "projectId": cfg.get("project_id"),
                "email": (cfg.get("account") or {}).get("email"),
                "outDir": str(self.d), "browserDir": str(paths.sub(self.d, "browser")),
                "shotsDir": str(paths.sub(self.d, "shots")), "console": say.CONSOLE,
                "projectName": say.PROJECT_NAME, "appName": say.APP_NAME, "home": say.HOME_URL,
                "privacy": say.PRIVACY_URL, "domain": say.DOMAIN, "apis": list(say.APIS.values()),
                "redirect": auth.REDIRECT}

    def run(self):
        exe = node()
        leftover = self.d / "client.json"
        if leftover.exists() and not config.load().get("client_id"):
            self.import_client(str(leftover))  # a previous job died between download and import
        plan = self.plan()
        _write(self.d / "plan.json", plan)
        self.set(state="starting", step="browser", msg="opening the browser")
        log = open(self.d / "job.log", "a", encoding="utf-8")
        self.child = subprocess.Popen([exe, str(SCRIPT), str(self.d / "plan.json")], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8", bufsize=1)
        threading.Thread(target=self._read_child, daemon=True).start()
        try:
            self.loop()
        finally:
            self.stop_server()
            try:
                self.child.stdin.close()
            except OSError:
                pass
            try:
                self.child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
            self.child.stdout.close()
            log.close()
        if self.st.get("state") == "done":
            time.sleep(2)  # Chrome releases its profile files
            shutil.rmtree(self.d / "browser", ignore_errors=True)

    def _read_child(self):
        for line in self.child.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                self.events.put(("ev", json.loads(line)))
            except ValueError:
                continue
        self.events.put(("eof", None))

    def loop(self):
        while self.st.get("state") not in TERMINAL:
            try:
                kind, val = self.events.get(timeout=IDLE_S)
            except queue.Empty:
                self.fail(self.st.get("step"), "no progress for 30 minutes")
                break
            if kind == "eof":
                if self.st.get("state") not in TERMINAL:
                    tail = "; ".join(proc.tail(self.d / "job.log", 3))
                    self.fail(self.st.get("step"), f"the browser automation ended early ({tail[-300:]})")
                break
            if kind == "redirect":
                self.finish_login(val)
                continue
            self.handle(val)

    def fail(self, step, msg, shot=None):
        self.set(state="failed", step=step or self.st.get("step"), msg=msg, screenshot=shot)
        self.send({"quit": True, "close": False})

    def handle(self, ev):  # noqa: C901 - one branch per driver event
        e = ev.get("ev")
        if e == "state":
            self.set(state=ev.get("state") or "working", step=ev.get("step") or self.st.get("step"), msg=ev.get("msg"))
        elif e == "email" and ev.get("email"):
            acct = config.load().get("account") or {}
            if not acct.get("email"):
                config.update(account={**acct, "email": ev["email"]})
        elif e == "project":
            config.update(project_id=ev["id"])
        elif e == "audience":
            config.update(audience=ev.get("kind"))
        elif e == "done":
            step = ev.get("step")
            if step == "apis":
                config.update(apis_confirmed=True)
            elif step in ("consent", "branding", "publish"):
                cfg = config.load()
                config.update(done_steps=sorted(set(cfg.get("done_steps") or []) | {step}))
        elif e == "warn":
            self.set(warnings=self.st.get("warnings", []) + [f"{ev.get('step')}: {ev.get('msg')}"])
            if ev.get("screenshot"):
                self.set(screenshot=ev["screenshot"])
        elif e == "client_file":
            self.import_client(ev["path"])
        elif e == "need_consent_url":
            self.consent_url()
        elif e == "redirect":
            self.finish_login(ev.get("url"))
        elif e == "fail":
            self.fail(ev.get("step"), ev.get("msg"), ev.get("screenshot"))

    def import_client(self, path):
        from . import onboarding
        try:
            onboarding.apply(config.load(), {"client_file": path}, self.note)
        except CliError as e:
            return self.fail("client", f"the downloaded key could not be imported: {e}")
        Path(path).unlink(missing_ok=True)

    def consent_url(self):
        from . import auth
        cfg = config.load()
        url = auth.start(cfg, cfg["client_id"])
        self.start_server()
        self.send({"consent_url": url})

    def finish_login(self, url):
        from . import auth, drive, google
        if self.finishing or not url:
            return
        self.finishing = True
        cfg = config.load()
        try:
            code, state = auth.parse_redirect(url)
            auth.finish(cfg, cfg["client_id"], cfg["client_secret"], code, state)
        except CliError as e:
            self.finishing = False
            return self.fail("login", str(e))
        try:
            drive.about(cfg["remote"])
        except CliError as e:
            why = google.reasons(e)
            if e.status == 403 and not {"accessNotConfigured", "SERVICE_DISABLED"} & why:
                auth.drop_token(cfg["remote"])
                return self.fail("login", "the Google Drive box was not ticked on the access page")
        self.set(state="done", step="login", msg="connected")
        self.send({"quit": True, "close": True})

    # the browser lands on http://127.0.0.1:53682/?code=...: catch it here as well (the driver
    # also reports the URL it saw, whichever comes first wins)
    def start_server(self):
        from . import auth
        events = self.events

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = f"<h2>{say.APP_NAME} is connected.</h2><p>You can close this window.</p>".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
                if "code=" in self.path or "error=" in self.path:
                    events.put(("redirect", f"{auth.REDIRECT.rstrip('/')}{self.path}"))

            def log_message(self, *a):
                pass

        if self.server:
            return
        try:
            self.server = http.server.HTTPServer(("127.0.0.1", auth.PORT), Handler)
        except OSError:
            self.server = None  # port busy: the driver's report of the URL is enough
            return
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop_server(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def run_job(prof, note):
    Job(prof, note).run()
