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
  claude-tg doctor           # token, getMe, Threaded Mode, claude, model-cli
  claude-tg install          # systemd unit (system if sudo works, else user unit), starts it
  claude-tg restart          # waits until no run is active, then restarts (use after deploys)
  claude-tg logs -f          # journalctl -u claude-tg
  claude-tg run              # foreground (debugging); only one poller per token
  echo done | claude-tg notify       # bot -> owner, topic "Notifications" (scripts, scheduled jobs)
  claude-tg notify --file out.mp4 "demo"   # file -> owner; inside a bot run: into that run's topic
  claude-tg profile --name "Helper" --photo me.png   # bot's own name / about / avatar (no args: show)
  claude-tg local-api status # local Bot API server for attachments > 20 MB (optional)
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
    s = sub.add_parser("setup", help="BotFather steps + save the token file")
    s.add_argument("--token-stdin", action="store_true", help="read the token from stdin (never pass it in argv)")
    sub.add_parser("doctor", help="check token, bot, Threaded Mode, claude, voice deps, service")
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
    s.add_argument("text", nargs="*", help="message text (default: stdin)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--html", action="store_true", help="text is Telegram HTML")
    g.add_argument("--markdown", "--md", action="store_true", help="text is markdown (converted like bot answers)")
    s.add_argument("--silent", action="store_true", help="no sound / vibration")
    s.add_argument("--file", action="append", metavar="PATH",
                   help="send a file (repeatable; <= 50 MB): mp4/mov/m4v as streaming video, jpg/png/webp as photo, "
                        "else as document")
    s.add_argument("--button", action="append", metavar="TEXT=URL",
                   help="inline URL button under the message (repeatable, one per row)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--topic", metavar="KEY",
                   help="config notify_topics key, else a literal topic name (default: own topic inside a bot run, "
                        "else Notifications)")
    g.add_argument("--thread", type=int, metavar="ID", help="send into this topic (message_thread_id)")
    g.add_argument("--main-chat", action="store_true", help="send to All messages instead of a topic")
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
                                   "references rbw:NAME | env:NAME | cred:NAME (default rbw:TELEGRAM_API_ID / "
                                   "rbw:TELEGRAM_API_HASH), local_api_bin. Setup: references/setup.md.")
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
