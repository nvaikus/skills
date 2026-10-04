"""`gmail onboard`: a resumable state machine. Every run applies the answers it was given, then
walks the steps with REAL checks (client present, token works, Gmail API answers) and stops at
the first one that needs the user. Texts (relayed word for word) live in `onboard_say`.

The OAuth client is reused when one exists here (another gmail profile, else a gdrive profile):
one Desktop client serves any number of Google accounts. Only without one the console steps run."""
import json
import os
import re
import time
from pathlib import Path

from ..core import config, paths, profile
from ..core.errors import UsageError
from . import onboard_say as say

PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
DONE_STEPS = ("apis", "consent", "branding", "publish")
PROPAGATION_S = 300  # a fresh "Gmail API on" may answer SERVICE_DISABLED for a few minutes


# ---- the OAuth client ---------------------------------------------------------------------------

def read_client_file(path):
    """Desktop-app client JSON -> (client_id, client_secret, project_id). Wrong kind -> exit 2."""
    p = Path(os.path.expanduser(path))
    if not p.is_file():
        raise UsageError(f"no file at {p}: give the path of the downloaded client_secret_*.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except ValueError:
        raise UsageError(f"{p} is not a JSON file: download the client JSON again (DOWNLOAD JSON button)") from None
    if "web" in data:
        raise UsageError("this key is for a 'Web application'; create one with Application type = Desktop app")
    inst = data.get("installed")
    if not isinstance(inst, dict) or not inst.get("client_id") or not inst.get("client_secret"):
        raise UsageError(f"{p} is not an OAuth client file (no installed.client_id/client_secret)")
    return inst["client_id"], inst["client_secret"], inst.get("project_id")


def _read(p):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def client_sources(prof):
    """Clients on this machine, best first: gmail profiles whose Gmail API is proven, the gdrive
    profile of the same name, the gdrive default, other gdrive profiles, other gmail profiles."""
    out = []
    gm = paths.root_peek()
    gmail = [(n, _read(gm / n / "config.json")) for n in profile.names() if n != prof]
    gd = paths.gdrive_root()
    gdrive_names = sorted(p.name for p in gd.iterdir() if (p / "config.json").exists()) if gd.is_dir() else []
    gd_default = _read(gd / "config.json").get("default_profile")
    order = sorted(gdrive_names, key=lambda n: (n != prof, n != gd_default, n))
    for n, c in gmail:
        if c.get("gmail_api"):
            out.append(("gmail", n, c))
    for n in order:
        out.append(("gdrive", n, _read(gd / n / "config.json")))
    for n, c in gmail:
        if not c.get("gmail_api"):
            out.append(("gmail", n, c))
    res = []
    for kind, n, c in out:
        if c.get("client_id") and c.get("client_secret") and "..." not in str(c["client_secret"]):
            res.append({"source": f"{kind}:{n}", "client_id": c["client_id"], "client_secret": c["client_secret"],
                        "project_id": c.get("project_id"), "gmail_api": bool(c.get("gmail_api")),
                        "app_name": c.get("app_name") or ("Personal Drive" if kind == "gdrive" else None),
                        "email": (c.get("account") or {}).get("email")})
    return res


def _take(src):
    ch = {k: src[k] for k in ("client_id", "client_secret", "project_id", "app_name")}
    ch["client_from"] = src["source"]
    if src.get("gmail_api"):
        ch["apis_confirmed"] = True
    return ch


def apply(cfg, a, prof, note):
    """Store the answers passed on this run. -> updated config."""
    ch = {}
    if a.get("project"):
        pid = a["project"].strip()
        if not PROJECT_ID.match(pid):
            raise UsageError(f"{pid!r} does not look like a Project ID (lowercase, digits, dashes, 6-30 chars, "
                             "e.g. personal-mail-123456) - the project NAME is different; copy the ID")
        ch["project_id"] = pid
    if a.get("account") and not (cfg.get("account") or {}).get("domain"):
        ch["account"] = {**(cfg.get("account") or {}), "email": a["account"].strip()}
    done = list(a.get("done") or [])
    for d in done:
        if d not in DONE_STEPS:
            raise UsageError(f"--done {d}: one of {', '.join(DONE_STEPS)}")
    if "apis" in done:
        ch.update(apis_confirmed=True, apis_confirmed_at=time.time())
    rest = [d for d in done if d != "apis"]
    if rest:
        ch["done_steps"] = sorted(set(cfg.get("done_steps") or []) | set(rest))
    if a.get("audience"):
        ch["audience"] = a["audience"]
    if a.get("keep_testing"):
        ch["keep_testing"] = True
    if a.get("new_client"):
        ch.update(client_id=None, client_secret=None, client_from="new", app_name=say.APP_NAME,
                  apis_confirmed=False, gmail_api=False)
    if a.get("client_from"):
        spec = a["client_from"] if ":" in a["client_from"] else f"gdrive:{a['client_from']}"
        src = next((s for s in client_sources(prof) if s["source"] == spec), None)
        if not src:
            have = ", ".join(s["source"] for s in client_sources(prof)) or "none"
            raise UsageError(f"--client-from {a['client_from']}: no OAuth client there (available: {have})")
        ch.update(_take(src), gmail_api=False)
        note(say.reused(src["source"], src.get("email")))
    if a.get("client_file"):
        cid, secret, pid = read_client_file(a["client_file"])
        ch.update(client_id=cid, client_secret=secret, client_from="file", gmail_api=False)
        if cfg.get("client_from") != "new":
            ch["app_name"] = None
        if pid:
            if cfg.get("project_id") and pid != cfg["project_id"]:
                note(f"the key file belongs to project {pid}, not {cfg['project_id']}: using {pid}")
                ch["apis_confirmed"] = False
            ch["project_id"] = pid
        note("key imported; the downloaded file is no longer needed (it holds a secret: you may delete it)")
    return config.update(prof, **ch) if ch else cfg


def adopt(cfg, prof, note):
    """No client yet and none chosen: take the best one on this machine, if any."""
    if cfg.get("client_id") or cfg.get("client_from") == "new":
        return cfg
    srcs = client_sources(prof)
    if not srcs:
        return cfg
    note(say.reused(srcs[0]["source"], srcs[0].get("email"))
         + (f" Others: {', '.join(s['source'] for s in srcs[1:])} (--client-from NAME)." if len(srcs) > 1 else ""))
    return config.update(prof, **_take(srcs[0]))


# ---- the machine ------------------------------------------------------------------------------

def result(status, sid, text, nxt=None, now=False, **facts):
    return {"status": status, "id": sid, "say": text, "next": nxt, "now": now, "facts": facts}


def _new_client(cfg, run):
    done = set(cfg.get("done_steps") or [])
    if not cfg.get("project_id"):
        return result("waiting", "project", say.project(cfg), f"{run} --project <PROJECT_ID>")
    if not cfg.get("apis_confirmed"):
        return result("waiting", "apis", say.apis(cfg), f"{run} --done apis")
    if "consent" not in done:
        return result("waiting", "consent", say.consent(cfg), f"{run} --done consent --audience external|internal")
    if cfg.get("audience") != "internal":
        if "branding" not in done:
            return result("waiting", "branding", say.branding(cfg), f"{run} --done branding")
        if "publish" not in done and not cfg.get("keep_testing"):
            return result("waiting", "publish", say.publish(cfg),
                          f"{run} --done publish   |   cannot publish: {run} --keep-testing")
    return result("waiting", "client", say.client(cfg), f"{run} --client-file <PATH>")


def advance(env, cfg, prof, note, relogin=False):
    """-> result dict. env: live checks (LiveEnv in production, a fake in tests). relogin: show the
    login step although the token works (adds scopes requested later, e.g. filters); the old token
    stays until the new one arrives."""
    run = f"gmail --profile {prof} onboard"
    cfg = adopt(cfg, prof, note)
    if not cfg.get("client_id"):
        return _new_client(cfg, run)
    finish = f"printf '%s' '<PASTED_ADDRESS>' | gmail --profile {prof} login --finish && {run}"
    if not cfg.get("apis_confirmed") and not cfg.get("gmail_api"):
        return result("waiting", "apis", say.apis(cfg), f"{run} --done apis")
    if not env.has_token():
        return result("waiting", "login", say.login(cfg, env.login_url(cfg)), finish)
    state = env.probe()  # ok | disabled | token | scope
    if state in ("token", "scope"):
        env.drop_token()
        why = say.UNTICKED if state == "scope" else ""
        return result("waiting", "login", say.login(cfg, env.login_url(cfg), again=state == "token", why=why), finish)
    if state == "disabled":
        config.update(prof, gmail_api=False)
        fresh = time.time() - (cfg.get("apis_confirmed_at") or 0) < PROPAGATION_S
        if fresh:
            return result("running", "apis-propagating", say.PROPAGATING, run, now=True)
        config.update(prof, apis_confirmed=False)
        return result("waiting", "apis", say.apis(cfg, still=True), f"{run} --done apis")
    if relogin:
        why = say.SETTINGS if env.lacks_settings() else ""
        return result("waiting", "relogin", say.login(cfg, env.login_url(cfg), why=why), finish)
    stats = env.stats()
    acct = {**(cfg.get("account") or {}), "email": stats.get("emailAddress") or (cfg.get("account") or {}).get("email")}
    cfg = config.update(prof, gmail_api=True, apis_confirmed=True, account=acct)
    if not acct.get("domain") and acct.get("refresh_expires_in") and not cfg.get("keep_testing"):
        done = set(cfg.get("done_steps") or [])
        keep = f"   |   keep 7-day logins: {run} --keep-testing"
        if "branding" not in done:
            return result("waiting", "branding", say.branding(cfg, say.TESTING), f"{run} --done branding{keep}")
        if "publish" not in done:
            return result("waiting", "publish", say.publish(cfg, say.TESTING), f"{run} --done publish{keep}")
        env.drop_token()
        return result("waiting", "relogin", say.login(cfg, env.login_url(cfg), why=say.RELOGIN), finish + keep)
    if not profile.root_config().get("default_profile"):
        profile.set_default(prof)
    filters = not env.lacks_settings()
    return result("done", "done", say.done(cfg, prof, stats, filters), None, email=acct.get("email"), filters=filters,
                  messages=stats.get("messagesTotal"), threads=stats.get("threadsTotal"),
                  client_from=cfg.get("client_from"))


# ---- live environment -------------------------------------------------------------------------

class LiveEnv:
    def __init__(self, prof):
        self.prof = prof
        self._stats = None

    def has_token(self):
        from . import auth
        return auth.logged_in(self.prof)

    def drop_token(self):
        from . import auth
        auth.drop(self.prof)

    def login_url(self, cfg):
        from . import auth
        return auth.start(self.prof, cfg["client_id"], reuse=True, hint=(cfg.get("account") or {}).get("email"))

    def lacks_settings(self):
        from . import auth
        return auth.lacks_settings(self.prof)

    def probe(self):
        from . import google
        try:
            self._stats = google.get(self.prof, "/profile") or {}
            return "ok"
        except UsageError as e:
            rs = google.reasons(e)
            if {"accessNotConfigured", "SERVICE_DISABLED"} & rs:
                return "disabled"
            if {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"} & rs:
                return "scope"
            if e.status in (400, 401) or e.status is None:
                return "token"
            raise

    def stats(self):
        return self._stats or {}
