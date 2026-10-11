"""Account actions run in the user's own logged-in browser: playwright-cli, headed persistent Chrome.

eBay keeps cart / order / messaging APIs partner-only, so cart and seller messages go through the web UI.
One JS file per action in js/, prefixed by js/prelude.js; params go in as JSON, a dict comes back:
  {"status": "ok", ...} | {"status": "login"} | {"status": "captcha"} | {"status": "usage", "error"} | {"status": "fail", "step", "error", ...dump}
Never checkout, pay, bid or offer: the rail test greps js/ for those controls."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..core import paths
from ..core.errors import CliError, UsageError, Waiting
from . import markets

JS = Path(__file__).resolve().parent / "js"
SESSION = "ebay"
TIMEOUTS = {"nav": 60000, "el": 20000, "verify": 30000}  # ms: page load, one control, an outcome to show up
RUN_TIMEOUT = 240  # s: whole action incl. a dump; the browser waits above are each bounded
CAPTCHA = ("eBay shows a captcha in the ebay Chrome window: the user solves it there (tell him now), then rerun; "
           "slow down - it follows bursts of automated page loads")
NOT_LOGGED_IN = "not logged in to eBay in the ebay browser: run `ebay login` (the user signs in once in the Chrome window)"


def session(cfg):
    return os.environ.get("EBAY_BROWSER_SESSION") or cfg.get("browser_session") or SESSION


def domain(cfg, market=None):
    m = markets.norm(market) or markets.norm(cfg.get("market")) or markets.FALLBACK
    return markets.MARKETS[m][1]


def _cli():
    exe = shutil.which("playwright-cli")
    if not exe:
        raise UsageError("playwright-cli not found: npm install -g @playwright/cli, then `ebay login`")
    return exe


def _call(args, timeout):
    # cwd: open/snapshot drop .playwright-cli/ files into the working dir; keep them out of the user's repo
    try:
        return subprocess.run([_cli(), *args], capture_output=True, text=True, timeout=timeout,
                              cwd=str(paths.sub("browser")), encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise CliError(f"playwright-cli {args[1] if len(args) > 1 else ''} gave no answer in {timeout} s "
                       "(browser hung?): `playwright-cli -s=<session> close`, rerun") from None


def _reason(text):
    """Node stack traces open with source lines: return the Error lines, not the first 300 chars."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    hits = [ln for ln in lines if re.search(r"(?:^|\[)\w*Error\b", ln) and "new Error(" not in ln]
    return (" | ".join(hits) or " ".join(lines))[:400]


def is_open(name):
    r = _call(["list", "--json"], 30)
    try:
        browsers = json.loads(r.stdout).get("browsers") or []
    except ValueError:
        return False
    return any(b.get("name") == name and b.get("status") == "open" for b in browsers)


def ensure_open(name, url="about:blank"):
    """Headed: eBay challenges headless Chrome, and the user must see the window to log in."""
    if is_open(name):
        return False
    r = _call([f"-s={name}", "open", "--browser=chrome", "--headed", "--persistent", url], 90)
    if r.returncode != 0:
        hint = ""
        if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            hint = (" (headless host, no DISPLAY: browser actions need the user's desktop machine;"
                    " seller replies also arrive as eBay notification emails)")
        raise CliError(f"could not open the browser: {_reason(r.stderr or r.stdout)}{hint}")
    return True


def _script(action, params):
    body = (JS / f"{action}.js").read_text(encoding="utf-8")
    prelude = (JS / "prelude.js").read_text(encoding="utf-8")
    return ("async page => {\n  const P = " + json.dumps(params, ensure_ascii=False) + ";\n"
            + prelude + "\n  let step = 'start';\n  try {\n" + body
            + "\n  } catch (e) {\n    if (e === LOGIN) return {status: 'login'};\n    if (e === CAPTCHA) return {status: 'captcha', url: page.url()};\n"
            + "    return await fail(step, String((e && e.message) || e));\n  }\n}\n")


def _dump_text(res):
    """The page dump goes next to the screenshot: url, title, ARIA snapshot (run-code has no fs)."""
    if not res.get("aria") and not res.get("url"):
        return None
    p = Path(res.get("png") or paths.sub("browser", "dumps") / f"{res.get('step', 'fail')}-{int(time.time())}.png")
    txt = p.with_suffix(".txt")
    txt.parent.mkdir(parents=True, exist_ok=True)
    txt.write_text(f"url: {res.get('url')}\ntitle: {res.get('title')}\nerror: {res.get('error')}\n\n{res.get('aria') or ''}\n",
                   encoding="utf-8")
    return str(txt)


def run(cfg, action, params, market=None):
    """Run js/<action>.js in the ebay browser session -> result dict (status ok)."""
    name = session(cfg)
    ensure_open(name)
    dumps = paths.sub("browser", "dumps")
    params = {**params, "domain": domain(cfg, market), "dumpDir": str(dumps), "T": TIMEOUTS}
    script = paths.sub("browser") / f"run-{action}-{os.getpid()}.js"
    script.write_text(_script(action, params), encoding="utf-8")
    try:
        r = _call([f"-s={name}", "--json", "run-code", f"--filename={script}"], RUN_TIMEOUT)
    finally:
        script.unlink(missing_ok=True)
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out.startswith("{"):
        raise CliError(f"playwright-cli failed: {(r.stderr or out).strip()[:300]}")
    env = json.loads(out)
    if env.get("isError"):
        raise CliError(f"browser script error in {action}: {str(env.get('error'))[:300]}")
    res = json.loads(env.get("result") or "null") or {}
    st = res.get("status")
    if st == "ok":
        return res
    if st == "login":
        raise Waiting(NOT_LOGGED_IN)
    if st == "captcha":
        raise Waiting(CAPTCHA)
    if st == "usage":
        raise UsageError(res.get("error"))
    txt = _dump_text(res)
    where = ", ".join(x for x in (res.get("png"), txt) if x)
    raise CliError(f"{action}: step '{res.get('step')}' failed: {res.get('error')}"
                   + (f" | page {res.get('url')}" if res.get("url") else "")
                   + (f" | dump: {where} (read it before retrying)" if where else ""))
