"""Telethon boundary: import, connect, raw TL requests, error translation. Tests patch this module."""
import os
import sys
import time

from .. import VERSION
from . import config
from .errors import Cannot, CliError, UsageError

FLOOD_SLEEP = 30  # FloodWait up to this many seconds is slept through; longer -> exit 1
LOCK_TIMEOUT = 300  # s to wait for another process using the same account; env TG_CLI_LOCK_TIMEOUT overrides
BUSY_TIMEOUT_MS = 30000  # sqlite busy_timeout on the session db: backstop for brief foreign writes

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    try:
        import msvcrt
    except ImportError:
        msvcrt = None


def telethon():
    try:
        import telethon.sync  # noqa: F401  (makes client methods synchronous)
        import telethon as t
    except ImportError:
        raise UsageError("Telethon is not installed - run: tg-cli deps") from None
    return t


# ---- per-account inter-process lock ------------------------------------------
# Telethon's SQLite session keeps a write transaction open while the client runs, so a second process on the
# same account dies with "database is locked" (and two live clients on one auth key are unsafe anyway). Every
# connect() takes an exclusive flock on <session>.lock first and holds it until client.disconnect() or process
# exit; other users of the account wait (bounded) instead of crashing. Re-entrant within one process.

_held = {}  # lock path -> [fd, refcount]


def _try_lock(fd):
    if fcntl:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
    if msvcrt:  # lock one byte far past the pid text so other processes can still read the holder
        os.lseek(fd, 1 << 20, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    return True  # no locking primitive: degrade to the old behavior (sqlite "locked" -> clear exit 1)


def _holder(lock):
    try:
        with open(lock, encoding="utf-8", errors="replace") as f:
            return f.read(200).strip()
    except OSError:
        return ""


def lock_account(path, timeout=None):
    """Take the account lock for session file `path`; wait up to `timeout` s (None: env / LOCK_TIMEOUT)."""
    lock = str(path) + ".lock"
    if lock in _held:
        _held[lock][1] += 1
        return lock
    if timeout is None:
        try:
            timeout = float(os.environ.get("TG_CLI_LOCK_TIMEOUT") or LOCK_TIMEOUT)
        except ValueError:
            raise UsageError("TG_CLI_LOCK_TIMEOUT must be a number of seconds") from None
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    while not _try_lock(fd):
        if time.monotonic() >= deadline:
            os.close(fd)
            who = _holder(lock)
            raise CliError(f"account session {path.stem!r} is busy: another process holds {lock}"
                           f"{f' (pid {who})' if who else ''} for over {timeout:g} s - wait for it to finish or "
                           f"raise TG_CLI_LOCK_TIMEOUT")
        time.sleep(0.2)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()} {os.path.basename(sys.argv[0] or 'python')} since "
                 f"{time.strftime('%Y-%m-%d %H:%M:%S')}".ljust(120).encode())
    _held[lock] = [fd, 1]
    return lock


def unlock_account(lock):
    entry = _held.get(lock)
    if not entry:
        return
    entry[1] -= 1
    if entry[1] <= 0:
        del _held[lock]
        os.close(entry[0])  # closing the fd drops flock / msvcrt lock


def _busy_timeout(client):
    conn = getattr(getattr(client, "session", None), "_conn", None)  # Telethon SQLiteSession internals
    if conn is not None:
        try:
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        except Exception:  # noqa: BLE001  (backstop only; never fail connect over it)
            pass


def connect(cfg, account, need_auth=True, lock_timeout=None):
    """Connected TelegramClient for `account`. Holds the account lock until client.disconnect() / process exit."""
    t = telethon()
    api_id, api_hash = config.api_creds(cfg)
    path = config.session_path(account)
    if need_auth and not path.exists():
        raise UsageError(f"account {account!r} is not logged in on this machine - a person runs, in a terminal: "
                         f"tg-cli --account {account} login (known: {', '.join(config.accounts()) or 'none'})")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    lock = lock_account(path, lock_timeout)
    held = [True]

    def release():
        if held[0]:
            held[0] = False
            unlock_account(lock)
    try:
        client = t.TelegramClient(str(path.with_suffix("")), api_id, api_hash, device_model="tg-cli",
                                  app_version=VERSION, flood_sleep_threshold=FLOOD_SLEEP)
        _busy_timeout(client)
        client.parse_mode = None  # text goes out exactly as given; --markdown opts in
        original = client.disconnect

        def disconnect(*a, **k):
            try:
                return original(*a, **k)
            finally:
                release()
        client.disconnect = disconnect  # Telethon's log_out() calls self.disconnect() too
        client.connect()
        if path.exists():
            os.chmod(path, 0o600)  # the session file IS full account access
    except BaseException:
        release()
        raise
    if need_auth and not client.is_user_authorized():
        client.disconnect()
        raise UsageError(f"account {account!r}: session is no longer authorized (revoked or expired) - "
                         f"run: tg-cli --account {account} login")
    return client


def run(client, coro):
    """Await a coroutine that telethon.sync does not wrap (QRLogin.wait/recreate)."""
    return client.loop.run_until_complete(coro)


# ---- raw TL requests (no high-level wrapper in Telethon) ---------------------

def contacts(client):
    from telethon.tl.functions.contacts import GetContactsRequest
    return client(GetContactsRequest(hash=0)).users


def search_peers(client, q, limit):
    """contacts.search -> Found(my_results, results, chats, users)."""
    from telethon.tl.functions.contacts import SearchRequest
    return client(SearchRequest(q=q, limit=limit))


def resolve_username(client, name):
    """Entity for @name, or None when the username does not exist."""
    from telethon import errors
    try:
        return client.get_entity(name)
    except (ValueError, errors.UsernameNotOccupiedError, errors.UsernameInvalidError):
        return None


def dialog_filters(client):
    """messages.getDialogFilters -> list of DialogFilter / DialogFilterChatlist / DialogFilterDefault."""
    from telethon.tl.functions.messages import GetDialogFiltersRequest
    res = client(GetDialogFiltersRequest())
    return getattr(res, "filters", res)  # layer >=176 wraps them in messages.DialogFilters


def notify_defaults(client):
    """account.getNotifySettings per peer type -> {"users"|"chats"|"broadcasts": mute_until}. A dialog whose own
    mute_until is unset inherits these (Telegram's default: groups and channels muted, private chats not)."""
    from telethon.tl.functions.account import GetNotifySettingsRequest
    from telethon.tl.types import InputNotifyBroadcasts, InputNotifyChats, InputNotifyUsers
    return {k: client(GetNotifySettingsRequest(p)).mute_until for k, p in
            (("users", InputNotifyUsers()), ("chats", InputNotifyChats()), ("broadcasts", InputNotifyBroadcasts()))}


def posts_flood(client, query):
    """channels.checkSearchPostsFlood -> SearchPostsFlood(total_daily, remains, stars_amount, query_is_free, wait_till)."""
    from telethon.tl.functions.channels import CheckSearchPostsFloodRequest
    return client(CheckSearchPostsFloodRequest(query=query))


def search_posts(client, query, hashtag, limit):
    """channels.searchPosts over all public channels. Never passes allow_paid_stars."""
    from telethon.tl.functions.channels import SearchPostsRequest
    from telethon.tl.types import InputPeerEmpty
    return client(SearchPostsRequest(offset_rate=0, offset_peer=InputPeerEmpty(), offset_id=0, limit=limit,
                                     hashtag=hashtag, query=query))


def delete_scheduled(client, chat, ids):
    """messages.deleteScheduledMessages: cancel scheduled (not yet delivered) messages of one chat."""
    from telethon.tl.functions.messages import DeleteScheduledMessagesRequest
    return client(DeleteScheduledMessagesRequest(peer=client.get_input_entity(chat), id=list(ids)))


_FILTERS = {"document": "InputMessagesFilterDocument", "photo": "InputMessagesFilterPhotos",
            "video": "InputMessagesFilterVideo", "voice": "InputMessagesFilterVoice",
            "audio": "InputMessagesFilterMusic", "round": "InputMessagesFilterRoundVideo",
            "gif": "InputMessagesFilterGif"}


def media_filter(kind):
    """Server-side messages.search filter class for one media kind, or None (sticker: no such filter)."""
    if kind not in _FILTERS:
        return None
    from telethon.tl import types
    return getattr(types, _FILTERS[kind])


# ---- errors -----------------------------------------------------------------

def translate(exc):
    """Telethon exception -> CliError, or None when it is not a Telegram error (then it is our bug)."""
    try:
        from telethon import errors
    except ImportError:
        return None
    if isinstance(exc, errors.FloodWaitError):
        return CliError(f"Telegram rate limit: retry in {exc.seconds} s (FLOOD_WAIT). Do not loop - wait it out.")
    if isinstance(exc, errors.RPCError):
        msg = getattr(exc, "message", "") or type(exc).__name__
        if "PREMIUM" in msg.upper():
            return Cannot(f"Telegram: {msg} - this needs a Telegram Premium account")
        return CliError(f"Telegram: {msg} ({type(exc).__name__})")
    if type(exc).__name__ == "OperationalError" and "locked" in str(exc):  # sqlite3: session file in use
        return CliError("this account's session is in use by another tg-cli/Telethon process (one at a time per "
                        "account) - wait for it to finish, then retry")
    if isinstance(exc, ConnectionError):
        return CliError(f"cannot reach Telegram: {exc}")
    return None
