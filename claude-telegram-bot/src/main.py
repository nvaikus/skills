"""argv -> subcommand. Exit: 0 ok, 1 runtime failure, 2 usage/config."""
import argparse
import fcntl
import logging
import signal
import sys

from . import config

TOP = """Telegram bot <-> Claude Code bridge: one bot topic = one `claude -p` session.

examples:
  claude-tg setup            # BotFather steps + token file (prompted, or --token-stdin)
  claude-tg doctor           # token, getMe, Threaded Mode or group rights, claude, model-cli
  claude-tg install          # systemd unit (system if sudo works, else user unit), starts it
  claude-tg restart          # waits until no run is active, then restarts (use after deploys)
  claude-tg logs -f          # journalctl -u claude-tg
  claude-tg run              # foreground (debugging); only one poller per token
  echo done | claude-tg notify       # bot -> owner, topic "Notifications" (scripts, scheduled jobs)
  claude-tg notify --file out.mp4 "demo"   # file -> owner; inside a bot run: into that run's topic
  claude-tg notify --replace digest "..."  # send, then delete the previous message(s) sent with --replace digest
  claude-tg notify-delete digest           # delete the message(s) stored under --replace digest
  claude-tg spawn --title "Fix X" --cwd ~/proj "do X"   # new topic + claude session with that prompt (scripts)
  claude-tg send --thread 123 "next step"   # prompt into a topic as if the owner wrote it (resumes / joins a run)
  claude-tg alive --thread 123              # exit 0 = a claude run is live or queued there, 1 = idle
  claude-tg topic-icon --thread 123 ❗       # emoji | off | base (icon from /icon or spawn --icon)
  claude-tg group add team                 # connect the owner group the bot was just added to (never edit the config)
  claude-tg spawn --chat team --title "Fix X" "do X"   # same in an owner group (config owner_groups name or id)
  claude-tg triage on --cwd ~ --exclude mail   # notify --topic events open a "🔎" investigation topic
  claude-tg bots add 123456789              # let that bot talk to this one in groups (replies / @mentions only)
  claude-tg profile --name "Helper" --photo me.png   # bot's own name / about / avatar (no args: show)
  claude-tg local-api status # local Bot API server for attachments > 20 MB (optional)
  claude-tg chats            # group setup: group ids + sender ids from pending updates (service stopped)
"""


class TokenFilter(logging.Filter):
    def __init__(self, token):
        super().__init__()
        self.token = token

    def filter(self, record):
        msg = record.getMessage()
        if self.token in msg:
            record.msg, record.args = msg.replace(self.token, "<token>"), ()
        return True


def run(cfg):
    from .bridge import Bridge
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(config.STATE_DIR / "lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("claude-tg: another instance is running (service? `claude-tg status`)", file=sys.stderr)
        return 2
    token = config.read_token(cfg)
    handler = logging.StreamHandler()
    handler.addFilter(TokenFilter(token))
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(levelname)s %(threadName)s: %(message)s")
    bridge = Bridge(cfg, token)

    def on_term(*_):
        bridge.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, on_term)
    bridge.serve()


def main(argv=None):
    p = argparse.ArgumentParser(prog="claude-tg", description=TOP, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    CHAT = ("target chat: an owner group (config owner_groups name or id); default the home chat; a t.me/c/ topic "
            "link implies its chat")
    s = sub.add_parser("setup", help="BotFather steps + save the token file")
    s.add_argument("--token-stdin", action="store_true", help="read the token from stdin (never pass it in argv)")
    sub.add_parser("doctor", help="check token, bot, Threaded Mode (private) or group + admin rights (group mode), claude, voice deps, service")
    sub.add_parser("chats", help="group mode setup: groups + senders in pending updates (nothing confirmed)",
                   description="Lists group/supergroup chats (id, type, title, forum) and the users who wrote "
                               "there, from getUpdates without an offset: nothing is confirmed, the bot still gets "
                               "them on start. 409 = the service is polling: stop it first.")
    s = sub.add_parser("install", help="write + enable + (re)start the systemd unit (Linux)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--system", dest="mode", action="store_const", const="system",
                   help="system unit with User= + root token copy (sudo); default when sudo works without a prompt")
    g.add_argument("--user", dest="mode", action="store_const", const="user",
                   help="systemd --user unit, no sudo; needs linger (default without sudo)")
    sub.add_parser("uninstall", help="stop + remove the unit (and the root token copy); state is kept")
    sub.add_parser("status", help="systemctl status + runs in flight / queued")
    s = sub.add_parser("restart", help="restart the service once no run is active (deploys: never cut a run)")
    s.add_argument("--wait", type=int, default=600, metavar="SEC", help="max seconds to wait for idle (default 600)")
    s.add_argument("--now", action="store_true", help="do not wait; cut runs re-run after the restart")
    s.add_argument("--report", metavar="TOPIC", help=argparse.SUPPRESS)  # set by the deferred in-bot restart
    s = sub.add_parser("logs", help="journalctl [--user] -u claude-tg")
    s.add_argument("-n", type=int, default=50)
    s.add_argument("-f", "--follow", action="store_true")
    sub.add_parser("run", help="run the bot in the foreground")
    s = sub.add_parser("notify", help="send a message from the bot to the owner (no service needed)",
                       description="Text from args or stdin (with --file: args only, becomes the caption). Target: "
                                   "--thread > --main-chat > --topic > $CLAUDE_TG_RUN_TOPIC (inside a bot run: its own "
                                   "topic) > topic 'Notifications' (created once, id kept in STATE_DIR/notify.json); "
                                   "--topic KEY resolves via config notify_topics. Replying there starts a claude "
                                   "session that sees the quoted notification. Prints {chat, thread, message_ids}. "
                                   "Exit 3 = a file was withheld by the leak guard.")
    s.add_argument("--chat", metavar="NAME|ID", help=CHAT)
    s.add_argument("--replace", metavar="KEY",
                   help="after a successful send, delete the message(s) last sent with this KEY and remember the new "
                        "ones (STATE_DIR/notify.json); a delete that fails (too old, gone) only warns")
    s.add_argument("--keep", metavar="KEY",
                   help="keep ONE message per chat + KEY up to date: edit it in place (prints edited / unchanged), "
                        "send a new one when none is stored or it was deleted (STATE_DIR/notify.json keep)")
    s.add_argument("--pin", action="store_true", help="with --keep: pin the message when it is (re)sent, silently")
    s.add_argument("--topic-icon", metavar="EMOJI",
                   help="with --topic: the topic's icon (getForumTopicIconStickers emoji); overrides notify_topics")
    s.add_argument("text", nargs="*", help="message text (default: stdin)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--html", action="store_true", help="text is Telegram HTML")
    g.add_argument("--markdown", "--md", action="store_true", help="text is markdown (converted like bot answers)")
    s.add_argument("--silent", action="store_true", help="no sound / vibration")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--triage", dest="triage", action="store_const", const=True,
                   help="open an investigation topic for this --topic event even if config notify_triage is off "
                        "(never with --keep / --replace / --file or inside a bot run)")
    g.add_argument("--no-triage", dest="triage", action="store_const", const=False,
                   help="no investigation topic for this event")
    s.add_argument("--mention", action="append", metavar="ID=NAME",
                   help="group mode: mention this user at {who} in the text (else in front): @username via "
                        "getChatMember (cached a day), else a text_mention; private mode: the name (repeatable)")
    s.add_argument("--file", action="append", metavar="PATH",
                   help="send a file (repeatable; <= 50 MB): mp4/mov/m4v as streaming video, jpg/png/webp as photo, "
                        "else as document")
    s.add_argument("--button", action="append", metavar="TEXT=URL",
                   help="inline URL button under the message (repeatable, one per row)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--topic", metavar="KEY",
                   help="config notify_topics key, else a literal topic name (default: own topic inside a bot run, "
                        "else Notifications)")
    g.add_argument("--thread", metavar="ID|LINK", help="send into this topic (message_thread_id or topic link)")
    g.add_argument("--main-chat", action="store_true", help="send to All messages instead of a topic")
    INBOX = ("Needs the running bot: the prompt is posted into the topic as a bot message, then queued in "
             "STATE_DIR/inbox/ and run by the bot like an owner message (queued while it is down). Prints JSON.")
    s = sub.add_parser("spawn", help="new topic + claude session started with PROMPT (args or stdin)",
                       description=INBOX + " Output: {thread, link, message_id, cwd[, icon]}.")
    s.add_argument("--title", required=True, help="topic name")
    s.add_argument("--chat", metavar="NAME|ID", help=CHAT)
    s.add_argument("--mention", action="append", metavar="ID=NAME",
                   help="group mode: mention this user at {who} in the posted line (else in front): @username via "
                        "getChatMember (cached a day), else a text_mention; private mode: the name (repeatable)")
    s.add_argument("--cwd", help="working dir of the topic's session (default: config default_cwd)")
    s.add_argument("--icon", help="topic icon emoji (getForumTopicIconStickers); kept as the topic's base icon")
    s.add_argument("--start-icon", metavar="EMOJI",
                   help="create the topic with this icon instead, not kept as base (topic-icon base restores --icon or "
                        "none); output gets \"icon\" when an icon was set")
    s.add_argument("--system", metavar="TEXT|@FILE",
                   help="appended to claude's system prompt on every run of this topic (topic role)")
    s.add_argument("--settings", metavar="PATH",
                   help="absolute path of a claude settings JSON passed as --settings on every run of this topic "
                        "(e.g. a deny list); missing/invalid at run time -> the run is refused, the topic is told")
    s.add_argument("--silent", action="store_true", help="post the prompt without sound")
    s.add_argument("--show", metavar="TEXT",
                   help="post this short line in the topic instead of the prompt (claude still gets the full prompt)")
    s.add_argument("--quiet", action="store_true",
                   help="make the topic quiet (/quiet): text between steps stays in the status line, only the final "
                        "answer is posted")
    s.add_argument("prompt", nargs="*")
    s = sub.add_parser("send", help="PROMPT into an existing topic as if the owner wrote it",
                       description=INBOX + " A live run takes it at once (stdin); else the topic's session resumes.")
    s.add_argument("--thread", required=True, metavar="ID|LINK")
    s.add_argument("--chat", metavar="NAME|ID", help=CHAT)
    s.add_argument("--silent", action="store_true", help="post the prompt without sound")
    s.add_argument("--show", metavar="TEXT",
                   help="post this short line in the topic instead of the prompt (claude still gets the full prompt)")
    s.add_argument("--quiet", action="store_true",
                   help="make the topic quiet (/quiet): text between steps stays in the status line, only the final "
                        "answer is posted")
    s.add_argument("prompt", nargs="*")
    s = sub.add_parser("alive", help="is a claude run live (or queued) in a topic? exit 0 yes, 1 no",
                       description="Live = a process with CLAUDE_TG_RUN_TOPIC=<thread> (/proc), a pending request "
                                   "of the topic in state.json, or an inbox file for it. Prints JSON.")
    s.add_argument("--thread", required=True, metavar="ID|LINK")
    s.add_argument("--chat", metavar="NAME|ID", help=CHAT)
    s = sub.add_parser("topic-icon", help="set a topic's icon: emoji | off | base")
    s.add_argument("--thread", required=True, metavar="ID|LINK")
    s.add_argument("--chat", metavar="NAME|ID", help=CHAT)
    s.add_argument("icon", help="emoji from getForumTopicIconStickers, off, or base (the topic's /icon or "
                                "spawn --icon; none = off)")
    s = sub.add_parser("notify-delete", help="delete notifications sent with --replace KEY (or by message id)",
                       description="Deletes the messages stored under each KEY and forgets the KEY; --id deletes "
                                   "message ids in the owner chat. Exit 0 = all deleted (unknown KEY: nothing to do), "
                                   "1 = some not deleted (too old, gone, network; a network failure keeps the id), "
                                   "2 = usage.")
    s.add_argument("key", nargs="*", help="--replace KEY(s)")
    s.add_argument("--id", type=int, action="append", metavar="MSG", help="message id in the owner chat (repeatable)")
    s.add_argument("--chat", metavar="NAME|ID", help=CHAT)
    s = sub.add_parser("group", help="owner groups (private mode): list | add NAME [ID] | remove NAME",
                       description="Manages config owner_groups without hand-editing the config: only that key is "
                                   "rewritten (atomic, other keys + file mode kept), then the bot restarts like "
                                   "`claude-tg restart` (inside a bot run: deferred until idle). add without ID takes "
                                   "the newest `owner added the bot to chat <id>` from the bot's logs and checks: "
                                   "forum supergroup, bot admin with Manage Topics. Refused in group mode.")
    gs = s.add_subparsers(dest="action", required=True)
    gs.add_parser("list", help="TSV: name, id, title, forum on/off, bot admin rights")
    g = gs.add_parser("add", help="add (or confirm) an owner group; idempotent")
    g.add_argument("name", help="the --chat NAME used by spawn / send / notify")
    g.add_argument("id", nargs="?", help="supergroup id -100…; default: newest group the owner added the bot to")
    g.add_argument("--no-restart", action="store_true", help="write the config only")
    g = gs.add_parser("remove", help="drop an owner group from the config")
    g.add_argument("name")
    g.add_argument("--no-restart", action="store_true", help="write the config only")
    s = sub.add_parser("bots", help="peer bots heard in groups (allowed_bots): list | add BOT | remove BOT",
                       description="Manages config allowed_bots without hand-editing the config (only that key, "
                                   "atomic), then restarts like `group`. A listed bot's group message is answered only "
                                   "when it addresses this bot: a reply to its message, @username, /cmd@username. "
                                   "Telegram delivers bot messages only with Bot-to-Bot Communication Mode on (BotFather) "
                                   "for at least one of the two bots. Loop cap: config bot_turns_max (default 6).")
    gs = s.add_subparsers(dest="action", required=True)
    gs.add_parser("list", help="TSV: id, username (from the bot's logs)")
    for act, h in (("add", "allow a bot; idempotent"), ("remove", "drop a bot")):
        g = gs.add_parser(act, help=h)
        g.add_argument("bot", help="bot id (token part before ':') or @username seen in the bot's logs")
        g.add_argument("--no-restart", action="store_true", help="write the config only")
    s = sub.add_parser("triage", help="auto-triage of notify events: show | on [opts] | off",
                       description="Config notify_triage (only that key is rewritten; applies to the next notify, no "
                                   "restart). On: every `notify --topic KEY` event (not --keep / --replace / --file, "
                                   "not from inside a bot run, not a first line with a check mark) also opens a topic "
                                   "'🔎 <first line>' whose claude session finds the cause, fixes what is safe and "
                                   "reports. Same first line (numbers ignored) within the cooldown: counted in the "
                                   "open topic. Prints the settings as JSON.")
    s.add_argument("action", choices=["show", "on", "off"], nargs="?", default="show")
    s.add_argument("--cwd", help="working dir of triage sessions (default: config default_cwd)")
    s.add_argument("--chat", metavar="NAME|ID", help="owner group for triage topics; home = the notification's chat")
    s.add_argument("--cooldown", type=int, metavar="MIN", help="same event within MIN minutes = no new topic (360)")
    s.add_argument("--topics", nargs="+", metavar="KEY", help="only these notify topic keys; 'all' = every key")
    s.add_argument("--exclude", nargs="+", metavar="KEY", help="never these keys; 'none' clears the list")
    s = sub.add_parser("profile", help="show or change the bot's own name, descriptions, profile photo",
                       description="No flags: print name / description / short (TSV, newlines as \\n). Each flag is "
                                   "applied on its own; prints one '<field>\\t<ok|error: ...>' line per change. "
                                   "An empty TEXT clears the field.")
    s.add_argument("--name", metavar="TEXT", help="bot name (<= 64 chars)")
    s.add_argument("--description", metavar="TEXT", help="text shown in an empty chat with the bot (<= 512)")
    s.add_argument("--short", metavar="TEXT", help="profile 'about' text, also in shares (<= 120)")
    s.add_argument("--photo", metavar="FILE", help="profile photo; jpg, other images converted via ffmpeg")
    s.add_argument("--photo-remove", action="store_true", help="remove the bot's profile photo")
    s.add_argument("--lang", metavar="CODE", help="two-letter language code for name / descriptions (default: all)")
    s = sub.add_parser("local-api", help="local Bot API server for attachments > 20 MB (install | serve | status)",
                       description="Downloads only: polling and sending stay on api.telegram.org. Config: "
                                   "local_api_url (http://127.0.0.1:PORT), local_api_id / local_api_hash = secret "
                                   "references env:NAME | cred:NAME (default env:TELEGRAM_API_ID / "
                                   "env:TELEGRAM_API_HASH, from the env or env_files), local_api_bin. Setup: references/setup.md.")
    s.add_argument("action", choices=["install", "uninstall", "serve", "status"],
                   help="install = systemd --user unit claude-tg-botapi; serve = its ExecStart; status = unit + probe")
    a = p.parse_args(argv)
    try:
        cfg = config.load()
    except ValueError as e:
        print(f"claude-tg: bad {config.CONFIG_FILE}: {e}", file=sys.stderr)
        return 2
    from . import service
    try:
        if a.cmd == "notify":
            from . import notify
            return notify.main(cfg, a)
        if a.cmd == "notify-delete":
            from . import notify
            return notify.delete_main(cfg, a)
        if a.cmd in ("spawn", "send", "alive", "topic-icon"):
            from . import inbox
            return inbox.main(cfg, a)
        if a.cmd == "group":
            from . import groups
            return groups.main(cfg, a)
        if a.cmd == "bots":
            from . import peerbots
            return peerbots.main(cfg, a)
        if a.cmd == "triage":
            from . import triage
            return triage.main(cfg, a)
        if a.cmd == "profile":
            from . import botprofile
            return botprofile.main(cfg, a)
        if a.cmd == "local-api":
            from . import localapi
            try:
                return getattr(localapi, a.action)(cfg) or 0
            except localapi.Fail as e:
                print(f"claude-tg local-api: {e}", file=sys.stderr)
                return 2
        if a.cmd == "run":
            return run(cfg) or 0
        if a.cmd == "setup":
            return service.setup(cfg, a.token_stdin)
        if a.cmd == "doctor":
            return service.doctor(cfg)
        if a.cmd == "chats":
            return service.chats(cfg)
        if a.cmd == "install":
            return service.install(cfg, a.mode) or 0
        if a.cmd == "uninstall":
            return service.uninstall(cfg) or 0
        if a.cmd == "restart":
            return service.restart(cfg, None if a.now else a.wait, a.report)
        if a.cmd == "status":
            return service.status(cfg)
        if a.cmd == "logs":
            return service.logs(cfg, a.n, a.follow)
    except (service.Fail, FileNotFoundError) as e:
        print(f"claude-tg: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
