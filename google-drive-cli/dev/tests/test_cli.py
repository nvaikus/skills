"""Contract tests with mocked HTTP and no rclone. Run: python3 -m unittest discover -s dev/tests"""
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from support import ROOT, TMP, main_mod, run  # noqa: E402  (sets the test environment first)

from src.api import auth, drive, google, markdown, mounts, persist, rclone, sheets  # noqa: E402
from src.core import http, output, wait  # noqa: E402
from src.core.errors import CliError, UsageError  # noqa: E402

FOLDER, DOC, SHEET = drive.FOLDER, drive.DOC, drive.SHEET


# ---- fake Google ---------------------------------------------------------------------------

FILES = {
    "root": {"id": "root", "name": "My Drive", "mimeType": FOLDER},
    "fProj": {"id": "fProj", "name": "Projects", "mimeType": FOLDER, "parents": ["root"]},
    "dPlan": {"id": "dPlan", "name": "Plan", "mimeType": DOC, "parents": ["fProj"], "webViewLink": "https://docs/dPlan"},
    "sBud": {"id": "sBud", "name": "Budget", "mimeType": SHEET, "parents": ["fProj"], "webViewLink": "https://sheets/sBud"},
    "dup1": {"id": "dupAAAAAAAAAAAAAAAA1", "name": "Notes", "mimeType": DOC, "parents": ["fProj"]},
    "dup2": {"id": "dupAAAAAAAAAAAAAAAA2", "name": "Notes", "mimeType": DOC, "parents": ["fProj"]},
    "pdf": {"id": "pdf1", "name": "report.pdf", "mimeType": "application/pdf", "parents": ["fProj"], "size": "10"},
    "swm": {"id": "fSwm", "name": "Brief", "mimeType": FOLDER, "sharedWithMeTime": "2026-01-01T00:00:00Z"},
    "swmDoc": {"id": "dSwm", "name": "Passport", "mimeType": DOC, "parents": ["fSwm"]},
}
BY_ID = {f["id"]: f for f in FILES.values()}


def para(text, style="NORMAL_TEXT", start=1, bullet=None, runs=None):
    elements = runs or [{"textRun": {"content": text + "\n", "textStyle": {}}}]
    p = {"elements": elements, "paragraphStyle": {"namedStyleType": style}}
    if bullet:
        p["bullet"] = bullet
    n = markdown.u16(text) + 1
    return {"startIndex": start, "endIndex": start + n, "paragraph": p}


def doc_body(*items):
    content, i = [{"endIndex": 1, "sectionBreak": {}}], 1
    for text, style in items:
        el = para(text, style, i)
        content.append(el)
        i = el["endIndex"]
    return {"content": content}


PLAN_BODY = doc_body(("Plan", "TITLE"), ("Goals", "HEADING_1"), ("Ship it.", "NORMAL_TEXT"),
                     ("Risks", "HEADING_1"), ("Vendor.", "NORMAL_TEXT"))


class FakeGoogle:
    def __init__(self):
        self.calls = []
        self.batches = []
        self.replaced = 2
        self.created = []
        self.perms = {  # fProj: permissionDetails absent (My Drive); dPlan: Bob inherited from fProj
            "fProj": [{"id": "pOwn", "type": "user", "role": "owner", "emailAddress": "me@x.com"},
                      {"id": "pBob", "type": "user", "role": "reader", "emailAddress": "bob@x.com"}],
            "dPlan": [{"id": "pOwn", "type": "user", "role": "owner", "emailAddress": "me@x.com"},
                      {"id": "pBob", "type": "user", "role": "reader", "emailAddress": "Bob@x.com"},
                      {"id": "pAnn", "type": "user", "role": "writer", "emailAddress": "ann@x.com"},
                      {"id": "anyoneWithLink", "type": "anyone", "role": "reader"}],
        }

    def __call__(self, method, url, params=None, body=None, form=None, headers=None, allow_mutate=False, **kw):
        if method != "GET" and not allow_mutate:
            raise RuntimeError("transport rail")
        self.calls.append((method, url, params, body))
        path = url.split("googleapis.com", 1)[-1]
        perm = re.match(r"/drive/v3/files/([^/?]+)/permissions(?:/([^/?]+))?$", path.split("?")[0])
        if perm and method == "GET":
            return {"permissions": [dict(p) for p in self.perms.get(perm.group(1), [])]}
        if perm and method == "DELETE":
            self.perms[perm.group(1)] = [p for p in self.perms[perm.group(1)] if p["id"] != perm.group(2)]
            return None
        if path.startswith("/drive/v3/files/") and method == "GET":
            fid = path.rsplit("/", 1)[-1]
            if fid in BY_ID:
                return BY_ID[fid]
            raise CliError("HTTP 404", status=404, body={"error": {"message": "File not found"}})
        if path == "/drive/v3/files" and method == "GET":
            q = params["q"]
            parent = re.search(r"'([^']+)' in parents", q)
            name = re.search(r"name = '((?:[^'\\]|\\.)*)'", q)
            mime = re.search(r"mimeType = '([^']+)'", q)
            here = (lambda f: parent.group(1) in f.get("parents", [])) if parent else \
                (lambda f: "sharedWithMe = true" in q and bool(f.get("sharedWithMeTime")))
            out = [f for f in BY_ID.values() if here(f)
                   and (not name or f["name"] == name.group(1).replace("\\'", "'"))
                   and (not mime or f["mimeType"] == mime.group(1))]
            return {"files": out}
        if path.endswith("/permissions") and method == "POST":
            return {"id": "anyoneWithLink"}
        if path == "/drive/v3/files" and method == "POST":
            f = {"id": "new1", "name": body["name"], "mimeType": body["mimeType"], "webViewLink": "https://new"}
            self.created.append(f)
            return f
        if path.startswith("/v1/documents/dPlan") and method == "GET":
            return {"documentId": "dPlan", "revisionId": "rev1",
                    "tabs": [{"tabProperties": {"tabId": "t.0", "title": "Tab 1"}, "documentTab": {"body": PLAN_BODY, "lists": {}}}]}
        if path.endswith(":batchUpdate"):
            self.batches.append(body)
            if "replaceAllText" in body["requests"][0]:
                n = self.replaced
                return {"replies": [{"replaceAllText": {"occurrencesChanged": n} if n else {}}]}
            return {"replies": [{}]}
        if "/spreadsheets/sBud" in path and "/values/" not in path:
            return {"sheets": [{"properties": {"sheetId": 0, "title": "Q3 plan", "index": 0,
                                               "gridProperties": {"rowCount": 100, "columnCount": 5}}}]}
        if "/values/" in path and method == "GET":
            return {"range": "'Q3 plan'!A1:B2", "values": [["Name", "Qty"], ["a\tb", "line1\nline2"]]}
        if "/values/" in path and method == "PUT":
            return {"updatedRange": body["range"], "updatedRows": len(body["values"]), "updatedColumns": 2,
                    "updatedCells": sum(map(len, body["values"]))}
        if path.endswith(":append"):
            return {"updates": {"updatedRange": "'Q3 plan'!A3:B3", "updatedRows": 1, "updatedCells": 2}}
        raise AssertionError(f"unrouted {method} {url}")


class GoogleCase(unittest.TestCase):
    def setUp(self):
        self.g = FakeGoogle()
        patches = [mock.patch.object(http, "request", self.g), mock.patch.object(auth, "access_token", lambda r: "tok")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


# ---- dispatch / output contract ------------------------------------------------------------

class Dispatch(unittest.TestCase):
    def test_top_help(self):
        rc, out, _ = run("--help")
        self.assertEqual(rc, 0)
        self.assertIn("doc edit", out)
        self.assertIn("exit: 0 ok", out)
        self.assertEqual(run()[0], 2)

    def test_unknown_suggests(self):
        rc, _, err = run("mout")
        self.assertEqual(rc, 2)
        self.assertIn("did you mean: mount", err)
        rc, _, err = run("doc", "catt", "x")
        self.assertEqual(rc, 2)
        self.assertIn("cat", err)

    def test_family_help(self):
        rc, out, _ = run("sheet")
        self.assertEqual(rc, 2)
        self.assertIn("sheet append", out)

    def test_every_command_help(self):
        from src import registry
        for name in registry.COMMANDS:
            with self.subTest(name=name):
                with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()):
                    main_mod.main(name.split() + ["-h"])
                self.assertEqual(cm.exception.code, 0)

    def test_wait_only_on_async(self):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            main_mod.main(["status", "--wait", "5"])  # a read has no --wait
        self.assertEqual(cm.exception.code, 2)

    def test_wait_clamp(self):
        notes = []
        self.assertEqual(wait.clamp(999, notes.append), 230)
        self.assertTrue(notes)
        self.assertEqual(wait.clamp(None, notes.append), 200)

    def test_writer_fields(self):
        buf = io.StringIO()
        w = output.Writer(fields="a,b.c", out=buf)
        w.write([{"a": 1, "b": {"c": "x\ty"}}], ["z"])
        self.assertEqual(buf.getvalue(), "a\tb.c\n1\tx y\n")
        with self.assertRaises(UsageError):
            output.Writer(fields="nope").write([{"a": 1}], ["a"])

    def test_transport_rail(self):
        with self.assertRaises(RuntimeError):
            http.request("POST", "https://example.invalid/x")

    def test_commands_never_mutate_directly(self):
        for p in (ROOT / "src" / "commands").rglob("*.py"):
            text = p.read_text()
            self.assertNotIn("allow_mutate", text, p)
            self.assertNotIn("print(", text, p)


# ---- config / login ------------------------------------------------------------------------

class Login(unittest.TestCase):
    def test_no_client_points_at_onboard(self):
        rc, _, err = run("login", "--start")
        self.assertEqual(rc, 2)
        self.assertIn("gdrive onboard", err)

    def test_start_finish(self):
        env = {"GDRIVE_CLIENT_ID": "cid", "GDRIVE_CLIENT_SECRET": "sec", "GDRIVE_REMOTE": "gtest"}
        with mock.patch.dict(os.environ, env):
            rc, out, _ = run("login", "--start")
            self.assertEqual(rc, 0)
            url = out.strip()
            self.assertIn("code_challenge_method=S256", url)
            self.assertIn("access_type=offline", url)
            state = re.search(r"state=([^&]+)", url).group(1)

            def token(method, url, form=None, **kw):
                self.assertTrue(kw.get("allow_mutate"))
                self.assertEqual(form["client_secret"], "sec")
                self.assertTrue(form["code_verifier"])
                return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3599, "token_type": "Bearer"}

            about = {"user": {"emailAddress": "me@example.com", "displayName": "Me"}}
            with mock.patch.object(http, "request", token), mock.patch.object(drive, "about", lambda r: about):
                rc, out, err = run("login", "--finish", stdin=f"http://127.0.0.1:53682/?state={state}&code=C0DE&scope=x\n")
            self.assertEqual(rc, 0, err)
            self.assertIn("me@example.com", out)
            sec = auth.section("gtest")
            self.assertEqual(sec["type"], "drive")
            self.assertEqual(json.loads(sec["token"])["refresh_token"], "RT")
            self.assertEqual(oct(rclone.conf().stat().st_mode & 0o777), "0o600")
            # replaying the finish is refused: the pending login was consumed
            rc, _, err = run("login", "--finish", stdin=f"http://127.0.0.1:53682/?state={state}&code=C0DE")
            self.assertEqual(rc, 2)

    def test_interactive_needs_tty(self):
        with mock.patch.dict(os.environ, {"GDRIVE_CLIENT_ID": "cid", "GDRIVE_CLIENT_SECRET": "sec"}):
            rc, _, err = run("login", stdin="")
        self.assertEqual(rc, 2)
        self.assertIn("--start", err)

    def test_expiry_formats(self):
        for s in ("2026-09-30T22:37:14.123456789+01:00", "2026-09-30T21:37:14Z", "2026-09-30T21:37:14.5+00:00"):
            self.assertEqual(auth.parse_expiry(s).year, 2026)

    def test_refresh_writes_back_and_keeps_other_sections(self):
        rclone.conf().write_text("[other]\ntype = alias\nremote = /x\n\n")
        auth.save_token("gref", "cid", "sec", {"access_token": "old", "refresh_token": "RT",
                                                "expiry": "2000-01-01T00:00:00Z", "token_type": "Bearer"})
        with mock.patch.object(http, "request", lambda *a, **k: {"access_token": "NEW", "expires_in": 3600}):
            self.assertEqual(auth.access_token("gref"), "NEW")
        tok = json.loads(auth.section("gref")["token"])
        self.assertEqual(tok["refresh_token"], "RT")
        self.assertEqual(auth.access_token("gref"), "NEW")  # cached, no HTTP
        self.assertEqual(auth._read_conf().get("other", "remote"), "/x")

    def test_parse_redirect(self):
        self.assertEqual(auth.parse_redirect("http://127.0.0.1:53682/?state=s&code=c"), ("c", "s"))
        self.assertEqual(auth.parse_redirect("4/0AbCd"), ("4/0AbCd", None))
        with self.assertRaises(CliError):
            auth.parse_redirect("http://127.0.0.1:53682/?error=access_denied")


# ---- paths ---------------------------------------------------------------------------------

class Paths(GoogleCase):
    def test_split(self):
        self.assertEqual(drive.split("/A/B"), (("my", None), ["A", "B"]))
        self.assertEqual(drive.split("shared:Team X/A"), (("shared", "Team X"), ["A"]))
        self.assertEqual(drive.split("https://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/edit"),
                         (("id", "1AbCdEfGhIjKlMnOp"), []))
        self.assertEqual(drive.split("@xyz"), (("id", "xyz"), []))

    def test_shared_with_me_address(self):
        self.assertEqual(drive.split("shared-with-me:/Brief/Passport"), (("swm", None), ["Brief", "Passport"]))
        self.assertEqual(drive.resolve("g", "shared-with-me:/Brief/Passport")["id"], "dSwm")
        rc, out, _ = run("ls", "shared-with-me:", "--fields", "name,kind")
        self.assertEqual(rc, 0)
        self.assertIn("Brief\tfolder", out)
        self.assertNotIn("Projects", out)

    def test_no_create_at_shared_with_me_top(self):
        rc, _, err = run("doc", "new", "shared-with-me:/New doc")
        self.assertEqual(rc, 2)
        self.assertIn('top of "Shared with me"', err)
        self.assertFalse(self.g.created)

    def test_read_only_403_is_usage(self):
        e = CliError("HTTP 403", status=403, body={"error": {"message": "The user does not have sufficient permissions",
                                                             "errors": [{"reason": "insufficientFilePermissions"}]}})
        got = google.translate(e)
        self.assertIsInstance(got, UsageError)
        self.assertIn("edit access", str(got))

    def test_layout_address(self):
        self.assertEqual(drive.layout_address("My Drive/A/b.txt"), "/A/b.txt")
        self.assertEqual(drive.layout_address("My Drive"), "/")
        self.assertEqual(drive.layout_address("Shared with me/Brief/x"), "shared-with-me:/Brief/x")
        self.assertEqual(drive.layout_address("Shared drives/Team/A"), "shared:Team/A")
        self.assertEqual(drive.layout_address("Shared drives/Team@0AbCdEfGhIjKlMnOpQ"), "shared:@0AbCdEfGhIjKlMnOpQ")
        self.assertEqual(drive.drive_segments([{"id": "1", "name": "T"}, {"id": "2", "name": "t"},
                                               {"id": "3", "name": "A/B"}]), {"1": "T@1", "2": "t@2", "3": "A／B"})

    def test_resolve_and_export_name(self):
        self.assertEqual(drive.resolve("g", "/Projects/Plan")["id"], "dPlan")
        self.assertEqual(drive.resolve("g", "Projects/Plan.docx")["id"], "dPlan")
        self.assertEqual(drive.resolve("g", "/Projects/Notes@dupAAAAAAAAAAAAAAAA2")["id"], "dupAAAAAAAAAAAAAAAA2")

    def test_ambiguous_lists_candidates(self):
        rc, _, err = run("doc", "cat", "/Projects/Notes")
        self.assertEqual(rc, 2)
        self.assertIn("Notes@dupAAAAAAAAAAAAAAAA1", err)
        self.assertIn("Notes@dupAAAAAAAAAAAAAAAA2", err)

    def test_not_found_suggests(self):
        rc, _, err = run("ls", "/Projects/Plam")
        self.assertEqual(rc, 2)
        self.assertIn("did you mean: Plan", err)

    def test_ls(self):
        rc, out, _ = run("ls", "/Projects", "--fields", "name,kind")
        self.assertEqual(rc, 0)
        self.assertIn("Plan\tdoc", out)
        self.assertIn("Budget\tsheet", out)
        rc, out, _ = run("ls", "/Projects/report.pdf", "-j")
        self.assertEqual(json.loads(out)[0]["kind"], "file")

    def test_link_private_changes_nothing(self):
        rc, out, _ = run("link", "/Projects/Plan", "--no-header")
        self.assertEqual(rc, 0)
        self.assertIn("https://docs/dPlan", out)
        self.assertFalse([c for c in self.g.calls if c[0] != "GET"])

    def test_link_public_creates_permission(self):
        rc, _, _ = run("link", "/Projects/Plan", "--public")
        self.assertEqual(rc, 0)
        perm = [c for c in self.g.calls if c[0] == "POST"]
        self.assertTrue(perm and perm[0][1].endswith("/permissions") and perm[0][3]["type"] == "anyone")

    def test_share_lists_without_changes(self):
        rc, out, _ = run("share", "/Projects/Plan", "--fields", "who,role,inherited", "--no-header")
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["me@x.com\towner\tno", "Bob@x.com\treader\tyes",
                                            "ann@x.com\twriter\tno", "anyone\treader\tno"])
        self.assertFalse([c for c in self.g.calls if c[0] != "GET"])

    def test_share_inherited_from_details(self):
        self.g.perms["dPlan"] = [{"id": "pX", "type": "domain", "role": "reader", "domain": "x.com",
                                  "permissionDetails": [{"inherited": True}]}]
        rc, out, _ = run("share", "/Projects/Plan", "-j")
        self.assertEqual(json.loads(out)[0]["inherited"], "yes")
        self.assertEqual(json.loads(out)[0]["who"], "x.com")

    def test_share_user_default_reader_silent(self):
        rc, _, _ = run("share", "/Projects/Plan", "--user", "eve@x.com")
        self.assertEqual(rc, 0)
        post = [c for c in self.g.calls if c[0] == "POST"]
        self.assertEqual(len(post), 1)
        self.assertEqual(post[0][3], {"type": "user", "role": "reader", "emailAddress": "eve@x.com"})
        self.assertEqual(post[0][2]["sendNotificationEmail"], "false")
        run("share", "/Projects/Plan", "--user", "eve@x.com", "--role", "writer", "--notify")
        post = [c for c in self.g.calls if c[0] == "POST"]
        self.assertEqual((post[1][3]["role"], post[1][2]["sendNotificationEmail"]), ("writer", "true"))

    def test_share_usage(self):
        self.assertEqual(run("share", "/Projects/Plan", "--role", "writer")[0], 2)
        for bad in (["--user", "a@x", "--remove", "b@x"], ["--user", "a@x", "--role", "owner"]):
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
                run("share", "/Projects/Plan", *bad)
            self.assertEqual(cm.exception.code, 2)
        self.assertFalse([c for c in self.g.calls if c[0] != "GET"])

    def test_share_remove(self):
        rc, out, _ = run("share", "/Projects/Plan", "--remove", "ANN@x.com", "--no-header")
        self.assertEqual(rc, 0)
        dels = [c for c in self.g.calls if c[0] == "DELETE"]
        self.assertEqual(len(dels), 1)
        self.assertTrue(dels[0][1].endswith("/files/dPlan/permissions/pAnn"))
        self.assertNotIn("ann@x.com", out)

    def test_share_remove_refuses_inherited_and_unknown(self):
        rc, _, err = run("share", "/Projects/Plan", "--remove", "bob@x.com")
        self.assertEqual(rc, 2)
        self.assertIn("inherited", err)
        rc, _, err = run("share", "/Projects/Plan", "--remove", "zed@x.com")
        self.assertEqual(rc, 2)
        self.assertIn("no access", err)
        self.assertFalse([c for c in self.g.calls if c[0] == "DELETE"])

    def test_wrong_kind(self):
        rc, _, err = run("sheet", "get", "/Projects/Plan")
        self.assertEqual(rc, 2)
        self.assertIn("not a Google Sheet", err)


# ---- docs ----------------------------------------------------------------------------------

class Docs(GoogleCase):
    def test_cat(self):
        rc, out, _ = run("doc", "cat", "/Projects/Plan")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "# Plan\n\n# Goals\n\nShip it.\n\n# Risks\n\nVendor.\n")

    def test_replace(self):
        rc, out, _ = run("doc", "edit", "/Projects/Plan", "--replace", "Ship", "Launch", "--fields", "changed")
        self.assertEqual(rc, 0)
        self.assertIn("2 occurrence", out)
        req = self.g.batches[0]["requests"][0]["replaceAllText"]
        self.assertEqual(req["containsText"], {"text": "Ship", "matchCase": True})
        self.g.replaced = 0
        self.assertEqual(run("doc", "edit", "/Projects/Plan", "--replace", "zzz", "y")[0], 2)

    def test_after_inserts_before_next_heading(self):
        rc, _, err = run("doc", "edit", "/Projects/Plan", "--after", "Goals", "- one\n- two")
        self.assertEqual(rc, 0, err)
        body = self.g.batches[-1]
        risks = [e for e in PLAN_BODY["content"] if "paragraph" in e][3]
        ins = body["requests"][0]["insertText"]
        self.assertEqual(ins["location"]["index"], risks["startIndex"])
        self.assertEqual(ins["text"], "one\ntwo\n")
        self.assertEqual(body["writeControl"], {"requiredRevisionId": "rev1"})
        self.assertIn("createParagraphBullets", body["requests"][-1])

    def test_after_missing_heading_lists_them(self):
        rc, _, err = run("doc", "edit", "/Projects/Plan", "--after", "Nope", "x")
        self.assertEqual(rc, 2)
        self.assertIn("# Risks", err)

    def test_append_at_end(self):
        rc, _, _ = run("doc", "edit", "/Projects/Plan", "--append", "-", stdin="## New\ntext")
        self.assertEqual(rc, 0)
        ins = self.g.batches[-1]["requests"][0]["insertText"]
        self.assertEqual(ins["location"]["index"], PLAN_BODY["content"][-1]["endIndex"] - 1)
        self.assertTrue(ins["text"].startswith("\nNew\n"))

    def test_new_refuses_duplicate(self):
        rc, _, err = run("doc", "new", "/Projects/Plan")
        self.assertEqual(rc, 3)
        self.assertFalse(self.g.created)
        rc, out, _ = run("doc", "new", "/Projects/Fresh", "# Hi", "--fields", "id")
        self.assertEqual((rc, out), (0, "new1\n"))
        self.assertEqual(self.g.created[0]["mimeType"], DOC)


class Markdown(unittest.TestCase):
    def test_to_markdown_styles(self):
        lists = {"L1": {"listProperties": {"nestingLevels": [{"glyphType": "DECIMAL"}, {"glyphSymbol": "o"}]}}}
        runs = [{"textRun": {"content": "Hello ", "textStyle": {}}},
                {"textRun": {"content": "bold ", "textStyle": {"bold": True}}},
                {"textRun": {"content": "site", "textStyle": {"link": {"url": "https://x"}}}},
                {"textRun": {"content": "\n", "textStyle": {}}}]
        body = {"content": [para("", runs=runs), para("first", bullet={"listId": "L1"}),
                            para("inner", bullet={"listId": "L1", "nestingLevel": 1})]}
        self.assertEqual(markdown.to_markdown(body, lists), "Hello **bold** [site](https://x)\n\n1. first\n   - inner\n")

    def test_requests_utf16_and_bullets(self):
        blocks, warns = markdown.parse("# Title 😀\n\n- a\n  - **b**\n\n1. c\n\n---\n")
        self.assertEqual([b["kind"] for b in blocks], ["heading", "bullet", "bullet", "bullet"])
        self.assertTrue(warns)
        reqs = markdown.requests(blocks, 10, False, False)
        text = reqs[0]["insertText"]["text"]
        self.assertEqual(text, "Title 😀\na\n\tb\nc")
        heading = next(r for r in reqs if "updateParagraphStyle" in r)["updateParagraphStyle"]
        self.assertEqual(heading["paragraphStyle"]["namedStyleType"], "HEADING_1")
        self.assertEqual(heading["range"]["endIndex"], 10 + markdown.u16("Title 😀"))
        bold = next(r["updateTextStyle"] for r in reqs if r.get("updateTextStyle", {}).get("textStyle", {}).get("bold"))
        b_start = 10 + markdown.u16("Title 😀\na\n\t")
        self.assertEqual((bold["range"]["startIndex"], bold["range"]["endIndex"]), (b_start, b_start + 1))
        bullets = [r["createParagraphBullets"] for r in reqs if "createParagraphBullets" in r]
        self.assertEqual([b["bulletPreset"] for b in bullets], ["NUMBERED_DECIMAL_ALPHA_ROMAN", "BULLET_DISC_CIRCLE_SQUARE"])
        self.assertGreater(bullets[0]["range"]["startIndex"], bullets[1]["range"]["startIndex"])


# ---- sheets --------------------------------------------------------------------------------

class Sheets(GoogleCase):
    def test_norm_range(self):
        self.assertEqual(sheets.norm_range("A1:C9"), "A1:C9")
        self.assertEqual(sheets.norm_range("Q3 plan"), "'Q3 plan'")
        self.assertEqual(sheets.norm_range("Q3 plan!A1"), "'Q3 plan'!A1")
        self.assertEqual(sheets.norm_range("'It''s'!B:B"), "'It''s'!B:B")

    def test_get_roundtrip(self):
        rc, out, err = run("sheet", "get", "/Projects/Budget")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "Name\tQty\na\\tb\tline1\\nline2\n")
        self.assertEqual(sheets.parse_tsv(out), [["Name", "Qty"], ["a\tb", "line1\nline2"]])
        rc, out, _ = run("sheet", "get", "/Projects/Budget", "A1:B2", "-j")
        self.assertEqual(json.loads(out)[1][1], "line1\nline2")
        self.assertEqual(run("sheet", "get", "/Projects/Budget", "--fields", "a")[0], 2)

    def test_set_and_append(self):
        rc, out, _ = run("sheet", "set", "/Projects/Budget", "Q3 plan!A1", stdin="x\t1\ny\t2\n")
        self.assertEqual(rc, 0)
        put = [c for c in self.g.calls if c[0] == "PUT"][0]
        self.assertEqual(put[2]["valueInputOption"], "USER_ENTERED")
        self.assertEqual(put[3]["values"], [["x", "1"], ["y", "2"]])
        self.assertIn("4", out)
        rc, _, _ = run("sheet", "append", "/Projects/Budget", "--raw", stdin="z\t3\n")
        self.assertEqual(rc, 0)
        app = [c for c in self.g.calls if c[1].endswith(":append")][0]
        self.assertEqual((app[2]["valueInputOption"], app[2]["insertDataOption"]), ("RAW", "INSERT_ROWS"))

    def test_set_needs_stdin(self):
        self.assertEqual(run("sheet", "set", "/Projects/Budget", "A1")[0], 2)

    def test_tabs(self):
        rc, out, _ = run("sheet", "tabs", "/Projects/Budget", "--no-header")
        self.assertEqual(out, "Q3 plan\t100\t5\tno\t0\n")


# ---- rclone / mounts -----------------------------------------------------------------------

class Mounts(unittest.TestCase):
    def state(self, mode="mount", **kw):
        with mock.patch.object(mounts, "free_port", lambda: 55555):
            st = mounts.new_state({"remote": "gdrive"}, "/Projects", f"{TMP}/mnt-{mode}", mode, "gdrive:Projects", "10G")
        st.update(kw)
        return st

    def test_mount_argv(self):
        st = self.state()
        argv = mounts.mount_argv(st)
        self.assertEqual(argv[1:4], ["mount", "gdrive:Projects", st["where"]])
        for flag in ("--vfs-cache-mode", "--cache-dir", "--vfs-cache-max-size", "--rc-addr", "--config"):
            self.assertIn(flag, argv)
        # FUSE mount: `full` serves size-less Google exports as 0 bytes; nfsmount keeps the read cache
        self.assertEqual(argv[argv.index("--vfs-cache-mode") + 1], "writes")
        nfs = mounts.mount_argv(self.state("nfsmount"))
        self.assertEqual(nfs[nfs.index("--vfs-cache-mode") + 1], "full")
        self.assertNotIn(st["rc_pass"], " ".join(argv))  # rc password rides in env only
        self.assertEqual(mounts.rc_env(st)["RCLONE_RC_PASS"], st["rc_pass"])

    def test_bisync_argv(self):
        st = self.state("sync")
        self.assertIn("--resync", mounts.bisync_argv(st, True))
        self.assertNotIn("--resync", mounts.bisync_argv(st, False))
        self.assertIn("--drive-skip-gdocs", mounts.bisync_argv(st, False))

    def test_source(self):
        cfg = {"remote": "gdrive"}
        with mock.patch.object(drive, "shared_drives", lambda r: []):
            self.assertEqual(mounts.source(cfg, "/"),
                             ":combine,upstreams='\"My Drive=gdrive:\" \"Shared with me=gdrive,shared_with_me:\"':")
        with mock.patch.object(drive, "shared_drives", lambda r: [{"id": "0AbC", "name": "Team's"}]):
            # live-verified quoting: '' inside the '...' value, "" inside a "..." upstream
            nested = ":combine,upstreams=''\"\"Team''''s=gdrive,team_drive=0AbC:\"\"'':"
            self.assertTrue(mounts.source(cfg, "/").endswith(f" \"Shared drives={nested}\"':"))
        self.assertEqual(mounts.source(cfg, "/A/B/"), "gdrive:A/B")
        with mock.patch.object(drive, "shared_drive", lambda r, n: {"id": "0AbC", "name": n}):
            self.assertEqual(mounts.source(cfg, "shared:Team X/Sub"), "gdrive,team_drive=0AbC:Sub")
        with self.assertRaises(UsageError):
            mounts.source(cfg, "Projects")

    def test_gdocs_note(self):
        # rclone FUSE/WinFsp open size-unknown files with direct IO -> exports readable; NFS cannot
        self.assertIsNone(mounts.gdocs_note("mount"))
        self.assertIn("EMPTY", mounts.gdocs_note("nfsmount"))
        self.assertIn("doc cat", mounts.gdocs_note("sync"))

    def test_pick_mode(self):
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(os.path, "exists", lambda p: False):
            self.assertEqual(mounts.pick_mode("auto")[0], "sync")
            with self.assertRaises(UsageError):
                mounts.pick_mode("mount")
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(os.path, "exists", lambda p: True), \
                mock.patch.object(mounts, "fuse_helper", lambda: "/usr/bin/fusermount3"):
            self.assertEqual(mounts.pick_mode("auto")[0], "mount")
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(mounts.pick_mode("auto")[0], "nfsmount")
        self.assertEqual(mounts.pick_mode("sync")[0], "sync")

    def test_check_target(self):
        d = Path(TMP) / "busy"
        d.mkdir()
        (d / "x").write_text("x")
        with self.assertRaises(UsageError):
            mounts.check_target(str(d), "mount")
        mounts.check_target(f"{TMP}/fresh/sub", "mount")
        self.assertTrue(Path(f"{TMP}/fresh/sub").is_dir())

    def test_to_drive(self):
        st = self.state()
        mounts.save(st)
        try:
            self.assertEqual(mounts.to_drive(st["where"] + "/Plan.docx"), "/Projects/Plan.docx")
            self.assertEqual(mounts.to_drive(st["where"]), "/Projects")
            self.assertIsNone(mounts.to_drive("/Projects/Plan"))
        finally:
            mounts.forget(st)

    def test_to_drive_layout(self):
        with mock.patch.object(mounts, "free_port", lambda: 55555):
            st = mounts.new_state({"remote": "gdrive"}, "/", f"{TMP}/mnt-all", "mount", "x", "10G")
        self.assertEqual(st["layout"], "all")
        self.assertFalse(mounts.old_layout(st))
        self.assertTrue(mounts.old_layout({**st, "layout": None}))
        mounts.save(st)
        try:
            w = st["where"]
            self.assertEqual(mounts.to_drive(w + "/My Drive/A/x.pdf"), "/A/x.pdf")
            self.assertEqual(mounts.to_drive(w + "/Shared with me/Brief/Passport.docx"),
                             "shared-with-me:/Brief/Passport.docx")
            self.assertEqual(mounts.to_drive(w + "/Shared drives/Team/A"), "shared:Team/A")
        finally:
            mounts.forget(st)

    def test_umount_refuses_with_dirty_cache(self):
        st = self.state(pid=None)
        Path(st["where"]).mkdir(parents=True, exist_ok=True)
        meta = Path(st["cache_dir"]) / "vfsMeta" / "gdrive" / "Projects"
        meta.mkdir(parents=True)
        (meta / "new.txt").write_text(json.dumps({"Dirty": True}))
        (meta / "old.txt").write_text(json.dumps({"Dirty": False}))
        st["path_meta"] = str(Path(st["cache_dir"]) / "vfsMeta" / "gdrive" / "Projects")
        mounts.save(st)
        try:
            with mock.patch.object(mounts, "unmount") as um:
                rc, out, err = run("umount", st["where"])
                self.assertEqual(rc, 3)
                self.assertEqual(out, "pending_upload\nnew.txt\n")
                um.assert_not_called()
                rc, out, err = run("umount", st["where"], "--force")
                self.assertEqual(rc, 0, err)
                um.assert_called_once()
            self.assertIn("kept in", err)
            self.assertTrue(Path(st["cache_dir"]).exists())  # kept so the upload resumes on remount
            self.assertIsNone(mounts.load(st["id"]))
        finally:
            mounts.forget(st)

    def _all_state(self, **kw):
        with mock.patch.object(mounts, "free_port", lambda: 55555):
            st = mounts.new_state({"remote": "gdrive"}, "/", f"{TMP}/mnt-all2", "nfsmount", "x", "10G")
        st.update(kw)
        return st

    @staticmethod
    def _fake_rc(queue):
        def rc(state, method, params=None):
            if method == "vfs/stats":
                return {"diskCache": {"bytesUsed": 1, "uploadsInProgress": 0, "uploadsQueued": len(queue), "erroredFiles": 0}}
            if method == "vfs/queue":
                return {"queue": [{"name": n, "tries": 15, "uploading": False} for n in queue]}
        return rc

    def test_combine_root_file_is_stuck_not_pending(self):
        # Finder's .DS_Store at a what=/ root: rclone retries it forever ("combine ... directory not
        # found"); it used to keep pending_uploads=1, so sync waited out its deadline (exit 6).
        st = self._all_state(source=":combine,upstreams='x':")
        self.assertTrue(mounts.unuploadable(st, ".DS_Store"))
        self.assertFalse(mounts.unuploadable(st, "My Drive/.DS_Store"))
        self.assertFalse(mounts.unuploadable(self.state(), "root.txt"))  # a folder mount's root is real
        with mock.patch("src.api.rclone.rc", self._fake_rc([".DS_Store", "My Drive/a.txt"])):
            got = mounts.cache_stats(st)
        self.assertEqual(got["pending_uploads"], 1)
        self.assertEqual((got["stuck"], got["queued"]), ([".DS_Store"], ["My Drive/a.txt"]))
        mounts.save(st)
        try:
            with mock.patch("src.api.rclone.rc", self._fake_rc([".DS_Store"])), \
                    mock.patch("src.core.proc.alive", lambda pid: True):
                rc, out, err = run("sync", st["where"], "--wait", "1")
                self.assertEqual(rc, 0, err)
                self.assertIn("uploaded\t0", out)
                self.assertIn(".DS_Store can never upload", err)
            with mock.patch("src.api.rclone.rc", self._fake_rc(["My Drive/a.txt"])), \
                    mock.patch("src.core.proc.alive", lambda pid: True):
                rc, out, err = run("sync", st["where"], "--wait", "0")
                self.assertEqual(rc, 6)
                self.assertIn("waiting on My Drive/a.txt", err)
        finally:
            mounts.forget(st)

    def test_umount_not_blocked_by_combine_root_file(self):
        st = self._all_state(pid=None, source=":combine,upstreams='x':")
        Path(st["where"]).mkdir(parents=True, exist_ok=True)
        meta = Path(st["cache_dir"]) / "vfsMeta" / ":combine{x}"
        meta.mkdir(parents=True)
        (meta / ".DS_Store").write_text(json.dumps({"Dirty": True}))
        st["path_meta"] = str(meta)
        mounts.save(st)
        try:
            rc, out, err = run("status", "-j")
            row = json.loads(out)[0]
            self.assertEqual((row["pending_uploads"], row["stuck_uploads"]), (0, [".DS_Store"]))
            with mock.patch.object(mounts, "unmount"):
                rc, out, err = run("umount", st["where"])
            self.assertEqual(rc, 0, err)
            self.assertIn("dropped with the cache: .DS_Store", err)
        finally:
            mounts.forget(st)

    def test_explicit_mount_becomes_profile_default(self):
        from src.core import config
        st = self.state(persist="launchd")
        with mock.patch("src.api.mounting.bring_up", lambda *a: (st, "mounted")):
            rc, out, err = run("mount", "/Projects", st["where"], "--persist")
            self.assertEqual(rc, 0, err)
            self.assertEqual(config.load()["mount"], {"what": "/Projects", "where": st["where"], "persist": True})
            config.update(mount={"what": "/", "where": "/old", "persist": False})
            run("mount")  # a bare mount uses the default and leaves it alone
            self.assertEqual(config.load()["mount"]["where"], "/old")

    def test_status_empty(self):
        rc, out, err = run("status")
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("id\tprofile\tmode"))

    def test_systemd_unit(self):
        st = self.state(where="/home/u/My Drive", persist=None)
        with mock.patch.object(mounts, "fuse_helper", lambda: "/usr/bin/fusermount3"):
            unit = persist.systemd_unit(st)
        self.assertIn('"/home/u/My Drive"', unit)
        self.assertIn("ExecStartPre=-", unit)
        self.assertIn("RCLONE_RC_PASS=", unit)

    def test_launchd_plist_no_keepalive(self):
        import plistlib
        pl = plistlib.loads(persist.launchd_plist(self.state()))
        self.assertNotIn("KeepAlive", pl)
        self.assertEqual(pl["ProgramArguments"][0], "/bin/sh")
        self.assertIn("umount -f", pl["ProgramArguments"][2])


class Setup(unittest.TestCase):
    def test_checksum_mismatch_installs_nothing(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("rclone-v9.9.9-osx-arm64/rclone", "#!/bin/sh\necho rclone v9.9.9\n")
        data = buf.getvalue()
        name = "rclone-v9.9.9-osx-arm64.zip"

        def sums(good):
            h = hashlib.sha256(data).hexdigest() if good else "0" * 64
            return lambda url, timeout=30: f"-----BEGIN PGP-----\n{h}  {name}\n"

        with mock.patch.object(rclone, "os_arch", lambda: ("osx", "arm64")), \
                mock.patch.object(http, "download", lambda url, dest, timeout=120: Path(dest).write_bytes(data)):
            with mock.patch.object(http, "get_text", sums(False)):
                with self.assertRaises(CliError):
                    rclone.install("v9.9.9")
                self.assertFalse(rclone.binary().exists())
            with mock.patch.object(http, "get_text", sums(True)):
                path = rclone.install("v9.9.9")
            self.assertTrue(os.access(path, os.X_OK))
        path.unlink()


if __name__ == "__main__":
    unittest.main()
