"""systemd unit (Linux): install / uninstall / status / logs; plus doctor and setup.

Two modes. system = /etc/systemd/system unit with User=, root-only token copy (needs sudo).
user = ~/.config/systemd/user unit, LoadCredential straight from the user's token file (no sudo;
needs linger to survive logout). Commands other than install follow whichever unit file exists."""
import getpass
import grp
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

from . import config, runner
from .botapi import Bot, TgError

UNIT_PATH = Path(f"/etc/systemd/system/{config.SERVICE}.service")
USER_UNIT_PATH = Path(f"~/.config/systemd/user/{config.SERVICE}.service").expanduser()
ENTRY = Path(os.path.abspath(__file__)).parents[1] / "claude-tg.py"  # abspath: keep the skill's own path

UNIT = """[Unit]
Description=claude-tg: Telegram bot bridge to Claude Code
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={group}
WorkingDirectory={home}
Environment=HOME={home}
Environment=PATH={path}
Environment=PYTHONUNBUFFERED=1
LoadCredential=token:{token}
ExecStart={python} {entry} run
Restart=always
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
"""

USER_UNIT = """[Unit]
Description=claude-tg: Telegram bot bridge to Claude Code (user unit)

[Service]
Type=simple
WorkingDirectory=%h
Environment=PATH={path}
Environment=PYTHONUNBUFFERED=1
LoadCredential=token:{token}
ExecStart={python} {entry} run
Restart=always
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=default.target
"""


class Fail(Exception):
    pass


def _sudo(argv, **kw):
    cmd = argv if os.geteuid() == 0 else ["sudo", *argv]
    return subprocess.run(cmd, check=True, **kw)


def _user_env():
    env = dict(os.environ)
    run_dir = f"/run/user/{os.getuid()}"
    if not env.get("XDG_RUNTIME_DIR") and os.path.isdir(run_dir):  # agent / su shells lack it
        env["XDG_RUNTIME_DIR"] = run_dir
    return env


def _ctl(mode, *args, check=True):
    """systemctl for the given mode: sudo for system, --user (no sudo) for user."""
    if mode == "user":
        return subprocess.run(["systemctl", "--user", *args], check=check, env=_user_env())
    if check:
        return _sudo(["systemctl", *args])
    return subprocess.run((["sudo"] if os.geteuid() else []) + ["systemctl", *args])


def can_sudo() -> bool:
    if os.geteuid() == 0:
        return True
    if not shutil.which("sudo"):
        return False
    return subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0


def _system_unit_mine() -> bool:
    """The system unit is per host, not per user: another user's bot (User=<them>) is not ours."""
    try:
        text = UNIT_PATH.read_text()
    except OSError:
        return False
    return f"User={getpass.getuser()}" in text.splitlines()


def installed_mode():
    """'user' if the user unit file exists, else 'system' if the system one runs as us, else None."""
    if USER_UNIT_PATH.exists():
        return "user"
    return "system" if _system_unit_mine() else None


def pick_mode(force=None) -> str:
    """install: forced flag > mode of the existing unit > system if sudo works without a prompt > user."""
    have = installed_mode()
    if force and have and force != have:
        raise Fail(f"a {have} unit is installed; `claude-tg uninstall` first (two pollers on one token = 409)")
    mode = force or have or ("system" if can_sudo() else "user")
    if mode == "system" and not have and UNIT_PATH.exists():
        raise Fail(f"{UNIT_PATH} belongs to another user's bot; use `claude-tg install --user`")
    return mode


def linger() -> str:
    """'yes' | 'no' | '?' from logind for the current user."""
    try:
        out = subprocess.run(["loginctl", "show-user", getpass.getuser(), "-p", "Linger", "--value"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "?"
    return out or "?"


def linger_hint() -> str:
    return f"linger off: the bot stops at logout -> ask the admin: sudo loginctl enable-linger {getpass.getuser()}"


def _linux():
    if sys.platform != "linux" or not shutil.which("systemctl"):
        raise Fail("install/uninstall/status/logs need Linux + systemd (macOS launchd is out of scope; "
                   "use `claude-tg run` in tmux there)")


def unit_text(cfg, mode="system") -> str:
    home = str(Path.home())
    claude_dir = os.path.dirname(config.claude_bin(cfg)) or "/usr/local/bin"
    path = []
    for d in (f"{home}/.local/bin", claude_dir, "/usr/local/bin", "/usr/bin", "/bin"):
        if d not in path:
            path.append(d)
    if mode == "user":
        token = str(Path(cfg["token_file"]).expanduser().resolve()).replace("%", "%%")
        return USER_UNIT.format(path=":".join(path), token=token, python=sys.executable, entry=ENTRY)
    return UNIT.format(user=getpass.getuser(), group=grp.getgrgid(os.getgid()).gr_name, home=home,
                       path=":".join(path), token=config.SYSTEM_TOKEN, python=sys.executable, entry=ENTRY)


def install(cfg, force=None):
    _linux()
    token = Path(cfg["token_file"]).expanduser()
    if not token.exists():
        raise Fail(f"{token} missing: run `claude-tg setup` first")
    mode = pick_mode(force)
    if mode == "user":
        USER_UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        USER_UNIT_PATH.write_text(unit_text(cfg, "user"))
    else:
        # root-only copy for LoadCredential; the service reads it via $CREDENTIALS_DIRECTORY
        _sudo(["install", "-D", "-m", "600", "-o", "root", "-g", "root", str(token), str(config.SYSTEM_TOKEN)])
        _sudo(["tee", str(UNIT_PATH)], input=unit_text(cfg), text=True, stdout=subprocess.DEVNULL)
    _ctl(mode, "daemon-reload")
    _ctl(mode, "enable", config.SERVICE)
    if not wait_idle(600):
        print("# still busy after 600 s: unit updated, not restarted - `claude-tg restart` later", file=sys.stderr)
        return 1
    _ctl(mode, "restart", config.SERVICE)
    if mode == "user":
        print(f"# installed user unit {USER_UNIT_PATH}; token read from {token} via LoadCredential", file=sys.stderr)
        if linger() != "yes":
            print(f"# {linger_hint()}", file=sys.stderr)
    else:
        print(f"# installed {UNIT_PATH}; token copied to {config.SYSTEM_TOKEN} (root, 600)", file=sys.stderr)
    print(f"# logs: claude-tg logs -f   (after a token change: claude-tg install again)", file=sys.stderr)


def uninstall(cfg):
    _linux()
    mode = installed_mode()
    if mode is None:
        raise Fail("no claude-tg unit installed")
    _ctl(mode, "disable", "--now", config.SERVICE, check=False)
    if mode == "user":
        USER_UNIT_PATH.unlink()
    else:
        _sudo(["rm", "-f", str(UNIT_PATH), str(config.SYSTEM_TOKEN)])
        _sudo(["rmdir", "--ignore-fail-on-non-empty", str(config.SYSTEM_TOKEN.parent)])
    _ctl(mode, "daemon-reload")
    print(f"# removed {mode} unit; state kept in {config.STATE_DIR}", file=sys.stderr)


def busy():
    """(running, queued) topic ids from the bot's pending requests in state.json."""
    try:
        pending = json.loads((config.STATE_DIR / "state.json").read_text()).get("pending", {})
    except (OSError, ValueError):
        return [], []
    run = [e["thread"] for e in pending.values() if e.get("started")]
    return run, [e["thread"] for e in pending.values() if not e.get("started")]


def live_runs():
    """Topic ids of claude processes the bot still runs. A run outlives its answer while background
    teammates work, and its pending entry is gone by then: busy() alone would let a restart kill them."""
    mode = installed_mode() or "system"
    argv = ["systemctl"] + (["--user"] if mode == "user" else []) + ["show", "-p", "MainPID", "--value", config.SERVICE]
    main = subprocess.run(argv, capture_output=True, text=True, env=_user_env()).stdout.strip()
    if not main or main == "0":
        return []
    topics = []
    for d in Path("/proc").iterdir():
        try:
            if not d.name.isdigit() or (d / "stat").read_text().rsplit(")", 1)[1].split()[1] != main:
                continue
            env = dict(kv.split("=", 1) for kv in (d / "environ").read_bytes().decode(errors="replace").split("\0") if "=" in kv)
        except (OSError, IndexError):
            continue
        if config.RUN_TOPIC_ENV in env:
            topics.append(env[config.RUN_TOPIC_ENV])
    return topics


def wait_idle(timeout: int) -> bool:
    end = time.monotonic() + timeout
    said = False
    while True:
        run, queued = busy()
        run = run + [t for t in live_runs() if t not in map(str, run)]
        if not run and not queued:
            return True
        if time.monotonic() >= end:
            return False
        if not said:
            print(f"# waiting for {len(run)} run(s) / {len(queued)} queued to finish (topics {sorted(set(run + queued))})",
                  file=sys.stderr)
            said = True
        time.sleep(2)


def restart(cfg, wait: int, report=None):
    """Restart only when idle. A cut run is re-run on start anyway, but its partial work may repeat."""
    _linux()
    topic = os.environ.get(config.RUN_TOPIC_ENV)
    if wait is not None and topic:
        # called from a bot run: waiting here would wait for that very run (deadlock until --wait expires).
        # Hand off to a detached waiter that restarts once this run has answered and the bot is idle,
        # then reports the outcome into the topic (the run that asked is gone by then).
        argv = [sys.executable, str(Path(__file__).resolve().parents[1] / "claude-tg.py"), "restart",
                "--wait", str(max(wait, 3600)), "--report", topic]
        logf = config.STATE_DIR / "restart.log"
        # the waiter must leave the service cgroup: KillMode=control-group would kill it with the old bot
        keep = [f"--setenv={k}={v}" for k, v in os.environ.items() if k.startswith("CLAUDE_TG_") and k != config.RUN_TOPIC_ENV]
        scoped = subprocess.run(["systemd-run", "--user", "--collect", "--quiet", f"--unit=claude-tg-restart-{os.getpid()}",
                                 f"-pStandardOutput=append:{logf}", f"-pStandardError=append:{logf}", *keep, *argv],
                                env=_user_env(), capture_output=True, text=True)
        if scoped.returncode:  # no user manager: the restart still happens, only the report may be lost
            env = {k: v for k, v in os.environ.items() if k != config.RUN_TOPIC_ENV}
            log = open(logf, "a")
            subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        print(f"# called from bot topic {topic}: restart deferred until this run answers and the bot is idle; "
              f"the outcome is posted to the topic (log: {config.STATE_DIR / 'restart.log'})", file=sys.stderr)
        return 0
    if wait is not None and not wait_idle(wait):
        if report:
            _report(cfg, report, "restart_busy", s=wait)
        raise Fail(f"still busy after {wait} s; `claude-tg restart --now` cuts the runs (they re-run after restart)")
    mode = installed_mode() or "system"
    _ctl(mode, "restart", config.SERVICE)
    print("# restarted", file=sys.stderr)
    if report:
        time.sleep(10)  # a crash on import / config shows up as failed or activating (auto-restart) by now
        argv = ["systemctl"] + (["--user"] if mode == "user" else []) + ["is-active", config.SERVICE]
        state = subprocess.run(argv, capture_output=True, text=True, env=_user_env()).stdout.strip()
        rev = _revision()
        _report(cfg, report, "restart_ok" if state == "active" else "restart_down", rev=rev, state=state)
    return 0


def _revision():
    """'<short sha> <subject>' of the running code: git in a dev clone, else the skilltap lock commit."""
    git = lambda d, *a: subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True).stdout.strip()
    here = Path(__file__).resolve().parents[1]
    if rev := git(here, "log", "-1", "--format=%h %s"):
        return rev
    try:  # skilltap install: ~/.claude/skills/<name> is a plain copy, the lock records its source commit
        lock = json.loads((here.parents[1] / "skilltap" / "lock.json").read_text())
        entry = lock.get("skills", lock)[here.name]
        src = here.parents[1] / "skilltap" / "sources" / entry["source"]
        return git(src, "log", "-1", "--format=%h %s", entry["commit"]) or entry["commit"][:7]
    except (OSError, ValueError, KeyError, TypeError):
        return "?"


def _report(cfg, topic, key, **kw):
    """Post a restart outcome into the topic that asked for it (works even if the bot itself is down)."""
    from . import ui
    st = config.STATE_DIR / "state.json"
    try:
        owner = cfg.get("owner_id") or json.loads(st.read_text()).get("owner_id")
        Bot(config.read_token(cfg)).call("sendMessage", chat_id=owner, message_thread_id=int(topic),
                                         text=ui.t(ui.lang(cfg), key, **kw))
    except (OSError, ValueError, TgError) as e:
        print(f"# restart report to topic {topic} failed: {e}", file=sys.stderr)


def status(cfg):
    _linux()
    if installed_mode() == "user":
        argv = ["systemctl", "--user", "status", "--no-pager", "-n", "0", config.SERVICE]
    else:
        argv = ["systemctl", "status", "--no-pager", "-n", "0", config.SERVICE]
    rc = subprocess.run(argv, env=_user_env()).returncode
    run, queued = busy()
    run = run + [t for t in live_runs() if t not in map(str, run)]
    print(f"runs in flight: {len(run)}{f' (topics {sorted(run)})' if run else ''}; queued: {len(queued)}")
    return rc


def logs(cfg, n: int, follow: bool):
    _linux()
    if installed_mode() == "user":  # own user journal: readable without adm / systemd-journal
        argv = ["journalctl", "--user", "-u", config.SERVICE, "-n", str(n), "--no-pager"] + (["-f"] if follow else [])
        return subprocess.run(argv, env=_user_env()).returncode
    argv = ["journalctl", "-u", config.SERVICE, "-n", str(n), "--no-pager"] + (["-f"] if follow else [])
    rc = subprocess.run(argv).returncode
    if rc:  # not in systemd-journal / adm group
        rc = subprocess.run(["sudo", "-n", *argv]).returncode
    return rc


def doctor(cfg) -> int:
    rows, bad = [], 0

    def row(check, ok, detail=""):
        nonlocal bad
        bad += not ok
        rows.append(f"{check}\t{'ok' if ok else 'FAIL'}\t{detail}")

    tf = Path(cfg["token_file"]).expanduser()
    token = None
    if tf.exists():
        mode = stat.S_IMODE(tf.stat().st_mode)
        row("token_file", mode & 0o077 == 0, f"{tf} mode {oct(mode)}" + ("" if mode & 0o077 == 0 else " -> chmod 600"))
        token = tf.read_text().strip()
    else:
        row("token_file", False, f"{tf} missing -> claude-tg setup")
    if token:
        try:
            me = Bot(token).call("getMe", _retries=0, _timeout=15)
            row("getMe", True, "@" + me.get("username", "?"))
            row("threaded_mode", bool(me.get("has_topics_enabled")),
                "on" if me.get("has_topics_enabled") else "off -> @BotFather: Bot Settings -> Threads Settings")
        except TgError as e:
            row("getMe", False, e.description)
    cb = config.claude_bin(cfg)
    row("claude", bool(shutil.which(cb) or os.path.exists(cb)), cb)
    mc = config.model_cli_bin()
    row("model-cli (voice, optional)", True, " ".join(mc) if mc else "missing: voice notes get an install hint")
    row("ffmpeg (voice, optional)", True, shutil.which("ffmpeg") or "missing: ogg sent as-is")
    for f in cfg["env_files"]:
        row("env_file", Path(f).expanduser().exists(), f)
    pm = cfg.get("permission_mode") or "bypass"
    args = cfg.get("claude_args") or []
    model = args[args.index("--model") + 1] if "--model" in args[:-1] else ""
    if pm not in runner.PERMISSION_MODES:
        row("permission_mode", False, f"{pm!r} unknown -> one of {', '.join(runner.PERMISSION_MODES)}")
    elif pm == "auto" and "haiku" in model.lower():
        rows.append(f"permission_mode\tWARN\tauto on {model}: haiku silently falls back to default (no prompts headless)")
    else:
        row("permission_mode", True, pm)
    if cfg.get("protected_paths"):
        from . import guard
        row("leak_filter", True, guard.from_config(cfg).stats())
    st = config.STATE_DIR / "state.json"
    owner = cfg.get("owner_id") or (json.loads(st.read_text()).get("owner_id") if st.exists() else None)
    if owner and not str(owner).lstrip("-").isdigit():
        row("owner", False, f"{owner!r} is not a numeric Telegram user id: the bot ignores everyone")
    else:
        row("owner", True, str(owner) if owner else "not yet: first private-chat user becomes owner")
    if sys.platform == "linux" and shutil.which("systemctl"):
        mode = installed_mode()
        would = mode or pick_mode()
        argv = ["systemctl"] + (["--user"] if mode == "user" else []) + ["is-active", config.SERVICE]
        active = subprocess.run(argv, capture_output=True, text=True, env=_user_env()).stdout.strip()
        row("service", active == "active" or not mode,
            f"{active} ({mode} unit)" if mode else f"not installed; install would use the {would} unit")
        if would == "user":
            lg = linger()
            row("linger", lg == "yes", "yes" if lg == "yes" else linger_hint())
    print("check\tstatus\tdetail")
    print("\n".join(rows))
    return 1 if bad else 0


SETUP = """claude-tg setup
1. Telegram -> @BotFather -> /newbot -> name + username -> copy the token.
2. @BotFather -> open the Mini App (Open button) -> your bot -> Bot Settings -> Threads Settings ->
   turn Threaded Mode on (topics in the private chat; users may create topics).
3. Token file: {tf} (chmod 600). Enter the token below, or pipe it: `... | claude-tg setup --token-stdin`.
4. claude-tg doctor   -> everything ok
5. claude-tg install  -> systemd service (Linux; system unit if sudo works, else user unit); or `claude-tg run`
6. Message the bot first: the first private-chat user becomes its only owner.
"""


def setup(cfg, token_stdin: bool):
    tf = Path(cfg["token_file"]).expanduser()
    print(SETUP.format(tf=tf), file=sys.stderr)
    if token_stdin:
        token = sys.stdin.read().strip()
    elif sys.stdin.isatty():
        token = getpass.getpass("bot token (empty = keep current): ").strip()
    else:
        token = ""
    if not token:
        return 0
    if ":" not in token:
        raise Fail("that does not look like a bot token (<digits>:<secret>)")
    tf.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(tf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    os.chmod(tf, 0o600)
    print(f"# saved {tf} (600); next: claude-tg doctor", file=sys.stderr)
    return 0
