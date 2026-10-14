"""`claude-tg notify`: one-way message from the bot to the owner, for scripts and scheduled jobs.

Runs without the service (plain sendMessage never conflicts with its getUpdates poll). Default target is a
dedicated topic ("Notifications"), created on first use and remembered in STATE_DIR/notify.json - a separate
file, so the running bot never races us on state.json. The bot treats that topic like any other: a reply there
starts a claude session, and the quoted notification reaches the prompt (bridge.Worker.prompt).

Topic registry (config `notify_topics`): short key -> display name (+ optional icon). The cache is keyed by the key,
so a new display name / icon in config edits the existing topic (editForumTopic) instead of creating another one.
An unknown --topic is a literal name (key == name), as before.

Target order: --thread ID > --main-chat > --topic KEY > $CLAUDE_TG_RUN_TOPIC (a bot-spawned claude: its own topic)
> "Notifications". `--chat NAME|ID` (config owner_groups) or a `t.me/c/` --thread link picks an owner group instead
of the home chat; the run-topic default follows $CLAUDE_TG_RUN_CHAT. Files (--file): video -> sendVideo (streams inline), image -> sendPhoto, else / on error ->
sendDocument; text becomes the caption when it fits, else a message before the files.

--replace KEY: after a successful send, the messages stored under KEY (notify.json "replace") are deleted and the
new ids take their place - send first, so a failed send never leaves the topic empty. A refused delete (400: too
old, already gone) is a warning and is forgotten; a transient one (network, 5xx) keeps its id under KEY for the
next try. `notify-delete KEY` deletes and forgets without sending.

--keep KEY [--pin]: one message per (chat, KEY) edited in place on every call (a status board); see `keep`."""
import html
import json
import os
import re
import sys
import time
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


def cli_bot(cfg: dict) -> Bot:
    """Bot for a CLI process: shares the bot's flood state (STATE_DIR/flood.json), notes a wait on stderr."""
    def note(left):
        print(f"claude-tg: chat in a Telegram flood wait, sending in {left:.0f} s", file=sys.stderr)
    return Bot(config.read_token(cfg), state_dir=config.STATE_DIR, on_wait=note)


def owner_chat(cfg: dict) -> int:
    """The bot's home chat. Group mode: config group_id. Else the private chat (id == the owner's user id):
    pinned in config, else learned by the bot (state.json)."""
    if config.group_id(cfg) is not None:
        return config.group_id(cfg)
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


STICKERS_TTL, ME_TTL, MISS_TTL = 7 * 86400, 30 * 86400, 3600  # MISS: an unknown emoji refetches at most hourly


def _cache_file() -> Path:
    return config.STATE_DIR / "cache.json"


def cached(key: str, ttl: float, fetch, now=None):
    """Value of `fetch()` remembered in STATE_DIR/cache.json for `ttl` s (Bot API lookups that rarely change:
    topic icon stickers, the bot's username). Any file error = just fetch."""
    p, now = _cache_file(), time.time() if now is None else now
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        data = {}
    hit = data.get(key) if isinstance(data, dict) else None
    if isinstance(hit, dict) and now - hit.get("at", 0) < ttl:
        return hit["value"]
    value = fetch()
    data = data if isinstance(data, dict) else {}
    data[key] = {"at": now, "value": value}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"cache.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        os.replace(tmp, p)
    except OSError:
        pass
    return value


def _cache_age(key: str) -> float:
    try:
        return time.time() - json.loads(_cache_file().read_text())[key]["at"]
    except (OSError, ValueError, KeyError, TypeError):
        return float("inf")


def bot_username(bot):
    """The bot's @username (for topic links), cached; None when getMe fails."""
    try:
        return cached("username", ME_TTL, lambda: bot.call("getMe").get("username"))
    except TgError:
        return None


def icon_id(bot, icon):
    """custom_emoji_id for an icon given as emoji or id; None (with a warning) when unknown.
    The sticker list is cached (STICKERS_TTL); an emoji missing from it refetches once the cache is > 1 h old."""
    if not icon:
        return None
    if str(icon).isdigit():
        return str(icon)
    want = str(icon).rstrip("\ufe0f")

    def fetch():
        return [{"emoji": s.get("emoji", ""), "custom_emoji_id": s["custom_emoji_id"]}
                for s in bot.call("getForumTopicIconStickers")]
    try:
        for ttl in (STICKERS_TTL, 0):
            if ttl == 0 and _cache_age("stickers") < MISS_TTL:
                break
            for s in cached("stickers", ttl, fetch):
                if s.get("emoji", "").rstrip("\ufe0f") == want:
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
    if chat in config.owner_groups(cfg or {}).values():  # an owner group: its own cache, the home one untouched
        box = data.setdefault("chats", {}).setdefault(str(chat), {})
    else:
        box = data
        if data.get("chat") != chat:  # cached ids belong to another chat (switched to/from group mode): start over
            if data.get("chat") is not None:
                data.pop("topics", None)
                data.pop("meta", None)
            data["chat"] = chat
            _save(data)
    topics = box.setdefault("topics", {})
    meta = box.setdefault("meta", {})
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


MENTION_TTL = 86400


def mention(bot, cfg: dict, spec: str):
    """`ID=Name` (or `ID`) -> (text, needs_html). Group mode: '@username' when the member has one (getChatMember,
    cached a day), else a text_mention by id (notifies without a username). Private-chat mode: just the name."""
    uid, _, name = str(spec).partition("=")
    uid, name = uid.strip(), name.strip() or uid.strip()
    group = config.group_id(cfg)
    if group is None or not uid.lstrip("-").isdigit():
        return name, False

    def fetch():
        try:
            return (bot.call("getChatMember", _retries=0, _timeout=15, chat_id=group, user_id=int(uid))
                    .get("user") or {}).get("username")
        except TgError:
            return None
    user = cached(f"username:{group}:{uid}", MENTION_TTL, fetch)
    if user:
        return "@" + user, False
    return f'<a href="tg://user?id={int(uid)}">{html.escape(name)}</a>', True


def with_mentions(bot, cfg: dict, text: str, mode: str, specs) -> tuple:
    """Put the mentions of `specs` at `{who}` in text (else in front): (text, mode). A text_mention or a non-plain
    text turns the whole message into HTML (plain text escaped)."""
    if not isinstance(specs, (list, tuple)) or not specs:
        return text, mode
    ms = [mention(bot, cfg, s) for s in specs]
    if mode == "md":
        text, mode = fmt.md_to_html(text), "html"
    elif mode == "plain" and any(h for _, h in ms):
        text, mode = html.escape(text, quote=False), "html"
    who = ", ".join(m for m, _ in ms)
    return (text.replace("{who}", who) if "{who}" in text else f"{who} {text}"), mode



def people(bot, cfg: dict, owner=None) -> list:
    """Who the bot talks to: group mode = allowed_users (getChatMember), private mode = the owner (getChat); a day
    in the cache. [{id, handle, names}]: handle '@username', else a markdown text mention (no username)."""
    group = config.group_id(cfg)
    uids = sorted(config.allowed_users(cfg)) if group is not None else [owner] if owner else []
    aliases = cfg.get("people_aliases") or {}
    out = []
    for uid in uids:
        def fetch(uid=uid):
            if group is not None:
                u = bot.call("getChatMember", _retries=0, _timeout=15, chat_id=group, user_id=int(uid)).get("user")
            else:
                u = bot.call("getChat", _retries=0, _timeout=15, chat_id=int(uid))
            return {k: (u or {}).get(k) for k in ("username", "first_name", "last_name")}
        try:
            u = cached(f"member:{group or 'private'}:{uid}", MENTION_TTL, fetch)
        except TgError:
            continue  # unknown here (not a member, chat not started): nobody to address
        first, last = (u.get("first_name") or "").strip(), (u.get("last_name") or "").strip()
        names = [n for n in (first, last, f"{first} {last}".strip()) if n]
        names += [str(a).strip() for a in aliases.get(str(uid), aliases.get(uid, [])) if str(a).strip()]
        names = list(dict.fromkeys(names))
        if not names and not u.get("username"):
            continue
        label = names[0] if names else str(uid)
        handle = "@" + u["username"] if u.get("username") else f"[{label}](tg://user?id={int(uid)})"
        out.append({"id": int(uid), "handle": handle, "names": names or [label]})
    return out


def people_prompt(ps: list, group: bool) -> str:
    """The addressing rule for claude (--append-system-prompt): Telegram notifies only on a mention."""
    if not ps:
        return ""
    lines = "\n".join(f"- {' / '.join(p['names'])}: {p['handle']}" for p in ps)
    if group:
        return ("You answer in a Telegram group shared by several people. Their mentions:\n" + lines + "\n"
                "Address a person only by their mention above (e.g. \"" + ps[0]["handle"] + ", нужно от тебя: …\"), "
                "never by a bare or bold name (\"Name:\"): Telegram notifies only on a mention. A final message that "
                "waits on someone (a decision, an action, an answer) starts with their mention(s) and the ask - one "
                "message, no separate ping. If the work is a tracked task, also record the wait "
                "(`github-tasks needs <ref> --who <name> --action …`).")
    return ("You answer in a Telegram chat with " + ps[0]["names"][0] + " (" + ps[0]["handle"] + "). A final message "
            "that waits on them (a decision, an action, an answer) starts with " + ps[0]["handle"] + " and the ask: "
            "the mention notifies even in a muted chat and marks the message as waiting on them. No mention in other "
            "messages. If the work is a tracked task, also record the wait (`github-tasks needs <ref> --action …`).")


def address(text: str, ps: list) -> str:
    """A line opening with a person's name as a header ("Name:", "**Name:**") -> their mention, so it notifies."""
    names = sorted({n for p in ps for n in p["names"]}, key=len, reverse=True)
    if not names or not text:
        return text
    by = {n.casefold(): p["handle"] for p in reversed(ps) for n in p["names"]}
    head = re.compile(r"^(?P<lead>[ \t]*(?:[-*•][ \t]+)?)(?:\*\*|__)?(?P<name>" + "|".join(map(re.escape, names))
                      + r")(?:[ \t]*:[ \t]*(?:\*\*|__)|(?:\*\*|__)[ \t]*:|[ \t]*:)[ \t]*", re.I)
    out, fence = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence:
            line = head.sub(lambda m: m["lead"] + by[m["name"].casefold()] + ", ", line, count=1)
        out.append(line)
    return "\n".join(out)

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
        return None, _thread(a.thread)
    if a.main_chat:
        return None, None
    if a.topic:
        return a.topic, None
    run = (os.environ if env is None else env).get(config.RUN_TOPIC_ENV, "")
    if run.isdigit() and int(run):
        return None, int(run)
    return DEFAULT_TOPIC, None


def _thread(ref) -> int:
    from .inbox import thread_of  # inbox imports this module
    return thread_of(ref)


def target_chat(cfg, a, env=None):
    """Destination chat: --chat, else the chat of a `t.me/c/` --thread link, else - when the run-topic default
    applies - $CLAUDE_TG_RUN_CHAT if it names a configured chat, else the home chat (None)."""
    from .inbox import target_chat as pick
    ref = getattr(a, "thread", None)
    if getattr(a, "chat", None) or ref:
        return pick(cfg, getattr(a, "chat", None), ref)
    env = os.environ if env is None else env
    if a.main_chat or a.topic or not env.get(config.RUN_TOPIC_ENV, "").isdigit():
        return None
    try:
        return config.chat_ref(cfg, env.get(config.RUN_CHAT_ENV) or None)
    except ValueError:
        return None


class _Dest:
    """Owner chat + thread; a cached topic deleted in the client is recreated once. An explicit thread is not."""

    def __init__(self, bot, cfg, topic, thread, chat=None):
        self.bot, self.cfg, self.topic = bot, cfg, topic
        self.chat = owner_chat(cfg) if chat is None else chat
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


def send(bot, cfg: dict, text: str, mode="plain", silent=False, topic=DEFAULT_TOPIC, buttons=None, thread=None,
         chat=None) -> dict:
    text = text.strip()
    if not text:
        raise NotifyError("empty text")
    markup = keyboard(buttons)
    dest = _Dest(bot, cfg, topic, thread, chat)
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
               thread=None, guard=None, chat=None) -> dict:
    """Upload files; text = caption of the first file when it fits in one caption, else messages before them.
    Files the leak guard rejects are replaced by a notice (listed under "blocked")."""
    files = check_files(paths)
    markup = keyboard(buttons)
    dest = _Dest(bot, cfg, topic, thread, chat)
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


def keep(bot, cfg: dict, key: str, text: str, mode="plain", topic=DEFAULT_TOPIC, thread=None, chat=None,
         pin=False, silent=True) -> dict:
    """--keep KEY: one message per (chat, KEY) kept up to date in place (a status board). Stored message in the same
    topic -> editMessageText (`"unchanged": true` when Telegram says not modified, `"edited": true` else). None yet,
    or the edit is refused (deleted message / topic: any 400) -> a new message (+ pinChatMessage with `pin`, silent),
    its id stored in notify.json "keep". One message only: text over the limit is an error."""
    text = text.strip()
    if not text:
        raise NotifyError("empty text")
    parts = chunks(text, mode)
    if len(parts) > 1:
        raise NotifyError(f"--keep needs one message; text is {len(text)} chars (limit {fmt.LIMIT})")
    body, parse = parts[0]
    dest = _Dest(bot, cfg, topic, thread, chat)
    k = f"{dest.chat}:{key}"
    old = _load().get("keep", {}).get(k)
    if old and old.get("thread") == dest.thread:
        try:
            bot.call("editMessageText", chat_id=dest.chat, message_id=old["message_id"], text=body, parse_mode=parse,
                     link_preview_options={"is_disabled": True})
            return dest.result([old], edited=True)
        except TgError as e:
            if "message is not modified" in e.description:
                return dest.result([old], unchanged=True)
            if e.code != 400:
                raise
            print(f"claude-tg notify: kept message {key} gone ({e.description}); sending a new one", file=sys.stderr)
    sent = _messages(bot, dest, [(body, parse)], silent, None)
    mid = sent[0]["message_id"]
    extra = {"created": True}
    if pin:
        try:
            bot.call("pinChatMessage", chat_id=dest.chat, message_id=mid, disable_notification=True)
            extra["pinned"] = True
        except TgError as e:  # no can_pin_messages right: the message still works, unpinned
            print(f"claude-tg notify: not pinned ({e.description})", file=sys.stderr)
    data = _load()
    data.setdefault("keep", {})[k] = {"thread": dest.thread, "message_id": mid}
    _save(data)
    return dest.result(sent, **extra)


def with_topic_icon(cfg: dict, topic, icon) -> dict:
    """--topic-icon: the topic of KEY gets this icon (registry name kept; created with it or edited once)."""
    if not (topic and icon):
        return cfg
    return dict(cfg, notify_topics={**(cfg.get("notify_topics") or {}), topic: {**spec(cfg, topic), "icon": icon}})


def forget(bot, cfg: dict, keys, ids, chat=None) -> int:
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
        failed += delete_ids(bot, owner_chat(cfg) if chat is None else chat, ids, "notify-delete")[0]
    _save(data)
    return 1 if failed else 0


def delete_main(cfg: dict, a) -> int:
    if not (a.key or a.id):
        print("claude-tg notify-delete: give a KEY or --id", file=sys.stderr)
        return 2
    try:
        chat = None
        if getattr(a, "chat", None):
            from .inbox import target_chat as pick
            chat = pick(cfg, a.chat)
        return forget(cli_bot(cfg), cfg, a.key, a.id or [], chat)
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
    try:
        topic, thread = target(a)
        chat = target_chat(cfg, a)
        bot = cli_bot(cfg)
        cfg = with_topic_icon(cfg, topic, getattr(a, "topic_icon", None))
        text, mode = with_mentions(bot, cfg, text, mode, getattr(a, "mention", None))
        if getattr(a, "keep", None):
            if files or getattr(a, "replace", None) or a.button:
                raise NotifyError("--keep takes text only (no --file / --replace / --button)")
            r = keep(bot, cfg, a.keep, text, mode, topic, thread, chat, getattr(a, "pin", False), a.silent)
            print(json.dumps(r))
            return 0
        if files:
            r = send_files(bot, cfg, files, text, mode, a.silent, topic, a.button, thread, g, chat)
        else:
            r = send(bot, cfg, text, mode, a.silent, topic, a.button, thread, chat)
    except NotifyError as e:
        print(f"claude-tg notify: {e}", file=sys.stderr)
        return 2
    except TgError as e:
        print(f"claude-tg notify: {e}", file=sys.stderr)
        return 1
    if getattr(a, "replace", None):
        replace(bot, a.replace, r)
    print(json.dumps(r))
    return 3 if r.get("blocked") else 0
