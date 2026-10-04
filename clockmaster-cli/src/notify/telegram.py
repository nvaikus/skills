"""Telegram mirror via `claude-tg notify` (the claude-telegram-bot skill's bot writes to its owner). Opt-in through
<data>/notify.yaml:

    telegram: on
    telegram_topic: system            # optional; claude-tg notify_topics key or literal name; default: its default topic
    claude_tg: ~/.local/bin/claude-tg  # optional; default: claude-tg on PATH, else ~/.local/bin/claude-tg

Text = `<task> — ❌ failed in 1m 04s`, the last lines of the run's output in <pre>, a muted meta line.
Scheduler services run with a bare PATH, hence the ~/.local/bin fallback.
"""
import html
import shutil
import subprocess
from pathlib import Path

import identity
import notify
import store

KEYS = {"telegram", "telegram_topic", "claude_tg"}
OUTPUT_CHARS = 1500  # one Telegram message holds 4096; the run's log stays in the UI
TIMEOUT = 60


def settings(cfg=None):
    cfg = notify.config() if cfg is None else cfg
    if not cfg or cfg.get("telegram", "off") != "on":
        return None
    cli = cfg.get("claude_tg") or shutil.which("claude-tg") or str(identity.home() / ".local" / "bin" / "claude-tg")
    return {"cli": Path(cli).expanduser(), "topic": cfg.get("telegram_topic", "")}


def text(msg):
    head = f"<b>{html.escape(msg.title)}</b> — {notify.LABELS.get(msg.status, msg.status)} in {store.fmt_dur(msg.duration)}"
    out = ""
    if msg.log_path:
        try:
            out = Path(msg.log_path).read_text(encoding="utf-8", errors="replace").strip("\n")
        except OSError:
            pass
    if len(out) > OUTPUT_CHARS:
        out = "…\n" + out[-OUTPUT_CHARS:]
    m = msg.meta
    tail = f"<i>exit {m.get('exitCode')} · trigger {html.escape(str(m.get('trigger', '?')))} · run {html.escape(str(m.get('runId', '?')))}</i>"
    return "\n".join([head] + ([f"<pre>{html.escape(out)}</pre>"] if out else []) + [tail])


def argv(cfg):
    a = [str(cfg["cli"]), "notify", "--html"]
    return a + ["--topic", cfg["topic"]] if cfg["topic"] else a


def send(msg):
    cfg = settings()
    if not cfg:
        return
    who = f"{msg.title} {msg.run_id}"
    try:
        p = subprocess.run(argv(cfg), input=text(msg), capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        notify.note(f"{who}: claude-tg notify timed out after {TIMEOUT}s")
        return
    except OSError as e:
        notify.note(f"{who}: claude-tg could not run ({e})")
        return
    if p.returncode:
        notify.note(f"{who}: claude-tg notify exit {p.returncode}: {(p.stderr or '').strip()[:300]}")
