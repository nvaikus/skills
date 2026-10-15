"""`claude-tg bots list|add|remove`: manage config `allowed_bots` (peer bots heard in groups when they address this
bot) without editing the config file by hand. Same write rules as `claude-tg group` (only that key, atomic)."""
import re
import sys

from . import config, service
from .groups import GroupError, _apply, raw_config, write_key

IGNORED_RE = re.compile(r"ignored: bot (\d+) \(@(\w+)\)")


def logged(text: str) -> dict:
    """username (lowercase) -> bot id from the bridge's `ignored: bot ID (@name)` log lines."""
    return {name.lower(): int(bid) for bid, name in IGNORED_RE.findall(text)}


def resolve(ref: str) -> int:
    """ID or @username -> bot id; a username must appear in the bot's logs (a message from it was ignored)."""
    ref = ref.strip()
    if ref.lstrip("-").isdigit():
        bid = int(ref)
        if bid <= 0:
            raise GroupError(f"bad id {bid}: a bot id is positive (the token part before ':')")
        return bid
    name = ref.lstrip("@").lower()
    bid = logged(service.journal()).get(name)
    if bid is None:
        raise GroupError(f"@{name} not in the bot's logs (it logs `ignored: bot ID (@name)` when that bot writes to "
                         "it): pass the numeric id (the bot token's part before ':', or ask its owner)")
    print(f"# @{name} = {bid} (bot logs)", file=sys.stderr)
    return bid


def current() -> list:
    return [int(x) for x in raw_config().get("allowed_bots") or [] if str(x).lstrip("-").isdigit()]


def main(cfg, a) -> int:
    try:
        if a.action == "list":
            names = {v: k for k, v in logged(service.journal()).items()}
            print("id\tusername")
            for bid in sorted(config.allowed_bots(cfg)):
                print(f"{bid}\t{'@' + names[bid] if bid in names else ''}")
            print(f"# bot_turns_max {cfg.get('bot_turns_max')}: bot messages answered in a row per topic without a "
                  "human", file=sys.stderr)
            return 0
        bid, ids = resolve(a.bot), current()
        if a.action == "add":
            if bid in ids:
                print(f"{bid}\tunchanged")
                return 0
            write_key("allowed_bots", ids + [bid])
            print(f"{bid}\tadded")
        else:
            if bid not in ids:
                raise GroupError(f"bot {bid} is not in allowed_bots ({', '.join(map(str, ids)) or 'none set'})")
            write_key("allowed_bots", [x for x in ids if x != bid])
            print(f"{bid}\tremoved")
        return _apply(cfg, not a.no_restart)
    except GroupError as e:
        print(f"claude-tg bots: {e}", file=sys.stderr)
        return 2
