"""`gdrive onboard`: a resumable state machine. Every run applies the answers it was given, then
walks the steps with REAL checks (binary runs, client imported, token works, APIs answer, mount
is up, service loaded, index exists), performs the ones that need nobody, and stops at the first
one that needs the user. Texts (relayed word for word) live in `onboard_say`.

Steps 3-8 (Google Cloud console) have nothing to check before a login exists: in manual mode they
advance on the user's answer (--project, --done ...), in auto mode a background browser job
(`autoconsole`) does them; both are re-verified live after login (APIs probed, Testing token)."""
import json
import os
import re
import shutil
from pathlib import Path

from ..core import config, paths, profile
from ..core.errors import UsageError
from . import onboard_say as say
from .onboard_say import APIS, CONSOLE, TOTAL, default_where  # noqa: F401 - re-exported

PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
DONE_STEPS = ("apis", "consent", "branding", "publish")
# auto-job steps in run order; the first three happen before anything can be done by hand
ORDER = ("browser", "signin", "terms", "project", "apis", "consent", "branding", "publish", "client", "login")
USER_STATES = ("signin", "terms", "consent")  # the job waits for a click in the browser


# ---- answers ---------------------------------------------------------------------------------

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


def check_what(what):
    if what == "/" or what.startswith("/") or what.startswith("shared:"):
        return what.rstrip("/") or "/"
    return "/" + what.strip("/")  # a bare folder name means a folder of My Drive


def apply(cfg, a, note):
    """Store the answers passed on this run. -> updated config."""
    ch = {}
    if a.get("project"):
        pid = a["project"].strip()
        if not PROJECT_ID.match(pid):
            raise UsageError(f"{pid!r} does not look like a Project ID (lowercase, digits, dashes, 6-30 chars, "
                             "e.g. personal-drive-123456) - the project NAME is different; copy the ID")
        ch["project_id"] = pid
    if a.get("account") and not (cfg.get("account") or {}).get("domain"):
        ch["account"] = {**(cfg.get("account") or {}), "email": a["account"].strip()}
    if a.get("mode"):
        ch["mode"] = a["mode"]
    done = list(a.get("done") or []) + (["apis"] if a.get("apis_done") else [])
    for d in done:
        if d not in DONE_STEPS:
            raise UsageError(f"--done {d}: one of {', '.join(DONE_STEPS)}")
    if "apis" in done:
        ch["apis_confirmed"] = True
    rest = [d for d in done if d != "apis"]
    if rest:
        ch["done_steps"] = sorted(set(cfg.get("done_steps") or []) | set(rest))
    if a.get("audience"):
        ch["audience"] = a["audience"]
    if a.get("keep_testing"):
        ch["keep_testing"] = True
    if a.get("client_file"):
        cid, secret, pid = read_client_file(a["client_file"])
        ch.update(client_id=cid, client_secret=secret)
        if pid:
            if cfg.get("project_id") and pid != cfg["project_id"]:
                note(f"the key file belongs to project {pid}, not {cfg['project_id']}: using {pid}")
                ch["apis_confirmed"] = False
            ch["project_id"] = pid
        note("key imported; the downloaded file is no longer needed (it holds a secret: you may delete it)")
    m = dict(cfg.get("mount") or {})
    if a.get("mount"):
        m["what"] = check_what(a["mount"])
    if a.get("where"):
        m["where"] = os.path.abspath(os.path.expanduser(a["where"]))
    if a.get("persist"):
        m["persist"] = a["persist"] == "yes"
    if m != (cfg.get("mount") or {}):
        if m.get("what") and not m.get("where"):
            m["where"] = default_where(profile.active())
        ch["mount"] = m
    return config.update(**ch) if ch else cfg


def import_legacy(cfg, note):
    """v0.1 kept one client in ~/.gdrive.json and the token in ~/.config/gdrive/rclone.conf:
    take them over once for a profile that has neither."""
    if cfg.get("client_id"):
        return cfg
    legacy = paths.legacy_config()
    if legacy.exists():
        try:
            old = json.loads(legacy.read_text(encoding="utf-8-sig"))
        except ValueError:
            old = {}
        if old.get("client_id") and old.get("client_secret") and "..." not in str(old["client_secret"]):
            cfg = config.update(client_id=old["client_id"], client_secret=old["client_secret"])
            note(f"imported the OAuth client from {legacy} (v0.1 config; it is not read again)")
    conf, mine = paths.legacy_rclone_conf(), profile.dir() / "rclone.conf"
    if cfg.get("client_id") and conf.exists() and not mine.exists():
        shutil.copy2(conf, mine)
        os.chmod(mine, 0o600)
        note(f"imported the login from {conf}")
    return cfg


# ---- the machine ------------------------------------------------------------------------------

def result(status, step, sid, text, nxt=None, now=False, **facts):
    """now: the next command is run right away by the agent, without waiting for an answer."""
    return {"status": status, "step": step, "total": TOTAL, "id": sid, "say": text, "next": nxt, "now": now,
            "facts": facts}


def first_open(cfg, env):
    """The first Google-side step (3-9) not done yet, or None when a token exists."""
    if not cfg.get("client_id"):
        done = set(cfg.get("done_steps") or [])
        if not cfg.get("project_id"):
            return "project"
        if not cfg.get("apis_confirmed"):
            return "apis"
        if "consent" not in done:
            return "consent"
        if cfg.get("audience") != "internal":
            if "branding" not in done:
                return "branding"
            if "publish" not in done and not cfg.get("keep_testing"):
                return "publish"
        return "client"
    return None if env.has_token() else "login"


def _manual(cfg, prof, step, run, why=""):
    """Manual text for a Google-side step before login (3-8)."""
    if step == "project":
        return result("waiting", 3, "project", why + say.project(cfg, prof), f"{run} --project <PROJECT_ID>")
    if step == "apis":
        return result("waiting", 4, "apis", why + say.apis(cfg), f"{run} --done apis")
    if step == "consent":
        return result("waiting", 5, "consent", why + say.consent(cfg),
                      f"{run} --done consent --audience external|internal")
    if step == "branding":
        return result("waiting", 6, "branding", say.branding(cfg, why), f"{run} --done branding")
    if step == "publish":
        return result("waiting", 7, "publish", say.publish(cfg, why),
                      f"{run} --done publish   |   cannot publish: {run} --keep-testing")
    return result("waiting", 8, "client", why + say.client(cfg), f"{run} --client-file <PATH>")


def _progressed(st, cur):
    """A failed job may resume by itself once the user did the failed step by hand."""
    step = st.get("step")
    return (st.get("state") == "failed" and step in ORDER and cur in ORDER
            and ORDER.index(step) >= ORDER.index("project") and ORDER.index(cur) > ORDER.index(step))


def _auto(env, cfg, run, note, restart):
    """Mode auto: start / follow the browser job. -> (result or None, text prefix for the manual step)."""
    cur = first_open(cfg, env)
    if cur is None:
        return None, ""
    why = env.auto_unavailable()
    if why:
        note(f"automatic setup unavailable here ({why}): showing the manual steps")
        return None, ""
    st = env.auto_status()
    if not st.get("alive"):
        if not (restart or not st or _progressed(st, cur)):
            if st.get("state") == "failed":
                return None, say.auto_failed(st)
            return None, ""  # the job finished earlier; what is still open is done by hand
        env.auto_start(cfg)
        st = env.auto_status()
    st = env.auto_wait(st)
    state, step = st.get("state"), st.get("step") or "browser"
    if st.get("alive"):
        num = say.AUTO_STEP.get(step, 3)
        if state in ("signin", "terms", "consent"):
            text = {"signin": say.auto_signin, "terms": lambda c: say.auto_terms(),
                    "consent": say.auto_consent}[state](cfg)
            return result("waiting", num, f"auto-{state}", text, run, now=True), ""
        return result("running", num, f"auto-{step}", say.auto_working(st), run, now=True), ""
    if state == "failed":
        return None, say.auto_failed(st)
    return None, ""


def advance(env, cfg, prof, note, restart=False):
    """-> result dict. env: live checks/actions (LiveEnv in production, a fake in tests).
    restart: --mode auto given on this run (start the browser job again even after a failure)."""
    run = f"gdrive --profile {prof} onboard"
    # 1. rclone
    if not env.rclone_ok():
        note(f"installing rclone: {env.install_rclone()}")
    cfg = import_legacy(cfg, note)
    # 2. automatic or manual
    if not cfg.get("client_id") and not cfg.get("mode"):
        why = env.auto_unavailable()
        if not why:
            return result("waiting", 2, "mode", say.mode(), f"A: {run} --mode auto   |   B: {run} --mode manual")
        cfg = config.update(mode="manual")
        note(f"automatic setup unavailable here ({why}): manual steps")
    prefix = ""
    if cfg.get("mode") == "auto":
        r, prefix = _auto(env, cfg, run, note, restart)
        if r:
            return r
        cfg = config.load()  # the job may have written project, client, token
    # 3-8. project, APIs, consent screen, branding, publish, key file
    if not cfg.get("client_id"):
        r = _manual(cfg, prof, first_open(cfg, env), run, prefix)
        if prefix:
            r["next"] += f"   |   retry automatic: {run} --mode auto"
        return r
    finish = f"printf '%s' '<PASTED_ADDRESS>' | gdrive --profile {prof} login --finish && {run}"
    # 9. login (+ the live re-checks of 3-7)
    who = env.whoami()
    if who is None:
        return result("waiting", 9, "login", say.login(cfg, env.login_url(cfg), again=env.has_token(), why=prefix),
                      finish)
    cfg["account"] = {**(cfg.get("account") or {}), **{k: v for k, v in who.items() if v}}
    disabled = env.disabled_apis()
    if disabled:
        config.update(apis_confirmed=False)
        if not cfg.get("project_id"):
            raise UsageError(f"APIs switched off: {', '.join(disabled)}; set --project <ID> of the key's project")
        return result("waiting", 4, "apis", say.apis(cfg, disabled), f"{run} --done apis")
    acct = cfg.get("account") or {}
    if not acct.get("domain") and acct.get("refresh_expires_in") and not cfg.get("keep_testing"):
        done = set(cfg.get("done_steps") or [])
        keep = f"   |   keep 7-day logins: {run} --keep-testing"
        if "branding" not in done:
            return result("waiting", 6, "branding", say.branding(cfg, prefix + say.TESTING),
                          f"{run} --done branding{keep}")
        if "publish" not in done:
            return result("waiting", 7, "publish", say.publish(cfg, prefix + say.TESTING),
                          f"{run} --done publish{keep}")
        return result("waiting", 9, "relogin", say.login(cfg, env.login_url(cfg), why=say.RELOGIN), finish + keep)
    # 10-11. what to mount, autostart
    m = cfg.get("mount") or {}
    if not m.get("what"):
        return result("waiting", 10, "mount", say.mount(cfg, prof, env.shared_drives()),
                      f"{run} --mount '/' | --mount '/<Folder>' | --mount 'shared:<Drive>'  [--where DIR]")
    if m.get("persist") is None:
        if not env.can_persist():
            m = config.update(mount={**m, "persist": False})["mount"]
            note("autostart is not supported on this system: after a restart run `gdrive mount`")
        else:
            return result("waiting", 11, "autostart", say.PERSIST, f"{run} --persist yes|no")
    status = env.mount_up(cfg)
    if status not in ("mounted", "ok"):
        return result("running", 11, "mount-starting",
                      f"Google Drive is still connecting at {m['where']}. I will check again in a minute.", run)
    # 12. index
    svc = env.service_on()
    if svc is False:
        env.install_service()
    idx = env.index_progress()
    if not idx.get("built") and not idx.get("running"):
        env.start_index()
        idx = {**idx, "running": True}
    return result("done", 12, "done", say.done(cfg, m, idx, svc is not None), None,
                  email=(cfg.get("account") or {}).get("email"), where=m["where"], what=m["what"],
                  persist=bool(m.get("persist")), **{f"index_{k}": v for k, v in idx.items()})


# ---- live environment -------------------------------------------------------------------------

class LiveEnv:
    def __init__(self, cfg, prof, wait_s, note, auto_wait_s=None):
        self.cfg, self.prof, self.wait_s, self.note = cfg, prof, wait_s, note
        self.auto_wait_s = auto_wait_s or wait_s

    def rclone_ok(self):
        from . import rclone
        return rclone.installed_version() is not None

    def install_rclone(self):
        from . import rclone
        ver = rclone.latest_version()
        rclone.install(ver)
        if rclone.installed_version() != ver:
            raise UsageError(f"rclone {ver} was downloaded but does not run on this machine")
        return ver

    def has_token(self):
        from . import auth
        return auth.logged_in(self.cfg["remote"])

    def whoami(self):
        """-> {email} when the stored token works (live call), None when there is none / it is refused."""
        from . import auth, drive
        if not auth.logged_in(self.cfg["remote"]):
            return None
        try:
            u = (drive.about(self.cfg["remote"]) or {}).get("user", {})
        except UsageError as e:
            if e.status in (None, 400, 401):
                return None
            if e.status == 403:  # Drive API off: the token itself is fine
                return {"email": (self.cfg.get("account") or {}).get("email")}
            raise
        return {"email": u.get("emailAddress")}

    def login_url(self, cfg):
        from . import auth
        return auth.start(cfg, cfg["client_id"], reuse=True)

    def disabled_apis(self):
        from . import google
        off = []
        probes = {"drive": f"{google.DRIVE}/about?fields=user", "docs": f"{google.DOCS}/documents/gdrive-api-probe",
                  "sheets": f"{google.SHEETS}/spreadsheets/gdrive-api-probe"}
        for name, url in probes.items():
            try:
                google.get(self.cfg["remote"], url)
            except UsageError as e:
                if {"accessNotConfigured", "SERVICE_DISABLED"} & google.reasons(e):
                    off.append(name)
                elif e.status in (None, 401):
                    raise
            except Exception:  # noqa: BLE001 - 400 on a bogus id means the API answered = enabled
                pass
        return off

    def shared_drives(self):
        from . import google
        try:
            got = google.get(self.cfg["remote"], f"{google.DRIVE}/drives", {"pageSize": 100}) or {}
        except Exception:  # noqa: BLE001 - listing is a courtesy
            return []
        return [d["name"] for d in got.get("drives", [])]

    def can_persist(self):
        from . import persist
        try:
            persist.kind()
            return True
        except UsageError:
            return False

    def mount_up(self, cfg):
        from . import mounting, mounts, persist
        m = cfg["mount"]
        keep = bool(m.get("persist"))
        old = mounts.load(mounts.mount_id(m["where"]))
        if old and old["what"] == m["what"] and bool(old.get("persist")) != keep and old["mode"] != "sync":
            if mounts.dirty_files(old):
                self.note("autostart setting not applied yet: uploads are pending; run onboard again later")
            else:  # restart it under (or out of) the autostart service
                if old.get("persist"):
                    persist.remove(old, lambda: mounts.unmount(old))
                mounts.unmount(old)
                mounts.forget(old)
        _, status = mounting.bring_up(cfg, m["what"], m["where"], "auto", bool(m.get("persist")), None,
                                      self.wait_s, self.note)
        return status

    def service_on(self):
        """True on · False off (install it) · None unsupported here."""
        from . import service
        st = service.state(self.prof)
        return None if st == "unsupported" else st == "on"

    def install_service(self):
        from . import service
        service.install(self.prof)

    def index_progress(self):
        from . import indexer
        out = {"running": bool(indexer.Lock(self.prof).holder())}
        if indexer.manifest_path(self.prof).exists():
            man = indexer.open_manifest(self.prof)
            try:
                out.update(built=bool(man.meta("cursor")), **man.counts())
            finally:
                man.close()
        return out

    def start_index(self):
        from . import indexer
        indexer.spawn(self.prof)

    # automatic mode: the browser job (api/autoconsole)
    def auto_unavailable(self):
        from . import autoconsole
        return autoconsole.unavailable()

    def auto_status(self):
        from . import autoconsole
        return autoconsole.status(self.prof)

    def auto_start(self, cfg):
        from . import autoconsole
        autoconsole.start(self.prof)

    def auto_wait(self, st):
        from . import autoconsole
        return autoconsole.wait(self.prof, st, self.auto_wait_s)

    def auto_stop(self):
        from . import autoconsole
        return autoconsole.stop(self.prof)
