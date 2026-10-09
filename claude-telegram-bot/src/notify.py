"""`claude-tg notify`: one-way message from the bot to the owner, for scripts and scheduled jobs.

Runs without the service (plain sendMessage never conflicts with its getUpdates poll). Default target is a
dedicated topic ("Notifications"), created on first use and remembered in STATE_DIR/notify.json - a separate
file, so the running bot never races us on state.json. The bot treats that topic like any other: a reply there
starts a claude session, and the quoted notification reaches the prompt (bridge.Worker.prompt).

Topic registry (config `notify_topics`): short key -> display name (+ optional icon). The cache is keyed by the key,
so a new display name / icon in config edits the existing topic (editForumTopic) instead of creating another one.
An unknown --topic is a literal name (key == name), as before.

Target order: --thread ID > --main-chat > --topic KEY > $CLAUDE_TG_RUN_TOPIC (a bot-spawned claude: its own topic)
> "Notifications". Files (--file): video -> sendVideo (streams inline), image -> sendPhoto, else / on error ->
sendDocument; text becomes the caption when it fits, else a message before the files.

--replace KEY: after a successful send, the messages stored under KEY (notify.json "replace") are deleted and the
new ids take their place - send first, so a failed send never leaves the topic empty. A refused delete (400: too
old, already gone) is a warning and is forgotten; a transient one (network, 5xx) keeps its id under KEY for the
next try. `notify-delete KEY` deletes and forgets without sending."""
import json
import os
import sys
from pathlib import Path

from . import config, fmt, guard, ui
from .botapi import Bot, TgError

DEFAULT_TOPIC = "Notifications"
GONE = ("message thread not found", "TOPIC_")
MAX_FILE = 50 * 1024 * 1024  # Bot API upload limit
MAX_PHOTO = 10 * 1024 * 1024  # sendPhoto limit; bigger images go as documents
CAPTION = 1024
VIDEO = {".mp4", ".mov", ".m4v"}
PHOTO = {".jpg", ".jpeg", ".png", ".webp"}


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


def spec(cfg: dict, key: str) -> dict:
    """Registry entry for `key`: {"name", "icon"}. Value in config: "Name" or {"name": .., "icon": ..};
    icon = an emoji from getForumTopicIconStickers or a custom_emoji_id. Unknown key = literal name, no icon."""
    v = (cfg.get("notify_topics") or {}).get(key)
    if isinstance(v, str):
        v = {"name": v}
    v = v or {}
    return {"name": v.get("name") or key, "icon": v.get("icon") or None}


def icon_id(bot, icon):
    """custom_emoji_id for an icon given as emoji or id; None (with a warning) when unknown."""
    if not icon:
        return None
    if str(icon).isdigit():
        return str(icon)
    try:
        for s in bot.call("getForumTopicIconStickers"):
            if s.get("emoji", "").rstrip("\ufe0f") == str(icon).rstrip("\ufe0f"):
                return s["custom_emoji_id"]
    except TgError as e:
        print(f"claude-tg notify: no topic icons ({e.description})", file=sys.stderr)
        return None
    print(f"claude-tg notify: icon {icon} is not a topic icon (getForumTopicIconStickers); none set", file=sys.stderr)
    return None


def _icon_args(bot, icon) -> dict:
    cid = icon_id(bot, icon)
    return {"icon_custom_emoji_id": cid} if cid else {}


def topic_id(bot, chat: int, key: str, fresh=False, cfg=None):
    """Remembered thread id of topic `key`, created when missing (or `fresh`), renamed when its registry entry
    changed. None = topics unavailable."""
    want = spec(cfg or {}, key)
    data = _load()
    topics = data.setdefault("topics", {})
    meta = data.setdefault("meta", {})
    if not fresh and topics.get(key):
        have = meta.get(key) or {"name": key, "icon": None}  # pre-registry entries were created as their key
        if have != want:
            try:
                bot.call("editForumTopic", chat_id=chat, message_thread_id=topics[key], name=want["name"],
                         **_icon_args(bot, want["icon"]))
                meta[key] = want
                _save(data)
            except TgError as e:  # cosmetic: keep sending to the old-named topic
                if "TOPIC_NOT_MODIFIED" in e.description:  # already looks like that
                    meta[key] = want
                    _save(data)
                else:
                    print(f"claude-tg notify: rename failed ({e.description})", file=sys.stderr)
        return topics[key]
    try:
        thread = bot.call("createForumTopic", chat_id=chat, name=want["name"],
                          **_icon_args(bot, want["icon"]))["message_thread_id"]
    except TgError as e:
        print(f"claude-tg notify: no topic ({e.description}); sending to the main chat", file=sys.stderr)
        return None
    topics[key] = thread
    meta[key] = want
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


def target(a, env=None):
    """(topic key, thread id) from the CLI args; at most one is set, (None, None) = All messages."""
    if a.thread:
        return None, a.thread
    if a.main_chat:
        return None, None
    if a.topic:
        return a.topic, None
    run = (os.environ if env is None else env).get(config.RUN_TOPIC_ENV, "")
    if run.isdigit() and int(run):
        return None, int(run)
    return DEFAULT_TOPIC, None


class _Dest:
    """Owner chat + thread; a cached topic deleted in the client is recreated once. An explicit thread is not."""

    def __init__(self, bot, cfg, topic, thread):
        self.bot, self.cfg, self.topic = bot, cfg, topic
        self.chat = owner_chat(cfg)
        self.thread = thread or (topic_id(bot, self.chat, topic, cfg=cfg) if topic else None)

    def do(self, fn):
        try:
            return fn(self.thread)
        except TgError as e:
            if not (self.topic and self.thread and any(g in e.description for g in GONE)):
                raise
            self.thread = topic_id(self.bot, self.chat, self.topic, fresh=True, cfg=self.cfg)
            return fn(self.thread)

    def result(self, sent, **extra):
        return dict({"chat": self.chat, "thread": self.thread, "message_ids": [m.get("message_id") for m in sent]},
                    **extra)


def _messages(bot, dest, parts, silent, markup):
    sent = []
    for i, (body, parse) in enumerate(parts):
        p = {"chat_id": dest.chat, "text": body, "parse_mode": parse, "disable_notification": silent or None,
             "link_preview_options": {"is_disabled": True}}
        if markup and i == len(parts) - 1:
            p["reply_markup"] = markup
        sent.append(dest.do(lambda th: bot.call("sendMessage", message_thread_id=th, **p)))
    return sent


def send(bot, cfg: dict, text: str, mode="plain", silent=False, topic=DEFAULT_TOPIC, buttons=None, thread=None) -> dict:
    text = text.strip()
    if not text:
        raise NotifyError("empty text")
    markup = keyboard(buttons)
    dest = _Dest(bot, cfg, topic, thread)
    return dest.result(_messages(bot, dest, chunks(text, mode), silent, markup))


def check_files(paths) -> list:
    """Existing regular files within the Bot API limit, else NotifyError before anything is sent."""
    out = []
    for p in paths:
        f = Path(p).expanduser()
        if not f.is_file():
            raise NotifyError(f"no such file: {p}")
        size = f.stat().st_size
        if size > MAX_FILE:
            raise NotifyError(f"{p} is {size / 2**20:.1f} MB; the Bot API uploads at most 50 MB "
                              "(compress it, e.g. ffmpeg -crf 28, or split it)")
        out.append(f)
    return out


def method_for(f: Path):
    """(Bot API method, multipart field, extra params) by extension."""
    ext = f.suffix.lower()
    if ext in VIDEO:
        return "sendVideo", "video", {"supports_streaming": True}
    if ext in PHOTO and f.stat().st_size <= MAX_PHOTO:
        return "sendPhoto", "photo", {}
    return "sendDocument", "document", {}


def send_files(bot, cfg: dict, paths, text="", mode="plain", silent=False, topic=DEFAULT_TOPIC, buttons=None,
               thread=None, guard=None) -> dict:
    """Upload files; text = caption of the first file when it fits in one caption, else messages before them.
    Files the leak guard rejects are replaced by a notice (listed under "blocked")."""
    files = check_files(paths)
    markup = keyboard(buttons)
    dest = _Dest(bot, cfg, topic, thread)
    sent, blocked = [], []
    parts = chunks(text.strip(), mode) if text.strip() else []
    caption = parts[0] if len(parts) == 1 and len(parts[0][0]) <= CAPTION else None
    if parts and not caption:
        sent += _messages(bot, dest, parts, silent, None)
    for i, f in enumerate(files):
        why = guard and guard.file_leak(f)
        if why:
            print(f"claude-tg notify: {f} blocked, quotes protected {why}", file=sys.stderr)
            blocked.append(str(f))
            sent += _messages(bot, dest, [(ui.t(ui.lang(cfg), "leak_file"), None)], silent, None)
            continue
        p = {"chat_id": dest.chat, "disable_notification": silent or None,
             "_timeout": 120 + f.stat().st_size // (256 * 1024)}
        if caption and i == 0:
            p["caption"], p["parse_mode"] = caption
        if markup and i == len(files) - 1:
            p["reply_markup"] = markup
        method, field, extra = method_for(f)

        def up(th, method=method, field=field, extra=extra):
            return bot.upload(method, field, f, message_thread_id=th, **p, **extra)
        try:
            sent.append(dest.do(up))
        except TgError as e:
            if method == "sendDocument":
                raise
            print(f"claude-tg notify: {method} failed for {f.name} ({e.description}); sending as a document",
                  file=sys.stderr)
            sent.append(dest.do(lambda th: bot.upload("sendDocument", "document", f, message_thread_id=th, **p)))
    return dest.result(sent, **({"blocked": blocked} if blocked else {}))


def delete_ids(bot, chat: int, ids, who="notify") -> tuple:
    """deleteMessage each id, warnings on stderr. -> (failed ids, ids worth retrying = transient failures)."""
    failed, keep = [], []
    for i in ids:
        try:
            bot.call("deleteMessage", chat_id=chat, message_id=i)
        except TgError as e:
            print(f"claude-tg {who}: message {i} not deleted ({e.description})", file=sys.stderr)
            failed.append(i)
            if e.code != 400:  # 400 = too old / already gone: never deletable
                keep.append(i)
    return failed, keep


def replace(bot, key: str, r: dict):
    """After a successful send: delete what KEY held, store the new ids (+ transient leftovers) under KEY."""
    data = _load()
    reps = data.setdefault("replace", {})
    old = reps.get(key) or {}
    keep = []
    if old.get("chat"):
        keep = delete_ids(bot, old["chat"], [i for i in old.get("message_ids", []) if i not in r["message_ids"]])[1]
        if keep and old["chat"] != r["chat"]:
            print(f"claude-tg notify: dropping undeleted {keep} of {key} (owner chat changed)", file=sys.stderr)
            keep = []
    reps[key] = {"chat": r["chat"], "message_ids": keep + r["message_ids"]}
    _save(data)


def forget(bot, cfg: dict, keys, ids) -> int:
    """`claude-tg notify-delete`: delete the messages stored under KEYs and/or explicit ids in the owner chat.
    0 = all gone (unknown KEY = nothing to do), 1 = some not deleted (transient ones stay under their KEY)."""
    data = _load()
    reps = data.setdefault("replace", {})
    failed = []
    for key in keys:
        old = reps.get(key)
        if not old:
            print(f"claude-tg notify-delete: nothing stored under {key!r}", file=sys.stderr)
            continue
        bad, keep = delete_ids(bot, old["chat"], old.get("message_ids", []), "notify-delete")
        failed += bad
        if keep:
            reps[key] = dict(old, message_ids=keep)
        else:
            reps.pop(key)
    if ids:
        failed += delete_ids(bot, owner_chat(cfg), ids, "notify-delete")[0]
    _save(data)
    return 1 if failed else 0


def delete_main(cfg: dict, a) -> int:
    if not (a.key or a.id):
        print("claude-tg notify-delete: give a KEY or --id", file=sys.stderr)
        return 2
    try:
        return forget(Bot(config.read_token(cfg)), cfg, a.key, a.id or [])
    except NotifyError as e:
        print(f"claude-tg notify-delete: {e}", file=sys.stderr)
        return 2


def main(cfg: dict, a) -> int:
    files = getattr(a, "file", None) or []
    text = " ".join(a.text) if a.text else "" if files else sys.stdin.read()  # with files: text from args only
    mode = "html" if a.html else "md" if a.markdown else "plain"
    g = guard.from_config(cfg)
    src = g and g.match(text, is_html=mode == "html")
    if src:  # quotes a protected file (config protected_paths): the owner gets the notice instead
        print(f"claude-tg notify: blocked, quotes protected {src}", file=sys.stderr)
        text, mode = ui.t(ui.lang(cfg), "leak"), "plain"
    topic, thread = target(a)
    try:
        token = config.read_token(cfg)
        if files:
            r = send_files(Bot(token), cfg, files, text, mode, a.silent, topic, a.button, thread, g)
        else:
            r = send(Bot(token), cfg, text, mode, a.silent, topic, a.button, thread)
    except NotifyError as e:
        print(f"claude-tg notify: {e}", file=sys.stderr)
        return 2
    except TgError as e:
        print(f"claude-tg notify: {e}", file=sys.stderr)
        return 1
    if getattr(a, "replace", None):
        replace(Bot(token), a.replace, r)
    print(json.dumps(r))
    return 3 if r.get("blocked") else 0
