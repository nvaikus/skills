"""neonize boundary: import, logging, account lock, connect/session lifecycle, JID strings, error
translation. Methods return plain dicts/strings; only events carry raw protos (api/normalize.py reads
them duck-typed). Tests patch `connect`."""
import logging
import os
import queue
import sys
import threading
import time

from . import config
from .errors import CliError, UsageError

CONNECT_TIMEOUT = 30  # s to the Connected event
LOCK_WAIT = 20        # s to wait for another wa-cli on the same account
OFFLINE_GRACE = 8     # s of silence that ends a drain when the server never says "offline sync done"
DATA = ("message", "history", "group_info", "joined_group")  # events that change the store
FATAL = ("logged_out", "temp_ban", "connect_failure", "replaced", "outdated", "error", "stopped")


def norm_ts(v):
    """Unix seconds from seconds or milliseconds (neonize is not uniform); 0/None -> None."""
    if not v:
        return None
    v = int(v)
    return v // 1000 if v > 10 ** 11 else v


def jid_str(j):
    """JID proto -> 'user@server' (device part dropped); empty -> None."""
    if j is None or not getattr(j, "Server", ""):
        return None
    return f"{j.User}@{j.Server}" if j.User else j.Server


def _logging(account):
    """neonize calls logging.basicConfig(INFO) on import: claim the root logger first, into a file."""
    path = config.log_path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if not any(getattr(h, "_wa_cli", False) for h in root.handlers):
        for h in list(root.handlers):
            root.removeHandler(h)
        h = logging.FileHandler(path, encoding="utf-8")
        h._wa_cli = True
        h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        root.addHandler(h)
    root.setLevel(logging.WARNING)
    logging.getLogger("neonize.utils.log").setLevel(logging.WARNING)  # also sets the Go-side log level


class Quiet:
    """While connected, fds 1/2 go to the account log: the Go lib writes there directly ('Login event: ...',
    'Press Ctrl+C to exit'). sys.stdout/sys.stderr move to duplicates of the real fds, so wa-cli's own output
    (data, '# ' notes, the QR) still reaches the terminal. A stream that is not on fd 1/2 (tests) is left alone."""

    def __init__(self, log_path):
        self.log_path, self.saved = log_path, []

    def start(self):
        if self.saved:
            return
        log = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            for fd, name in ((1, "stdout"), (2, "stderr")):
                old = getattr(sys, name)
                old.flush()
                real = os.dup(fd)
                swap = None
                try:
                    if old.fileno() == fd:
                        swap = open(real, "w", encoding="utf-8", errors=getattr(old, "errors", None) or "strict",
                                    newline="\n", closefd=False, buffering=1 if fd == 2 else -1)
                        setattr(sys, name, swap)
                except (AttributeError, OSError, ValueError):  # not a real file (StringIO)
                    pass
                os.dup2(log, fd)
                self.saved.append((fd, name, real, old, swap))
        finally:
            os.close(log)

    def stop(self):
        while self.saved:
            fd, name, real, old, swap = self.saved.pop()
            if swap is not None:
                try:
                    swap.flush()
                except (OSError, ValueError):
                    pass
                if getattr(sys, name) is swap:
                    setattr(sys, name, old)
            os.dup2(real, fd)
            os.close(real)


def _mute(nc):
    """neonize prints every login status (a bare number) to stdout: log it instead."""
    def status(self, uuid, status):
        logging.getLogger("neonize").info("login status %s", status)
    if hasattr(nc.NewClient, "_NewClient__onLoginStatus"):
        nc.NewClient._NewClient__onLoginStatus = status


def neonize():
    if sys.version_info < (3, 10):
        raise UsageError(f"neonize needs Python 3.10+, this is {sys.version.split()[0]} - install a newer python3, "
                         "then: wa-cli deps")
    try:
        import neonize.client as nc
    except ImportError as e:
        if "magic" in str(e):
            raise UsageError("libmagic is missing (neonize needs it) - macOS: brew install libmagic · "
                             "Debian/Ubuntu: sudo apt install libmagic1; then retry") from None
        raise UsageError(f"neonize is not installed ({e}) - run: wa-cli deps") from None
    _mute(nc)
    return nc


def to_jid(s):
    from neonize.proto.Neonize_pb2 import JID
    user, _, server = s.rpartition("@")
    return JID(User=user, Server=server, Device=0, RawAgent=0, Integrator=0, IsEmpty=False)


def _enum(msg, field):
    v = getattr(msg, field)
    ev = type(msg).DESCRIPTOR.fields_by_name[field].enum_type.values_by_number.get(v)
    return ev.name.lower() if ev else str(v)


class _Lock:
    """One connection per account: two would kick each other off (StreamReplaced)."""

    def __init__(self, account):
        self.f = None
        try:
            import fcntl
        except ImportError:  # Windows: no lock; never run two wa-cli on one account at once
            return
        path = config.account_dir(account) / "lock"
        self.f = open(path, "w")
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if time.monotonic() > deadline:
                    self.f.close()
                    raise CliError(f"account {account!r} is busy: another wa-cli is connected with it for over "
                                   f"{LOCK_WAIT} s (a running `sync`?) - retry when it ends") from None
                time.sleep(0.3)

    def release(self):
        if self.f:
            self.f.close()
            self.f = None


def connect(cfg, account, need_auth=True):
    path = config.session_path(account)
    if need_auth and not path.exists():
        raise UsageError(f"account {account!r} is not logged in on this machine - a person runs, in a terminal: "
                         f"wa-cli --account {account} login (known: {', '.join(config.accounts()) or 'none'})")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    lock = _Lock(account)
    quiet = Quiet(config.log_path(account))
    try:
        _logging(account)
        quiet.start()
        nc = neonize()
        from neonize import events as ev
        from neonize.proto.waCompanionReg.WAWebProtobufsCompanionReg_pb2 import DeviceProps
        props = DeviceProps(os="wa-cli", platformType=DeviceProps.CHROME)
        client = nc.NewClient(str(path), uuid=account, props=props)
    except BaseException:
        quiet.stop()
        lock.release()
        raise
    s = Session(client, lock, account, need_auth, quiet)
    kinds = {ev.ConnectedEv: "connected", ev.MessageEv: "message", ev.HistorySyncEv: "history",
             ev.OfflineSyncCompletedEv: "offline_done", ev.LoggedOutEv: "logged_out", ev.TemporaryBanEv: "temp_ban",
             ev.ConnectFailureEv: "connect_failure", ev.PairStatusEv: "pair", ev.StreamReplacedEv: "replaced",
             ev.ClientOutdatedEv: "outdated", ev.GroupInfoEv: "group_info", ev.JoinedGroupEv: "joined_group"}
    for cls, kind in kinds.items():
        client.event(cls)(lambda _c, e, k=kind: s.q.put((k, e)))
    client.event.qr(lambda _c, data: s.q.put(("qr", data)))
    s.start()
    if path.exists():
        os.chmod(path, 0o600)  # the session file IS full account access
    if need_auth:
        try:
            s.wait_connected()
        except BaseException:
            s.stop()  # lock + fds back before the error is printed
            raise
    return s


class Session:
    def __init__(self, client, lock, account, need_auth, quiet=None):
        self.client, self.lock, self.account, self.need_auth, self.quiet = client, lock, account, need_auth, quiet
        self.q = queue.Queue()
        self.pending = []  # data events that arrived before "connected"
        self.thread = None

    def start(self):
        def run():
            try:
                self.client.connect()
            except BaseException as e:  # noqa: BLE001  surfaced on the main thread
                self.q.put(("error", e))
            finally:
                self.q.put(("stopped", None))
        self.thread = threading.Thread(target=run, name=f"wa-{self.account}", daemon=True)
        self.thread.start()

    # ---- event flow -----------------------------------------------------------
    def fatal(self, kind, e):
        a = self.account
        if kind == "error":
            return translate(e) or CliError(f"WhatsApp connection failed: {e}")
        if kind == "logged_out" or (kind == "connect_failure" and _enum(e, "Reason") in ("logged_out", "main_device_gone")):
            return UsageError(f"account {a!r} was logged out (unlinked on the phone, or inactive too long) - "
                              f"run: wa-cli --account {a} login")
        if kind == "temp_ban" or (kind == "connect_failure" and _enum(e, "Reason") == "temp_banned"):
            left = f", expires in {int(e.Expire)} s" if kind == "temp_ban" and getattr(e, "Expire", 0) else ""
            return CliError(f"WhatsApp TEMPORARY BAN on account {a!r}{left}. Stop all wa-cli activity on it; "
                            "never retry in a loop.")
        if kind == "connect_failure":
            return CliError(f"WhatsApp refused the connection: {_enum(e, 'Reason')} {getattr(e, 'Message', '')}".strip())
        if kind == "replaced":
            return CliError(f"another client took over account {a!r}'s session (same session file used elsewhere?)")
        if kind == "outdated":
            return CliError("WhatsApp says this client is outdated - run: wa-cli deps --upgrade")
        return CliError("WhatsApp connection ended unexpectedly")

    def wait_connected(self, timeout=CONNECT_TIMEOUT):
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise CliError(f"cannot reach WhatsApp within {timeout} s (network?)")
            try:
                kind, e = self.q.get(timeout=min(left, 0.5))
            except queue.Empty:
                continue
            if kind == "connected":
                return
            if kind == "qr":
                raise UsageError(f"account {self.account!r} is not logged in (no paired device in its session) - "
                                 f"a person runs, in a terminal: wa-cli --account {self.account} login")
            if kind in FATAL:
                raise self.fatal(kind, e)
            if kind in DATA:
                self.pending.append((kind, e))

    def events(self, quiet=1.5, maximum=20):
        """Data events until the offline queue is drained and the stream has been quiet for `quiet` s."""
        yield from self.pending
        self.pending = []
        start = last = time.monotonic()
        done = False
        while time.monotonic() - start < maximum:
            try:
                kind, e = self.q.get(timeout=0.25)
            except queue.Empty:
                idle = time.monotonic() - last
                if idle >= (quiet if done else max(quiet, OFFLINE_GRACE)):
                    return
                continue
            last = time.monotonic()
            if kind == "offline_done":
                done = True
            elif kind in FATAL:
                raise self.fatal(kind, e)
            elif kind in DATA:
                yield kind, e

    def next_event(self, timeout):
        """(kind, event) or None on timeout - the login flow reads qr/pair/connected itself."""
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def leftovers(self):
        """Data events still queued (call after stop: nothing may be lost - the server never resends)."""
        out = []
        while True:
            try:
                kind, e = self.q.get_nowait()
            except queue.Empty:
                return out
            if kind in DATA:
                out.append((kind, e))

    def stop(self):
        if self.thread is not None:
            try:
                self.client.stop()
            except Exception:  # noqa: BLE001
                pass
            self.thread.join(10)
            self.thread = None
        if self.quiet:
            self.quiet.stop()
        self.lock.release()

    # ---- requests (main thread, while connected) --------------------------------
    def me(self):
        d = self.client.get_me()
        return {"jid": jid_str(d.JID), "phone": d.JID.User or None, "lid": jid_str(d.LID), "name": d.PushName or None,
                "platform": d.Platform or None}

    def contacts(self):
        return [{"jid": jid_str(c.JID), "full_name": c.Info.FullName, "first_name": c.Info.FirstName,
                 "push_name": c.Info.PushName, "business_name": c.Info.BusinessName}
                for c in self.client.contact.get_all_contacts()]

    def groups(self):
        return [_group(g) for g in self.client.get_joined_groups()]

    def group(self, jid):
        """Full info of a group this account is in (the invite-link preview lists only some participants)."""
        return _group(self.client.get_group_info(to_jid(jid)))

    def group_from_link(self, code):
        return _group(self.client.get_group_info_from_link(code))

    def join_link(self, code):
        return jid_str(self.client.join_group_with_link(code))

    def newsletter_by_invite(self, code):
        return _newsletter(self.client.get_newsletter_info_with_invite(code))

    def newsletter(self, jid):
        return _newsletter(self.client.get_newsletter_info(to_jid(jid)))

    def subscribed_newsletters(self):
        """Channels this account follows (whatsmeow GetSubscribedNewsletters) - the only follow signal:
        get_newsletter_info's ViewerMeta.Role reads "subscriber" for a channel the account does not follow."""
        return [_newsletter(n) for n in self.client.get_subscribed_newletters()]

    def newsletter_messages(self, jid, count):
        """-> [(server_id, views, {emoji: count}, waE2E.Message)], as the server returns them. neonize's proto has no
        timestamp (none in the raw message either, checked live 2026-10-04); ViewsCount is 0 unless the viewer is an admin (checked live, 0.5.2)."""
        return [(m.MessageServerID, m.ViewsCount, {r.type: r.count for r in m.ReactionCounts}, m.Message)
                for m in self.client.get_newsletter_messages(to_jid(jid), count, 0)]

    def on_whatsapp(self, *phones):
        return [{"query": r.Query, "jid": jid_str(r.JID), "is_in": bool(r.IsIn)}
                for r in self.client.is_on_whatsapp(*phones)]

    def send_text(self, jid, text):
        from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
        return _sent(self.client.send_message(to_jid(jid), Message(conversation=text)))  # verbatim: no @mention parsing

    def send_document(self, jid, path, caption=None):
        msg = self.client.build_document_message(path, caption=caption or None, filename=os.path.basename(path))
        return _sent(self.client.send_message(to_jid(jid), msg))

    def download(self, blob, path):
        """Stored media part (normalize.media_of) -> decrypted file at path. Read-only: no receipt, no retry request
        (whatsmeow's media retry / on-demand history sync are not exported by neonize 0.5.2).
        Fails with CliError whose .status is "expired" (gone from the media servers) or "failed"."""
        from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
        try:
            self.client.download_any(Message.FromString(blob), path)
        except Exception as e:  # noqa: BLE001
            raise download_error(e) from None

    def pair_phone(self, phone):
        from neonize.utils.enum import ClientName
        return self.client.PairPhone(phone, True, ClientName.LINUX)

    def logout(self):
        self.client.logout()


def _group(g):
    return {"jid": jid_str(g.JID), "name": g.GroupName.Name or None, "topic": g.GroupTopic.Topic or None,
            "created": norm_ts(g.GroupCreated), "owner": jid_str(g.OwnerPN) or jid_str(g.OwnerJID),
            "participants": len(g.Participants), "announce": bool(g.GroupAnnounce.IsAnnounce),
            "community": bool(g.GroupParent.IsParent), "parent": jid_str(g.GroupLinkedParent.LinkedParentJID)}


def _newsletter(n):
    t = n.ThreadMeta
    return {"jid": jid_str(n.ID), "name": t.Name.Text or None, "description": t.Description.Text or None,
            "invite": t.InviteCode or None, "subscribers": t.SubscriberCount, "verified": _enum(t, "VerificationState") == "verified",
            "created": norm_ts(t.CreationTime), "state": _enum(n.State, "Type")}


def _sent(r):
    return {"id": r.ID, "ts": norm_ts(r.Timestamp) or int(time.time()), "server_id": r.ServerID or None}


# ---- errors -------------------------------------------------------------------

RATE = ("429", "rate-overlimit", "rate limit", "too many")
NOT_FOUND = ("not valid", "invalid", "revoked", "item-not-found", "404", "not-found", "410", "gone")


EXPIRED = ("status code 404", "status code 410", "status code 403", "media not available", "no url present")


def download_error(exc):
    """whatsmeow download failure -> CliError with .status: expired (exit 2) | failed (exit 1)."""
    msg = str(exc).strip() or type(exc).__name__
    if any(k in msg.lower() for k in EXPIRED):
        err = UsageError(f"media expired on WhatsApp's servers ({msg}); only the phone can re-upload it - "
                         "save it from the phone")
        err.status = "expired"
    else:
        err = CliError(f"download failed: {msg}")
        err.status = "failed"
    return err


def translate(exc):
    """neonize exception -> CliError, or None when it is not a WhatsApp error (then it is our bug)."""
    try:
        from neonize.exc import NeonizeError
    except ImportError:
        return None
    if isinstance(exc, NeonizeError):
        msg = str(exc).strip() or type(exc).__name__
        low = msg.lower()
        if any(k in low for k in RATE):
            return CliError(f"WhatsApp rate limit: {msg}. Stop - never retry in a loop; wait and act again only on "
                            "an explicit user request.")
        if any(k in low for k in NOT_FOUND):
            return UsageError(f"WhatsApp: {msg} ({type(exc).__name__})")
        return CliError(f"WhatsApp: {msg} ({type(exc).__name__})")
    if isinstance(exc, ConnectionError):
        return CliError(f"cannot reach WhatsApp: {exc}")
    return None
