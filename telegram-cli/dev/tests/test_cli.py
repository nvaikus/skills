"""Contract tests with a fake Telegram client. Run: python3 -m unittest discover -s dev/tests"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TMP = tempfile.mkdtemp(prefix="tg-cli-test-")
os.environ.update(TG_CLI_HOME=TMP, TG_CLI_CONFIG=f"{TMP}/cfg.json", TG_CLI_API_ID="1", TG_CLI_API_HASH="h")
sys.path.insert(0, str(ROOT))

from src import main as main_mod  # noqa: E402
from src.core import config, tg  # noqa: E402

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


class User(SimpleNamespace):
    pass


class Channel(SimpleNamespace):
    pass


class Chat(SimpleNamespace):
    pass


class MessageMediaPhoto:
    pass


def user(id, first, last=None, username=None, phone=None, bot=False):
    return User(id=id, first_name=first, last_name=last, username=username, phone=phone, bot=bot, premium=False)


ME = user(1, "Nikita", username="nik", phone="351900")
SASHA1 = user(10, "Саша", "Иванов", username="sasha_i")
SASHA2 = user(11, "Саша", "Петров")
IVAN = user(12, "Ivan", username="ivan")
QA = Channel(id=500, title="Команда QA", megagroup=True, username=None)
NEWS = Channel(id=600, title="News", megagroup=False, username="news")


class MessageMediaDocument:
    pass


class MessageMediaGeo:
    pass


def msg(id, chat, sender, text, minutes_ago=0, media=None, **kw):
    return SimpleNamespace(id=id, chat=chat, sender=sender, message=text, media=media,
                           date=NOW - timedelta(minutes=minutes_ago), **kw)


def doc(id, chat, name, minutes_ago=0, kind="document", ext=".pdf", text=""):
    """A file message the way Telethon exposes it: media + kind property + .file."""
    return msg(id, chat, IVAN, text, minutes_ago, MessageMediaDocument(), **{"document": True, kind: True},
               file=SimpleNamespace(name=name, size=1000 + id, ext=ext))


class FakeClient:
    def __init__(self):
        self.dialogs = [SimpleNamespace(entity=e, unread_count=i, date=NOW) for i, e in
                        enumerate([QA, SASHA1, SASHA2, IVAN, NEWS])]
        self.msgs = [msg(3, QA, IVAN, "релиз завтра", 1), msg(2, QA, SASHA1, "x" * 300, 60),
                     msg(1, NEWS, NEWS, "", 60 * 48, MessageMediaPhoto())]
        self.sent, self.calls, self.downloads = [], [], []

    def is_user_authorized(self):
        return True

    def get_me(self):
        return ME

    def get_entity(self, ref):
        for e in [ME, SASHA1, SASHA2, IVAN, QA, NEWS]:
            from src.api.peers import peer_id
            if ref == peer_id(e):
                return e
        raise ValueError("Could not find the input entity")

    def iter_dialogs(self, limit=None):
        return iter(self.dialogs[:limit] if limit else self.dialogs)

    def iter_messages(self, chat, search=None, from_user=None, offset_date=None, filter=None):
        self.calls.append(("iter_messages", chat, search, from_user, offset_date, filter))
        return iter([m for m in self.msgs if chat is None or m.chat is chat])

    def get_messages(self, chat, ids):
        by_id = {m.id: m for m in self.msgs if m.chat is chat}
        return [by_id.get(i) for i in ids]

    def download_media(self, m, file):
        with open(file, "wb") as f:
            f.write(b"%PDF-" + str(m.id).encode())
        self.downloads.append((m.id, file))
        return file

    def send_message(self, chat, text, parse_mode=None, reply_to=None):
        self.sent.append((chat, text, parse_mode))
        return SimpleNamespace(id=77, date=NOW)

    def send_file(self, chat, file, caption=None, force_document=False, parse_mode=None, reply_to=None):
        self.sent.append((chat, file, caption, force_document))
        if isinstance(file, list):
            return [SimpleNamespace(id=80 + i, date=NOW) for i in range(len(file))]
        return SimpleNamespace(id=78, date=NOW)

    def disconnect(self):
        pass


def cli(*argv, client=None, stdin=None):
    client = client or FakeClient()
    out, err = io.StringIO(), io.StringIO()
    usernames = {"ivan": IVAN, "news": NEWS, "sasha_i": SASHA1}
    found = SimpleNamespace(my_results=[SimpleNamespace(user_id=10)], results=[SimpleNamespace(channel_id=600)],
                            users=[SASHA1], chats=[NEWS])
    with mock.patch.object(tg, "connect", lambda *a, **k: client), \
            mock.patch.object(tg, "contacts", lambda c: [SASHA1, SASHA2]), \
            mock.patch.object(tg, "resolve_username", lambda c, n: usernames.get(n.lower())), \
            mock.patch.object(tg, "search_peers", lambda c, q, limit: found), \
            mock.patch.object(tg, "media_filter", lambda k: f"F:{k}"), \
            mock.patch("sys.stdin", io.StringIO(stdin or "")), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main_mod.main(list(argv))
        except SystemExit as e:  # argparse
            code = e.code
    return code, out.getvalue(), err.getvalue(), client


class Contract(unittest.TestCase):
    def test_top_help_lists_exit_codes(self):
        code, out, _, _ = cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("user-find", out)
        self.assertIn("3 refused", out)

    def test_every_command_help_renders(self):
        from src import registry
        for name in registry.COMMANDS:
            code, out, _, _ = cli(name, "--help")
            self.assertEqual(code, 0, name)
            self.assertIn("examples:", out, name)

    def test_unknown_command_suggests(self):
        code, _, err, _ = cli("serch", "x")
        self.assertEqual(code, 2)
        self.assertIn("did you mean: search", err)

    def test_json_parses_and_fields_narrow(self):
        code, out, _, _ = cli("chats", "-j", "--fields", "id,name")
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual(set(rows[0]), {"id", "name"})
        self.assertEqual(rows[0]["id"], -100500)

    def test_tsv_header_and_no_header(self):
        _, out, _, _ = cli("chats", "--fields", "id,type")
        self.assertEqual(out.splitlines()[0], "id\ttype")
        _, out, _, _ = cli("chats", "--fields", "id", "--no-header")
        self.assertEqual(out.splitlines()[0], "-100500")

    def test_unknown_field_is_exit_2(self):
        code, _, err, _ = cli("chats", "--fields", "bogus")
        self.assertEqual(code, 2)
        self.assertIn("this command has:", err)

    def test_missing_api_keys_is_exit_2_quoting_example(self):
        with mock.patch.dict(os.environ, {"TG_CLI_API_ID": ""}):
            with mock.patch.object(config, "CONFIG_PATH", Path(TMP) / "none.json"):
                code, err = self._real_connect()
        self.assertEqual(code, 2)
        self.assertIn("TG_CLI_API_ID", err)
        self.assertIn('"api_hash"', err)

    def _real_connect(self):
        err = io.StringIO()
        with mock.patch.object(tg, "telethon", lambda: None), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            code = main_mod.main(["whoami"])
        return code, err.getvalue()

    def test_not_logged_in_is_exit_2(self):
        err = io.StringIO()
        with mock.patch.object(tg, "telethon", lambda: None), contextlib.redirect_stderr(err):
            code = main_mod.main(["--account", "ghost", "whoami"])
        self.assertEqual(code, 2)
        self.assertIn("tg-cli --account ghost login", err.getvalue())


class Keys(unittest.TestCase):
    def test_keys_refuses_without_tty(self):
        code, _, err, _ = cli("keys")
        self.assertEqual(code, 2)
        self.assertIn("interactive", err)

    def test_keys_writes_0600_and_merges(self):
        cfg = Path(TMP) / "keys.json"
        cfg.write_text('{"default_account": "work"}')
        tty = io.StringIO("123456\n")
        tty.isatty = lambda: True
        with mock.patch.object(config, "CONFIG_PATH", cfg), mock.patch("sys.stdin", tty), \
                mock.patch("getpass.getpass", lambda p: "a" * 32), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main_mod.main(["keys"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(cfg.read_text()), {"default_account": "work", "api_id": 123456, "api_hash": "a" * 32})
        self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)


class Commands(unittest.TestCase):
    def test_whoami_receipt_has_no_header(self):
        code, out, _, _ = cli("whoami", "--fields", "username")
        self.assertEqual((code, out), (0, "nik\n"))

    def test_chats_filter_and_type(self):
        _, out, _, _ = cli("chats", "саша", "--type", "user", "--fields", "id", "--no-header")
        self.assertEqual(out.split(), ["10", "11"])

    def test_user_find_merges_sources_without_duplicates(self):
        _, out, _, _ = cli("user-find", "саша", "-j")
        rows = json.loads(out)
        self.assertEqual([(r["id"], r["source"]) for r in rows], [(10, "contact"), (11, "contact"), (-100600, "global")])

    def test_user_find_exact_username(self):
        _, out, _, _ = cli("user-find", "@ivan", "--fields", "id,source", "--no-header")
        self.assertIn("12\tusername", out)

    def test_global_search_truncates_and_notes(self):
        code, out, err, client = cli("search", "релиз")
        self.assertEqual(code, 0)
        self.assertEqual(client.calls[0][1:3], (None, "релиз"))
        self.assertIn("x" * 200 + "…", out)
        self.assertIn("--full", err)

    def test_search_since_stops_early(self):
        _, out, _, _ = cli("search", "x", "--since", "1d", "--fields", "msg_id", "--no-header")
        self.assertNotIn("1", out.split())  # the 2-day-old message is cut

    def test_search_from_needs_chat(self):
        code, _, err, _ = cli("search", "x", "--from", "@ivan")
        self.assertEqual(code, 2)
        self.assertIn("--from needs --chat", err)

    def test_search_in_chat_by_name(self):
        _, out, _, client = cli("search", "--chat", "команда qa", "--from", "@ivan", "-j")
        self.assertIs(client.calls[0][1], QA)
        self.assertIs(client.calls[0][3], IVAN)

    def test_media_label(self):
        _, out, _, _ = cli("history", "@news", "-j")
        self.assertEqual(json.loads(out)[0]["text"], "[photo]")
        self.assertEqual(json.loads(out)[0]["link"], "https://t.me/news/1")

    def test_webpage_preview_has_no_label(self):
        class MessageMediaWebPage:
            pass
        c = FakeClient()
        c.msgs = [msg(9, NEWS, NEWS, "see https://x.io", 0, MessageMediaWebPage())]
        _, out, _, _ = cli("history", "@news", "--fields", "text", "--no-header", client=c)
        self.assertEqual(out, "see https://x.io\n")

    def test_send_receipt_and_verbatim_text(self):
        code, out, _, client = cli("send", "@ivan", "**hi**", "--fields", "id", "--no-header")
        self.assertEqual((code, out), (0, "77\n"))
        self.assertEqual(client.sent, [(IVAN, "**hi**", None)])

    def test_send_stdin(self):
        _, _, _, client = cli("send", "me", "-", stdin="from stdin\n")
        self.assertEqual(client.sent[0][:2], (ME, "from stdin\n"))

    def test_send_ambiguous_name_sends_nothing(self):
        code, out, err, client = cli("send", "Саша", "hi")
        self.assertEqual(code, 2)
        self.assertEqual(client.sent, [])
        self.assertEqual(out, "")
        self.assertIn("2 chats match", err)
        self.assertIn("sasha_i", err)

    def test_send_exact_name_wins_over_substring(self):
        _, _, _, client = cli("send", "ivan", "hi")
        self.assertIs(client.sent[0][0], IVAN)

    def test_send_unknown_username(self):
        code, _, err, client = cli("send", "@nobody_here", "hi")
        self.assertEqual((code, client.sent), (2, []))
        self.assertIn("does not exist", err)

    def test_send_empty_text(self):
        code, _, _, client = cli("send", "@ivan", "  ")
        self.assertEqual((code, client.sent), (2, []))

    def _tmpfile(self, name="a.zip"):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, name)
        with open(path, "wb") as f:
            f.write(b"PK")
        return path

    def test_send_file_with_caption_as_document(self):
        path = self._tmpfile()
        code, out, _, client = cli("send", "@ivan", "logs", "--file", path, "--fields", "id", "--no-header")
        self.assertEqual((code, out), (0, "78\n"))
        self.assertEqual(client.sent, [(IVAN, path, "logs", True)])

    def test_send_file_without_text(self):
        path = self._tmpfile()
        code, out, _, client = cli("send", "@ivan", "--file", path, "-j")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["id"], 78)
        self.assertEqual(client.sent, [(IVAN, path, None, True)])

    def test_send_several_files_one_row_each(self):
        a, b = self._tmpfile("a.pdf"), self._tmpfile("b.pdf")
        code, out, _, client = cli("send", "@ivan", "--file", a, "--file", b, "--fields", "id", "--no-header")
        self.assertEqual((code, out), (0, "80\n81\n"))
        self.assertEqual(client.sent[0][1], [a, b])
        _, out, _, _ = cli("send", "@ivan", "--file", a, "--file", b, "-j")
        self.assertEqual([r["id"] for r in json.loads(out)], [80, 81])

    def test_send_missing_file_sends_nothing(self):
        code, _, err, client = cli("send", "@ivan", "x", "--file", "/nonexistent/x.zip")
        self.assertEqual((code, client.sent), (2, []))
        self.assertIn("no such file", err)

    def test_send_no_text_no_file(self):
        code, _, _, client = cli("send", "@ivan")
        self.assertEqual((code, client.sent), (2, []))


class Media(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out)
        self.c = FakeClient()
        self.c.msgs = [doc(9, IVAN, "a.pdf", 1, text="scan"), doc(8, IVAN, "../../etc/a.pdf", 60),
                       doc(7, IVAN, None, 60 * 24, "voice", ".oga"), msg(6, IVAN, IVAN, "hi", 60 * 30),
                       msg(5, IVAN, IVAN, "", 60 * 30, MessageMediaGeo()),
                       doc(4, IVAN, "old.pdf", 60 * 24 * 10)]

    def get(self, *argv):
        return cli("media-get", "@ivan", *argv, "-o", self.out, client=self.c)

    def test_history_shows_type_and_file_name(self):
        _, out, _, _ = cli("history", "@ivan", "-j", client=self.c)
        rows = {r["msg_id"]: r for r in json.loads(out)}
        self.assertEqual(rows[9]["text"], "[document: a.pdf] scan")
        self.assertEqual((rows[9]["media"], rows[9]["file"]), ("document", "a.pdf"))
        self.assertEqual(rows[7]["text"], "[voice]")
        self.assertEqual(rows[5]["text"], "[geo]")
        self.assertIsNone(rows[6]["media"])

    def test_service_message_is_labelled(self):
        class MessageActionPhoneCall:
            pass
        self.c.msgs = [msg(3, IVAN, IVAN, None, 0, action=MessageActionPhoneCall())]
        _, out, _, _ = cli("history", "@ivan", "--fields", "text", "--no-header", client=self.c)
        self.assertEqual(out, "[phonecall]\n")

    def test_get_by_id_keeps_original_name(self):
        code, out, _, c = self.get("9", "--fields", "msg_id,path", "--no-header")
        self.assertEqual(code, 0)
        path = os.path.join(self.out, "a.pdf")
        self.assertEqual(out, f"9\t{path}\n")
        with open(path, "rb") as f:
            self.assertTrue(f.read().startswith(b"%PDF-"))
        self.assertEqual(c.sent, [])

    def test_hostile_name_stays_inside_out_dir_and_repeat_gets_msg_id(self):
        _, out, _, _ = self.get("9", "8", "-j")
        paths = [r["path"] for r in json.loads(out)]
        self.assertEqual(paths, [os.path.join(self.out, "a.pdf"), os.path.join(self.out, "_.._etc_a.pdf")])
        self.assertTrue(all(os.path.dirname(p) == self.out for p in paths))

    def test_nameless_media_gets_type_and_msg_id(self):
        _, out, _, _ = self.get("7", "--fields", "type,path", "--no-header")
        self.assertEqual(out, f"voice\t{os.path.join(self.out, 'voice_7.oga')}\n")

    def test_missing_or_text_only_id_downloads_nothing(self):
        for ids in (["9", "6"], ["9", "999"], ["5"]):
            code, _, err, c = self.get(*ids)
            self.assertEqual((code, c.downloads), (2, []), ids)
            self.assertIn("nothing downloaded", err)

    def test_all_filters_type_and_since(self):
        code, out, _, c = self.get("all", "--type", "document", "--since", "2026-09-28", "--fields", "msg_id", "--no-header")
        self.assertEqual((code, out.split()), (0, ["9", "8"]))
        self.assertEqual(c.calls[0][5], "F:document")  # server-side filter for one type

    def test_all_multi_type_filters_client_side(self):
        _, out, _, c = self.get("all", "--type", "voice,photo", "--fields", "msg_id", "--no-header")
        self.assertEqual(out.split(), ["7"])
        self.assertIsNone(c.calls[0][5])

    def test_all_limit_notes_more(self):
        _, out, err, _ = self.get("all", "-n", "2", "--fields", "msg_id", "--no-header")
        self.assertEqual(out.split(), ["9", "8"])
        self.assertIn("more exist", err)

    def test_list_downloads_nothing(self):
        code, out, _, c = self.get("all", "--list")
        self.assertEqual((code, c.downloads), (0, []))
        self.assertEqual(out.splitlines()[0], "msg_id\tdate\ttype\tsize\tname")
        self.assertEqual(len(out.splitlines()), 5)

    def test_usage_errors(self):
        for argv in (["abc"], ["9", "--type", "photo"], ["all", "--type", "pdf"]):
            code, _, _, c = self.get(*argv)
            self.assertEqual((code, c.downloads), (2, []), argv)


class Public(unittest.TestCase):
    def run_public(self, flood, query="claude"):
        res = SimpleNamespace(messages=[SimpleNamespace(id=5, date=NOW, message="post", media=None, from_id=None,
                                                        peer_id=SimpleNamespace(channel_id=600))],
                              chats=[NEWS], users=[])
        with mock.patch.object(tg, "posts_flood", lambda c, q: flood), \
                mock.patch.object(tg, "search_posts", mock.Mock(return_value=res)) as sp:
            r = cli("search", "--public", query, "-j")
        return r, sp

    def test_quota_exhausted_refuses_without_sending(self):
        flood = SimpleNamespace(total_daily=10, remains=0, stars_amount=10, query_is_free=False, wait_till=None)
        (code, _, err, _), sp = self.run_public(flood)
        self.assertEqual(code, 3)
        sp.assert_not_called()
        self.assertIn("never", err)

    def test_quota_ok(self):
        flood = SimpleNamespace(total_daily=10, remains=4, stars_amount=10, query_is_free=False, wait_till=None)
        (code, out, err, _), _ = self.run_public(flood)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["link"], "https://t.me/news/5")
        self.assertIn("3/10 left", err)

    def test_hashtag_skips_quota(self):
        (code, _, _, _), sp = self.run_public(None, "#ai")
        self.assertEqual(code, 0)
        self.assertEqual(sp.call_args[0][1:3], (None, "ai"))


class Pipes(unittest.TestCase):
    def test_broken_pipe_exits_0(self):
        import subprocess
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        r = subprocess.run(f'"{sys.executable}" "{ROOT}/tg-cli.py" --help | head -1', shell=True,
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.stdout.count("\n"), 1)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
