"""`claude-tg group list|add|remove`: manage config `owner_groups` without editing the config file by hand.

Tenant-safe: the agent never reads or writes ~/.config/claude-tg itself; only the `owner_groups` key is rewritten
(atomic replace, every other key and the file mode kept). Private-owner mode only."""
import json
import os
import re
import sys
import tempfile

from . import config, service
from .botapi import Bot, TgError

ADDED_RE = re.compile(r"owner added the bot to chat (-\d+)")


class GroupError(Exception):
    pass


def raw_config() -> dict:
    """The config file as written (no defaults merged in), {} when absent."""
    if not config.CONFIG_FILE.exists():
        return {}
    data = json.loads(config.CONFIG_FILE.read_text())
    if not isinstance(data, dict):
        raise GroupError(f"{config.CONFIG_FILE}: not a JSON object")
    return data


def write_groups(groups: dict):
    write_key("owner_groups", groups)


def write_key(key: str, value):
    """Replace only this config key, atomically; keep key order, other keys and the file mode."""
    data = raw_config()
    data[key] = value
    path = config.CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = (path.stat().st_mode & 0o7777) if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def newest_added(text: str, skip=()):
    """Chat id of the newest `owner added the bot to chat <id>` log line not in skip, else None."""
    for cid in reversed(ADDED_RE.findall(text)):
        if int(cid) not in skip:
            return int(cid)
    return None


def inspect(bot, me_id: int, chat_id: int) -> dict:
    """getChat + getChatMember(bot) -> {title, forum, admin, topics, error}."""
    out = {"title": "", "forum": False, "admin": False, "topics": False, "type": "", "error": ""}
    try:
        chat = bot.call("getChat", _retries=0, _timeout=15, chat_id=chat_id)
    except TgError as e:
        out["error"] = f"getChat: {e.description}"
        return out
    out.update(title=chat.get("title", ""), type=chat.get("type", ""), forum=bool(chat.get("is_forum")))
    try:
        m = bot.call("getChatMember", _retries=0, _timeout=15, chat_id=chat_id, user_id=me_id)
    except TgError as e:
        out["error"] = f"getChatMember: {e.description}"
        return out
    out.update(admin=m.get("status") == "administrator", topics=bool(m.get("can_manage_topics")))
    return out


def problems(info: dict) -> list:
    """Plain fix lines; empty = the group works as an owner group."""
    if info["error"]:
        return [f"{info['error']} -> add the bot to the group first, or check the id (newest add: omit ID)"]
    out = []
    if info["type"] != "supergroup" or not info["forum"]:
        out.append("turn Topics on in the group settings (makes it a forum supergroup)")
    if not info["admin"]:
        out.append("make the bot an admin of the group with Manage Topics")
    elif not info["topics"]:
        out.append("give the bot the Manage Topics admin right")
    return out


def _bot(cfg):
    bot = Bot(config.read_token(cfg))
    return bot, bot.call("getMe", _retries=0, _timeout=15)["id"]


def _apply(cfg, restart: bool):
    if not restart:
        print("# not restarted (--no-restart): `claude-tg restart` applies it", file=sys.stderr)
        return 0
    if service.installed_mode() is None:
        print("# no service installed: the change applies when the bot starts", file=sys.stderr)
        return 0
    return service.restart(cfg, 600)


def _private_only(cfg):
    if config.group_id(cfg) is not None:
        raise GroupError("group mode (group_id set): owner groups are ignored there; nothing changed")


def list_groups(cfg) -> int:
    groups = config.owner_groups(cfg)
    if config.group_id(cfg) is not None:
        print("# group mode (group_id set): owner_groups are ignored", file=sys.stderr)
    print("name\tid\ttitle\tforum\tadmin")
    if not groups:
        return 0
    bot, me = _bot(cfg)
    for name, cid in groups.items():
        i = inspect(bot, me, cid)
        admin = "error: " + i["error"] if i["error"] else (
            "admin, can_manage_topics" if i["admin"] and i["topics"] else
            "admin, no Manage Topics" if i["admin"] else "not admin")
        print(f"{name}\t{cid}\t{i['title']}\t{'on' if i['forum'] else 'off'}\t{admin}")
    return 0


def add(cfg, name: str, chat_id=None, restart=True) -> int:
    _private_only(cfg)
    if not name or name.lstrip("-").isdigit() or name != name.strip():
        raise GroupError(f"bad name {name!r}: use a short word (it is the --chat NAME)")
    groups = {str(k): v for k, v in (raw_config().get("owner_groups") or {}).items()}
    known = config.owner_groups(cfg)
    if chat_id is None:
        if name in known:
            chat_id = known[name]
        else:
            chat_id = newest_added(service.journal(), skip=set(known.values()))
            if chat_id is None:
                raise GroupError("no `owner added the bot to chat` line in the bot's logs: add the bot to the group "
                                 "(as the owner, bot running), or pass the id")
            print(f"# chat {chat_id}: newest group the owner added the bot to (bot logs)", file=sys.stderr)
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        raise GroupError(f"bad id {chat_id!r}: a supergroup id looks like -100…")
    if chat_id >= 0:
        raise GroupError(f"bad id {chat_id}: a supergroup id is negative (-100…)")
    if name in known and known[name] != chat_id:
        raise GroupError(f"{name!r} is already chat {known[name]}: remove it first or pick another name")
    other = [n for n, c in known.items() if c == chat_id and n != name]
    if other:
        raise GroupError(f"chat {chat_id} is already owner group {other[0]!r}")
    bot, me = _bot(cfg)
    info = inspect(bot, me, chat_id)
    bad = problems(info)
    if bad:
        raise GroupError(f"chat {chat_id} {info['title']!r}: " + "; ".join(bad) + "; then run this again")
    if known.get(name) == chat_id:
        print(f"{name}\t{chat_id}\t{info['title']}\tunchanged")
        return 0
    groups[name] = chat_id
    write_groups(groups)
    print(f"{name}\t{chat_id}\t{info['title']}\tadded")
    return _apply(cfg, restart)


def remove(cfg, name: str, restart=True) -> int:
    _private_only(cfg)
    groups = {str(k): v for k, v in (raw_config().get("owner_groups") or {}).items()}
    if name not in groups:
        raise GroupError(f"no owner group {name!r} ({', '.join(groups) or 'none set'})")
    cid = groups.pop(name)
    write_groups(groups)
    print(f"{name}\t{cid}\tremoved")
    return _apply(cfg, restart)


def main(cfg, a) -> int:
    try:
        if a.action == "list":
            return list_groups(cfg)
        if a.action == "add":
            return add(cfg, a.name, a.id, not a.no_restart)
        return remove(cfg, a.name, not a.no_restart)
    except GroupError as e:
        print(f"claude-tg group: {e}", file=sys.stderr)
        return 2
    except TgError as e:
        print(f"claude-tg group: {e}", file=sys.stderr)
        return 1
