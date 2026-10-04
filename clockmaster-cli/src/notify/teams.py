"""Teams channel mirror via m365-cli `channel-post`. Opt-in through
<data>/notify.yaml:

    teams_team: <team id>
    teams_channel: <channel id>
    m365_cli: <path to m365-cli.py>   # optional, default: the installed skill
    teams: off                        # optional kill switch

Subject = task, outcome, duration (a channel lists subjects only). Body = the
run's output in Teams' own `<codeblock class="Markdown">` (the only block the
client renders faithfully; newlines must be <br>), then a muted meta line.
"""
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import identity
import notify
import store

KEYS = {"teams", "teams_team", "teams_channel", "m365_cli"}
OUTPUT_CHARS = 20_000  # Graph rejects a body much past ~28 KB
TIMEOUT = 45           # --wait 30 for a 429, plus the round trip


def settings(cfg=None):
    cfg = notify.config() if cfg is None else cfg
    if not cfg or cfg.get("teams", "on") == "off":
        return None
    team, chan = cfg.get("teams_team", ""), cfg.get("teams_channel", "")
    if not team or not chan:
        return None
    cli = Path(cfg["m365_cli"]).expanduser() if cfg.get("m365_cli") \
        else identity.home() / ".claude" / "skills" / "m365-cli" / "m365-cli.py"
    return {"team": team, "channel": chan, "cli": cli}


def subject(msg):
    return f"{msg.title} — {notify.LABELS.get(msg.status, msg.status)} in {store.fmt_dur(msg.duration)}"


def body(msg):
    text = ""
    if msg.log_path:
        try:
            text = Path(msg.log_path).read_text(encoding="utf-8", errors="replace").strip("\n")
        except OSError:
            pass
    if text:
        if len(text) > OUTPUT_CHARS:
            text = f"… first {len(text) - OUTPUT_CHARS} chars omitted …\n" + text[-OUTPUT_CHARS:]
        out = '<codeblock class="Markdown"><code>' + "<br>".join(escape(x) for x in text.split("\n")) \
            + "</code></codeblock>"
    else:
        out = "(no output)"
    m = msg.meta
    tail = (f"exit {m.get('exitCode')} · trigger {escape(str(m.get('trigger', '?')))}"
            f" · run {escape(str(m.get('runId', '?')))}")
    return f"{out}<br><small><i>{tail}</i></small>"


def argv(cfg, msg):
    return [sys.executable, str(cfg["cli"]), "channel-post", cfg["team"], cfg["channel"], body(msg),
            "--subject", subject(msg), "--html", "--wait", "30", "--no-header"]


def send(msg):
    raw = notify.config()
    unknown = sorted(set(raw) - KEYS - set(getattr(notify, "EXTRA_KEYS", ())))
    if unknown:
        notify.note(f"notify.yaml: unknown keys {unknown} ignored")
    cfg = settings(raw)
    if not cfg:
        return
    who = f"{msg.title} {msg.run_id}"
    if not cfg["cli"].is_file():
        notify.note(f"{who}: no m365-cli at {cfg['cli']}")
        return
    try:
        p = subprocess.run(argv(cfg, msg), capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        notify.note(f"{who}: m365-cli timed out after {TIMEOUT}s")
        return
    except OSError as e:
        notify.note(f"{who}: m365-cli could not run ({e})")
        return
    if p.returncode:
        notify.note(f"{who}: m365-cli exit {p.returncode}: {(p.stderr or '').strip()[:300]}")
