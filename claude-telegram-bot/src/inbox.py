"""Scripts -> running bot: `claude-tg spawn | send | alive | topic-icon`.

The bot owns state.json, so a script never writes it. A prompt for a topic is posted into the topic as a bot
message (the owner sees what was asked), then queued as a file in STATE_DIR/inbox/; the bot's inbox thread
(`Bridge.drain_inbox`, every second) turns each file into an owner message of that topic: same queue, same
resume, same mid-run stdin injection. Files wait while the bot is down. Topic settings (cwd, title, base icon,
appended system prompt) travel in the same file and are applied by the bot before the prompt runs.

Liveness (`alive`): a claude process whose env carries CLAUDE_TG_RUN_TOPIC=<thread> (/proc, Linux), a pending
request of that topic in state.json, or a queued inbox file for it."""
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

from . import config
from .botapi import Bot, TgError
from .notify import NotifyError, icon_id, owner_chat

POSTED = 3900  # visible copy of a prompt; the full text travels in the inbox file


def inbox_dir() -> Path:
    return config.STATE_DIR / "inbox"


def enqueue(item: dict) -> Path:
    d = inbox_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
    tmp = d / (name + ".tmp")
    tmp.write_text(json.dumps(item, ensure_ascii=False))
    path = d / (name + ".json")
    os.replace(tmp, path)
    return path


def pending_files(thread=None) -> list:
    out = []
    for p in sorted(inbox_dir().glob("*.json")) if inbox_dir().is_dir() else []:
        try:
            item = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if thread is None or item.get("thread") == thread:
            out.append((p, item))
    return out


def post(bot, chat, thread, prompt, silent=False) -> dict:
    """The prompt as a visible bot message in the topic; its id becomes the request key in the bot."""
    text = prompt if len(prompt) <= POSTED else prompt[:POSTED] + "…"
    m = bot.call("sendMessage", chat_id=chat, message_thread_id=thread, text=text,
                 disable_notification=silent or None, link_preview_options={"is_disabled": True})
    return {"message_id": m["message_id"], "chat": {"id": chat, "type": "private"}, "from": {"id": chat},
            "message_thread_id": thread, "date": int(time.time()), "text": prompt}


def link(bot, thread) -> str:
    try:
        name = bot.call("getMe").get("username")
    except TgError:
        name = None
    return f"https://t.me/{name}/{thread}" if name else ""


def thread_of(ref) -> int:
    """Topic id from an id or a link ending in /<id>."""
    m = re.search(r"(\d+)/?$", str(ref).strip())
    if not m:
        raise NotifyError(f"not a topic id or link: {ref!r}")
    return int(m.group(1))


def read_system(arg):
    if not arg:
        return None
    if arg.startswith("@"):
        return Path(arg[1:]).expanduser().read_text().strip()
    return arg.strip()


def spawn(bot, cfg, title, cwd, prompt, icon=None, system=None, silent=False) -> dict:
    path = Path(os.path.expanduser(cwd or cfg["default_cwd"])).resolve()
    if not path.is_dir():
        raise NotifyError(f"cwd is not a directory: {path}")
    chat = owner_chat(cfg)
    extra = {}
    cid = icon_id(bot, icon) if icon else None
    if cid:
        extra["icon_custom_emoji_id"] = cid
    thread = bot.call("createForumTopic", chat_id=chat, name=title.strip()[:128], **extra)["message_thread_id"]
    topic = {"cwd": str(path), "title": title.strip()[:128], "implicit": False}
    if cid:
        topic["icon"] = cid
    if system:
        topic["system"] = system
    msg = post(bot, chat, thread, prompt, silent)
    enqueue({"op": "prompt", "thread": thread, "chat": chat, "msg": msg, "topic": topic})
    return {"thread": thread, "link": link(bot, thread), "message_id": msg["message_id"], "cwd": str(path)}


def send(bot, cfg, thread, prompt, silent=False) -> dict:
    chat = owner_chat(cfg)
    msg = post(bot, chat, thread, prompt, silent)
    enqueue({"op": "prompt", "thread": thread, "chat": chat, "msg": msg})
    return {"thread": thread, "message_id": msg["message_id"]}


def _proc_topics(proc=Path("/proc")) -> dict:
    """thread -> [pid] of processes started by the bot for that topic (env CLAUDE_TG_RUN_TOPIC)."""
    out = {}
    if not proc.is_dir():
        return out
    key = (config.RUN_TOPIC_ENV + "=").encode()
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            env = (d / "environ").read_bytes()
        except OSError:
            continue
        for kv in env.split(b"\0"):
            if kv.startswith(key):
                v = kv[len(key):].decode(errors="ignore")
                if v.isdigit():
                    out.setdefault(int(v), []).append(int(d.name))
                break
    return out


def alive(thread, proc=Path("/proc")) -> dict:
    try:
        state = json.loads((config.STATE_DIR / "state.json").read_text())
    except (OSError, ValueError):
        state = {}
    pend = [k for k, e in (state.get("pending") or {}).items() if e.get("thread") == thread]
    pids = _proc_topics(proc).get(thread, [])
    queued = len(pending_files(thread))
    return {"thread": thread, "live": bool(pids or pend or queued), "pids": pids, "pending": len(pend),
            "inbox": queued, "known": str(thread) in (state.get("topics") or {})}


def topic_icon(bot, cfg, thread, arg) -> dict:
    """emoji | off | base (the icon set by /icon or spawn --icon, kept in state.json; none = off)."""
    chat = owner_chat(cfg)
    a = (arg or "").strip()
    if a.lower() == "base":
        try:
            t = json.loads((config.STATE_DIR / "state.json").read_text())["topics"].get(str(thread)) or {}
        except (OSError, ValueError, KeyError):
            t = {}
        cid = t.get("icon") or ""
    elif a.lower() in ("off", "none", "-"):
        cid = ""
    else:
        cid = icon_id(bot, a)
        if not cid:
            raise NotifyError(f"{a} is not a topic icon (getForumTopicIconStickers)")
    try:
        bot.call("editForumTopic", chat_id=chat, message_thread_id=thread, icon_custom_emoji_id=cid)
    except TgError as e:
        if "NOT_MODIFIED" not in (e.description or "").upper():
            raise
    return {"thread": thread, "icon": cid or None}


def _text(a) -> str:
    text = " ".join(a.prompt) if a.prompt else sys.stdin.read()
    if not text.strip():
        raise NotifyError("empty prompt (args or stdin)")
    return text.strip()


def main(cfg: dict, a) -> int:
    name = f"claude-tg {a.cmd}"
    try:
        if a.cmd == "alive":
            r = alive(thread_of(a.thread))
            print(json.dumps(r))
            return 0 if r["live"] else 1
        bot = Bot(config.read_token(cfg))
        if a.cmd == "spawn":
            r = spawn(bot, cfg, a.title, a.cwd, _text(a), a.icon, read_system(a.system), a.silent)
        elif a.cmd == "send":
            r = send(bot, cfg, thread_of(a.thread), _text(a), a.silent)
        else:
            r = topic_icon(bot, cfg, thread_of(a.thread), a.icon)
    except (NotifyError, OSError) as e:
        print(f"{name}: {e}", file=sys.stderr)
        return 2
    except TgError as e:
        print(f"{name}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(r, ensure_ascii=False))
    return 0


def apply(bridge, item: dict):
    """Bot side: one inbox file -> topic settings + an owner message of that topic."""
    if item.get("op") != "prompt":
        raise ValueError(f"unknown op {item.get('op')!r}")
    thread, chat, msg = int(item["thread"]), int(item["chat"]), item["msg"]
    topic = item.get("topic") or {}
    if topic:
        cur = bridge.store.topic(thread)
        if topic.get("cwd") and topic["cwd"] != cur["cwd"]:
            topic = dict(topic, session_id=None)  # sessions are per cwd
        bridge.store.update(thread, **topic)
    msg["_rx"] = time.time()
    bridge.worker(chat, thread).put([msg])
    return thread
