"""`claude-tg notify`: one-way message from the bot to the owner, for scripts and scheduled jobs.

Runs without the service (plain sendMessage never conflicts with its getUpdates poll). Default target is a
dedicated topic ("Notifications"), created on first use and remembered in STATE_DIR/notify.json - a separate
file, so the running bot never races us on state.json. The bot treats that topic like any other: a reply there
starts a claude session, and the quoted notification reaches the prompt (bridge.Worker.prompt)."""
import json
import os
import sys
from pathlib import Path

from . import config, fmt, guard, ui
from .botapi import Bot, TgError

DEFAULT_TOPIC = "Notifications"
GONE = ("message thread not found", "TOPIC_")


class NotifyError(Exception):
    pass


def owner_chat(cfg: dict) -> int:
    """Private chat id == the owner's user id: pinned in config, else learned by the bot (state.json)."""
    if cfg.get("owner_id"):
        return int(cfg["owner_id"])
    state = config.STATE_DIR / "state.json"
    try:
        owner = json.loads(state.read_text()).get("owner_id")
    except (OSError, ValueError):
        owner = None
    if not owner:
        raise NotifyError("owner unknown: write to the bot once, or set owner_id in " + str(config.CONFIG_FILE))
    return int(owner)


def _topics_file() -> Path:
    return config.STATE_DIR / "notify.json"


def _load() -> dict:
    try:
        return json.loads(_topics_file().read_text())
    except (OSError, ValueError):
        return {}


def _save(data: dict):
    p = _topics_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def topic_id(bot, chat: int, name: str, fresh=False):
    """Remembered thread id of topic `name`, created when missing (or `fresh`). None = topics unavailable."""
    data = _load()
    topics = data.setdefault("topics", {})
    if not fresh and topics.get(name):
        return topics[name]
    try:
        thread = bot.call("createForumTopic", chat_id=chat, name=name)["message_thread_id"]
    except TgError as e:
        print(f"claude-tg notify: no topic ({e.description}); sending to the main chat", file=sys.stderr)
        return None
    topics[name] = thread
    _save(data)
    return thread


def chunks(text: str, mode: str) -> list:
    """[(text, parse_mode)] within Telegram's limit. mode: plain | html | md."""
    if mode == "html":
        if len(text) > fmt.LIMIT:
            raise NotifyError(f"html text is {len(text)} chars; Telegram allows {fmt.LIMIT}")
        return [(text, "HTML")]
    if mode == "md":
        return [(fmt.md_to_html(c), "HTML") for c in fmt.split_md(text)]
    return [(text[i:i + fmt.LIMIT], None) for i in range(0, len(text), fmt.LIMIT)] or [("", None)]


def keyboard(buttons) -> dict:
    """["Text=https://url", ...] -> inline keyboard, one button per row."""
    rows = []
    for b in buttons or []:
        label, sep, url = b.partition("=")
        if not (sep and label.strip() and url.strip().startswith(("https://", "http://", "tg://"))):
            raise NotifyError(f"--button wants TEXT=URL, got {b!r}")
        rows.append([{"text": label.strip(), "url": url.strip()}])
    return {"inline_keyboard": rows} if rows else None


def send(bot, cfg: dict, text: str, mode="plain", silent=False, topic=DEFAULT_TOPIC, buttons=None) -> dict:
    text = text.strip()
    if not text:
        raise NotifyError("empty text")
    chat = owner_chat(cfg)
    markup = keyboard(buttons)
    thread = topic_id(bot, chat, topic) if topic else None
    sent = []
    parts = chunks(text, mode)
    for i, (body, parse) in enumerate(parts):
        p = {"chat_id": chat, "text": body, "parse_mode": parse, "disable_notification": silent or None,
             "link_preview_options": {"is_disabled": True}}
        if markup and i == len(parts) - 1:
            p["reply_markup"] = markup
        try:
            sent.append(bot.call("sendMessage", message_thread_id=thread, **p))
        except TgError as e:
            if not (thread and any(g in e.description for g in GONE)):
                raise
            thread = topic_id(bot, chat, topic, fresh=True)  # topic deleted in the client: recreate once
            sent.append(bot.call("sendMessage", message_thread_id=thread, **p))
    return {"chat": chat, "thread": thread, "message_ids": [m.get("message_id") for m in sent]}


def main(cfg: dict, a) -> int:
    text = " ".join(a.text) if a.text else sys.stdin.read()
    mode = "html" if a.html else "md" if a.markdown else "plain"
    g = guard.from_config(cfg)
    src = g and g.match(text, is_html=mode == "html")
    if src:  # quotes a protected file (config protected_paths): the owner gets the notice instead
        print(f"claude-tg notify: blocked, quotes protected {src}", file=sys.stderr)
        text, mode = ui.t(ui.lang(cfg), "leak"), "plain"
    try:
        token = config.read_token(cfg)
        r = send(Bot(token), cfg, text, mode, a.silent, None if a.main_chat else a.topic, a.button)
    except NotifyError as e:
        print(f"claude-tg notify: {e}", file=sys.stderr)
        return 2
    except TgError as e:
        print(f"claude-tg notify: {e}", file=sys.stderr)
        return 1
    print(json.dumps(r))
    return 0
