"""Auto-triage: a `claude-tg notify --topic KEY` event also opens a new topic whose claude session investigates it.

Opt-in: config `notify_triage` (written only by `claude-tg triage on|off`, the rest of the config untouched) or
`notify --triage`. Never for --keep / --replace / --file (boards, digests, files), --thread / --main-chat targets, a
notify from inside a bot run ($CLAUDE_TG_RUN_TOPIC: no recursion), a leak-blocked text, `--no-triage`; without
--triage also not for a first line with ✅ (a recovery), keys outside `topics` (empty = all) or in `exclude`.

Dedupe: signature = chat + topic key + first line with numbers, hex ids and punctuation removed. Same signature within
`cooldown_minutes` of its topic's creation -> no new topic: count += 1, a silent "repeat #N" bot line in that topic at
N = 2, 4, 8, ... (a deleted topic -> a new one). State: STATE_DIR/triage.json under flock STATE_DIR/triage.lock.
The notification gets a URL button to the triage topic (editMessageReplyMarkup after the send).
Every failure here is a stderr warning: notify's output and exit code stay as without triage."""
import fcntl
import json
import os
import re
import socket
import sys
import time
from pathlib import Path

from . import config, ui
from .botapi import TgError

DEFAULTS = {"enabled": False, "cooldown_minutes": 360, "cwd": None, "chat": None, "topics": [], "exclude": []}
TITLE = 64
OK_MARK = "✅"
MARKS = re.compile("[❌⚠❗‼\U0001f525\U0001f494\U0001f6a8✅️]")
NOISE = re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,}\b|\d+", re.I)
GONE = ("message thread not found", "TOPIC_")

PROMPT = """A system event was just reported to the owner via `claude-tg notify`. Investigate it.

Event:
<<<
{text}
>>>
Source: notify topic `{key}`, host {host}, {at}{unit}{sender}.

1. Find the root cause: logs (`journalctl -u <unit>`, `--user` for user units), the unit / timer files, the script and \
the repo that own it (routing table in CLAUDE.md), recent changes.
2. Transient and already recovered (service healthy now): say so in 1-2 lines and stop.
3. Otherwise fix it when the fix is safe and in scope, following that repo's rules (its CLAUDE.md; git: worktree + \
branch + PR). Destructive, risky or needs a decision: don't, ask instead.
4. Final message, short: cause / what you fixed / what is left and who must act.
Answer in the language of the event text. Repeats of this event are counted in this topic, they are not new events."""


def settings(cfg: dict) -> dict:
    v = cfg.get("notify_triage")
    return dict(DEFAULTS, **(v if isinstance(v, dict) else {}))


def first_line(text: str) -> str:
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def signature(chat, key: str, text: str) -> str:
    line = re.sub(r"[\W_]+", " ", NOISE.sub(" ", MARKS.sub("", first_line(text)).casefold()))
    return f"{chat}:{key}:{' '.join(line.split())}"


def title(text: str) -> str:
    t = " ".join(MARKS.sub("", first_line(text)).replace(" — ", ": ").split()).strip(" :-")
    return "\U0001f50e " + (t if len(t) <= TITLE else t[:TITLE - 1].rstrip() + "…")


def skip(cfg: dict, a, topic, text: str, blocked=False, env=None):
    """Why this notify gets no triage (str), or None = triage it."""
    env = os.environ if env is None else env
    want = getattr(a, "triage", None)  # True --triage, False --no-triage, None config
    if want is False:
        return "--no-triage"
    if env.get(config.RUN_TOPIC_ENV):
        return "inside a bot run"
    if getattr(a, "keep", None) or getattr(a, "replace", None) or getattr(a, "file", None):
        return "--keep / --replace / --file"
    if not topic:
        return "not a --topic notification"
    if blocked:
        return "leak guard"
    if want:
        return None
    s = settings(cfg)
    if not s["enabled"]:
        return "off"
    if s["topics"] and topic not in s["topics"]:
        return f"topic {topic} not in notify_triage.topics"
    if topic in (s["exclude"] or []):
        return f"topic {topic} excluded"
    if OK_MARK in first_line(text):
        return "recovery (✅)"
    return None


def _file() -> Path:
    return config.STATE_DIR / "triage.json"


def _load() -> dict:
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict):
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, _file())


def origin(pid=None, ppid=None) -> dict:
    """Where the event came from: systemd unit of this process (cgroup) and the sending command (parent cmdline)."""
    out = {}
    try:
        cg = Path(f"/proc/{pid or 'self'}/cgroup").read_text().strip().splitlines()[-1].split("/")
        unit = next((c for c in reversed(cg) if c.endswith((".service", ".timer"))), "")
        if unit and not unit.startswith("user@"):
            out["unit"] = unit
    except (OSError, IndexError):
        pass
    try:
        cmd = Path(f"/proc/{ppid or os.getppid()}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        if cmd.strip():
            out["sender"] = cmd.strip()[:200]
    except OSError:
        pass
    return out


def prompt(key: str, text: str, now: float, src: dict) -> str:
    return PROMPT.format(text=text.strip(), key=key, host=socket.gethostname(),
                         at=time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(now)),
                         unit=f", unit {src['unit']}" if src.get("unit") else "",
                         sender=f", sent by `{src['sender']}`" if src.get("sender") else "")


def _repeat(bot, cfg, e: dict, text: str) -> bool:
    """Count a repeat; a silent line at 2, 4, 8, ... False = the topic is gone (open a new one)."""
    e["count"] = e.get("count", 1) + 1
    if e["count"] & (e["count"] - 1):
        return True
    try:
        bot.call("sendMessage", chat_id=e["chat"], message_thread_id=e["thread"], disable_notification=True,
                 text=ui.t(ui.lang(cfg), "triage_repeat", n=e["count"], event=first_line(text)[:200]),
                 link_preview_options={"is_disabled": True})
    except TgError as err:
        if any(g in err.description for g in GONE):
            return False
        print(f"claude-tg notify: triage repeat line not sent ({err.description})", file=sys.stderr)
    return True


def open_topic(bot, cfg: dict, key: str, text: str, r: dict, now=None, src=None) -> dict:
    """New triage topic for this event, or the repeat count of the open one. -> {thread, link, new, count}."""
    from . import inbox  # inbox imports notify, notify imports this module
    s, now = settings(cfg), time.time() if now is None else now
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.STATE_DIR / "triage.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cut = now - float(s["cooldown_minutes"] or 0) * 60
        events = {k: v for k, v in (_load().get("events") or {}).items() if v.get("at", 0) >= cut}
        sig = signature(r["chat"], key, text)
        e = events.get(sig)
        if e and _repeat(bot, cfg, e, text):
            out = {"thread": e["thread"], "link": e["link"], "new": False, "count": e["count"]}
        else:
            chat = config.chat_ref(cfg, s["chat"]) if s["chat"] else r["chat"]
            sp = inbox.spawn(bot, cfg, title(text), s["cwd"], prompt(key, text, now, src or origin()), silent=True,
                             show=ui.t(ui.lang(cfg), "triage_show", event=first_line(text)[:300]), chat=chat)
            e = {"thread": sp["thread"], "chat": sp.get("chat", chat), "link": sp["link"], "at": now, "count": 1}
            out = {"thread": e["thread"], "link": e["link"], "new": True, "count": 1}
        events[sig] = e
        _save({"events": events})
    return out


def button(bot, cfg: dict, r: dict, link: str, buttons=None):
    """Add the triage button under the notification's last message (its own --button rows kept)."""
    from .notify import keyboard
    if not (link and r.get("message_ids")):
        return
    rows = (keyboard(buttons) or {}).get("inline_keyboard", [])
    rows.append([{"text": ui.t(ui.lang(cfg), "triage_button"), "url": link}])
    bot.call("editMessageReplyMarkup", _retries=1, chat_id=r["chat"], message_id=r["message_ids"][-1],
             reply_markup={"inline_keyboard": rows})


def after_notify(bot, cfg: dict, a, topic, text: str, r: dict, blocked=False, env=None):
    """Called by notify after a successful send. Returns the triage result or None; never raises."""
    why = skip(cfg, a, topic, text, blocked, env)
    if why:
        if getattr(a, "triage", None):
            print(f"claude-tg notify: no triage ({why})", file=sys.stderr)
        return None
    try:
        out = open_topic(bot, cfg, topic, text, r)
    except Exception as e:  # noqa: BLE001 - triage must never break notify
        print(f"claude-tg notify: triage failed ({e})", file=sys.stderr)
        return None
    try:
        button(bot, cfg, r, out["link"], getattr(a, "button", None))
    except Exception as e:  # noqa: BLE001
        print(f"claude-tg notify: triage button not added ({e})", file=sys.stderr)
    return out


# `claude-tg triage show | on | off`

def main(cfg: dict, a) -> int:
    from .groups import GroupError, raw_config, write_key
    try:
        cur = raw_config().get("notify_triage")
        cur = dict(cur) if isinstance(cur, dict) else {}
        if a.action in ("on", "off"):
            cur["enabled"] = a.action == "on"
            if getattr(a, "cwd", None):
                p = Path(os.path.expanduser(a.cwd)).resolve()
                if not p.is_dir():
                    raise GroupError(f"cwd is not a directory: {p}")
                cur["cwd"] = str(p)
            if getattr(a, "chat", None):
                if a.chat in ("home", "none"):
                    cur.pop("chat", None)
                else:
                    config.chat_ref(cfg, a.chat)
                    cur["chat"] = a.chat
            if getattr(a, "cooldown", None) is not None:
                cur["cooldown_minutes"] = max(0, a.cooldown)
            for flag, k, empty in (("topics", "topics", "all"), ("exclude", "exclude", "none")):
                v = getattr(a, flag, None)
                if v is not None:
                    cur[k] = [] if v == [empty] else v
            write_key("notify_triage", cur)
        s = settings(dict(cfg, notify_triage=cur))
        live = [v for v in (_load().get("events") or {}).values()
                if v.get("at", 0) >= time.time() - float(s["cooldown_minutes"] or 0) * 60]
        print(json.dumps(dict(s, open_topics=len(live)), ensure_ascii=False))
        if a.action != "show":
            print("# applies to the next notify; no restart needed", file=sys.stderr)
        return 0
    except (GroupError, ValueError, OSError) as e:
        print(f"claude-tg triage: {e}", file=sys.stderr)
        return 2
