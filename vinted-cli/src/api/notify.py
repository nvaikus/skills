"""`watch run --notify`: one Telegram message per run via `claude-tg notify --topic <key>` (never the Bot API).
Hits (new + drops) and failures only; nothing new = no message. A failure kind (blocked / error) is alerted
when it starts and then at most once a day. A failed send never fails the run."""
import html
import json
import shutil
import socket
import subprocess
import time

from ..core import paths
from ..core.errors import Broken

MAX_LINES = 25
REPEAT = 86400


def _line(r):
    drop = f" ⬇ was {html.escape(r['change'][5:].split('>')[0])}" if r["change"].startswith("drop") else ""
    price = f"{r['price']} {r['cur']}".strip()
    return (f"{html.escape(price)} · <a href=\"{html.escape(r['url'])}\">{html.escape(r['title'][:70])}</a>"
            f"{html.escape(' · ' + ' · '.join(x for x in (r.get('brand'), r.get('size')) if x)) if r.get('brand') or r.get('size') else ''}{drop}")


def message(hits, failures):
    new = sum(1 for h in hits if h["change"] == "new")
    drops = len(hits) - new
    blocked = any(isinstance(e, Broken) for e in failures.values())
    head = [f"{new} new" if new else "", f"{drops} price drop{'s' if drops != 1 else ''}" if drops else "",
            ("❌ Vinted blocked / changed" if blocked else f"❌ {len(failures)} watch(es) failed") if failures else ""]
    lines = [f"<b>vinted watch — {', '.join(x for x in head if x)}</b>"]
    if failures:
        first = next(iter(failures.values()))
        lines.append(f"⚠️ {html.escape(', '.join(failures))}: {html.escape(str(first)[:300])}")
    shown, by_watch = 0, {}
    for h in hits:
        by_watch.setdefault(h["watch"], []).append(h)
    for w, rows in by_watch.items():
        if shown >= MAX_LINES:
            break
        lines += ["", f"<b>{html.escape(w)}</b>"]
        for r in rows[:MAX_LINES - shown]:
            lines.append(_line(r))
            shown += 1
    if len(hits) > shown:
        lines.append(f"… +{len(hits) - shown} more: <code>vinted watch run</code> output / -j")
    lines += ["", f"<i>vinted watch run · {html.escape(socket.gethostname())}</i>"]
    return "\n".join(lines)


def due_failures(failed, now=None):
    """Failures worth alerting now: kind new for that watch, or last alert > a day ago. Recovered watches cleared."""
    now = now or int(time.time())
    p = paths.root_peek() / "watch" / "alerted.json"
    try:
        before = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        before = {}
    after, due = {}, {}
    for n, e in failed.items():
        kind = "blocked" if isinstance(e, Broken) else "error"
        prev = before.get(n) or {}
        if prev.get("kind") != kind or now - prev.get("at", 0) >= REPEAT:
            due[n] = e
            after[n] = {"kind": kind, "at": now}
        else:
            after[n] = prev
    paths.write_private(p, json.dumps(after))
    return due


def send(text, topic, note):
    exe = shutil.which("claude-tg")
    if not exe:
        note("claude-tg not on PATH: notification not sent")
        return False
    try:
        r = subprocess.run([exe, "notify", "--html", "--topic", topic], input=text, capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        note(f"claude-tg notify failed: {e}")
        return False
    if r.returncode != 0:
        note(f"claude-tg notify exit {r.returncode}: {r.stderr.strip()[:200]}")
        return False
    return True
