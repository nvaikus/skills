"""Contract tests with a fake WhatsApp session (no neonize needed). Run: python3 -m unittest discover -s dev/tests"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TMP = tempfile.mkdtemp(prefix="wa-cli-test-")
os.environ.update(WA_CLI_HOME=TMP, WA_CLI_CONFIG=f"{TMP}/cfg.json")
sys.path.insert(0, str(ROOT))

from src import main as main_mod  # noqa: E402
from src.api import normalize  # noqa: E402
from src.core import config, wa  # noqa: E402
from src.core.errors import CliError  # noqa: E402

T0 = int(time.time())  # "now" for the fixtures (--since is relative to the real clock)


class P:
    """Fake proto: set fields from kwargs; unset scalar fields read as ''."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return ""

    def HasField(self, f):
        return bool(self.__dict__.get(f))

    def ListFields(self):
        return [(types.SimpleNamespace(name=k), v) for k, v in self.__dict__.items() if v]


def J(jid):
    user, _, server = jid.rpartition("@")
    return P(User=user, Server=server)


ME = "351900000001@s.whatsapp.net"
SASHA1, SASHA2, IVAN = "351911111111@s.whatsapp.net", "351922222222@s.whatsapp.net", "351933333333@s.whatsapp.net"
QA = "120363000000000001@g.us"
NEWS = "120363999999999999@newsletter"


def live(chat, sender, mid, message, ts=T0, from_me=False, push="", server_id=0):
    src = P(Chat=J(chat), Sender=J(sender), IsFromMe=from_me, IsGroup=chat.endswith("@g.us"), SenderAlt=P(), RecipientAlt=P())
    return ("message", P(Info=P(MessageSource=src, ID=mid, ServerID=server_id, Pushname=push, Timestamp=ts), Message=message))


def hmsg(chat, mid, text, ts, sender=None, from_me=False, push=""):
    return P(message=P(key=P(remoteJID=chat, fromMe=from_me, ID=mid, participant=sender or ""),
                       message=P(conversation=text), messageTimestamp=ts, participant="", pushName=push))


def history_event():
    convs = [P(ID=QA, name="Команда QA", displayName="", pnJID="", lidJID="", conversationTimestamp=T0 - 60, unreadCount=2,
               messages=[hmsg(QA, "q1", "релиз завтра", T0 - 60, IVAN, push="Vanya"),
                         hmsg(QA, "q2", "x" * 300, T0 - 3600, SASHA1),
                         hmsg(QA, "q3", "старое сообщение", T0 - 86400 * 3, SASHA2)]),
             P(ID=IVAN, name="", displayName="", pnJID="", lidJID="", conversationTimestamp=T0 - 30, unreadCount=0,
               messages=[hmsg(IVAN, "i1", "hello ivan", T0 - 30, from_me=True)]),
             P(ID="status@broadcast", messages=[])]
    return ("history", P(Data=P(conversations=convs, pushnames=[P(ID="351944444444@s.whatsapp.net", pushname="Stranger")])))


def default_events():
    img = P(imageMessage=P(caption="photo cap"))
    edit = P(protocolMessage=P(type=normalize.MESSAGE_EDIT, key=P(ID="q1"), editedMessage=P(conversation="релиз послезавтра")))
    return [history_event(),
            live(IVAN, IVAN, "i2", P(ephemeralMessage=P(message=img)), T0 - 10, push="Vanya"),
            live(QA, IVAN, "q4", edit, T0 - 5),
            live(QA, SASHA1, "q5", P(conversation="oops"), T0 - 4),
            live(QA, SASHA1, "q6", P(protocolMessage=P(type=normalize.REVOKE, key=P(ID="q5"))), T0 - 3),
            live(QA, SASHA1, "q7", P(reactionMessage=P(text="👍")), T0 - 2)]


def fake_blob(m, field):
    """normalize._blob needs real protos: a fake media part carries its 'serialized' bytes in blob=."""
    return getattr(m, field).__dict__.get("blob", field.encode())


def doc(name, blob=None, mime="application/pdf"):
    return P(documentMessage=P(fileName=name, mimetype=mime, **({"blob": blob} if blob else {})))


class FakeSession:
    def __init__(self, events=None, leftovers=None):
        self.queue = list(default_events() if events is None else events)
        self.left = list(leftovers or [])
        self.sent, self.calls, self.pending = [], [], []
        self.registered = {SASHA1, SASHA2, IVAN, "351955555555@s.whatsapp.net"}
        self.fail = None
        self.member_of = set()
        self.follows = []
        self.joined = [{"jid": QA, "name": "Команда QA", "created": T0 - 999999}]

    def events(self, quiet=1.5, maximum=20):
        q, self.queue = self.queue, []
        yield from q

    def leftovers(self):
        left, self.left = self.left, []
        return left

    def stop(self):
        self.calls.append(("stop",))

    def me(self):
        return {"jid": ME, "phone": ME.split("@")[0], "lid": "111@lid", "name": "Nikita", "platform": "android"}

    def contacts(self):
        return [{"jid": SASHA1, "full_name": "Саша Иванов", "first_name": "Саша", "push_name": "", "business_name": ""},
                {"jid": SASHA2, "full_name": "Саша Петров", "first_name": "Саша", "push_name": "", "business_name": ""},
                {"jid": IVAN, "full_name": "Ivan", "first_name": "Ivan", "push_name": "Vanya", "business_name": ""}]

    def groups(self):
        self.calls.append(("groups",))
        return list(self.joined)

    def group_from_link(self, code):
        self.calls.append(("group_from_link", code))
        if code == "Revoked1234":
            raise CliError("WhatsApp: invite link revoked", code=2)
        return {"jid": "120363000000000777@g.us", "name": "Joinable", "topic": "t", "created": T0, "owner": IVAN,
                "participants": 12, "announce": False, "community": False, "parent": None}

    def join_link(self, code):
        self.calls.append(("join_link", code))
        return "120363000000000777@g.us"

    def newsletter_by_invite(self, code):
        self.calls.append(("newsletter_by_invite", code))
        return self.newsletter(NEWS)

    def newsletter(self, jid):
        return {"jid": NEWS, "name": "News", "description": "d", "invite": "0029VaNEWSnewsNEWS1234", "subscribers": 1000,
                "verified": True, "created": T0, "state": "active"}

    def subscribed_newsletters(self):
        if self.fail == "subscribed":
            raise CliError("WhatsApp: boom")
        return [dict(self.newsletter(NEWS), jid=j, name=f"F{i}") for i, j in enumerate(self.follows)]

    def newsletter_messages(self, jid, count):
        self.calls.append(("newsletter_messages", jid, count))
        return [(101, 0, {"👍": 5, "❤️": 40}, P(conversation="первый пост")),
                (102, 0, {}, P(imageMessage=P(caption="второй пост")))][:count]

    def group(self, jid):
        self.calls.append(("group", jid))
        if jid not in self.member_of:
            raise CliError("WhatsApp: forbidden")
        return {"jid": jid, "name": "Joinable", "topic": "t", "created": T0, "owner": IVAN, "participants": 3,
                "announce": False, "community": False, "parent": None}

    def on_whatsapp(self, *phones):
        self.calls.append(("on_whatsapp",) + phones)
        jid = phones[0].lstrip("+") + "@s.whatsapp.net"
        return [{"query": phones[0], "jid": jid if jid in self.registered else None, "is_in": jid in self.registered}]

    def _sent(self):
        if self.fail:
            raise self.fail
        return {"id": f"3EB0{len(self.sent)}", "ts": T0, "server_id": None}

    def send_text(self, jid, text):
        r = self._sent()
        self.sent.append((jid, text))
        return r

    def send_document(self, jid, path, caption=None):
        r = self._sent()
        self.sent.append((jid, path, caption))
        return r

    def download(self, blob, path):
        self.calls.append(("download", blob))
        if blob == b"gone":
            raise wa.download_error(Exception("download failed with status code 404"))
        if blob == b"broken":
            raise wa.download_error(Exception("invalid media hmac"))
        Path(path).write_bytes(b"%PDF-1.4 " + blob)

    def logout(self):
        self.calls.append(("logout",))


class Base(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="wa-home-", dir=TMP))
        for name, val in (("ACCOUNTS", self.home / "accounts"), ("LOGS", self.home / "logs")):
            p = mock.patch.object(config, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(normalize, "_blob", fake_blob)
        p.start()
        self.addCleanup(p.stop)
        self.session = FakeSession()

    def cli(self, *argv, session=None, stdin=None, tty=False, connect=None):
        s = session or self.session
        out, err = io.StringIO(), io.StringIO()
        sin = io.StringIO(stdin or "")
        sin.isatty = lambda: tty

        def fake_connect(cfg, account, need_auth=True):
            path = config.session_path(account)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or not path.stat().st_size:
                path.write_bytes(b"SQLite format 3\0")
            return s
        with mock.patch.object(wa, "connect", connect or fake_connect), mock.patch("sys.stdin", sin), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main_mod.main(list(argv))
            except SystemExit as e:  # argparse
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def offline(self, *argv):
        def boom(*a, **k):
            raise AssertionError("connected despite --offline")
        return self.cli(*argv, "--offline", connect=boom)


class Contract(Base):
    def test_top_help_lists_exit_codes(self):
        code, out, _ = self.cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("channel-fetch", out)
        self.assertIn("3 refused", out)
        self.assertIn("never loop", out)

    def test_every_command_help_renders(self):
        from src import registry
        for name in registry.COMMANDS:
            code, out, _ = self.cli(name, "--help")
            self.assertEqual(code, 0, name)
            self.assertIn("examples:", out, name)

    def test_unknown_command_suggests(self):
        code, _, err = self.cli("serch", "x")
        self.assertEqual(code, 2)
        self.assertIn("did you mean: search", err)

    def test_json_parses_and_fields_narrow(self):
        code, out, _ = self.cli("chats", "-j", "--fields", "jid,name")
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual(set(rows[0]), {"jid", "name"})
        self.assertEqual(rows[0]["jid"], QA)  # newest activity first

    def test_tsv_header_and_no_header(self):
        _, out, _ = self.cli("chats", "--fields", "jid,type")
        self.assertEqual(out.splitlines()[0], "jid\ttype")
        _, out, _ = self.cli("chats", "--fields", "jid", "--no-header")
        self.assertEqual(out.splitlines()[0], QA)

    def test_unknown_field_is_exit_2(self):
        code, _, err = self.cli("chats", "--fields", "bogus")
        self.assertEqual(code, 2)
        self.assertIn("this command has:", err)

    def test_not_logged_in_is_exit_2_without_neonize(self):
        err = io.StringIO()
        with mock.patch.object(config, "ACCOUNTS", self.home / "none"), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            code = main_mod.main(["--account", "ghost", "whoami"])
        self.assertEqual(code, 2)
        self.assertIn("wa-cli --account ghost login", err.getvalue())

    def test_bad_account_name_is_exit_2(self):
        code, _, err = self.cli("--account", "../x", "whoami")
        self.assertEqual(code, 2)
        self.assertIn("bad account name", err)

    def test_login_refuses_without_tty(self):
        code, _, err = self.cli("login")
        self.assertEqual(code, 2)
        self.assertIn("interactive", err)

    def test_single_row_commands_have_header_unless_no_header(self):
        code, out, _ = self.cli("whoami", "--fields", "phone")
        self.assertEqual((code, out), (0, "phone\n+351900000001\n"))
        self.assertEqual(self.cli("whoami", "--fields", "phone", "--no-header")[1], "+351900000001\n")
        _, out, _ = self.cli("send", "me", "test")
        self.assertEqual(out.splitlines()[0], "id\tchat_jid\tchat\tdate")
        _, out, _ = self.cli("send", "me", "test", "--fields", "id", "--no-header")  # ID=$(...) idiom
        self.assertEqual(out, "3EB01\n")
        _, out, _ = self.cli("channel-info", NEWS)
        self.assertEqual(out.splitlines()[0], "jid\tname\tsubscribers\tverified\tfollowing\tinvite")
        self.assertEqual(json.loads(self.cli("channel-info", NEWS, "-j")[1])["name"], "News")  # -j: one object

    def test_accounts_offline(self):
        self.cli("whoami")
        code, out, _ = self.cli("accounts", "--fields", "account,jid,messages", "--no-header")
        self.assertEqual(code, 0)
        self.assertEqual(out.split("\t")[:2], ["default", ME])


class Store(Base):
    def test_history_sync_lands_in_history(self):
        code, out, _ = self.cli("history", "Команда QA", "-j", "--full")
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual([r["msg_id"] for r in rows], ["q5", "q1", "q2", "q3"])
        self.assertEqual(rows[1]["sender"], "Ivan")  # address-book name beats push name

    def test_edit_and_revoke_applied(self):
        _, out, _ = self.cli("history", QA, "-j")
        by_id = {r["msg_id"]: r for r in json.loads(out)}
        self.assertEqual(by_id["q1"]["text"], "релиз послезавтра")
        self.assertEqual(by_id["q5"]["text"], "[deleted]")
        self.assertNotIn("q4", by_id)  # the edit op itself is no message
        self.assertNotIn("q7", by_id)  # reactions are skipped

    def test_media_label_through_wrapper(self):
        _, out, _ = self.cli("history", "Ivan", "--fields", "sender,text", "--no-header")
        self.assertEqual(out.splitlines(), ["Ivan\t[image] photo cap", "me\thello ivan"])

    def test_text_limit_and_note(self):
        _, out, err = self.cli("history", QA)
        self.assertIn("x" * 200 + "…", out)
        self.assertIn("--full", err)

    def test_search_is_prefix_fts(self):
        _, out, _ = self.cli("search", "рели", "--fields", "msg_id", "--no-header")
        self.assertEqual(out.split(), ["q1"])
        _, out, _ = self.cli("search", "сообщ стар", "--fields", "msg_id", "--no-header")
        self.assertEqual(out.split(), ["q3"])

    def test_search_filters(self):
        self.cli("sync")
        _, out, _ = self.offline("search", "--chat", "команда qa", "--from", "Саша Петров", "--fields", "msg_id", "--no-header")
        self.assertEqual(out.split(), ["q3"])
        _, out, _ = self.offline("search", "--chat", QA, "--since", "1d", "-n", "1", "--fields", "msg_id", "--no-header")
        self.assertEqual(out.split(), ["q5"])

    def test_search_needs_query_or_chat(self):
        code, _, err = self.cli("search")
        self.assertEqual(code, 2)
        self.assertIn("query is required", err)

    def test_quotes_in_query_are_safe(self):
        code, _, _ = self.cli("search", 'a"b OR', "NEAR(")
        self.assertEqual(code, 0)

    def test_offline_never_connects(self):
        self.cli("sync")
        code, out, _ = self.offline("chats", "--fields", "name", "--no-header")
        self.assertEqual(code, 0)
        self.assertIn("Команда QA", out)

    def test_leftovers_at_disconnect_are_kept(self):
        s = FakeSession(leftovers=[live(IVAN, IVAN, "late", P(conversation="arrived late"), T0)])
        self.cli("whoami", session=s)
        _, out, _ = self.offline("search", "late", "--fields", "msg_id", "--no-header")
        self.assertEqual(out.split(), ["late"])

    def test_sync_counts(self):
        code, out, _ = self.cli("sync", "-j")
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertEqual((r["new"], r["messages"]), (6, 6))  # 4 history + image + oops (revoked, kept as [deleted])
        self.assertGreaterEqual(r["contacts"], 4)

    def test_chats_filter_and_contacts(self):
        _, out, _ = self.cli("chats", "ivan", "--fields", "jid,phone", "--no-header")
        self.assertEqual(out, f"{IVAN}\t+351933333333\n")
        _, out, _ = self.offline("contacts", "--fields", "name", "--no-header")
        self.assertEqual(sorted(out.split("\n")[:-1]), ["Ivan", "Саша Иванов", "Саша Петров"])

    def test_user_find_sources(self):
        _, out, _ = self.cli("user-find", "саша", "-j")
        self.assertEqual({(r["jid"], r["source"]) for r in json.loads(out)}, {(SASHA1, "contact"), (SASHA2, "contact")})
        _, out, _ = self.offline("user-find", "Stranger", "--fields", "phone,source", "--no-header")
        self.assertEqual(out, "+351944444444\tseen\n")

    def test_user_find_check(self):
        _, out, _ = self.cli("user-find", "+351 955 555 555", "--check", "--fields", "jid", "--no-header")
        self.assertEqual(out, "351955555555@s.whatsapp.net\n")
        code, out, err = self.cli("user-find", "+351000000000", "--check", "--no-header")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("not on WhatsApp", err)


class GroupNames(Base):
    NEW = "120363431303927976@g.us"

    def test_group_created_after_login_gets_its_name(self):
        self.cli("chats")  # first run: refresh done, store "refreshed" now
        self.session.queue = [live(self.NEW, IVAN, "n1", P(conversation="hi"), T0)]
        self.session.joined.append({"jid": self.NEW, "name": "Посмотрим", "created": T0 - 100})
        _, out, _ = self.cli("chats", "--fields", "jid,name", "--no-header")
        self.assertIn(f"{self.NEW}\tПосмотрим", out.splitlines())
        _, out, _ = self.offline("history", self.NEW, "--fields", "chat", "--no-header")
        self.assertEqual(out, "Посмотрим\n")

    def test_left_nameless_group_does_not_refresh_every_run(self):
        self.cli("chats")
        self.session.queue = [live(self.NEW, IVAN, "n1", P(conversation="hi"), T0)]
        self.cli("chats")  # forced refresh, group not among joined ones
        n = self.session.calls.count(("groups",))
        self.cli("chats")
        self.assertEqual(self.session.calls.count(("groups",)), n)

    def test_group_info_and_joined_events_update_names(self):
        rename = ("group_info", P(JID=J(QA), Name=P(Name="QA team (new)")))
        topic_only = ("group_info", P(JID=J(QA), Topic=P(Topic="x")))
        joined = ("joined_group", P(GroupInfo=P(JID=J(self.NEW), GroupName=P(Name="Added"), GroupCreated=T0)))
        self.cli("chats")  # history + hourly refresh done
        self.session.queue = [rename, topic_only, joined]
        _, out, _ = self.cli("chats", "--fields", "jid,name", "--no-header")
        rows = dict(line.split("\t") for line in out.splitlines())
        self.assertEqual((rows[QA], rows[self.NEW]), ("QA team (new)", "Added"))

    def test_group_events_left_at_disconnect_are_kept(self):
        rename = ("group_info", P(JID=J(QA), Name=P(Name="Renamed late")))
        s = FakeSession(leftovers=[rename])
        self.cli("chats", session=s)
        _, out, _ = self.offline("chats", "--fields", "name", "--no-header")
        self.assertIn("Renamed late", out.splitlines())

    def test_system_chat_is_named_whatsapp_without_phone(self):
        self.session.queue = [live("0@s.whatsapp.net", "0@s.whatsapp.net", "z1", P(conversation="code"), T0)]
        _, out, _ = self.cli("chats", "--fields", "jid,name,phone", "--no-header")
        self.assertIn("0@s.whatsapp.net\tWhatsApp\t", out.splitlines())
        self.assertNotIn("+0", out)


class Send(Base):
    def test_send_verbatim_to_name_and_recorded(self):
        code, out, _ = self.cli("send", "Ivan", "@351911111111 *hi*", "--fields", "id,chat", "--no-header")
        self.assertEqual((code, out), (0, "3EB00\tIvan\n"))
        self.assertEqual(self.session.sent, [(IVAN, "@351911111111 *hi*")])
        _, out, _ = self.offline("search", "hi", "--fields", "sender", "--no-header")
        self.assertEqual(out, "me\n")

    def test_send_stdin_and_me(self):
        self.cli("send", "me", "-", stdin="from stdin\n")
        self.assertEqual(self.session.sent, [(ME, "from stdin\n")])

    def test_send_ambiguous_sends_nothing(self):
        self.cli("sync")
        code, out, err = self.cli("send", "Саша", "hi")
        self.assertEqual((code, out, self.session.sent), (2, "", []))
        self.assertIn("2 chats match", err)
        self.assertIn(SASHA2, err)

    def test_send_unknown_phone_checked_first(self):
        code, _, _ = self.cli("send", "+351 955 555 555", "hi")
        self.assertEqual(code, 0)
        self.assertIn(("on_whatsapp", "+351955555555"), self.session.calls)
        code, _, err = self.cli("send", "+351000000000", "hi", session=FakeSession())
        self.assertEqual(code, 2)
        self.assertIn("not on WhatsApp - nothing sent", err)

    def test_send_known_phone_skips_check(self):
        self.cli("send", "+351933333333", "hi")
        self.assertNotIn("on_whatsapp", [c[0] for c in self.session.calls])

    def test_send_unknown_name(self):
        code, _, err = self.cli("send", "Nobody Here", "hi")
        self.assertEqual((code, self.session.sent), (2, []))
        self.assertIn("user-find", err)

    def _tmpfile(self, name):
        d = tempfile.mkdtemp(dir=TMP)
        path = os.path.join(d, name)
        Path(path).write_bytes(b"PK")
        return path

    def test_send_files_one_message_each_caption_first(self):
        a, b = self._tmpfile("a.pdf"), self._tmpfile("b.pdf")
        code, out, _ = self.cli("send", "Ivan", "logs", "--file", a, "--file", b, "--fields", "id", "--no-header")
        self.assertEqual((code, out), (0, "3EB00\n3EB01\n"))
        self.assertEqual(self.session.sent, [(IVAN, a, "logs"), (IVAN, b, None)])

    def test_send_missing_file_or_empty_sends_nothing(self):
        code, _, err = self.cli("send", "Ivan", "x", "--file", "/nonexistent/x.zip")
        self.assertEqual((code, self.session.sent), (2, []))
        self.assertIn("no such file", err)
        code, _, _ = self.cli("send", "Ivan", "  ")
        self.assertEqual((code, self.session.sent), (2, []))

    def test_rate_limit_is_exit_1_never_retry(self):
        exc_mod = types.ModuleType("neonize.exc")

        class NeonizeError(Exception):
            pass
        exc_mod.NeonizeError = NeonizeError
        self.session.fail = NeonizeError("server returned error 429: rate-overlimit")
        with mock.patch.dict(sys.modules, {"neonize": types.ModuleType("neonize"), "neonize.exc": exc_mod}):
            code, _, err = self.cli("send", "Ivan", "hi")
        self.assertEqual(code, 1)
        self.assertIn("never retry in a loop", err)
        self.assertEqual(len(self.session.sent), 0)

    def test_temp_ban_message(self):
        s = wa.Session(None, types.SimpleNamespace(release=lambda: None), "a", True)
        e = s.fatal("temp_ban", P(Expire=3600))
        self.assertEqual(e.code, 1)
        self.assertIn("TEMPORARY BAN", str(e))
        self.assertIn("never retry", str(e))


class GroupsChannels(Base):
    def test_group_info_parses_link_and_does_not_join(self):
        code, out, _ = self.cli("group-info", "https://chat.whatsapp.com/AbCdEf123456GhIjKl", "-j")
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertEqual((r["name"], r["owner"], r["participants"], r["participants_preview"], r["member"]),
                         ("Joinable", "+351933333333", None, 12, False))  # preview is partial: no fake total
        self.assertEqual([c for c in self.session.calls if c[0] not in ("stop", "groups")],
                         [("group_from_link", "AbCdEf123456GhIjKl")])

    def test_group_info_member_gets_real_participant_count(self):
        g = "120363000000000777@g.us"
        self.session.joined.append({"jid": g, "name": "Joinable", "created": T0})
        self.session.member_of.add(g)
        code, out, _ = self.cli("group-info", "https://chat.whatsapp.com/AbCdEf123456GhIjKl?s=cl&p=i&mlu=0&ilr=4", "-j")
        r = json.loads(out)
        self.assertEqual((code, r["participants"], r["participants_preview"], r["member"]), (0, 3, 12, True))

    def test_group_bad_link(self):
        code, _, err = self.cli("group-info", "https://example.com/x")
        self.assertEqual(code, 2)
        self.assertIn("not a group invite link", err)

    def test_join_looks_then_joins_once(self):
        code, out, _ = self.cli("join", "https://chat.whatsapp.com/invite/AbCdEf123456GhIjKl", "--fields", "jid,name", "--no-header")
        self.assertEqual((code, out), (0, "120363000000000777@g.us\tJoinable\n"))
        names = [c[0] for c in self.session.calls if c[0] not in ("stop", "groups")]
        self.assertEqual(names, ["group_from_link", "join_link"])

    def test_join_revoked_link_joins_nothing(self):
        code, _, _ = self.cli("join", "Revoked1234")
        self.assertEqual(code, 2)
        self.assertNotIn("join_link", [c[0] for c in self.session.calls])

    def test_channel_info_by_link(self):
        code, out, _ = self.cli("channel-info", "https://whatsapp.com/channel/0029VaNEWSnewsNEWS1234", "--fields", "jid,name,verified", "--no-header")
        self.assertEqual((code, out), (0, f"{NEWS}\tNews\tyes\n"))
        self.assertIn(("newsletter_by_invite", "0029VaNEWSnewsNEWS1234"), self.session.calls)

    def test_channel_fetch_stores_posts_for_search(self):
        code, out, err = self.cli("channel-fetch", NEWS, "--no-header")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["s102\t0\t[image] второй пост", "s101\t45\tпервый пост"])
        rows = json.loads(self.cli("channel-fetch", NEWS, "-j")[1])
        self.assertEqual((rows[1]["top_reactions"], rows[1]["views"]), ("❤️40 👍5", None))  # views 0 = not shown
        self.assertIn("News", err)
        _, out, _ = self.offline("search", "пост", "--chat", "News", "--fields", "msg_id", "--no-header")
        self.assertEqual(sorted(out.split()), ["s101", "s102"])

    def test_channel_info_following_from_subscribed_list(self):
        _, out, _ = self.cli("channel-info", NEWS, "--fields", "following", "--no-header")
        self.assertEqual(out, "no\n")
        self.assertNotIn("role", json.loads(self.cli("channel-info", NEWS, "-j")[1]))
        self.session.follows = [NEWS]
        _, out, _ = self.cli("channel-info", NEWS, "--fields", "following", "--no-header")
        self.assertEqual(out, "yes\n")

    def test_chats_hides_unfollowed_channel_keeps_posts(self):
        self.cli("channel-fetch", NEWS)
        _, out, _ = self.offline("chats", "--fields", "jid", "--no-header")
        self.assertNotIn(NEWS, out)
        rows = json.loads(self.offline("chats", "--all", "--type", "channel", "-j")[1])
        self.assertEqual([(r["jid"], r["following"]) for r in rows], [(NEWS, False)])
        _, out, _ = self.offline("search", "пост", "--fields", "msg_id", "--no-header")
        self.assertEqual(sorted(out.split()), ["s101", "s102"])

    def test_refresh_marks_followed_and_unfollowed_channels(self):
        other = "120363888888888888@newsletter"
        self.cli("channel-fetch", NEWS)
        self.session.follows = [other]
        from src.api import sync
        from src.core.store import Store
        st = Store(config.store_path("default"))
        self.addCleanup(st.close)
        sync.mark_followed(self.session, st)
        st.commit()
        self.assertEqual((st.chat(other)["info"], st.chat(NEWS)["info"]), ("following", "not-following"))
        self.session.fail = "subscribed"
        sync.mark_followed(self.session, st)  # a failed request marks nothing, raises nothing
        self.assertEqual(st.chat(other)["info"], "following")


class Download(Base):
    def setUp(self):
        super().setUp()
        self.out = Path(tempfile.mkdtemp(prefix="wa-dl-", dir=TMP))
        self.session.queue = default_events() + [
            live(IVAN, IVAN, "d1", doc("bolt.pdf"), T0 - 86400 * 400),
            live(IVAN, IVAN, "d2", doc("bolt.pdf"), T0 - 86400 * 399),
            live(IVAN, IVAN, "d3", P(audioMessage=P(PTT=True, mimetype="audio/ogg; codecs=opus")), T0 - 100),
            live(IVAN, IVAN, "d4", doc("old.pdf", blob=b"gone"), T0 - 90),
            live(IVAN, IVAN, "d5", P(conversation="text only"), T0 - 80)]

    def dl(self, *argv):
        return self.cli("download", *argv, "-o", str(self.out))

    def test_by_id_keeps_original_name(self):
        code, out, _ = self.dl("Ivan", "d1", "-j")
        self.assertEqual(code, 0)
        r = json.loads(out)[0]
        self.assertEqual((r["status"], r["kind"], Path(r["path"]).name), ("ok", "document", "bolt.pdf"))
        self.assertTrue((self.out / "bolt.pdf").read_bytes().startswith(b"%PDF"))
        self.assertEqual(list(self.out.glob("*.part")), [])

    def test_history_shows_id_kind_and_file(self):
        self.cli("whoami")
        _, out, _ = self.offline("history", "Ivan", "--fields", "msg_id,kind,file,text", "--no-header")
        self.assertIn("d1\tdocument\tbolt.pdf\t[document] bolt.pdf", out)
        self.assertIn("i2\timage\t\t[image] photo cap", out)  # media through a wrapper keeps its keys

    def test_all_with_kind_filter_and_name_dedupe(self):
        code, out, _ = self.dl("Ivan", "all", "--kind", "document", "--until", "60d", "--fields", "msg_id,path", "--no-header")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(Path(line.split("\t")[1]).name for line in out.splitlines()),
                         ["bolt (2).pdf", "bolt.pdf"])  # same name twice in one run: no overwrite

    def test_all_since_and_generated_name(self):
        code, out, err = self.dl("Ivan", "all", "--since", "1d", "--kind", "voice,image", "-j")
        self.assertEqual(code, 0, err)
        names = {r["msg_id"]: Path(r["path"]).name for r in json.loads(out)}
        day = datetime.fromtimestamp(T0 - 100).date().isoformat()
        self.assertEqual(names["d3"], f"{day}_d3.ogg")
        self.assertEqual(set(names), {"d3", "i2"})

    def test_expired_is_exit_2_others_still_saved(self):
        code, out, err = self.dl("Ivan", "d4", "d1", "--fields", "msg_id,status", "--no-header")
        self.assertEqual((code, out), (2, "d4\texpired\nd1\tok\n"))
        self.assertIn("1 expired: media expired on WhatsApp's servers", err)
        self.assertFalse(list(self.out.glob("*.part")))

    def test_other_failure_is_exit_1(self):
        self.session.queue.append(live(IVAN, IVAN, "d6", doc("x.pdf", blob=b"broken"), T0 - 70))
        code, _, err = self.dl("Ivan", "d6")
        self.assertEqual(code, 1)
        self.assertIn("failed: download failed: invalid media hmac", err)

    def test_stored_without_keys_is_no_keys(self):
        self.cli("whoami")
        st = __import__("src.core.store", fromlist=["Store"]).Store(config.store_path("default"))
        st.db.execute("UPDATE messages SET media=NULL WHERE id='d1'")
        st.close()
        code, out, err = self.dl("Ivan", "d1", "--fields", "status", "--no-header")
        self.assertEqual((code, out), (2, "no-keys\n"))
        self.assertIn("logout + login", err)
        self.assertNotIn(("download", None), self.session.calls)

    def test_usage_errors(self):
        self.assertEqual(self.dl("Ivan", "nope")[0], 2)
        code, _, err = self.dl("Ivan", "d5")
        self.assertEqual(code, 2)
        self.assertIn("is text, not media", err)
        code, _, err = self.dl("Ivan", "d1", "--since", "1d")
        self.assertEqual(code, 2)
        self.assertIn("go with all", err)
        code, _, err = self.dl("Ivan", "all", "--kind", "gif")
        self.assertEqual(code, 2)
        self.assertNotIn(("download",), [c[:1] for c in self.session.calls])

    def test_v1_store_gets_media_columns(self):
        import sqlite3
        path = config.store_path("default")
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path))
        db.execute("CREATE TABLE messages (rowid INTEGER PRIMARY KEY, chat_jid TEXT NOT NULL, id TEXT NOT NULL, ts INTEGER, "
                   "sender_jid TEXT, sender_name TEXT, from_me INTEGER, kind TEXT, text TEXT, server_id INTEGER, "
                   "views INTEGER, UNIQUE (chat_jid, id))")
        db.execute("INSERT INTO messages (chat_jid, id, ts, kind, text) VALUES (?, 'old', ?, 'document', '[document] a.pdf')",
                   (IVAN, T0 - 50))
        db.commit()
        db.close()
        code, out, err = self.dl("Ivan", "old", "--fields", "status", "--no-header")
        self.assertEqual((code, out), (2, "no-keys\n"), err)


class Normalize(unittest.TestCase):
    def test_nested_wrappers_and_document(self):
        m = P(viewOnceMessageV2=P(message=P(documentWithCaptionMessage=P(message=P(documentMessage=P(fileName="a.pdf", caption="see"))))))
        self.assertEqual(normalize.content(m), ("msg", "document", "[document] a.pdf see"))

    def test_voice_poll_unknown_and_noise(self):
        self.assertEqual(normalize.content(P(audioMessage=P(PTT=True))), ("msg", "voice", "[voice]"))
        poll = P(pollCreationMessageV3=P(name="Q?", options=[P(optionName="a"), P(optionName="b")]))
        self.assertEqual(normalize.content(poll), ("msg", "poll", "[poll] Q? (a / b)"))
        self.assertEqual(normalize.content(P(eventMessage=P(name="x"))), ("msg", "other", "[event]"))
        self.assertIsNone(normalize.content(P(senderKeyDistributionMessage=P(x=1))))

    def test_media_of_kinds_and_non_media(self):
        with mock.patch.object(normalize, "_blob", fake_blob):
            got = normalize.media_of(P(ephemeralMessage=P(message=doc("a.pdf"))))
            self.assertEqual((got["file"], got["mime"], got["media"]), ("a.pdf", "application/pdf", b"documentMessage"))
            self.assertEqual(normalize.media_of(P(ptvMessage=P()))["media"], b"ptvMessage")
            self.assertIsNone(normalize.media_of(P(conversation="hi")))
        self.assertIsNone(normalize.media_of(doc("a.pdf"))["media"])  # fakes are not protos: no blob, no crash

    def test_download_error_classes(self):
        self.assertEqual((wa.download_error(Exception("download failed with status code 410")).code,
                          wa.download_error(Exception("download failed with status code 410")).status), (2, "expired"))
        self.assertEqual(wa.download_error(Exception("context deadline exceeded")).status, "failed")

    def test_timestamps_ms_and_s(self):
        self.assertEqual(wa.norm_ts(T0 * 1000), T0)
        self.assertEqual(wa.norm_ts(T0), T0)
        self.assertIsNone(wa.norm_ts(0))


class Logout(Base):
    def test_purge_removes_account_dir(self):
        self.cli("whoami")
        code, out, _ = self.cli("logout", "--purge")
        self.assertEqual((code, out), (0, "account\tstatus\ndefault\tlogged-out+purged\n"))
        self.assertIn(("logout",), self.session.calls)
        self.assertFalse(config.account_dir("default").exists())
        code, out, err = self.cli("accounts", "--no-header")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("no accounts", err)

    def test_plain_logout_keeps_store(self):
        self.cli("whoami")
        code, out, _ = self.cli("logout")
        self.assertEqual((code, out), (0, "account\tstatus\ndefault\tlogged-out\n"))
        self.assertTrue(config.store_path("default").exists())
        self.assertFalse(config.session_path("default").exists())
        self.assertEqual(self.cli("accounts", "--no-header")[1], "")

    def test_empty_session_db_is_not_an_account(self):
        d = config.account_dir("ghost")
        d.mkdir(parents=True)
        (d / "session.db").touch()  # sqlite reopened by path after logout
        (d / "lock").touch()
        self.assertEqual(config.accounts(), [])


QUIET_SCRIPT = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from src.core import wa
from src.core.output import Writer
w = Writer()
q = wa.Quiet(sys.argv[2])

class Client:
    def stop(self): os.write(1, b"Press Ctrl+C to exit\n")

class Lock:
    def release(self): pass

q.start()
os.write(1, b"Login event: success\n")
os.write(2, b"go stderr noise\n")
w.write([{"a": "data"}], ["a"], receipt=True)  # header row too
w.note("linked; connecting")
sys.stderr.write("QR-BLOCK\n")
s = wa.Session(Client(), Lock(), "t", True, q)
s.thread = __import__("threading").Thread(target=lambda: None); s.thread.start()
s.stop()
print("after")
sys.stderr.write("# after\n")
"""


class Quiet(unittest.TestCase):
    def test_native_output_goes_to_log_and_wa_cli_output_stays(self):
        import subprocess
        log = Path(TMP) / "quiet.log"
        r = subprocess.run([sys.executable, "-c", QUIET_SCRIPT, str(ROOT), str(log)], capture_output=True, text=True)
        self.assertEqual(r.stdout, "a\ndata\nafter\n", r.stderr)
        self.assertEqual(r.stderr, "# linked; connecting\nQR-BLOCK\n# after\n")
        noise = log.read_text()
        for line in ("Login event: success", "go stderr noise", "Press Ctrl+C to exit"):
            self.assertIn(line, noise)

    def test_quiet_leaves_non_fd_streams_alone(self):
        q = wa.Quiet(Path(TMP) / "quiet2.log")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            q.start()
            try:
                print("x")
            finally:
                q.stop()
        self.assertEqual(out.getvalue(), "x\n")

    def test_login_status_print_is_muted(self):
        class NewClient:
            def _NewClient__onLoginStatus(self, uuid, status):
                print(status)
        wa._mute(types.SimpleNamespace(NewClient=NewClient))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            NewClient()._NewClient__onLoginStatus(1, 105553139400736)
        self.assertEqual(out.getvalue(), "")


class Pipes(unittest.TestCase):
    def test_broken_pipe_exits_0(self):
        import subprocess
        env = dict(os.environ, PYTHONPATH=str(ROOT), WA_CLI_IN_VENV="1")
        r = subprocess.run(f'"{sys.executable}" "{ROOT}/wa-cli.py" --help | head -1', shell=True,
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.stdout.count("\n"), 1)
        self.assertNotIn("Traceback", r.stderr)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)



class LinkedJids(unittest.TestCase):
    """A phone chat and a lid chat of one person (the lid row carries the phone jid in alt_jid): +phone, the phone
    jid and the lid all resolve to both; the name is one chat, not ambiguous."""

    def test_phone_and_lid_chat_fold(self):
        from src.api import peers
        from src.core.store import Store
        st = Store(Path(tempfile.mkdtemp(prefix="wa-store-", dir=TMP)) / "s.db")
        st.upsert_chat("351900000001@s.whatsapp.net", "user", "Vet", last_ts=T0)
        st.upsert_chat("777@lid", "user", "Vet", alt_jid="351900000001@s.whatsapp.net", last_ts=T0)
        for ref in ("+351900000001", "351900000001@s.whatsapp.net", "777@lid", "Vet"):
            _, jids, _ = peers.resolve(st, ref)
            self.assertEqual(set(jids), {"351900000001@s.whatsapp.net", "777@lid"}, ref)


if __name__ == "__main__":
    unittest.main()
