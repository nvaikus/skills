"""Account actions run in the user's own logged-in browser: a plain Chrome on its own profile, attached by playwright-cli over CDP.

OLX keeps buyer chat out of its public API (the Partner API covers only the user's own adverts), so login and seller
messages go through the web UI. Never a Playwright-launched or headless Chrome: automation switches meet bot walls.
One JS file per action in js/, prefixed by js/prelude.js; params go in as JSON, a dict comes back:
  {"status": "ok", ...} | {"status": "login"} | {"status": "captcha"} | {"status": "usage", "error"} | {"status": "fail", "step", "error", ...dump}
Never posts, buys or pays: the rail test greps js/ for those controls."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from ..core import paths
from ..core.errors import CliError, UsageError, Waiting

JS = Path(__file__).resolve().parent / "js"
SESSION = "olx"
PORT = 9335  # Chrome remote-debugging port; decathlon-pt uses 9334, 9333 is left for ad-hoc browsers
TIMEOUTS = {"nav": 60000, "el": 20000, "verify": 30000}  # ms: page load, one control, an outcome to show up
RUN_TIMEOUT = 240  # s: whole action incl. a dump; every browser wait is bounded on its own
CAPTCHA = ("OLX shows a captcha / security check in the olx Chrome window: the user solves it{where}. Then rerun;"
           " space out calls")
NOT_LOGGED_IN = "not signed in to OLX in the olx browser: run `olx login` (the user signs in once{where})"


def view_hint(cfg):
    """Remote view of the browser (config browser_view_url) for exit-5 texts."""
    url = cfg.get("browser_view_url")
    if url:
        return (f" - the browser runs on this host: send the user the link {url} (live browser screen, also on a phone)"
                " and wait for his \"done\"")
    return " in the Chrome window on this machine"


def session(cfg):
    return cfg.get("browser_session") or SESSION


def port(cfg):
    v = cfg.get("browser_port") or PORT
    try:
        return int(v)
    except (TypeError, ValueError):
        raise UsageError(f"browser_port must be a number, got {v!r}") from None


def cdp_url(cfg):
    return f"http://127.0.0.1:{port(cfg)}"


def _cli():
    exe = shutil.which("playwright-cli")
    if not exe:
        raise UsageError("playwright-cli not found: npm install -g @playwright/cli, then `olx login`")
    return exe


def _call(args, timeout):
    # cwd: playwright-cli drops .playwright-cli/ files into the working dir; keep them out of the user's repo
    try:
        return subprocess.run([_cli(), *args], capture_output=True, text=True, timeout=timeout,
                              cwd=str(paths.sub("browser")), encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise CliError(f"playwright-cli {args[1] if len(args) > 1 else ''} gave no answer in {timeout} s"
                       " (browser hung?): `playwright-cli -s=<session> detach`, stop the browser, rerun") from None


def debug_up(cfg):
    """Something listens on the debug port (a TCP connect; core/http stays the only URL opener)."""
    try:
        with socket.create_connection(("127.0.0.1", port(cfg)), timeout=3):
            return True
    except OSError:
        return False


def attached(name):
    r = _call(["list", "--json"], 30)
    try:
        browsers = json.loads(r.stdout).get("browsers") or []
    except ValueError:
        return False
    return any(b.get("name") == name and b.get("status") == "open" for b in browsers)


def chrome_exe(cfg):
    if cfg.get("browser_chrome"):
        return cfg["browser_chrome"]
    if sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    elif sys.platform == "win32":
        cands = [Path(os.environ.get(v, "")) / "Google/Chrome/Application/chrome.exe"
                 for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(v)]
    else:
        cands = [shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")]
    for c in cands:
        if c and Path(c).is_file():
            return str(c)
    raise UsageError("Google Chrome not found: install it or set config browser_chrome to its executable")


def launch_argv(cfg, name, url):
    """Plain Chrome on the session's own profile, behind config browser_launch_prefix (e.g. systemd-run) so it
    outlives the caller (bots that run `claude -p` per message kill the whole process tree)."""
    display = cfg.get("browser_display") or os.environ.get("DISPLAY") or ""
    subst = {"{cwd}": str(paths.sub("browser")), "{display}": display, "{ts}": str(int(time.time())),
             "{path}": os.environ.get("PATH", "")}
    prefix = []
    for a in cfg.get("browser_launch_prefix") or []:
        for k, v in subst.items():
            a = a.replace(k, v)
        prefix.append(a)
    flags = [f"--user-data-dir={paths.sub('browser', 'profiles', name)}", f"--remote-debugging-port={port(cfg)}",
             "--no-first-run", "--no-default-browser-check"]
    if sys.platform.startswith("linux"):
        flags.append("--password-store=basic")  # no keyring prompt on a headless host
    return prefix + [chrome_exe(cfg), *flags, url]


def _no_display():
    return sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def start_chrome(cfg, name, url):
    if cfg.get("browser_display") and _no_display():
        os.environ["DISPLAY"] = cfg["browser_display"]
    run_dir = f"/run/user/{os.getuid()}" if hasattr(os, "getuid") else ""
    if cfg.get("browser_launch_prefix") and not os.environ.get("XDG_RUNTIME_DIR") and run_dir and os.path.isdir(run_dir):
        os.environ["XDG_RUNTIME_DIR"] = run_dir  # systemd-run --user needs it; agent runners often drop it
    argv = launch_argv(cfg, name, url)
    log = paths.sub("browser") / "chrome.log"
    detach = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
              if sys.platform == "win32" else {"start_new_session": True})
    with open(log, "ab") as out:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=out, cwd=str(paths.sub("browser")),
                                **detach)
    deadline = time.time() + 30
    while time.time() < deadline:
        if debug_up(cfg):
            return
        if proc.poll() not in (None, 0):
            break
        time.sleep(0.5)
    hint = (" (no DISPLAY: set config browser_display to an always-on Xvfb display, see references/account.md)"
            if _no_display() else "")
    tail = log.read_text(encoding="utf-8", errors="replace").strip()[-300:]
    raise CliError(f"Chrome did not open its debug port {port(cfg)} in 30 s{hint}; log {log}: {tail}")


def ensure_open(cfg, name, url="about:blank"):
    """Headed plain Chrome on the session's own profile, attached over CDP; re-attaches to a running one."""
    if not debug_up(cfg):
        start_chrome(cfg, name, url)
    elif attached(name):
        return False
    r = _call([f"-s={name}", "attach", f"--cdp={cdp_url(cfg)}"], 60)
    if not attached(name):
        raise CliError(f"could not attach to Chrome on {cdp_url(cfg)}: {(r.stderr or r.stdout).strip()[-300:]}")
    return True


def script(action, params):
    body = (JS / f"{action}.js").read_text(encoding="utf-8")
    prelude = (JS / "prelude.js").read_text(encoding="utf-8")
    return ("async page => {\n  const P = " + json.dumps(params, ensure_ascii=False) + ";\n"
            + prelude + "\n  let step = 'start';\n  try {\n" + body
            + "\n  } catch (e) {\n    if (e === LOGIN) return {status: 'login', url: page.url()};\n"
            + "    if (e === CAPTCHA) return {status: 'captcha', url: page.url()};\n"
            + "    return await fail(step, String((e && e.message) || e));\n  }\n}\n")


def dump_text(res):
    """The page dump goes next to the screenshot: url, title, ARIA snapshot (run-code has no fs)."""
    if not res.get("aria") and not res.get("url"):
        return None
    p = Path(res.get("png") or paths.sub("dumps") / f"{res.get('step', 'fail')}-{int(time.time())}.png")
    txt = p.with_suffix(".txt")
    txt.parent.mkdir(parents=True, exist_ok=True)
    txt.write_text(f"url: {res.get('url')}\ntitle: {res.get('title')}\nerror: {res.get('error')}\n\n{res.get('aria') or ''}\n",
                   encoding="utf-8")
    return str(txt)


def interpret(cfg, action, out):
    """playwright-cli --json run-code stdout -> result dict, or raise by status."""
    out = (out or "").strip()
    if not out.startswith("{"):
        raise CliError(f"playwright-cli failed: {out[:300]}")
    env = json.loads(out)
    if env.get("isError"):
        raise CliError(f"browser script error in {action}: {str(env.get('error'))[:300]}")
    res = env.get("result")
    res = json.loads(res) if isinstance(res, str) else (res or {})
    st = res.get("status")
    if st == "ok":
        return res
    if st == "login":
        raise Waiting(NOT_LOGGED_IN.format(where=view_hint(cfg)))
    if st == "captcha":
        raise Waiting(CAPTCHA.format(where=view_hint(cfg)))
    if st == "usage":
        raise UsageError(res.get("error"))
    txt = dump_text(res)
    where = ", ".join(x for x in (res.get("png"), txt) if x)
    raise CliError(f"{action}: step '{res.get('step')}' failed: {res.get('error')}"
                   + (f" | page {res.get('url')}" if res.get("url") else "")
                   + (f" | dump: {where} (read it before retrying)" if where else ""))


def run(cfg, action, params, host):
    """Run js/<action>.js in the olx browser session on www.olx.<site> -> result dict (status ok)."""
    name = session(cfg)
    ensure_open(cfg, name)
    params = {**params, "host": host, "dumpDir": str(paths.sub("dumps")), "T": TIMEOUTS}
    path = paths.sub("browser") / f"run-{action}-{os.getpid()}.js"
    path.write_text(script(action, params), encoding="utf-8")
    try:
        r = _call([f"-s={name}", "--json", "run-code", f"--filename={path}"], RUN_TIMEOUT)
    finally:
        path.unlink(missing_ok=True)
    if r.returncode != 0 and not (r.stdout or "").strip().startswith("{"):
        raise CliError(f"playwright-cli failed: {(r.stderr or r.stdout).strip()[:300]}")
    return interpret(cfg, action, r.stdout)

