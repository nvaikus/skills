"""Scripts -> running bot: `claude-tg spawn | send | alive | topic-icon`.

The bot owns state.json, so a script never writes it. A prompt for a topic is posted into the topic as a bot
message (the owner sees what was asked, or a short `--show` line standing in for it), then queued as a file in STATE_DIR/inbox/; the bot's inbox thread
(`Bridge.drain_inbox`, every second) turns each file into an owner message of that topic: same queue, same
resume, same mid-run stdin injection. Files wait while the bot is down. Topic settings (cwd, title, base icon,
appended system prompt, quiet flag) travel in the same file and are applied by the bot before the prompt runs.

Liveness (`alive`): a claude process whose env carries CLAUDE_TG_RUN_TOPIC=<thread> (+ CLAUDE_TG_RUN_CHAT=<chat>;
/proc, Linux), a pending request of that topic in state.json, or a queued inbox file for it.

Target chat: the home chat, or an owner group (config owner_groups) given by `--chat NAME|ID` or implied by a
`t.me/c/<chat>/<thread>` link. Topics are keyed by config.topic_key (thread ids collide across chats)."""
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

from . import config
from .botapi import Skipped, TgError
from .notify import NotifyError, bot_username, cli_bot, icon_id, owner_chat, with_mentions

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


def pending_files(key=None, cfg=None) -> list:
    """Queued inbox files, oldest first; `key` (config.topic_key) = only that topic's."""
    out = []
    for p in sorted(inbox_dir().glob("*.json")) if inbox_dir().is_dir() else []:
        try:
            item = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if key is None or _item_key(cfg or {}, item) == str(key):
            out.append((p, item))
    return out


def post(bot, chat, thread, prompt, silent=False, show=None, cfg=None, mention=None) -> dict:
    """The prompt as a visible bot message in the topic (or `show`, a short human line standing in for it:
    claude still gets the full prompt); its id becomes the request key in the bot. `mention`: ["ID=Name"] put at
    `{who}` of the posted line (notify.with_mentions)."""
    text = (show or prompt).strip()
    text = text if len(text) <= POSTED else text[:POSTED] + "…"
    text, mode = with_mentions(bot, cfg or {}, text, "plain", mention)
    m = bot.call("sendMessage", chat_id=chat, message_thread_id=thread, text=text,
                 parse_mode="HTML" if mode == "html" else None,
                 disable_notification=silent or None, link_preview_options={"is_disabled": True})
    return {"message_id": m["message_id"], "chat": {"id": chat, "type": "private" if chat > 0 else "supergroup"},
            "from": {"id": chat},
            "message_thread_id": thread, "date": int(time.time()), "text": prompt}


LAST_MSG = 2147483647  # int32 max: a message that doesn't exist -> Telegram opens the topic at its last message
LINK_RE = re.compile(r"^(?:https?://)?t\.me/(?:c/\d+|[^/\s]+)/(\d+)(?:/\d+)?/?$")


def topic_link(name, thread, group=None) -> str:
    """Link that opens the topic at its last message (`/<thread>` alone opens only the creation message
    in the main chat view, `/<thread>/<thread>` the topic's first message). Group mode: `t.me/c/<internal id>`
    (the chat id without its -100 prefix; members only)."""
    if group is not None:
        g = str(group)
        return f"https://t.me/c/{g[4:] if g.startswith('-100') else g.lstrip('-')}/{thread}/{LAST_MSG}"
    return f"https://t.me/{name}/{thread}/{LAST_MSG}" if name else ""


def _item_key(cfg, item):
    try:
        return config.topic_key(cfg, item.get("chat"), item.get("thread"))
    except (TypeError, ValueError):
        return None


def link(bot, thread, cfg=None, chat=None) -> str:
    """Topic link: home chat as before (bot link; group mode `t.me/c/<group>`), an owner group `t.me/c/<chat>`."""
    group = config.group_id(cfg or {})
    if chat is not None and not config.home(cfg or {}, chat):
        return topic_link(None, thread, chat)
    return topic_link(None if group is not None else bot_username(bot), thread, group)


def thread_of(ref) -> int:
    """Topic id from an id or a topic link: `t.me/<bot>/<thread>[/<msg>]`, `t.me/c/<chat>/<thread>[/<msg>]`."""
    return ref_of(ref)[1]


def ref_of(ref) -> tuple:
    """(chat or None, thread) from an id or a topic link; a `t.me/c/<internal id>/...` link gives chat -100<id>."""
    s = str(ref).strip()
    m = LINK_RE.match(s) or re.fullmatch(r"(\d+)", s)
    if not m:
        raise NotifyError(f"not a topic id or link: {ref!r}")
    c = re.match(r"^(?:https?://)?t\.me/c/(\d+)/", s)
    return (int("-100" + c.group(1)) if c else None), int(m.group(1))


def target_chat(cfg, chat_arg=None, ref=None) -> int:
    """Chat id for a CLI call: --chat NAME|ID, else the chat of a `t.me/c/` link, else the home chat (owner_chat).
    Both given and different -> error; an unknown chat -> error."""
    try:
        want = config.chat_ref(cfg, chat_arg)
        linked = ref_of(ref)[0] if ref is not None else None
        linked = config.chat_ref(cfg, linked) if linked is not None else None
    except ValueError as e:
        raise NotifyError(str(e))
    if chat_arg not in (None, "") and ref is not None and ref_of(ref)[0] is not None and want != linked:
        raise NotifyError(f"--chat {chat_arg} does not match the link's chat {ref_of(ref)[0]}")
    chat = want if chat_arg not in (None, "") else linked
    return owner_chat(cfg) if chat is None else chat


def read_system(arg):
    if not arg:
        return None
    if arg.startswith("@"):
        return Path(arg[1:]).expanduser().read_text().strip()
    return arg.strip()


def spawn(bot, cfg, title, cwd, prompt, icon=None, system=None, silent=False, show=None, quiet=False,
          mention=None, chat=None, start_icon=None) -> dict:
    """`icon` = the topic's base icon (stored, `topic-icon base` restores it); `start_icon` = the icon the topic is
    created with instead, not stored (e.g. a ❗ mark set in createForumTopic: no separate, skippable editForumTopic)."""
    path = Path(os.path.expanduser(cwd or cfg["default_cwd"])).resolve()
    if not path.is_dir():
        raise NotifyError(f"cwd is not a directory: {path}")
    chat = chat if chat is not None else owner_chat(cfg)
    extra = {}
    cid = icon_id(bot, icon) if icon else None
    shown = (icon_id(bot, start_icon) if start_icon else None) or cid
    if shown:
        extra["icon_custom_emoji_id"] = shown
    thread = bot.call("createForumTopic", chat_id=chat, name=title.strip()[:128], **extra)["message_thread_id"]
    topic = {"cwd": str(path), "title": title.strip()[:128], "implicit": False}
    if cid:
        topic["icon"] = cid
    if system:
        topic["system"] = system
    if quiet:
        topic["quiet"] = True
    msg = post(bot, chat, thread, prompt, silent, show, cfg, mention)
    enqueue({"op": "prompt", "thread": thread, "chat": chat, "msg": msg, "topic": topic})
    out = {"thread": thread, "link": link(bot, thread, cfg, chat), "message_id": msg["message_id"], "cwd": str(path)}
    if shown:
        out["icon"] = shown
    return out if config.home(cfg, chat) else dict(out, chat=chat)


def send(bot, cfg, thread, prompt, silent=False, show=None, quiet=False, chat=None) -> dict:
    chat = chat if chat is not None else owner_chat(cfg)
    msg = post(bot, chat, thread, prompt, silent, show)
    item = {"op": "prompt", "thread": thread, "chat": chat, "msg": msg}
    if quiet:
        item["topic"] = {"quiet": True}
    enqueue(item)
    return {"thread": thread, "message_id": msg["message_id"]}


def _proc_topics(proc=Path("/proc"), cfg=None) -> dict:
    """topic key -> [pid] of processes started by the bot for that topic (env CLAUDE_TG_RUN_TOPIC + _RUN_CHAT;
    no chat = a run of an older bot: home chat)."""
    out = {}
    if not proc.is_dir():
        return out
    topic, chat = (config.RUN_TOPIC_ENV + "=").encode(), (config.RUN_CHAT_ENV + "=").encode()
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            env = (d / "environ").read_bytes()
        except OSError:
            continue
        t = c = None
        for kv in env.split(b"\0"):
            if kv.startswith(topic):
                t = kv[len(topic):].decode(errors="ignore")
            elif kv.startswith(chat):
                c = kv[len(chat):].decode(errors="ignore")
        if t and t.isdigit():
            c = int(c) if c and c.lstrip("-").isdigit() else None
            out.setdefault(config.topic_key(cfg or {}, c, t), []).append(int(d.name))
    return out


def alive(thread, proc=Path("/proc"), chat=None, cfg=None) -> dict:
    cfg = cfg or {}
    key = config.topic_key(cfg, chat, thread)
    try:
        state = json.loads((config.STATE_DIR / "state.json").read_text())
    except (OSError, ValueError):
        state = {}
    pend = [k for k, e in (state.get("pending") or {}).items() if str(e.get("topic", e.get("thread"))) == key]
    pids = _proc_topics(proc, cfg).get(key, [])
    queued = len(pending_files(key, cfg))
    out = {"thread": thread, "live": bool(pids or pend or queued), "pids": pids, "pending": len(pend),
           "inbox": queued, "known": key in (state.get("topics") or {})}
    return out if config.home(cfg, chat) else dict(out, chat=chat)


def topic_icon(bot, cfg, thread, arg, chat=None) -> dict:
    """emoji | off | base (the icon set by /icon or spawn --icon, kept in state.json; none = off)."""
    chat = chat if chat is not None else owner_chat(cfg)
    a = (arg or "").strip()
    if a.lower() == "base":
        try:
            t = json.loads((config.STATE_DIR / "state.json").read_text())["topics"].get(
                config.topic_key(cfg, chat, thread)) or {}
        except (OSError, ValueError, KeyError):
            t = {}
        cid = t.get("icon") or ""
    elif a.lower() in ("off", "none", "-"):
        cid = ""
    else:
        cid = icon_id(bot, a)
        if not cid:
            raise NotifyError(f"{a} is not a topic icon (getForumTopicIconStickers)")
    try:  # cosmetic: skipped (not waited) while the chat is in a flood wait or over its budget
        bot.call("editForumTopic", _retries=0, chat_id=chat, message_thread_id=thread, icon_custom_emoji_id=cid)
    except Skipped as e:
        print(f"claude-tg topic-icon: not set, {e.description}", file=sys.stderr)
        return {"thread": thread, "icon": cid or None, "skipped": True}
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
        ref = getattr(a, "thread", None)
        chat_arg = getattr(a, "chat", None)
        if a.cmd == "alive":
            chat = None if chat_arg in (None, "") and ref_of(ref)[0] is None else target_chat(cfg, chat_arg, ref)
            r = alive(thread_of(ref), chat=chat, cfg=cfg)
            print(json.dumps(r))
            return 0 if r["live"] else 1
        chat = target_chat(cfg, chat_arg, ref)
        bot = cli_bot(cfg)
        if a.cmd == "spawn":
            r = spawn(bot, cfg, a.title, a.cwd, _text(a), a.icon, read_system(a.system), a.silent, a.show, a.quiet,
                      getattr(a, "mention", None), chat, getattr(a, "start_icon", None))
        elif a.cmd == "send":
            r = send(bot, cfg, thread_of(ref), _text(a), a.silent, a.show, a.quiet, chat)
        else:
            r = topic_icon(bot, cfg, thread_of(ref), a.icon, chat)
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
        key = bridge.key(chat, thread)
        cur = bridge.store.topic(key)
        if topic.get("cwd") and topic["cwd"] != cur["cwd"]:
            topic = dict(topic, session_id=None)  # sessions are per cwd
        bridge.store.update(key, **topic)
    msg["_rx"] = time.time()
    bridge.worker(chat, thread).put([msg])
    return thread
