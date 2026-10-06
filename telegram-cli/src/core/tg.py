"""Telethon boundary: import, connect, raw TL requests, error translation. Tests patch this module."""
import os

from .. import VERSION
from . import config
from .errors import Cannot, CliError, UsageError

FLOOD_SLEEP = 30  # FloodWait up to this many seconds is slept through; longer -> exit 1


def telethon():
    try:
        import telethon.sync  # noqa: F401  (makes client methods synchronous)
        import telethon as t
    except ImportError:
        raise UsageError("Telethon is not installed - run: tg-cli deps") from None
    return t


def connect(cfg, account, need_auth=True):
    t = telethon()
    api_id, api_hash = config.api_creds(cfg)
    path = config.session_path(account)
    if need_auth and not path.exists():
        raise UsageError(f"account {account!r} is not logged in on this machine - a person runs, in a terminal: "
                         f"tg-cli --account {account} login (known: {', '.join(config.accounts()) or 'none'})")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    client = t.TelegramClient(str(path.with_suffix("")), api_id, api_hash, device_model="tg-cli",
                              app_version=VERSION, flood_sleep_threshold=FLOOD_SLEEP)
    client.parse_mode = None  # text goes out exactly as given; --markdown opts in
    client.connect()
    if path.exists():
        os.chmod(path, 0o600)  # the session file IS full account access
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
